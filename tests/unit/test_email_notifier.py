"""Testes unitários para o EmailNotifier."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.alerts.alert_service import PriceAlert
from price_watchdog.alerts.email_notifier import EmailNotifier
from price_watchdog.models.entities import PriceCycle


@pytest.fixture
def notifier():
    """Cria instância do EmailNotifier."""
    return EmailNotifier()


@pytest.fixture
def sample_alert():
    """Cria alerta de exemplo para testes."""
    return PriceAlert(
        alert_type="price_drop",
        threshold_pct=5.0,
        actual_difference_pct=-7.5,
    )


@pytest.fixture
def sample_cycle():
    """Cria ciclo de exemplo para testes."""
    cycle = PriceCycle()
    cycle.id = uuid.uuid4()
    cycle.started_at = datetime(2024, 6, 15, 10, 0, 0)
    cycle.ended_at = datetime(2024, 6, 15, 10, 30, 0)
    cycle.status = "completed"
    cycle.total_products = 10
    cycle.products_succeeded = 8
    cycle.products_failed = 2
    cycle.alerts_triggered = 1
    return cycle


@pytest.fixture
def recipients():
    """Lista de destinatários de teste."""
    return ["analista@empresa.com", "gerente@empresa.com"]


class TestSendAlert:
    """Testes para o método send_alert."""

    @pytest.mark.asyncio
    async def test_send_alert_success(
        self, notifier, sample_alert, recipients
    ):
        """Deve enviar email de alerta via SES com sucesso."""
        mock_ses = AsyncMock()
        mock_ses.send_raw_email = AsyncMock(return_value={})

        with patch.object(
            notifier, "_session"
        ) as mock_session:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_ses)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_session.client.return_value = mock_client

            await notifier.send_alert(sample_alert, recipients)

            mock_ses.send_raw_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_empty_recipients(
        self, notifier, sample_alert
    ):
        """Não deve enviar email se não há destinatários."""
        with patch.object(notifier, "_send_raw_email") as mock_send:
            await notifier.send_alert(sample_alert, [])
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_alert_handles_failure_gracefully(
        self, notifier, sample_alert, recipients
    ):
        """Deve logar erro mas não crashar se envio falhar."""
        with patch.object(
            notifier,
            "_send_raw_email",
            side_effect=Exception("SES indisponível"),
        ):
            # Não deve levantar exceção
            await notifier.send_alert(sample_alert, recipients)


class TestSendReport:
    """Testes para o método send_report."""

    @pytest.mark.asyncio
    async def test_send_report_success(
        self, notifier, sample_cycle, recipients
    ):
        """Deve enviar relatório como anexo via SES."""
        report_bytes = b"fake excel content"

        mock_ses = AsyncMock()
        mock_ses.send_raw_email = AsyncMock(return_value={})

        with patch.object(
            notifier, "_session"
        ) as mock_session:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_ses)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_session.client.return_value = mock_client

            await notifier.send_report(
                report_bytes, sample_cycle, recipients
            )

            mock_ses.send_raw_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_report_empty_recipients(
        self, notifier, sample_cycle
    ):
        """Não deve enviar relatório se não há destinatários."""
        with patch.object(notifier, "_send_raw_email") as mock_send:
            await notifier.send_report(b"data", sample_cycle, [])
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_report_handles_failure_gracefully(
        self, notifier, sample_cycle, recipients
    ):
        """Deve logar erro mas não crashar se envio falhar."""
        with patch.object(
            notifier,
            "_send_raw_email",
            side_effect=Exception("SES indisponível"),
        ):
            # Não deve levantar exceção
            await notifier.send_report(
                b"data", sample_cycle, recipients
            )


class TestAlertEmailContent:
    """Testes para conteúdo do email de alerta."""

    def test_alert_subject_price_drop(self, notifier, sample_alert):
        """Assunto deve conter tipo de alerta e variação."""
        subject = notifier._build_alert_subject(sample_alert)
        assert "Queda de Preço" in subject
        assert "Price Watchdog" in subject

    def test_alert_subject_price_increase(self, notifier):
        """Assunto deve indicar aumento de preço."""
        alert = PriceAlert(
            alert_type="price_increase",
            threshold_pct=10.0,
            actual_difference_pct=15.0,
        )
        subject = notifier._build_alert_subject(alert)
        assert "Aumento de Preço" in subject

    def test_alert_body_contains_info(self, notifier, sample_alert):
        """Corpo do email deve conter informações do alerta."""
        body = notifier._build_alert_body(sample_alert)
        assert "price_drop" in body
        assert "-7.50%" in body
        assert "5.00%" in body


class TestReportEmailContent:
    """Testes para conteúdo do email de relatório."""

    def test_report_subject_contains_date(self, notifier, sample_cycle):
        """Assunto deve conter data do ciclo."""
        subject = notifier._build_report_subject(sample_cycle)
        assert "15/06/2024" in subject
        assert "Price Watchdog" in subject

    def test_report_body_contains_stats(self, notifier, sample_cycle):
        """Corpo deve conter estatísticas do ciclo."""
        body = notifier._build_report_body(sample_cycle)
        assert "10" in body  # total_products
        assert "8" in body  # products_succeeded
        assert "2" in body  # products_failed
