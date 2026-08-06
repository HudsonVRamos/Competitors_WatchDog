"""Modelos de dados (SQLAlchemy entities e dataclasses).

Exporta entidades ORM e DTOs para uso nos demais módulos.
"""

from price_watchdog.models.dataclasses import (
    AlertThresholds,
    ExtractionResult,
    PriceCheckMessage,
    PriceComparison,
    ScrapeResult,
    ValidationResult,
)
from price_watchdog.models.entities import (
    Base,
    Competitor,
    PriceAlert,
    PriceCycle,
    PriceRecord,
    ProductConfig,
)
from price_watchdog.models.intelligence_dataclasses import (
    CommercialCommunicationData,
    IntelligenceAlert,
    IntelligenceExtractionResult,
    PackageCompositionData,
)
from price_watchdog.models.intelligence_entities import (
    CompetitorIntelligenceRecord,
    PackageComposition,
)

__all__ = [
    # Entidades SQLAlchemy
    "Base",
    "Competitor",
    "ProductConfig",
    "PriceCycle",
    "PriceRecord",
    "PriceAlert",
    # Entidades de Inteligência Competitiva
    "CompetitorIntelligenceRecord",
    "PackageComposition",
    # Dataclasses / DTOs
    "ScrapeResult",
    "ExtractionResult",
    "ValidationResult",
    "PriceCheckMessage",
    "PriceComparison",
    "AlertThresholds",
    # Inteligência Competitiva - DTOs
    "PackageCompositionData",
    "CommercialCommunicationData",
    "IntelligenceExtractionResult",
    "IntelligenceAlert",
]
