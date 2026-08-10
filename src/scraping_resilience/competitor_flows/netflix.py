"""Fluxo específico para Netflix — validação de região.

Valida que o conteúdo da Netflix está em português/BRL antes
de prosseguir com a extração de preços. Se GEO_MISMATCH for
detectado, salva evidência (HTML + screenshot), pula a extração
e registra a razão.
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


class NetflixFlow:
    """Fluxo de scraping para Netflix com validação de região.

    Executa validação de conteúdo (idioma pt, moeda BRL) antes da
    extração. Se GEO_MISMATCH for detectado, captura evidência
    diagnóstica e pula a extração para evitar contaminação do banco.
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
        """Inicializa o NetflixFlow.

        Args:
            content_validator: Validador genérico de conteúdo/região.
            diagnostics_collector: Coletor de artefatos diagnósticos.
            health_check_scorer: Calculador de Health Check Score.
            screenshotter: Capturador de screenshots sequenciais.
            competitor_id: Identificador do concorrente (netflix).
            cycle_id: Identificador do ciclo de monitoramento.
        """
        self._content_validator = content_validator
        self._diagnostics = diagnostics_collector
        self._scorer = health_check_scorer
        self._screenshotter = screenshotter
        self._competitor_id = competitor_id
        self._cycle_id = cycle_id

    async def execute(self, page: Page) -> dict:
        """Valida região do conteúdo Netflix antes da extração.

        Fluxo:
        1. Chama ContentValidator.validate() com pt/BRL
        2. Se GEO_MISMATCH: salva evidência, pula extração
        3. Se SUCCESS: prossegue com extração normal

        Args:
            page: Página Playwright já carregada com Netflix.

        Returns:
            Dict com resultado da execução:
            - success: bool indicando se extração pode prosseguir
            - extraction_skipped: bool se extração foi pulada
            - health_check_score: valor do HealthCheckScore
            - reason: razão descritiva (quando GEO_MISMATCH)
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
            # GEO_MISMATCH: salvar evidência e pular extração
            logger.warning(
                "Netflix GEO_MISMATCH detectado: %s",
                validation.reason,
            )

            # Capturar evidência diagnóstica (HTML + screenshot)
            await self._diagnostics.capture_diagnostic(
                page,
                validation.reason or "geo_mismatch",
                self._competitor_id,
                self._cycle_id,
            )

            # Screenshot de evidência do mismatch
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

        # SUCCESS: conteúdo em português/BRL, prosseguir
        logger.info(
            "Netflix: conteúdo validado (pt/BRL). "
            "Prosseguindo com extração."
        )

        # Screenshot de confirmação do conteúdo validado
        await self._screenshotter.capture(
            page, "content_validated"
        )

        return {
            "success": True,
            "extraction_skipped": False,
            "health_check_score": HealthCheckScore.SUCCESS.value,
        }
