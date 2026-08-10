"""Testes unitários para ComponentInteractionStrategy e estratégias concretas.

Valida o comportamento de can_handle() e interact() para cada estratégia
de interação com componentes customizados.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.scraping_resilience.component_interactor import (
    CustomComponentInteractor,
    KeyboardFallbackStrategy,
    MaterialUIStrategy,
    NativeSelectStrategy,
    ReactSelectStrategy,
    Select2Strategy,
)
from src.scraping_resilience.models import ComponentType, InteractionResult


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_page():
    """Fixture para mock de Page do Playwright."""
    page = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    # Mock do locator para MaterialUIStrategy
    locator_mock = MagicMock()
    filter_mock = MagicMock()
    first_mock = AsyncMock()
    first_mock.click = AsyncMock()
    filter_mock.first = first_mock
    locator_mock.filter = MagicMock(return_value=filter_mock)
    page.locator = MagicMock(return_value=locator_mock)
    return page


def _make_element_mock(
    tag_name: str = "div",
    class_name: str = "",
    ancestor_check: bool = False,
):
    """Cria mock de elemento com tag e classe configuráveis."""
    element = AsyncMock()

    async def eval_fn(script):
        if "tagName" in script:
            return tag_name
        # Scripts de verificação de ancestrais (contêm parentElement)
        if "parentElement" in script:
            return ancestor_check
        # Check simples de className (sem parentElement)
        if "className" in script:
            return class_name
        return ""

    element.evaluate = eval_fn
    element.click = AsyncMock()
    element.focus = AsyncMock()
    element.fill = AsyncMock()
    element.type = AsyncMock()
    return element


# ============================================================
# Testes NativeSelectStrategy
# ============================================================


class TestNativeSelectStrategyCanHandle:
    """Testes para NativeSelectStrategy.can_handle()."""

    async def test_retorna_true_para_tag_select(self, mock_page):
        """Deve retornar True quando o elemento é <select>."""
        element = _make_element_mock(tag_name="select")
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = NativeSelectStrategy()

        result = await strategy.can_handle(mock_page, "#city-select")

        assert result is True

    async def test_retorna_false_para_tag_div(self, mock_page):
        """Deve retornar False quando o elemento não é <select>."""
        element = _make_element_mock(tag_name="div")
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = NativeSelectStrategy()

        result = await strategy.can_handle(mock_page, "#city-dropdown")

        assert result is False

    async def test_retorna_false_para_tag_input(self, mock_page):
        """Deve retornar False para elementos input."""
        element = _make_element_mock(tag_name="input")
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = NativeSelectStrategy()

        result = await strategy.can_handle(mock_page, "#search")

        assert result is False

    async def test_retorna_false_quando_elemento_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar False quando o elemento não existe."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = NativeSelectStrategy()

        result = await strategy.can_handle(mock_page, "#inexistente")

        assert result is False

    async def test_retorna_false_em_timeout(self, mock_page):
        """Deve retornar False quando ocorre timeout."""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        strategy = NativeSelectStrategy()

        result = await strategy.can_handle(mock_page, "#slow-element")

        assert result is False


class TestNativeSelectStrategyInteract:
    """Testes para NativeSelectStrategy.interact()."""

    async def test_seleciona_por_label(self, mock_page):
        """Deve selecionar opção por label."""
        mock_page.select_option = AsyncMock()
        strategy = NativeSelectStrategy()

        result = await strategy.interact(
            mock_page, "#city-select", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "native_select"
        assert result.component_type == ComponentType.NATIVE_SELECT
        mock_page.select_option.assert_called_once_with(
            "#city-select", label="São Paulo"
        )

    async def test_fallback_para_value_quando_label_falha(self, mock_page):
        """Deve tentar selecionar por value quando label falha."""
        mock_page.select_option = AsyncMock(
            side_effect=[Exception("label não encontrada"), None]
        )
        strategy = NativeSelectStrategy()

        result = await strategy.interact(
            mock_page, "#city-select", "sp"
        )

        assert result.success is True
        assert result.strategy_used == "native_select"

    async def test_retorna_falha_quando_ambos_falham(self, mock_page):
        """Deve retornar erro quando label e value falham."""
        mock_page.select_option = AsyncMock(
            side_effect=Exception("Opção não encontrada")
        )
        strategy = NativeSelectStrategy()

        result = await strategy.interact(
            mock_page, "#city-select", "inexistente"
        )

        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "native_select"


# ============================================================
# Testes ReactSelectStrategy
# ============================================================


class TestReactSelectStrategyCanHandle:
    """Testes para ReactSelectStrategy.can_handle()."""

    async def test_retorna_true_para_classe_react_select(self, mock_page):
        """Deve retornar True quando classe contém 'react-select'."""
        element = _make_element_mock(class_name="react-select__control")
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = ReactSelectStrategy()

        result = await strategy.can_handle(mock_page, ".dropdown")

        assert result is True

    async def test_retorna_true_para_ancestral_react_select(
        self, mock_page
    ):
        """Deve retornar True quando ancestral tem classe react-select."""
        element = _make_element_mock(
            class_name="custom-input", ancestor_check=True
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = ReactSelectStrategy()

        result = await strategy.can_handle(mock_page, ".input-wrapper")

        assert result is True

    async def test_retorna_false_sem_classe_react_select(self, mock_page):
        """Deve retornar False quando não há classe react-select."""
        element = _make_element_mock(
            class_name="custom-dropdown", ancestor_check=False
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = ReactSelectStrategy()

        result = await strategy.can_handle(mock_page, ".dropdown")

        assert result is False

    async def test_retorna_false_quando_elemento_none(self, mock_page):
        """Deve retornar False quando elemento é None."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = ReactSelectStrategy()

        result = await strategy.can_handle(mock_page, "#react-dd")

        assert result is False

    async def test_retorna_false_em_timeout(self, mock_page):
        """Deve retornar False quando ocorre timeout."""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        strategy = ReactSelectStrategy()

        result = await strategy.can_handle(mock_page, "#slow")

        assert result is False


