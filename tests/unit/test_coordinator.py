"""Testes unitários para o PriceMonitoringCoordinator."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.coordinator.coordinator import (
    PriceMonitoringCoordinator,
)
from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.models.entities import (
    Competitor,
    PriceCycle,
    ProductConfig,
)


def _make_config(index: int = 0) -> ProductConfig:
    """Cria um ProductConfig de teste com competitor associado."""
    competitor = Competitor(
        id=uuid.uuid4(),
        name=f"Competitor {index}",
        base_url=f"https://example-{index}.com",
        is_active=True,
    )
    config = ProductConfig(
        id=uuid.uuid4(),
        competitor_id=competitor.id,
        product_name=f"Product {index}",
        page_url=f"https://example-{index}.com/product",
        extraction_strategy="css_selector",
        selector_or_pattern=".price",
        our_price=99.90,
        currency="BRL",
        is_active=True,
    )
    config.competitor = competitor
    return config


@pytest.fixture
def mock_publisher():
    """Publisher mockado."""
    publisher = AsyncMock()
    publisher.publish_all = AsyncMock(return_value=5)
    return publisher


@pytest.fixture
def mock_consolidator():
    """CycleConsolidator mockado."""
    return MagicMock()


@pytest.fixture
def mock_price_store():
    """PriceStore mockado."""
    return AsyncMock()


@pytest.fixture
def mock_competitor_manager():
    """CompetitorManager mockado."""
    manager = AsyncMock()
    manager.get_active_configs = AsyncMock(return_value=[])
    return manager


@pytest.fixture
def coordinator(
    mock_publisher,
    mock_consolidator,
    mock_price_store,
    mock_competitor_manager,
):
    """Coordinator com todas as dependências mockadas."""
    return PriceMonitoringCoordinator(
        publisher=mock_publisher,
        consolidator=mock_consolidator,
        price_store=mock_price_store,
        competitor_manager=mock_competitor_manager,
    )


class TestRunCycle:
    """Testes para run_cycle."""

    @pytest.mark.asyncio
    async def test_cria_ciclo_com_status_running(
        self, coordinator, mock_competitor_manager
    ):
        """run_cycle deve criar um PriceCycle com status running."""
        mock_competitor_manager.get_active_configs.return_value = []

        with patch(
            "price_watchdog.coordinator.coordinator.get_session"
        ) as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()
            mock_session.execute = AsyncMock()

            # Simular o context manager de sessão
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = ctx

            # Mock para select do cycle na atualização
            mock_cycle = PriceCycle(
                id=uuid.uuid4(),
                started_at=datetime.utcnow(),
                status="running",
                total_products=0,
            )
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = mock_cycle
            mock_session.execute.return_value = mock_result

            result = await coordinator.run_cycle()

        assert result.status == "running"

    @pytest.mark.asyncio
    async def test_busca_configs_ativos(
        self, coordinator, mock_competitor_manager
    ):
        """run_cycle deve chamar get_active_configs."""
        configs = [_make_config(i) for i in range(3)]
        mock_competitor_manager.get_active_configs.return_value = (
            configs
        )

        with patch(
            "price_watchdog.coordinator.coordinator.get_session"
        ) as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = ctx

            mock_cycle = PriceCycle(
                id=uuid.uuid4(),
                started_at=datetime.utcnow(),
                status="running",
                total_products=0,
            )
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = mock_cycle
            mock_session.execute.return_value = mock_result

            await coordinator.run_cycle()

        mock_competitor_manager.get_active_configs.assert_called_once()

    @pytest.mark.asyncio
    async def test_publica_tarefas_via_publisher(
        self, coordinator, mock_publisher, mock_competitor_manager
    ):
        """run_cycle deve publicar mensagens via SQSPublisher."""
        configs = [_make_config(i) for i in range(5)]
        mock_competitor_manager.get_active_configs.return_value = (
            configs
        )
        mock_publisher.publish_all.return_value = 5

        with patch(
            "price_watchdog.coordinator.coordinator.get_session"
        ) as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = ctx

            mock_cycle = PriceCycle(
                id=uuid.uuid4(),
                started_at=datetime.utcnow(),
                status="running",
                total_products=0,
            )
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = mock_cycle
            mock_session.execute.return_value = mock_result

            await coordinator.run_cycle()

        mock_publisher.publish_all.assert_called_once()
        call_args = mock_publisher.publish_all.call_args
        messages = call_args[0][0]
        assert len(messages) == 5
        assert call_args[1]["batch_size"] == 10

    @pytest.mark.asyncio
    async def test_falha_publicacao_marca_ciclo_failed(
        self, coordinator, mock_publisher, mock_competitor_manager
    ):
        """Se publish_all falhar, o ciclo deve ser marcado failed."""
        configs = [_make_config(0)]
        mock_competitor_manager.get_active_configs.return_value = (
            configs
        )
        mock_publisher.publish_all.side_effect = RuntimeError(
            "SQS indisponível"
        )

        with patch(
            "price_watchdog.coordinator.coordinator.get_session"
        ) as mock_get_session:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_session)
            ctx.__aexit__ = AsyncMock(return_value=False)
            mock_get_session.return_value = ctx

            mock_cycle = PriceCycle(
                id=uuid.uuid4(),
                started_at=datetime.utcnow(),
                status="running",
                total_products=0,
            )
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = mock_cycle
            mock_session.execute.return_value = mock_result

            result = await coordinator.run_cycle()

        assert result.status == "failed"
        assert result.ended_at is not None


class TestPublishTasks:
    """Testes para _publish_tasks."""

    @pytest.mark.asyncio
    async def test_configs_vazios_retorna_zero(
        self, coordinator
    ):
        """Lista vazia de configs retorna 0."""
        cycle = PriceCycle(
            id=uuid.uuid4(),
            started_at=datetime.utcnow(),
            status="running",
        )

        result = await coordinator._publish_tasks(cycle, [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_converte_config_para_message(
        self, coordinator, mock_publisher
    ):
        """Cada ProductConfig deve ser convertido para PriceCheckMessage."""
        cycle = PriceCycle(
            id=uuid.uuid4(),
            started_at=datetime.utcnow(),
            status="running",
        )
        configs = [_make_config(0)]
        mock_publisher.publish_all.return_value = 1

        await coordinator._publish_tasks(cycle, configs)

        call_args = mock_publisher.publish_all.call_args
        messages = call_args[0][0]
        assert len(messages) == 1

        msg = messages[0]
        assert isinstance(msg, PriceCheckMessage)
        assert msg.product_config_id == str(configs[0].id)
        assert msg.competitor_id == str(configs[0].competitor_id)
        assert msg.competitor_name == "Competitor 0"
        assert msg.product_name == "Product 0"
        assert msg.page_url == "https://example-0.com/product"
        assert msg.extraction_strategy == "css_selector"
        assert msg.selector_or_pattern == ".price"
        assert msg.our_price == 99.90
        assert msg.cycle_id == str(cycle.id)

    @pytest.mark.asyncio
    async def test_publish_all_chamado_com_batch_10(
        self, coordinator, mock_publisher
    ):
        """publish_all deve ser chamado com batch_size=10."""
        cycle = PriceCycle(
            id=uuid.uuid4(),
            started_at=datetime.utcnow(),
            status="running",
        )
        configs = [_make_config(i) for i in range(15)]
        mock_publisher.publish_all.return_value = 15

        result = await coordinator._publish_tasks(cycle, configs)

        assert result == 15
        mock_publisher.publish_all.assert_called_once()
        call_kwargs = mock_publisher.publish_all.call_args[1]
        assert call_kwargs["batch_size"] == 10
