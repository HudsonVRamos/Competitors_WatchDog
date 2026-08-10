"""Fluxo específico para Paramount+ — detecção de redirect.

Valida se o conteúdo carregado é a página brasileira de planos
ou se houve redirecionamento para conteúdo americano (gift cards).

Indicadores de redirect US:
- Termos: "Gift Card", "Walmart", "Best Buy", "Sam's Club", "Available at"
- Preços em USD
- URL final sem "/br/" ou com domínio diferente

Quando detecta GEO_REDIRECT:
- Salva evidência (HTML + screenshot via DiagnosticsCollector)
- Skipa extração de preços
- Registra razão com URL final

Quando conteúdo é válido (SUCCESS):
- Prossegue com extração normal
"""

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


class ParamountFlow:
    """Fluxo de validação e extração para Paramount+.

    Detecta redirecionamento para conteúdo US antes de permitir
    a extração de preços. Utiliza ContentValidator para análise
    genérica de idioma, moeda e URL.

    Args:
        content_validator: Validador de conteúdo/região.
        diagnostics_collector: Coletor de artefatos diagnósticos.
        health_check_scorer: Calculador de Health Check Score.
        screenshotter: Captura de screenshots por etapa.
        competitor_id: Identificador do concorrente.
        cycle_id: Identificador do ciclo de monitoramento.
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
        self._content_validator = content_validator
        self._diagnostics = diagnostics_collector
        self._scorer = health_check_scorer
        self._screenshotter = screenshotter
        self._competitor_id = competitor_id
        self._cycle_id = cycle_id

    async def execute(self, page: Page) -> dict:
        """Valida conteúdo do Paramount+ para detecção de redirect US.

        Fluxo:
        1. Chama ContentValidator.validate() com expected_url_pattern="/br/"
        2. Se GEO_REDIRECT: captura diagnóstico, skip extração
        3. Se GEO_MISMATCH: captura diagnóstico, skip extração
        4. Se SUCCESS: prossegue com extração normal

        Args:
            page: Página Playwright já navegada para o Paramount+.

        Returns:
            Dict com resultado da validação:
            - success: bool
            - extraction_skipped: bool
            - health_check_score: str (valor do enum)
            - reason: str | None (razão de falha)
            - final_url: str | None (URL final em caso de redirect)
        """
        # Validar conteúdo com verificação de URL pattern
        validation = await self._content_validator.validate(
            page,
            expected_language="pt",
            expected_currency="BRL",
            expected_url_pattern="/br/",
        )

        if validation.health_check_score == (
            HealthCheckScore.GEO_REDIRECT
        ):
            logger.warning(
                "Paramount+ GEO_REDIRECT: %s", validation.reason
            )
            await self._diagnostics.capture_diagnostic(
                page,
                validation.reason or "geo_redirect",
                self._competitor_id,
                self._cycle_id,
            )
            await self._screenshotter.capture(
                page, "geo_redirect_evidence"
            )
            return {
                "success": False,
                "extraction_skipped": True,
                "health_check_score": (
                    HealthCheckScore.GEO_REDIRECT.value
                ),
                "reason": validation.reason,
                "final_url": validation.final_url,
            }

        if validation.health_check_score == (
            HealthCheckScore.GEO_MISMATCH
        ):
            logger.warning(
                "Paramount+ GEO_MISMATCH: %s", validation.reason
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

        # SUCCESS — conteúdo válido (português/BRL, URL com /br/)
        logger.info(
            "Paramount+: conteúdo válido (pt/BRL, URL /br/). "
            "Prosseguindo com extração."
        )
        await self._screenshotter.capture(
            page, "content_validated"
        )
        return {
            "success": True,
            "extraction_skipped": False,
            "health_check_score": HealthCheckScore.SUCCESS.value,
        }
