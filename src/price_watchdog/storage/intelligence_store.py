"""Persistência de dados de inteligência competitiva no Aurora PostgreSQL."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from price_watchdog.database import get_session
from price_watchdog.models.intelligence_entities import (
    CompetitorIntelligenceRecord,
)

logger = logging.getLogger(__name__)

# Configuração de retry com backoff exponencial (em segundos)
_RETRY_DELAYS = [1, 2, 4]


class IntelligenceStore:
    """Persistência de dados de inteligência competitiva.

    Implementa semântica append-only: registros são apenas inseridos,
    nunca atualizados ou removidos, preservando histórico completo.
    """

    async def save_record(
        self, record: CompetitorIntelligenceRecord
    ) -> None:
        """Persiste um CompetitorIntelligenceRecord no banco.

        Realiza INSERT (append-only) com retry e backoff exponencial
        (1s, 2s, 4s) em caso de falha de persistência. Se todas as
        tentativas falharem, registra 'persistence_failed'.

        Args:
            record: Instância a ser persistida.
        """
        last_error: Exception | None = None

        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                async with get_session() as session:
                    session.add(record)
                logger.info(
                    "CompetitorIntelligenceRecord salvo: competitor_id=%s, "
                    "cycle_id=%s, status=%s",
                    record.competitor_id,
                    record.cycle_id,
                    record.extraction_status,
                )
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Falha ao persistir IntelligenceRecord (tentativa %d/%d): "
                    "competitor_id=%s, cycle_id=%s, erro=%s",
                    attempt,
                    len(_RETRY_DELAYS),
                    record.competitor_id,
                    record.cycle_id,
                    str(exc),
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(delay)

        # Todas as tentativas falharam
        logger.error(
            "persistence_failed: Todas as %d tentativas falharam para "
            "competitor_id=%s, cycle_id=%s. Último erro: %s",
            len(_RETRY_DELAYS),
            record.competitor_id,
            record.cycle_id,
            str(last_error),
        )

    async def get_previous_record(
        self, competitor_id: str
    ) -> CompetitorIntelligenceRecord | None:
        """Busca último registro de inteligência bem-sucedido.

        Retorna o registro mais recente onde
        extraction_status != 'failed', ordenado por
        extracted_at DESC, limitado a 1.

        Args:
            competitor_id: ID do concorrente.

        Returns:
            O último CompetitorIntelligenceRecord com sucesso,
            ou None se não houver registro anterior válido.
        """
        async with get_session() as session:
            stmt = (
                select(CompetitorIntelligenceRecord)
                .where(
                    CompetitorIntelligenceRecord.competitor_id
                    == competitor_id,
                    CompetitorIntelligenceRecord.extraction_status
                    != "failed",
                )
                .order_by(
                    CompetitorIntelligenceRecord.extracted_at.desc()
                )
                .limit(1)
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is not None:
                logger.info(
                    "Registro anterior encontrado para competitor_id=%s: "
                    "cycle_id=%s, status=%s",
                    competitor_id,
                    record.cycle_id,
                    record.extraction_status,
                )
            else:
                logger.info(
                    "Nenhum registro anterior para competitor_id=%s",
                    competitor_id,
                )
            return record

    async def get_records_for_cycle(
        self, cycle_id: str
    ) -> list[CompetitorIntelligenceRecord]:
        """Busca todos os registros de inteligência de um ciclo.

        Args:
            cycle_id: ID do ciclo de monitoramento.

        Returns:
            Lista de CompetitorIntelligenceRecords do ciclo.
        """
        async with get_session() as session:
            stmt = (
                select(CompetitorIntelligenceRecord)
                .where(CompetitorIntelligenceRecord.cycle_id == cycle_id)
                .order_by(CompetitorIntelligenceRecord.extracted_at)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(
                "Encontrados %d registros de inteligência para cycle_id=%s",
                len(records),
                cycle_id,
            )
            return records
