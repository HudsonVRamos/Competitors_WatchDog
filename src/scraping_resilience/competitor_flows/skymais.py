"""Fluxo específico para SKY+ (skymais.com.br).

O SKY+ exibe planos base com ícones de streaming inclusos,
mas a IA tem dificuldade em associar os logos aos planos.
Este flow extrai o texto detalhado de cada card de plano
para garantir que os streamings sejam capturados.
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from scraping_resilience.intelligent_wait import IntelligentWaitManager
from scraping_resilience.step_screenshotter import StepScreenshotter

logger = logging.getLogger(__name__)

# Seletores de cards de plano do skymais
_PLAN_CARD_SELECTORS = [
    "[class*='card']",
    "[class*='plan']",
    "[class*='plano']",
    "[class*='Plan']",
    "[class*='package']",
    "[data-testid*='plan']",
]


class SkyMaisFlow:
    """Fluxo de scraping para SKY+ (skymais.com.br).

    Extrai texto detalhado de cada card de plano para garantir
    que streamings inclusos sejam capturados pelo extractor.
    """

    def __init__(
        self,
        wait_manager: IntelligentWaitManager,
        screenshotter: StepScreenshotter,
    ) -> None:
        self._wait_manager = wait_manager
        self._screenshotter = screenshotter

    async def execute(self, page: Page) -> str:
        """Extrai texto detalhado dos cards de plano.

        Args:
            page: Página Playwright já navegada.

        Returns:
            Texto acumulado dos cards com info de streamings.
        """
        logger.info("SkyMaisFlow: extraindo detalhes dos cards")

        # Esperar cards carregarem
        try:
            await page.wait_for_function(
                """() => {
                    const text = document.body.innerText;
                    return text.includes('R$') && text.length > 1000;
                }""",
                timeout=15000,
            )
        except Exception:
            pass

        # Expandir detalhes — clicar em "Ver mais" ou "Detalhes"
        await self._expand_plan_details(page)

        # Capturar screenshot após expansão
        await self._screenshotter.capture(page, "skymais_expanded")

        # Extrair texto de cada seção de plano
        plan_text = await self._extract_plan_details(page)

        # Capturar texto completo como fallback
        full_text = await page.evaluate("document.body.innerText")

        if plan_text:
            combined = (
                "--- DETALHES DOS PLANOS SKY+ ---\n"
                "IMPORTANTE: Cada plano pode incluir streamings listados "
                "abaixo do preço. Associar TODOS os streamings ao plano "
                "correspondente.\n\n"
                f"{plan_text}\n\n"
                f"--- TEXTO COMPLETO ---\n{full_text}"
            )
        else:
            combined = full_text

        logger.info(
            "SkyMaisFlow: texto extraído (%d chars, "
            "detalhes=%d chars)",
            len(combined),
            len(plan_text),
        )
        return combined

    async def _expand_plan_details(self, page: Page) -> None:
        """Expande detalhes/ver mais dos planos."""
        try:
            # Clicar em botões "Ver mais", "Detalhes", etc.
            for text in ["Ver mais", "Detalhes", "Saiba mais",
                         "Ver detalhes", "Inclusos"]:
                buttons = page.get_by_text(text, exact=False)
                count = await buttons.count()
                for i in range(min(count, 10)):
                    try:
                        await buttons.nth(i).click(timeout=2000)
                        await page.wait_for_timeout(500)
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("SkyMaisFlow: expand falhou: %s", e)

        await page.wait_for_timeout(1000)

    async def _extract_plan_details(self, page: Page) -> str:
        """Extrai texto detalhado de cada card de plano."""
        texts: list[str] = []

        for selector in _PLAN_CARD_SELECTORS:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    try:
                        text = await el.inner_text()
                        # Filtrar: cards com R$ e mais de 30 chars
                        if "R$" in text and len(text) > 30:
                            if text.strip() not in texts:
                                texts.append(text.strip())
                    except Exception:
                        continue

                if len(texts) >= 3:
                    break
            except Exception:
                continue

        return "\n\n--- PLANO ---\n\n".join(texts)
