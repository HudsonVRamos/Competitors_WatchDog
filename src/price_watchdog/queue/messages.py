"""Serialização e deserialização de PriceCheckMessage para SQS.

Converte PriceCheckMessage para JSON string (envio) e de JSON string
de volta para PriceCheckMessage (recebimento), com validação de campos
obrigatórios.
"""

import json
from dataclasses import asdict

from price_watchdog.models.dataclasses import PriceCheckMessage

# Campos obrigatórios que devem estar presentes na mensagem
REQUIRED_FIELDS: tuple[str, ...] = (
    "product_config_id",
    "competitor_id",
    "competitor_name",
    "product_name",
    "page_url",
    "extraction_strategy",
    "selector_or_pattern",
    "our_price",
    "cycle_id",
)


def serialize_message(message: PriceCheckMessage) -> str:
    """Serializa PriceCheckMessage para JSON string.

    Args:
        message: Instância de PriceCheckMessage a ser serializada.

    Returns:
        String JSON com todos os campos da mensagem.
    """
    return json.dumps(asdict(message))


def deserialize_message(json_str: str) -> PriceCheckMessage:
    """Deserializa JSON string para PriceCheckMessage.

    Valida que todos os campos obrigatórios estão presentes
    antes de construir o objeto.

    Args:
        json_str: String JSON contendo os dados da mensagem.

    Returns:
        Instância de PriceCheckMessage com os dados deserializados.

    Raises:
        ValueError: Se o JSON for inválido ou se campos obrigatórios
            estiverem ausentes.
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"JSON inválido: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(
            "JSON deve ser um objeto (dict), "
            f"recebido: {type(data).__name__}"
        )

    missing_fields = [
        field for field in REQUIRED_FIELDS if field not in data
    ]

    if missing_fields:
        raise ValueError(
            "Campos obrigatórios ausentes: "
            f"{', '.join(missing_fields)}"
        )

    return PriceCheckMessage(
        product_config_id=str(data["product_config_id"]),
        competitor_id=str(data["competitor_id"]),
        competitor_name=str(data["competitor_name"]),
        product_name=str(data["product_name"]),
        page_url=str(data["page_url"]),
        extraction_strategy=str(data["extraction_strategy"]),
        selector_or_pattern=str(data["selector_or_pattern"]),
        our_price=float(data["our_price"]),
        cycle_id=str(data["cycle_id"]),
        intelligence_enabled=bool(data.get("intelligence_enabled", False)),
        intelligence_home_url=data.get("intelligence_home_url"),
    )
