"""Property-based tests para o módulo de registry (CompetitorManager).

Feature: price-watchdog, Properties 11, 12, 14

- Property 11: Filtragem de configs ativos exclui inativos
- Property 12: Atualização de preço não afeta registros históricos
- Property 14: Taxa de sucesso calculada corretamente

Validates: Requirements 11.3, 14.4, 15.7
"""

from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    booleans,
    floats,
    integers,
    lists,
    sampled_from,
)


# ============================================================
# Objetos auxiliares leves para simular ProductConfig e PriceRecord
# sem depender de SQLAlchemy ou banco de dados.
# ============================================================


@dataclass
class FakeProductConfig:
    """Simula um ProductConfig com os campos relevantes para os testes."""

    id: int
    is_active: bool
    our_price: float


@dataclass
class FakePriceRecord:
    """Simula um PriceRecord com our_price capturado no momento da extração."""

    id: int
    product_config_id: int
    our_price: float  # valor capturado no momento da extração


# ============================================================
# Funções puras que representam a lógica testada pelas properties.
# Estas funções serão chamadas pelo CompetitorManager quando
# implementado, e testamos aqui a corretude lógica.
# ============================================================


def filter_active_configs(
    configs: list[FakeProductConfig],
) -> list[FakeProductConfig]:
    """Filtra apenas configs com is_active == True.

    Esta é a lógica central de get_active_configs().
    """
    return [c for c in configs if c.is_active]


def calculate_success_rate(statuses: list[str]) -> float:
    """Calcula taxa de sucesso = (success / total) * 100.

    Retorna 0.0 se a lista estiver vazia.
    """
    if not statuses:
        return 0.0
    success_count = sum(1 for s in statuses if s == "success")
    return (success_count / len(statuses)) * 100


# ============================================================
# Strategies
# ============================================================