class TestReactSelectStrategyInteract:
    """Testes para ReactSelectStrategy.interact()."""

    async def test_interacao_bem_sucedida(self, mock_page):
        """Deve completar fluxo: click → type → select option."""
        element = AsyncMock()
        element.click = AsyncMock()
        input_el = AsyncMock()
        input_el.fill = AsyncMock()
        option = AsyncMock()
        option.click = AsyncMock()

        mock_page.wait_for_selector = AsyncMock(
            side_effect=[element, input_el, option]
        )
        strategy = ReactSelectStrategy()

        result = await strategy.interact(
            mock_page, ".react-select", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "react_select"
        assert result.component_type == ComponentType.REACT_SELECT

    async def test_retorna_falha_quando_controle_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar erro quando controle não é encontrado."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = ReactSelectStrategy()

        result = await strategy.interact(
            mock_page, ".react-select", "SP"
        )

        assert result.success is False
        assert result.error is not None


# ============================================================
# Testes MaterialUIStrategy
# ============================================================


class TestMaterialUIStrategyCanHandle:
    """Testes para MaterialUIStrategy.can_handle()."""

    async def test_retorna_true_para_classe_muiselect(self, mock_page):
        """Deve retornar True quando classe contém 'MuiSelect'."""
        element = _make_element_mock(class_name="MuiSelect-root")
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = MaterialUIStrategy()

        result = await strategy.can_handle(mock_page, ".select")

        assert result is True

    async def test_retorna_true_para_classe_muiautocomplete(
        self, mock_page
    ):
        """Deve retornar True quando classe contém 'MuiAutocomplete'."""
        element = _make_element_mock(
            class_name="MuiAutocomplete-root"
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = MaterialUIStrategy()

        result = await strategy.can_handle(mock_page, ".autocomplete")

        assert result is True

    async def test_retorna_true_para_ancestral_mui(self, mock_page):
        """Deve retornar True quando ancestral tem classe MUI."""
        element = _make_element_mock(
            class_name="inner-input", ancestor_check=True
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = MaterialUIStrategy()

        result = await strategy.can_handle(mock_page, ".input")

        assert result is True

    async def test_retorna_false_sem_classe_mui(self, mock_page):
        """Deve retornar False quando não há classe MUI."""
        element = _make_element_mock(
            class_name="custom-select", ancestor_check=False
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = MaterialUIStrategy()

        result = await strategy.can_handle(mock_page, ".select")

        assert result is False

    async def test_retorna_false_quando_elemento_none(self, mock_page):
        """Deve retornar False quando elemento é None."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = MaterialUIStrategy()

        result = await strategy.can_handle(mock_page, "#mui-dd")

        assert result is False


class TestMaterialUIStrategyInteract:
    """Testes para MaterialUIStrategy.interact()."""

    async def test_interacao_bem_sucedida(self, mock_page):
        """Deve completar fluxo: click → find menu item → click."""
        element = AsyncMock()
        element.click = AsyncMock()
        menu_item = AsyncMock()

        mock_page.wait_for_selector = AsyncMock(
            side_effect=[element, menu_item]
        )
        strategy = MaterialUIStrategy()

        result = await strategy.interact(
            mock_page, ".MuiSelect", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "material_ui"
        assert result.component_type == ComponentType.MATERIAL_UI

    async def test_retorna_falha_quando_elemento_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar erro quando elemento não é encontrado."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = MaterialUIStrategy()

        result = await strategy.interact(
            mock_page, ".MuiSelect", "SP"
        )

        assert result.success is False
        assert result.error is not None


# ============================================================
# Testes Select2Strategy
# ============================================================


class TestSelect2StrategyCanHandle:
    """Testes para Select2Strategy.can_handle()."""

    async def test_retorna_true_para_classe_select2(self, mock_page):
        """Deve retornar True quando classe contém 'select2'."""
        element = _make_element_mock(
            class_name="select2-container"
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = Select2Strategy()

        result = await strategy.can_handle(mock_page, ".dropdown")

        assert result is True

    async def test_retorna_true_para_ancestral_select2(self, mock_page):
        """Deve retornar True quando ancestral tem classe select2."""
        element = _make_element_mock(
            class_name="selection-input", ancestor_check=True
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = Select2Strategy()

        result = await strategy.can_handle(mock_page, ".input")

        assert result is True

    async def test_retorna_false_sem_classe_select2(self, mock_page):
        """Deve retornar False quando não há classe select2."""
        element = _make_element_mock(
            class_name="other-dropdown", ancestor_check=False
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = Select2Strategy()

        result = await strategy.can_handle(mock_page, ".dropdown")

        assert result is False

    async def test_retorna_false_quando_elemento_none(self, mock_page):
        """Deve retornar False quando elemento é None."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = Select2Strategy()

        result = await strategy.can_handle(mock_page, "#s2-dd")

        assert result is False

    async def test_retorna_false_em_timeout(self, mock_page):
        """Deve retornar False quando ocorre timeout."""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        strategy = Select2Strategy()

        result = await strategy.can_handle(mock_page, "#slow")

        assert result is False


class TestSelect2StrategyInteract:
    """Testes para Select2Strategy.interact()."""

    async def test_interacao_bem_sucedida(self, mock_page):
        """Deve completar fluxo: click → type → select result."""
        element = AsyncMock()
        element.click = AsyncMock()
        search_input = AsyncMock()
        search_input.fill = AsyncMock()
        result_item = AsyncMock()
        result_item.click = AsyncMock()

        mock_page.wait_for_selector = AsyncMock(
            side_effect=[element, search_input, result_item]
        )
        strategy = Select2Strategy()

        result = await strategy.interact(
            mock_page, ".select2", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "select2"
        assert result.component_type == ComponentType.SELECT2

    async def test_retorna_falha_quando_elemento_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar erro quando elemento não é encontrado."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = Select2Strategy()

        result = await strategy.interact(
            mock_page, ".select2", "SP"
        )

        assert result.success is False
        assert result.error is not None


# ============================================================
# Testes KeyboardFallbackStrategy
# ============================================================


class TestKeyboardFallbackStrategyCanHandle:
    """Testes para KeyboardFallbackStrategy.can_handle()."""

    async def test_sempre_retorna_true(self, mock_page):
        """Deve sempre retornar True (é o fallback universal)."""
        strategy = KeyboardFallbackStrategy()

        result = await strategy.can_handle(mock_page, "#qualquer")

        assert result is True

    async def test_retorna_true_para_qualquer_selector(self, mock_page):
        """Deve retornar True para qualquer selector."""
        strategy = KeyboardFallbackStrategy()

        assert await strategy.can_handle(mock_page, ".a") is True
        assert await strategy.can_handle(mock_page, "#b") is True
        assert await strategy.can_handle(mock_page, "div") is True
        assert await strategy.can_handle(mock_page, "") is True


class TestKeyboardFallbackStrategyInteract:
    """Testes para KeyboardFallbackStrategy.interact()."""

    async def test_interacao_bem_sucedida(self, mock_page):
        """Deve completar fluxo: focus → type → ArrowDown + Enter."""
        element = AsyncMock()
        element.focus = AsyncMock()
        element.fill = AsyncMock()
        element.type = AsyncMock()
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        strategy = KeyboardFallbackStrategy()

        result = await strategy.interact(
            mock_page, "#input", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "keyboard_fallback"
        assert result.component_type == ComponentType.UNKNOWN
        element.focus.assert_called_once()
        element.fill.assert_called_once_with("")
        element.type.assert_called_once_with("São Paulo", delay=50)
        mock_page.keyboard.press.assert_any_call("ArrowDown")
        mock_page.keyboard.press.assert_any_call("Enter")

    async def test_retorna_falha_quando_elemento_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar erro quando elemento não é encontrado."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        strategy = KeyboardFallbackStrategy()

        result = await strategy.interact(
            mock_page, "#input", "SP"
        )

        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "keyboard_fallback"

    async def test_retorna_falha_em_timeout(self, mock_page):
        """Deve retornar erro quando ocorre timeout."""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        strategy = KeyboardFallbackStrategy()

        result = await strategy.interact(
            mock_page, "#input", "SP"
        )

        assert result.success is False
        assert result.error is not None


# ============================================================
# Testes CustomComponentInteractor
# ============================================================


class TestCustomComponentInteractorDetect:
    """Testes para CustomComponentInteractor.detect_component_type()."""

    async def test_detecta_native_select(self, mock_page):
        """Deve detectar NATIVE_SELECT para tag <select>."""
        element = _make_element_mock(tag_name="select")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s, tag="select", role="", class_name=""
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#city"
        )

        assert result == ComponentType.NATIVE_SELECT

    async def test_detecta_combobox(self, mock_page):
        """Deve detectar COMBOBOX para role=combobox."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s, tag="div", role="combobox", class_name=""
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#combo"
        )

        assert result == ComponentType.COMBOBOX

    async def test_detecta_react_select(self, mock_page):
        """Deve detectar REACT_SELECT para classe react-select."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s,
                tag="div",
                role="",
                class_name="react-select__control",
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#rs"
        )

        assert result == ComponentType.REACT_SELECT

    async def test_detecta_material_ui_select(self, mock_page):
        """Deve detectar MATERIAL_UI para classe MuiSelect."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s,
                tag="div",
                role="",
                class_name="MuiSelect-root",
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#mui"
        )

        assert result == ComponentType.MATERIAL_UI

    async def test_detecta_material_ui_autocomplete(self, mock_page):
        """Deve detectar MATERIAL_UI para classe MuiAutocomplete."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s,
                tag="div",
                role="",
                class_name="MuiAutocomplete-root",
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#mui-auto"
        )

        assert result == ComponentType.MATERIAL_UI

    async def test_detecta_select2(self, mock_page):
        """Deve detectar SELECT2 para classe select2."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s,
                tag="div",
                role="",
                class_name="select2-container",
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#s2"
        )

        assert result == ComponentType.SELECT2

    async def test_detecta_unknown_sem_padrao(self, mock_page):
        """Deve retornar UNKNOWN quando nenhum padrão reconhecido."""
        element = _make_element_mock(tag_name="div")
        element.evaluate = AsyncMock(
            side_effect=lambda s: _detect_eval(
                s,
                tag="div",
                role="",
                class_name="custom-component",
            )
        )
        mock_page.wait_for_selector = AsyncMock(return_value=element)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#custom"
        )

        assert result == ComponentType.UNKNOWN

    async def test_retorna_unknown_quando_elemento_none(self, mock_page):
        """Deve retornar UNKNOWN quando elemento não encontrado."""
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#nope"
        )

        assert result == ComponentType.UNKNOWN

    async def test_retorna_unknown_em_timeout(self, mock_page):
        """Deve retornar UNKNOWN quando ocorre timeout."""
        mock_page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("timeout")
        )
        interactor = CustomComponentInteractor()

        result = await interactor.detect_component_type(
            mock_page, "#slow"
        )

        assert result == ComponentType.UNKNOWN


class TestCustomComponentInteractorInteract:
    """Testes para CustomComponentInteractor.interact()."""

    async def test_para_na_primeira_estrategia_bem_sucedida(
        self, mock_page
    ):
        """Deve parar na primeira estratégia que tem sucesso."""
        interactor = CustomComponentInteractor()

        # Mock detect_component_type
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.NATIVE_SELECT
        )

        # Primeira estratégia pode lidar e tem sucesso
        strategy1 = AsyncMock()
        strategy1.can_handle = AsyncMock(return_value=True)
        strategy1.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
            )
        )

        # Segunda estratégia NÃO deve ser chamada
        strategy2 = AsyncMock()
        strategy2.can_handle = AsyncMock(return_value=True)
        strategy2.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
            )
        )

        interactor._strategies = [strategy1, strategy2]

        result = await interactor.interact(
            mock_page, "#dropdown", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "native_select"
        strategy1.can_handle.assert_called_once()
        strategy2.can_handle.assert_not_called()

    async def test_pula_estrategias_que_nao_podem_lidar(
        self, mock_page
    ):
        """Deve pular estratégias cujo can_handle retorna False."""
        interactor = CustomComponentInteractor()
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.REACT_SELECT
        )

        # Primeira não pode lidar
        strategy1 = AsyncMock()
        strategy1.can_handle = AsyncMock(return_value=False)
        strategy1.interact = AsyncMock()

        # Segunda pode lidar e tem sucesso
        strategy2 = AsyncMock()
        strategy2.can_handle = AsyncMock(return_value=True)
        strategy2.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
            )
        )

        interactor._strategies = [strategy1, strategy2]

        result = await interactor.interact(
            mock_page, "#rs-dropdown", "São Paulo"
        )

        assert result.success is True
        assert result.strategy_used == "react_select"
        strategy1.interact.assert_not_called()

    async def test_retorna_erro_quando_todas_falham(self, mock_page):
        """Deve retornar erro quando todas estratégias falham."""
        interactor = CustomComponentInteractor()
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.UNKNOWN
        )

        # Todas podem lidar mas falham
        strategy1 = AsyncMock()
        strategy1.can_handle = AsyncMock(return_value=True)
        strategy1.interact = AsyncMock(
            return_value=InteractionResult(
                success=False,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
                error="não encontrou opção",
            )
        )

        strategy2 = AsyncMock()
        strategy2.can_handle = AsyncMock(return_value=True)
        strategy2.interact = AsyncMock(
            return_value=InteractionResult(
                success=False,
                strategy_used="keyboard_fallback",
                component_type=ComponentType.UNKNOWN,
                error="timeout",
            )
        )

        interactor._strategies = [strategy1, strategy2]

        result = await interactor.interact(
            mock_page, "#broken", "São Paulo"
        )

        assert result.success is False
        assert result.error == "custom_dropdown_interaction_failed"
        assert result.strategy_used == "all"

    async def test_usa_fallback_value_quando_desired_falha(
        self, mock_page
    ):
        """Deve tentar fallback_value quando desired_value falha."""
        interactor = CustomComponentInteractor()
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.NATIVE_SELECT
        )

        call_count = 0

        async def mock_can_handle(page, selector):
            return True

        async def mock_interact(page, selector, value):
            nonlocal call_count
            call_count += 1
            # Falha na primeira tentativa (desired_value)
            # Sucesso na segunda (fallback_value)
            if value == "São Paulo":
                return InteractionResult(
                    success=False,
                    strategy_used="native_select",
                    component_type=ComponentType.NATIVE_SELECT,
                    error="não encontrou São Paulo",
                )
            return InteractionResult(
                success=True,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
            )

        strategy = AsyncMock()
        strategy.can_handle = mock_can_handle
        strategy.interact = mock_interact

        interactor._strategies = [strategy]

        result = await interactor.interact(
            mock_page,
            "#city",
            desired_value="São Paulo",
            fallback_value="Campinas",
        )

        assert result.success is True
        assert call_count == 2

    async def test_desired_value_padrao_sao_paulo(self, mock_page):
        """Deve usar 'São Paulo' como desired_value padrão."""
        interactor = CustomComponentInteractor()
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.NATIVE_SELECT
        )

        captured_value = None

        async def mock_can_handle(page, selector):
            return True

        async def mock_interact(page, selector, value):
            nonlocal captured_value
            captured_value = value
            return InteractionResult(
                success=True,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
            )

        strategy = AsyncMock()
        strategy.can_handle = mock_can_handle
        strategy.interact = mock_interact
        interactor._strategies = [strategy]

        await interactor.interact(mock_page, "#city")

        assert captured_value == "São Paulo"

    async def test_continua_proximo_quando_can_handle_lanca_excecao(
        self, mock_page
    ):
        """Deve continuar para próxima estratégia em exceção."""
        interactor = CustomComponentInteractor()
        interactor.detect_component_type = AsyncMock(
            return_value=ComponentType.UNKNOWN
        )

        # Primeira lança exceção
        strategy1 = AsyncMock()
        strategy1.can_handle = AsyncMock(
            side_effect=Exception("unexpected")
        )

        # Segunda funciona
        strategy2 = AsyncMock()
        strategy2.can_handle = AsyncMock(return_value=True)
        strategy2.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="keyboard_fallback",
                component_type=ComponentType.UNKNOWN,
            )
        )

        interactor._strategies = [strategy1, strategy2]

        result = await interactor.interact(
            mock_page, "#dropdown", "SP"
        )

        assert result.success is True
        assert result.strategy_used == "keyboard_fallback"


class TestCustomComponentInteractorValidate:
    """Testes para CustomComponentInteractor.validate_interaction()."""

    async def test_validacao_sucesso_valor_visivel_menu_fechado(
        self, mock_page
    ):
        """Deve retornar True quando valor visível e menu fechado."""
        mock_page.evaluate = AsyncMock(
            side_effect=[
                "Planos disponíveis em São Paulo - confira",
                False,  # menu fechado
            ]
        )
        interactor = CustomComponentInteractor()

        result = await interactor.validate_interaction(
            mock_page, "São Paulo"
        )

        assert result is True

    async def test_validacao_falha_valor_nao_encontrado(
        self, mock_page
    ):
        """Deve retornar False quando valor não está na página."""
        mock_page.evaluate = AsyncMock(
            return_value="Selecione uma cidade para continuar"
        )
        interactor = CustomComponentInteractor()

        result = await interactor.validate_interaction(
            mock_page, "São Paulo"
        )

        assert result is False

    async def test_validacao_falha_menu_aberto(self, mock_page):
        """Deve retornar False quando menu está aberto."""
        mock_page.evaluate = AsyncMock(
            side_effect=[
                "Planos em São Paulo",
                True,  # menu aberto
            ]
        )
        interactor = CustomComponentInteractor()

        result = await interactor.validate_interaction(
            mock_page, "São Paulo"
        )

        assert result is False

    async def test_validacao_case_insensitive(self, mock_page):
        """Deve fazer comparação case-insensitive."""
        mock_page.evaluate = AsyncMock(
            side_effect=[
                "Planos disponíveis em SÃO PAULO",
                False,
            ]
        )
        interactor = CustomComponentInteractor()

        result = await interactor.validate_interaction(
            mock_page, "são paulo"
        )

        assert result is True

    async def test_validacao_retorna_false_em_excecao(self, mock_page):
        """Deve retornar False quando ocorre exceção."""
        mock_page.evaluate = AsyncMock(
            side_effect=Exception("page crash")
        )
        interactor = CustomComponentInteractor()

        result = await interactor.validate_interaction(
            mock_page, "São Paulo"
        )

        assert result is False


# ============================================================
# Helper para detect_component_type tests
# ============================================================


def _detect_eval(script: str, tag: str, role: str, class_name: str):
    """Helper para simular evaluate no detect_component_type."""
    if "tagName" in script:
        return tag
    if "getAttribute('role')" in script or "getAttribute(\"role\")" in script:
        return role
    if "className" in script:
        return class_name
    return ""
