"""Testes unitários para invocação do Bedrock no AIIntelligenceExtractor.

Valida os métodos _invoke_bedrock, _classify_error,
_call_bedrock_api e _extract_json_from_response.
Requirements: 10.2, 10.3, 10.5, 5.3
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from price_watchdog.scraper.intelligence_extractor import (
    AIIntelligenceExtractor,
    SchemaValidationError,
)


@pytest.fixture
def extractor() -> AIIntelligenceExtractor:
    """Cria instância do extractor para os testes."""
    return AIIntelligenceExtractor()


@pytest.fixture
def valid_response_data() -> dict:
    """Resposta válida simulada do Bedrock."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "package_composition": [
                            {
                                "plan_name": "Plano X",
                                "default_price": 99.90,
                                "promotional_price": None,
                                "promotional_period_months": None,
                                "linear_channels": 100,
                                "simultaneous_screens": 3,
                                "has_fiber": True,
                                "fiber_speed_mbps": 300,
                                "has_mobile_internet": False,
                                "mobile_speed_mbps": None,
                                "bundled_streamings": [
                                    "Netflix"
                                ],
                            }
                        ],
                        "commercial_communication": {
                            "commercial_keywords": [
                                "oferta",
                                "fibra",
                                "streaming",
                            ],
                            "home_banner_description": (
                                "Banner teste"
                            ),
                            "commercial_positioning_summary": (
                                "Posicionamento teste"
                            ),
                        },
                    }
                ),
            }
        ]
    }


@pytest.fixture
def screenshot_bytes() -> bytes:
    """Bytes simulados de screenshot."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


class TestClassifyError:
    """Testes para _classify_error."""

    def test_timeout_error_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """asyncio.TimeoutError é retentável."""
        error = asyncio.TimeoutError()
        assert extractor._classify_error(error) == "retryable"

    def test_connection_error_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ConnectionError é retentável."""
        error = ConnectionError("Connection refused")
        assert extractor._classify_error(error) == "retryable"

    def test_os_error_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """OSError (rede) é retentável."""
        error = OSError("Network unreachable")
        assert extractor._classify_error(error) == "retryable"

    def test_client_error_429_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ClientError HTTP 429 (throttling) é retentável."""
        error = ClientError(
            error_response={
                "Error": {
                    "Code": "ThrottlingException",
                    "Message": "Rate exceeded",
                },
                "ResponseMetadata": {"HTTPStatusCode": 429},
            },
            operation_name="InvokeModel",
        )
        assert extractor._classify_error(error) == "retryable"

    def test_client_error_500_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ClientError HTTP 500 é retentável."""
        error = ClientError(
            error_response={
                "Error": {
                    "Code": "InternalServerError",
                    "Message": "Internal error",
                },
                "ResponseMetadata": {"HTTPStatusCode": 500},
            },
            operation_name="InvokeModel",
        )
        assert extractor._classify_error(error) == "retryable"

    def test_client_error_503_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ClientError HTTP 503 é retentável."""
        error = ClientError(
            error_response={
                "Error": {
                    "Code": "ServiceUnavailable",
                    "Message": "Service unavailable",
                },
                "ResponseMetadata": {"HTTPStatusCode": 503},
            },
            operation_name="InvokeModel",
        )
        assert extractor._classify_error(error) == "retryable"

    def test_client_error_400_non_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ClientError HTTP 400 é não-retentável."""
        error = ClientError(
            error_response={
                "Error": {
                    "Code": "ValidationException",
                    "Message": "Invalid input",
                },
                "ResponseMetadata": {"HTTPStatusCode": 400},
            },
            operation_name="InvokeModel",
        )
        assert (
            extractor._classify_error(error) == "non_retryable"
        )

    def test_client_error_403_non_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ClientError HTTP 403 é não-retentável."""
        error = ClientError(
            error_response={
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "Access denied",
                },
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            operation_name="InvokeModel",
        )
        assert (
            extractor._classify_error(error) == "non_retryable"
        )

    def test_schema_validation_error(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """SchemaValidationError é schema_error."""
        error = SchemaValidationError("Campo ausente")
        assert (
            extractor._classify_error(error) == "schema_error"
        )

    def test_json_decode_error_non_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """JSONDecodeError é não-retentável."""
        error = json.JSONDecodeError(
            "Expecting value", "doc", 0
        )
        assert (
            extractor._classify_error(error) == "non_retryable"
        )

    def test_value_error_non_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """ValueError é não-retentável."""
        error = ValueError("Invalid value")
        assert (
            extractor._classify_error(error) == "non_retryable"
        )

    def test_unknown_error_retryable(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Erros desconhecidos são retentáveis por padrão."""
        error = RuntimeError("Unknown error")
        assert extractor._classify_error(error) == "retryable"


