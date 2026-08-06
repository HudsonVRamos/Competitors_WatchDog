"""Testes unitários para AIIntelligenceExtractor.extract().

Valida o método principal de orquestração da extração de
inteligência competitiva, incluindo cenários de sucesso,
no_packages_found e falha.

Requirements: 1.1, 1.5, 2.1
"""

import pytest
from unittest.mock import AsyncMock, patch

from price_watchdog.scraper.intelligence_extractor import (
    AIIntelligenceExtractor,
)
from price_watchdog.models.intelligence_dataclasses import (
    IntelligenceExtractionResult,
)


@pytest.fixture
def extractor() -> AIIntelligenceExtractor:
    """Cria instância do extractor para os testes."""
    return AIIntelligenceExtractor()


@pytest.fixture
def valid_bedrock_response() -> dict:
    """Resposta válida do Bedrock com pacotes e comunicação."""
    return {
        "package_composition": [
            {
                "plan_name": "Plano Família HD",
                "default_price": 159.90,
                "promotional_price": 119.90,
                "promotional_period_months": 12,
                "linear_channels": 180,
                "simultaneous_screens": 4,
                "has_fiber": True,
                "fiber_speed_mbps": 600,
                "has_mobile_internet": True,
                "mobile_speed_mbps": 50,
                "bundled_streamings": [
                    "Netflix",
                    "Disney+",
                    "Globoplay",
                ],
            }
        ],
        "commercial_communication": {
            "commercial_keywords": [
                "melhor custo-benefício",
                "fibra ultra rápida",
                "streaming grátis",
            ],
            "home_banner_description": (
                "Banner com oferta Black Friday"
            ),
            "commercial_positioning_summary": (
                "Posicionamento focado em preço"
            ),
        },
    }


@pytest.fixture
def empty_packages_response() -> dict:
    """Resposta do Bedrock sem pacotes encontrados."""
    return {
        "package_composition": [],
        "commercial_communication": {
            "commercial_keywords": [
                "oferta",
                "desconto",
                "fibra",
            ],
            "home_banner_description": "Banner genérico",
            "commercial_positioning_summary": "Resumo",
        },
    }


class TestExtractSuccess:
    """Testes para cenários de sucesso do extract()."""

    @pytest.mark.asyncio
    async def test_extract_success_with_packages(
        self,
        extractor: AIIntelligenceExtractor,
        valid_bedrock_response: dict,
    ) -> None:
        """Extração bem-sucedida retorna success com pacotes."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            return_value=valid_bedrock_response,
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Claro",
                home_url="https://www.claro.com.br",
            )

        assert result.success is True
        assert result.status == "success"
        assert len(result.package_compositions) == 1
        assert (
            result.package_compositions[0].plan_name
            == "Plano Família HD"
        )
        assert result.commercial_communication is not None
        assert result.failure_reason is None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_extract_no_packages_found(
        self,
        extractor: AIIntelligenceExtractor,
        empty_packages_response: dict,
    ) -> None:
        """Nenhum pacote encontrado retorna no_packages_found
        sem marcar falha (Requirement 1.5)."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            return_value=empty_packages_response,
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Oi",
            )

        assert result.success is True
        assert result.status == "no_packages_found"
        assert result.package_compositions == []
        assert result.commercial_communication is not None
        assert result.failure_reason is None

    @pytest.mark.asyncio
    async def test_extract_measures_latency(
        self,
        extractor: AIIntelligenceExtractor,
        valid_bedrock_response: dict,
    ) -> None:
        """Latência é medida e retornada no resultado."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            return_value=valid_bedrock_response,
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Vivo",
            )

        assert result.latency_ms >= 0
        assert isinstance(result.latency_ms, float)


class TestExtractFailure:
    """Testes para cenários de falha do extract()."""

    @pytest.mark.asyncio
    async def test_extract_bedrock_exception(
        self,
        extractor: AIIntelligenceExtractor,
    ) -> None:
        """Exceção no Bedrock retorna falha com razão."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Bedrock timeout"),
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Claro",
            )

        assert result.success is False
        assert result.status == "failed"
        assert "Bedrock timeout" in result.failure_reason
        assert result.package_compositions == []
        assert result.commercial_communication is None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_extract_invalid_schema(
        self,
        extractor: AIIntelligenceExtractor,
    ) -> None:
        """Schema inválido retorna falha."""
        invalid_response = {"only_one_field": []}
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            return_value=invalid_response,
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Sky",
            )

        assert result.success is False
        assert result.status == "failed"
        assert "Schema inválido" in result.failure_reason

    @pytest.mark.asyncio
    async def test_extract_preserves_retry_count(
        self,
        extractor: AIIntelligenceExtractor,
    ) -> None:
        """Exceção preserva retry_count no resultado."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Erro de rede"),
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Vivo",
            )

        assert result.retry_count == 0
        assert result.success is False


class TestExtractHomUrlOptional:
    """Testes para o parâmetro home_url opcional."""

    @pytest.mark.asyncio
    async def test_extract_without_home_url(
        self,
        extractor: AIIntelligenceExtractor,
        valid_bedrock_response: dict,
    ) -> None:
        """Extração funciona sem home_url (parâmetro opcional)."""
        with patch.object(
            extractor,
            "_invoke_bedrock",
            new_callable=AsyncMock,
            return_value=valid_bedrock_response,
        ):
            result = await extractor.extract(
                screenshot_bytes=b"fake_screenshot",
                competitor_name="Claro",
            )

        assert result.success is True
