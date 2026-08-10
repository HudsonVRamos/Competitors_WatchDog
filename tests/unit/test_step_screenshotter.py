"""Testes unitários para o StepScreenshotter."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from scraping_resilience.step_screenshotter import StepScreenshotter, _sanitize_description


class TestSanitizeDescription:
    """Testes para a sanitização de descrições."""

    def test_lowercase_conversion(self):
        """Converte texto para lowercase."""
        assert _sanitize_description("After Load") == "after_load"

    def test_spaces_to_underscores(self):
        """Substitui espaços por underscores."""
        assert _sanitize_description("after load page") == "after_load_page"

    def test_removes_special_characters(self):
        """Remove caracteres não alfanuméricos/underscore."""
        assert _sanitize_description("step@#$test!") == "steptest"

    def test_removes_accents(self):
        """Remove caracteres acentuados (não-ASCII)."""
        assert _sanitize_description("após carregamento") == "aps_carregamento"

    def test_collapses_multiple_underscores(self):
        """Colapsa múltiplos underscores em um só."""
        assert _sanitize_description("a   b") == "a_b"

    def test_strips_leading_trailing_underscores(self):
        """Remove underscores no início e fim."""
        assert _sanitize_description("  test  ") == "test"

    def test_empty_string_returns_step(self):
        """String vazia retorna 'step' como fallback."""
        assert _sanitize_description("") == "step"

    def test_only_special_chars_returns_step(self):
        """String com apenas caracteres especiais retorna 'step'."""
        assert _sanitize_description("@#$%") == "step"

    def test_preserves_numbers(self):
        """Mantém números na descrição."""
        assert _sanitize_description("tab 3 click") == "tab_3_click"

    def test_already_sanitized(self):
        """Texto já sanitizado permanece inalterado."""
        assert _sanitize_description("after_dropdown") == "after_dropdown"


class TestStepScreenshotterInit:
    """Testes para inicialização do StepScreenshotter."""

    def test_initial_step_counter_is_zero(self):
        """Counter inicia em 0."""
        ss = StepScreenshotter("comp-1", "cycle-1")
        assert ss.step_count == 0

    def test_initial_screenshots_list_empty(self):
        """Lista de screenshots inicia vazia."""
        ss = StepScreenshotter("comp-1", "cycle-1")
        assert ss.screenshots == []

    def test_custom_bucket(self):
        """Aceita bucket customizado."""
        ss = StepScreenshotter("comp-1", "cycle-1", bucket="my-bucket")
        assert ss._bucket == "my-bucket"

    def test_default_bucket(self):
        """Bucket padrão é 'price-watchdog-screenshots'."""
        ss = StepScreenshotter("comp-1", "cycle-1")
        assert ss._bucket == "price-watchdog-screenshots"


class TestBuildS3Key:
    """Testes para a construção da S3 key."""

    def test_key_format(self):
        """Verifica formato completo da key."""
        ss = StepScreenshotter("netflix", "cycle-abc")
        key = ss._build_s3_key(1, "after load")
        assert key == "netflix/cycle-abc/step_001_after_load.png"

    def test_key_with_step_number_padding(self):
        """Número do step é padded com zeros (3 dígitos)."""
        ss = StepScreenshotter("vivo_tv", "cycle-xyz")
        key = ss._build_s3_key(42, "tab click")
        assert key == "vivo_tv/cycle-xyz/step_042_tab_click.png"

    def test_key_with_large_step_number(self):
        """Step numbers acima de 999 não quebram (mais de 3 dígitos)."""
        ss = StepScreenshotter("comp", "cycle")
        key = ss._build_s3_key(1000, "test")
        assert key == "comp/cycle/step_1000_test.png"

    def test_key_sanitizes_description(self):
        """Descrição é sanitizada na key."""
        ss = StepScreenshotter("comp", "cycle")
        key = ss._build_s3_key(1, "After Dropdown Select!")
        assert key == "comp/cycle/step_001_after_dropdown_select.png"


class TestCapture:
    """Testes para o método capture()."""

    @pytest.fixture
    def mock_page(self):
        """Cria um mock de Page do Playwright."""
        page = AsyncMock()
        page.screenshot = AsyncMock(return_value=b"fake-png-data")
        return page

    @pytest.fixture
    def mock_s3_session(self):
        """Cria um mock de sessão aioboto3."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.client = MagicMock(return_value=mock_client)
        return session

    @pytest.mark.asyncio
    async def test_capture_returns_s3_key(self, mock_page, mock_s3_session):
        """Captura bem-sucedida retorna a S3 key."""
        ss = StepScreenshotter(
            "netflix", "cycle-001", s3_client=mock_s3_session
        )
        key = await ss.capture(mock_page, "after load")

        assert key == "netflix/cycle-001/step_001_after_load.png"

    @pytest.mark.asyncio
    async def test_capture_increments_counter(self, mock_page, mock_s3_session):
        """Cada captura incrementa o counter."""
        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "step one")
        await ss.capture(mock_page, "step two")
        await ss.capture(mock_page, "step three")

        assert ss.step_count == 3

    @pytest.mark.asyncio
    async def test_capture_sequential_numbering(self, mock_page, mock_s3_session):
        """Screenshots seguem numeração sequencial crescente."""
        ss = StepScreenshotter(
            "vivo_tv", "cycle-x", s3_client=mock_s3_session
        )

        key1 = await ss.capture(mock_page, "first")
        key2 = await ss.capture(mock_page, "second")
        key3 = await ss.capture(mock_page, "third")

        assert key1 == "vivo_tv/cycle-x/step_001_first.png"
        assert key2 == "vivo_tv/cycle-x/step_002_second.png"
        assert key3 == "vivo_tv/cycle-x/step_003_third.png"

    @pytest.mark.asyncio
    async def test_capture_stores_metadata(self, mock_page, mock_s3_session):
        """Captura armazena metadados na lista de screenshots."""
        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "after load")

        assert len(ss.screenshots) == 1
        screenshot = ss.screenshots[0]
        assert screenshot.step_number == 1
        assert screenshot.description == "after load"
        assert screenshot.s3_key == "comp/cycle/step_001_after_load.png"
        assert screenshot.captured_at != ""

    @pytest.mark.asyncio
    async def test_capture_calls_page_screenshot(self, mock_page, mock_s3_session):
        """Captura chama page.screenshot() com parâmetros corretos."""
        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "test")

        mock_page.screenshot.assert_called_once_with(type="png", full_page=True)

    @pytest.mark.asyncio
    async def test_capture_uploads_to_s3(self, mock_page, mock_s3_session):
        """Captura faz upload para S3 com parâmetros corretos."""
        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session, bucket="my-bucket"
        )

        await ss.capture(mock_page, "test")

        # Pegar o mock do s3 client
        mock_client_ctx = mock_s3_session.client.return_value
        mock_s3 = mock_client_ctx.__aenter__.return_value
        mock_s3.put_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="comp/cycle/step_001_test.png",
            Body=b"fake-png-data",
            ContentType="image/png",
        )

    @pytest.mark.asyncio
    async def test_capture_failure_returns_none(self, mock_s3_session):
        """Falha no screenshot retorna None sem levantar exceção."""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=Exception("Page crashed"))

        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        result = await ss.capture(mock_page, "will fail")

        assert result is None

    @pytest.mark.asyncio
    async def test_capture_failure_does_not_increment_counter(self, mock_s3_session):
        """Falha não incrementa o counter (sem lacunas na numeração)."""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=Exception("Error"))

        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "fail")
        assert ss.step_count == 0

    @pytest.mark.asyncio
    async def test_capture_failure_does_not_add_to_screenshots_list(
        self, mock_s3_session
    ):
        """Falha não adiciona entry à lista de screenshots."""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=RuntimeError("Timeout"))

        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "fail")
        assert ss.screenshots == []

    @pytest.mark.asyncio
    async def test_capture_s3_upload_failure_returns_none(self, mock_page):
        """Falha no upload S3 retorna None sem interromper fluxo."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=Exception("S3 unavailable"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.client = MagicMock(return_value=mock_client)

        ss = StepScreenshotter("comp", "cycle", s3_client=session)

        result = await ss.capture(mock_page, "s3 fail")
        assert result is None

    @pytest.mark.asyncio
    async def test_capture_s3_failure_does_not_increment_counter(self, mock_page):
        """Falha no upload S3 não incrementa counter."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=Exception("S3 error"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.client = MagicMock(return_value=mock_client)

        ss = StepScreenshotter("comp", "cycle", s3_client=session)

        await ss.capture(mock_page, "s3 fail")
        assert ss.step_count == 0

    @pytest.mark.asyncio
    async def test_capture_after_failure_continues_sequence(
        self, mock_page, mock_s3_session
    ):
        """Após uma falha, a próxima captura mantém sequência correta."""
        # Primeiro, simular uma falha
        failing_page = AsyncMock()
        failing_page.screenshot = AsyncMock(side_effect=Exception("Error"))

        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        # Captura 1 - sucesso
        key1 = await ss.capture(mock_page, "first")
        # Captura 2 - falha
        await ss.capture(failing_page, "will fail")
        # Captura 3 - sucesso
        key3 = await ss.capture(mock_page, "third")

        assert key1 == "comp/cycle/step_001_first.png"
        assert key3 == "comp/cycle/step_002_third.png"
        assert ss.step_count == 2

    @pytest.mark.asyncio
    async def test_screenshots_property_returns_copy(self, mock_page, mock_s3_session):
        """A property screenshots retorna uma cópia, não a lista interna."""
        ss = StepScreenshotter(
            "comp", "cycle", s3_client=mock_s3_session
        )

        await ss.capture(mock_page, "test")

        screenshots = ss.screenshots
        screenshots.clear()  # Modificar cópia

        # Lista interna não é afetada
        assert len(ss.screenshots) == 1
