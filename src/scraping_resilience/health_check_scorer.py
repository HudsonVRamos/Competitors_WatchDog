"""HealthCheckScorer - Calcula e atribui Health Check Score por execução.

Classificação com hierarquia de prioridade:
- NETWORK_ERROR: Falha de conectividade (timeout, DNS, connection reset)
- GEO_REDIRECT: URL final diverge significativamente da esperada
- GEO_MISMATCH: Conteúdo em idioma/moeda incorretos
- SCRAPER_ERROR: Falha de interação com a página
- SUCCESS: Preços extraídos com sucesso em idioma e moeda corretos

Quando score é GEO_MISMATCH ou GEO_REDIRECT, a extração é marcada como
"skipped" para evitar contaminação do banco com dados incorretos.
"""

from __future__ import annotations

from src.scraping_resilience.models import (
    ContentValidationResult,
    HealthCheckScore,
)


class HealthCheckScorer:
    """Calcula Health Check Score para uma execução."""

    def score(
        self,
        validation_result: ContentValidationResult | None,
        extraction_success: bool,
        network_error: bool,
    ) -> tuple[HealthCheckScore, str | None, bool]:
        """Determina score baseado em hierarquia de prioridade.

        Prioridade (maior para menor):
        1. NETWORK_ERROR — se network_error=True
        2. GEO_REDIRECT — se validation_result indica redirecionamento
        3. GEO_MISMATCH — se validation_result indica mismatch de geo
        4. SCRAPER_ERROR — se extraction_success=False sem problemas geo
        5. SUCCESS — se extraction_success=True e validação OK

        Args:
            validation_result: Resultado da validação de conteúdo/região,
                ou None se a validação não foi executada.
            extraction_success: Se a extração de preços teve sucesso.
            network_error: Se houve erro de rede na execução.

        Returns:
            Tupla (score, reason, extraction_skipped):
            - score: HealthCheckScore enum value
            - reason: Razão descritiva não-vazia para GEO_MISMATCH
              e GEO_REDIRECT; None para os demais
            - extraction_skipped: True quando score é GEO_MISMATCH
              ou GEO_REDIRECT; False caso contrário
        """
        # Prioridade 1: NETWORK_ERROR
        if network_error:
            return (HealthCheckScore.NETWORK_ERROR, None, False)

        # Prioridade 2 e 3: verificar validação de conteúdo
        if validation_result is not None:
            score = validation_result.health_check_score

            # Prioridade 2: GEO_REDIRECT
            if score == HealthCheckScore.GEO_REDIRECT:
                reason = validation_result.reason or "geo_redirect detectado"
                return (HealthCheckScore.GEO_REDIRECT, reason, True)

            # Prioridade 3: GEO_MISMATCH
            if score == HealthCheckScore.GEO_MISMATCH:
                reason = validation_result.reason or "geo_mismatch detectado"
                return (HealthCheckScore.GEO_MISMATCH, reason, True)

        # Prioridade 4: SCRAPER_ERROR
        if not extraction_success:
            return (HealthCheckScore.SCRAPER_ERROR, None, False)

        # Prioridade 5: SUCCESS
        return (HealthCheckScore.SUCCESS, None, False)
