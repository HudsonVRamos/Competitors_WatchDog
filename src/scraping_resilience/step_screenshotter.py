"""StepScreenshotter - Captura screenshots sequenciais por etapa de navegação.

Nomenclatura: {competitor_id}/{cycle_id}/step_{n:03d}_{descricao}.png
Upload assíncrono para S3 bucket de evidências.

Captura nos momentos:
- Após carregamento inicial da página
- Após cada interação significativa (clique em tab, seleção de dropdown)
- Antes da extração de preços

Falha de screenshot não interrompe o fluxo principal.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import aioboto3
from playwright.async_api import Page

from scraping_resilience.models import StepScreenshot

logger = logging.getLogger(__name__)


def _sanitize_description(description: str) -> str:
    """Sanitiza descrição para uso em nome de arquivo S3.

    Converte para lowercase, substitui espaços por underscores e remove
    caracteres que não sejam alfanuméricos ou underscores.

    Args:
        description: Descrição livre da etapa.

    Returns:
        Descrição sanitizada segura para uso em S3 keys.
    """
    sanitized = description.lower().strip()
    sanitized = sanitized.replace(" ", "_")
    sanitized = re.sub(r"[^a-z0-9_]", "", sanitized)
    # Remove underscores duplicados e trailing underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip("_")
    return sanitized or "step"


class StepScreenshotter:
    """Captura e nomeia screenshots sequenciais por etapa de navegação.

    Cada instância gerencia screenshots para um par (competitor_id, cycle_id),
    mantendo numeração estritamente crescente sem lacunas.

    Atributos:
        _competitor_id: Identificador do concorrente.
        _cycle_id: Identificador do ciclo de monitoramento.
        _step_counter: Contador sequencial de steps (inicia em 0, incrementa antes do uso).
        _s3_client: Cliente S3 (aioboto3 session). Se None, cria uma sessão padrão.
        _bucket: Nome do bucket S3 para upload.
        _screenshots: Lista de metadados dos screenshots capturados.
    """

    def __init__(
        self,
        competitor_id: str,
        cycle_id: str,
        s3_client: aioboto3.Session | None = None,
        bucket: str = "price-watchdog-screenshots",
    ) -> None:
        """Inicializa o StepScreenshotter.

        Args:
            competitor_id: Identificador do concorrente.
            cycle_id: Identificador do ciclo de monitoramento.
            s3_client: Sessão aioboto3 para upload. Se None, cria uma padrão.
            bucket: Nome do bucket S3 de destino.
        """
        self._competitor_id = competitor_id
        self._cycle_id = cycle_id
        self._step_counter = 0
        self._s3_client = s3_client or aioboto3.Session()
        self._bucket = bucket
        self._screenshots: list[StepScreenshot] = []

    @property
    def screenshots(self) -> list[StepScreenshot]:
        """Retorna a lista de screenshots capturados (somente leitura)."""
        return list(self._screenshots)

    @property
    def step_count(self) -> int:
        """Retorna o número de screenshots capturados com sucesso."""
        return self._step_counter

    def _build_s3_key(self, step_number: int, description: str) -> str:
        """Constrói a S3 key para o screenshot.

        Formato: {competitor_id}/{cycle_id}/step_{n:03d}_{descricao}.png

        Args:
            step_number: Número sequencial do step.
            description: Descrição já sanitizada.

        Returns:
            S3 key completa.
        """
        sanitized = _sanitize_description(description)
        return (
            f"{self._competitor_id}/{self._cycle_id}/"
            f"step_{step_number:03d}_{sanitized}.png"
        )

    async def capture(self, page: Page, step_description: str) -> str | None:
        """Captura screenshot da etapa atual, incrementa counter e faz upload ao S3.

        A numeração é estritamente crescente: começa em 1 e incrementa
        monotonicamente a cada chamada bem-sucedida (sem lacunas).

        Falhas de screenshot ou upload NÃO interrompem o fluxo principal.
        Em caso de erro, loga um warning e retorna None.

        Args:
            page: Página Playwright para capturar.
            step_description: Descrição livre da etapa (será sanitizada).

        Returns:
            S3 key do screenshot capturado, ou None em caso de falha.
        """
        try:
            # Incrementar counter ANTES da captura para manter sequência sem lacunas
            self._step_counter += 1
            step_number = self._step_counter

            # Construir S3 key
            s3_key = self._build_s3_key(step_number, step_description)

            # Capturar screenshot via Playwright
            screenshot_bytes = await page.screenshot(type="png", full_page=True)

            # Upload assíncrono para S3
            async with self._s3_client.client("s3") as s3:
                await s3.put_object(
                    Bucket=self._bucket,
                    Key=s3_key,
                    Body=screenshot_bytes,
                    ContentType="image/png",
                )

            # Registrar metadados
            captured_at = datetime.now(timezone.utc).isoformat()
            step_screenshot = StepScreenshot(
                step_number=step_number,
                description=step_description,
                s3_key=s3_key,
                captured_at=captured_at,
            )
            self._screenshots.append(step_screenshot)

            logger.info(
                "Screenshot capturado: step=%d key=%s",
                step_number,
                s3_key,
            )
            return s3_key

        except Exception as exc:
            # Falha de screenshot NÃO interrompe o fluxo principal
            # Reverter counter para manter sequência sem lacunas
            self._step_counter -= 1
            logger.warning(
                "Falha ao capturar screenshot: step_description=%s erro=%s",
                step_description,
                exc,
            )
            return None
