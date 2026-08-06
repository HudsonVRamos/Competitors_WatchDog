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


class TestValidateIntelligenceUrl:
    """Testes para validate_intelligence_url."""

    def test_valid_https_url(self):
        """URL https válida deve retornar True."""
        assert CompetitorManager.validate_intelligence_url(
            "https://www.example.com/page"
        ) is True

    def test_valid_http_url(self):
        """URL http válida deve retornar True."""
        assert CompetitorManager.validate_intelligence_url(
            "http://example.com"
        ) is True

    def test_valid_localhost(self):
        """URL com localhost deve retornar True."""
        assert CompetitorManager.validate_intelligence_url(
            "http://localhost:8080/path"
        ) is True

    def test_none_returns_false(self):
        """None deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            None
        ) is False

    def test_empty_string_returns_false(self):
        """String vazia deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            ""
        ) is False

    def test_ftp_scheme_returns_false(self):
        """Esquema ftp deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            "ftp://example.com/file"
        ) is False

    def test_file_scheme_returns_false(self):
        """Esquema file deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            "file:///etc/passwd"
        ) is False

    def test_javascript_scheme_returns_false(self):
        """Esquema javascript deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            "javascript:alert(1)"
        ) is False

    def test_no_domain_returns_false(self):
        """URL sem domínio (https://) deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            "https://"
        ) is False

    def test_max_length_2048(self):
        """URL com exatamente 2048 caracteres deve ser aceita."""
        base = "https://example.com/"
        url = base + "a" * (2048 - len(base))
        assert len(url) == 2048
        assert CompetitorManager.validate_intelligence_url(
            url
        ) is True

    def test_exceeds_2048_chars_returns_false(self):
        """URL com mais de 2048 caracteres deve retornar False."""
        base = "https://example.com/"
        url = base + "a" * (2049 - len(base))
        assert len(url) == 2049
        assert CompetitorManager.validate_intelligence_url(
            url
        ) is False

    def test_domain_without_dot_returns_false(self):
        """Domínio sem ponto (não-localhost) deve retornar False."""
        assert CompetitorManager.validate_intelligence_url(
            "https://intranet/page"
        ) is False

    def test_url_with_port(self):
        """URL com porta deve ser aceita."""
        assert CompetitorManager.validate_intelligence_url(
            "https://example.com:8443/path"
        ) is True

    def test_url_with_query_params(self):
        """URL com query params deve ser aceita."""
        assert CompetitorManager.validate_intelligence_url(
            "https://example.com/page?q=test&lang=pt"
        ) is True

    def test_url_with_fragment(self):
        """URL com fragment deve ser aceita."""
        assert CompetitorManager.validate_intelligence_url(
            "https://example.com/page#section"
        ) is True


class TestEnableIntelligence:
    """Testes para enable_intelligence."""

    @pytest.mark.asyncio
    async def test_enable_with_valid_url(self):
        """Deve habilitar inteligência e salvar URL válida."""
        added_items = []
        competitor = MagicMock(spec=Competitor)
        competitor.id = "test-id"
        competitor.intelligence_enabled = False
        competitor.intelligence_home_url = None

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = competitor
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.enable_intelligence(
                "test-id", home_url="https://example.com"
            )

        assert competitor.intelligence_enabled is True
        assert (
            competitor.intelligence_home_url
            == "https://example.com"
        )

    @pytest.mark.asyncio
    async def test_enable_without_url_keeps_existing(self):
        """Deve habilitar sem alterar URL existente."""
        competitor = MagicMock(spec=Competitor)
        competitor.id = "test-id"
        competitor.intelligence_enabled = False
        competitor.intelligence_home_url = (
            "https://existing.com"
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = competitor
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.enable_intelligence("test-id")

        assert competitor.intelligence_enabled is True
        assert (
            competitor.intelligence_home_url
            == "https://existing.com"
        )

    @pytest.mark.asyncio
    async def test_enable_with_invalid_url_raises(self):
        """Deve levantar ValueError para URL inválida."""
        manager = CompetitorManager()

        with pytest.raises(ValueError, match="URL de inteligência inválida"):
            await manager.enable_intelligence(
                "test-id", home_url="ftp://invalid.com"
            )

    @pytest.mark.asyncio
    async def test_enable_competitor_not_found_raises(self):
        """Deve levantar ValueError se concorrente não existir."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            with pytest.raises(
                ValueError, match="Concorrente não encontrado"
            ):
                await manager.enable_intelligence("nonexistent")


class TestDisableIntelligence:
    """Testes para disable_intelligence."""

    @pytest.mark.asyncio
    async def test_disable_sets_flag_false(self):
        """Deve desabilitar flag de inteligência."""
        competitor = MagicMock(spec=Competitor)
        competitor.id = "test-id"
        competitor.intelligence_enabled = True
        competitor.intelligence_home_url = (
            "https://example.com"
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = competitor
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.disable_intelligence("test-id")

        assert competitor.intelligence_enabled is False

    @pytest.mark.asyncio
    async def test_disable_preserves_home_url(self):
        """Desabilitar NÃO deve remover intelligence_home_url."""
        competitor = MagicMock(spec=Competitor)
        competitor.id = "test-id"
        competitor.intelligence_enabled = True
        competitor.intelligence_home_url = (
            "https://example.com/home"
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = competitor
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            await manager.disable_intelligence("test-id")

        # URL deve ser preservada
        assert (
            competitor.intelligence_home_url
            == "https://example.com/home"
        )

    @pytest.mark.asyncio
    async def test_disable_competitor_not_found_raises(self):
        """Deve levantar ValueError se concorrente não existir."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(
            return_value=mock_result
        )

        @asynccontextmanager
        async def mock_get_session():
            yield mock_session

        with patch(
            "price_watchdog.registry.competitor_manager"
            ".get_session",
            mock_get_session,
        ):
            manager = CompetitorManager()
            with pytest.raises(
                ValueError, match="Concorrente não encontrado"
            ):
                await manager.disable_intelligence("nonexistent")


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
