"""Testes unitários para ParamountFlow.

Testa o fluxo de detecção de redirect para conteúdo US do Paramount+,
incluindo cenários de GEO_REDIRECT, GEO_MISMATCH e SUCCESS.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from scraping_resilience.competitor_flows.paramount import (
    ParamountFlow,
)
from scraping_resilience.content_validator import ContentValidator
from scraping_resilience.diagnostics_collector import (
    DiagnosticsCollector,
)
from scraping_resilience.health_check_scorer import HealthCheckScorer
from scraping_resilience.models import (
    ContentValidationResult,
    DiagnosticArtifact,
    HealthCheckScore,
)
from scraping_resilience.step_screenshotter import StepScreenshotter


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def content_validator() -> AsyncMock:
    """Mock do ContentValidator."""
    return AsyncMock(spec=ContentValidator)


@pytest.fixture
def diagnostics_collector() -> AsyncMock:
    """Mock do DiagnosticsCollector."""
    mock = AsyncMock(spec=DiagnosticsCollector)
    mock.capture_diagnostic.return_value = DiagnosticArtifact(
        html_s3_key="diagnostics/paramount/cycle1/html.html",
        screenshot_s3_key="diagnostics/paramount/cycle1/shot.png",
        final_url="https://www.paramountplus.com/us/gift-cards",
        elements_found=[],
        error_message="geo_redirect",
        timestamp="2024-01-15T10:00:00+00:00",
    )
    return mock


@pytest.fixture
def health_check_scorer() -> MagicMock:
    """Mock do HealthCheckScorer."""
    return MagicMock(spec=HealthCheckScorer)


@pytest.fixture
def screenshotter() -> AsyncMock:
    """Mock do StepScreenshotter."""
    mock = AsyncMock(spec=StepScreenshotter)
    mock.capture.return_value = "paramount/cycle1/step_001_evidence.png"
    return mock


@pytest.fixture
def paramount_flow(
    content_validator: AsyncMock,
    diagnostics_collector: AsyncMock,
    health_check_scorer: MagicMock,
    screenshotter: AsyncMock,
) -> ParamountFlow:
    """Instância do ParamountFlow com dependências mockadas."""
    return ParamountFlow(
        content_validator=content_validator,
        diagnostics_collector=diagnostics_collector,
        health_check_scorer=health_check_scorer,
        screenshotter=screenshotter,
        competitor_id="paramount",
        cycle_id="cycle1",
    )


def _make_page_mock(url: str = "https://www.paramountplus.com/br/") -> AsyncMock:
    """Cria mock de Page do Playwright com URL configurável."""
    page = AsyncMock()
    type(page).url = PropertyMock(return_value=url)
    return page


def _make_validation_result(
    score: HealthCheckScore,
    reason: str | None = None,
    final_url: str = "https://www.paramountplus.com/br/",
    detected_language: str = "pt",
    detected_currency: str = "BRL",
    indicators: list[str] | None = None,
) -> ContentValidationResult:
    """Helper para criar ContentValidationResult."""
    return ContentValidationResult(
        is_valid=(score == HealthCheckScore.SUCCESS),
        health_check_score=score,
        reason=reason,
        detected_language=detected_language,
        detected_currency=detected_currency,
        final_url=final_url,
        indicators_found=indicators or [],
    )


# ============================================================================
# Testes: GEO_REDIRECT
# ============================================================================


class TestParamountFlowGeoRedirect:
    """Testes para cenário GEO_REDIRECT."""

    @pytest.mark.asyncio
    async def test_geo_redirect_url_without_br(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_REDIRECT quando URL final não contém /br/."""
        page = _make_page_mock(
            "https://www.paramountplus.com/us/gift-cards"
        )
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_REDIRECT,
                reason=(
                    "geo_redirect: URL redirecionada - "
                    "path esperado '/br/' ausente na URL final"
                ),
                final_url=(
                    "https://www.paramountplus.com/us/gift-cards"
                ),
            )
        )

        result = await paramount_flow.execute(page)

        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_REDIRECT"
        assert result["reason"] is not None
        assert "geo_redirect" in result["reason"]
        assert result["final_url"] == (
            "https://www.paramountplus.com/us/gift-cards"
        )

    @pytest.mark.asyncio
    async def test_geo_redirect_us_content_indicators(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_REDIRECT quando indicadores US detectados no conteúdo."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_REDIRECT,
                reason=(
                    "geo_redirect: conteúdo US detectado. "
                    "Indicadores encontrados: "
                    "['Gift Card', 'Walmart', 'Best Buy']"
                ),
                indicators=[
                    "Gift Card", "Walmart", "Best Buy"
                ],
            )
        )

        result = await paramount_flow.execute(page)

        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_REDIRECT"

    @pytest.mark.asyncio
    async def test_geo_redirect_captures_diagnostic(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_REDIRECT salva evidência via DiagnosticsCollector."""
        page = _make_page_mock()
        reason = "geo_redirect: URL redirecionada para US"
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_REDIRECT,
                reason=reason,
            )
        )

        await paramount_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_awaited_once_with(
            page, reason, "paramount", "cycle1"
        )

    @pytest.mark.asyncio
    async def test_geo_redirect_captures_screenshot(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_REDIRECT captura screenshot como evidência."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_REDIRECT,
                reason="geo_redirect: redirect detectado",
            )
        )

        await paramount_flow.execute(page)

        screenshotter.capture.assert_awaited_once_with(
            page, "geo_redirect_evidence"
        )

    @pytest.mark.asyncio
    async def test_geo_redirect_calls_validator_with_br_pattern(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Validador é chamado com expected_url_pattern='/br/'."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        content_validator.validate.assert_awaited_once_with(
            page,
            expected_language="pt",
            expected_currency="BRL",
            expected_url_pattern="/br/",
        )


# ============================================================================
# Testes: GEO_MISMATCH
# ============================================================================


class TestParamountFlowGeoMismatch:
    """Testes para cenário GEO_MISMATCH."""

    @pytest.mark.asyncio
    async def test_geo_mismatch_english_content(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_MISMATCH quando conteúdo em inglês detectado."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_MISMATCH,
                reason=(
                    "geo_mismatch: conteúdo em inglês/USD detectado. "
                    "idioma inglês detectado (confiança: 0.71)"
                ),
                detected_language="en",
                detected_currency="USD",
            )
        )

        result = await paramount_flow.execute(page)

        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_MISMATCH"
        assert result["reason"] is not None
        assert "geo_mismatch" in result["reason"]

    @pytest.mark.asyncio
    async def test_geo_mismatch_captures_diagnostic(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_MISMATCH salva evidência via DiagnosticsCollector."""
        page = _make_page_mock()
        reason = "geo_mismatch: moeda USD detectada"
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_MISMATCH,
                reason=reason,
            )
        )

        await paramount_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_awaited_once_with(
            page, reason, "paramount", "cycle1"
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_captures_screenshot(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """GEO_MISMATCH captura screenshot como evidência."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_MISMATCH,
                reason="geo_mismatch: inglês detectado",
            )
        )

        await paramount_flow.execute(page)

        screenshotter.capture.assert_awaited_once_with(
            page, "geo_mismatch_evidence"
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_no_final_url_in_result(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """GEO_MISMATCH não inclui final_url no resultado (sem redirect)."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_MISMATCH,
                reason="geo_mismatch: USD detectado",
            )
        )

        result = await paramount_flow.execute(page)

        assert "final_url" not in result


