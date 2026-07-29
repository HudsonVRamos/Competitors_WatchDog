"""Publisher SQS para envio de mensagens em batches.

Utiliza aioboto3 para operações assíncronas com a fila SQS,
dividindo mensagens em batches de até 10 (limite da API SQS).
"""

from __future__ import annotations

import logging
import uuid

import aioboto3

from price_watchdog.config import settings
from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.queue.messages import serialize_message

logger = logging.getLogger(__name__)


class SQSPublisher:
    """Publica mensagens na fila SQS em batches.

    Cada batch contém no máximo 10 mensagens, respeitando o limite
    da API send_message_batch do SQS.

    Attributes:
        _queue_url: URL da fila SQS de destino.
        _session: Sessão aioboto3 para operações async.
    """

    def __init__(self, queue_url: str | None = None) -> None:
        """Inicializa o publisher com a URL da fila.

        Args:
            queue_url: URL da fila SQS. Se None, usa settings.
        """
        self._queue_url = queue_url or settings.sqs_queue_url
        self._session = aioboto3.Session()

    async def publish_batch(
        self, messages: list[PriceCheckMessage]
    ) -> int:
        """Publica até 10 mensagens em um único batch.

        Args:
            messages: Lista de mensagens (máximo 10).

        Returns:
            Quantidade de mensagens enviadas com sucesso.

        Raises:
            ValueError: Se mais de 10 mensagens forem passadas.
        """
        if not messages:
            return 0

        if len(messages) > 10:
            raise ValueError(
                f"Batch não pode exceder 10 mensagens, "
                f"recebido: {len(messages)}"
            )

        entries = []
        for msg in messages:
            entry = {
                "Id": str(uuid.uuid4()),
                "MessageBody": serialize_message(msg),
            }
            entries.append(entry)

        async with self._session.client("sqs") as sqs:
            response = await sqs.send_message_batch(
                QueueUrl=self._queue_url,
                Entries=entries,
            )

        successful = response.get("Successful", [])
        failed = response.get("Failed", [])

        if failed:
            for failure in failed:
                logger.error(
                    "Falha ao publicar mensagem SQS: "
                    "Id=%s, Code=%s, Message=%s",
                    failure.get("Id"),
                    failure.get("Code"),
                    failure.get("Message"),
                )

        sent_count = len(successful)
        logger.info(
            "Batch SQS publicado: %d/%d mensagens enviadas",
            sent_count,
            len(messages),
        )

        return sent_count

    async def publish_all(
        self,
        messages: list[PriceCheckMessage],
        batch_size: int = 10,
    ) -> int:
        """Publica todas as mensagens dividindo em batches.

        Divide a lista de mensagens em sub-listas de tamanho
        batch_size e envia cada uma via publish_batch.

        Args:
            messages: Lista completa de mensagens a publicar.
            batch_size: Tamanho máximo de cada batch (padrão 10).

        Returns:
            Total de mensagens enviadas com sucesso.
        """
        if not messages:
            return 0

        # Garante que batch_size não exceda o limite da API
        batch_size = min(batch_size, 10)

        total_sent = 0

        for i in range(0, len(messages), batch_size):
            batch = messages[i:i + batch_size]
            sent = await self.publish_batch(batch)
            total_sent += sent

        logger.info(
            "Publicação completa: %d/%d mensagens enviadas "
            "em %d batches",
            total_sent,
            len(messages),
            -(-len(messages) // batch_size),  # ceil division
        )

        return total_sent
