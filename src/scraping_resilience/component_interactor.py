"""CustomComponentInteractor - Detecta e interage com componentes de UI não-nativos.

Utiliza Cascade Strategy (chain-of-responsibility) para interagir com
diferentes tipos de componentes customizados:

1. NativeSelectStrategy: click + option select para <select> nativos
2. ReactSelectStrategy: click + listbox navigation para React Select
3. MaterialUIStrategy: click + menu item selection para Material UI
4. Select2Strategy: input + dropdown selection para Select2
5. KeyboardFallbackStrategy: focus + digitação + Enter (fallback universal)

Detecta automaticamente o tipo de componente via atributos DOM.
"""

from __future__ import annotations

import logging
from typing import Protocol

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scraping_resilience.models import ComponentType, InteractionResult

logger = logging.getLogger(__name__)

# Timeout padrão para operações waitForSelector (5 segundos)
DEFAULT_TIMEOUT_MS = 5_000


class ComponentInteractionStrategy(Protocol):
    """Protocolo para estratégias de interação com componentes."""

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Verifica se esta estratégia pode lidar com o componente."""
        ...

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Executa a interação com o componente."""
        ...


class NativeSelectStrategy:
    """Estratégia para elementos <select> HTML nativos.

    Utiliza page.select_option() para selecionar opção por label ou value.
    """

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Verifica se o elemento é um <select> nativo."""
        try:
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                return False
            tag_name = await element.evaluate("el => el.tagName.toLowerCase()")
            return tag_name == "select"
        except (PlaywrightTimeoutError, Exception) as e:
            logger.debug(
                "NativeSelectStrategy.can_handle falhou para '%s': %s",
                selector,
                e,
            )
            return False

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Seleciona opção em <select> nativo via label ou value."""
        try:
            # Tenta selecionar por label primeiro
            try:
                await page.select_option(selector, label=value)
            except Exception:
                # Fallback para seleção por value
                await page.select_option(selector, value=value)

            logger.info(
                "NativeSelectStrategy: selecionou '%s' em '%s'.",
                value,
                selector,
            )
            return InteractionResult(
                success=True,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
            )
        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning(
                "NativeSelectStrategy.interact falhou para '%s': %s",
                selector,
                e,
            )
            return InteractionResult(
                success=False,
                strategy_used="native_select",
                component_type=ComponentType.NATIVE_SELECT,
                error=str(e),
            )