# ============================================================================
# Testes: SUCCESS
# ============================================================================


class TestParamountFlowSuccess:
    """Testes para cenário SUCCESS."""

    @pytest.mark.asyncio
    async def test_success_valid_content(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """SUCCESS quando conteúdo PT/BRL válido e URL com /br/."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
                detected_language="pt",
                detected_currency="BRL",
            )
        )

        result = await paramount_flow.execute(page)

        assert result["success"] is True
        assert result["extraction_skipped"] is False
        assert result["health_check_score"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_success_no_diagnostics_captured(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """SUCCESS não captura diagnóstico."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_captures_validation_screenshot(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        screenshotter: AsyncMock,
    ) -> None:
        """SUCCESS captura screenshot de validação concluída."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        screenshotter.capture.assert_awaited_once_with(
            page, "content_validated"
        )

    @pytest.mark.asyncio
    async def test_success_no_reason_in_result(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """SUCCESS não inclui reason no resultado."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        result = await paramount_flow.execute(page)

        assert "reason" not in result


# ============================================================================
# Testes: Integração com ContentValidator (parâmetros)
# ============================================================================


class TestParamountFlowValidatorParams:
    """Testes para verificar parâmetros passados ao ContentValidator."""

    @pytest.mark.asyncio
    async def test_validator_called_with_pt_language(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Validador recebe expected_language='pt'."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        call_kwargs = (
            content_validator.validate.call_args.kwargs
        )
        assert call_kwargs["expected_language"] == "pt"

    @pytest.mark.asyncio
    async def test_validator_called_with_brl_currency(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Validador recebe expected_currency='BRL'."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        call_kwargs = (
            content_validator.validate.call_args.kwargs
        )
        assert call_kwargs["expected_currency"] == "BRL"

    @pytest.mark.asyncio
    async def test_validator_called_with_br_url_pattern(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
    ) -> None:
        """Validador recebe expected_url_pattern='/br/'."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.SUCCESS,
            )
        )

        await paramount_flow.execute(page)

        call_kwargs = (
            content_validator.validate.call_args.kwargs
        )
        assert call_kwargs["expected_url_pattern"] == "/br/"


# ============================================================================
# Testes: Fallback de razão no diagnóstico
# ============================================================================


class TestParamountFlowDiagnosticFallback:
    """Testes para fallback de razão quando None."""

    @pytest.mark.asyncio
    async def test_geo_redirect_fallback_reason(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """Usa 'geo_redirect' como fallback quando reason é None."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_REDIRECT,
                reason=None,
            )
        )

        await paramount_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_awaited_once_with(
            page, "geo_redirect", "paramount", "cycle1"
        )

    @pytest.mark.asyncio
    async def test_geo_mismatch_fallback_reason(
        self,
        paramount_flow: ParamountFlow,
        content_validator: AsyncMock,
        diagnostics_collector: AsyncMock,
    ) -> None:
        """Usa 'geo_mismatch' como fallback quando reason é None."""
        page = _make_page_mock()
        content_validator.validate.return_value = (
            _make_validation_result(
                score=HealthCheckScore.GEO_MISMATCH,
                reason=None,
            )
        )

        await paramount_flow.execute(page)

        diagnostics_collector.capture_diagnostic.assert_awaited_once_with(
            page, "geo_mismatch", "paramount", "cycle1"
        )