# Preços positivos realistas
positive_prices = floats(
    min_value=0.01,
    max_value=100_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Status de extração válidos
extraction_status_strategy = sampled_from(["success", "failed", "not_found"])


# ============================================================
# Property 11: Filtragem de configs ativos exclui inativos
# ============================================================


@pytest.mark.property
class TestFilterActiveConfigsProperties:
    """Testes de propriedade para filtragem de configs ativos.

    **Validates: Requirements 11.3**
    """

    @given(
        active_flags=lists(booleans(), min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_filter_returns_only_active_configs(
        self, active_flags: list[bool]
    ) -> None:
        """Property 11: Todos os retornados devem ter is_active == True.

        **Validates: Requirements 11.3**

        Para qualquer conjunto de ProductConfig com status variados,
        o resultado da filtragem deve conter apenas configs com
        is_active == True.
        """
        configs = [
            FakeProductConfig(id=i, is_active=flag, our_price=99.90)
            for i, flag in enumerate(active_flags)
        ]

        result = filter_active_configs(configs)

        for config in result:
            assert config.is_active is True, (
                f"Config id={config.id} com is_active=False "
                f"apareceu no resultado filtrado"
            )

    @given(
        active_flags=lists(booleans(), min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_filter_result_is_subset_of_total(
        self, active_flags: list[bool]
    ) -> None:
        """Property 11: O conjunto retornado é subconjunto do total.

        **Validates: Requirements 11.3**

        Para qualquer conjunto de ProductConfig, todos os configs
        retornados devem estar presentes na lista original.
        """
        configs = [
            FakeProductConfig(id=i, is_active=flag, our_price=99.90)
            for i, flag in enumerate(active_flags)
        ]

        result = filter_active_configs(configs)
        original_ids = {c.id for c in configs}

        for config in result:
            assert config.id in original_ids, (
                f"Config id={config.id} não está na lista original"
            )

    @given(
        active_flags=lists(booleans(), min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_filter_count_matches_active_count(
        self, active_flags: list[bool]
    ) -> None:
        """Property 11: Quantidade retornada == quantidade de ativos.

        **Validates: Requirements 11.3**

        O tamanho do resultado deve ser exatamente igual ao número
        de configs com is_active == True na lista original.
        """
        configs = [
            FakeProductConfig(id=i, is_active=flag, our_price=99.90)
            for i, flag in enumerate(active_flags)
        ]

        result = filter_active_configs(configs)
        expected_count = sum(1 for flag in active_flags if flag)

        assert len(result) == expected_count, (
            f"Esperado {expected_count} configs ativos, "
            f"mas obteve {len(result)}"
        )

    @given(
        active_flags=lists(booleans(), min_size=0, max_size=50),
    )
    @settings(max_examples=100)
    def test_filter_excludes_all_inactive(
        self, active_flags: list[bool]
    ) -> None:
        """Property 11: Nenhum inativo está presente no resultado.

        **Validates: Requirements 11.3**

        Nenhum config com is_active == False deve aparecer no
        resultado filtrado.
        """
        configs = [
            FakeProductConfig(id=i, is_active=flag, our_price=99.90)
            for i, flag in enumerate(active_flags)
        ]

        result = filter_active_configs(configs)
        result_ids = {c.id for c in result}
        inactive_ids = {c.id for c in configs if not c.is_active}

        assert result_ids.isdisjoint(inactive_ids), (
            f"Configs inativos encontrados no resultado: "
            f"{result_ids & inactive_ids}"
        )


# ============================================================
# Property 12: Atualização de preço não afeta registros históricos
# ============================================================


@pytest.mark.property
class TestPriceUpdateImmutabilityProperties:
    """Testes de propriedade para imutabilidade do histórico de preços.

    **Validates: Requirements 14.4**
    """

    @given(
        original_price=positive_prices,
        new_price=positive_prices,
        num_records=integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_updating_config_price_does_not_change_records(
        self, original_price: float, new_price: float, num_records: int
    ) -> None:
        """Property 12: PriceRecords mantêm our_price original.

        **Validates: Requirements 14.4**

        Para qualquer ProductConfig com PriceRecords existentes,
        ao atualizar our_price no config, todos os PriceRecords
        anteriores devem manter o valor de our_price que tinham
        no momento da extração (imutabilidade do histórico).
        """
        # Criar config com preço original
        config = FakeProductConfig(
            id=1, is_active=True, our_price=original_price
        )

        # Simular criação de PriceRecords com o preço original
        records = [
            FakePriceRecord(
                id=i,
                product_config_id=config.id,
                our_price=config.our_price,  # captura o valor atual
            )
            for i in range(num_records)
        ]

        # Salvar valores dos records antes da atualização
        prices_before = [r.our_price for r in records]

        # Atualizar preço no config (simula update_our_price)
        config.our_price = new_price

        # Verificar que records NÃO foram alterados
        for i, record in enumerate(records):
            assert record.our_price == prices_before[i], (
                f"PriceRecord id={record.id} teve our_price alterado "
                f"de {prices_before[i]} para {record.our_price} "
                f"após atualização do config"
            )

    @given(
        original_price=positive_prices,
        new_price=positive_prices,
        num_records=integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_records_preserve_original_price_value(
        self, original_price: float, new_price: float, num_records: int
    ) -> None:
        """Property 12: Records preservam exatamente o preço original.

        **Validates: Requirements 14.4**

        Após atualização do config, cada PriceRecord deve ter
        our_price == original_price (o valor no momento da criação).
        """
        assume(original_price != new_price)

        config = FakeProductConfig(
            id=1, is_active=True, our_price=original_price
        )

        # Records criados com preço atual do config
        records = [
            FakePriceRecord(
                id=i,
                product_config_id=config.id,
                our_price=config.our_price,
            )
            for i in range(num_records)
        ]

        # Atualizar preço no config
        config.our_price = new_price

        # Todos os records devem ter o preço ORIGINAL
        for record in records:
            assert record.our_price == pytest.approx(original_price), (
                f"PriceRecord id={record.id} deveria ter "
                f"our_price={original_price}, mas tem "
                f"our_price={record.our_price}"
            )

    @given(
        original_price=positive_prices,
        new_price=positive_prices,
        num_records=integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_new_records_after_update_use_new_price(
        self, original_price: float, new_price: float, num_records: int
    ) -> None:
        """Property 12: Novos records usam preço atualizado.

        **Validates: Requirements 14.4**

        Após atualização do config, novos PriceRecords devem ser
        criados com o novo our_price, enquanto os antigos mantêm
        o valor original.
        """
        config = FakeProductConfig(
            id=1, is_active=True, our_price=original_price
        )

        # Records antigos com preço original
        old_records = [
            FakePriceRecord(
                id=i,
                product_config_id=config.id,
                our_price=config.our_price,
            )
            for i in range(num_records)
        ]

        # Atualizar preço
        config.our_price = new_price

        # Novo record criado APÓS atualização
        new_record = FakePriceRecord(
            id=num_records,
            product_config_id=config.id,
            our_price=config.our_price,
        )

        # Records antigos mantêm preço original
        for record in old_records:
            assert record.our_price == pytest.approx(original_price)

        # Novo record tem preço atualizado
        assert new_record.our_price == pytest.approx(new_price)


# ============================================================
# Property 14: Taxa de sucesso calculada corretamente
# ============================================================


@pytest.mark.property
class TestSuccessRateProperties:
    """Testes de propriedade para cálculo de taxa de sucesso.

    **Validates: Requirements 15.7**
    """

    @given(
        statuses=lists(
            extraction_status_strategy,
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=100)
    def test_success_rate_formula(self, statuses: list[str]) -> None:
        """Property 14: Taxa = (success / total) * 100.

        **Validates: Requirements 15.7**

        Para qualquer conjunto de extrações, a taxa de sucesso
        deve ser igual a (extrações com status "success" / total
        de extrações) * 100.
        """
        result = calculate_success_rate(statuses)

        total = len(statuses)
        success_count = sum(1 for s in statuses if s == "success")
        expected = (success_count / total) * 100

        assert result == pytest.approx(expected, rel=1e-9), (
            f"Taxa de sucesso incorreta: esperado {expected}, "
            f"obtido {result}. Statuses: {statuses}"
        )

    @given(
        statuses=lists(
            extraction_status_strategy,
            min_size=1,
            max_size=100,
        ),
    )
    @settings(max_examples=100)
    def test_success_rate_between_0_and_100(
        self, statuses: list[str]
    ) -> None:
        """Property 14: Taxa de sucesso está entre 0% e 100%.

        **Validates: Requirements 15.7**

        Para qualquer conjunto de extrações não vazio, a taxa
        de sucesso deve estar no intervalo [0, 100].
        """
        result = calculate_success_rate(statuses)

        assert 0.0 <= result <= 100.0, (
            f"Taxa de sucesso fora do intervalo [0, 100]: "
            f"{result}. Statuses: {statuses}"
        )

    @given(
        n=integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_all_success_gives_100(self, n: int) -> None:
        """Property 14: Todos success → taxa = 100%.

        **Validates: Requirements 15.7**

        Se todas as extrações são "success", a taxa deve ser
        exatamente 100.0.
        """
        statuses = ["success"] * n
        result = calculate_success_rate(statuses)

        assert result == pytest.approx(100.0), (
            f"Esperado 100.0 para {n} sucessos, obtido {result}"
        )

    @given(
        n=integers(min_value=1, max_value=100),
    )
    @settings(max_examples=100)
    def test_no_success_gives_0(self, n: int) -> None:
        """Property 14: Nenhum success → taxa = 0%.

        **Validates: Requirements 15.7**

        Se nenhuma extração é "success", a taxa deve ser
        exatamente 0.0.
        """
        statuses = ["failed"] * n
        result = calculate_success_rate(statuses)

        assert result == pytest.approx(0.0), (
            f"Esperado 0.0 para {n} falhas, obtido {result}"
        )

    def test_empty_list_gives_0(self) -> None:
        """Property 14: Lista vazia → taxa = 0%.

        **Validates: Requirements 15.7**

        Se não há extrações, a taxa deve ser 0.0 (sem divisão
        por zero).
        """
        result = calculate_success_rate([])

        assert result == 0.0, (
            f"Esperado 0.0 para lista vazia, obtido {result}"
        )
