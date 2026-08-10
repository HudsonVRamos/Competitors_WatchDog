"""Testes unitários para ContentValidator.

Testa detecção de idioma, moeda, redirecionamento de URL
e validação completa de conteúdo/região.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, PropertyMock

from scraping_resilience.content_validator import (
    ContentValidator,
    EN_INDICATORS,
    PT_INDICATORS,
    US_REDIRECT_INDICATORS,
)
from scraping_resilience.models import (
    ContentValidationResult,
    CurrencyDetection,
    HealthCheckScore,
    LanguageDetection,
    RedirectCheckResult,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def validator() -> ContentValidator:
    """Instância do ContentValidator para testes."""
    return ContentValidator()


def _make_page_mock(text: str, url: str) -> AsyncMock:
    """Cria mock de Page do Playwright com texto e URL."""
    page = AsyncMock()
    page.inner_text = AsyncMock(return_value=text)
    type(page).url = PropertyMock(return_value=url)
    return page


# ============================================================================
# Testes: detect_language_indicators
# ============================================================================


class TestDetectLanguageIndicators:
    """Testes para detecção de idioma."""

    def test_detect_portuguese_indicators(
        self, validator: ContentValidator
    ) -> None:
        """Detecta idioma português com indicadores presentes."""
        text = "Assista onde quiser. Planos e preços. Assinar agora."
        result = validator.detect_language_indicators(text)

        assert result.detected_language == "pt"
        assert result.confidence > 0.0
        assert "Assista" in result.indicators
        assert "Planos" in result.indicators
        assert "Assinar" in result.indicators

    def test_detect_english_indicators(
        self, validator: ContentValidator
    ) -> None:
        """Detecta idioma inglês com indicadores presentes."""
        text = (
            "Unlimited movies, TV shows. Watch anywhere. "
            "Starting at US$6.99. Subscribe now."
        )
        result = validator.detect_language_indicators(text)

        assert result.detected_language == "en"
        assert result.confidence > 0.0
        assert "Unlimited" in result.indicators
        assert "Watch" in result.indicators
        assert "Starting at" in result.indicators

    def test_detect_unknown_no_indicators(
        self, validator: ContentValidator
    ) -> None:
        """Retorna unknown quando nenhum indicador é encontrado."""
        text = "Lorem ipsum dolor sit amet."
        result = validator.detect_language_indicators(text)

        assert result.detected_language == "unknown"
        assert result.confidence == 0.0
        assert result.indicators == []

    def test_portuguese_wins_on_tie(
        self, validator: ContentValidator
    ) -> None:
        """Em empate, português tem prioridade (benefit of doubt)."""
        # Um indicador de cada
        text = "Assista Watch"
        result = validator.detect_language_indicators(text)

        assert result.detected_language == "pt"

    def test_confidence_calculation(
        self, validator: ContentValidator
    ) -> None:
        """Confiança é proporção de indicadores encontrados."""
        # 3 de 6 indicadores PT
        text = "Assista aqui. Planos disponíveis. Assinar agora."
        result = validator.detect_language_indicators(text)

        expected_confidence = 3 / len(PT_INDICATORS)
        assert result.confidence == pytest.approx(
            expected_confidence
        )

    def test_empty_text(self, validator: ContentValidator) -> None:
        """Texto vazio retorna unknown."""
        result = validator.detect_language_indicators("")

        assert result.detected_language == "unknown"
        assert result.confidence == 0.0

    def test_case_sensitive_detection(
        self, validator: ContentValidator
    ) -> None:
        """Detecção é case-sensitive (conforme indicadores definidos)."""
        text = "assista planos assinar"  # lowercase
        result = validator.detect_language_indicators(text)

        # Indicadores são "Assista", "Planos", "Assinar" (capitalizados)
        assert result.detected_language == "unknown"

    def test_english_dominates_with_more_indicators(
        self, validator: ContentValidator
    ) -> None:
        """Inglês domina quando tem mais indicadores."""
        text = (
            "Unlimited movies. Watch now. Starting at $9.99. "
            "Subscribe today. per month. Assista"
        )
        result = validator.detect_language_indicators(text)

        assert result.detected_language == "en"
        assert result.confidence > 0.0


# ============================================================================
# Testes: detect_currency
# ============================================================================


class TestDetectCurrency:
    """Testes para detecção de moeda."""

    def test_detect_brl(self, validator: ContentValidator) -> None:
        """Detecta moeda BRL com R$."""
        text = "Plano básico R$ 29,90 por mês. Premium R$ 55,90."
        result = validator.detect_currency(text)

        assert result.detected_currency == "BRL"
        assert "R$" in result.symbols_found
        assert len(result.prices_found) >= 2

    def test_detect_usd_explicit(
        self, validator: ContentValidator
    ) -> None:
        """Detecta moeda USD com US$ explícito."""
        text = "Basic plan US$ 6.99. Premium US$ 15.49."
        result = validator.detect_currency(text)

        assert result.detected_currency == "USD"
        assert "US$" in result.symbols_found
        assert len(result.prices_found) >= 2

    def test_detect_dollar_sign_as_usd(
        self, validator: ContentValidator
    ) -> None:
        """Detecta $ isolado (sem R antes) como USD."""
        text = "Starting at $9.99 per month. Premium $15.49."
        result = validator.detect_currency(text)

        assert result.detected_currency == "USD"
        assert "$" in result.symbols_found

    def test_brl_not_confused_with_dollar(
        self, validator: ContentValidator
    ) -> None:
        """R$ não é confundido com $ isolado."""
        text = "Plano R$ 29,90 por mês."
        result = validator.detect_currency(text)

        assert result.detected_currency == "BRL"
        assert "R$" in result.symbols_found
        # Não deve encontrar $ isolado
        assert "$" not in result.symbols_found

    def test_detect_unknown_no_currency(
        self, validator: ContentValidator
    ) -> None:
        """Retorna unknown quando nenhuma moeda encontrada."""
        text = "Nenhum preço aqui, apenas texto."
        result = validator.detect_currency(text)

        assert result.detected_currency == "unknown"
        assert result.symbols_found == []
        assert result.prices_found == []

    def test_brl_dominates_on_tie(
        self, validator: ContentValidator
    ) -> None:
        """Em empate de contagem, BRL tem prioridade."""
        text = "Plano R$ 29,90. Plan $9.99."
        result = validator.detect_currency(text)

        assert result.detected_currency == "BRL"

    def test_brl_price_formats(
        self, validator: ContentValidator
    ) -> None:
        """Detecta diferentes formatos de preço BRL."""
        text = "R$ 29,90 ou R$55,90 ou R$ 199,90"
        result = validator.detect_currency(text)

        assert result.detected_currency == "BRL"
        assert len(result.prices_found) >= 3

    def test_empty_text_currency(
        self, validator: ContentValidator
    ) -> None:
        """Texto vazio retorna unknown."""
        result = validator.detect_currency("")

        assert result.detected_currency == "unknown"


# ============================================================================
# Testes: check_url_redirect
# ============================================================================


class TestCheckUrlRedirect:
    """Testes para verificação de redirecionamento de URL."""

    def test_no_redirect_pattern_present(
        self, validator: ContentValidator
    ) -> None:
        """Sem redirect quando padrão esperado está no path."""
        result = validator.check_url_redirect(
            "https://www.example.com/br/plans",
            "/br/",
        )

        assert result.redirected is False
        assert result.mismatch_reason is None

    def test_redirect_pattern_absent(
        self, validator: ContentValidator
    ) -> None:
        """Redirect quando padrão esperado NÃO está no path."""
        result = validator.check_url_redirect(
            "https://www.example.com/us/gift-cards",
            "/br/",
        )

        assert result.redirected is True
        assert result.mismatch_reason is not None
        assert "/br/" in result.mismatch_reason

    def test_redirect_stores_final_url(
        self, validator: ContentValidator
    ) -> None:
        """final_url é armazenada no resultado."""
        url = "https://www.paramountplus.com/us/plans"
        result = validator.check_url_redirect(url, "/br/")

        assert result.final_url == url

    def test_redirect_stores_expected_pattern(
        self, validator: ContentValidator
    ) -> None:
        """expected_pattern é armazenada no resultado."""
        result = validator.check_url_redirect(
            "https://example.com/plans",
            "/br/",
        )

        assert result.expected_pattern == "/br/"

    def test_pattern_in_subdirectory(
        self, validator: ContentValidator
    ) -> None:
        """Padrão encontrado em subdiretório é válido."""
        result = validator.check_url_redirect(
            "https://www.example.com/content/br/plans",
            "/br/",
        )

        assert result.redirected is False

    def test_empty_path_redirect(
        self, validator: ContentValidator
    ) -> None:
        """URL sem path (só domínio) é redirect se espera /br/."""
        result = validator.check_url_redirect(
            "https://www.example.com/",
            "/br/",
        )

        assert result.redirected is True


# ============================================================================
# Testes: validate (integração dos métodos)
# ============================================================================


class TestValidate:
    """Testes para validate() — fluxo completo."""

    @pytest.mark.asyncio
    async def test_success_portuguese_brl(
        self, validator: ContentValidator
    ) -> None:
        """SUCCESS quando conteúdo em português com BRL."""
        text = (
            "Assista onde quiser. Planos e preços. "
            "Assinar por R$ 29,90 por mês."
        )
        page = _make_page_mock(
            text, "https://www.netflix.com/br/plans"
        )

        result = await validator.validate(page)

        assert result.is_valid is True
        assert result.health_check_score == HealthCheckScore.SUCCESS
        assert result.reason is None
        assert result.detected_language == "pt"
        assert result.detected_currency == "BRL"

    @pytest.mark.asyncio
    async def test_geo_mismatch_english_content(
        self, validator: ContentValidator
    ) -> None:
        """GEO_MISMATCH quando conteúdo em inglês."""
        text = (
            "Unlimited movies, TV shows. Watch anywhere. "
            "Starting at US$6.99. Subscribe now. per month."
        )
        page = _make_page_mock(
            text, "https://www.netflix.com/br/plans"
        )

        result = await validator.validate(page)

        assert result.is_valid is False
        assert (
            result.health_check_score
            == HealthCheckScore.GEO_MISMATCH
        )
        assert result.reason is not None
        assert "geo_mismatch" in result.reason
        assert result.detected_language == "en"

    @pytest.mark.asyncio
    async def test_geo_mismatch_usd_currency(
        self, validator: ContentValidator
    ) -> None:
        """GEO_MISMATCH quando moeda USD detectada (mesmo sem inglês)."""
        # Texto sem indicadores de idioma claros, mas com USD
        text = "Preço: US$ 6.99 e US$ 15.49. Outros US$ 22.99."
        page = _make_page_mock(
            text, "https://www.netflix.com/br/"
        )

        result = await validator.validate(page)

        assert result.is_valid is False
        assert (
            result.health_check_score
            == HealthCheckScore.GEO_MISMATCH
        )
        assert result.detected_currency == "USD"

    @pytest.mark.asyncio
    async def test_geo_redirect_url_pattern(
        self, validator: ContentValidator
    ) -> None:
        """GEO_REDIRECT quando URL não contém padrão esperado."""
        text = "Some content here."
        page = _make_page_mock(
            text, "https://www.paramountplus.com/us/gift-cards"
        )

        result = await validator.validate(
            page, expected_url_pattern="/br/"
        )

        assert result.is_valid is False
        assert (
            result.health_check_score
            == HealthCheckScore.GEO_REDIRECT
        )
        assert result.reason is not None
        assert "geo_redirect" in result.reason

    @pytest.mark.asyncio
    async def test_geo_redirect_us_content_indicators(
        self, validator: ContentValidator
    ) -> None:
        """GEO_REDIRECT quando indicadores US presentes no conteúdo."""
        text = (
            "Gift Card options. Available at Walmart and Best Buy. "
            "Sam's Club special offer."
        )
        page = _make_page_mock(
            text, "https://www.paramountplus.com/br/"
        )

        result = await validator.validate(
            page, expected_url_pattern="/br/"
        )

        assert result.is_valid is False
        assert (
            result.health_check_score
            == HealthCheckScore.GEO_REDIRECT
        )
        assert "Gift Card" in result.indicators_found

    @pytest.mark.asyncio
    async def test_geo_redirect_priority_over_mismatch(
        self, validator: ContentValidator
    ) -> None:
        """GEO_REDIRECT tem prioridade sobre GEO_MISMATCH."""
        text = (
            "Unlimited Watch. Gift Card at Walmart. "
            "Starting at US$9.99."
        )
        page = _make_page_mock(
            text, "https://www.paramountplus.com/us/plans"
        )

        result = await validator.validate(
            page, expected_url_pattern="/br/"
        )

        # Redirect (URL sem /br/) tem prioridade
        assert result.is_valid is False
        assert (
            result.health_check_score
            == HealthCheckScore.GEO_REDIRECT
        )

    @pytest.mark.asyncio
    async def test_success_no_url_pattern(
        self, validator: ContentValidator
    ) -> None:
        """SUCCESS quando sem expected_url_pattern e conteúdo PT/BRL."""
        text = "Assista. Planos. Assinar. R$ 29,90 por mês."
        page = _make_page_mock(
            text, "https://www.netflix.com/title/123"
        )

        result = await validator.validate(page)

        assert result.is_valid is True
        assert result.health_check_score == HealthCheckScore.SUCCESS

    @pytest.mark.asyncio
    async def test_final_url_always_present(
        self, validator: ContentValidator
    ) -> None:
        """final_url é sempre preenchida no resultado."""
        url = "https://www.example.com/page"
        page = _make_page_mock("Texto simples.", url)

        result = await validator.validate(page)

        assert result.final_url == url

    @pytest.mark.asyncio
    async def test_indicators_found_populated(
        self, validator: ContentValidator
    ) -> None:
        """indicators_found contém todos os indicadores detectados."""
        text = "Assista agora. Planos disponíveis. R$ 29,90."
        page = _make_page_mock(
            text, "https://example.com/br/"
        )

        result = await validator.validate(page)

        # Deve conter indicadores de idioma e moeda
        assert "Assista" in result.indicators_found
        assert "Planos" in result.indicators_found
        assert "R$" in result.indicators_found
