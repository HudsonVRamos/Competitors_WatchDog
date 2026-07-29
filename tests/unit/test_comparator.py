"""Testes unitários para o módulo PriceComparator."""

import pytest

from price_watchdog.comparator.comparator import PriceComparator
from price_watchdog.models.dataclasses import PriceComparison


class TestPriceComparator:
    """Testes para PriceComparator.compare()."""

    def setup_method(self):
        """Inicializa o comparator para cada teste."""
        self.comparator = PriceComparator()

    def test_preco_concorrente_maior(self):
        """Quando concorrente é mais caro, diferença é positiva."""
        result = self.comparator.compare(
            extracted_price=150.0, our_price=100.0
        )

        assert isinstance(result, PriceComparison)
        assert result.extracted_price == 150.0
        assert result.our_price == 100.0
        assert result.absolute_difference == 50.0
        assert result.percentage_difference == 50.0

    def test_preco_concorrente_menor(self):
        """Quando concorrente é mais barato, diferença é negativa."""
        result = self.comparator.compare(
            extracted_price=80.0, our_price=100.0
        )

        assert result.absolute_difference == -20.0
        assert result.percentage_difference == -20.0

    def test_precos_iguais(self):
        """Quando preços são iguais, diferença é zero."""
        result = self.comparator.compare(
            extracted_price=100.0, our_price=100.0
        )

        assert result.absolute_difference == 0.0
        assert result.percentage_difference == 0.0

    def test_diferenca_percentual_calculo(self):
        """Verifica fórmula: (extracted - our) / our * 100."""
        result = self.comparator.compare(
            extracted_price=1299.90, our_price=1199.90
        )

        expected_abs = 1299.90 - 1199.90
        expected_pct = (1299.90 - 1199.90) / 1199.90 * 100

        assert abs(result.absolute_difference - expected_abs) < 0.01
        assert abs(result.percentage_difference - expected_pct) < 0.01

    def test_our_price_zero_raises_error(self):
        """Deve lançar ValueError se our_price for zero."""
        with pytest.raises(ValueError):
            self.comparator.compare(
                extracted_price=100.0, our_price=0.0
            )

    def test_valores_decimais_pequenos(self):
        """Funciona com valores decimais pequenos."""
        result = self.comparator.compare(
            extracted_price=9.99, our_price=10.00
        )

        assert abs(result.absolute_difference - (-0.01)) < 0.001
        assert result.percentage_difference < 0

    def test_valores_grandes(self):
        """Funciona com valores grandes (milhares)."""
        result = self.comparator.compare(
            extracted_price=2599.90, our_price=1999.90
        )

        expected_abs = 2599.90 - 1999.90
        expected_pct = (2599.90 - 1999.90) / 1999.90 * 100

        assert abs(result.absolute_difference - expected_abs) < 0.01
        assert abs(result.percentage_difference - expected_pct) < 0.01
