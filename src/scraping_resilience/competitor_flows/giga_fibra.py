"""Fluxo específico para Giga+ Fibra — cookie injection + fallback dropdown.

Integra GeolocationCookieInjector (injeção de cookies ANTES da navegação)
com CustomComponentInteractor (Cascade Strategy como fallback) para garantir
que planos de São Paulo sejam carregados corretamente.

Fluxo:
1. Injetar 5 cookies interdependentes ANTES da navegação
2. Após page load, verificar se modal de localização foi suprimido
3. Se suprimido: prosseguir direto para screenshot e extração
4. Se não suprimido: usar Cascade Strategy como fallback
5. Validar que planos com preços estão carregados antes de extrair
"""

from __future__ import annotations

import logging

from playwright.async_api import BrowserContext, Page

from scraping_resilience.component_interactor import (
    CustomComponentInteractor,
)
from scraping_resilience.cookie_injector import GeolocationCookieInjector
from scraping_resilience.site_configs.giga_fibra import GIGA_FIBRA_CONFIG
from scraping_resilience.step_screenshotter import StepScreenshotter

logger = logging.getLogger(__name__)

# Seletor padrão para validar que planos com preços estão carregados
PLANS_LOADED_SELECTOR = (
    "[class*='card'], [class*='plan'], [class*='plano']"
)


class GigaFibraFlow:
    """Orquestra o fluxo de scraping da Giga+ Fibra.

    Coordena cookie injection, verificação de modal e fallback
    via Cascade Strategy para garantir extração confiável.
    """

    def __init__(
        self,
        cookie_injector: GeolocationCookieInjector,
        component_interactor: CustomComponentInteractor,
        screenshotter: StepScreenshotter,
    ) -> None:
        """Inicializa o fluxo com dependências injetadas.

        Args:
            cookie_injector: Injeta cookies de geolocalização.
            component_interactor: Interage com dropdowns customizados.
            screenshotter: Captura screenshots sequenciais.
        """
        self._cookie_injector = cookie_injector
        self._component_interactor = component_interactor
        self._screenshotter = screenshotter

    async def execute(
        self, browser_context: BrowserContext, page: Page
    ) -> dict:
        """Executa fluxo Giga+ Fibra: inject → navigate → verify → extract.

        Args:
            browser_context: Contexto do browser Playwright.
            page: Página Playwright já criada (navegação feita externamente).

        Returns:
            Dict com resultado: success, modal_suppressed, fallback_used,
            plans_loaded e eventuais erros.
        """
        # 1. Injetar cookies ANTES da navegação
        injection_result = await self._cookie_injector.inject_cookies(
            browser_context, GIGA_FIBRA_CONFIG
        )
        logger.info(
            "Cookies injetados: %d", injection_result.cookies_count
        )

        # 2. Após page load, verificar se modal foi suprimido
        modal_selector = GIGA_FIBRA_CONFIG["modal_selector"]
        modal_suppressed = (
            await self._cookie_injector.verify_modal_suppressed(
                page, modal_selector
            )
        )

        fallback_used = False

        if modal_suppressed:
            # Cookie suprimiu o modal com sucesso
            logger.info(
                "Modal suprimido via cookies. "
                "Prosseguindo para extração."
            )
            await self._screenshotter.capture(
                page, "after_cookie_injection_success"
            )
        else:
            # 3. Fallback: usar Cascade Strategy (Requirement 7)
            logger.info(
                "Modal detectado. Usando Cascade Strategy "
                "como fallback."
            )
            await self._screenshotter.capture(
                page, "modal_detected"
            )

            interaction_result = (
                await self._component_interactor.interact(
                    page,
                    modal_selector,
                    desired_value="São Paulo",
                    fallback_value=None,
                )
            )

            if not interaction_result.success:
                logger.error(
                    "Cascade Strategy falhou: %s",
                    interaction_result.error,
                )
                return {
                    "success": False,
                    "modal_suppressed": False,
                    "fallback_used": True,
                    "plans_loaded": False,
                    "error": interaction_result.error,
                }

            fallback_used = True
            await self._screenshotter.capture(
                page, "after_dropdown_interaction"
            )

        # 4. Validar que planos com preços estão carregados
        plans_loaded = await self._verify_plans_loaded(page)

        if not plans_loaded:
            logger.warning(
                "Planos com preços não encontrados na página."
            )

        return {
            "success": True,
            "modal_suppressed": modal_suppressed,
            "fallback_used": fallback_used,
            "plans_loaded": plans_loaded,
        }

    async def _verify_plans_loaded(
        self, page: Page, timeout_ms: int = 10_000
    ) -> bool:
        """Verifica que elementos de planos/preços estão visíveis.

        Args:
            page: Página Playwright.
            timeout_ms: Tempo máximo de espera por elementos.

        Returns:
            True se planos foram encontrados, False caso contrário.
        """
        try:
            await page.wait_for_selector(
                PLANS_LOADED_SELECTOR,
                timeout=timeout_ms,
                state="visible",
            )
            return True
        except Exception:
            return False
