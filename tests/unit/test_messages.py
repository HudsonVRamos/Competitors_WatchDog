"""Testes unitários para serialização/deserialização de PriceCheckMessage."""

import json

import pytest

from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.queue.messages import (
    REQUIRED_FIELDS,
    deserialize_message,
    serialize_message,
)


class TestSerializeMessage:
    """Testes para serialize_message."""

    def _make_message(self) -> PriceCheckMessage:
        """Cria uma mensagem de exemplo para testes."""
        return PriceCheckMessage(
            product_config_id="config-123",
            competitor_id="comp-456",
            competitor_name="HBO Max",
            product_name="Plano Básico",
            page_url="https://hbomax.com/planos",
            extraction_strategy="css_selector",
            selector_or_pattern=".price-value",
            our_price=49.90,
            cycle_id="cycle-789",
        )

    def test_serialize_returns_valid_json(self):
        """Deve retornar uma string JSON válida."""
        msg = self._make_message()
        result = serialize_message(msg)
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_serialize_contains_all_fields(self):
        """JSON serializado deve conter todos os campos obrigatórios."""
        msg = self._make_message()
        result = serialize_message(msg)
        data = json.loads(result)

        for field in REQUIRED_FIELDS:
            assert field in data

    def test_serialize_preserves_values(self):
        """Valores devem ser preservados na serialização."""
        msg = self._make_message()
        result = serialize_message(msg)
        data = json.loads(result)

        assert data["product_config_id"] == "config-123"
        assert data["competitor_id"] == "comp-456"
        assert data["competitor_name"] == "HBO Max"
        assert data["product_name"] == "Plano Básico"
        assert data["page_url"] == "https://hbomax.com/planos"
        assert data["extraction_strategy"] == "css_selector"
        assert data["selector_or_pattern"] == ".price-value"
        assert data["our_price"] == 49.90
        assert data["cycle_id"] == "cycle-789"

    def test_serialize_our_price_as_float(self):
        """our_price deve ser serializado como número."""
        msg = self._make_message()
        result = serialize_message(msg)
        data = json.loads(result)
        assert isinstance(data["our_price"], float)


class TestDeserializeMessage:
    """Testes para deserialize_message."""

    def _make_json(self, **overrides) -> str:
        """Cria JSON válido com possibilidade de sobrescrever campos."""
        data = {
            "product_config_id": "config-123",
            "competitor_id": "comp-456",
            "competitor_name": "HBO Max",
            "product_name": "Plano Básico",
            "page_url": "https://hbomax.com/planos",
            "extraction_strategy": "css_selector",
            "selector_or_pattern": ".price-value",
            "our_price": 49.90,
            "cycle_id": "cycle-789",
        }
        data.update(overrides)
        return json.dumps(data)

    def test_deserialize_returns_price_check_message(self):
        """Deve retornar uma instância de PriceCheckMessage."""
        json_str = self._make_json()
        result = deserialize_message(json_str)
        assert isinstance(result, PriceCheckMessage)

    def test_deserialize_preserves_values(self):
        """Valores devem ser preservados na deserialização."""
        json_str = self._make_json()
        result = deserialize_message(json_str)

        assert result.product_config_id == "config-123"
        assert result.competitor_id == "comp-456"
        assert result.competitor_name == "HBO Max"
        assert result.product_name == "Plano Básico"
        assert result.page_url == "https://hbomax.com/planos"
        assert result.extraction_strategy == "css_selector"
        assert result.selector_or_pattern == ".price-value"
        assert result.our_price == 49.90
        assert result.cycle_id == "cycle-789"

    def test_deserialize_converts_our_price_to_float(self):
        """our_price deve ser convertido para float."""
        json_str = self._make_json(our_price=50)
        result = deserialize_message(json_str)
        assert isinstance(result.our_price, float)
        assert result.our_price == 50.0

    def test_deserialize_invalid_json_raises_value_error(self):
        """JSON inválido deve levantar ValueError."""
        with pytest.raises(ValueError, match="JSON inválido"):
            deserialize_message("not json at all")

    def test_deserialize_none_raises_value_error(self):
        """None como input deve levantar ValueError."""
        with pytest.raises(ValueError, match="JSON inválido"):
            deserialize_message(None)

    def test_deserialize_non_dict_json_raises_value_error(self):
        """JSON que não é objeto (ex: lista) deve levantar ValueError."""
        with pytest.raises(ValueError, match="JSON deve ser um objeto"):
            deserialize_message("[1, 2, 3]")

    def test_deserialize_missing_single_field_raises_value_error(self):
        """Campo obrigatório ausente deve levantar ValueError."""
        data = {
            "product_config_id": "config-123",
            "competitor_id": "comp-456",
            "competitor_name": "HBO Max",
            "product_name": "Plano Básico",
            "page_url": "https://hbomax.com/planos",
            "extraction_strategy": "css_selector",
            "selector_or_pattern": ".price-value",
            "our_price": 49.90,
            # cycle_id ausente
        }
        json_str = json.dumps(data)
        with pytest.raises(ValueError, match="cycle_id"):
            deserialize_message(json_str)

    def test_deserialize_missing_multiple_fields_raises_value_error(self):
        """Múltiplos campos ausentes devem ser listados no erro."""
        data = {
            "product_config_id": "config-123",
            "competitor_id": "comp-456",
        }
        json_str = json.dumps(data)
        with pytest.raises(ValueError, match="Campos obrigatórios ausentes"):
            deserialize_message(json_str)

    def test_deserialize_empty_dict_raises_value_error(self):
        """Dicionário vazio deve levantar ValueError."""
        with pytest.raises(ValueError, match="Campos obrigatórios ausentes"):
            deserialize_message("{}")

    def test_deserialize_extra_fields_are_ignored(self):
        """Campos extras no JSON devem ser ignorados."""
        json_str = self._make_json(extra_field="should_be_ignored")
        result = deserialize_message(json_str)
        assert result.product_config_id == "config-123"


class TestRoundTrip:
    """Testes de round-trip (serializar → deserializar)."""

    def test_roundtrip_preserves_message(self):
        """Serializar e deserializar deve manter a mensagem idêntica."""
        original = PriceCheckMessage(
            product_config_id="config-abc",
            competitor_id="comp-xyz",
            competitor_name="Claro TV+",
            product_name="Plano Família",
            page_url="https://clarotv.com.br/planos",
            extraction_strategy="regex",
            selector_or_pattern=r"R\$\s*(\d+[.,]\d{2})",
            our_price=89.90,
            cycle_id="cycle-001",
        )

        json_str = serialize_message(original)
        restored = deserialize_message(json_str)

        assert restored == original

    def test_roundtrip_with_special_characters(self):
        """Round-trip deve funcionar com caracteres especiais."""
        original = PriceCheckMessage(
            product_config_id="config-ação",
            competitor_id="comp-número",
            competitor_name="Vivo TV — Planos",
            product_name="Plano Básico (HD)",
            page_url="https://vivo.com.br/tv?plano=básico",
            extraction_strategy="ai",
            selector_or_pattern="Encontre o preço mensal",
            our_price=119.90,
            cycle_id="cycle-especial-ñ",
        )

        json_str = serialize_message(original)
        restored = deserialize_message(json_str)

        assert restored == original
