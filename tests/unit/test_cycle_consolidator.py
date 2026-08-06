"""Testes unitários para o CycleConsolidator."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.coordinator.cycle_consolidator import (
    CycleConsolidator,
    CycleConsolidationTimeout,
    _MAX_WAIT_SECONDS,
)
from price_watchdog.models.entities import PriceCycle, PriceRecord


def _make_cycle(
    total_products: int = 5, status: str = "running"
) -> PriceCycle:
    """Cria um PriceCycle para testes."""
    cycle = PriceCycle()
    cycle.id = uuid.uuid4()
    cycle.started_at = datetime(2024, 1, 15, 10, 0, 0)
    cycle.ended_at = None
    cycle.status = status
    cycle.total_products = total_products
    cycle.products_succeeded = 0
    cycle.products_failed = 0
    cycle.alerts_triggered = 0
    return cycle


def _make_record(
    cycle_id, status: str = "success"
) -> PriceRecord:
    """Cria um PriceRecord para testes."""
    record = PriceRecord()
    record.id = uuid.uuid4()
    record.cycle_id = cycle_id
    record.product_config_id = uuid.uuid4()
    record.competitor_id = uuid.uuid4()
    record.extraction_status = status
    record.our_price = 99.90
    record.extracted_price = 89.90 if status == "success" else None
    record.price_difference = -10.0 if status == "success" else None
    record.price_difference_pct = -10.0 if status == "success" else None
    record.extracted_at = datetime.utcnow()
    return record


@pytest.fixture
def consolidator():
    """Cria instância do CycleConsolidator com mocks."""
    price_store = AsyncMock()
    report_generator = MagicMock()
    email_notifier = AsyncMock()
    intelligence_store = AsyncMock()
    intelligence_store.get_records_for_cycle.return_value = []
    return CycleConsolidator(
        price_store=price_store,
        report_generator=report_generator,
        email_notifier=email_notifier,
        intelligence_store=intelligence_store,
    )


class TestConsolidate:
    """Testes para o método consolidate."""

    @pytest.mark.asyncio
    async def test_consolida_ciclo_com_sucesso(
        self, consolidator
    ):
        """Consolida ciclo atualizando contadores e enviando relatório."""
        cycle = _make_cycle(total_products=3)
        records = [
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "failed"),
        ]
        consolidator._price_store.get_cycle_records.return_value = (
            records
        )
        consolidator._report_generator.generate.return_value = (
            b"excel-bytes"
        )

        # Mock get_session para atualizar ciclo
        mock_cycle = _make_cycle(total_products=3)
        mock_cycle.id = cycle.id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_cycle
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".settings"
        ) as mock_settings:
            mock_settings.recipients_list = [
                "admin@example.com"
            ]
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            await consolidator.consolidate(cycle)

        # Verifica que relatório foi gerado
        consolidator._report_generator.generate.assert_called_once_with(
            records, cycle, []
        )
        # Verifica que email foi enviado
        consolidator._email_notifier.send_report.assert_called_once()
        call_kwargs = (
            consolidator._email_notifier.send_report.call_args
        )
        assert call_kwargs[1]["report_bytes"] == b"excel-bytes"
        assert call_kwargs[1]["recipients"] == [
            "admin@example.com"
        ]

    @pytest.mark.asyncio
    async def test_consolida_sem_destinatarios_nao_envia_email(
        self, consolidator
    ):
        """Se não há destinatários, não tenta enviar email."""
        cycle = _make_cycle(total_products=2)
        records = [
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "not_found"),
        ]
        consolidator._price_store.get_cycle_records.return_value = (
            records
        )
        consolidator._report_generator.generate.return_value = (
            b"excel-bytes"
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = _make_cycle(
            total_products=2
        )
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".settings"
        ) as mock_settings:
            mock_settings.recipients_list = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            await consolidator.consolidate(cycle)

        consolidator._email_notifier.send_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_falha_geracao_relatorio_nao_interrompe(
        self, consolidator
    ):
        """Falha na geração do relatório não impede consolidação."""
        cycle = _make_cycle(total_products=1)
        records = [_make_record(cycle.id, "success")]
        consolidator._price_store.get_cycle_records.return_value = (
            records
        )
        consolidator._report_generator.generate.side_effect = (
            RuntimeError("openpyxl error")
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = _make_cycle(
            total_products=1
        )
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".settings"
        ) as mock_settings:
            mock_settings.recipients_list = [
                "admin@example.com"
            ]
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            # Não deve lançar exceção
            await consolidator.consolidate(cycle)

        # Email não enviado porque relatório falhou
        consolidator._email_notifier.send_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_contadores_calculados_corretamente(
        self, consolidator
    ):
        """Verifica cálculo correto de succeeded e failed."""
        cycle = _make_cycle(total_products=5)
        records = [
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "failed"),
            _make_record(cycle.id, "not_found"),
        ]
        consolidator._price_store.get_cycle_records.return_value = (
            records
        )
        consolidator._report_generator.generate.return_value = (
            b"data"
        )

        mock_db_cycle = _make_cycle(total_products=5)
        mock_db_cycle.id = cycle.id
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_db_cycle
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".settings"
        ) as mock_settings:
            mock_settings.recipients_list = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            await consolidator.consolidate(cycle)

        # Verificar que contadores foram atualizados no ciclo do DB
        assert mock_db_cycle.products_succeeded == 3
        assert mock_db_cycle.products_failed == 2
        assert mock_db_cycle.status == "completed"
        assert mock_db_cycle.ended_at is not None

    @pytest.mark.asyncio
    async def test_contadores_inteligencia_calculados_corretamente(
        self, consolidator
    ):
        """Verifica cálculo correto dos contadores de inteligência."""
        cycle = _make_cycle(total_products=2)
        records = [
            _make_record(cycle.id, "success"),
            _make_record(cycle.id, "success"),
        ]
        consolidator._price_store.get_cycle_records.return_value = (
            records
        )
        consolidator._report_generator.generate.return_value = (
            b"data"
        )

        # Simular registros de inteligência com statuses variados
        intel_record_success = MagicMock()
        intel_record_success.extraction_status = "success"
        intel_record_success.extraction_latency_ms = 1000.0
        intel_record_success.retry_count = 0
        intel_record_no_pkg = MagicMock()
        intel_record_no_pkg.extraction_status = "no_packages_found"
        intel_record_no_pkg.extraction_latency_ms = 800.0
        intel_record_no_pkg.retry_count = 0
        intel_record_failed = MagicMock()
        intel_record_failed.extraction_status = "failed"
        intel_record_failed.extraction_latency_ms = 500.0
        intel_record_failed.retry_count = 2

        consolidator._intelligence_store.get_records_for_cycle.return_value = [
            intel_record_success,
            intel_record_no_pkg,
            intel_record_failed,
        ]

        mock_db_cycle = _make_cycle(total_products=2)
        mock_db_cycle.id = cycle.id
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_db_cycle
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".settings"
        ) as mock_settings:
            mock_settings.recipients_list = []
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            await consolidator.consolidate(cycle)

        # Verificar contadores de inteligência
        assert mock_db_cycle.intelligence_attempted == 3
        assert mock_db_cycle.intelligence_succeeded == 2  # success + no_packages_found
        assert mock_db_cycle.intelligence_failed == 1


class TestWaitForCompletion:
    """Testes para o método wait_for_completion."""

    @pytest.mark.asyncio
    async def test_retorna_ciclo_quando_completo(self):
        """Retorna ciclo imediatamente se já está completo."""
        cycle = _make_cycle(total_products=3)
        price_store = AsyncMock()
        consolidator = CycleConsolidator(
            price_store=price_store,
            report_generator=MagicMock(),
            email_notifier=AsyncMock(),
        )

        mock_session = AsyncMock()
        # Mock para query do ciclo
        mock_cycle_result = MagicMock()
        mock_cycle_result.scalar_one_or_none.return_value = cycle
        # Mock para count de records
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 3

        mock_session.execute = AsyncMock(
            side_effect=[mock_cycle_result, mock_count_result]
        )

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            result = await consolidator.wait_for_completion(
                str(cycle.id), poll_interval=1
            )

        assert result == cycle

    @pytest.mark.asyncio
    async def test_ciclo_nao_encontrado_raises(self):
        """Lança ValueError se ciclo não existe."""
        consolidator = CycleConsolidator(
            price_store=AsyncMock(),
            report_generator=MagicMock(),
            email_notifier=AsyncMock(),
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            with pytest.raises(ValueError, match="não encontrado"):
                await consolidator.wait_for_completion(
                    str(uuid.uuid4()), poll_interval=1
                )

    @pytest.mark.asyncio
    async def test_timeout_raises_exception(self):
        """Lança CycleConsolidationTimeout se exceder tempo máximo."""
        cycle = _make_cycle(total_products=10)
        consolidator = CycleConsolidator(
            price_store=AsyncMock(),
            report_generator=MagicMock(),
            email_notifier=AsyncMock(),
        )

        mock_session = AsyncMock()
        mock_cycle_result = MagicMock()
        mock_cycle_result.scalar_one_or_none.return_value = cycle
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2  # Nunca completa

        mock_session.execute = AsyncMock(
            side_effect=[mock_cycle_result, mock_count_result]
        )

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".get_session"
        ) as mock_get_session, patch(
            "price_watchdog.coordinator.cycle_consolidator"
            "._MAX_WAIT_SECONDS",
            1,
        ), patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
        ):
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__.return_value = mock_session
            mock_ctx.__aexit__.return_value = False
            mock_get_session.return_value = mock_ctx

            with pytest.raises(CycleConsolidationTimeout):
                await consolidator.wait_for_completion(
                    str(cycle.id), poll_interval=1
                )


class TestLogCycleIntelligenceMetrics:
    """Testes para o método log_cycle_intelligence_metrics."""

    def test_metricas_calculadas_corretamente(self, consolidator):
        """Verifica cálculo correto das métricas de inteligência."""
        # Simular registros com métricas variadas
        record_1 = MagicMock()
        record_1.extraction_status = "success"
        record_1.extraction_latency_ms = 1500.0
        record_1.retry_count = 1

        record_2 = MagicMock()
        record_2.extraction_status = "success"
        record_2.extraction_latency_ms = 2500.0
        record_2.retry_count = 0

        record_3 = MagicMock()
        record_3.extraction_status = "failed"
        record_3.extraction_latency_ms = 500.0
        record_3.retry_count = 3

        record_4 = MagicMock()
        record_4.extraction_status = "no_packages_found"
        record_4.extraction_latency_ms = 1000.0
        record_4.retry_count = 0

        records = [record_1, record_2, record_3, record_4]

        metrics = consolidator.log_cycle_intelligence_metrics(
            cycle_id="test-cycle-123",
            intelligence_records=records,
        )

        assert metrics["intelligence_extractions_success"] == 3  # success + no_packages_found
        assert metrics["intelligence_extractions_failed"] == 1
        assert metrics["intelligence_avg_latency_ms"] == 1375.0  # (1500+2500+500+1000)/4
        assert metrics["intelligence_total_retries"] == 4  # 1+0+3+0
        assert metrics["metric_type"] == "intelligence_cycle"
        assert metrics["cycle_id"] == "test-cycle-123"

    def test_metricas_com_lista_vazia(self, consolidator):
        """Retorna zeros quando não há registros de inteligência."""
        metrics = consolidator.log_cycle_intelligence_metrics(
            cycle_id="empty-cycle",
            intelligence_records=[],
        )

        assert metrics["intelligence_extractions_success"] == 0
        assert metrics["intelligence_extractions_failed"] == 0
        assert metrics["intelligence_avg_latency_ms"] == 0.0
        assert metrics["intelligence_total_retries"] == 0

    def test_metricas_com_latencia_null(self, consolidator):
        """Calcula latência média ignorando registros com latência null."""
        record_1 = MagicMock()
        record_1.extraction_status = "success"
        record_1.extraction_latency_ms = 2000.0
        record_1.retry_count = 0

        record_2 = MagicMock()
        record_2.extraction_status = "failed"
        record_2.extraction_latency_ms = None  # Sem latência (falha antes da chamada)
        record_2.retry_count = 0

        metrics = consolidator.log_cycle_intelligence_metrics(
            cycle_id="partial-cycle",
            intelligence_records=[record_1, record_2],
        )

        # Latência média só considera record_1 (2000.0)
        assert metrics["intelligence_avg_latency_ms"] == 2000.0
        assert metrics["intelligence_extractions_success"] == 1
        assert metrics["intelligence_extractions_failed"] == 1

    def test_metricas_logadas_no_logger_dedicado(self, consolidator):
        """Verifica que métricas são emitidas no logger de inteligência."""
        record = MagicMock()
        record.extraction_status = "success"
        record.extraction_latency_ms = 1000.0
        record.retry_count = 2

        with patch(
            "price_watchdog.coordinator.cycle_consolidator"
            ".intelligence_metrics_logger"
        ) as mock_logger:
            consolidator.log_cycle_intelligence_metrics(
                cycle_id="log-test-cycle",
                intelligence_records=[record],
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            # Verifica prefixo [INTELLIGENCE_METRICS]
            assert "[INTELLIGENCE_METRICS]" in call_args[0][0]
            # Verifica que cycle_id está nos args
            assert "log-test-cycle" in call_args[0][1]

    def test_metricas_com_retry_count_null(self, consolidator):
        """Trata retry_count null como 0."""
        record = MagicMock()
        record.extraction_status = "success"
        record.extraction_latency_ms = 1000.0
        record.retry_count = None

        metrics = consolidator.log_cycle_intelligence_metrics(
            cycle_id="null-retry-cycle",
            intelligence_records=[record],
        )

        assert metrics["intelligence_total_retries"] == 0
