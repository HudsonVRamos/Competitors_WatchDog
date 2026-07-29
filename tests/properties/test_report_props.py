"""Property-based tests para o ExcelReportGenerator (Traffic Light).

Feature: price-watchdog, Property 5: Classificação Traffic Light determinística

Validates: Requirements 10.2
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import floats

from price_watchdog.reports.excel_report import ExcelReportGenerator


# Estratégia para diferença percentual positiva (somos competitivos)
pct_diff_green = floats(
    min_value=0.001,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
)

# Estratégia para diferença percentual na faixa amarela (-5 < pct_diff <= 0)
pct_diff_yellow = floats(
    min_value=-4.999,
    max_value=0.0,
    allow_nan=False,
    allow_infinity=False,
)

# Estratégia para diferença percentual vermelha (pct_diff <= -5)
pct_diff_red = floats(
    min_value=-500.0,
    max_value=-5.0,
    allow_nan=False,
    allow_infinity=False,
)

# Qualquer diferença percentual válida para teste de determinismo
any_pct_diff = floats(
    min_value=-500.0,
    max_value=500.0,
    allow_nan=False,
    allow_infinity=False,
)


@pytest.mark.property
class TestTrafficLightClassificationProperties:
    """Testes de propriedade para classificação Traffic Light.

    **Validates: Requirements 10.2**

    Property 5: Para qualquer PriceRecord com diferença percentual calculada,
    a classificação de cor deve ser: verde quando our_price < extracted_price
    (somos mais baratos), amarelo quando a diferença absoluta é inferior a 5%,
    e vermelho quando our_price é mais de 5% acima do concorrente.
    """

    @given(pct_diff=pct_diff_green)
    @settings(max_examples=100)
    def test_green_classification_when_competitor_is_more_expensive(
        self, pct_diff: float
    ) -> None:
        """Property 5: pct_diff > 0 → classificação "Competitivo" (verde).

        **Validates: Requirements 10.2**

        Quando a diferença percentual é positiva (concorrente cobra mais),
        a classificação deve ser sempre "Competitivo".
        """
        generator = ExcelReportGenerator()
        status = generator._get_status(pct_diff)

        assert status == "Competitivo", (
            f"Para pct_diff={pct_diff} (positivo, somos mais baratos), "
            f"esperado 'Competitivo', obtido '{status}'"
        )

    @given(pct_diff=pct_diff_yellow)
    @settings(max_examples=100)
    def test_yellow_classification_when_difference_under_5_percent(
        self, pct_diff: float
    ) -> None:
        """Property 5: -5 < pct_diff <= 0 → classificação "Atenção" (amarelo).

        **Validates: Requirements 10.2**

        Quando a diferença percentual está entre -5% e 0% (inclusive zero),
        a classificação deve ser sempre "Atenção".
        """
        generator = ExcelReportGenerator()
        status = generator._get_status(pct_diff)

        assert status == "Atenção", (
            f"Para pct_diff={pct_diff} (entre -5 e 0, diferença < 5%), "
            f"esperado 'Atenção', obtido '{status}'"
        )

    @given(pct_diff=pct_diff_red)
    @settings(max_examples=100)
    def test_red_classification_when_more_than_5_percent_above(
        self, pct_diff: float
    ) -> None:
        """Property 5: pct_diff <= -5 → classificação "Não Competitivo" (vermelho).

        **Validates: Requirements 10.2**

        Quando a diferença percentual é <= -5 (nosso preço mais de 5% acima),
        a classificação deve ser sempre "Não Competitivo".
        """
        generator = ExcelReportGenerator()
        status = generator._get_status(pct_diff)

        assert status == "Não Competitivo", (
            f"Para pct_diff={pct_diff} (<= -5, somos muito mais caros), "
            f"esperado 'Não Competitivo', obtido '{status}'"
        )

    @given(pct_diff=any_pct_diff)
    @settings(max_examples=100)
    def test_classification_is_deterministic(
        self, pct_diff: float
    ) -> None:
        """Property 5: Mesma entrada sempre produz mesma classificação.

        **Validates: Requirements 10.2**

        A classificação Traffic Light é determinística — chamadas
        repetidas com o mesmo pct_diff devem retornar o mesmo resultado.
        """
        generator = ExcelReportGenerator()

        result_1 = generator._get_status(pct_diff)
        result_2 = generator._get_status(pct_diff)
        result_3 = generator._get_status(pct_diff)

        assert result_1 == result_2 == result_3, (
            f"Classificação não-determinística para pct_diff={pct_diff}: "
            f"obtido '{result_1}', '{result_2}', '{result_3}'"
        )

        # Verificar que o resultado é sempre um dos três valores válidos
        assert result_1 in ("Competitivo", "Atenção", "Não Competitivo"), (
            f"Classificação inválida: '{result_1}' "
            f"não é um dos valores esperados"
        )
