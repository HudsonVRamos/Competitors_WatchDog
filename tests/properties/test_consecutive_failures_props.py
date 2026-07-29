"""Property-based tests para detecção de falhas consecutivas.

Feature: price-watchdog, Property 13: Detecção de 3 falhas consecutivas
por competitor

Validates: Requirements 15.6
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    lists,
    sampled_from,
)

from price_watchdog.alerts.alert_service import AlertService


# Estratégia para status de extração válidos
status_strategy = sampled_from(["success", "failed", "not_found"])

# Status considerados falha
FAILURE_STATUSES = {"failed", "not_found"}


@pytest.mark.property
class TestConsecutiveFailuresProperties:
    """Testes de propriedade para AlertService.check_consecutive_failures().

    **Validates: Requirements 15.6**
    """

    @given(
        failures=lists(
            sampled_from(["failed", "not_found"]),
            min_size=3,
            max_size=20,
        ),
        tail=lists(status_strategy, min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_three_or_more_leading_failures_returns_true(
        self, failures: list[str], tail: list[str]
    ) -> None:
        """Property 13: 3+ falhas consecutivas no início → retorna True.

        **Validates: Requirements 15.6**

        Para qualquer sequência onde os primeiros 3 ou mais status são
        falhas ("failed" ou "not_found"), o método deve retornar True
        independentemente dos status subsequentes.
        """
        statuses = failures + tail
        service = AlertService()

        result = service.check_consecutive_failures(statuses, threshold=3)

        assert result is True, (
            f"Esperado True para {len(failures)} falhas consecutivas "
            f"no início, mas obteve False. Statuses: {statuses}"
        )

    @given(
        statuses=lists(status_strategy, min_size=3, max_size=20),
    )
    @settings(max_examples=100)
    def test_less_than_three_leading_failures_returns_false(
        self, statuses: list[str]
    ) -> None:
        """Property 13: <3 falhas consecutivas no início → retorna False.

        **Validates: Requirements 15.6**

        Para qualquer sequência onde há menos de 3 falhas consecutivas
        a partir do início, o método deve retornar False.
        """
        # Contar falhas consecutivas desde o início
        consecutive = 0
        for s in statuses:
            if s in FAILURE_STATUSES:
                consecutive += 1
            else:
                break

        assume(consecutive < 3)

        service = AlertService()
        result = service.check_consecutive_failures(statuses, threshold=3)

        assert result is False, (
            f"Esperado False para {consecutive} falhas consecutivas "
            f"no início, mas obteve True. Statuses: {statuses}"
        )

    @given(
        statuses=lists(status_strategy, min_size=0, max_size=2),
    )
    @settings(max_examples=100)
    def test_list_shorter_than_threshold_returns_false(
        self, statuses: list[str]
    ) -> None:
        """Property 13: Lista menor que threshold → retorna False.

        **Validates: Requirements 15.6**

        Para qualquer lista com menos elementos que o threshold (3),
        o método deve retornar False, mesmo que todos sejam falhas.
        """
        service = AlertService()
        result = service.check_consecutive_failures(statuses, threshold=3)

        assert result is False, (
            f"Esperado False para lista de tamanho {len(statuses)} "
            f"(menor que threshold 3), mas obteve True. "
            f"Statuses: {statuses}"
        )

    @given(
        threshold=integers(min_value=1, max_value=10),
        extra_failures=integers(min_value=0, max_value=5),
        tail=lists(status_strategy, min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_threshold_parameter_respected(
        self, threshold: int, extra_failures: int, tail: list[str]
    ) -> None:
        """Property 13: O parâmetro threshold é respeitado.

        **Validates: Requirements 15.6**

        Para qualquer threshold N, se os primeiros N+ status são
        falhas, o método retorna True. O threshold é configurável.
        """
        # Criar lista com exatamente threshold + extra falhas no início
        failures = ["failed"] * (threshold + extra_failures)
        statuses = failures + tail
        service = AlertService()

        result = service.check_consecutive_failures(
            statuses, threshold=threshold
        )

        assert result is True, (
            f"Esperado True para {len(failures)} falhas consecutivas "
            f"com threshold={threshold}, mas obteve False. "
            f"Statuses: {statuses}"
        )
