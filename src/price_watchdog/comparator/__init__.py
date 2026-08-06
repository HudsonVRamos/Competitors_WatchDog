"""Módulo de comparação de preços e detecção de mudanças."""

from price_watchdog.comparator.comparator import PriceComparator
from price_watchdog.comparator.change_detector import ChangeDetector

__all__ = ["ChangeDetector", "PriceComparator"]
