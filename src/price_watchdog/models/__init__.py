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

__all__ = [
    # Entidades SQLAlchemy
    "Base",
    "Competitor",
    "ProductConfig",
    "PriceCycle",
    "PriceRecord",
    "PriceAlert",
    # Dataclasses / DTOs
    "ScrapeResult",
    "ExtractionResult",
    "ValidationResult",
    "PriceCheckMessage",
    "PriceComparison",
    "AlertThresholds",
]
