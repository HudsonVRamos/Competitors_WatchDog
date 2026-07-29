"""Property-based tests para o AlertService.

Feature: price-watchdog, Property 4: Alertas baseados em thresholds de variação

Validates: Requirements 9.1, 9.2
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import floats

from price_watchdog.alerts.alert_service import AlertService, PriceAlert
from price_watchdog.models.dataclasses import AlertThresholds


# Estratégia para preços positivos realistas
positive_prices = floats(
    min_value=0.01,
    max_value=1_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Estratégia para thresholds positivos (percentuais entre 0.1% e 99%)
positive_thresholds = floats(
    min_value=0.1,
    max_value=99.0,
    allow_nan=False,
    allow_infinity=False,
)


@pytest.mark.property
class TestAlertServiceThresholdProperties:
    """Testes de propriedade para AlertService.evaluate().

    Property 4: Para qualquer par de preços (preço anterior e preço
    atual de um concorrente) e thresholds configurados, o
    AlertService.evaluate() deve gerar um alerta "price_drop" se e
    somente se a queda percentual exceder o threshold de drop, e um
    alerta "price_increase" se e somente se o aumento percentual
    exceder o threshold de increase.
    """

    @given(
        current_price=positive_prices,
        previous_price=positive_prices,
        our_price=positive_prices,
        drop_threshold=positive_thresholds,
        increase_threshold=positive_thresholds,
    )
    @settings(max_examples=100)
    def test_price_drop_alert_iff_exceeds_threshold(
        self,
        current_price: float,
        previous_price: float,
        our_price: float,
        drop_threshold: float,
        increase_threshold: float,
    ) -> None:
        """Property 4: Alerta price_drop se e somente se queda > threshold.

        Validates: Requirements 9.1, 9.2

        Se a queda percentual (previous -> current) excede o threshold
        de drop, deve gerar alerta "price_drop". Caso contrário, não
        deve gerar esse tipo de alerta.
        """
        # Filtrar para cenário de queda de preço
        assume(current_price < previous_price)

        thresholds = AlertThresholds(
            price_drop_pct=drop_threshold,
            price_increase_pct=increase_threshold,
        )
        service = AlertService()

        pct_change = (
            (current_price - previous_price) / previous_price * 100
        )
        actual_drop_pct = abs(pct_change)

        result = service.evaluate(
            current_price, previous_price, our_price, thresholds
        )

        if actual_drop_pct > drop_threshold:
            assert result is not None, (
                f"Esperava alerta price_drop: queda={actual_drop_pct:.2f}% "
                f"> threshold={drop_threshold:.2f}%"
            )
            assert result.alert_type == "price_drop"
            assert result.threshold_pct == drop_threshold
            assert result.actual_difference_pct == pytest.approx(
                pct_change, rel=1e-9
            )
        else:
            assert result is None, (
                f"Não deveria alertar: queda={actual_drop_pct:.2f}% "
                f"<= threshold={drop_threshold:.2f}%"
            )

    @given(
        current_price=positive_prices,
        previous_price=positive_prices,
        our_price=positive_prices,
        drop_threshold=positive_thresholds,
        increase_threshold=positive_thresholds,
    )
    @settings(max_examples=100)
    def test_price_increase_alert_iff_exceeds_threshold(
        self,
        current_price: float,
        previous_price: float,
        our_price: float,
        drop_threshold: float,
        increase_threshold: float,
    ) -> None:
        """Property 4: Alerta price_increase se e somente se aumento > threshold.

        Validates: Requirements 9.1, 9.2

        Se o aumento percentual (previous -> current) excede o
        threshold de increase, deve gerar alerta "price_increase".
        Caso contrário, não deve gerar esse tipo de alerta.
        """
        # Filtrar para cenário de aumento de preço
        assume(current_price > previous_price)

        thresholds = AlertThresholds(
            price_drop_pct=drop_threshold,
            price_increase_pct=increase_threshold,
        )
        service = AlertService()

        pct_change = (
            (current_price - previous_price) / previous_price * 100
        )

        result = service.evaluate(
            current_price, previous_price, our_price, thresholds
        )

        if pct_change > increase_threshold:
            assert result is not None, (
                f"Esperava alerta price_increase: "
                f"aumento={pct_change:.2f}% "
                f"> threshold={increase_threshold:.2f}%"
            )
            assert result.alert_type == "price_increase"
            assert result.threshold_pct == increase_threshold
            assert result.actual_difference_pct == pytest.approx(
                pct_change, rel=1e-9
            )
        else:
            assert result is None, (
                f"Não deveria alertar: aumento={pct_change:.2f}% "
                f"<= threshold={increase_threshold:.2f}%"
            )

    @given(
        price=positive_prices,
        our_price=positive_prices,
        drop_threshold=positive_thresholds,
        increase_threshold=positive_thresholds,
    )
    @settings(max_examples=100)
    def test_no_alert_when_prices_equal(
        self,
        price: float,
        our_price: float,
        drop_threshold: float,
        increase_threshold: float,
    ) -> None:
        """Property 4: Sem alerta quando preço atual == preço anterior.

        Validates: Requirements 9.1, 9.2

        Se o preço não mudou (current == previous), a variação é 0%
        e nenhum alerta deve ser gerado.
        """
        thresholds = AlertThresholds(
            price_drop_pct=drop_threshold,
            price_increase_pct=increase_threshold,
        )
        service = AlertService()

        result = service.evaluate(price, price, our_price, thresholds)

        assert result is None, (
            "Não deveria gerar alerta quando preço não mudou"
        )

    @given(
        current_price=positive_prices,
        our_price=positive_prices,
        drop_threshold=positive_thresholds,
        increase_threshold=positive_thresholds,
    )
    @settings(max_examples=100)
    def test_no_alert_when_previous_price_is_none(
        self,
        current_price: float,
        our_price: float,
        drop_threshold: float,
        increase_threshold: float,
    ) -> None:
        """Property 4: Sem alerta quando preço anterior é None.

        Validates: Requirements 9.1, 9.2

        Se não há preço anterior (primeira extração), não é possível
        calcular variação e nenhum alerta deve ser gerado.
        """
        thresholds = AlertThresholds(
            price_drop_pct=drop_threshold,
            price_increase_pct=increase_threshold,
        )
        service = AlertService()

        result = service.evaluate(
            current_price, None, our_price, thresholds
        )

        assert result is None, (
            "Não deveria gerar alerta sem preço anterior"
        )
