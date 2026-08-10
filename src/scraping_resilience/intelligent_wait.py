"""IntelligentWaitManager - Gerencia esperas inteligentes baseadas em condição.

Substitui sleeps fixos (time.sleep / asyncio.sleep) por esperas baseadas em
condição, utilizando estratégia em cascata:
1. networkidle (até 30s)
2. waitForSelector para elementos críticos (até 15s)
3. toBeVisible para confirmar renderização

Também fornece detecção de mudança de conteúdo após interações (ex: clique em tab).
"""

from __future__ import annotations

import logging
import time

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import expect

from src.scraping_resilience.models import WaitResult

logger = logging.getLogger(__name__)


class IntelligentWaitManager:
    """Gerencia esperas inteligentes baseadas em condição.

    Utiliza estratégia em cascata para aguardar que a página esteja pronta,
    sem depender de sleeps fixos arbitrários.
    """

    async def wait_for_page_ready(
        self,
        page: Page,
        critical_selectors: list[str] | None = None,
        network_idle_timeout_ms: int = 30_000,
        selector_timeout_ms: int = 15_000,
    ) -> WaitResult:
        """Aguarda página pronta usando estratégia em cascata.

        Prioridade:
        1. networkidle (até network_idle_timeout_ms)
        2. waitForSelector para elementos críticos (até selector_timeout_ms)
        3. toBeVisible para confirmar renderização

        Retorna WaitResult com a estratégia que obteve sucesso e o tempo decorrido.
        Se nenhuma estratégia funcionar, retorna WaitResult com timeout_occurred=True.
        """
        start = time.perf_counter()

        # Estratégia 1: networkidle
        try:
            await page.wait_for_load_state(
                "networkidle", timeout=network_idle_timeout_ms
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "Página pronta via networkidle em %d ms", elapsed_ms
            )
            return WaitResult(
                success=True,
                strategy_used="networkidle",
                elapsed_ms=elapsed_ms,
                timeout_occurred=False,
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "networkidle timeout após %d ms, tentando waitForSelector",
                network_idle_timeout_ms,
            )

        # Estratégia 2: waitForSelector para elementos críticos
        if critical_selectors:
            for selector in critical_selectors:
                try:
                    await page.wait_for_selector(
                        selector, timeout=selector_timeout_ms
                    )
                    elapsed_ms = int((time.perf_counter() - start) * 1000)
                    logger.info(
                        "Página pronta via waitForSelector('%s') em %d ms",
                        selector,
                        elapsed_ms,
                    )
                    return WaitResult(
                        success=True,
                        strategy_used="selector",
                        elapsed_ms=elapsed_ms,
                        timeout_occurred=False,
                    )
                except PlaywrightTimeoutError:
                    logger.warning(
                        "waitForSelector('%s') timeout após %d ms",
                        selector,
                        selector_timeout_ms,
                    )
                    continue
        else:
            # Sem seletores críticos: tentar body como fallback
            try:
                await page.wait_for_selector("body", timeout=selector_timeout_ms)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    "Página pronta via waitForSelector('body') em %d ms",
                    elapsed_ms,
                )
                return WaitResult(
                    success=True,
                    strategy_used="selector",
                    elapsed_ms=elapsed_ms,
                    timeout_occurred=False,
                )
            except PlaywrightTimeoutError:
                logger.warning(
                    "waitForSelector('body') timeout após %d ms",
                    selector_timeout_ms,
                )

        # Estratégia 3: toBeVisible — confirmar que pelo menos um elemento está visível
        visible_targets = critical_selectors if critical_selectors else ["body"]
        for selector in visible_targets:
            try:
                locator = page.locator(selector).first
                await expect(locator).to_be_visible(timeout=selector_timeout_ms)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    "Página pronta via toBeVisible('%s') em %d ms",
                    selector,
                    elapsed_ms,
                )
                return WaitResult(
                    success=True,
                    strategy_used="visible",
                    elapsed_ms=elapsed_ms,
                    timeout_occurred=False,
                )
            except (PlaywrightTimeoutError, AssertionError):
                logger.warning(
                    "toBeVisible('%s') timeout após %d ms",
                    selector,
                    selector_timeout_ms,
                )
                continue

        # Nenhuma estratégia obteve sucesso
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            "Todas as estratégias de espera falharam após %d ms", elapsed_ms
        )
        return WaitResult(
            success=False,
            strategy_used="none",
            elapsed_ms=elapsed_ms,
            timeout_occurred=True,
        )

    async def wait_for_content_change(
        self,
        page: Page,
        reference_selector: str,
        timeout_ms: int = 15_000,
    ) -> bool:
        """Aguarda mudança de conteúdo após interação (ex: clique em tab).

        Captura o conteúdo textual do reference_selector antes, e aguarda
        até que ele mude ou timeout expire.

        Retorna True se o conteúdo mudou, False se timeout expirou sem mudança.
        """
        # Capturar conteúdo de referência antes da mudança
        try:
            reference_content = await page.locator(
                reference_selector
            ).first.inner_text()
        except Exception:
            # Se não conseguir capturar referência, assume conteúdo vazio
            reference_content = ""

        logger.debug(
            "Conteúdo de referência capturado para '%s' (%d chars)",
            reference_selector,
            len(reference_content),
        )

        # Aguardar até que o conteúdo mude usando page.wait_for_function
        try:
            await page.wait_for_function(
                """
                ([selector, previousContent]) => {
                    const element = document.querySelector(selector);
                    if (!element) return false;
                    return element.innerText !== previousContent;
                }
                """,
                [reference_selector, reference_content],
                timeout=timeout_ms,
            )
            logger.info(
                "Conteúdo de '%s' mudou com sucesso", reference_selector
            )
            return True
        except PlaywrightTimeoutError:
            logger.warning(
                "Conteúdo de '%s' não mudou dentro de %d ms",
                reference_selector,
                timeout_ms,
            )
            return False
