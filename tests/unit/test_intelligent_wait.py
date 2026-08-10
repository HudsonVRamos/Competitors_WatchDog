"""Testes unitários para IntelligentWaitManager.

Valida o comportamento da cascata de espera inteligente e
detecção de mudança de conteúdo.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.scraping_resilience.intelligent_wait import IntelligentWaitManager
from src.scraping_resilience.models import WaitResult


@pytest.fixture
def wait_manager():
    """Fixture para IntelligentWaitManager."""
    return IntelligentWaitManager()


@pytest.fixture
def mock_page():
    """Fixture para mock de Page do Playwright."""
    page = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()

    # Configurar locator().first.inner_text()
    locator_mock = MagicMock()
    first_mock = AsyncMock()
    first_mock.inner_text = AsyncMock(return_value="conteúdo original")
    locator_mock.first = first_mock
    page.locator = MagicMock(return_value=locator_mock)

    return page


class TestWaitForPageReady:
    """Testes para wait_for_page_ready()."""

    async def test_networkidle_sucesso(self, wait_manager, mock_page):
        """Deve retornar sucesso via networkidle na primeira tentativa."""
        result = await wait_manager.wait_for_page_ready(mock_page)

        assert result.success is True
        assert result.strategy_used == "networkidle"
        assert result.elapsed_ms >= 0
        assert result.timeout_occurred is False
        mock_page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=30_000
        )

    async def test_fallback_para_selector_quando_networkidle_falha(
        self, wait_manager, mock_page
    ):
        """Quando networkidle falha, deve tentar waitForSelector."""
        mock_page.wait_for_load_state.side_effect = (
            PlaywrightTimeoutError("timeout")
        )

        result = await wait_manager.wait_for_page_ready(
            mock_page, critical_selectors=[".price-card"]
        )

        assert result.success is True
        assert result.strategy_used == "selector"
        assert result.timeout_occurred is False
        mock_page.wait_for_selector.assert_called_with(
            ".price-card", timeout=15_000
        )

    async def test_fallback_para_visible_quando_selector_falha(
        self, wait_manager, mock_page
    ):
        """Quando networkidle e selector falham, deve tentar toBeVisible."""
        mock_page.wait_for_load_state.side_effect = (
            PlaywrightTimeoutError("timeout")
        )
        mock_page.wait_for_selector.side_effect = (
            PlaywrightTimeoutError("timeout")
        )

        # Configurar expect/toBeVisible para sucesso
        locator_mock = MagicMock()
        first_mock = AsyncMock()
        locator_mock.first = first_mock
        mock_page.locator = MagicMock(return_value=locator_mock)

        with patch(
            "src.scraping_resilience.intelligent_wait.expect"
        ) as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock()
            result = await wait_manager.wait_for_page_ready(
                mock_page, critical_selectors=[".price-card"]
            )

        assert result.success is True
        assert result.strategy_used == "visible"
        assert result.timeout_occurred is False

    async def test_todas_estrategias_falham(
        self, wait_manager, mock_page
    ):
        """Quando todas as estratégias falham, retorna timeout."""
        mock_page.wait_for_load_state.side_effect = (
            PlaywrightTimeoutError("timeout")
        )
        mock_page.wait_for_selector.side_effect = (
            PlaywrightTimeoutError("timeout")
        )

        with patch(
            "src.scraping_resilience.intelligent_wait.expect"
        ) as mock_expect:
            mock_expect.return_value.to_be_visible = AsyncMock(
                side_effect=PlaywrightTimeoutError("timeout")
            )
            result = await wait_manager.wait_for_page_ready(
                mock_page, critical_selectors=[".price-card"]
            )

        assert result.success is False
        assert result.strategy_used == "none"
        assert result.timeout_occurred is True

    async def test_timeouts_customizados(self, wait_manager, mock_page):
        """Deve respeitar timeouts customizados."""
        await wait_manager.wait_for_page_ready(
            mock_page,
            network_idle_timeout_ms=10_000,
            selector_timeout_ms=5_000,
        )

        mock_page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=10_000
        )

    async def test_sem_critical_selectors_usa_body(
        self, wait_manager, mock_page
    ):
        """Sem seletores críticos, deve usar body como fallback."""
        mock_page.wait_for_load_state.side_effect = (
            PlaywrightTimeoutError("timeout")
        )

        result = await wait_manager.wait_for_page_ready(mock_page)

        assert result.success is True
        assert result.strategy_used == "selector"
        mock_page.wait_for_selector.assert_called_with(
            "body", timeout=15_000
        )

    async def test_multiplos_selectors_tenta_todos(
        self, wait_manager, mock_page
    ):
        """Com múltiplos seletores, tenta todos até achar um que funcione."""
        mock_page.wait_for_load_state.side_effect = (
            PlaywrightTimeoutError("timeout")
        )
        # Primeiro selector falha, segundo funciona
        mock_page.wait_for_selector.side_effect = [
            PlaywrightTimeoutError("timeout"),
            None,  # sucesso
        ]

        result = await wait_manager.wait_for_page_ready(
            mock_page, critical_selectors=[".tab1", ".tab2"]
        )

        assert result.success is True
        assert result.strategy_used == "selector"


class TestWaitForContentChange:
    """Testes para wait_for_content_change()."""

    async def test_conteudo_muda_retorna_true(
        self, wait_manager, mock_page
    ):
        """Quando conteúdo muda, deve retornar True."""
        result = await wait_manager.wait_for_content_change(
            mock_page, ".plans-container"
        )

        assert result is True
        mock_page.wait_for_function.assert_called_once()

    async def test_timeout_sem_mudanca_retorna_false(
        self, wait_manager, mock_page
    ):
        """Quando timeout expira sem mudança, deve retornar False."""
        mock_page.wait_for_function.side_effect = (
            PlaywrightTimeoutError("timeout")
        )

        result = await wait_manager.wait_for_content_change(
            mock_page, ".plans-container", timeout_ms=5_000
        )

        assert result is False

    async def test_referencia_nao_encontrada_usa_vazio(
        self, wait_manager, mock_page
    ):
        """Quando referência não existe, usa string vazia como base."""
        # inner_text lança exceção
        locator_mock = MagicMock()
        first_mock = AsyncMock()
        first_mock.inner_text = AsyncMock(
            side_effect=Exception("Element not found")
        )
        locator_mock.first = first_mock
        mock_page.locator = MagicMock(return_value=locator_mock)

        result = await wait_manager.wait_for_content_change(
            mock_page, ".non-existent"
        )

        # Deve funcionar normalmente usando "" como referência
        assert result is True
        # Verifica que wait_for_function foi chamado com conteúdo vazio
        call_args = mock_page.wait_for_function.call_args
        assert call_args[0][1] == [".non-existent", ""]

    async def test_timeout_customizado(self, wait_manager, mock_page):
        """Deve respeitar timeout customizado."""
        await wait_manager.wait_for_content_change(
            mock_page, ".plans", timeout_ms=10_000
        )

        call_args = mock_page.wait_for_function.call_args
        assert call_args[1]["timeout"] == 10_000
