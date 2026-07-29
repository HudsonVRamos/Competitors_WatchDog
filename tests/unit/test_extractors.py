"""Testes unitários para os extractors de preço.

Testa CSSSelectorExtractor, RegexExtractor e AIExtractor com mocks
de Playwright Page e Bedrock.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.models.dataclasses import ExtractionResult
from price_watchdog.scraper.extractors import (
    AIExtractor,
    BaseExtractor,
    CSSSelectorExtractor,
    RegexExtractor,
)


# --- CSSSelectorExtractor ---


class TestCSSSelectorExtractor:
    """Testes para CSSSelectorExtractor."""

    @pytest.fixture
    def extractor(self):
        return CSSSelectorExtractor()

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_extrai_preco_com_sucesso(
        self, extractor, mock_page
    ):
        """Deve extrair preço quando selector encontra elemento."""
        element = AsyncMock()
        element.text_content.return_value = "R$ 1.299,90"
        mock_page.query_selector.return_value = element

        result = await extractor.extract(
            mock_page, ".price", "SKY Play"
        )

        assert result.success is True
        assert result.price == 1299.90
        mock_page.query_selector.assert_called_once_with(".price")

    @pytest.mark.asyncio
    async def test_retorna_not_found_quando_selector_nao_encontra(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando selector não encontra elemento."""
        mock_page.query_selector.return_value = None

        result = await extractor.extract(
            mock_page, ".preco-invalido", "SKY Play"
        )

        assert result.success is False
        assert "não encontrou nenhum elemento" in result.failure_reason

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_texto_vazio(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando elemento não tem texto."""
        element = AsyncMock()
        element.text_content.return_value = ""
        mock_page.query_selector.return_value = element

        result = await extractor.extract(
            mock_page, ".price", "SKY Play"
        )

        assert result.success is False
        assert "não contém texto" in result.failure_reason

    @pytest.mark.asyncio
    async def test_retorna_falha_quando_texto_nao_contem_preco(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando texto não é preço válido."""
        element = AsyncMock()
        element.text_content.return_value = "Indisponível"
        mock_page.query_selector.return_value = element

        result = await extractor.extract(
            mock_page, ".price", "SKY Play"
        )

        assert result.success is False
        assert "não contém preço válido" in result.failure_reason

    @pytest.mark.asyncio
    async def test_trata_excecao_graciosamente(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando ocorre exceção inesperada."""
        mock_page.query_selector.side_effect = Exception(
            "Timeout"
        )

        result = await extractor.extract(
            mock_page, ".price", "SKY Play"
        )

        assert result.success is False
        assert "Erro na extração CSS" in result.failure_reason


# --- RegexExtractor ---


class TestRegexExtractor:
    """Testes para RegexExtractor."""

    @pytest.fixture
    def extractor(self):
        return RegexExtractor()

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_extrai_preco_com_grupo_de_captura(
        self, extractor, mock_page
    ):
        """Deve extrair preço usando grupo de captura do regex."""
        html = '<span class="price">R$ 89,90/mês</span>'
        mock_page.content.return_value = html

        result = await extractor.extract(
            mock_page, r"R\$\s*([\d.,]+)", "DGO Básico"
        )

        assert result.success is True
        assert result.price == 89.90

    @pytest.mark.asyncio
    async def test_extrai_preco_com_formato_completo(
        self, extractor, mock_page
    ):
        """Deve extrair preço no formato brasileiro completo."""
        html = '<div>Preço: R$ 1.299,90</div>'
        mock_page.content.return_value = html

        result = await extractor.extract(
            mock_page, r"Preço:\s*(R\$\s*[\d.,]+)", "SKY+"
        )

        assert result.success is True
        assert result.price == 1299.90

    @pytest.mark.asyncio
    async def test_retorna_not_found_sem_match(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando regex não encontra match."""
        html = "<div>Sem preço aqui</div>"
        mock_page.content.return_value = html

        result = await extractor.extract(
            mock_page, r"R\$\s*([\d.,]+)", "Produto"
        )

        assert result.success is False
        assert "não encontrou correspondência" in result.failure_reason

    @pytest.mark.asyncio
    async def test_retorna_falha_com_regex_invalido(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando padrão regex é inválido."""
        mock_page.content.return_value = "<div>texto</div>"

        result = await extractor.extract(
            mock_page, r"[inválido", "Produto"
        )

        assert result.success is False
        assert "Padrão regex inválido" in result.failure_reason

    @pytest.mark.asyncio
    async def test_retorna_falha_com_pagina_vazia(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando HTML está vazio."""
        mock_page.content.return_value = ""

        result = await extractor.extract(
            mock_page, r"R\$\s*([\d.,]+)", "Produto"
        )

        assert result.success is False
        assert "vazio" in result.failure_reason


# --- AIExtractor ---


class TestAIExtractor:
    """Testes para AIExtractor."""

    @pytest.fixture
    def extractor(self):
        return AIExtractor(region_name="us-east-1")

    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.screenshot.return_value = b"fake_screenshot_bytes"
        return page

    def _make_bedrock_response(self, price_text, confidence):
        """Cria resposta simulada do Bedrock."""
        response_content = json.dumps(
            {"price": price_text, "confidence": confidence}
        )
        return {
            "content": [
                {"type": "text", "text": response_content}
            ]
        }

    @pytest.mark.asyncio
    async def test_extrai_preco_com_alta_confidence(
        self, extractor, mock_page
    ):
        """Deve extrair preço quando confidence >= 80%."""
        bedrock_response = self._make_bedrock_response(
            "R$ 99,90", 95
        )

        with patch.object(
            extractor,
            "_invoke_bedrock_with_retry",
            new_callable=AsyncMock,
        ) as mock_bedrock:
            mock_bedrock.return_value = ExtractionResult(
                success=True, price=99.90, confidence=95.0
            )

            result = await extractor.extract(
                mock_page, "plano básico", "HBO Max"
            )

        assert result.success is True
        assert result.price == 99.90
        assert result.confidence == 95.0

    @pytest.mark.asyncio
    async def test_rejeita_preco_com_baixa_confidence(
        self, extractor, mock_page
    ):
        """Deve rejeitar quando confidence < 80%."""
        with patch.object(
            extractor,
            "_invoke_bedrock_with_retry",
            new_callable=AsyncMock,
        ) as mock_bedrock:
            mock_bedrock.return_value = ExtractionResult(
                success=False,
                confidence=60.0,
                failure_reason="low_confidence",
            )

            result = await extractor.extract(
                mock_page, "plano básico", "HBO Max"
            )

        assert result.success is False
        assert result.confidence == 60.0
        assert result.failure_reason == "low_confidence"

    @pytest.mark.asyncio
    async def test_parse_bedrock_response_alta_confidence(
        self, extractor
    ):
        """Deve parsear resposta do Bedrock com alta confidence."""
        response_json = self._make_bedrock_response(
            "R$ 1.299,90", 92
        )

        result = extractor._parse_bedrock_response(
            response_json, "SKY+"
        )

        assert result.success is True
        assert result.price == 1299.90
        assert result.confidence == 92.0

    @pytest.mark.asyncio
    async def test_parse_bedrock_response_baixa_confidence(
        self, extractor
    ):
        """Deve rejeitar resposta com confidence abaixo de 80%."""
        response_json = self._make_bedrock_response(
            "R$ 49,90", 50
        )

        result = extractor._parse_bedrock_response(
            response_json, "DGO"
        )

        assert result.success is False
        assert result.confidence == 50.0
        assert result.failure_reason == "low_confidence"

    @pytest.mark.asyncio
    async def test_parse_bedrock_response_preco_null(
        self, extractor
    ):
        """Deve retornar falha quando AI não encontra preço."""
        response_json = self._make_bedrock_response(None, 85)

        result = extractor._parse_bedrock_response(
            response_json, "Produto"
        )

        assert result.success is False
        assert "não identificou preço" in result.failure_reason

    @pytest.mark.asyncio
    async def test_parse_bedrock_response_sem_conteudo(
        self, extractor
    ):
        """Deve retornar falha quando resposta não tem conteúdo."""
        response_json = {"content": []}

        result = extractor._parse_bedrock_response(
            response_json, "Produto"
        )

        assert result.success is False
        assert "sem conteúdo" in result.failure_reason

    @pytest.mark.asyncio
    async def test_falha_screenshot_retorna_erro(
        self, extractor, mock_page
    ):
        """Deve retornar falha quando screenshot falha."""
        mock_page.screenshot.return_value = b""

        result = await extractor.extract(
            mock_page, "plano", "Produto"
        )

        assert result.success is False
        assert "screenshot" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_confidence_exatamente_80_aceita(
        self, extractor
    ):
        """Deve aceitar quando confidence é exatamente 80%."""
        response_json = self._make_bedrock_response(
            "R$ 199,90", 80
        )

        result = extractor._parse_bedrock_response(
            response_json, "Produto"
        )

        assert result.success is True
        assert result.price == 199.90
        assert result.confidence == 80.0


# --- BaseExtractor (verifica que é ABC) ---


class TestBaseExtractor:
    """Verifica que BaseExtractor é abstract."""

    def test_nao_pode_instanciar_diretamente(self):
        """BaseExtractor não deve poder ser instanciada."""
        with pytest.raises(TypeError):
            BaseExtractor()
