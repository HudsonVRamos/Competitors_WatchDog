"""Armazenamento de screenshots no S3 usando aioboto3."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aioboto3

from price_watchdog.config import settings

logger = logging.getLogger(__name__)


class ScreenshotStore:
    """Armazenamento de screenshots no S3."""

    def __init__(self, bucket: str | None = None) -> None:
        """Inicializa o ScreenshotStore.

        Args:
            bucket: Nome do bucket S3. Se não informado, usa settings.s3_bucket.
        """
        self._bucket = bucket or settings.s3_bucket
        self._session = aioboto3.Session()

    def _generate_key(
        self, cycle_id: str, competitor_id: str, timestamp: str
    ) -> str:
        """Gera a S3 key contendo cycle_id, competitor_id e timestamp.

        Formato: screenshots/{cycle_id}/{competitor_id}/{timestamp}.png

        Args:
            cycle_id: Identificador do ciclo de monitoramento.
            competitor_id: Identificador do concorrente.
            timestamp: Timestamp no formato ISO (sem caracteres especiais).

        Returns:
            S3 key gerada.
        """
        return f"screenshots/{cycle_id}/{competitor_id}/{timestamp}.png"

    async def upload(
        self,
        screenshot_bytes: bytes,
        cycle_id: str,
        competitor_id: str,
    ) -> str:
        """Faz upload de um screenshot para o S3.

        Gera uma chave S3 contendo cycle_id, competitor_id e timestamp,
        garantindo unicidade e rastreabilidade. Em caso de falha no upload,
        registra o erro no log mas não levanta exceção (degradação graciosa).

        Args:
            screenshot_bytes: Conteúdo binário do screenshot.
            cycle_id: Identificador do ciclo de monitoramento.
            competitor_id: Identificador do concorrente.

        Returns:
            S3 key do screenshot salvo, ou string vazia em caso de falha.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        s3_key = self._generate_key(cycle_id, competitor_id, timestamp)

        try:
            async with self._session.client("s3") as s3_client:
                await s3_client.put_object(
                    Bucket=self._bucket,
                    Key=s3_key,
                    Body=screenshot_bytes,
                    ContentType="image/png",
                )
            logger.info(
                "Screenshot uploaded: bucket=%s key=%s",
                self._bucket,
                s3_key,
            )
        except Exception as exc:
            logger.error(
                "Falha ao fazer upload do screenshot: bucket=%s key=%s erro=%s",
                self._bucket,
                s3_key,
                exc,
            )
            return ""

        return s3_key
