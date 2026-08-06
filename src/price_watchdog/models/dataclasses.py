"""DTOs e dataclasses para comunicação entre módulos do Price Watchdog.

Estas classes são usadas para transferência de dados entre camadas,
sem acoplamento com SQLAlchemy ou banco de dados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScrapeResult:
    """Resultado completo de uma operação de scraping.

    Attributes:
        extraction_status: Status da extração ("success", "failed", "not_found")
        extracted_price: Preço extraído (None se falhou)
        failure_reason: Razão da falha (None se sucesso)
        screenshot_bytes: Bytes do screenshot capturado
        screenshot_s3_key: Chave S3 após upload do screenshot
    """

    extraction_status: str  # "success" | "failed" | "not_found"
    extracted_price: float | None = None
    failure_reason: str | None = None
    screenshot_bytes: bytes | None = None
    screenshot_s3_key: str | None = None


@dataclass
class ExtractionResult:
    """Resultado de uma estratégia de extração de preço.

    Attributes:
        success: Se a extração foi bem-sucedida
        price: Preço extraído (None se falhou)
        confidence: Nível de confiança do AI extractor (0-100)
        failure_reason: Razão da falha (None se sucesso)
    """

    success: bool
    price: float | None = None
    confidence: float | None = None  # Para AI extractor (0-100)
    failure_reason: str | None = None


@dataclass
class MultiPriceExtractionResult:
    """Resultado de extração múltipla de preços de uma página.

    Usado quando a estratégia é "ai_all": Claude extrai TODOS os
    planos/preços visíveis na página de um concorrente de uma vez.

    Attributes:
        success: Se a extração foi bem-sucedida
        plans: Lista de planos encontrados [{"name": "...", "price": 99.90}]
        failure_reason: Razão da falha (None se sucesso)
        screenshot_bytes: Bytes do screenshot capturado
    """

    success: bool
    plans: list[dict[str, Any]] = field(default_factory=list)
    failure_reason: str | None = None
    screenshot_bytes: bytes | None = None


@dataclass
class ValidationResult:
    """Resultado da validação de um ProductConfig.

    Attributes:
        is_valid: Se a configuração é válida
        errors: Lista de erros encontrados na validação
    """

    is_valid: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class PriceCheckMessage:
    """Mensagem SQS para processamento de extração de preço.

    Contém todos os dados necessários para um worker realizar
    a extração de preço de um concorrente.

    Quando extraction_strategy="ai_all", o worker extrai TODOS os
    planos da página de uma vez (1 mensagem por concorrente).

    Attributes:
        product_config_id: ID do ProductConfig (ou primeiro config do grupo)
        competitor_id: ID do Competitor
        competitor_name: Nome do concorrente
        product_name: Nome do produto (ou vazio para ai_all)
        page_url: URL da página a ser acessada
        extraction_strategy: Estratégia ("css_selector", "regex", "ai", "ai_all")
        selector_or_pattern: Seletor CSS ou padrão regex
        our_price: Preço de referência próprio
        cycle_id: ID do ciclo de monitoramento
        multi_extraction: Flag indicando extração múltipla
        intelligence_enabled: Flag indicando se inteligência competitiva está habilitada
        intelligence_home_url: URL específica da home para extração de comunicação comercial
    """

    product_config_id: str
    competitor_id: str
    competitor_name: str
    product_name: str
    page_url: str
    extraction_strategy: str  # "css_selector" | "regex" | "ai" | "ai_all"
    selector_or_pattern: str
    our_price: float
    cycle_id: str
    multi_extraction: bool = False
    intelligence_enabled: bool = False
    intelligence_home_url: str | None = None


@dataclass
class PriceComparison:
    """Resultado da comparação entre preço extraído e preço de referência.

    Attributes:
        extracted_price: Preço extraído do concorrente
        our_price: Nosso preço de referência
        absolute_difference: Diferença absoluta (extracted - our)
        percentage_difference: Diferença percentual ((extracted - our) / our * 100)
    """

    extracted_price: float
    our_price: float
    absolute_difference: float  # extracted_price - our_price
    percentage_difference: float  # (extracted_price - our_price) / our_price * 100


@dataclass
class AlertThresholds:
    """Thresholds configuráveis para disparo de alertas de preço.

    Attributes:
        price_drop_pct: Percentual mínimo de queda para gerar alerta (padrão 5%)
        price_increase_pct: Percentual mínimo de aumento para gerar alerta (padrão 10%)
    """

    price_drop_pct: float = 5.0
    price_increase_pct: float = 10.0
