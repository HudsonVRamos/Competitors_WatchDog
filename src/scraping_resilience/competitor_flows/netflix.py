"""Fluxo específico para Netflix — navegação interativa + validação de região.

A Netflix mostra apenas "A partir de R$ 20,90" na landing page.
Para ver todos os planos, é necessário clicar em "Vamos lá" e
aguardar a tabela de comparação carregar.

Este flow:
1. Valida região (pt/BRL)
2. Tenta navegar para a tabela de planos via clique
3. Aguarda cards/tabela de planos renderizar
4. Retorna texto dos planos para o extractor
"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from scraping_resilience.content_validator import ContentValidator
from scraping_resilience.diagnostics_collector import (
    DiagnosticsCollector,
)
from scraping_resilience.health_check_scorer import HealthCheckScorer
from scraping_resilience.models import HealthCheckScore
from scraping_resilience.step_screenshotter import StepScreenshotter

logger = logging.getLogger(__name__)

# Textos de botões que levam à página de planos
_CTA_TEXTS = ["Vamos lá", "Assine agora", "Comece agora", "Saiba mais"]

# Seletores que indicam que a tabela de planos carregou
_PLAN_SELECTORS = [
    "[class*='planGrid']",
    "[class*='plan-card']",
    "[class*='PlanCard']",
    "[data-uia*='plan']",
    "table",
    "[class*='price']",
]


class NetflixFlow:
    """Fluxo de scraping para Netflix com navegação interativa.

    Executa validação de conteúdo (idioma pt, moeda BRL) e tenta
    navegar para a tabela de planos via clique em CTA.
    """

    def __init__(
        self,
        content_validator: ContentValidator,
        diagnostics_collector: DiagnosticsCollector,
        health_check_scorer: HealthCheckScorer,
        screenshotter: StepScreenshotter,
        competitor_id: str,
        cycle_id: str,
    ) -> None:
        """Inicializa o NetflixFlow."""
        self._content_validator = content_validator
        self._diagnostics = diagnostics_collector
        self._scorer = health_check_scorer
        self._screenshotter = screenshotter
        self._competitor_id = competitor_id
        self._cycle_id = cycle_id

    async def execute(self, page: Page) -> dict:
        """Valida região e navega para tabela de planos.

        Args:
            page: Página Playwright já carregada com Netflix.

        Returns:
            Dict com resultado da execução.
        """
        # Validar conteúdo (idioma e moeda)
        validation = await self._content_validator.validate(
            page,
            expected_language="pt",
            expected_currency="BRL",
        )

        if (
            validation.health_check_score
            == HealthCheckScore.GEO_MISMATCH
        ):
            logger.warning(
                "Netflix GEO_MISMATCH detectado: %s",
                validation.reason,
            )
            await self._diagnostics.capture_diagnostic(
                page,
                validation.reason or "geo_mismatch",
                self._competitor_id,
                self._cycle_id,
            )
            await self._screenshotter.capture(
                page, "geo_mismatch_evidence"
            )
            return {
                "success": False,
                "extraction_skipped": True,
                "health_check_score": (
                    HealthCheckScore.GEO_MISMATCH.value
                ),
                "reason": validation.reason,
            }

        # Conteúdo em pt/BRL — tentar navegar para planos
        logger.info(
            "Netflix: conteúdo validado. Tentando navegar "
            "para tabela de planos..."
        )

        # Tentar clicar em CTA para ir à página de planos
        navigated = await self._navigate_to_plans(page)

        if navigated:
            await self._screenshotter.capture(
                page, "plans_table_loaded"
            )
        else:
            await self._screenshotter.capture(
                page, "content_validated"
            )

        return {
            "success": True,
            "extraction_skipped": False,
            "health_check_score": HealthCheckScore.SUCCESS.value,
        }

    async def _navigate_to_plans(self, page: Page) -> bool:
        """Tenta navegar para a tabela de planos da Netflix.

        Estratégias:
        1. Clicar em links/botões com texto CTA
        2. Navegar diretamente para /signup/planform
        3. Esperar se já está na página de planos

        Returns:
            True se conseguiu navegar e planos estão visíveis.
        """
        import asyncio

        # Verificar se já tem R$ na página (planos visíveis)
        text = await page.evaluate("document.body.innerText")
        # Contar ocorrências de R$ — se tem mais de 2, provavelmente
        # já está mostrando planos
        r_count = text.count("R$")
        if r_count >= 3:
            logger.info(
                "Netflix: %d preços já visíveis na página", r_count
            )
            return True

        # Estratégia 1: Clicar em CTA
        for cta_text in _CTA_TEXTS:
            try:
                locator = page.get_by_role(
                    "link", name=cta_text
                ).or_(page.get_by_role("button", name=cta_text))
                if await locator.count() > 0:
                    await locator.first.click(timeout=5000)
                    logger.info(
                        "Netflix: clicou em '%s'", cta_text
                    )
                    await page.wait_for_timeout(3000)

                    # Verificar se navegou para signup/planform
                    if "signup" in page.url or "planform" in page.url:
                        # Esperar planos carregarem
                        await self._wait_for_plans(page)
                        return True
            except Exception:
                continue

        # Estratégia 2: Navegar direto para planform
        try:
            current_url = page.url
            plan_url = "https://www.netflix.com/br/signup/planform"
            await page.goto(plan_url, timeout=30000)
            await page.wait_for_timeout(5000)

            text = await page.evaluate("document.body.innerText")
            if "R$" in text and len(text) > 500:
                logger.info(
                    "Netflix: navegação direta para planform OK"
                )
                return True
            else:
                # Voltar para a URL original
                await page.goto(current_url, timeout=30000)
                await page.wait_for_timeout(3000)
        except Exception as e:
            logger.debug(
                "Netflix: falha na navegação direta: %s", e
            )

        # Estratégia 3: Scroll e esperar mais
        for _ in range(3):
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await asyncio.sleep(2)
            text = await page.evaluate("document.body.innerText")
            if text.count("R$") >= 3:
                logger.info("Netflix: planos apareceram após scroll")
                return True

        logger.warning(
            "Netflix: não conseguiu navegar para tabela de planos"
        )
        return False

    async def _wait_for_plans(self, page: Page) -> None:
        """Aguarda a tabela de planos carregar."""
        try:
            await page.wait_for_function(
                """() => {
                    const text = document.body.innerText;
                    return (text.match(/R\\$/g) || []).length >= 2
                        && text.length > 500;
                }""",
                timeout=15000,
            )
            logger.info("Netflix: tabela de planos detectada")
        except Exception:
            logger.warning(
                "Netflix: timeout aguardando tabela de planos"
            )
