"""Testes unitários para o HealthCheckScorer.

Verifica a hierarquia de prioridade de scoring, razões descritivas
e sinalização de extração como "skipped" para GEO_MISMATCH/GEO_REDIRECT.
"""

from __future__ import annotations

import pytest

from src.scraping_resilience.health_check_scorer import HealthCheckScorer
from src.scraping_resilience.models import (
    ContentValidationResult,
    HealthCheckScore,
)


@pytest.fixture
def scorer() -> HealthCheckScorer:
    """Instância do HealthCheckScorer para os testes."""
    return HealthCheckScorer()


@pytest.mark.unit
class TestHealthCheckScorerPriority:
    """Testes para hierarquia de prioridade do scoring."""

    def test_network_error_tem_maior_prioridade(
        self, scorer: HealthCheckScorer
    ) -> None:
        """NETWORK_ERROR tem prioridade sobre qualquer outro resultado."""
        # Mesmo com validation indicando GEO_REDIRECT e extração falhando
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="redirecionado para /us/",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=True,
        )

        assert score == HealthCheckScore.NETWORK_ERROR
        assert reason is None
        assert skipped is False

    def test_geo_redirect_tem_prioridade_sobre_geo_mismatch(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_REDIRECT tem prioridade sobre GEO_MISMATCH."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="URL redirecionada para /us/gift-cards",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_REDIRECT

    def test_geo_mismatch_tem_prioridade_sobre_scraper_error(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_MISMATCH tem prioridade sobre SCRAPER_ERROR."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="idioma inglês detectado",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_MISMATCH

    def test_scraper_error_quando_extracao_falha_sem_geo(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SCRAPER_ERROR quando extração falha sem problemas de geo."""
        validation = ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.SCRAPER_ERROR
        assert reason is None
        assert skipped is False

    def test_success_quando_tudo_ok(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SUCCESS quando validação OK e extração bem-sucedida."""
        validation = ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.SUCCESS
        assert reason is None
        assert skipped is False


@pytest.mark.unit
class TestHealthCheckScorerReason:
    """Testes para razão descritiva no scoring."""

    def test_geo_mismatch_inclui_razao_nao_vazia(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_MISMATCH retorna razão descritiva não-vazia."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="idioma inglês detectado, moeda USD encontrada",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_MISMATCH
        assert reason is not None
        assert len(reason) > 0
        assert "inglês" in reason

    def test_geo_redirect_inclui_razao_nao_vazia(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_REDIRECT retorna razão descritiva não-vazia."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="URL redirecionada para /us/gift-cards",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_REDIRECT
        assert reason is not None
        assert len(reason) > 0
        assert "gift-cards" in reason

    def test_geo_mismatch_razao_fallback_quando_reason_none(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_MISMATCH produz razão fallback se validation.reason é None."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason=None,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_MISMATCH
        assert reason is not None
        assert len(reason) > 0

    def test_geo_redirect_razao_fallback_quando_reason_none(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_REDIRECT produz razão fallback se validation.reason é None."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason=None,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_REDIRECT
        assert reason is not None
        assert len(reason) > 0

    def test_network_error_sem_razao(
        self, scorer: HealthCheckScorer
    ) -> None:
        """NETWORK_ERROR retorna reason=None."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=False,
            network_error=True,
        )

        assert reason is None

    def test_scraper_error_sem_razao(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SCRAPER_ERROR retorna reason=None."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=False,
            network_error=False,
        )

        assert reason is None

    def test_success_sem_razao(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SUCCESS retorna reason=None."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=True,
            network_error=False,
        )

        assert reason is None


@pytest.mark.unit
class TestHealthCheckScorerExtractionSkipped:
    """Testes para sinalização de extração como skipped."""

    def test_geo_mismatch_sinaliza_skipped(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_MISMATCH sinaliza extraction_skipped=True."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="moeda USD detectada",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert skipped is True

    def test_geo_redirect_sinaliza_skipped(
        self, scorer: HealthCheckScorer
    ) -> None:
        """GEO_REDIRECT sinaliza extraction_skipped=True."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="redirecionado para conteúdo US",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert skipped is True

    def test_success_nao_sinaliza_skipped(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SUCCESS não sinaliza extraction_skipped."""
        validation = ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=False,
        )

        assert skipped is False

    def test_scraper_error_nao_sinaliza_skipped(
        self, scorer: HealthCheckScorer
    ) -> None:
        """SCRAPER_ERROR não sinaliza extraction_skipped."""
        validation = ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert skipped is False

    def test_network_error_nao_sinaliza_skipped(
        self, scorer: HealthCheckScorer
    ) -> None:
        """NETWORK_ERROR não sinaliza extraction_skipped."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=False,
            network_error=True,
        )

        assert skipped is False


@pytest.mark.unit
class TestHealthCheckScorerEdgeCases:
    """Testes para casos de borda do HealthCheckScorer."""

    def test_validation_result_none_com_extracao_sucesso(
        self, scorer: HealthCheckScorer
    ) -> None:
        """Quando validation_result=None e extração OK, retorna SUCCESS."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.SUCCESS
        assert reason is None
        assert skipped is False

    def test_validation_result_none_com_extracao_falha(
        self, scorer: HealthCheckScorer
    ) -> None:
        """Quando validation_result=None e extração falha, SCRAPER_ERROR."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.SCRAPER_ERROR
        assert reason is None
        assert skipped is False

    def test_network_error_ignora_validation_result(
        self, scorer: HealthCheckScorer
    ) -> None:
        """NETWORK_ERROR ignora validation_result mesmo se GEO_MISMATCH."""
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="idioma inglês",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=True,
            network_error=True,
        )

        assert score == HealthCheckScore.NETWORK_ERROR

    def test_network_error_ignora_extraction_success(
        self, scorer: HealthCheckScorer
    ) -> None:
        """NETWORK_ERROR retornado mesmo com extraction_success=True."""
        score, reason, skipped = scorer.score(
            validation_result=None,
            extraction_success=True,
            network_error=True,
        )

        assert score == HealthCheckScore.NETWORK_ERROR

    def test_validation_success_com_extracao_falha(
        self, scorer: HealthCheckScorer
    ) -> None:
        """Validação SUCCESS mas extração falhou resulta em SCRAPER_ERROR."""
        validation = ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.SCRAPER_ERROR
        assert skipped is False
