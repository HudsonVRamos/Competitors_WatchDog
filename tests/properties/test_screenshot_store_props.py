"""Property-based tests para o ScreenshotStore.

Feature: price-watchdog, Property 10: S3 key contém componentes de identificação

Validates: Requirements 7.2
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from price_watchdog.storage.screenshot_store import ScreenshotStore


# Estratégia para gerar IDs razoáveis: letras, números e pontuação,
# sem caracteres de controle ou strings vazias
reasonable_ids = st.text(
    min_size=1,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
)


@pytest.mark.property
class TestScreenshotStoreProperties:
    """Testes de propriedade para ScreenshotStore._generate_key().

    Verifica que a S3 key gerada contém todos os componentes de
    identificação (cycle_id, competitor_id, timestamp) como substrings.
    """

    @given(
        cycle_id=reasonable_ids,
        competitor_id=reasonable_ids,
        timestamp=reasonable_ids,
    )
    @settings(max_examples=100)
    def test_s3_key_contains_cycle_id(
        self, cycle_id: str, competitor_id: str, timestamp: str
    ) -> None:
        """Property 10: S3 key contém cycle_id como substring.

        Feature: price-watchdog, Property 10: S3 key contém componentes de identificação
        Validates: Requirements 7.2

        Para qualquer cycle_id gerado, a S3 key deve conter
        o cycle_id como substring, garantindo rastreabilidade.
        """
        store = ScreenshotStore(bucket="test-bucket")
        key = store._generate_key(cycle_id, competitor_id, timestamp)

        assert cycle_id in key, (
            f"cycle_id '{cycle_id}' não encontrado na S3 key '{key}'"
        )

    @given(
        cycle_id=reasonable_ids,
        competitor_id=reasonable_ids,
        timestamp=reasonable_ids,
    )
    @settings(max_examples=100)
    def test_s3_key_contains_competitor_id(
        self, cycle_id: str, competitor_id: str, timestamp: str
    ) -> None:
        """Property 10: S3 key contém competitor_id como substring.

        Feature: price-watchdog, Property 10: S3 key contém componentes de identificação
        Validates: Requirements 7.2

        Para qualquer competitor_id gerado, a S3 key deve conter
        o competitor_id como substring, garantindo unicidade.
        """
        store = ScreenshotStore(bucket="test-bucket")
        key = store._generate_key(cycle_id, competitor_id, timestamp)

        assert competitor_id in key, (
            f"competitor_id '{competitor_id}' não encontrado na S3 key '{key}'"
        )

    @given(
        cycle_id=reasonable_ids,
        competitor_id=reasonable_ids,
        timestamp=reasonable_ids,
    )
    @settings(max_examples=100)
    def test_s3_key_contains_timestamp(
        self, cycle_id: str, competitor_id: str, timestamp: str
    ) -> None:
        """Property 10: S3 key contém timestamp como substring.

        Feature: price-watchdog, Property 10: S3 key contém componentes de identificação
        Validates: Requirements 7.2

        Para qualquer timestamp gerado, a S3 key deve conter
        o timestamp como substring, garantindo rastreabilidade temporal.
        """
        store = ScreenshotStore(bucket="test-bucket")
        key = store._generate_key(cycle_id, competitor_id, timestamp)

        assert timestamp in key, (
            f"timestamp '{timestamp}' não encontrado na S3 key '{key}'"
        )

    @given(
        cycle_id=reasonable_ids,
        competitor_id=reasonable_ids,
        timestamp=reasonable_ids,
    )
    @settings(max_examples=100)
    def test_s3_key_contains_all_three_components(
        self, cycle_id: str, competitor_id: str, timestamp: str
    ) -> None:
        """Property 10: S3 key contém todos os três componentes simultaneamente.

        Feature: price-watchdog, Property 10: S3 key contém componentes de identificação
        Validates: Requirements 7.2

        Para qualquer combinação de cycle_id, competitor_id e timestamp,
        a S3 key deve conter todos os três como substrings, garantindo
        unicidade e rastreabilidade completa.
        """
        store = ScreenshotStore(bucket="test-bucket")
        key = store._generate_key(cycle_id, competitor_id, timestamp)

        assert cycle_id in key, (
            f"cycle_id '{cycle_id}' não encontrado na S3 key '{key}'"
        )
        assert competitor_id in key, (
            f"competitor_id '{competitor_id}' não encontrado na S3 key '{key}'"
        )
        assert timestamp in key, (
            f"timestamp '{timestamp}' não encontrado na S3 key '{key}'"
        )