class TestExtractJsonFromResponse:
    """Testes para _extract_json_from_response."""

    def test_json_direto(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Extrai JSON quando resposta é JSON direto."""
        data = {
            "content": [
                {
                    "type": "text",
                    "text": '{"package_composition": [],'
                    ' "commercial_communication": {}}',
                }
            ]
        }
        result = extractor._extract_json_from_response(data)
        assert result == {
            "package_composition": [],
            "commercial_communication": {},
        }

    def test_json_com_wrapper(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Extrai JSON quando resposta tem texto antes/depois."""
        data = {
            "content": [
                {
                    "type": "text",
                    "text": 'Aqui está: {"package_composition"'
                    ': [], "commercial_communication":'
                    " {}} fim",
                }
            ]
        }
        result = extractor._extract_json_from_response(data)
        assert "package_composition" in result

    def test_resposta_sem_conteudo(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Levanta ValueError se content vazio."""
        data = {"content": []}
        with pytest.raises(ValueError, match="sem conteúdo"):
            extractor._extract_json_from_response(data)

    def test_resposta_sem_texto(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Levanta ValueError se não há bloco de texto."""
        data = {
            "content": [{"type": "image", "data": "abc"}]
        }
        with pytest.raises(ValueError, match="sem texto"):
            extractor._extract_json_from_response(data)

    def test_resposta_sem_json_valido(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Levanta ValueError se texto não contém JSON."""
        data = {
            "content": [
                {
                    "type": "text",
                    "text": "Nenhum JSON aqui",
                }
            ]
        }
        with pytest.raises(
            ValueError, match="não contém JSON"
        ):
            extractor._extract_json_from_response(data)


class TestInvokeBedrockRetry:
    """Testes para _invoke_bedrock com retry e timeout."""

    @pytest.mark.asyncio
    async def test_sucesso_primeira_tentativa(
        self,
        extractor: AIIntelligenceExtractor,
        valid_response_data: dict,
        screenshot_bytes: bytes,
    ) -> None:
        """Retorna resultado na primeira tentativa com sucesso."""
        with patch.object(
            extractor,
            "_call_bedrock_api",
            new_callable=AsyncMock,
            return_value=valid_response_data,
        ):
            result = await extractor._invoke_bedrock(
                screenshot_bytes,
                extractor._build_prompt(),
            )
            assert "package_composition" in result
            assert "commercial_communication" in result

    @pytest.mark.asyncio
    async def test_retry_erro_retentavel(
        self,
        extractor: AIIntelligenceExtractor,
        valid_response_data: dict,
        screenshot_bytes: bytes,
    ) -> None:
        """Faz retry em erros retentáveis e retorna sucesso."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection refused")
            return valid_response_data

        with patch.object(
            extractor,
            "_call_bedrock_api",
            side_effect=mock_call,
        ):
            result = await extractor._invoke_bedrock(
                screenshot_bytes,
                extractor._build_prompt(),
            )
            assert "package_composition" in result
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_esgotado_levanta_excecao(
        self,
        extractor: AIIntelligenceExtractor,
        screenshot_bytes: bytes,
    ) -> None:
        """Levanta exceção após esgotar retries retentáveis."""
        with patch.object(
            extractor,
            "_call_bedrock_api",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Falha permanente"),
        ):
            with pytest.raises(ConnectionError):
                await extractor._invoke_bedrock(
                    screenshot_bytes,
                    extractor._build_prompt(),
                )

    @pytest.mark.asyncio
    async def test_erro_nao_retentavel_falha_imediata(
        self,
        extractor: AIIntelligenceExtractor,
        screenshot_bytes: bytes,
    ) -> None:
        """Erro não-retentável causa falha imediata (sem retry)."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ClientError(
                error_response={
                    "Error": {
                        "Code": "ValidationException",
                        "Message": "Bad request",
                    },
                    "ResponseMetadata": {
                        "HTTPStatusCode": 400,
                    },
                },
                operation_name="InvokeModel",
            )

        with patch.object(
            extractor,
            "_call_bedrock_api",
            side_effect=mock_call,
        ):
            with pytest.raises(ClientError):
                await extractor._invoke_bedrock(
                    screenshot_bytes,
                    extractor._build_prompt(),
                )
            # Apenas 1 chamada — sem retry
            assert call_count == 1

    @pytest.mark.asyncio
    async def test_schema_retry_com_feedback(
        self,
        extractor: AIIntelligenceExtractor,
        valid_response_data: dict,
        screenshot_bytes: bytes,
    ) -> None:
        """Faz schema retry com feedback e retorna sucesso."""
        call_count = 0
        # Resposta inválida (falta commercial_communication)
        invalid_response = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"package_composition": []}
                    ),
                }
            ]
        }

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return invalid_response
            return valid_response_data

        with patch.object(
            extractor,
            "_call_bedrock_api",
            side_effect=mock_call,
        ):
            result = await extractor._invoke_bedrock(
                screenshot_bytes,
                extractor._build_prompt(),
            )
            assert "package_composition" in result
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_schema_retry_esgotado(
        self,
        extractor: AIIntelligenceExtractor,
        screenshot_bytes: bytes,
    ) -> None:
        """Levanta SchemaValidationError após esgotar retries."""
        invalid_response = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"package_composition": []}
                    ),
                }
            ]
        }

        with patch.object(
            extractor,
            "_call_bedrock_api",
            new_callable=AsyncMock,
            return_value=invalid_response,
        ):
            with pytest.raises(SchemaValidationError):
                await extractor._invoke_bedrock(
                    screenshot_bytes,
                    extractor._build_prompt(),
                )

    @pytest.mark.asyncio
    async def test_timeout_global(
        self,
        extractor: AIIntelligenceExtractor,
        screenshot_bytes: bytes,
    ) -> None:
        """Aborta com timeout se exceder TIMEOUT_SECONDS."""
        # Reduzir timeout para teste rápido
        extractor.TIMEOUT_SECONDS = 1

        async def mock_slow_call(*args, **kwargs):
            await asyncio.sleep(5)
            return {}

        with patch.object(
            extractor,
            "_call_bedrock_api",
            side_effect=mock_slow_call,
        ):
            with pytest.raises(
                (asyncio.TimeoutError, TimeoutError)
            ):
                await extractor._invoke_bedrock(
                    screenshot_bytes,
                    extractor._build_prompt(),
                )

    @pytest.mark.asyncio
    async def test_retry_429_com_backoff(
        self,
        extractor: AIIntelligenceExtractor,
        valid_response_data: dict,
        screenshot_bytes: bytes,
    ) -> None:
        """HTTP 429 faz retry com backoff."""
        # Reduzir backoff para teste rápido
        extractor.BACKOFF_BASE = 0.01
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ClientError(
                    error_response={
                        "Error": {
                            "Code": "ThrottlingException",
                            "Message": "Rate exceeded",
                        },
                        "ResponseMetadata": {
                            "HTTPStatusCode": 429,
                        },
                    },
                    operation_name="InvokeModel",
                )
            return valid_response_data

        with patch.object(
            extractor,
            "_call_bedrock_api",
            side_effect=mock_call,
        ):
            result = await extractor._invoke_bedrock(
                screenshot_bytes,
                extractor._build_prompt(),
            )
            assert "package_composition" in result
            assert call_count == 2
