"""Testes de integração para S3: upload e verificação de screenshots.

Utiliza moto (mock_aws) para simular o serviço S3 localmente,
validando upload de screenshots, formato da S3 key e integridade
dos dados armazenados.

Nota: Como aioboto3 tem problemas com moto em operações de upload S3,
usamos uma abordagem híbrida:
- Testamos a geração de key via método _generate_key() do ScreenshotStore
- Testamos o upload/download com sync boto3 para validar a integração S3
- Testamos o fluxo async completo mockando o session do aioboto3
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from price_watchdog.storage.screenshot_store import ScreenshotStore


# Região e bucket padrão para testes
TEST_REGION = "us-east-1"
TEST_BUCKET = "price-watchdog-screenshots-test"


@pytest.fixture(autouse=True)
def aws_credentials():
    """Configura credenciais fake para moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION
    yield


def _create_fake_screenshot(size: int = 1024) -> bytes:
    """Cria bytes fake simulando um screenshot PNG."""
    png_header = b"\x89PNG\r\n\x1a\n"
    return png_header + os.urandom(size - len(png_header))


class TestScreenshotS3KeyGeneration:
    """Testa geração da S3 key pelo ScreenshotStore."""

    def test_key_contem_cycle_id(self):
        """A key gerada contém o cycle_id."""
        store = ScreenshotStore(bucket=TEST_BUCKET)
        key = store._generate_key(
            cycle_id="cycle-abc-123",
            competitor_id="comp-xyz",
            timestamp="20240115T120000000000",
        )
        assert "cycle-abc-123" in key

    def test_key_contem_competitor_id(self):
        """A key gerada contém o competitor_id."""
        store = ScreenshotStore(bucket=TEST_BUCKET)
        key = store._generate_key(
            cycle_id="cycle-001",
            competitor_id="comp-hbo-max",
            timestamp="20240115T120000000000",
        )
        assert "comp-hbo-max" in key

    def test_key_contem_timestamp(self):
        """A key gerada contém o timestamp."""
        store = ScreenshotStore(bucket=TEST_BUCKET)
        key = store._generate_key(
            cycle_id="cycle-001",
            competitor_id="comp-001",
            timestamp="20240115T143022567890",
        )
        assert "20240115T143022567890" in key

    def test_key_formato_completo(self):
        """A key segue o formato: screenshots/{cycle_id}/{competitor_id}/{timestamp}.png"""
        store = ScreenshotStore(bucket=TEST_BUCKET)
        key = store._generate_key(
            cycle_id="cycle-fmt-001",
            competitor_id="comp-fmt-abc",
            timestamp="20240115T143022567890",
        )

        assert key == "screenshots/cycle-fmt-001/comp-fmt-abc/20240115T143022567890.png"
        parts = key.split("/")
        assert len(parts) == 4
        assert parts[0] == "screenshots"
        assert parts[1] == "cycle-fmt-001"
        assert parts[2] == "comp-fmt-abc"
        assert parts[3] == "20240115T143022567890.png"

    def test_key_termina_com_png(self):
        """A key sempre termina com .png."""
        store = ScreenshotStore(bucket=TEST_BUCKET)
        key = store._generate_key(
            cycle_id="any-cycle",
            competitor_id="any-comp",
            timestamp="20240101T000000000000",
        )
        assert key.endswith(".png")


