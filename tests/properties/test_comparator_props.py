"""Property-based tests para o PriceComparator.

Feature: price-watchdog, Property 3: Cálculo de comparação de preços

Validates: Requirements 8.1
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import floats

from price_watchdog.comparator.comparator import PriceComparator


# Estratégia para preços positivos realistas (evita valores extremos
# que causem overflow em float)
positive_prices = floats(
    min_value=0.01,
    max_value=1_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)


@pytest.mark.property
class TestPriceComparatorProperties:
    """Testes de propriedade para PriceComparator.compare()."""

    @given(
        extracted_price=positive_prices,
        our_price=positive_prices,
    )
    @settings(max_examples=200)
    def test_absolute_difference_is_extracted_minus_our(
        self, extracted_price: float, our_price: float
    ) -> None:
        """Property 3: absolute_difference == extracted_price - our_price.

        Feature: price-watchdog, Property 3: Cálculo de comparação de preços
        Validates: Requirements 8.1

        Para qualquer par de preços positivos, a diferença absoluta
        deve ser exatamente extracted_price - our_price.
        """
        comparator = PriceComparator()
        result = comparator.compare(extracted_price, our_price)

        expected_absolute = extracted_price - our_price

        assert result.absolute_difference == pytest.approx(
            expected_absolute, rel=1e-9
        ), (
            f"absolute_difference incorreta: "
            f"esperado {expected_absolute}, obtido "
            f"{result.absolute_difference}"
        )

    @given(
        extracted_price=positive_prices,
        our_price=positive_prices,
    )
    @settings(max_examples=200)
    def test_percentage_difference_formula(
        self, extracted_price: float, our_price: float
    ) -> None:
        """Property 3: percentage_difference == (extracted - our) / our * 100.

        Feature: price-watchdog, Property 3: Cálculo de comparação de preços
        Validates: Requirements 8.1

        Para qualquer par de preços positivos, a diferença percentual
        deve seguir a fórmula (extracted - our) / our * 100.
        """
        comparator = PriceComparator()
        result = comparator.compare(extracted_price, our_price)

        expected_pct = (extracted_price - our_price) / our_price * 100

        assert result.percentage_difference == pytest.approx(
            expected_pct, rel=1e-9
        ), (
            f"percentage_difference incorreta: "
            f"esperado {expected_pct}, obtido "
            f"{result.percentage_difference}"
        )

    @given(
        extracted_price=positive_prices,
        our_price=positive_prices,
    )
    @settings(max_examples=200)
    def test_comparison_preserves_input_prices(
        self, extracted_price: float, our_price: float
    ) -> None:
        """Property 3: O resultado preserva os preços de entrada.

        Feature: price-watchdog, Property 3: Cálculo de comparação de preços
        Validates: Requirements 8.1

        O PriceComparison retornado deve conter os mesmos valores
        de extracted_price e our_price passados como argumento.
        """
        comparator = PriceComparator()
        result = comparator.compare(extracted_price, our_price)

        assert result.extracted_price == extracted_price
        assert result.our_price == our_price
