"""Testes de integração para SQS: publicação e consumo de mensagens.

Utiliza moto (@mock_aws) para simular o serviço SQS localmente,
validando o fluxo completo de publicação em batch, consumo,
renovação de visibility e acknowledgement.
"""

import json
import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.queue.consumer import SQSConsumer
from price_watchdog.queue.messages import (
    REQUIRED_FIELDS,
    deserialize_message,
    serialize_message,
)
from price_watchdog.queue.publisher import SQSPublisher


# Região padrão para testes
TEST_REGION = "us-east-1"
TEST_QUEUE_NAME = "price-check-test-queue"


def _create_sample_messages(count: int = 3) -> list[PriceCheckMessage]:
    """Cria uma lista de mensagens de exemplo para testes."""
    messages = []
    for i in range(count):
        msg = PriceCheckMessage(
            product_config_id=f"config-{i}",
            competitor_id=f"comp-{i}",
            competitor_name=f"Concorrente {i}",
            product_name=f"Produto {i}",
            page_url=f"https://example.com/product-{i}",
            extraction_strategy="css_selector",
            selector_or_pattern=f".price-{i}",
            our_price=49.90 + i * 10,
            cycle_id="cycle-integration-test",
        )
        messages.append(msg)
    return messages


@pytest.fixture
def aws_credentials():
    """Configura credenciais fake para moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION
    yield
    # Cleanup não necessário pois moto limpa automaticamente


@pytest.fixture
def sqs_queue_url(aws_credentials):
    """Cria uma fila SQS e retorna a URL."""
    with mock_aws():
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        response = sqs.create_queue(QueueName=TEST_QUEUE_NAME)
        yield response["QueueUrl"]


class TestSQSPublishAndConsumeBatch:
    """Testa publicação em batch e consumo de mensagens SQS."""

    @mock_aws
    def test_publish_batch_envia_mensagens_para_fila(self, aws_credentials):
        """Publica batch de mensagens e verifica que estão na fila."""
        # Setup: criar fila
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(QueueName=TEST_QUEUE_NAME)
        queue_url = queue["QueueUrl"]

        # Publicar mensagens usando sync boto3 (validação direta)
        messages = _create_sample_messages(5)
        entries = []
        for i, msg in enumerate(messages):
            entries.append({
                "Id": str(i),
                "MessageBody": serialize_message(msg),
            })

        response = sqs.send_message_batch(
            QueueUrl=queue_url, Entries=entries
        )

        # Verificar que todas foram enviadas com sucesso
        assert len(response["Successful"]) == 5
        assert "Failed" not in response or len(response.get("Failed", [])) == 0

        # Verificar atributos da fila
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        approx_count = int(
            attrs["Attributes"]["ApproximateNumberOfMessages"]
        )
        assert approx_count == 5

    @mock_aws
    def test_publish_and_consume_roundtrip(self, aws_credentials):
        """Publica uma mensagem e consome, validando integridade dos dados."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(QueueName=TEST_QUEUE_NAME)
        queue_url = queue["QueueUrl"]

        # Publicar mensagem
        original_msg = PriceCheckMessage(
            product_config_id="config-roundtrip",
            competitor_id="comp-roundtrip",
            competitor_name="HBO Max Brasil",
            product_name="Plano Mensal Premium",
            page_url="https://www.hbomax.com/br/pt/pricing",
            extraction_strategy="css_selector",
            selector_or_pattern=".plan-card .price",
            our_price=54.90,
            cycle_id="cycle-roundtrip-001",
        )

        sqs.send_message(
            QueueUrl=queue_url, MessageBody=serialize_message(original_msg)
        )

        # Consumir mensagem
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1
        )
        messages = response.get("Messages", [])
        assert len(messages) == 1

        # Deserializar e comparar
        consumed_msg = deserialize_message(messages[0]["Body"])
        assert consumed_msg.product_config_id == original_msg.product_config_id
        assert consumed_msg.competitor_id == original_msg.competitor_id
        assert consumed_msg.competitor_name == original_msg.competitor_name
        assert consumed_msg.product_name == original_msg.product_name
        assert consumed_msg.page_url == original_msg.page_url
        assert consumed_msg.extraction_strategy == original_msg.extraction_strategy
        assert consumed_msg.selector_or_pattern == original_msg.selector_or_pattern
        assert consumed_msg.our_price == original_msg.our_price
        assert consumed_msg.cycle_id == original_msg.cycle_id


