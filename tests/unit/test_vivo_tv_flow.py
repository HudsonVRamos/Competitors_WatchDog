"""Testes unitários para o fluxo Vivo TV (navegação de 3 tabs).

Valida:
- Navegação sequencial pelas 3 tabs
- Uso de wait_for_content_change() após cada clique
- Captura de screenshot independente por tab
- Tratamento de tab não encontrada (log warning e prosseguir)
- Tratamento de conteúdo sem mudança após 15s (log warning e prosseguir)
- Consolidação de planos sem duplicatas
- Extração de planos por tab
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from scraping_resilience.competitor_flows.vivo_tv import (
    CONTENT_CHANGE_SELECTORS,
    CONTENT_CHANGE_TIMEOUT_MS,
    VIVO_TV_TABS,
    VivoTVFlow,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_wait_manager() -> AsyncMock:
    """Cria mock do IntelligentWaitManager."""
    manager = AsyncMock()
    manager.wait_for_content_change = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_screenshotter() -> AsyncMock:
    """Cria mock do StepScreenshotter."""
    screenshotter = AsyncMock()
    screenshotter.capture = AsyncMock(
        return_value="comp/cycle/step_001_test.png"
    )
    return screenshotter


@pytest.fixture
def flow(mock_wait_manager, mock_screenshotter) -> VivoTVFlow:
    """Instância de VivoTVFlow com mocks."""
    return VivoTVFlow(
        wait_manager=mock_wait_manager,
        screenshotter=mock_screenshotter,
    )


def _make_tab_locator(count: int = 1) -> AsyncMock:
    """Cria um mock de locator para tabs com count especificado."""
    locator = AsyncMock()
    locator.count = AsyncMock(return_value=count)
    locator.first = AsyncMock()
    locator.first.click = AsyncMock()
    return locator


def _make_plan_locator(plans_text: list[str]) -> AsyncMock:
    """Cria mock de locator para cards de plano."""
    locator = AsyncMock()
    locator.count = AsyncMock(return_value=len(plans_text))

    elements = []
    for text in plans_text:
        elem = AsyncMock()
        elem.inner_text = AsyncMock(return_value=text)
        elements.append(elem)

    locator.nth = MagicMock(side_effect=lambda i: elements[i])
    return locator


def _make_page_mock(
    tab_found: bool = True,
    plan_texts: list[str] | None = None,
) -> AsyncMock:
    """Cria mock de Page do Playwright com comportamento configurável.

    Args:
        tab_found: Se True, get_by_text encontrará a tab.
        plan_texts: Textos dos cards de plano retornados pelo locator.
    """
    page = AsyncMock()

    # get_by_text para tabs
    tab_locator = _make_tab_locator(count=1 if tab_found else 0)
    page.get_by_text = MagicMock(return_value=tab_locator)

    # locator para cards de plano
    if plan_texts is None:
        plan_texts = ["Plano HD\nR$ 89,90\nAssinar"]

    plan_locator = _make_plan_locator(plan_texts)
    # Locators que não encontram nada
    empty_locator = AsyncMock()
    empty_locator.count = AsyncMock(return_value=0)

    def locator_factory(selector: str) -> AsyncMock:
        # Primeiro seletor com planos retorna dados
        if "[class*='plan']" in selector:
            return plan_locator
        return empty_locator

    page.locator = MagicMock(side_effect=locator_factory)

    return page


# ============================================================================
# Testes: Constantes
# ============================================================================


class TestConstants:
    """Testes para constantes do módulo."""

    def test_vivo_tv_tabs_has_3_entries(self):
        """Verifica que existem exatamente 3 tabs configuradas."""
        assert len(VIVO_TV_TABS) == 3

    def test_vivo_tv_tabs_content(self):
        """Verifica os nomes das 3 tabs."""
        assert VIVO_TV_TABS == [
            "TV Online",
            "TV por Assinatura",
            "Vivo Fibra + TV",
        ]

    def test_content_change_timeout_is_15_seconds(self):
        """Timeout para mudança de conteúdo é 15000ms (15s)."""
        assert CONTENT_CHANGE_TIMEOUT_MS == 15_000


# ============================================================================
# Testes: navigate_tabs
# ============================================================================


class TestNavigateTabs:
    """Testes para o método navigate_tabs()."""

    @pytest.mark.asyncio
    async def test_navigates_all_3_tabs_successfully(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Navega por todas as 3 tabs quando todas existem e mudam conteúdo."""
        page = _make_page_mock(
            tab_found=True,
            plan_texts=["Plano A\nR$ 50,00"],
        )

        await flow.navigate_tabs(page)

        # Deve ter chamado get_by_text para cada tab
        assert page.get_by_text.call_count == 3

        # Deve ter aguardado mudança de conteúdo 3 vezes
        wm = mock_wait_manager
        assert wm.wait_for_content_change.call_count == 3

        # Deve ter capturado 3 screenshots
        assert mock_screenshotter.capture.call_count == 3

    @pytest.mark.asyncio
    async def test_returns_consolidated_plans(self, flow, mock_wait_manager):
        """Retorna planos de todas as tabs consolidados."""
        # Configurar tabs com planos diferentes
        plan_texts_per_call = [
            ["Plano A\nR$ 50,00"],
            ["Plano B\nR$ 70,00"],
            ["Plano C\nR$ 90,00"],
        ]
        call_idx = {"idx": 0}

        page = AsyncMock()
        tab_locator = _make_tab_locator(count=1)
        page.get_by_text = MagicMock(return_value=tab_locator)

        def locator_side_effect(selector: str) -> AsyncMock:
            if "[class*='plan']" in selector:
                idx = call_idx["idx"]
                texts = plan_texts_per_call[
                    min(idx, len(plan_texts_per_call) - 1)
                ]
                call_idx["idx"] += 1
                return _make_plan_locator(texts)
            empty = AsyncMock()
            empty.count = AsyncMock(return_value=0)
            return empty

        page.locator = MagicMock(side_effect=locator_side_effect)

        result = await flow.navigate_tabs(page)

        # 3 planos únicos de 3 tabs
        assert len(result) == 3
        names = [p["name"] for p in result]
        assert "Plano A" in names
        assert "Plano B" in names
        assert "Plano C" in names

    @pytest.mark.asyncio
    async def test_deduplicates_plans_from_different_tabs(
        self, flow, mock_wait_manager
    ):
        """Remove duplicatas quando planos aparecem em múltiplas tabs."""
        page = _make_page_mock(
            tab_found=True,
            # Mesmo plano aparecerá em todas as tabs
            plan_texts=["Plano Duplicado\nR$ 50,00"],
        )

        result = await flow.navigate_tabs(page)

        # Plano duplicado deve aparecer apenas uma vez
        plan_names = [p["name"] for p in result]
        assert plan_names.count("Plano Duplicado") == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_tabs_found(
        self, flow, mock_wait_manager
    ):
        """Retorna lista vazia quando nenhuma tab é encontrada."""
        page = _make_page_mock(tab_found=False)

        result = await flow.navigate_tabs(page)

        assert result == []

    @pytest.mark.asyncio
    async def test_skips_tabs_without_content_change(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Pula tabs onde o conteúdo não mudou após timeout."""
        mock_wait_manager.wait_for_content_change = AsyncMock(
            return_value=False
        )
        page = _make_page_mock(tab_found=True)

        result = await flow.navigate_tabs(page)

        # Sem mudança de conteúdo, não captura screenshots nem extrai planos
        mock_screenshotter.capture.assert_not_called()
        assert result == []


# ============================================================================
# Testes: _process_tab
# ============================================================================


class TestProcessTab:
    """Testes para o método _process_tab()."""

    @pytest.mark.asyncio
    async def test_clicks_tab(self, flow, mock_wait_manager):
        """Clica na tab encontrada."""
        page = _make_page_mock(tab_found=True)

        await flow._process_tab(page, "TV Online")

        tab_locator = page.get_by_text.return_value
        tab_locator.first.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_waits_for_content_change_after_click(
        self, flow, mock_wait_manager
    ):
        """Aguarda mudança de conteúdo após clicar na tab."""
        page = _make_page_mock(tab_found=True)

        await flow._process_tab(page, "TV Online")

        mock_wait_manager.wait_for_content_change.assert_called_once_with(
            page,
            CONTENT_CHANGE_SELECTORS,
            timeout_ms=CONTENT_CHANGE_TIMEOUT_MS,
        )

    @pytest.mark.asyncio
    async def test_captures_screenshot_after_content_change(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Captura screenshot após conteúdo mudar."""
        page = _make_page_mock(tab_found=True)

        await flow._process_tab(page, "TV Online")

        mock_screenshotter.capture.assert_called_once_with(
            page, "tab_TV Online"
        )

    @pytest.mark.asyncio
    async def test_returns_empty_when_tab_not_found(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Retorna lista vazia e não clica quando tab não encontrada."""
        page = _make_page_mock(tab_found=False)

        result = await flow._process_tab(page, "TV Online")

        assert result == []
        tab_locator = page.get_by_text.return_value
        tab_locator.first.click.assert_not_called()
        mock_wait_manager.wait_for_content_change.assert_not_called()
        mock_screenshotter.capture.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_content_doesnt_change(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Retorna lista vazia quando conteúdo não muda após 15s."""
        mock_wait_manager.wait_for_content_change = AsyncMock(
            return_value=False
        )
        page = _make_page_mock(tab_found=True)

        result = await flow._process_tab(page, "TV por Assinatura")

        assert result == []
        mock_screenshotter.capture.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(
        self, flow, mock_wait_manager, mock_screenshotter
    ):
        """Captura exceções sem propagar e retorna lista vazia."""
        page = _make_page_mock(tab_found=True)
        # Forçar exceção no clique
        tab_locator = page.get_by_text.return_value
        tab_locator.first.click = AsyncMock(
            side_effect=RuntimeError("Elemento destacou do DOM")
        )

        result = await flow._process_tab(page, "TV Online")

        assert result == []

    @pytest.mark.asyncio
    async def test_extracts_plans_after_content_change(
        self, flow, mock_wait_manager
    ):
        """Extrai planos da tab após conteúdo mudar com sucesso."""
        page = _make_page_mock(
            tab_found=True,
            plan_texts=[
                "Plano HD\nR$ 89,90\nAssinar",
                "Plano Ultra\nR$ 129,90",
            ],
        )

        result = await flow._process_tab(page, "TV Online")

        assert len(result) == 2
        assert result[0]["name"] == "Plano HD"
        assert result[1]["name"] == "Plano Ultra"
        assert result[0]["tab"] == "TV Online"


# ============================================================================
# Testes: _extract_tab_plans
# ============================================================================


class TestExtractTabPlans:
    """Testes para o método _extract_tab_plans()."""

    @pytest.mark.asyncio
    async def test_extracts_plan_name_from_card_text(self, flow):
        """Extrai o nome do plano (primeira linha) do texto do card."""
        page = _make_page_mock(
            plan_texts=["Vivo Play Premium\nR$ 49,90/mês\nAssinar agora"],
        )

        result = await flow._extract_tab_plans(page, "TV Online")

        assert len(result) == 1
        assert result[0]["name"] == "Vivo Play Premium"
        assert result[0]["tab"] == "TV Online"

    @pytest.mark.asyncio
    async def test_extracts_multiple_plans(self, flow):
        """Extrai múltiplos planos de uma tab."""
        page = _make_page_mock(
            plan_texts=[
                "Plano Básico\nR$ 29,90",
                "Plano Plus\nR$ 49,90",
                "Plano Premium\nR$ 89,90",
            ],
        )

        result = await flow._extract_tab_plans(page, "TV por Assinatura")

        assert len(result) == 3
        names = [p["name"] for p in result]
        assert names == ["Plano Básico", "Plano Plus", "Plano Premium"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_plan_elements(self, flow):
        """Retorna lista vazia quando não encontra elementos de plano."""
        page = AsyncMock()
        # Todos os locators retornam count=0
        empty_locator = AsyncMock()
        empty_locator.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=empty_locator)

        result = await flow._extract_tab_plans(page, "TV Online")

        assert result == []

    @pytest.mark.asyncio
    async def test_includes_raw_text_in_plan(self, flow):
        """Inclui texto bruto do card nos dados do plano."""
        page = _make_page_mock(
            plan_texts=["Plano HD\nR$ 89,90\nAssinar"],
        )

        result = await flow._extract_tab_plans(page, "TV Online")

        assert "raw_text" in result[0]
        assert "R$ 89,90" in result[0]["raw_text"]

    @pytest.mark.asyncio
    async def test_skips_cards_with_extraction_error(self, flow):
        """Pula cards onde inner_text() falha sem interromper extração."""
        page = AsyncMock()

        # Locator com um elemento que falha e outro que funciona
        locator = AsyncMock()
        locator.count = AsyncMock(return_value=2)

        elem_ok = AsyncMock()
        elem_ok.inner_text = AsyncMock(return_value="Plano OK\nR$ 50,00")

        elem_fail = AsyncMock()
        elem_fail.inner_text = AsyncMock(side_effect=RuntimeError("Detached"))

        locator.nth = MagicMock(side_effect=lambda i: [elem_fail, elem_ok][i])

        empty_locator = AsyncMock()
        empty_locator.count = AsyncMock(return_value=0)

        page.locator = MagicMock(
            side_effect=lambda s: (
                locator if "[class*='plan']" in s else empty_locator
            )
        )

        result = await flow._extract_tab_plans(page, "TV Online")

        # Apenas o segundo card foi extraído
        assert len(result) == 1
        assert result[0]["name"] == "Plano OK"


# ============================================================================
# Testes: _extract_plan_name
# ============================================================================


class TestExtractPlanName:
    """Testes para o método _extract_plan_name()."""

    def test_returns_first_non_empty_line(self):
        """Retorna a primeira linha não-vazia como nome do plano."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        assert flow._extract_plan_name("Plano HD\nR$ 89,90") == "Plano HD"

    def test_strips_whitespace(self):
        """Remove espaços extras das linhas."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        result = flow._extract_plan_name("  Plano Ultra  \nR$ 50")
        assert result == "Plano Ultra"

    def test_returns_empty_for_empty_text(self):
        """Retorna string vazia para texto vazio."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        assert flow._extract_plan_name("") == ""

    def test_returns_empty_for_only_whitespace(self):
        """Retorna string vazia para texto apenas com espaços/newlines."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        assert flow._extract_plan_name("   \n   \n  ") == ""

    def test_handles_single_line(self):
        """Funciona com texto de uma linha só."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        assert flow._extract_plan_name("Plano Simples") == "Plano Simples"


# ============================================================================
# Testes: _deduplicate_plans
# ============================================================================


class TestDeduplicatePlans:
    """Testes para o método _deduplicate_plans()."""

    def test_removes_exact_duplicates(self):
        """Remove planos com nome idêntico."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "Plano A", "tab": "TV Online"},
            {"name": "Plano A", "tab": "TV por Assinatura"},
            {"name": "Plano B", "tab": "Vivo Fibra + TV"},
        ]

        result = flow._deduplicate_plans(plans)

        assert len(result) == 2
        names = [p["name"] for p in result]
        assert "Plano A" in names
        assert "Plano B" in names

    def test_case_insensitive_dedup(self):
        """Deduplicação é case-insensitive."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "Plano HD", "tab": "Tab1"},
            {"name": "plano hd", "tab": "Tab2"},
            {"name": "PLANO HD", "tab": "Tab3"},
        ]

        result = flow._deduplicate_plans(plans)

        assert len(result) == 1

    def test_preserves_first_occurrence(self):
        """Mantém a primeira ocorrência do plano duplicado."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "Plano A", "tab": "TV Online", "price": "R$ 50"},
            {"name": "Plano A", "tab": "TV por Assinatura", "price": "R$ 70"},
        ]

        result = flow._deduplicate_plans(plans)

        assert len(result) == 1
        assert result[0]["tab"] == "TV Online"
        assert result[0]["price"] == "R$ 50"

    def test_preserves_order(self):
        """Mantém a ordem original dos planos."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "Plano C", "tab": "Tab1"},
            {"name": "Plano A", "tab": "Tab1"},
            {"name": "Plano B", "tab": "Tab2"},
        ]

        result = flow._deduplicate_plans(plans)

        names = [p["name"] for p in result]
        assert names == ["Plano C", "Plano A", "Plano B"]

    def test_empty_list_returns_empty(self):
        """Lista vazia retorna lista vazia."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        assert flow._deduplicate_plans([]) == []

    def test_skips_plans_with_empty_name(self):
        """Planos com nome vazio são ignorados (não incluídos no resultado)."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "", "tab": "Tab1"},
            {"name": "Plano A", "tab": "Tab1"},
            {"name": "   ", "tab": "Tab2"},
        ]

        result = flow._deduplicate_plans(plans)

        assert len(result) == 1
        assert result[0]["name"] == "Plano A"

    def test_no_duplicates_all_unique(self):
        """Quando não há duplicatas, retorna todos os planos."""
        flow = VivoTVFlow(
            wait_manager=AsyncMock(), screenshotter=AsyncMock()
        )
        plans = [
            {"name": "Plano A", "tab": "Tab1"},
            {"name": "Plano B", "tab": "Tab2"},
            {"name": "Plano C", "tab": "Tab3"},
        ]

        result = flow._deduplicate_plans(plans)

        assert len(result) == 3
