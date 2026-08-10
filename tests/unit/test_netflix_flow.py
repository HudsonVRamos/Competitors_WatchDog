"""Testes unitários para NetflixFlow.

Testa o fluxo de validação de região da Netflix:
- GEO_MISMATCH: evidência salva, extração pulada
- SUCCESS: extração prossegue normalmente
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, PropertyMock, patch

from scraping_resilience.competitor_flows.netflix import NetflixFlow
from scraping_resilience.models import (
    ContentValidationResult,
    DiagnosticArtifact,
    HealthCheckScore,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def content_validator() -> AsyncMock:
    """Mock do ContentValidator."""
    return AsyncMock()


@pytest.fixture
def diagnostics_collector() -> AsyncMock:
    """Mock do DiagnosticsCollector."""
    mock = AsyncMock()
    mock.capture_diagnostic = AsyncMock(
        return_value=DiagnosticArtifact(
            html_s3_key="diagnostics/netflix/cycle1/html.html",
            screenshot_s3_key=(
                "diagnostics/netflix/cycle1/screenshot.png"
            ),
            final_url="https://www.netflix.com/br/",
            elements_found=[],
            error_message="geo_mismatch",
            timestamp="2024-01-15T10:00:00+00:00",
        )
    )
    return mock


@pytest.fixture
def health_check_scorer() -> AsyncMock:
    """Mock do HealthCheckScorer."""
    return AsyncMock()


@pytest.fixture
def screenshotter() -> AsyncMock:
    """Mock do StepScreenshotter."""
    mock = AsyncMock()
    mock.capture = AsyncMock(return_value="s3-key-screenshot.png")
    return mock


@pytest.fixture
def netflix_flow(
    content_validator: AsyncMock,
    diagnostics_collector: AsyncMock,
    health_check_scorer: AsyncMock,
    screenshotter: AsyncMock,
) -> NetflixFlow:
    """Instância do NetflixFlow com mocks injetados."""
    return NetflixFlow(
        content_validator=content_validator,
        diagnostics_collector=diagnostics_collector,
        health_check_scorer=health_check_scorer,
        screenshotter=screenshotter,
        competitor_id="netflix",
        cycle_id="cycle_001",
    )


def _make_page_mock(url: str = "https://www.netflix.com/br/") -> AsyncMock:
    """Cria mock de Page do Playwright."""
    page = AsyncMock()
    type(page).url = PropertyMock(return_value=url)
    return page


# ============================================================================
# Testes: execute() — cenário GEO_MISMATCH
# ============================================================================


class TestNetflixFlowGeoMismatch:
    """Testes para cenário GEO_MISMATCH (conteúdo em inglês/USD)."""

    @pytest.mark.asyncio
    async def test_geo_mismatch_returns_failure(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Retorna success=False quando GEO_MISMATCH."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason=(
                    "geo_mismatch: conteúdo em inglês/USD "
                    "detectado. idioma inglês detectado"
                ),
                detected_language="en",
                detected_currency="USD",
                final_url="https://www.netflix.com/br/",
                indicators_found=["Unlimited", "Watch", "US$"],
            )
        )
        page = _make_page_mock()

        result = await netflix_flow.execute(page)

        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert (
            result["health_check_score"]
            == HealthCheckScore.GEO_MISMATCH.value
        )
        assert "geo_mismatch" in result["reason"]

    @pytest.mark.asyncio
    async def test_geo_mismatch_calls_validate_with_pt_brl(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Chama validate() com expected_language=pt, expected_currency=BRL."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason="geo_mismatch detectado",
                detected_language="en",
                detected_currency="USD",
            )
        )
        page = _make_page_mock()

        await netflix_flow.execute(page)

        content_validator.validate.assert_called_once_with(
            page,
            expected_language="pt",
            expected_currency="BRL",
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_captures_diagnostics(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """Captura diagnóstico (HTML + screenshot) no GEO_MISMATCH."""
        reason = (
            "geo_mismatch: idioma inglês detectado "
            "(confiança: 0.71)"
        )
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason=reason,
                detected_language="en",
                detected_currency="USD",
            )
        )
        page = _make_page_mock()

        await netflix_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_called_once_with(
            page,
            reason,
            "netflix",
            "cycle_001",
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_captures_screenshot(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """Captura screenshot de evidência no GEO_MISMATCH."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason="geo_mismatch: moeda USD detectada",
                detected_language="en",
                detected_currency="USD",
            )
        )
        page = _make_page_mock()

        await netflix_flow.execute(page)

        screenshotter.capture.assert_called_once_with(
            page, "geo_mismatch_evidence"
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_with_none_reason_uses_default(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """Usa 'geo_mismatch' como razão padrão quando reason é None."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason=None,
                detected_language="en",
                detected_currency="USD",
            )
        )
        page = _make_page_mock()

        result = await netflix_flow.execute(page)

        # Deve usar fallback "geo_mismatch" no diagnostics
        diagnostics_collector.capture_diagnostic.assert_called_once_with(
            page,
            "geo_mismatch",
            "netflix",
            "cycle_001",
        )
        # Resultado deve ter reason=None (do validation)
        assert result["reason"] is None


# ============================================================================
# Testes: execute() — cenário SUCCESS
# ============================================================================


class TestNetflixFlowSuccess:
    """Testes para cenário SUCCESS (conteúdo em português/BRL)."""

    @pytest.mark.asyncio
    async def test_success_returns_extraction_allowed(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Retorna success=True quando conteúdo validado."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
                reason=None,
                detected_language="pt",
                detected_currency="BRL",
                final_url="https://www.netflix.com/br/",
                indicators_found=["Assista", "Planos", "R$"],
            )
        )
        page = _make_page_mock()

        result = await netflix_flow.execute(page)

        assert result["success"] is True
        assert result["extraction_skipped"] is False
        assert (
            result["health_check_score"]
            == HealthCheckScore.SUCCESS.value
        )

    @pytest.mark.asyncio
    async def test_success_does_not_capture_diagnostics(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """NÃO captura diagnóstico no SUCCESS."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
                reason=None,
                detected_language="pt",
                detected_currency="BRL",
            )
        )
        page = _make_page_mock()

        await netflix_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_captures_validation_screenshot(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """Captura screenshot de confirmação no SUCCESS."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
                reason=None,
                detected_language="pt",
                detected_currency="BRL",
            )
        )
        page = _make_page_mock()

        await netflix_flow.execute(page)

        screenshotter.capture.assert_called_once_with(
            page, "content_validated"
        )

    @pytest.mark.asyncio
    async def test_success_result_has_no_reason(
        self,
        netflix_flow: NetflixFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Resultado SUCCESS não contém campo 'reason'."""
        content_validator.validate = AsyncMock(
            return_value=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
                reason=None,
                detected_language="pt",
                detected_currency="BRL",
            )
        )
        page = _make_page_mock()

        result = await netflix_flow.execute(page)

        assert "reason" not in result
