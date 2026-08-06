"""Testes unitários para parsing de resposta JSON e validação de schema.

Valida os métodos _validate_schema, _parse_packages e _parse_communication
do AIIntelligenceExtractor conforme Requirements 5.1, 5.2, 1.4.
"""

import pytest

from price_watchdog.scraper.intelligence_extractor import (
    AIIntelligenceExtractor,
)
from price_watchdog.models.intelligence_dataclasses import (
    PackageCompositionData,
    CommercialCommunicationData,
)


@pytest.fixture
def extractor() -> AIIntelligenceExtractor:
    """Cria instância do extractor para os testes."""
    return AIIntelligenceExtractor()


class TestValidateSchema:
    """Testes para _validate_schema."""

    def test_schema_valido_completo(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Schema com ambos os campos obrigatórios e tipos corretos."""
        data = {
            "package_composition": [
                {"plan_name": "Plano X", "default_price": 99.90}
            ],
            "commercial_communication": {
                "commercial_keywords": ["oferta"],
            },
        }
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is True
        assert reason == ""

    def test_schema_valido_listas_vazias(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Schema com lista vazia e dict vazio são válidos."""
        data = {
            "package_composition": [],
            "commercial_communication": {},
        }
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is True
        assert reason == ""

    def test_schema_sem_package_composition(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Ausência de package_composition deve rejeitar."""
        data = {"commercial_communication": {}}
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False
        assert "package_composition" in reason

    def test_schema_sem_commercial_communication(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Ausência de commercial_communication deve rejeitar."""
        data = {"package_composition": []}
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False
        assert "commercial_communication" in reason

    def test_schema_package_composition_nao_lista(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """package_composition deve ser lista, não dict."""
        data = {
            "package_composition": {},
            "commercial_communication": {},
        }
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False
        assert "lista" in reason

    def test_schema_commercial_communication_nao_dict(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """commercial_communication deve ser dict, não lista."""
        data = {
            "package_composition": [],
            "commercial_communication": [],
        }
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False
        assert "dicionário" in reason

    def test_schema_package_composition_string(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """package_composition como string deve rejeitar."""
        data = {
            "package_composition": "invalid",
            "commercial_communication": {},
        }
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False
        assert "lista" in reason

    def test_schema_vazio(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Dict vazio deve rejeitar."""
        data = {}
        is_valid, reason = extractor._validate_schema(data)
        assert is_valid is False


class TestParsePackages:
    """Testes para _parse_packages."""

    def test_lista_vazia(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Lista vazia retorna lista vazia."""
        result = extractor._parse_packages([])
        assert result == []

    def test_pacote_valido_completo(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Pacote com todos os campos válidos."""
        packages = [
            {
                "plan_name": "Plano X",
                "default_price": 99.90,
                "promotional_price": 79.90,
                "promotional_period_months": 12,
                "linear_channels": 150,
                "simultaneous_screens": 3,
                "has_fiber": True,
                "fiber_speed_mbps": 500,
                "has_mobile_internet": False,
                "mobile_speed_mbps": None,
                "bundled_streamings": [
                    "Netflix", "Disney+", "Paramount+"
                ],
            }
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].plan_name == "Plano X"
        assert result[0].default_price == 99.90
        assert result[0].promotional_price == 79.90
        assert result[0].promotional_period_months == 12
        assert result[0].linear_channels == 150
        assert result[0].simultaneous_screens == 3
        assert result[0].has_fiber is True
        assert result[0].fiber_speed_mbps == 500
        assert result[0].has_mobile_internet is False
        assert result[0].mobile_speed_mbps is None
        assert result[0].bundled_streamings == [
            "Netflix", "Disney+", "Paramount+"
        ]

    def test_limite_20_pacotes(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Máximo de 20 pacotes; excedentes são descartados."""
        packages = [
            {"plan_name": f"Plano {i}", "default_price": 50.0}
            for i in range(25)
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 20

    def test_pacote_sem_plan_name_ignorado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Pacote sem plan_name é ignorado."""
        packages = [
            {"default_price": 99.90},
            {"plan_name": "Plano Y", "default_price": 50.0},
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].plan_name == "Plano Y"

    def test_pacote_plan_name_vazio_ignorado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Pacote com plan_name vazio (espaços) é ignorado."""
        packages = [
            {"plan_name": "   ", "default_price": 99.90},
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 0

    def test_pacote_invalido_ignorado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Pacote com dados de composição inválidos é ignorado."""
        packages = [
            {
                "plan_name": "Plano Inválido",
                "default_price": -10.0,
            },
            {
                "plan_name": "Plano Válido",
                "default_price": 99.90,
            },
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].plan_name == "Plano Válido"

    def test_normaliza_streamings(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Streamings são normalizados (sufixo removido, capitalização)."""
        packages = [
            {
                "plan_name": "Plano Z",
                "bundled_streamings": [
                    "netflix premium",
                    "DISNEY+ basic",
                ],
            }
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].bundled_streamings == [
            "Netflix", "Disney+"
        ]

    def test_bundled_streamings_nao_lista(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """bundled_streamings não-lista é tratado como lista vazia."""
        packages = [
            {
                "plan_name": "Plano W",
                "bundled_streamings": "Netflix",
            }
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].bundled_streamings == []

    def test_pacote_nao_dict_ignorado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Item da lista que não é dict é ignorado."""
        packages = ["invalid", {"plan_name": "OK"}]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].plan_name == "OK"

    def test_pacote_com_campos_null(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Pacote com campos null é aceito normalmente."""
        packages = [
            {
                "plan_name": "Plano Null",
                "default_price": None,
                "promotional_price": None,
                "linear_channels": None,
                "fiber_speed_mbps": None,
            }
        ]
        result = extractor._parse_packages(packages)
        assert len(result) == 1
        assert result[0].default_price is None
        assert result[0].promotional_price is None
        assert result[0].linear_channels is None


class TestParseCommunication:
    """Testes para _parse_communication."""

    def test_comunicacao_completa_valida(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Comunicação com todos os campos válidos."""
        comm_data = {
            "commercial_keywords": [
                "melhor preço",
                "fibra ultra",
                "streaming grátis",
            ],
            "home_banner_description": (
                "Banner com oferta de Black Friday"
            ),
            "commercial_positioning_summary": (
                "Posicionamento focado em preço baixo"
            ),
        }
        result = extractor._parse_communication(comm_data)
        assert isinstance(result, CommercialCommunicationData)
        assert result.commercial_keywords == [
            "melhor preço",
            "fibra ultra",
            "streaming grátis",
        ]
        assert result.keywords_status == "identified"
        assert result.home_banner_description == (
            "Banner com oferta de Black Friday"
        )
        assert result.banner_status == "identified"
        assert result.commercial_positioning_summary == (
            "Posicionamento focado em preço baixo"
        )

    def test_keywords_insuficientes_nao_identificado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Menos de 3 keywords resulta em 'não identificado'."""
        comm_data = {
            "commercial_keywords": ["oferta", "fibra"],
            "home_banner_description": "Banner",
            "commercial_positioning_summary": "Resumo",
        }
        result = extractor._parse_communication(comm_data)
        assert result.commercial_keywords == []
        assert result.keywords_status == "não identificado"

    def test_banner_vazio_nao_identificado(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Banner vazio resulta em status 'não identificado'."""
        comm_data = {
            "commercial_keywords": ["a", "b", "c"],
            "home_banner_description": "",
            "commercial_positioning_summary": "Resumo",
        }
        result = extractor._parse_communication(comm_data)
        assert result.banner_status == "não identificado"

    def test_banner_truncado_500_chars(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Banner é truncado a 500 caracteres."""
        comm_data = {
            "commercial_keywords": ["a", "b", "c"],
            "home_banner_description": "x" * 600,
            "commercial_positioning_summary": "Resumo",
        }
        result = extractor._parse_communication(comm_data)
        assert len(result.home_banner_description) == 500

    def test_positioning_truncado_1000_chars(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Positioning summary é truncado a 1000 caracteres."""
        comm_data = {
            "commercial_keywords": ["a", "b", "c"],
            "home_banner_description": "Banner",
            "commercial_positioning_summary": "y" * 1500,
        }
        result = extractor._parse_communication(comm_data)
        assert len(result.commercial_positioning_summary) == 1000

    def test_campos_ausentes(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Campos ausentes usam defaults (lista vazia, string vazia)."""
        comm_data = {}
        result = extractor._parse_communication(comm_data)
        assert result.commercial_keywords == []
        assert result.keywords_status == "não identificado"
        assert result.home_banner_description == ""
        assert result.banner_status == "não identificado"
        assert result.commercial_positioning_summary == ""

    def test_keywords_nao_lista(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Keywords não-lista é tratado como lista vazia."""
        comm_data = {
            "commercial_keywords": "keyword",
            "home_banner_description": "Banner",
            "commercial_positioning_summary": "Resumo",
        }
        result = extractor._parse_communication(comm_data)
        assert result.commercial_keywords == []
        assert result.keywords_status == "não identificado"

    def test_banner_nao_string(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Banner não-string resulta em string vazia."""
        comm_data = {
            "commercial_keywords": ["a", "b", "c"],
            "home_banner_description": 123,
            "commercial_positioning_summary": "Resumo",
        }
        result = extractor._parse_communication(comm_data)
        assert result.home_banner_description == ""
        assert result.banner_status == "não identificado"
