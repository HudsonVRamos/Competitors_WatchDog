"""Consolidador de ciclos de monitoramento de preços.

Responsável por aguardar a conclusão do processamento de todos os
PriceRecords de um ciclo e consolidar os resultados (contadores,
relatório Excel, envio de email).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import func, select

from price_watchdog.alerts.email_notifier import EmailNotifier
from price_watchdog.config import settings
from price_watchdog.database import get_session
from price_watchdog.models.entities import PriceCycle, PriceRecord
from price_watchdog.reports.excel_report import ExcelReportGenerator
from price_watchdog.storage.intelligence_store import IntelligenceStore
from price_watchdog.storage.price_store import PriceStore

logger = logging.getLogger(__name__)

# Logger dedicado para métricas de inteligência competitiva,
# separado do logger principal (que inclui métricas de preço).
intelligence_metrics_logger = logging.getLogger(
    "price_watchdog.metrics.intelligence"
)

# Timeout máximo de espera: 2 horas (em segundos)
_MAX_WAIT_SECONDS = 2 * 60 * 60


class CycleConsolidationTimeout(Exception):
    """Exceção quando o ciclo não completa dentro do tempo máximo."""

    pass


class CycleConsolidator:
    """Consolida resultados de um ciclo e gera relatórios."""

    def __init__(
        self,
        price_store: PriceStore,
        report_generator: ExcelReportGenerator,
        email_notifier: EmailNotifier,
        intelligence_store: IntelligenceStore | None = None,
    ) -> None:
        self._price_store = price_store
        self._report_generator = report_generator
        self._email_notifier = email_notifier
        self._intelligence_store = intelligence_store or IntelligenceStore()

    def log_cycle_intelligence_metrics(
        self,
        cycle_id: str,
        intelligence_records: list,
    ) -> dict:
        """Registra métricas de inteligência competitiva de forma estruturada.

        Calcula e loga métricas separadas das métricas de preço:
        - intelligence_extractions_success: extrações com sucesso
        - intelligence_extractions_failed: extrações com falha
        - intelligence_avg_latency_ms: latência média de extração
        - intelligence_total_retries: total de retries no ciclo

        As métricas são emitidas em formato JSON estruturado em um
        logger dedicado (price_watchdog.metrics.intelligence), garantindo
        separação das métricas de preço.

        Args:
            cycle_id: ID do ciclo sendo consolidado.
            intelligence_records: Lista de CompetitorIntelligenceRecord
                do ciclo.

        Returns:
            Dict com as métricas calculadas (útil para testes).
        """
        extractions_success = sum(
            1
            for r in intelligence_records
            if r.extraction_status in ("success", "no_packages_found")
        )
        extractions_failed = sum(
            1
            for r in intelligence_records
            if r.extraction_status == "failed"
        )

        # Calcular latência média apenas dos registros que possuem valor
        latencies = [
            r.extraction_latency_ms
            for r in intelligence_records
            if r.extraction_latency_ms is not None
        ]
        avg_latency_ms = (
            round(sum(latencies) / len(latencies), 2)
            if latencies
            else 0.0
        )

        # Somar total de retries do ciclo
        total_retries = sum(
            r.retry_count
            for r in intelligence_records
            if r.retry_count is not None
        )

        metrics = {
            "metric_type": "intelligence_cycle",
            "cycle_id": str(cycle_id),
            "intelligence_extractions_success": extractions_success,
            "intelligence_extractions_failed": extractions_failed,
            "intelligence_avg_latency_ms": avg_latency_ms,
            "intelligence_total_retries": total_retries,
        }

        intelligence_metrics_logger.info(
            "[INTELLIGENCE_METRICS] cycle=%s | %s",
            cycle_id,
            json.dumps(metrics, ensure_ascii=False),
        )

        return metrics

    async def wait_for_completion(
        self,
        cycle_id: str,
        poll_interval: int = 30,
    ) -> PriceCycle:
        """Polling periódico até todos os PriceRecords serem processados.

        Verifica a cada poll_interval segundos se a quantidade de
        PriceRecords do ciclo atingiu o total_products esperado.

        Args:
            cycle_id: ID do ciclo a monitorar.
            poll_interval: Intervalo em segundos entre cada checagem.

        Returns:
            PriceCycle atualizado quando todos os records são processados.

        Raises:
            CycleConsolidationTimeout: Se exceder o tempo máximo de espera.
        """
        elapsed = 0
        logger.info(
            "Aguardando conclusão do ciclo %s (poll_interval=%ds)",
            cycle_id,
            poll_interval,
        )

        while elapsed < _MAX_WAIT_SECONDS:
            async with get_session() as session:
                # Buscar o ciclo atual
                stmt = select(PriceCycle).where(
                    PriceCycle.id == cycle_id
                )
                result = await session.execute(stmt)
                cycle = result.scalar_one_or_none()

                if cycle is None:
                    raise ValueError(
                        f"Ciclo não encontrado: {cycle_id}"
                    )

                # Contar records processados
                count_stmt = (
                    select(func.count(PriceRecord.id))
                    .where(PriceRecord.cycle_id == cycle_id)
                )
                count_result = await session.execute(count_stmt)
                records_count = count_result.scalar() or 0

                logger.info(
                    "Ciclo %s: %d/%d records processados",
                    cycle_id,
                    records_count,
                    cycle.total_products,
                )

                if records_count >= cycle.total_products:
                    logger.info(
                        "Ciclo %s concluído: todos os %d records processados",
                        cycle_id,
                        records_count,
                    )
                    return cycle

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise CycleConsolidationTimeout(
            f"Ciclo {cycle_id} não concluiu em "
            f"{_MAX_WAIT_SECONDS // 3600}h"
        )

    async def consolidate(self, cycle: PriceCycle) -> None:
        """Gera relatório Excel e envia email de consolidação.

        Atualiza os contadores do ciclo (succeeded/failed),
        marca como concluído, gera relatório e envia por email.

        Args:
            cycle: PriceCycle a ser consolidado.
        """
        logger.info("Iniciando consolidação do ciclo %s", cycle.id)

        # Buscar todos os records do ciclo
        records = await self._price_store.get_cycle_records(
            str(cycle.id)
        )

        # Calcular contadores
        succeeded = sum(
            1
            for r in records
            if r.extraction_status == "success"
        )
        failed = sum(
            1
            for r in records
            if r.extraction_status in ("failed", "not_found")
        )

        # Calcular contadores de inteligência competitiva
        intelligence_records = (
            await self._intelligence_store.get_records_for_cycle(
                str(cycle.id)
            )
        )
        intelligence_attempted = len(intelligence_records)
        intelligence_succeeded = sum(
            1
            for r in intelligence_records
            if r.extraction_status in ("success", "no_packages_found")
        )
        intelligence_failed = sum(
            1
            for r in intelligence_records
            if r.extraction_status == "failed"
        )

        logger.info(
            "Ciclo %s inteligência: attempted=%d, succeeded=%d, failed=%d",
            cycle.id,
            intelligence_attempted,
            intelligence_succeeded,
            intelligence_failed,
        )

        # Registrar métricas estruturadas de inteligência (separadas de preço)
        self.log_cycle_intelligence_metrics(
            cycle_id=str(cycle.id),
            intelligence_records=intelligence_records,
        )

        # Atualizar ciclo no banco
        async with get_session() as session:
            stmt = select(PriceCycle).where(
                PriceCycle.id == cycle.id
            )
            result = await session.execute(stmt)
            db_cycle = result.scalar_one()

            db_cycle.products_succeeded = succeeded
            db_cycle.products_failed = failed
            db_cycle.intelligence_attempted = intelligence_attempted
            db_cycle.intelligence_succeeded = intelligence_succeeded
            db_cycle.intelligence_failed = intelligence_failed
            db_cycle.status = "completed"
            db_cycle.ended_at = datetime.utcnow()

            logger.info(
                "Ciclo %s atualizado: succeeded=%d, failed=%d, "
                "intel_attempted=%d, intel_succeeded=%d, intel_failed=%d",
                cycle.id,
                succeeded,
                failed,
                intelligence_attempted,
                intelligence_succeeded,
                intelligence_failed,
            )

        # Gerar relatório Excel
        report_bytes: bytes | None = None
        try:
            report_bytes = self._report_generator.generate(
                records, cycle, intelligence_records
            )
            logger.info(
                "Relatório Excel gerado para ciclo %s (%d bytes)",
                cycle.id,
                len(report_bytes),
            )
        except Exception:
            logger.error(
                "Falha ao gerar relatório Excel para ciclo %s",
                cycle.id,
                exc_info=True,
            )

        # Determinar se inteligência falhou para todos os concorrentes
        intelligence_all_failed = (
            intelligence_attempted > 0
            and not self._report_generator.has_successful_intelligence(
                intelligence_records
            )
        )

        # Enviar email com relatório
        recipients = settings.recipients_list
        if report_bytes and recipients:
            try:
                await self._email_notifier.send_report(
                    report_bytes=report_bytes,
                    cycle=cycle,
                    recipients=recipients,
                    intelligence_all_failed=intelligence_all_failed,
                )
                logger.info(
                    "Email de relatório enviado para %s", recipients
                )
            except Exception:
                logger.error(
                    "Falha ao enviar email de relatório para ciclo %s",
                    cycle.id,
                    exc_info=True,
                )
        elif not recipients:
            logger.warning(
                "Nenhum destinatário configurado para envio de relatório"
            )
