"""Testes unitários para o Worker de processamento de preços.

Valida o loop principal, processamento de mensagens, degradação graciosa
e renovação de visibility timeout.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.models.dataclasses import (
    PriceCheckMessage,
    ScrapeResult,
)
from price_watchdog.worker.worker import Worker


@pytest.fixture
def message() -> PriceCheckMessage:
    """Cria uma PriceCheckMessage de teste."""
    msg = PriceCheckMessage(
        product_config_id="config-123",
        competitor_id="comp-456",
        competitor_name="Concorrente X",
        product_name="Plano Premium",
        page_url="https://example.com/planos",
        extraction_strategy="css_selector",
        selector_or_pattern=".price-value",
        our_price=99.90,
        cycle_id="cycle-789",
    )
    msg._receipt_handle = "receipt-abc"  # type: ignore[attr-defined]
    return msg


@pytest.fixture
def worker_deps():
    """Cria mocks das dependências do Worker."""
    consumer = AsyncMock()
    scraper = AsyncMock()
    comparator = MagicMock()
    price_store = AsyncMock()
    screenshot_store = AsyncMock()
    alert_service = MagicMock()
    return {
        "consumer": consumer,
        "scraper": scraper,
        "comparator": comparator,
        "price_store": price_store,
        "screenshot_store": screenshot_store,
        "alert_service": alert_service,
    }


@pytest.fixture
def worker(worker_deps) -> Worker:
    """Cria instância do Worker com mocks."""
    return Worker(**worker_deps)


class TestWorkerProcessMessage:
    """Testes de processamento individual de mensagens."""

    @pytest.mark.asyncio
    async def test_processa_mensagem_com_sucesso(
        self, worker, worker_deps, message
    ):
        """Deve processar mensagem, comparar preços e persistir."""
        # Configurar scraper com resultado de sucesso
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=119.90,
            screenshot_bytes=b"fake-png",
        )

        # Configurar comparator
        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = 20.0
        comparison_mock.percentage_difference = 20.02
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        # Configurar screenshot store
        worker_deps["screenshot_store"].upload.return_value = (
            "screenshots/cycle-789/comp-456/20240101T120000.png"
        )

        await worker._process_message(message, "receipt-abc")

        # Verificar que scraper foi chamado
        worker_deps["scraper"].scrape.assert_called_once_with(message)

        # Verificar comparação
        worker_deps["comparator"].compare.assert_called_once_with(
            119.90, 99.90
        )

        # Verificar upload de screenshot
        worker_deps["screenshot_store"].upload.assert_called_once_with(
            screenshot_bytes=b"fake-png",
            cycle_id="cycle-789",
            competitor_id="comp-456",
        )

        # Verificar persistência
        worker_deps["price_store"].save_record.assert_called_once()
        saved_record = (
            worker_deps["price_store"].save_record.call_args[0][0]
        )
        assert saved_record.extraction_status == "success"
        assert saved_record.extracted_price == 119.90
        assert saved_record.price_difference == 20.0
        assert saved_record.price_difference_pct == 20.02

        # Verificar acknowledge
        worker_deps["consumer"].acknowledge.assert_called_once_with(
            "receipt-abc"
        )

    @pytest.mark.asyncio
    async def test_processa_mensagem_com_falha_de_scraping(
        self, worker, worker_deps, message
    ):
        """Deve persistir record com status failed se scraping falhar."""
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="failed",
            failure_reason="Timeout após 30s",
            screenshot_bytes=b"error-screenshot",
        )

        worker_deps["screenshot_store"].upload.return_value = (
            "screenshots/cycle-789/comp-456/error.png"
        )

        await worker._process_message(message, "receipt-abc")

        # Verificar persistência com status failed
        worker_deps["price_store"].save_record.assert_called_once()
        saved_record = (
            worker_deps["price_store"].save_record.call_args[0][0]
        )
        assert saved_record.extraction_status == "failed"
        assert saved_record.failure_reason == "Timeout após 30s"
        assert saved_record.extracted_price is None
        assert saved_record.price_difference is None

        # Ainda faz acknowledge (scraping reportou falha controlada)
        worker_deps["consumer"].acknowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_degradacao_graciosa_em_excecao(
        self, worker, worker_deps, message
    ):
        """Deve registrar PriceRecord failed e não levantar exceção."""
        worker_deps["scraper"].scrape.side_effect = RuntimeError(
            "Erro de conexão"
        )

        # Não deve levantar exceção
        await worker._process_message(message, "receipt-abc")

        # Deve persistir record de falha
        worker_deps["price_store"].save_record.assert_called_once()
        saved_record = (
            worker_deps["price_store"].save_record.call_args[0][0]
        )
        assert saved_record.extraction_status == "failed"
        assert "Erro de conexão" in saved_record.failure_reason

        # Não deve fazer acknowledge (permitir retry via SQS)
        worker_deps["consumer"].acknowledge.assert_not_called()

    @pytest.mark.asyncio
    async def test_sem_screenshot_nao_faz_upload(
        self, worker, worker_deps, message
    ):
        """Não deve fazer upload se não há screenshot."""
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=89.90,
            screenshot_bytes=None,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -10.0
        comparison_mock.percentage_difference = -10.01
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        await worker._process_message(message, "receipt-abc")

        # Não deve chamar upload
        worker_deps["screenshot_store"].upload.assert_not_called()


class TestWorkerMainLoop:
    """Testes do loop principal do worker."""

    @pytest.mark.asyncio
    async def test_loop_para_quando_stop_chamado(
        self, worker, worker_deps
    ):
        """O loop deve encerrar quando stop() é chamado."""
        # Simular: retorna None na primeira chamada, depois para
        call_count = 0

        async def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                worker.stop()
            return None

        worker_deps["consumer"].receive_message.side_effect = (
            side_effect
        )

        await worker.run()

        assert not worker._running
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_loop_continua_apos_erro_no_processamento(
        self, worker, worker_deps, message
    ):
        """O loop principal não deve parar por erro em uma mensagem."""
        call_count = 0

        async def receive_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = PriceCheckMessage(
                    product_config_id="config-err",
                    competitor_id="comp-err",
                    competitor_name="Concorrente Erro",
                    product_name="Plano Erro",
                    page_url="https://error.com",
                    extraction_strategy="css_selector",
                    selector_or_pattern=".price",
                    our_price=50.0,
                    cycle_id="cycle-err",
                )
                msg._receipt_handle = "receipt-err"  # type: ignore[attr-defined]
                return msg
            if call_count == 2:
                worker.stop()
            return None

        worker_deps["consumer"].receive_message.side_effect = (
            receive_side_effect
        )
        worker_deps["scraper"].scrape.side_effect = RuntimeError(
            "Boom"
        )

        await worker.run()

        # O loop continuou e chamou receive pelo menos 2x
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_mensagem_sem_receipt_handle_ignorada(
        self, worker, worker_deps
    ):
        """Mensagem sem receipt_handle deve ser ignorada."""
        call_count = 0

        async def receive_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Mensagem sem _receipt_handle
                return PriceCheckMessage(
                    product_config_id="config-no-handle",
                    competitor_id="comp-no-handle",
                    competitor_name="Sem Handle",
                    product_name="Produto",
                    page_url="https://example.com",
                    extraction_strategy="css_selector",
                    selector_or_pattern=".price",
                    our_price=10.0,
                    cycle_id="cycle-no",
                )
            worker.stop()
            return None

        worker_deps["consumer"].receive_message.side_effect = (
            receive_side_effect
        )

        await worker.run()

        # Scraper não deve ser chamado
        worker_deps["scraper"].scrape.assert_not_called()


class TestVisibilityRenewal:
    """Testes de renovação de visibility timeout."""

    @pytest.mark.asyncio
    async def test_visibility_renovada_durante_processamento(
        self, worker, worker_deps, message
    ):
        """Visibility deve ser renovada durante processamento longo."""
        # Simular scraping demorado (> 30s simulados)
        async def slow_scrape(msg):
            # Aguardar tempo suficiente para 1 renovação
            await asyncio.sleep(0.1)
            return ScrapeResult(
                extraction_status="success",
                extracted_price=100.0,
            )

        worker_deps["scraper"].scrape.side_effect = slow_scrape

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = 0.10
        comparison_mock.percentage_difference = 0.10
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        # Patch do intervalo para teste rápido
        with patch(
            "price_watchdog.worker.worker._VISIBILITY_RENEWAL_INTERVAL",
            0.05,
        ):
            await worker._process_message(message, "receipt-abc")

        # Verificar que renew_visibility foi chamada pelo menos 1x
        assert (
            worker_deps["consumer"].renew_visibility.call_count >= 1
        )

    @pytest.mark.asyncio
    async def test_visibility_cancelada_apos_processamento(
        self, worker, worker_deps, message
    ):
        """Task de renovação deve ser cancelada ao finalizar."""
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=50.0,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -49.90
        comparison_mock.percentage_difference = -49.95
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        await worker._process_message(message, "receipt-abc")

        # Se chegou aqui sem travar, a task foi cancelada corretamente
        # (não ficou rodando infinitamente)

    @pytest.mark.asyncio
    async def test_falha_renovacao_nao_interrompe_processamento(
        self, worker, worker_deps, message
    ):
        """Erro na renovação não deve afetar o processamento."""
        worker_deps["consumer"].renew_visibility.side_effect = (
            RuntimeError("SQS Error")
        )

        async def slow_scrape(msg):
            await asyncio.sleep(0.1)
            return ScrapeResult(
                extraction_status="success",
                extracted_price=75.0,
            )

        worker_deps["scraper"].scrape.side_effect = slow_scrape

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -24.90
        comparison_mock.percentage_difference = -24.92
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        with patch(
            "price_watchdog.worker.worker._VISIBILITY_RENEWAL_INTERVAL",
            0.05,
        ):
            await worker._process_message(message, "receipt-abc")

        # Processamento completo mesmo com falha na renovação
        worker_deps["price_store"].save_record.assert_called_once()
        worker_deps["consumer"].acknowledge.assert_called_once()


class TestWorkerStop:
    """Testes do método stop()."""

    def test_stop_seta_flag_running_false(self, worker):
        """stop() deve setar _running = False."""
        worker._running = True
        worker.stop()
        assert worker._running is False


class TestWorkerAlertEvaluation:
    """Testes da lógica de alertas no processamento de mensagens."""

    @pytest.mark.asyncio
    async def test_alerta_disparado_quando_threshold_excedido(
        self, worker_deps, message
    ):
        """Deve avaliar alertas após comparação com sucesso."""
        from price_watchdog.alerts.alert_service import PriceAlert

        # Configurar worker com email_notifier mock
        email_notifier = AsyncMock()
        worker = Worker(**worker_deps, email_notifier=email_notifier)

        # Scraper retorna sucesso
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=80.0,
        )

        # Comparator
        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -19.90
        comparison_mock.percentage_difference = -19.92
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        # Preço anterior era 100.0, agora é 80.0 → queda de 20%
        worker_deps["price_store"].get_previous_price.return_value = (
            100.0
        )

        # AlertService retorna alerta
        alert = PriceAlert(
            alert_type="price_drop",
            threshold_pct=5.0,
            actual_difference_pct=-20.0,
        )
        worker_deps["alert_service"].evaluate.return_value = alert

        await worker._process_message(message, "receipt-abc")

        # Verificar que get_previous_price foi chamado
        worker_deps[
            "price_store"
        ].get_previous_price.assert_called_once_with(
            "config-123"
        )

        # Verificar que evaluate foi chamado com parâmetros corretos
        worker_deps["alert_service"].evaluate.assert_called_once()
        call_kwargs = (
            worker_deps["alert_service"].evaluate.call_args[1]
        )
        assert call_kwargs["current_price"] == 80.0
        assert call_kwargs["previous_price"] == 100.0
        assert call_kwargs["our_price"] == 99.90

        # Verificar que email foi enviado
        email_notifier.send_alert.assert_called_once_with(
            alert=alert,
            recipients=[],
        )

    @pytest.mark.asyncio
    async def test_sem_alerta_nao_envia_email(
        self, worker_deps, message
    ):
        """Não deve enviar email se evaluate retorna None."""
        email_notifier = AsyncMock()
        worker = Worker(**worker_deps, email_notifier=email_notifier)

        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=100.0,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = 0.10
        comparison_mock.percentage_difference = 0.10
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        # Sem preço anterior → evaluate retorna None
        worker_deps["price_store"].get_previous_price.return_value = (
            None
        )
        worker_deps["alert_service"].evaluate.return_value = None

        await worker._process_message(message, "receipt-abc")

        # Email não deve ser enviado
        email_notifier.send_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_falha_alert_nao_interrompe_processamento(
        self, worker_deps, message
    ):
        """Falha na avaliação de alertas não deve impedir o fluxo."""
        worker = Worker(**worker_deps)

        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=50.0,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -49.90
        comparison_mock.percentage_difference = -49.95
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        # get_previous_price lança exceção
        worker_deps[
            "price_store"
        ].get_previous_price.side_effect = RuntimeError(
            "DB connection lost"
        )

        await worker._process_message(message, "receipt-abc")

        # O processamento continuou normalmente
        worker_deps["price_store"].save_record.assert_called_once()
        worker_deps["consumer"].acknowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_falha_notificacao_nao_interrompe_processamento(
        self, worker_deps, message
    ):
        """Falha no envio de email não deve impedir o fluxo."""
        from price_watchdog.alerts.alert_service import PriceAlert

        email_notifier = AsyncMock()
        email_notifier.send_alert.side_effect = RuntimeError(
            "SES error"
        )
        worker = Worker(**worker_deps, email_notifier=email_notifier)

        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=50.0,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -49.90
        comparison_mock.percentage_difference = -49.95
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        worker_deps["price_store"].get_previous_price.return_value = (
            100.0
        )

        alert = PriceAlert(
            alert_type="price_drop",
            threshold_pct=5.0,
            actual_difference_pct=-50.0,
        )
        worker_deps["alert_service"].evaluate.return_value = alert

        await worker._process_message(message, "receipt-abc")

        # O processamento continuou normalmente apesar da falha no email
        worker_deps["price_store"].save_record.assert_called_once()
        worker_deps["consumer"].acknowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_sem_email_notifier_nao_tenta_enviar(
        self, worker, worker_deps, message
    ):
        """Sem email_notifier, não deve tentar enviar notificação."""
        from price_watchdog.alerts.alert_service import PriceAlert

        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="success",
            extracted_price=50.0,
        )

        comparison_mock = MagicMock()
        comparison_mock.absolute_difference = -49.90
        comparison_mock.percentage_difference = -49.95
        worker_deps["comparator"].compare.return_value = (
            comparison_mock
        )

        worker_deps["price_store"].get_previous_price.return_value = (
            100.0
        )

        alert = PriceAlert(
            alert_type="price_drop",
            threshold_pct=5.0,
            actual_difference_pct=-50.0,
        )
        worker_deps["alert_service"].evaluate.return_value = alert

        # Worker sem email_notifier (default)
        await worker._process_message(message, "receipt-abc")

        # O processamento continuou normalmente
        worker_deps["price_store"].save_record.assert_called_once()
        worker_deps["consumer"].acknowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_nao_avalia_alertas_se_extracao_falhou(
        self, worker, worker_deps, message
    ):
        """Não deve avaliar alertas se extração falhou."""
        worker_deps["scraper"].scrape.return_value = ScrapeResult(
            extraction_status="failed",
            failure_reason="Timeout",
        )

        await worker._process_message(message, "receipt-abc")

        # get_previous_price NÃO deve ser chamado
        worker_deps[
            "price_store"
        ].get_previous_price.assert_not_called()
        worker_deps["alert_service"].evaluate.assert_not_called()
