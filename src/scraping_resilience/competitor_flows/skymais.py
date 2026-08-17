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

        self._plan_details_text = ""

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

        # Clicar em "Detalhes do plano" e aba "Streamings" de cada card
        await self._expand_plan_details(page)

        # Capturar screenshot após interação
        await self._screenshotter.capture(page, "skymais_after_details")

        # Capturar texto completo da página
        full_text = await page.evaluate("document.body.innerText")

        # Combinar: texto das modais (com streamings) + texto da página
        if self._plan_details_text:
            combined = (
                "--- STREAMINGS POR PLANO (extraído das modais) ---\n"
                "IMPORTANTE: Associar os streamings listados abaixo a "
                "cada plano correspondente no campo bundled_streamings.\n\n"
                f"{self._plan_details_text}\n\n"
                f"--- TEXTO COMPLETO DA PÁGINA ---\n{full_text}"
            )
        else:
            combined = full_text

        logger.info(
            "SkyMaisFlow: texto extraído (%d chars, "
            "detalhes modais=%d chars)",
            len(combined),
            len(self._plan_details_text),
        )
        return combined

    async def _expand_plan_details(self, page: Page) -> None:
        """Clica em 'Detalhes do plano' de cada card e na aba 'Streamings'.

        O SKY+ mostra os streamings em uma modal que abre ao clicar em
        'Detalhes do plano'. Dentro da modal, há abas: Detalhes, Canais,
        Streamings. Precisamos clicar na aba 'Streamings' para ver a lista.
        """
        import asyncio

        details_links = page.get_by_text("Detalhes do plano", exact=False)
        count = await details_links.count()
        logger.info(
            "SkyMaisFlow: encontrados %d links 'Detalhes do plano'",
            count,
        )

        plan_streamings: list[str] = []

        for i in range(count):
            try:
                # Re-buscar os links a cada iteração (DOM pode mudar)
                details_links = page.get_by_text(
                    "Detalhes do plano", exact=False
                )
                current_count = await details_links.count()
                if i >= current_count:
                    break

                # Clicar em "Detalhes do plano"
                await details_links.nth(i).click(timeout=5000)
                await page.wait_for_timeout(2000)

                # Clicar na aba "Streamings"
                streaming_tab = page.get_by_text(
                    "Streamings", exact=True
                )
                if await streaming_tab.count() > 0:
                    await streaming_tab.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)

                    # Extrair nome do plano da modal
                    plan_name = await page.evaluate("""
                        () => {
                            // Buscar título do plano na modal
                            const headings = document.querySelectorAll(
                                'h1, h2, h3, [class*="title"], '
                                + '[class*="Title"], [class*="heading"]'
                            );
                            for (const h of headings) {
                                const text = h.innerText.trim();
                                if (text.includes('Plano') && text.length < 50) {
                                    return text;
                                }
                            }
                            return 'Plano desconhecido';
                        }
                    """)

                    # Extrair nomes dos streamings via texto da modal
                    streaming_names = await page.evaluate("""
                        () => {
                            // Lista de streamings conhecidos
                            const KNOWN_SERVICES = [
                                'Amazon Prime', 'Disney+',
                                'HBO Max', 'Paramount+',
                                'Premiere', 'Sportynet+',
                                'SportyNet+', 'Telecine',
                                'Netflix', 'Globoplay',
                                'Apple TV+', 'Star+',
                                'ESPN', 'Discovery+'
                            ];
                            // Buscar texto APENAS da modal
                            const modals = document.querySelectorAll(
                                '[class*="modal"], [class*="Modal"], '
                                + '[role="dialog"], [class*="popup"], '
                                + '[class*="Popup"], [class*="drawer"], '
                                + '[class*="Drawer"], [class*="overlay"]'
                            );
                            let modalText = '';
                            for (const m of modals) {
                                const t = m.innerText;
                                if (t.includes('Streaming') && t.length > 50) {
                                    modalText = t;
                                    break;
                                }
                            }
                            if (!modalText) return [];
                            // Buscar quais serviços conhecidos estão no texto da modal
                            const found = [];
                            for (const s of KNOWN_SERVICES) {
                                if (modalText.includes(s)) {
                                    found.push(s);
                                }
                            }
                            return found;
                        }
                    """)

                    if streaming_names:
                        entry = (
                            f"PLANO: {plan_name}\n"
                            f"STREAMINGS INCLUSOS: "
                            f"{', '.join(streaming_names)}"
                        )
                        plan_streamings.append(entry)
                        logger.info(
                            "SkyMaisFlow: plano '%s' -> %d streamings: %s",
                            plan_name, len(streaming_names),
                            ", ".join(streaming_names),
                        )
                    else:
                        # Fallback: texto completo da modal
                        modal_text = await page.evaluate("""
                            () => {
                                const modals = document.querySelectorAll(
                                    '[class*="modal"], [class*="Modal"], '
                                    + '[role="dialog"]'
                                );
                                for (const m of modals) {
                                    const text = m.innerText;
                                    if (text.includes('Streaming')) {
                                        return text;
                                    }
                                }
                                return '';
                            }
                        """)
                        if modal_text:
                            plan_streamings.append(
                                f"PLANO: {plan_name}\n{modal_text}"
                            )
                            logger.info(
                                "SkyMaisFlow: capturado texto da modal "
                                "(%d chars) para plano %d",
                                len(modal_text), i + 1,
                            )

                # Fechar modal (botão X ou Escape)
                close_btn = page.locator(
                    "[class*='close'], [aria-label='Close'], "
                    "[class*='Close'], button:has-text('×')"
                )
                if await close_btn.count() > 0:
                    await close_btn.first.click(timeout=2000)
                else:
                    await page.keyboard.press("Escape")
                await page.wait_for_timeout(1500)

                # Scroll de volta ao topo para encontrar próximo link
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)

            except Exception as e:
                logger.debug(
                    "SkyMaisFlow: erro no plano %d: %s", i, e
                )
                # Tentar fechar modal caso esteja aberta
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(500)
                except Exception:
                    pass

        # Salvar texto dos streamings como contexto
        if plan_streamings:
            self._plan_details_text = "\n\n".join(plan_streamings)
        else:
            self._plan_details_text = ""

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
