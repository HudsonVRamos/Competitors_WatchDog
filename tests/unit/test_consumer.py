"""Testes unitários para o SQSConsumer.

Valida recebimento, renovação de visibility e acknowledgement
de mensagens SQS usando mocks para simular respostas do serviço AWS.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.queue.consumer import SQSConsumer


SAMPLE_MESSAGE = {
    "product_config_id": "config-123",
    "competitor_id": "comp-456",
    "competitor_name": "HBO Max Brasil",
    "product_name": "Plano Mensal",
    "page_url": "https://www.hbomax.com/br/pt",
    "extraction_strategy": "css_selector",
    "selector_or_pattern": ".price-card .value",
    "our_price": 49.90,
    "cycle_id": "cycle-789",
}


def _mock_sqs_client():
    """Cria um mock do cliente SQS assíncrono."""
    mock_client = AsyncMock()
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    return mock_client, mock_context


class TestSQSConsumerReceiveMessage:
    """Testes para receive_message()."""

    @pytest.mark.asyncio
    async def test_receive_message_retorna_none_fila_vazia(self):
        """Deve retornar None quando a fila está vazia."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {"Messages": []}

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            result = await consumer.receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_retorna_none_sem_chave_messages(self):
        """Deve retornar None quando resposta não tem chave Messages."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {}

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            result = await consumer.receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_retorna_price_check_message(self):
        """Deve retornar PriceCheckMessage quando há mensagem na fila."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "Body": json.dumps(SAMPLE_MESSAGE),
                    "ReceiptHandle": "handle-abc-123",
                }
            ]
        }

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            result = await consumer.receive_message()

        assert result is not None
        assert isinstance(result, PriceCheckMessage)
        assert result.product_config_id == "config-123"
        assert result.competitor_id == "comp-456"
        assert result.competitor_name == "HBO Max Brasil"
        assert result.product_name == "Plano Mensal"
        assert result.page_url == "https://www.hbomax.com/br/pt"
        assert result.extraction_strategy == "css_selector"
        assert result.selector_or_pattern == ".price-card .value"
        assert result.our_price == 49.90
        assert result.cycle_id == "cycle-789"

    @pytest.mark.asyncio
    async def test_receive_message_armazena_receipt_handle(self):
        """Deve armazenar receipt_handle na mensagem retornada."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "Body": json.dumps(SAMPLE_MESSAGE),
                    "ReceiptHandle": "handle-abc-123",
                }
            ]
        }

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            result = await consumer.receive_message()

        assert result is not None
        assert hasattr(result, "_receipt_handle")
        assert result._receipt_handle == "handle-abc-123"

    @pytest.mark.asyncio
    async def test_receive_message_retorna_none_mensagem_corrompida(self):
        """Deve retornar None para mensagem com JSON inválido."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "Body": "json inválido{{",
                    "ReceiptHandle": "handle-corrupt",
                }
            ]
        }

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            result = await consumer.receive_message()

        assert result is None

    @pytest.mark.asyncio
    async def test_receive_message_parametros_corretos(self):
        """Deve chamar SQS com parâmetros corretos de long polling."""
        mock_client, mock_context = _mock_sqs_client()
        mock_client.receive_message.return_value = {"Messages": []}

        consumer = SQSConsumer(queue_url="http://my-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.receive_message()

        mock_client.receive_message.assert_called_once_with(
            QueueUrl="http://my-queue-url",
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )


class TestSQSConsumerRenewVisibility:
    """Testes para renew_visibility()."""

    @pytest.mark.asyncio
    async def test_renew_visibility_chama_change_message_visibility(self):
        """Deve chamar change_message_visibility com parâmetros corretos."""
        mock_client, mock_context = _mock_sqs_client()

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.renew_visibility("handle-123", timeout=120)

        mock_client.change_message_visibility.assert_called_once_with(
            QueueUrl="http://fake-queue-url",
            ReceiptHandle="handle-123",
            VisibilityTimeout=120,
        )

    @pytest.mark.asyncio
    async def test_renew_visibility_timeout_padrao_120(self):
        """Deve usar timeout padrão de 120 segundos."""
        mock_client, mock_context = _mock_sqs_client()

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.renew_visibility("handle-456")

        mock_client.change_message_visibility.assert_called_once_with(
            QueueUrl="http://fake-queue-url",
            ReceiptHandle="handle-456",
            VisibilityTimeout=120,
        )

    @pytest.mark.asyncio
    async def test_renew_visibility_timeout_customizado(self):
        """Deve aceitar timeout customizado."""
        mock_client, mock_context = _mock_sqs_client()

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.renew_visibility("handle-789", timeout=60)

        mock_client.change_message_visibility.assert_called_once_with(
            QueueUrl="http://fake-queue-url",
            ReceiptHandle="handle-789",
            VisibilityTimeout=60,
        )


class TestSQSConsumerAcknowledge:
    """Testes para acknowledge()."""

    @pytest.mark.asyncio
    async def test_acknowledge_chama_delete_message(self):
        """Deve chamar delete_message com parâmetros corretos."""
        mock_client, mock_context = _mock_sqs_client()

        consumer = SQSConsumer(queue_url="http://fake-queue-url")

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.acknowledge("handle-to-delete")

        mock_client.delete_message.assert_called_once_with(
            QueueUrl="http://fake-queue-url",
            ReceiptHandle="handle-to-delete",
        )

    @pytest.mark.asyncio
    async def test_acknowledge_usa_queue_url_correta(self):
        """Deve usar a queue_url configurada no consumer."""
        mock_client, mock_context = _mock_sqs_client()

        consumer = SQSConsumer(
            queue_url="http://custom-queue-url/my-queue"
        )

        with patch.object(
            consumer._session, "client", return_value=mock_context
        ):
            await consumer.acknowledge("any-handle")

        call_args = mock_client.delete_message.call_args
        assert call_args.kwargs["QueueUrl"] == (
            "http://custom-queue-url/my-queue"
        )


class TestSQSConsumerInit:
    """Testes para inicialização do SQSConsumer."""

    def test_init_usa_queue_url_fornecida(self):
        """Deve usar a queue_url fornecida no construtor."""
        consumer = SQSConsumer(queue_url="http://my-custom-url")
        assert consumer._queue_url == "http://my-custom-url"

    def test_init_usa_settings_quando_queue_url_none(self):
        """Deve usar settings.sqs_queue_url quando queue_url é None."""
        with patch(
            "price_watchdog.queue.consumer.settings"
        ) as mock_settings:
            mock_settings.sqs_queue_url = "http://from-settings"
            consumer = SQSConsumer(queue_url=None)
            assert consumer._queue_url == "http://from-settings"

    def test_init_usa_settings_quando_queue_url_vazia(self):
        """Deve usar settings.sqs_queue_url quando queue_url é string vazia."""
        with patch(
            "price_watchdog.queue.consumer.settings"
        ) as mock_settings:
            mock_settings.sqs_queue_url = "http://from-settings"
            consumer = SQSConsumer(queue_url="")
            assert consumer._queue_url == "http://from-settings"