class TestSQSMessageFields:
    """Testa que mensagens serializadas contêm todos os campos obrigatórios."""

    @mock_aws
    def test_mensagem_serializada_contem_campos_obrigatorios(
        self, aws_credentials
    ):
        """Após publicar e consumir, a mensagem contém todos os campos."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(QueueName=TEST_QUEUE_NAME)
        queue_url = queue["QueueUrl"]

        msg = PriceCheckMessage(
            product_config_id="cfg-001",
            competitor_id="comp-001",
            competitor_name="Claro TV+",
            product_name="Combo Fibra",
            page_url="https://www.claro.com.br/tv",
            extraction_strategy="regex",
            selector_or_pattern=r"R\$\s*([\d.,]+)",
            our_price=119.90,
            cycle_id="cycle-fields-test",
        )

        sqs.send_message(
            QueueUrl=queue_url, MessageBody=serialize_message(msg)
        )

        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1
        )
        body = response["Messages"][0]["Body"]
        data = json.loads(body)

        # Verificar que todos os campos obrigatórios estão presentes
        for field in REQUIRED_FIELDS:
            assert field in data, f"Campo obrigatório ausente: {field}"

    @mock_aws
    def test_tipos_dos_campos_preservados_apos_roundtrip(
        self, aws_credentials
    ):
        """Os tipos dos campos são preservados após serialização/deserialização."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(QueueName=TEST_QUEUE_NAME)
        queue_url = queue["QueueUrl"]

        msg = PriceCheckMessage(
            product_config_id="cfg-types",
            competitor_id="comp-types",
            competitor_name="Vivo TV",
            product_name="Plano HD",
            page_url="https://www.vivo.com.br/tv",
            extraction_strategy="ai",
            selector_or_pattern="preço mensal",
            our_price=89.99,
            cycle_id="cycle-types-test",
        )

        sqs.send_message(
            QueueUrl=queue_url, MessageBody=serialize_message(msg)
        )

        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1
        )
        consumed = deserialize_message(response["Messages"][0]["Body"])

        # Validar tipos
        assert isinstance(consumed.product_config_id, str)
        assert isinstance(consumed.competitor_id, str)
        assert isinstance(consumed.competitor_name, str)
        assert isinstance(consumed.product_name, str)
        assert isinstance(consumed.page_url, str)
        assert isinstance(consumed.extraction_strategy, str)
        assert isinstance(consumed.selector_or_pattern, str)
        assert isinstance(consumed.our_price, float)
        assert isinstance(consumed.cycle_id, str)


class TestSQSVisibilityRenewal:
    """Testa renovação de visibility timeout no SQS."""

    @mock_aws
    def test_visibility_timeout_change(self, aws_credentials):
        """Renovar visibility timeout mantém mensagem invisível."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(
            QueueName=TEST_QUEUE_NAME,
            Attributes={"VisibilityTimeout": "30"},
        )
        queue_url = queue["QueueUrl"]

        # Enviar mensagem
        msg = _create_sample_messages(1)[0]
        sqs.send_message(
            QueueUrl=queue_url, MessageBody=serialize_message(msg)
        )

        # Receber mensagem (fica invisível por 30s)
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1
        )
        receipt_handle = response["Messages"][0]["ReceiptHandle"]

        # Renovar visibility para 120s
        sqs.change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=120,
        )

        # Tentar receber novamente - não deve retornar nada
        # (mensagem ainda invisível)
        response2 = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=0,
        )
        assert len(response2.get("Messages", [])) == 0


class TestSQSAcknowledge:
    """Testa que acknowledge (delete) remove mensagem da fila."""

    @mock_aws
    def test_acknowledge_remove_mensagem_da_fila(self, aws_credentials):
        """Após delete_message, a mensagem não está mais na fila."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(
            QueueName=TEST_QUEUE_NAME,
            Attributes={"VisibilityTimeout": "0"},
        )
        queue_url = queue["QueueUrl"]

        # Enviar mensagem
        msg = _create_sample_messages(1)[0]
        sqs.send_message(
            QueueUrl=queue_url, MessageBody=serialize_message(msg)
        )

        # Receber mensagem
        response = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=1
        )
        receipt_handle = response["Messages"][0]["ReceiptHandle"]

        # Acknowledge (deletar)
        sqs.delete_message(
            QueueUrl=queue_url, ReceiptHandle=receipt_handle
        )

        # Verificar que a fila está vazia
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )
        total = int(
            attrs["Attributes"]["ApproximateNumberOfMessages"]
        ) + int(
            attrs["Attributes"]["ApproximateNumberOfMessagesNotVisible"]
        )
        assert total == 0

    @mock_aws
    def test_acknowledge_multiple_mensagens(self, aws_credentials):
        """Acknowledge de múltiplas mensagens remove todas da fila."""
        sqs = boto3.client("sqs", region_name=TEST_REGION)
        queue = sqs.create_queue(
            QueueName=TEST_QUEUE_NAME,
            Attributes={"VisibilityTimeout": "0"},
        )
        queue_url = queue["QueueUrl"]

        # Enviar 3 mensagens
        messages = _create_sample_messages(3)
        for msg in messages:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=serialize_message(msg),
            )

        # Receber e deletar todas
        for _ in range(3):
            response = sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=1
            )
            if response.get("Messages"):
                handle = response["Messages"][0]["ReceiptHandle"]
                sqs.delete_message(
                    QueueUrl=queue_url, ReceiptHandle=handle
                )

        # Verificar fila vazia
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        assert (
            int(attrs["Attributes"]["ApproximateNumberOfMessages"]) == 0
        )
