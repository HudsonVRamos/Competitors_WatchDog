"""Property-based tests para AIExtractor confidence threshold.

Valida que o AIExtractor aceita preços se e somente se
confidence >= 80, e rejeita com razão "low_confidence" caso contrário.

Feature: price-watchdog
Validates: Requirements 5.2, 5.3
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from price_watchdog.scraper.extractors import AIExtractor
from price_watchdog.models.dataclasses import ExtractionResult


# --- Estratégias (generators) ---


def valid_price_texts() -> st.SearchStrategy[str]:
    """Gera textos de preço válidos no formato brasileiro.

    Produz strings no formato "R$ X.XXX,XX" que o PriceParser
    consegue parsear com sucesso.
    """
    return st.floats(
        min_value=0.01,
        max_value=99_999.99,
        allow_nan=False,
        allow_infinity=False,
    ).map(lambda x: _format_price(round(x, 2)))


def _format_price(value: float) -> str:
    """Formata um float como preço brasileiro 'R$ X.XXX,XX'."""
    int_part = int(value)
    dec_part = round((value - int_part) * 100)
    int_str = f"{int_part:,}".replace(",", ".")
    dec_str = f"{dec_part:02d}"
    return f"R$ {int_str},{dec_str}"


def confidence_values() -> st.SearchStrategy[float]:
    """Gera valores de confidence entre 0 e 100 (inclusive)."""
    return st.floats(
        min_value=0.0,
        max_value=100.0,
        allow_nan=False,
        allow_infinity=False,
    )


def high_confidence_values() -> st.SearchStrategy[float]:
    """Gera valores de confidence >= 80 (aceitos)."""
    return st.floats(
        min_value=80.0,
        max_value=100.0,
        allow_nan=False,
        allow_infinity=False,
    )


def low_confidence_values() -> st.SearchStrategy[float]:
    """Gera valores de confidence < 80 (rejeitados)."""
    return st.floats(
        min_value=0.0,
        max_value=79.99,
        allow_nan=False,
        allow_infinity=False,
    )


def build_bedrock_response(price_text: str, confidence: float) -> dict:
    """Constrói uma resposta simulada do Bedrock no formato Messages API.

    Args:
        price_text: Texto do preço no formato brasileiro.
        confidence: Valor de confidence (0-100).

    Returns:
        Dict simulando a resposta JSON do Bedrock.
    """
    import json
    json_content = json.dumps({
        "price": price_text,
        "confidence": confidence,
    })
    return {
        "content": [
            {
                "type": "text",
                "text": json_content,
            }
        ]
    }


# --- Property Tests ---


@pytest.mark.property
class TestAIExtractorConfidenceProperties:
    """Property-based tests para threshold de confidence do AIExtractor.

    Feature: price-watchdog, Property 9: Threshold de confidence do AI Extractor
    """

    @settings(max_examples=150)
    @given(
        price=valid_price_texts(),
        confidence=high_confidence_values(),
    )
    def test_property_9_aceita_preco_com_confidence_acima_threshold(
        self, price: str, confidence: float
    ) -> None:
        """Property 9: Confidence >= 80 deve aceitar o preço.

        Para qualquer resposta simulada do Bedrock contendo um preço
        válido e confidence >= 80, o AIExtractor deve aceitar o preço
        e retornar success=True.

        **Validates: Requirements 5.2**
        """
        extractor = AIExtractor()
        response = build_bedrock_response(price, confidence)

        result = extractor._parse_bedrock_response(
            response, "Produto Teste"
        )

        assert result.success is True, (
            f"AIExtractor deveria aceitar preço com confidence "
            f"{confidence:.1f}% >= 80%, mas retornou success=False. "
            f"Preço: '{price}', failure_reason: '{result.failure_reason}'"
        )
        assert result.price is not None, (
            f"AIExtractor aceitou mas price é None. "
            f"Confidence: {confidence:.1f}%, preço: '{price}'"
        )
        assert result.confidence == confidence, (
            f"Confidence retornada ({result.confidence}) difere da "
            f"enviada ({confidence})"
        )

    @settings(max_examples=150)
    @given(
        price=valid_price_texts(),
        confidence=low_confidence_values(),
    )
    def test_property_9_rejeita_preco_com_confidence_abaixo_threshold(
        self, price: str, confidence: float
    ) -> None:
        """Property 9: Confidence < 80 deve rejeitar com "low_confidence".

        Para qualquer resposta simulada do Bedrock contendo um preço
        e confidence < 80, o AIExtractor deve rejeitar a extração
        e retornar status "failed" com razão "low_confidence".

        **Validates: Requirements 5.3**
        """
        extractor = AIExtractor()
        response = build_bedrock_response(price, confidence)

        result = extractor._parse_bedrock_response(
            response, "Produto Teste"
        )

        assert result.success is False, (
            f"AIExtractor deveria rejeitar preço com confidence "
            f"{confidence:.1f}% < 80%, mas retornou success=True. "
            f"Preço: '{price}'"
        )
        assert result.failure_reason == "low_confidence", (
            f"Razão de falha deveria ser 'low_confidence', mas foi "
            f"'{result.failure_reason}'. Confidence: {confidence:.1f}%"
        )
        assert result.confidence == confidence, (
            f"Confidence retornada ({result.confidence}) difere da "
            f"enviada ({confidence})"
        )

    @settings(max_examples=100)
    @given(confidence=confidence_values())
    def test_property_9_threshold_exato_80_bicondicional(
        self, confidence: float
    ) -> None:
        """Property 9: Bicondicional - aceita se e somente se >= 80.

        Para qualquer valor de confidence, o AIExtractor deve
        aceitar o preço se e somente se confidence >= 80.
        Verifica a propriedade bicondicional completa.

        **Validates: Requirements 5.2, 5.3**
        """
        extractor = AIExtractor()
        # Usa um preço fixo válido para isolar o teste da confidence
        price_text = "R$ 99,90"
        response = build_bedrock_response(price_text, confidence)

        result = extractor._parse_bedrock_response(
            response, "Produto Teste"
        )

        if confidence >= 80.0:
            assert result.success is True, (
                f"AIExtractor deveria aceitar com confidence "
                f"{confidence:.2f}% >= 80%, mas rejeitou. "
                f"failure_reason: '{result.failure_reason}'"
            )
        else:
            assert result.success is False, (
                f"AIExtractor deveria rejeitar com confidence "
                f"{confidence:.2f}% < 80%, mas aceitou."
            )
            assert result.failure_reason == "low_confidence", (
                f"Razão deveria ser 'low_confidence', mas foi "
                f"'{result.failure_reason}'"
            )
