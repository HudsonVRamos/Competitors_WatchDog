"""Consumer SQS assíncrono para processamento de mensagens de preço.

Consome mensagens da fila SQS, com suporte a renovação de visibility
timeout e acknowledgement (remoção) de mensagens processadas.
"""

from __future__ import annotations

import logging

import aioboto3

from price_watchdog.config import settings
from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.queue.messages import deserialize_message

logger = logging.getLogger(__name__)


class SQSConsumer:
    """Consome mensagens da fila SQS com renovação de visibility.

    Utiliza aioboto3 para operações assíncronas de recebimento,
    renovação de visibility timeout e remoção de mensagens.

    Attributes:
        _queue_url: URL da fila SQS configurada.
        _session: Sessão aioboto3 para criar clientes SQS.
    """

    def __init__(self, queue_url: str | None = None) -> None:
        """Inicializa o consumer com a URL da fila SQS.

        Args:
            queue_url: URL da fila SQS. Se None, usa o valor
                da configuração (settings.sqs_queue_url).
        """
        self._queue_url = queue_url or settings.sqs_queue_url
        self._session = aioboto3.Session()

    async def receive_message(self) -> PriceCheckMessage | None:
        """Recebe uma mensagem da fila SQS.

        Realiza long polling (até 20 segundos) para receber uma
        mensagem. Retorna None se nenhuma mensagem estiver disponível.

        Returns:
            PriceCheckMessage deserializada ou None se a fila estiver vazia.
        """
        async with self._session.client("sqs") as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )

        messages = response.get("Messages", [])
        if not messages:
            logger.debug("Nenhuma mensagem disponível na fila.")
            return None

        raw_message = messages[0]
        body = raw_message["Body"]
        receipt_handle = raw_message["ReceiptHandle"]

        try:
            message = deserialize_message(body)
        except ValueError as e:
            logger.error(
                "Mensagem corrompida na fila (será enviada para DLQ): %s",
                e,
            )
            return None

        # Armazena o receipt_handle na mensagem para uso posterior
        # via atributo dinâmico (não faz parte do dataclass)
        message._receipt_handle = receipt_handle  # type: ignore[attr-defined]

        logger.info(
            "Mensagem recebida: product_config_id=%s, cycle_id=%s",
            message.product_config_id,
            message.cycle_id,
        )

        return message

    async def renew_visibility(
        self, receipt_handle: str, timeout: int = 120
    ) -> None:
        """Renova o visibility timeout de uma mensagem na fila.

        Deve ser chamado periodicamente enquanto a mensagem está
        sendo processada para evitar que ela se torne visível
        novamente e seja reprocessada por outro worker.

        Args:
            receipt_handle: Handle de recebimento da mensagem.
            timeout: Novo timeout de visibilidade em segundos (padrão 120).
        """
        async with self._session.client("sqs") as sqs:
            await sqs.change_message_visibility(
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=timeout,
            )

        logger.debug(
            "Visibility timeout renovado para %d segundos.", timeout
        )

    async def acknowledge(self, receipt_handle: str) -> None:
        """Remove uma mensagem da fila (processamento concluído).

        Confirma que a mensagem foi processada com sucesso,
        removendo-a definitivamente da fila SQS.

        Args:
            receipt_handle: Handle de recebimento da mensagem a remover.
        """
        async with self._session.client("sqs") as sqs:
            await sqs.delete_message(
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt_handle,
            )

        logger.info("Mensagem removida da fila (acknowledged).")