class ReactSelectStrategy:
    """Estratégia para componentes React Select.

    Detecta via classe CSS contendo "react-select".
    Interação: click no controle → digitar no input → click na opção.
    """

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Verifica se o componente tem classe 'react-select'."""
        try:
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                return False
            class_attr = await element.evaluate(
                "el => el.className || ''"
            )
            # Verifica o elemento e seus ancestrais próximos
            if "react-select" in class_attr:
                return True
            # Verifica se há container pai com react-select
            has_react_select = await element.evaluate(
                """el => {
                    let current = el;
                    for (let i = 0; i < 5; i++) {
                        if (current && current.className &&
                            current.className.includes('react-select')) {
                            return true;
                        }
                        current = current.parentElement;
                    }
                    return false;
                }"""
            )
            return has_react_select
        except (PlaywrightTimeoutError, Exception) as e:
            logger.debug(
                "ReactSelectStrategy.can_handle falhou para '%s': %s",
                selector,
                e,
            )
            return False

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Interage com React Select: click → type → select option."""
        try:
            # Click no controle para abrir o dropdown
            control = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if control is None:
                raise Exception(
                    f"Elemento não encontrado: {selector}"
                )
            await control.click()

            # Localizar e digitar no input interno
            input_el = await page.wait_for_selector(
                f"{selector} input, "
                f"{selector} [role='combobox']",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            if input_el:
                await input_el.fill(value)

            # Aguardar opção na listbox e clicar
            option_selector = (
                "[role='listbox'] [role='option'], "
                ".react-select__menu .react-select__option"
            )
            option = await page.wait_for_selector(
                option_selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if option:
                await option.click()

            logger.info(
                "ReactSelectStrategy: selecionou '%s' em '%s'.",
                value,
                selector,
            )
            return InteractionResult(
                success=True,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
            )
        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning(
                "ReactSelectStrategy.interact falhou para '%s': %s",
                selector,
                e,
            )
            return InteractionResult(
                success=False,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
                error=str(e),
            )


class MaterialUIStrategy:
    """Estratégia para componentes Material UI (MuiSelect/MuiAutocomplete).

    Detecta via classe CSS contendo "MuiSelect" ou "MuiAutocomplete".
    Interação: click para abrir menu → encontrar menu item → click.
    """

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Verifica se o componente tem classe MuiSelect ou MuiAutocomplete."""
        try:
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                return False
            class_attr = await element.evaluate(
                "el => el.className || ''"
            )
            if "MuiSelect" in class_attr:
                return True
            if "MuiAutocomplete" in class_attr:
                return True
            # Verifica ancestrais próximos
            has_mui = await element.evaluate(
                """el => {
                    let current = el;
                    for (let i = 0; i < 5; i++) {
                        if (current && current.className) {
                            if (current.className.includes('MuiSelect') ||
                                current.className.includes('MuiAutocomplete')) {
                                return true;
                            }
                        }
                        current = current.parentElement;
                    }
                    return false;
                }"""
            )
            return has_mui
        except (PlaywrightTimeoutError, Exception) as e:
            logger.debug(
                "MaterialUIStrategy.can_handle falhou para '%s': %s",
                selector,
                e,
            )
            return False

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Interage com Material UI: click → find menu item → click."""
        try:
            # Click no elemento para abrir o menu
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                raise Exception(
                    f"Elemento não encontrado: {selector}"
                )
            await element.click()

            # Aguardar menu item com o texto desejado
            menu_item_selector = (
                f"[role='listbox'] [role='option'], "
                f".MuiMenu-list .MuiMenuItem-root, "
                f"[role='listbox'] li"
            )
            await page.wait_for_selector(
                menu_item_selector, timeout=DEFAULT_TIMEOUT_MS
            )

            # Buscar item com texto correspondente
            item = page.locator(
                f"{menu_item_selector}"
            ).filter(has_text=value).first
            await item.click()

            logger.info(
                "MaterialUIStrategy: selecionou '%s' em '%s'.",
                value,
                selector,
            )
            return InteractionResult(
                success=True,
                strategy_used="material_ui",
                component_type=ComponentType.MATERIAL_UI,
            )
        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning(
                "MaterialUIStrategy.interact falhou para '%s': %s",
                selector,
                e,
            )
            return InteractionResult(
                success=False,
                strategy_used="material_ui",
                component_type=ComponentType.MATERIAL_UI,
                error=str(e),
            )


class Select2Strategy:
    """Estratégia para componentes Select2.

    Detecta via classe CSS contendo "select2".
    Interação: click para abrir → digitar no search input → selecionar.
    """

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Verifica se o componente tem classe 'select2'."""
        try:
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                return False
            class_attr = await element.evaluate(
                "el => el.className || ''"
            )
            if "select2" in class_attr:
                return True
            # Verifica ancestrais próximos
            has_select2 = await element.evaluate(
                """el => {
                    let current = el;
                    for (let i = 0; i < 5; i++) {
                        if (current && current.className &&
                            current.className.includes('select2')) {
                            return true;
                        }
                        current = current.parentElement;
                    }
                    return false;
                }"""
            )
            return has_select2
        except (PlaywrightTimeoutError, Exception) as e:
            logger.debug(
                "Select2Strategy.can_handle falhou para '%s': %s",
                selector,
                e,
            )
            return False

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Interage com Select2: click → type search → select result."""
        try:
            # Click no container para abrir o dropdown
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                raise Exception(
                    f"Elemento não encontrado: {selector}"
                )
            await element.click()

            # Localizar input de busca do Select2
            search_input = await page.wait_for_selector(
                ".select2-search__field, "
                ".select2-search input, "
                "input.select2-input",
                timeout=DEFAULT_TIMEOUT_MS,
            )
            if search_input:
                await search_input.fill(value)

            # Aguardar resultados e clicar no primeiro
            result_selector = (
                ".select2-results__option, "
                ".select2-result-selectable"
            )
            result = await page.wait_for_selector(
                result_selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if result:
                await result.click()

            logger.info(
                "Select2Strategy: selecionou '%s' em '%s'.",
                value,
                selector,
            )
            return InteractionResult(
                success=True,
                strategy_used="select2",
                component_type=ComponentType.SELECT2,
            )
        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning(
                "Select2Strategy.interact falhou para '%s': %s",
                selector,
                e,
            )
            return InteractionResult(
                success=False,
                strategy_used="select2",
                component_type=ComponentType.SELECT2,
                error=str(e),
            )


class KeyboardFallbackStrategy:
    """Estratégia de fallback universal via teclado.

    Funciona como último recurso quando nenhuma outra estratégia
    reconhece o componente.
    Interação: focus → digitar texto → ArrowDown + Enter.
    """

    async def can_handle(self, page: Page, selector: str) -> bool:
        """Sempre retorna True — esta é a estratégia de fallback."""
        return True

    async def interact(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Interage via teclado: focus → type → ArrowDown + Enter."""
        try:
            # Focar no elemento
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                raise Exception(
                    f"Elemento não encontrado: {selector}"
                )
            await element.focus()

            # Digitar o valor desejado
            await element.fill("")  # Limpar campo primeiro
            await element.type(value, delay=50)

            # Navegar com ArrowDown e confirmar com Enter
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")

            logger.info(
                "KeyboardFallbackStrategy: digitou '%s' e "
                "confirmou com Enter em '%s'.",
                value,
                selector,
            )
            return InteractionResult(
                success=True,
                strategy_used="keyboard_fallback",
                component_type=ComponentType.UNKNOWN,
            )
        except (PlaywrightTimeoutError, Exception) as e:
            logger.warning(
                "KeyboardFallbackStrategy.interact falhou para '%s': %s",
                selector,
                e,
            )
            return InteractionResult(
                success=False,
                strategy_used="keyboard_fallback",
                component_type=ComponentType.UNKNOWN,
                error=str(e),
            )


class CustomComponentInteractor:
    """Detecta e interage com componentes de UI não-nativos.

    Utiliza Cascade Strategy para tentar cada estratégia de interação
    em ordem até que a primeira tenha sucesso. Se todas falharem,
    retorna erro com razão "custom_dropdown_interaction_failed".
    """

    def __init__(self) -> None:
        self._strategies: list[ComponentInteractionStrategy] = [
            NativeSelectStrategy(),
            ReactSelectStrategy(),
            MaterialUIStrategy(),
            Select2Strategy(),
            KeyboardFallbackStrategy(),
        ]

    async def detect_component_type(
        self, page: Page, selector: str
    ) -> ComponentType:
        """Detecta tipo do componente via atributos DOM.

        Prioridade de detecção:
        1. Tag <select> → NATIVE_SELECT
        2. role="combobox" → COMBOBOX
        3. Classe contendo "react-select" → REACT_SELECT
        4. Classe contendo "MuiSelect" ou "MuiAutocomplete" → MATERIAL_UI
        5. Classe contendo "select2" → SELECT2
        6. Nenhum padrão reconhecido → UNKNOWN
        """
        try:
            element = await page.wait_for_selector(
                selector, timeout=DEFAULT_TIMEOUT_MS
            )
            if element is None:
                return ComponentType.UNKNOWN

            # Verificar tag <select> nativa
            tag_name = await element.evaluate(
                "el => el.tagName.toLowerCase()"
            )
            if tag_name == "select":
                return ComponentType.NATIVE_SELECT

            # Verificar role="combobox"
            role = await element.evaluate(
                "el => el.getAttribute('role') || ''"
            )
            if role == "combobox":
                return ComponentType.COMBOBOX

            # Verificar classes CSS indicativas
            class_attr = await element.evaluate(
                "el => el.className || ''"
            )

            if "react-select" in class_attr:
                return ComponentType.REACT_SELECT

            if "MuiSelect" in class_attr or \
               "MuiAutocomplete" in class_attr:
                return ComponentType.MATERIAL_UI

            if "select2" in class_attr:
                return ComponentType.SELECT2

            return ComponentType.UNKNOWN

        except (PlaywrightTimeoutError, Exception) as e:
            logger.debug(
                "detect_component_type falhou para '%s': %s",
                selector,
                e,
            )
            return ComponentType.UNKNOWN

    async def interact(
        self,
        page: Page,
        selector: str,
        desired_value: str = "São Paulo",
        fallback_value: str | None = None,
    ) -> InteractionResult:
        """Aplica Cascade Strategy para interagir com componente.

        Tenta cada estratégia em ordem. Para na primeira que:
        1. can_handle() retorna True
        2. interact() retorna success=True

        Se desired_value falhar e fallback_value está definido,
        tenta novamente com fallback_value.

        Se todas falham, retorna InteractionResult com
        error="custom_dropdown_interaction_failed".
        """
        component_type = await self.detect_component_type(
            page, selector
        )

        # Tenta com desired_value primeiro
        result = await self._try_strategies(
            page, selector, desired_value
        )
        if result.success:
            result.component_type = component_type
            return result

        # Se fallback_value definido, tenta com ele
        if fallback_value is not None:
            logger.info(
                "Valor '%s' não encontrado, tentando fallback '%s'.",
                desired_value,
                fallback_value,
            )
            result = await self._try_strategies(
                page, selector, fallback_value
            )
            if result.success:
                result.component_type = component_type
                return result

        # Todas as estratégias falharam
        logger.error(
            "Todas as estratégias falharam para '%s' com "
            "valor '%s'. Retornando erro.",
            selector,
            desired_value,
        )
        return InteractionResult(
            success=False,
            strategy_used="all",
            component_type=component_type,
            error="custom_dropdown_interaction_failed",
        )

    async def _try_strategies(
        self, page: Page, selector: str, value: str
    ) -> InteractionResult:
        """Tenta cada estratégia em ordem até sucesso.

        Retorna o resultado da primeira estratégia que pode lidar
        com o componente (can_handle=True) e interage com sucesso.
        """
        for strategy in self._strategies:
            try:
                can_handle = await strategy.can_handle(
                    page, selector
                )
                if not can_handle:
                    continue

                result = await strategy.interact(
                    page, selector, value
                )
                if result.success:
                    logger.info(
                        "Estratégia '%s' teve sucesso para '%s'.",
                        result.strategy_used,
                        selector,
                    )
                    return result

                logger.debug(
                    "Estratégia '%s' falhou para '%s': %s",
                    result.strategy_used,
                    selector,
                    result.error,
                )
            except Exception as e:
                logger.debug(
                    "Exceção em estratégia para '%s': %s",
                    selector,
                    e,
                )
                continue

        # Nenhuma estratégia teve sucesso
        return InteractionResult(
            success=False,
            strategy_used="none",
            component_type=ComponentType.UNKNOWN,
            error="no_strategy_succeeded",
        )

    async def validate_interaction(
        self, page: Page, expected_value: str
    ) -> bool:
        """Valida que a interação teve efeito.

        Verifica que:
        1. O valor esperado está visível na página
        2. O menu dropdown está fechado (nenhum listbox visível)
        3. O conteúdo da página reflete a seleção

        Returns:
            True se a validação passou, False caso contrário.
        """
        try:
            # Verificar se o valor esperado está visível na página
            page_text = await page.evaluate(
                "() => document.body.innerText || ''"
            )
            if expected_value.lower() not in page_text.lower():
                logger.warning(
                    "Valor '%s' não encontrado no texto da página.",
                    expected_value,
                )
                return False

            # Verificar se dropdown/menu está fechado
            # (nenhum listbox ou menu aberto visível)
            open_menu = await page.evaluate(
                """() => {
                    const listbox = document.querySelector(
                        '[role="listbox"]:not([aria-hidden="true"])'
                    );
                    const menu = document.querySelector(
                        '.react-select__menu, '
                        + '.MuiMenu-list, '
                        + '.select2-results'
                    );
                    return !!(listbox || menu);
                }"""
            )
            if open_menu:
                logger.warning(
                    "Menu dropdown ainda está aberto após interação."
                )
                return False

            return True

        except Exception as e:
            logger.warning(
                "Erro ao validar interação: %s", e
            )
            return False
