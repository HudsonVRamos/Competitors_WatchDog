"""Testes unitários para o módulo de registro de concorrentes."""

from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from price_watchdog.models.entities import Competitor, ProductConfig
from price_watchdog.registry.competitor_manager import (
    CompetitorManager,
    seed_initial_competitors,
)


def _make_mock_session(added_items, existing=None):
    """Cria mock de sessão e context manager para testes."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock(
        side_effect=lambda item: added_items.append(item)
    )
    mock_session.flush = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing
    mock_result.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(
        return_value=mock_result
    )

    @asynccontextmanager
    async def mock_get_session():
        yield mock_session

    return mock_get_session


class TestCompetitorManager:
    """Testes para a classe CompetitorManager."""

    def test_competitor_manager_instantiation(self):
        """CompetitorManager deve ser instanciável."""
        manager = CompetitorManager()
        assert manager is not None

    def test_competitor_manager_has_required_methods(self):
        """CompetitorManager deve ter todos os métodos necessários."""
        manager = CompetitorManager()
        assert hasattr(manager, "get_active_configs")
        assert hasattr(manager, "register_competitor")
        assert hasattr(manager, "register_product_config")
        assert hasattr(manager, "validate_config")
        assert hasattr(manager, "update_our_price")
        assert hasattr(manager, "get_success_rate")
        assert hasattr(manager, "seed_initial_competitors")

    def test_seed_function_exists(self):
        """Função seed_initial_competitors deve estar disponível."""
        assert callable(seed_initial_competitors)


class TestValidateConfig:
    """Testes para validate_config."""

    @pytest.mark.asyncio
    async def test_valid_css_selector_config(self):
        """Config com CSS selector válido deve passar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://example.com/price",
            extraction_strategy="css_selector",
            selector_or_pattern=".price-value",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_valid_regex_config(self):
        """Config com regex válido deve passar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://example.com",
            extraction_strategy="regex",
            selector_or_pattern=r"R\$\s*[\d.,]+",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_valid_ai_config(self):
        """Config com estratégia AI deve passar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://example.com",
            extraction_strategy="ai",
            selector_or_pattern="Encontre o preco",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is True
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_invalid_url_scheme(self):
        """URL sem http/https deve falhar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="ftp://example.com",
            extraction_strategy="css_selector",
            selector_or_pattern=".price",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is False
        assert any("http" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_url(self):
        """URL vazia deve falhar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="",
            extraction_strategy="css_selector",
            selector_or_pattern=".price",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is False
        assert any("page_url" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_empty_selector(self):
        """Selector vazio deve falhar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://example.com",
            extraction_strategy="css_selector",
            selector_or_pattern="",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is False
        assert any(
            "selector_or_pattern" in e for e in result.errors
        )

    @pytest.mark.asyncio
    async def test_invalid_regex_pattern(self):
        """Regex inválido deve falhar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://example.com",
            extraction_strategy="regex",
            selector_or_pattern="[invalid",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is False
        assert any("regex" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_url_without_domain(self):
        """URL sem domínio deve falhar."""
        manager = CompetitorManager()
        config = ProductConfig(
            page_url="https://",
            extraction_strategy="css_selector",
            selector_or_pattern=".price",
            product_name="Test",
        )
        result = await manager.validate_config(config)
        assert result.is_valid is False


class TestSeedInitialCompetitors:
    """Testes para seed_initial_competitors."""

    @pytest.mark.asyncio
    async def test_seed_creates_three_competitors(self):
        """Seed deve criar exatamente 3 concorrentes."""
        added_items = []
        mock_get_session = _make_mock_session(added_items)

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.seed_initial_competitors()

        competitors = [
            item
            for item in added_items
            if isinstance(item, Competitor)
        ]
        configs = [
            item
            for item in added_items
            if isinstance(item, ProductConfig)
        ]

        assert len(competitors) == 3
        assert len(configs) == 6

    @pytest.mark.asyncio
    async def test_seed_is_idempotent(self):
        """Seed não deve criar se concorrentes já existem."""
        added_items = []
        existing = MagicMock()
        existing.name = "Existente"
        mock_get_session = _make_mock_session(
            added_items, existing=existing
        )

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.seed_initial_competitors()

        assert len(added_items) == 0

    @pytest.mark.asyncio
    async def test_seed_competitor_names(self):
        """Seed deve criar concorrentes com nomes corretos."""
        added_items = []
        mock_get_session = _make_mock_session(added_items)

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.seed_initial_competitors()

        competitors = [
            item
            for item in added_items
            if isinstance(item, Competitor)
        ]
        names = {c.name for c in competitors}

        assert "HBO Max Brasil" in names
        assert "Claro TV+" in names
        assert "Vivo TV" in names

    @pytest.mark.asyncio
    async def test_seed_extraction_strategies(self):
        """Cada concorrente deve ter a estratégia correta."""
        added_items = []
        mock_get_session = _make_mock_session(added_items)

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.seed_initial_competitors()

        configs = [
            item
            for item in added_items
            if isinstance(item, ProductConfig)
        ]
        strategies = {c.extraction_strategy for c in configs}

        assert "ai" in strategies
        assert "css_selector" in strategies
        assert "regex" in strategies

    @pytest.mark.asyncio
    async def test_seed_convenience_function(self):
        """Função de conveniência deve chamar o método."""
        added_items = []
        mock_get_session = _make_mock_session(added_items)

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            await seed_initial_competitors()

        competitors = [
            item
            for item in added_items
            if isinstance(item, Competitor)
        ]
        assert len(competitors) == 3
