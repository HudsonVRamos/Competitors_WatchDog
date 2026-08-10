"""Testes unitários para DiagnosticsCollector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraping_resilience.diagnostics_collector import DiagnosticsCollector
from scraping_resilience.models import DiagnosticArtifact


class TestCaptureHtml:
    """Testes para captura e truncamento de HTML."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_html_menor_que_limite_nao_trunca(self) -> None:
        """HTML menor que 5MB é preservado integralmente."""
        page = AsyncMock()
        page.content = AsyncMock(return_value="<html><body>ok</body></html>")

        result = await self.collector._capture_html(page)

        assert result == b"<html><body>ok</body></html>"

    @pytest.mark.asyncio
    async def test_html_maior_que_5mb_trunca(self) -> None:
        """HTML maior que 5MB é truncado para exatamente 5MB."""
        # Criar conteúdo > 5MB
        big_content = "x" * (6 * 1024 * 1024)  # 6MB
        page = AsyncMock()
        page.content = AsyncMock(return_value=big_content)

        result = await self.collector._capture_html(page)

        assert len(result) == DiagnosticsCollector.MAX_HTML_SIZE

    @pytest.mark.asyncio
    async def test_html_exatamente_5mb_nao_trunca(self) -> None:
        """HTML com exatamente 5MB não é truncado."""
        exact_content = "a" * (5 * 1024 * 1024)  # exatamente 5MB
        page = AsyncMock()
        page.content = AsyncMock(return_value=exact_content)

        result = await self.collector._capture_html(page)

        assert len(result) == DiagnosticsCollector.MAX_HTML_SIZE

    @pytest.mark.asyncio
    async def test_html_falha_retorna_vazio(self) -> None:
        """Falha ao capturar HTML retorna bytes vazios."""
        page = AsyncMock()
        page.content = AsyncMock(side_effect=Exception("Page error"))

        result = await self.collector._capture_html(page)

        assert result == b""

    @pytest.mark.asyncio
    async def test_html_com_unicode_trunca_por_bytes(self) -> None:
        """Truncamento é por bytes (não caracteres) — acentos usam mais bytes."""
        # 'ã' em UTF-8 ocupa 2 bytes
        page = AsyncMock()
        page.content = AsyncMock(return_value="ã" * (3 * 1024 * 1024))

        result = await self.collector._capture_html(page)

        assert len(result) <= DiagnosticsCollector.MAX_HTML_SIZE


class TestCaptureScreenshot:
    """Testes para captura de screenshot."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_screenshot_capturado_com_sucesso(self) -> None:
        """Screenshot é capturado como bytes."""
        page = AsyncMock()
        fake_png = b"\x89PNG\r\n\x1a\nfakedata"
        page.screenshot = AsyncMock(return_value=fake_png)

        result = await self.collector._capture_screenshot(page)

        assert result == fake_png
        page.screenshot.assert_called_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_screenshot_falha_retorna_vazio(self) -> None:
        """Falha na captura de screenshot retorna bytes vazios."""
        page = AsyncMock()
        page.screenshot = AsyncMock(
            side_effect=Exception("Screenshot failed")
        )

        result = await self.collector._capture_screenshot(page)

        assert result == b""


class TestCaptureElements:
    """Testes para captura de elementos da página."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_elementos_capturados_com_sucesso(self) -> None:
        """Elementos são retornados com tag, id e classes."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=[
            {"tag": "div", "id": "main", "classes": "container"},
            {"tag": "span", "id": "", "classes": "price"},
        ])

        result = await self.collector._capture_elements(page)

        assert len(result) == 2
        assert result[0]["tag"] == "div"
        assert result[0]["id"] == "main"
        assert result[1]["classes"] == "price"

    @pytest.mark.asyncio
    async def test_elementos_limitados_a_100(self) -> None:
        """Lista de elementos é truncada a MAX_ELEMENTS (100)."""
        page = AsyncMock()
        # Simular página com 150 elementos retornados pelo JS
        many_elements = [
            {"tag": f"div{i}", "id": f"el{i}", "classes": ""}
            for i in range(150)
        ]
        page.evaluate = AsyncMock(return_value=many_elements)

        result = await self.collector._capture_elements(page)

        assert len(result) == 100

    @pytest.mark.asyncio
    async def test_elementos_falha_retorna_lista_vazia(self) -> None:
        """Falha ao capturar elementos retorna lista vazia."""
        page = AsyncMock()
        page.evaluate = AsyncMock(
            side_effect=Exception("JS evaluation failed")
        )

        result = await self.collector._capture_elements(page)

        assert result == []

    @pytest.mark.asyncio
    async def test_elementos_menor_que_100_preservados(self) -> None:
        """Lista com menos de 100 elementos é preservada integralmente."""
        page = AsyncMock()
        elements = [
            {"tag": "div", "id": "x", "classes": "cls"}
            for _ in range(50)
        ]
        page.evaluate = AsyncMock(return_value=elements)

        result = await self.collector._capture_elements(page)

        assert len(result) == 50


class TestCaptureFinalUrl:
    """Testes para captura de URL final."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_url_final_capturada(self) -> None:
        """URL final é capturada via page.url."""
        page = AsyncMock()
        page.url = "https://example.com/br/plans"

        result = await self.collector._capture_final_url(page)

        assert result == "https://example.com/br/plans"

    @pytest.mark.asyncio
    async def test_url_final_falha_retorna_vazio(self) -> None:
        """Falha na captura de URL retorna string vazia."""
        page = MagicMock()
        type(page).url = property(
            fget=lambda self: (_ for _ in ()).throw(Exception("error"))
        )

        result = await self.collector._capture_final_url(page)

        assert result == ""


