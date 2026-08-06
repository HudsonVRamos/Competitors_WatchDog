"""DTOs e dataclasses para inteligência competitiva.

Estas classes são usadas para transferência de dados de composição de pacotes
e comunicação comercial entre camadas, sem acoplamento com SQLAlchemy ou banco.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PackageCompositionData:
    """Dados de composição de um pacote extraído.

    Attributes:
        plan_name: Nome do plano identificado na página
        default_price: Preço regular do pacote (None se não identificado)
        promotional_price: Preço promocional (None se não identificado)
        promotional_period_months: Duração da promoção em meses (None se não identificado)
        linear_channels: Número de canais lineares (None se não identificado)
        simultaneous_screens: Número de telas simultâneas (None se não identificado)
        has_fiber: Se o pacote inclui fibra óptica (None se não identificado)
        fiber_speed_mbps: Velocidade da fibra em Mbps (None se não identificado)
        has_mobile_internet: Se o pacote inclui internet móvel (None se não identificado)
        mobile_speed_mbps: Velocidade da internet móvel em Mbps (None se não identificado)
        bundled_streamings: Lista de streamings incluídos (até 3)
    """

    plan_name: str
    default_price: float | None = None
    promotional_price: float | None = None
    promotional_period_months: int | None = None
    linear_channels: int | None = None
    simultaneous_screens: int | None = None
    has_fiber: bool | None = None
    fiber_speed_mbps: int | None = None
    has_mobile_internet: bool | None = None
    mobile_speed_mbps: int | None = None
    bundled_streamings: list[str] = field(default_factory=list)


@dataclass
class CommercialCommunicationData:
    """Dados de comunicação comercial extraídos.

    Attributes:
        commercial_keywords: Palavras-chave comerciais (3 a 15, max 50 chars cada)
        home_banner_description: Descrição do banner principal (até 500 chars)
        commercial_positioning_summary: Resumo do posicionamento comercial (até 1000 chars)
        keywords_status: Status da extração de keywords ("identified" | "não identificado")
        banner_status: Status da extração de banner ("identified" | "não identificado")
    """

    commercial_keywords: list[str] = field(default_factory=list)
    home_banner_description: str = ""
    commercial_positioning_summary: str = ""
    keywords_status: str = "não identificado"  # "identified" | "não identificado"
    banner_status: str = "não identificado"  # "identified" | "não identificado"


@dataclass
class IntelligenceExtractionResult:
    """Resultado da extração de inteligência competitiva.

    Attributes:
        success: Se a extração foi bem-sucedida
        status: Status da extração ("success" | "failed" | "no_packages_found")
        package_compositions: Lista de composições de pacotes extraídas
        commercial_communication: Dados de comunicação comercial (None se não extraído)
        failure_reason: Razão da falha (None se sucesso)
        retry_count: Número de tentativas realizadas
        latency_ms: Latência total da extração em milissegundos
    """

    success: bool
    status: str  # "success" | "failed" | "no_packages_found"
    package_compositions: list[PackageCompositionData] = field(default_factory=list)
    commercial_communication: CommercialCommunicationData | None = None
    failure_reason: str | None = None
    retry_count: int = 0
    latency_ms: float = 0.0


@dataclass
class IntelligenceAlert:
    """Alerta de mudança em inteligência competitiva.

    Attributes:
        alert_type: Tipo do alerta ("package_composition_change" | "communication_change")
        competitor_name: Nome do concorrente
        attribute_name: Nome do atributo que mudou
        previous_value: Valor anterior (None se primeiro registro)
        current_value: Valor atual (None se removido)
        plan_name: Nome do plano afetado (None para alertas de comunicação)
    """

    alert_type: str  # "package_composition_change" | "communication_change"
    competitor_name: str
    attribute_name: str
    previous_value: str | None = None
    current_value: str | None = None
    plan_name: str | None = None