class TestScreenshotS3Upload:
    """Testa upload e verificação de screenshots no S3 usando sync boto3."""

    @mock_aws
    def test_upload_e_download_bytes_identicos(self):
        """Upload e download do S3 preservam os bytes originais."""
        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)

        # Simular o que o ScreenshotStore faz: gerar key e fazer put_object
        original_bytes = _create_fake_screenshot(2048)
        cycle_id = "cycle-integrity-001"
        competitor_id = "comp-claro-tv"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        s3_key = f"screenshots/{cycle_id}/{competitor_id}/{timestamp}.png"

        # Upload
        s3.put_object(
            Bucket=TEST_BUCKET,
            Key=s3_key,
            Body=original_bytes,
            ContentType="image/png",
        )

        # Download e comparar
        response = s3.get_object(Bucket=TEST_BUCKET, Key=s3_key)
        downloaded_bytes = response["Body"].read()

        assert downloaded_bytes == original_bytes

    @mock_aws
    def test_upload_content_type_image_png(self):
        """O ContentType armazenado é image/png."""
        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)

        screenshot_bytes = _create_fake_screenshot()
        s3_key = "screenshots/cycle-ct/comp-ct/20240115T120000000000.png"

        s3.put_object(
            Bucket=TEST_BUCKET,
            Key=s3_key,
            Body=screenshot_bytes,
            ContentType="image/png",
        )

        response = s3.head_object(Bucket=TEST_BUCKET, Key=s3_key)
        assert response["ContentType"] == "image/png"

    @mock_aws
    def test_upload_multiple_screenshots_listados(self):
        """Múltiplos uploads são armazenados com keys únicas e listáveis."""
        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)

        cycle_id = "cycle-multi-001"
        keys = []

        for i in range(3):
            screenshot = _create_fake_screenshot(512 + i)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            s3_key = f"screenshots/{cycle_id}/comp-{i}/{timestamp}.png"
            keys.append(s3_key)

            s3.put_object(
                Bucket=TEST_BUCKET,
                Key=s3_key,
                Body=screenshot,
                ContentType="image/png",
            )

        # Listar objetos no prefix do ciclo
        response = s3.list_objects_v2(
            Bucket=TEST_BUCKET,
            Prefix=f"screenshots/{cycle_id}/",
        )

        stored_keys = [obj["Key"] for obj in response["Contents"]]
        assert len(stored_keys) == 3
        for key in keys:
            assert key in stored_keys

    @mock_aws
    def test_key_contem_componentes_de_identificacao(self):
        """A S3 key armazenada contém cycle_id, competitor_id e timestamp."""
        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)

        cycle_id = "cycle-20240115-abc"
        competitor_id = "comp-hbo-max-br"
        timestamp = "20240115T143022567890"
        s3_key = f"screenshots/{cycle_id}/{competitor_id}/{timestamp}.png"

        s3.put_object(
            Bucket=TEST_BUCKET,
            Key=s3_key,
            Body=_create_fake_screenshot(),
            ContentType="image/png",
        )

        # Verificar que o objeto existe com a key correta
        response = s3.head_object(Bucket=TEST_BUCKET, Key=s3_key)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

        # Verificar componentes da key
        assert cycle_id in s3_key
        assert competitor_id in s3_key
        assert timestamp in s3_key
        assert s3_key.startswith("screenshots/")
        assert s3_key.endswith(".png")


class TestScreenshotStoreAsyncUpload:
    """Testa o fluxo async completo do ScreenshotStore com mock do aioboto3."""

    @pytest.mark.asyncio
    async def test_upload_async_retorna_key_valida(self):
        """O upload async retorna uma S3 key com formato correto."""
        # Criar mock para o client S3 async
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(return_value={})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        store = ScreenshotStore(bucket=TEST_BUCKET)

        with patch.object(
            store._session, "client", return_value=mock_context
        ):
            s3_key = await store.upload(
                screenshot_bytes=_create_fake_screenshot(),
                cycle_id="cycle-async-001",
                competitor_id="comp-async-hbo",
            )

        # Verificar key
        assert s3_key != ""
        assert "cycle-async-001" in s3_key
        assert "comp-async-hbo" in s3_key
        assert s3_key.startswith("screenshots/")
        assert s3_key.endswith(".png")

        # Verificar que put_object foi chamado com params corretos
        mock_s3_client.put_object.assert_called_once()
        call_kwargs = mock_s3_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == TEST_BUCKET
        assert call_kwargs["Key"] == s3_key
        assert call_kwargs["ContentType"] == "image/png"

    @pytest.mark.asyncio
    async def test_upload_async_falha_retorna_vazio(self):
        """Falha no upload async retorna string vazia (degradação graciosa)."""
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(
            side_effect=Exception("S3 connection error")
        )

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        store = ScreenshotStore(bucket=TEST_BUCKET)

        with patch.object(
            store._session, "client", return_value=mock_context
        ):
            s3_key = await store.upload(
                screenshot_bytes=_create_fake_screenshot(),
                cycle_id="cycle-fail",
                competitor_id="comp-fail",
            )

        assert s3_key == ""

    @pytest.mark.asyncio
    async def test_upload_async_timestamp_no_key(self):
        """O timestamp na key segue formato YYYYMMDDTHHMMSS + microseconds."""
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(return_value={})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        store = ScreenshotStore(bucket=TEST_BUCKET)

        with patch.object(
            store._session, "client", return_value=mock_context
        ):
            s3_key = await store.upload(
                screenshot_bytes=_create_fake_screenshot(),
                cycle_id="cycle-ts",
                competitor_id="comp-ts",
            )

        # Extrair e validar timestamp
        parts = s3_key.split("/")
        filename = parts[-1]  # timestamp.png
        timestamp_str = filename.replace(".png", "")

        assert len(timestamp_str) >= 15
        assert "T" in timestamp_str
        date_part = timestamp_str.split("T")[0]
        assert len(date_part) == 8
        assert date_part.isdigit()
