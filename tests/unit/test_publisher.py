"""Testes unitários para o SQSPublisher."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from price_watchdog.queue.publisher import SQSPublisher
from price_watchdog.models.dataclasses import PriceCheckMessage


def _make_message(index: int = 0) -> PriceCheckMessage:
    """Cria uma PriceCheckMessage de teste."""
    return PriceCheckMessage(
        product_config_id=f"config-{index}",
        competitor_id=f"comp-{index}",
        competitor_name=f"Competitor {index}",
        product_name=f"Product {index}",
        page_url=f"https://example.com/product/{index}",
        extraction_strategy="css_selector",
        selector_or_pattern=".price",
        our_price=99.90,
        cycle_id="cycle-001",
    )


@pytest.fixture
def publisher():
    """Publisher com URL de fila de teste."""
    return SQSPublisher(queue_url="https://sqs.us-east-1.amazonaws.com/123/test-queue")


class TestPublishBatch:
    """Testes para publish_batch."""

    @pytest.mark.asyncio
    async def test_batch_vazio_retorna_zero(self, publisher):
        """Lista vazia retorna 0 sem chamar SQS."""
        result = await publisher.publish_batch([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_excede_10_mensagens_erro(self, publisher):
        """Mais de 10 mensagens gera ValueError."""
        messages = [_make_message(i) for i in range(11)]
        with pytest.raises(ValueError, match="não pode exceder 10"):
            await publisher.publish_batch(messages)

    @pytest.mark.asyncio
    async def test_batch_sucesso_retorna_contagem(self, publisher):
        """Batch com 3 mensagens retorna 3 quando todas sucesso."""
        messages = [_make_message(i) for i in range(3)]

        mock_sqs = AsyncMock()
        mock_sqs.send_message_batch = AsyncMock(return_value={
            "Successful": [{"Id": f"id-{i}"} for i in range(3)],
            "Failed": [],
        })

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            publisher._session, "client", return_value=mock_context
        ):
            result = await publisher.publish_batch(messages)

        assert result == 3
        mock_sqs.send_message_batch.assert_called_once()
        call_kwargs = mock_sqs.send_message_batch.call_args[1]
        assert len(call_kwargs["Entries"]) == 3

    @pytest.mark.asyncio
    async def test_batch_com_falhas_parciais(self, publisher):
        """Batch com falhas parciais retorna apenas sucessos."""
        messages = [_make_message(i) for i in range(5)]

        mock_sqs = AsyncMock()
        mock_sqs.send_message_batch = AsyncMock(return_value={
            "Successful": [{"Id": f"id-{i}"} for i in range(3)],
            "Failed": [
                {"Id": "id-3", "Code": "InternalError", "Message": "err"},
                {"Id": "id-4", "Code": "InternalError", "Message": "err"},
            ],
        })

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            publisher._session, "client", return_value=mock_context
        ):
            result = await publisher.publish_batch(messages)

        assert result == 3


class TestPublishAll:
    """Testes para publish_all."""

    @pytest.mark.asyncio
    async def test_lista_vazia_retorna_zero(self, publisher):
        """Lista vazia retorna 0."""
        result = await publisher.publish_all([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_menos_de_10_mensagens_um_batch(self, publisher):
        """Até 10 mensagens usa um único batch."""
        messages = [_make_message(i) for i in range(7)]

        mock_sqs = AsyncMock()
        mock_sqs.send_message_batch = AsyncMock(return_value={
            "Successful": [{"Id": f"id-{i}"} for i in range(7)],
            "Failed": [],
        })

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            publisher._session, "client", return_value=mock_context
        ):
            result = await publisher.publish_all(messages)

        assert result == 7
        assert mock_sqs.send_message_batch.call_count == 1

    @pytest.mark.asyncio
    async def test_25_mensagens_gera_3_batches(self, publisher):
        """25 mensagens devem gerar 3 batches (10+10+5)."""
        messages = [_make_message(i) for i in range(25)]

        call_count = 0

        async def mock_send_batch(**kwargs):
            nonlocal call_count
            entries = kwargs["Entries"]
            call_count += 1
            return {
                "Successful": [{"Id": e["Id"]} for e in entries],
                "Failed": [],
            }

        mock_sqs = AsyncMock()
        mock_sqs.send_message_batch = mock_send_batch

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            publisher._session, "client", return_value=mock_context
        ):
            result = await publisher.publish_all(messages)

        assert result == 25
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_batch_size_limitado_a_10(self, publisher):
        """batch_size maior que 10 é limitado a 10."""
        messages = [_make_message(i) for i in range(15)]

        call_count = 0

        async def mock_send_batch(**kwargs):
            nonlocal call_count
            entries = kwargs["Entries"]
            # Verifica que nenhum batch excede 10
            assert len(entries) <= 10
            call_count += 1
            return {
                "Successful": [{"Id": e["Id"]} for e in entries],
                "Failed": [],
            }

        mock_sqs = AsyncMock()
        mock_sqs.send_message_batch = mock_send_batch

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_sqs)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch.object(
            publisher._session, "client", return_value=mock_context
        ):
            # Tenta batch_size=20, mas internamente limita a 10
            result = await publisher.publish_all(messages, batch_size=20)

        assert result == 15
        assert call_count == 2  # 10 + 5
