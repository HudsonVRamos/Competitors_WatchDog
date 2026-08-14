"""Fluxo específico para Globoplay — espera cards de plano renderizarem.

O Globoplay é uma SPA pesada que renderiza os cards de preço via JavaScript.
O conteúdo pode demorar 5-10s para aparecer. Este flow:
1. Aguarda os cards de plano ficarem visíveis no DOM
2. Opcionalmente clica na tab "Mensal" para garantir preços mensais
3. Captura o texto de todos os cards visíveis
4. Retorna o texto acumulado para o extractor usar como contexto

Referência visual: cards com "Padrão com anúncios R$16,90",
"Premium R$22,90", toggle "Mensal/Anual".
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from scraping_resilience.intelligent_wait import IntelligentWaitManager
from scraping_resilience.step_screenshotter import StepScreenshotter

logger = logging.getLogger(__name__)

# Seletores dos cards de plano do Globoplay
# Baseado na estrutura observada: cards com preços dentro de
# elementos que contêm "R$" e nomes de plano
_PLAN_CARD_SELECTORS = [
    "[class*='offer']",
    "[class*='plan-card']",
    "[class*='PlanCard']",
    "[class*='card']",
    "[data-testid*='plan']",
    "[data-testid*='offer']",
]

# Seletor do toggle Mensal/Anual
_MONTHLY_TAB_TEXTS = ["Mensal", "mensal"]

# Tempo máximo para aguardar cards renderizarem (ms)
_CARDS_WAIT_TIMEOUT_MS = 15_000


class GloboplayFlow:
    """Fluxo de scraping para Globoplay.

    Garante que os cards de preço estão renderizados antes da extração.
    O Globoplay é uma SPA que demora para carregar conteúdo dinâmico.

    Uso no scraper.py:
        globo_flow = GloboplayFlow(wait_manager, screenshotter)
        extra_text = await globo_flow.execute(page)
        # extra_text contém texto dos cards para passar ao AI
    """

    def __init__(
        self,
        wait_manager: IntelligentWaitManager,
        screenshotter: StepScreenshotter,
    ) -> None:
        """Inicializa o fluxo Globoplay.

        Args:
            wait_manager: Instância de IntelligentWaitManager.
            screenshotter: Instância de StepScreenshotter.
        """
        self._wait_manager = wait_manager
        self._screenshotter = screenshotter

    async def execute(self, page: Page) -> str:
        """Executa o fluxo completo do Globoplay.

        1. Aguarda cards de plano ficarem visíveis
        2. Tenta clicar na tab "Mensal" (se existir)
        3. Captura texto de todos os cards
        4. Captura screenshot após cards carregados

        Args:
            page: Página Playwright já navegada para o Globoplay.

        Returns:
            Texto acumulado dos cards com preços (para contexto do AI).
        """
        logger.info("GloboplayFlow: iniciando espera por cards de plano")

        # 1. Aguardar cards renderizarem
        cards_found = await self._wait_for_cards(page)

        if not cards_found:
            logger.warning(
                "GloboplayFlow: cards não encontrados após espera"
            )
            # Capturar texto mesmo assim (pode ter info útil)
            return await self._capture_page_text(page)

        logger.info("GloboplayFlow: cards de plano detectados")

        # 2. Tentar clicar na tab "Mensal" para ver preços mensais
        await self._click_monthly_tab(page)

        # 3. Capturar screenshot com cards visíveis
        await self._screenshotter.capture(page, "globoplay_cards")

        # 4. Extrair texto dos cards
        card_text = await self._extract_card_text(page)

        # 5. Capturar texto completo como fallback
        page_text = await self._capture_page_text(page)

        # Combinar: card text primeiro (mais relevante), depois page text
        if card_text:
            combined = (
                f"--- CARDS DE PLANO GLOBOPLAY ---\n{card_text}\n\n"
                f"--- TEXTO COMPLETO DA PAGINA ---\n{page_text}"
            )
        else:
            combined = page_text

        logger.info(
            "GloboplayFlow: texto capturado (%d chars, cards=%d chars)",
            len(combined),
            len(card_text),
        )
        return combined

    async def _wait_for_cards(self, page: Page) -> bool:
        """Aguarda cards de preço ficarem visíveis no DOM.

        Tenta múltiplos seletores em paralelo. Retorna True assim que
        algum card com texto "R$" for encontrado.

        Args:
            page: Página Playwright.

        Returns:
            True se cards com preços foram encontrados.
        """
        import asyncio

        # Estratégia: esperar até 15s por elemento que contenha "R$"
        try:
            # Aguardar qualquer elemento com R$ aparecer
            await page.wait_for_function(
                """
                () => {
                    const body = document.body.innerText;
                    return body.includes('R$') && body.length > 500;
                }
                """,
                timeout=_CARDS_WAIT_TIMEOUT_MS,
            )
            return True
        except Exception:
            pass

        # Fallback: esperar 8 segundos fixo e verificar
        await asyncio.sleep(8)
        text = await page.evaluate("document.body.innerText")
        return "R$" in text

    async def _click_monthly_tab(self, page: Page) -> None:
        """Tenta clicar na tab 'Mensal' se disponível.

        Alguns planos do Globoplay são exibidos em modo anual por padrão.
        Clicar em "Mensal" mostra o preço mensal de cada plano.

        Args:
            page: Página Playwright com cards já carregados.
        """
        try:
            for tab_text in _MONTHLY_TAB_TEXTS:
                locator = page.get_by_text(tab_text, exact=True)
                if await locator.count() > 0:
                    await locator.first.click(timeout=3000)
                    logger.info(
                        "GloboplayFlow: tab '%s' clicada", tab_text
                    )
                    await page.wait_for_timeout(2000)
                    return
        except Exception as e:
            logger.debug(
                "GloboplayFlow: tab Mensal não encontrada ou erro: %s", e
            )

    async def _extract_card_text(self, page: Page) -> str:
        """Extrai texto de todos os cards de plano visíveis.

        Itera nos seletores de card e extrai innerText de cada um.
        Filtra apenas cards que contêm "R$" (evita cards decorativos).

        Args:
            page: Página Playwright com cards renderizados.

        Returns:
            Texto concatenado de todos os cards com preço.
        """
        texts: list[str] = []

        for selector in _PLAN_CARD_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    try:
                        text = await el.inner_text()
                        if "R$" in text and len(text) > 20:
                            # Evitar duplicatas
                            if text.strip() not in texts:
                                texts.append(text.strip())
                    except Exception:
                        continue

                # Se encontrou cards com preço, usar esses
                if texts:
                    break
            except Exception:
                continue

        return "\n\n---\n\n".join(texts)

    async def _capture_page_text(self, page: Page) -> str:
        """Captura texto completo da página como fallback.

        Args:
            page: Página Playwright.

        Returns:
            innerText completo do body.
        """
        try:
            return await page.inner_text("body")
        except Exception:
            return ""
