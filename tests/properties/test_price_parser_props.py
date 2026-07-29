"""Property-based tests para PriceParser.

Valida propriedades universais do parsing de preços brasileiros
usando Hypothesis com mínimo de 100 iterações por propriedade.

Feature: price-watchdog
Validates: Requirements 6.1, 6.2, 6.3
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from price_watchdog.scraper.price_parser import PriceParser


# --- Estratégias (generators) ---

def brazilian_price_floats() -> st.SearchStrategy[float]:
    """Gera valores float positivos com até 2 casas decimais.

    Representa preços válidos no formato brasileiro (ex: 0.01 a 9.999.999,99).
    """
    return st.floats(
        min_value=0.01,
        max_value=9_999_999.99,
        allow_nan=False,
        allow_infinity=False,
    ).map(lambda x: round(x, 2))


def format_brazilian_price(value: float) -> str:
    """Formata um float como preço brasileiro 'R$ X.XXX,XX'.

    Aplica separador de milhares (ponto) e separador decimal (vírgula).
    """
    # Separa parte inteira e decimal
    int_part = int(value)
    dec_part = round((value - int_part) * 100)

    # Formata a parte inteira com separador de milhares (ponto)
    int_str = f"{int_part:,}".replace(",", ".")

    # Formata decimal com 2 dígitos
    dec_str = f"{dec_part:02d}"

    return f"R$ {int_str},{dec_str}"


def non_price_strings() -> st.SearchStrategy[str]:
    """Gera strings que NÃO contêm padrões de preço numérico.

    Exclui strings que contenham sequências de dígitos que possam
    ser interpretadas como preço pelo parser.
    """
    # Alfabeto sem dígitos para garantir que não haja padrão numérico
    alphabet = st.sampled_from(
        list("abcdefghijklmnopqrstuvwxyz"
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
             " !@#%&*()-_=+[]{}|;:'\"<>?/\\~`")
    )
    return st.text(alphabet=alphabet, min_size=0, max_size=100)


# --- Property Tests ---


@pytest.mark.property
class TestPriceParserProperties:
    """Property-based tests para PriceParser.

    Feature: price-watchdog, Property 1: Round-trip de parsing de preço brasileiro
    Feature: price-watchdog, Property 2: Texto sem padrão de preço retorna None
    """

    @settings(max_examples=150)
    @given(value=brazilian_price_floats())
    def test_property_1_roundtrip_parsing_preco_brasileiro(
        self, value: float
    ) -> None:
        """Property 1: Round-trip de parsing de preço brasileiro.

        Para qualquer valor float positivo com até 2 casas decimais,
        ao formatá-lo no padrão monetário brasileiro ("R$ X.XXX,XX")
        e depois aplicar PriceParser.parse(), o resultado deve ser
        igual ao valor original (com tolerância de 0.01).

        **Validates: Requirements 6.1, 6.2**
        """
        # Formata o valor como preço brasileiro
        formatted = format_brazilian_price(value)

        # Aplica o parser
        result = PriceParser.parse(formatted)

        # Verifica round-trip
        assert result is not None, (
            f"PriceParser.parse() retornou None para '{formatted}' "
            f"(valor original: {value})"
        )
        assert abs(result - value) < 0.01, (
            f"Round-trip falhou: valor={value}, "
            f"formatado='{formatted}', parseado={result}, "
            f"diferença={abs(result - value)}"
        )

    @settings(max_examples=150)
    @given(text=non_price_strings())
    def test_property_2_texto_sem_preco_retorna_none(
        self, text: str
    ) -> None:
        """Property 2: Texto sem padrão de preço retorna None.

        Para qualquer string que não contenha nenhuma sequência de
        dígitos separados por vírgula no padrão numérico, o
        PriceParser.parse() deve retornar None.

        **Validates: Requirements 6.3**
        """
        result = PriceParser.parse(text)

        assert result is None, (
            f"PriceParser.parse() deveria retornar None para texto "
            f"sem padrão de preço, mas retornou {result} para '{text}'"
        )
