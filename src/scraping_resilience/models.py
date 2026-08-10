"""Modelos de dados para o módulo Scraping Resilience.

Contém dataclasses e enums utilizados por todos os componentes do módulo:
- HealthCheckScore: Classificação de saúde de execução
- ComponentType: Tipos de componentes de UI detectáveis
- WaitResult: Resultado de espera inteligente
- CookieConfig: Configuração de cookie de geolocalização
- CookieInjectionResult: Resultado da injeção de cookies
- RetryResult: Resultado de operação com retry
- ContentValidationResult: Resultado de validação de conteúdo/região
- InteractionResult: Resultado de interação com componente customizado
- DiagnosticArtifact: Artefato diagnóstico capturado em erro
- StepScreenshot: Metadados de screenshot de etapa
- LanguageDetection: Resultado de detecção de idioma
- CurrencyDetection: Resultado de detecção de moeda
- RedirectCheckResult: Resultado de verificação de redirecionamento
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthCheckScore(str, Enum):
    """Classificação de saúde de uma execução de scraping."""

    SUCCESS = "SUCCESS"
    GEO_MISMATCH = "GEO_MISMATCH"
    GEO_REDIRECT = "GEO_REDIRECT"
    SCRAPER_ERROR = "SCRAPER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"


class ComponentType(str, Enum):
    """Tipos de componentes de UI detectáveis."""

    NATIVE_SELECT = "native_select"
    REACT_SELECT = "react_select"
    MATERIAL_UI = "material_ui"
    SELECT2 = "select2"
    COMBOBOX = "combobox"
    UNKNOWN = "unknown"


@dataclass
class WaitResult:
    """Resultado de uma espera inteligente."""

    success: bool
    strategy_used: str  # "networkidle" | "selector" | "visible"
    elapsed_ms: int
    timeout_occurred: bool = False


@dataclass
class CookieConfig:
    """Configuração de um cookie de geolocalização para injeção pré-navegação."""

    name: str
    value: str
    domain: str
    path: str = "/"
    url_encode: bool = False


@dataclass
class CookieInjectionResult:
    """Resultado da injeção de cookies de geolocalização."""

    cookies_injected: bool
    cookies_count: int
    modal_suppressed: bool | None = None
    fallback_required: bool = False


@dataclass
class RetryResult:
    """Resultado de uma operação com retry."""

    success: bool
    result: Any = None
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    total_delay_ms: int = 0


@dataclass
class ContentValidationResult:
    """Resultado da validação de conteúdo/região."""

    is_valid: bool
    health_check_score: HealthCheckScore
    reason: str | None = None
    detected_language: str | None = None
    detected_currency: str | None = None
    final_url: str | None = None
    indicators_found: list[str] = field(default_factory=list)


@dataclass
class InteractionResult:
    """Resultado de uma interação com componente customizado."""

    success: bool
    strategy_used: str
    component_type: ComponentType
    error: str | None = None
    value_confirmed: bool = False


@dataclass
class DiagnosticArtifact:
    """Artefato diagnóstico capturado em erro."""

    html_s3_key: str | None = None
    screenshot_s3_key: str | None = None
    final_url: str = ""
    elements_found: list[dict[str, str]] = field(default_factory=list)
    error_message: str = ""
    timestamp: str = ""


@dataclass
class StepScreenshot:
    """Metadados de um screenshot de etapa."""

    step_number: int
    description: str
    s3_key: str
    captured_at: str


@dataclass
class LanguageDetection:
    """Resultado da detecção de idioma."""

    detected_language: str  # "pt" | "en" | "unknown"
    confidence: float  # 0.0-1.0
    indicators: list[str] = field(default_factory=list)  # termos encontrados


@dataclass
class CurrencyDetection:
    """Resultado da detecção de moeda."""

    detected_currency: str  # "BRL" | "USD" | "unknown"
    symbols_found: list[str] = field(default_factory=list)  # ["R$", "US$"]
    prices_found: list[str] = field(default_factory=list)  # ["R$ 29,90", "US$ 6.99"]


@dataclass
class RedirectCheckResult:
    """Resultado da verificação de redirecionamento."""

    redirected: bool
    final_url: str
    expected_pattern: str
    mismatch_reason: str | None = None
