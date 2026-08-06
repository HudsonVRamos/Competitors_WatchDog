"""Testes unitários para o IntelligenceStore."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.storage.intelligence_store import (
    IntelligenceStore,
    _RETRY_DELAYS,
)
from price_watchdog.models.intelligence_entities import (
    CompetitorIntelligenceRecord,
)


@pytest.fixture
def store():
    """Cria instância do IntelligenceStore."""
    return IntelligenceStore()


@pytest.fixture
def sample_record():
    """Cria um CompetitorIntelligenceRecord de exemplo."""
    return CompetitorIntelligenceRecord(
        id=uuid.uuid4(),
        cycle_id=uuid.uuid4(),
        competitor_id=uuid.uuid4(),
        extraction_status="success",
        failure_reason=None,
        commercial_keywords=["oferta", "fibra", "streaming"],
        home_banner_description="Banner de teste",
        commercial_positioning_summary="Resumo teste",
        extraction_latency_ms=1500.0,
        retry_count=0,
        extracted_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )


def _mock_session_ok():
    """Cria mock de sessão que funciona sem erro."""
    session = AsyncMock()
    session.add = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_session_error(error):
    """Cria mock de sessão que levanta erro."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(side_effect=error)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestSaveRecord:
    """Testes para save_record."""

    @pytest.mark.asyncio
    async def test_save_success_on_first_attempt(
        self, store, sample_record
    ):
        """save_record persiste na primeira tentativa."""
        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=_mock_session_ok(),
        ):
            # Não deve levantar exceção
            await store.save_record(sample_record)

    @pytest.mark.asyncio
    async def test_save_uses_session_add(
        self, store, sample_record
    ):
        """save_record chama session.add com o record."""
        mock_ctx = _mock_session_ok()
        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            await store.save_record(sample_record)

        mock_session = await mock_ctx.__aenter__()
        mock_session.add.assert_called_once_with(sample_record)

    @pytest.mark.asyncio
    async def test_save_retries_on_failure(
        self, store, sample_record
    ):
        """save_record retenta em caso de falha."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("DB connection lost")
            # Terceira tentativa: sucesso
            session = MagicMock()
            session.add = MagicMock()
            return session

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = side_effect
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ), patch(
            "price_watchdog.storage.intelligence_store.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await store.save_record(sample_record)

        # Deve ter dormido entre tentativas
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    @pytest.mark.asyncio
    async def test_save_all_retries_fail_logs_error(
        self, store, sample_record
    ):
        """save_record loga persistence_failed quando tudo falha."""
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(
            side_effect=ConnectionError("DB down")
        )
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ), patch(
            "price_watchdog.storage.intelligence_store.asyncio.sleep",
            new_callable=AsyncMock,
        ), patch(
            "price_watchdog.storage.intelligence_store.logger"
        ) as mock_logger:
            await store.save_record(sample_record)

        # Verifica que logou erro persistence_failed
        mock_logger.error.assert_called_once()
        error_msg = mock_logger.error.call_args[0][0]
        assert "persistence_failed" in error_msg

    @pytest.mark.asyncio
    async def test_save_retry_delays_match_config(
        self, store, sample_record
    ):
        """Os delays de retry devem ser 1s, 2s, 4s."""
        assert _RETRY_DELAYS == [1, 2, 4]

    @pytest.mark.asyncio
    async def test_save_does_not_update_existing(
        self, store, sample_record
    ):
        """save_record usa INSERT (add), nunca merge/update."""
        mock_ctx = _mock_session_ok()
        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            await store.save_record(sample_record)

        mock_session = await mock_ctx.__aenter__()
        # Garante append-only: usa add, não merge
        mock_session.add.assert_called_once()
        assert not hasattr(mock_session, "merge") or \
            not mock_session.merge.called


class TestGetPreviousRecord:
    """Testes para get_previous_record."""

    @pytest.mark.asyncio
    async def test_returns_record_when_found(self, store):
        """Retorna registro quando existe."""
        mock_record = MagicMock(
            spec=CompetitorIntelligenceRecord
        )
        mock_record.cycle_id = uuid.uuid4()
        mock_record.extraction_status = "success"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            result = await store.get_previous_record("comp-123")

        assert result == mock_record

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, store):
        """Retorna None quando não há registro anterior."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            result = await store.get_previous_record("comp-999")

        assert result is None


class TestGetRecordsForCycle:
    """Testes para get_records_for_cycle."""

    @pytest.mark.asyncio
    async def test_returns_list_of_records(self, store):
        """Retorna lista de registros para o ciclo."""
        mock_records = [
            MagicMock(spec=CompetitorIntelligenceRecord),
            MagicMock(spec=CompetitorIntelligenceRecord),
        ]

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_records

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            result = await store.get_records_for_cycle("cycle-001")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_records(self, store):
        """Retorna lista vazia se não há registros no ciclo."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "price_watchdog.storage.intelligence_store.get_session",
            return_value=mock_ctx,
        ):
            result = await store.get_records_for_cycle("cycle-empty")

        assert result == []
