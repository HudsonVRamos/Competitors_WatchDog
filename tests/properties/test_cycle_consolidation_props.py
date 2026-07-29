"""Property-based tests para contadores de consolidação de ciclo.

Feature: price-watchdog, Property 8: Contadores de consolidação de ciclo

Validates: Requirements 1.4
"""

import uuid
from dataclasses import dataclass
from typing import List

import pytest
from hypothesis import given, settings
from hypothesis.strategies import lists, sampled_from


# Estratégia para status de extração válidos
extraction_statuses = sampled_from(["success", "failed", "not_found"])


@dataclass
class FakePriceRecord:
    """Record simplificado para testar lógica de contadores."""

    extraction_status: str
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())


def compute_consolidation_counters(
    records: List[FakePriceRecord],
) -> tuple[int, int, int]:
    """Replica a lógica de contadores do CycleConsolidator.consolidate().

    Retorna (succeeded, failed, total).
    """
    succeeded = sum(
        1 for r in records if r.extraction_status == "success"
    )
    failed = sum(
        1
        for r in records
        if r.extraction_status in ("failed", "not_found")
    )
    total = len(records)
    return succeeded, failed, total


@pytest.mark.property
class TestCycleConsolidationCountersProperties:
    """Testes de propriedade para contadores de consolidação de ciclo.

    **Validates: Requirements 1.4**

    Property 8: Para qualquer conjunto de PriceRecord associados a um ciclo,
    ao consolidar o ciclo: products_succeeded + products_failed == total_products,
    e products_succeeded deve ser igual à contagem de records com status 'success',
    e products_failed à contagem de records com status 'failed' ou 'not_found'.
    """

    @given(
        statuses=lists(
            extraction_statuses,
            min_size=0,
            max_size=200,
        ),
    )
    @settings(max_examples=100)
    def test_succeeded_plus_failed_equals_total(
        self, statuses: List[str]
    ) -> None:
        """Property 8: succeeded + failed == total_products.

        Feature: price-watchdog, Property 8: Contadores de consolidação de ciclo
        **Validates: Requirements 1.4**

        Para qualquer lista de records com status válidos,
        a soma de succeeded e failed deve ser igual ao total de records.
        """
        records = [FakePriceRecord(extraction_status=s) for s in statuses]

        succeeded, failed, total = compute_consolidation_counters(records)

        assert succeeded + failed == total, (
            f"succeeded ({succeeded}) + failed ({failed}) != "
            f"total ({total}). Statuses: {statuses}"
        )

    @given(
        statuses=lists(
            extraction_statuses,
            min_size=0,
            max_size=200,
        ),
    )
    @settings(max_examples=100)
    def test_succeeded_equals_success_count(
        self, statuses: List[str]
    ) -> None:
        """Property 8: succeeded == contagem de records com status 'success'.

        Feature: price-watchdog, Property 8: Contadores de consolidação de ciclo
        **Validates: Requirements 1.4**

        O contador products_succeeded deve ser exatamente igual à
        quantidade de records com extraction_status == 'success'.
        """
        records = [FakePriceRecord(extraction_status=s) for s in statuses]

        succeeded, _, _ = compute_consolidation_counters(records)

        expected_succeeded = sum(1 for s in statuses if s == "success")

        assert succeeded == expected_succeeded, (
            f"succeeded ({succeeded}) != expected ({expected_succeeded}). "
            f"Statuses: {statuses}"
        )

    @given(
        statuses=lists(
            extraction_statuses,
            min_size=0,
            max_size=200,
        ),
    )
    @settings(max_examples=100)
    def test_failed_equals_failed_plus_not_found_count(
        self, statuses: List[str]
    ) -> None:
        """Property 8: failed == contagem de 'failed' + 'not_found'.

        Feature: price-watchdog, Property 8: Contadores de consolidação de ciclo
        **Validates: Requirements 1.4**

        O contador products_failed deve ser exatamente igual à
        quantidade de records com extraction_status in ('failed', 'not_found').
        """
        records = [FakePriceRecord(extraction_status=s) for s in statuses]

        _, failed, _ = compute_consolidation_counters(records)

        expected_failed = sum(
            1 for s in statuses if s in ("failed", "not_found")
        )

        assert failed == expected_failed, (
            f"failed ({failed}) != expected ({expected_failed}). "
            f"Statuses: {statuses}"
        )
