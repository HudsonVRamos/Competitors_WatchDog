"""DiagnosticsCollector - Coleta e persiste artefatos diagnósticos em erro.

Captura em caso de erro:
- HTML completo da página (até 5MB)
- Screenshot do estado de erro
- URL final após redirecionamentos
- Lista de elementos encontrados (até 100, com tag/id/classes)
- Mensagem de erro detalhada

Upload para S3: diagnostics/{competitor_id}/{cycle_id}/
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import aioboto3
from playwright.async_api import Page

from scraping_resilience.models import DiagnosticArtifact

logger = logging.getLogger(__name__)


class DiagnosticsCollector:
    """Coleta e persiste artefatos diagnósticos em erro."""

    MAX_HTML_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_ELEMENTS = 100

    def __init__(
        self,
        bucket: str = "price-watchdog-diagnostics",
    ) -> None:
        """Inicializa o DiagnosticsCollector.

        Args:
            bucket: Nome do bucket S3 para upload dos artefatos.
        """
        self._bucket = bucket
        self._session = aioboto3.Session()

    async def capture_diagnostic(
        self,
        page: Page,
        error: Exception | str,
        competitor_id: str,
        cycle_id: str,
    ) -> DiagnosticArtifact:
        """Captura diagnóstico completo em caso de erro.

        Captura:
        1. HTML content (truncado a 5MB)
        2. Screenshot do estado de erro
        3. URL final após redirecionamentos
        4. Lista de elementos (max 100 com tag/id/classes)
        5. Mensagem de erro

        Faz upload para S3: diagnostics/{competitor_id}/{cycle_id}/
        Falhas no upload são logadas sem interromper o fluxo.

        Returns:
            DiagnosticArtifact com chaves S3 e metadados capturados.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        error_message = (
            str(error) if isinstance(error, Exception) else error
        )
        prefix = f"diagnostics/{competitor_id}/{cycle_id}"

        # Capturar URL final
        final_url = await self._capture_final_url(page)

        # Capturar HTML (truncado a 5MB)
        html_content = await self._capture_html(page)

        # Capturar screenshot
        screenshot_bytes = await self._capture_screenshot(page)

        # Capturar lista de elementos (max 100)
        elements = await self._capture_elements(page)

        # Upload para S3
        html_s3_key = await self._upload_html(
            html_content, prefix, timestamp
        )
        screenshot_s3_key = await self._upload_screenshot(
            screenshot_bytes, prefix, timestamp
        )

        return DiagnosticArtifact(
            html_s3_key=html_s3_key,
            screenshot_s3_key=screenshot_s3_key,
            final_url=final_url,
            elements_found=elements,
            error_message=error_message,
            timestamp=timestamp,
        )

    async def _capture_final_url(self, page: Page) -> str:
        """Captura a URL final da página após redirecionamentos."""
        try:
            return page.url
        except Exception as exc:
            logger.warning(
                "Falha ao capturar URL final: %s", exc
            )
            return ""

    async def _capture_html(self, page: Page) -> bytes:
        """Captura HTML da página, truncando a MAX_HTML_SIZE bytes."""
        try:
            content = await page.content()
            html_bytes = content.encode("utf-8")
            if len(html_bytes) > self.MAX_HTML_SIZE:
                html_bytes = html_bytes[: self.MAX_HTML_SIZE]
            return html_bytes
        except Exception as exc:
            logger.warning(
                "Falha ao capturar HTML da página: %s", exc
            )
            return b""

    async def _capture_screenshot(self, page: Page) -> bytes:
        """Captura screenshot da página no estado de erro."""
        try:
            return await page.screenshot(full_page=True)
        except Exception as exc:
            logger.warning(
                "Falha ao capturar screenshot: %s", exc
            )
            return b""

    async def _capture_elements(
        self, page: Page
    ) -> list[dict[str, str]]:
        """Captura lista de elementos da página (max MAX_ELEMENTS).

        Cada elemento contém: tag, id e classes.
        """
        try:
            elements = await page.evaluate(
                """() => {
                    const MAX = 100;
                    const allElements = document.querySelectorAll('*');
                    const result = [];
                    const limit = Math.min(allElements.length, MAX);
                    for (let i = 0; i < limit; i++) {
                        const el = allElements[i];
                        result.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            classes: el.className || ''
                        });
                    }
                    return result;
                }"""
            )
            return elements[: self.MAX_ELEMENTS]
        except Exception as exc:
            logger.warning(
                "Falha ao capturar elementos da página: %s", exc
            )
            return []

    async def _upload_html(
        self, html_bytes: bytes, prefix: str, timestamp: str
    ) -> str | None:
        """Faz upload do HTML para S3.

        Returns:
            S3 key do artefato ou None em caso de falha.
        """
        if not html_bytes:
            return None

        # Gerar timestamp seguro para filename
        ts_safe = self._safe_timestamp(timestamp)
        s3_key = f"{prefix}/html_{ts_safe}.html"

        try:
            async with self._session.client("s3") as s3_client:
                await s3_client.put_object(
                    Bucket=self._bucket,
                    Key=s3_key,
                    Body=html_bytes,
                    ContentType="text/html; charset=utf-8",
                )
            logger.info(
                "HTML diagnóstico uploaded: bucket=%s key=%s",
                self._bucket,
                s3_key,
            )
            return s3_key
        except Exception as exc:
            logger.error(
                "Falha ao fazer upload HTML: bucket=%s key=%s erro=%s",
                self._bucket,
                s3_key,
                exc,
            )
            return None

    async def _upload_screenshot(
        self, screenshot_bytes: bytes, prefix: str, timestamp: str
    ) -> str | None:
        """Faz upload do screenshot para S3.

        Returns:
            S3 key do artefato ou None em caso de falha.
        """
        if not screenshot_bytes:
            return None

        ts_safe = self._safe_timestamp(timestamp)
        s3_key = f"{prefix}/screenshot_{ts_safe}.png"

        try:
            async with self._session.client("s3") as s3_client:
                await s3_client.put_object(
                    Bucket=self._bucket,
                    Key=s3_key,
                    Body=screenshot_bytes,
                    ContentType="image/png",
                )
            logger.info(
                "Screenshot diagnóstico uploaded: bucket=%s key=%s",
                self._bucket,
                s3_key,
            )
            return s3_key
        except Exception as exc:
            logger.error(
                "Falha ao fazer upload screenshot: bucket=%s key=%s erro=%s",
                self._bucket,
                s3_key,
                exc,
            )
            return None

    def _safe_timestamp(self, timestamp: str) -> str:
        """Converte timestamp ISO para formato seguro para filename.

        Remove caracteres não permitidos em nomes de arquivo S3.
        Ex: '2024-01-15T10:30:00+00:00' → '20240115T103000'
        """
        # Remove caracteres não-alfanuméricos exceto T
        safe = timestamp.replace("-", "").replace(":", "")
        # Remover parte do timezone se presente
        if "+" in safe:
            safe = safe.split("+")[0]
        # Truncar microsegundos se presentes (após o '.')
        if "." in safe:
            safe = safe.split(".")[0]
        return safe