class TestUploadHtml:
    """Testes para upload de HTML ao S3."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_upload_html_retorna_s3_key(self) -> None:
        """Upload bem-sucedido retorna S3 key no formato correto."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(return_value={})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector._upload_html(
                b"<html>test</html>",
                "diagnostics/comp1/cycle1",
                "2024-01-15T10:30:00+00:00",
            )

        assert result is not None
        assert result.startswith("diagnostics/comp1/cycle1/html_")
        assert result.endswith(".html")
        mock_s3.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_html_vazio_retorna_none(self) -> None:
        """HTML vazio (bytes vazios) não faz upload e retorna None."""
        result = await self.collector._upload_html(
            b"",
            "diagnostics/comp1/cycle1",
            "2024-01-15T10:30:00+00:00",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_upload_html_falha_retorna_none(self) -> None:
        """Falha no S3 retorna None sem levantar exceção."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(
            side_effect=Exception("S3 unreachable")
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector._upload_html(
                b"<html>data</html>",
                "diagnostics/comp1/cycle1",
                "2024-01-15T10:30:00+00:00",
            )

        assert result is None


class TestUploadScreenshot:
    """Testes para upload de screenshot ao S3."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_upload_screenshot_retorna_s3_key(self) -> None:
        """Upload bem-sucedido retorna S3 key no formato correto."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(return_value={})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector._upload_screenshot(
                b"\x89PNGfakedata",
                "diagnostics/comp1/cycle1",
                "2024-01-15T10:30:00+00:00",
            )

        assert result is not None
        assert result.startswith("diagnostics/comp1/cycle1/screenshot_")
        assert result.endswith(".png")
        mock_s3.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_screenshot_vazio_retorna_none(self) -> None:
        """Screenshot vazio não faz upload e retorna None."""
        result = await self.collector._upload_screenshot(
            b"",
            "diagnostics/comp1/cycle1",
            "2024-01-15T10:30:00+00:00",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_upload_screenshot_falha_retorna_none(self) -> None:
        """Falha no S3 retorna None sem levantar exceção."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(
            side_effect=Exception("S3 timeout")
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector._upload_screenshot(
                b"\x89PNGdata",
                "diagnostics/comp1/cycle1",
                "2024-01-15T10:30:00+00:00",
            )

        assert result is None


class TestCaptureDiagnostic:
    """Testes para o método principal capture_diagnostic()."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    @pytest.mark.asyncio
    async def test_retorna_diagnostic_artifact_completo(self) -> None:
        """capture_diagnostic retorna DiagnosticArtifact com todos os campos."""
        page = AsyncMock()
        page.url = "https://example.com/plans"
        page.content = AsyncMock(
            return_value="<html><body>conteúdo</body></html>"
        )
        page.screenshot = AsyncMock(return_value=b"\x89PNGdata")
        page.evaluate = AsyncMock(return_value=[
            {"tag": "div", "id": "main", "classes": "container"},
        ])

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(return_value={})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector.capture_diagnostic(
                page=page,
                error="Falha ao extrair preços",
                competitor_id="netflix",
                cycle_id="cycle_001",
            )

        assert isinstance(result, DiagnosticArtifact)
        assert result.final_url == "https://example.com/plans"
        assert result.error_message == "Falha ao extrair preços"
        assert result.timestamp != ""
        assert len(result.elements_found) == 1
        assert result.elements_found[0]["tag"] == "div"

    @pytest.mark.asyncio
    async def test_s3_keys_tem_prefixo_correto(self) -> None:
        """S3 keys seguem padrão diagnostics/{competitor_id}/{cycle_id}/."""
        page = AsyncMock()
        page.url = "https://example.com"
        page.content = AsyncMock(return_value="<html></html>")
        page.screenshot = AsyncMock(return_value=b"\x89PNG")
        page.evaluate = AsyncMock(return_value=[])

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(return_value={})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector.capture_diagnostic(
                page=page,
                error=RuntimeError("test error"),
                competitor_id="paramount",
                cycle_id="cycle_abc",
            )

        assert result.html_s3_key is not None
        assert result.html_s3_key.startswith(
            "diagnostics/paramount/cycle_abc/"
        )
        assert result.screenshot_s3_key is not None
        assert result.screenshot_s3_key.startswith(
            "diagnostics/paramount/cycle_abc/"
        )

    @pytest.mark.asyncio
    async def test_error_exception_convertido_para_string(self) -> None:
        """Quando error é Exception, error_message é str(exception)."""
        page = AsyncMock()
        page.url = "https://example.com"
        page.content = AsyncMock(return_value="<html></html>")
        page.screenshot = AsyncMock(return_value=b"\x89PNG")
        page.evaluate = AsyncMock(return_value=[])

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(return_value={})
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector.capture_diagnostic(
                page=page,
                error=ValueError("preço inválido"),
                competitor_id="vivo",
                cycle_id="cycle_002",
            )

        assert result.error_message == "preço inválido"

    @pytest.mark.asyncio
    async def test_upload_falha_nao_interrompe_fluxo(self) -> None:
        """Falha no upload S3 não levanta exceção — retorna None nas keys."""
        page = AsyncMock()
        page.url = "https://example.com"
        page.content = AsyncMock(return_value="<html>data</html>")
        page.screenshot = AsyncMock(return_value=b"\x89PNG")
        page.evaluate = AsyncMock(return_value=[
            {"tag": "body", "id": "", "classes": ""},
        ])

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(
            side_effect=Exception("S3 down")
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            result = await self.collector.capture_diagnostic(
                page=page,
                error="S3 falhou",
                competitor_id="giga",
                cycle_id="cycle_003",
            )

        # Artifact retornado mesmo com falha no upload
        assert isinstance(result, DiagnosticArtifact)
        assert result.html_s3_key is None
        assert result.screenshot_s3_key is None
        # Demais campos preenchidos normalmente
        assert result.final_url == "https://example.com"
        assert result.error_message == "S3 falhou"
        assert len(result.elements_found) == 1

    @pytest.mark.asyncio
    async def test_html_truncado_no_upload(self) -> None:
        """HTML maior que 5MB é truncado antes do upload."""
        page = AsyncMock()
        page.url = "https://example.com"
        # 6MB de conteúdo
        big_html = "x" * (6 * 1024 * 1024)
        page.content = AsyncMock(return_value=big_html)
        page.screenshot = AsyncMock(return_value=b"\x89PNG")
        page.evaluate = AsyncMock(return_value=[])

        uploaded_body: bytes | None = None

        async def capture_put_object(**kwargs):
            nonlocal uploaded_body
            uploaded_body = kwargs.get("Body", b"")
            return {}

        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=capture_put_object)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch.object(
            self.collector._session, "client", return_value=mock_ctx
        ):
            await self.collector.capture_diagnostic(
                page=page,
                error="test",
                competitor_id="comp",
                cycle_id="cycle",
            )

        # O primeiro put_object foi para HTML — verificar tamanho
        first_call_kwargs = mock_s3.put_object.call_args_list[0].kwargs
        assert len(first_call_kwargs["Body"]) == 5 * 1024 * 1024


class TestSafeTimestamp:
    """Testes para _safe_timestamp()."""

    def setup_method(self) -> None:
        self.collector = DiagnosticsCollector(
            bucket="test-bucket"
        )

    def test_iso_com_timezone(self) -> None:
        """Timestamp ISO com timezone é convertido corretamente."""
        result = self.collector._safe_timestamp(
            "2024-01-15T10:30:00+00:00"
        )
        assert result == "20240115T103000"

    def test_iso_sem_timezone(self) -> None:
        """Timestamp ISO sem timezone é convertido."""
        result = self.collector._safe_timestamp(
            "2024-06-20T14:45:30"
        )
        assert result == "20240620T144530"

    def test_iso_com_microsegundos(self) -> None:
        """Timestamp com microsegundos remove fração."""
        result = self.collector._safe_timestamp(
            "2024-01-15T10:30:00.123456+00:00"
        )
        assert result == "20240115T103000"
