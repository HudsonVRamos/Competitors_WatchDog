"""ContentValidator - Valida região, idioma e moeda do conteúdo carregado.

Detecta problemas de geolocalização antes da extração de preços:
- Idioma incorreto (inglês ao invés de português)
- Moeda incorreta (USD ao invés de BRL)
- Redirecionamento para URL/conteúdo de outra região

Implementação genérica (não hardcoded por site) para compatibilidade
futura com BR_Proxy.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from playwright.async_api import Page

from scraping_resilience.models import (
    ContentValidationResult,
    CurrencyDetection,
    HealthCheckScore,
    LanguageDetection,
    RedirectCheckResult,
)

logger = logging.getLogger(__name__)

# Indicadores de idioma português
PT_INDICATORS: list[str] = [
    "Assista",
    "Planos",
    "Assinar",
    "Mensalidade",
    "por mês",
    "Cancelamento",
]

# Indicadores de idioma inglês
EN_INDICATORS: list[str] = [
    "Unlimited",
    "Watch",
    "Starting at",
    "Subscribe",
    "per month",
    "Gift Card",
    "Available at",
]

# Indicadores de redirecionamento para conteúdo US
US_REDIRECT_INDICATORS: list[str] = [
    "Gift Card",
    "Walmart",
    "Best Buy",
    "Sam's Club",
    "Available at",
]

# Regex para detectar preços em Real brasileiro (R$ 29,90 / R$29.90)
_BRL_PRICE_PATTERN = re.compile(
    r"R\$\s*\d{1,3}(?:[.,]\d{2,3})*(?:[.,]\d{2})?",
)

# Regex para detectar preços em Dólar (US$ 6.99 / $9.99)
_USD_PRICE_PATTERN = re.compile(
    r"(?:US\$|USD)\s*\d{1,3}(?:[.,]\d{2,3})*(?:[.,]\d{2})?",
)

# Regex para símbolo $ isolado seguido de preço (sem R antecedente)
_DOLLAR_SIGN_PATTERN = re.compile(
    r"(?<!R)\$\s*\d{1,3}(?:[.,]\d{2,3})*(?:[.,]\d{2})?",
)


class ContentValidator:
    """Valida conteúdo da página para detectar problemas de geo.

    Analisa indicadores de região (idioma, moeda, URL) para classificar
    a página como conteúdo válido (português/BRL) ou com problemas de
    geolocalização (inglês/USD/redirect).

    A implementação é genérica — detecta idioma e moeda por indicadores
    textuais sem lógica hardcoded por site, permitindo funcionamento
    automático quando BR_Proxy for configurado.
    """

    async def validate(
        self,
        page: Page,
        expected_language: str = "pt",
        expected_currency: str = "BRL",
        expected_url_pattern: str | None = None,
    ) -> ContentValidationResult:
        """Valida indicadores de região na página.

        Fluxo:
        1. Obtém texto da página e URL final
        2. Detecta idioma e moeda
        3. Verifica URL redirect (se expected_url_pattern fornecido)
        4. Classifica: GEO_REDIRECT > GEO_MISMATCH > SUCCESS

        Args:
            page: Instância da Page do Playwright.
            expected_language: Idioma esperado ("pt" ou "en").
            expected_currency: Moeda esperada ("BRL" ou "USD").
            expected_url_pattern: Padrão de URL esperado (ex: "/br/").

        Returns:
            ContentValidationResult com health_check_score e razão.
        """
        # Obter texto e URL da página
        page_text = await page.inner_text("body")
        final_url = page.url

        logger.info(
            "ContentValidator: validando página %s "
            "(idioma esperado=%s, moeda esperada=%s)",
            final_url,
            expected_language,
            expected_currency,
        )

        # Detectar idioma e moeda
        language_detection = self.detect_language_indicators(page_text)
        currency_detection = self.detect_currency(page_text)

        # Verificar URL redirect se padrão fornecido
        redirect_check: RedirectCheckResult | None = None
        if expected_url_pattern:
            redirect_check = self.check_url_redirect(
                final_url, expected_url_pattern
            )

        # Coletar todos os indicadores encontrados
        all_indicators: list[str] = []
        all_indicators.extend(language_detection.indicators)
        all_indicators.extend(currency_detection.symbols_found)

        # Classificação: verificar redirect primeiro (prioridade)
        if redirect_check and redirect_check.redirected:
            reason = (
                f"geo_redirect: URL redirecionada - "
                f"{redirect_check.mismatch_reason}. "
                f"URL final: {final_url}"
            )

            # Adicionar indicadores de redirect US ao check
            us_indicators = self._detect_us_redirect_indicators(
                page_text
            )
            if us_indicators:
                all_indicators.extend(us_indicators)
                reason += (
                    f". Indicadores US encontrados: "
                    f"{us_indicators}"
                )

            logger.warning(
                "ContentValidator: GEO_REDIRECT detectado - %s",
                reason,
            )

            return ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_REDIRECT,
                reason=reason,
                detected_language=language_detection.detected_language,
                detected_currency=currency_detection.detected_currency,
                final_url=final_url,
                indicators_found=all_indicators,
            )

        # Verificar indicadores de redirect US no conteúdo
        # (mesmo sem URL redirect, conteúdo pode ser US)
        us_indicators = self._detect_us_redirect_indicators(page_text)
        if us_indicators:
            all_indicators.extend(us_indicators)

            reason = (
                f"geo_redirect: conteúdo US detectado. "
                f"Indicadores encontrados: {us_indicators}"
            )

            logger.warning(
                "ContentValidator: GEO_REDIRECT (conteúdo) - %s",
                reason,
            )

            return ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_REDIRECT,
                reason=reason,
                detected_language=language_detection.detected_language,
                detected_currency=currency_detection.detected_currency,
                final_url=final_url,
                indicators_found=all_indicators,
            )

        # Verificar GEO_MISMATCH: inglês detectado ou USD detectado
        is_english = (
            language_detection.detected_language == "en"
            and expected_language == "pt"
        )
        is_usd = (
            currency_detection.detected_currency == "USD"
            and expected_currency == "BRL"
        )

        if is_english or is_usd:
            reasons: list[str] = []
            if is_english:
                reasons.append(
                    f"idioma inglês detectado "
                    f"(confiança: {language_detection.confidence:.2f}, "
                    f"termos: {language_detection.indicators})"
                )
            if is_usd:
                reasons.append(
                    f"moeda USD detectada "
                    f"(preços: {currency_detection.prices_found})"
                )

            reason = (
                f"geo_mismatch: conteúdo em inglês/USD detectado. "
                + "; ".join(reasons)
            )

            logger.warning(
                "ContentValidator: GEO_MISMATCH - %s", reason
            )

            return ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason=reason,
                detected_language=language_detection.detected_language,
                detected_currency=currency_detection.detected_currency,
                final_url=final_url,
                indicators_found=all_indicators,
            )

        # Tudo ok: conteúdo no idioma e moeda esperados
        logger.info(
            "ContentValidator: SUCCESS - conteúdo válido "
            "(idioma=%s, moeda=%s)",
            language_detection.detected_language,
            currency_detection.detected_currency,
        )

        return ContentValidationResult(
            is_valid=True,
            health_check_score=HealthCheckScore.SUCCESS,
            reason=None,
            detected_language=language_detection.detected_language,
            detected_currency=currency_detection.detected_currency,
            final_url=final_url,
            indicators_found=all_indicators,
        )

    def detect_language_indicators(
        self, page_text: str
    ) -> LanguageDetection:
        """Detecta idioma com base em termos-chave.

        Busca indicadores de português e inglês no texto da página.
        O idioma com maior número de indicadores encontrados é o
        detectado. A confiança é a razão indicadores encontrados /
        total de indicadores possíveis para o idioma detectado.

        Args:
            page_text: Texto completo da página (inner_text do body).

        Returns:
            LanguageDetection com idioma, confiança e indicadores.
        """
        # Buscar indicadores de português
        pt_found: list[str] = [
            indicator
            for indicator in PT_INDICATORS
            if indicator in page_text
        ]

        # Buscar indicadores de inglês
        en_found: list[str] = [
            indicator
            for indicator in EN_INDICATORS
            if indicator in page_text
        ]

        pt_count = len(pt_found)
        en_count = len(en_found)

        # Determinar idioma detectado
        if pt_count > en_count:
            detected = "pt"
            confidence = pt_count / len(PT_INDICATORS)
            indicators = pt_found
        elif en_count > pt_count:
            detected = "en"
            confidence = en_count / len(EN_INDICATORS)
            indicators = en_found
        elif pt_count == en_count and pt_count > 0:
            # Empate: considerar como português (benefit of doubt)
            detected = "pt"
            confidence = pt_count / len(PT_INDICATORS)
            indicators = pt_found
        else:
            # Nenhum indicador encontrado
            detected = "unknown"
            confidence = 0.0
            indicators = []

        logger.debug(
            "ContentValidator: idioma detectado=%s "
            "(confiança=%.2f, pt=%d, en=%d, indicadores=%s)",
            detected,
            confidence,
            pt_count,
            en_count,
            indicators,
        )

        return LanguageDetection(
            detected_language=detected,
            confidence=confidence,
            indicators=indicators,
        )

    def detect_currency(self, page_text: str) -> CurrencyDetection:
        """Detecta moeda presente no conteúdo.

        Busca padrões de preço em BRL (R$) e USD (US$/$).
        A moeda com maior número de ocorrências é a detectada.

        Args:
            page_text: Texto completo da página (inner_text do body).

        Returns:
            CurrencyDetection com moeda, símbolos e preços encontrados.
        """
        # Buscar preços em BRL
        brl_matches = _BRL_PRICE_PATTERN.findall(page_text)

        # Buscar preços em USD (US$ explícito)
        usd_matches = _USD_PRICE_PATTERN.findall(page_text)

        # Buscar $ isolado (sem R antes) como indicador adicional de USD
        dollar_matches = _DOLLAR_SIGN_PATTERN.findall(page_text)

        # Combinar matches USD
        all_usd = usd_matches + dollar_matches

        # Determinar símbolos encontrados
        symbols_found: list[str] = []
        if brl_matches:
            symbols_found.append("R$")
        if usd_matches:
            symbols_found.append("US$")
        if dollar_matches and "US$" not in symbols_found:
            symbols_found.append("$")

        # Coletar todos os preços encontrados
        prices_found: list[str] = brl_matches + all_usd

        # Determinar moeda predominante
        brl_count = len(brl_matches)
        usd_count = len(all_usd)

        if brl_count > usd_count:
            detected = "BRL"
        elif usd_count > brl_count:
            detected = "USD"
        elif brl_count == usd_count and brl_count > 0:
            # Empate: considerar BRL (benefit of doubt para Brasil)
            detected = "BRL"
        else:
            detected = "unknown"

        logger.debug(
            "ContentValidator: moeda detectada=%s "
            "(BRL=%d, USD=%d, símbolos=%s)",
            detected,
            brl_count,
            usd_count,
            symbols_found,
        )

        return CurrencyDetection(
            detected_currency=detected,
            symbols_found=symbols_found,
            prices_found=prices_found,
        )

    def check_url_redirect(
        self, final_url: str, expected_pattern: str
    ) -> RedirectCheckResult:
        """Verifica se URL final diverge do esperado.

        Verifica dois critérios de redirecionamento:
        1. O path esperado (ex: "/br/") NÃO está presente na URL final
        2. O domínio mudou em relação ao esperado

        Args:
            final_url: URL final após eventuais redirecionamentos.
            expected_pattern: Padrão esperado no path (ex: "/br/").

        Returns:
            RedirectCheckResult com status de redirecionamento.
        """
        parsed = urlparse(final_url)
        path = parsed.path
        domain = parsed.netloc

        # Verificar se o padrão esperado está presente no path
        pattern_in_path = expected_pattern in path

        if not pattern_in_path:
            reason = (
                f"path esperado '{expected_pattern}' ausente "
                f"na URL final '{final_url}' "
                f"(path atual: '{path}')"
            )

            logger.debug(
                "ContentValidator: redirect detectado - %s",
                reason,
            )

            return RedirectCheckResult(
                redirected=True,
                final_url=final_url,
                expected_pattern=expected_pattern,
                mismatch_reason=reason,
            )

        # URL contém o padrão esperado — sem redirect
        return RedirectCheckResult(
            redirected=False,
            final_url=final_url,
            expected_pattern=expected_pattern,
            mismatch_reason=None,
        )

    def _detect_us_redirect_indicators(
        self, page_text: str
    ) -> list[str]:
        """Detecta indicadores de redirecionamento para conteúdo US.

        Verifica presença de termos típicos de páginas americanas
        como "Gift Card", "Walmart", "Best Buy", etc.

        Args:
            page_text: Texto da página.

        Returns:
            Lista de indicadores US encontrados.
        """
        found: list[str] = [
            indicator
            for indicator in US_REDIRECT_INDICATORS
            if indicator in page_text
        ]
        return found
