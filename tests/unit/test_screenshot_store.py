"""Testes unitários para o ScreenshotStore."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from price_watchdog.storage.screenshot_store import ScreenshotStore


@pytest.fixture
def store():
    """Cria instância do ScreenshotStore com bucket de teste."""
    return ScreenshotStore(bucket="test-bucket")


class TestGenerateKey:
    """Testes para geração de S3 key."""

    def test_key_contains_cycle_id(self, store):
        """A key gerada deve conter o cycle_id."""
        key = store._generate_key("cycle-123", "comp-456", "20240101T120000000000")
        assert "cycle-123" in key

    def test_key_contains_competitor_id(self, store):
        """A key gerada deve conter o competitor_id."""
        key = store._generate_key("cycle-123", "comp-456", "20240101T120000000000")
        assert "comp-456" in key

    def test_key_contains_timestamp(self, store):
        """A key gerada deve conter o timestamp."""
        key = store._generate_key("cycle-123", "comp-456", "20240101T120000000000")
        assert "20240101T120000000000" in key

    def test_key_has_png_extension(self, store):
        """A key gerada deve ter extensão .png."""
        key = store._generate_key("cycle-123", "comp-456", "20240101T120000000000")
        assert key.endswith(".png")

    def test_key_has_screenshots_prefix(self, store):
        """A key gerada deve ter prefixo 'screenshots/'."""
        key = store._generate_key("cycle-123", "comp-456", "20240101T120000000000")
        assert key.startswith("screenshots/")


class TestUpload:
    """Testes para upload de screenshots."""

    @pytest.mark.asyncio
    async def test_upload_success_returns_key(self, store):
        """Upload bem-sucedido retorna a S3 key."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(store._session, "client", return_value=mock_client):
            result = await store.upload(b"fake-png-data", "cycle-001", "comp-001")

        assert result != ""
        assert "cycle-001" in result
        assert "comp-001" in result

    @pytest.mark.asyncio
    async def test_upload_success_calls_put_object(self, store):
        """Upload deve chamar put_object com parâmetros corretos."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(store._session, "client", return_value=mock_client):
            await store.upload(b"fake-png-data", "cycle-001", "comp-001")

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"fake-png-data"
        assert call_kwargs["ContentType"] == "image/png"

    @pytest.mark.asyncio
    async def test_upload_failure_returns_empty_string(self, store):
        """Falha no upload retorna string vazia sem levantar exceção."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(side_effect=Exception("S3 error"))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(store._session, "client", return_value=mock_client):
            result = await store.upload(b"fake-png-data", "cycle-001", "comp-001")

        assert result == ""

    @pytest.mark.asyncio
    async def test_upload_failure_does_not_raise(self, store):
        """Falha no upload não deve propagar exceção."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock(
            side_effect=RuntimeError("Connection refused")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(store._session, "client", return_value=mock_client):
            # Não deve levantar exceção
            result = await store.upload(b"data", "c1", "comp1")
            assert result == ""

    @pytest.mark.asyncio
    async def test_upload_key_contains_timestamp(self, store):
        """A key retornada pelo upload deve conter um timestamp."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(store._session, "client", return_value=mock_client):
            result = await store.upload(b"data", "cycle-x", "comp-y")

        # Timestamp no formato YYYYMMDDTHHMMSSffffff
        assert "T" in result
        assert ".png" in result
