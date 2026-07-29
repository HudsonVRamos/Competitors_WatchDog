"""Testes de wiring dos entrypoints do Price Watchdog.

Verifica que os módulos main_coordinator e main_worker podem ser
importados e que todas as dependências são conectadas corretamente
com mocks, simulando o fluxo end-to-end.

Requirements: 1.1, 1.2, 1.3, 1.4
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCoordinatorEntrypoint:
    """Testes de integração do entrypoint do Coordinator."""

    def test_coordinator_main_importable(self):
        """Verifica que main_coordinator é importável sem erros."""
        from price_watchdog.main_coordinator import main

        assert asyncio.iscoroutinefunction(main)

    def test_coordinator_imports_all_dependencies(self):
        """Verifica que todas as dependências do coordinator são importáveis."""
        from price_watchdog.alerts.email_notifier import EmailNotifier
        from price_watchdog.config import settings
        from price_watchdog.coordinator.coordinator import (
            PriceMonitoringCoordinator,
        )
        from price_watchdog.coordinator.cycle_consolidator import (
            CycleConsolidator,
        )
        from price_watchdog.queue.publisher import SQSPublisher
        from price_watchdog.registry.competitor_manager import (
            CompetitorManager,
            seed_initial_competitors,
        )
        from price_watchdog.reports.excel_report import ExcelReportGenerator
        from price_watchdog.scheduler.scheduler import PriceWatchdogScheduler
        from price_watchdog.storage.price_store import PriceStore

        # Verificar que settings tem os campos necessários
        assert hasattr(settings, "monitoring_interval_hours")
        assert hasattr(settings, "recipients_list")
        assert isinstance(settings.monitoring_interval_hours, int)
        assert isinstance(settings.recipients_list, list)

    def test_coordinator_wiring_with_mocks(self):
        """Verifica que o coordinator conecta dependências corretamente."""
        from price_watchdog.alerts.email_notifier import EmailNotifier
        from price_watchdog.coordinator.coordinator import (
            PriceMonitoringCoordinator,
        )
        from price_watchdog.coordinator.cycle_consolidator import (
            CycleConsolidator,
        )
        from price_watchdog.queue.publisher import SQSPublisher
        from price_watchdog.registry.competitor_manager import (
            CompetitorManager,
        )
        from price_watchdog.reports.excel_report import ExcelReportGenerator
        from price_watchdog.scheduler.scheduler import PriceWatchdogScheduler
        from price_watchdog.storage.price_store import PriceStore

        # Instanciar dependências
        publisher = SQSPublisher()
        price_store = PriceStore()
        report_generator = ExcelReportGenerator()
        email_notifier = EmailNotifier()
        competitor_manager = CompetitorManager()

        # Instanciar consolidator com dependências
        consolidator = CycleConsolidator(
            price_store=price_store,
            report_generator=report_generator,
            email_notifier=email_notifier,
        )

        # Instanciar coordinator com dependências
        coordinator = PriceMonitoringCoordinator(
            publisher=publisher,
            consolidator=consolidator,
            price_store=price_store,
            competitor_manager=competitor_manager,
        )

        # Instanciar scheduler com coordinator
        scheduler = PriceWatchdogScheduler(
            coordinator=coordinator,
            interval_hours=12,
        )

        # Verificar que tudo foi conectado
        assert coordinator._publisher is publisher
        assert coordinator._consolidator is consolidator
        assert coordinator._price_store is price_store
        assert coordinator._competitor_manager is competitor_manager
        assert scheduler._coordinator is coordinator
        assert scheduler._interval_hours == 12

    @pytest.mark.asyncio
    async def test_coordinator_main_runs_and_shuts_down(self):
        """Verifica que main() do coordinator inicia e responde a shutdown."""
        from price_watchdog.main_coordinator import main

        with (
            patch(
                "price_watchdog.main_coordinator.SQSPublisher"
            ) as mock_pub,
            patch(
                "price_watchdog.main_coordinator.PriceStore"
            ) as mock_store,
            patch(
                "price_watchdog.main_coordinator.ExcelReportGenerator"
            ) as mock_report,
            patch(
                "price_watchdog.main_coordinator.EmailNotifier"
            ) as mock_notifier,
            patch(
                "price_watchdog.main_coordinator.CompetitorManager"
            ) as mock_cm,
            patch(
                "price_watchdog.main_coordinator.seed_initial_competitors",
                new_callable=AsyncMock,
            ) as mock_seed,
            patch(
                "price_watchdog.main_coordinator.PriceWatchdogScheduler"
            ) as mock_scheduler_cls,
        ):
            mock_scheduler = MagicMock()
            mock_scheduler_cls.return_value = mock_scheduler

            # Simular que o main inicia e depois recebe shutdown
            # Cancelamos a task depois de um breve tempo
            task = asyncio.create_task(main())

            # Dar tempo para inicializar
            await asyncio.sleep(0.1)

            # Cancelar para simular shutdown
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verificar que seed foi chamado
            mock_seed.assert_awaited_once()

            # Verificar que scheduler foi iniciado
            mock_scheduler.start.assert_called_once()


class TestWorkerEntrypoint:
    """Testes de integração do entrypoint do Worker."""

    def test_worker_main_importable(self):
        """Verifica que main_worker é importável sem erros."""
        from price_watchdog.main_worker import main

        assert asyncio.iscoroutinefunction(main)

    def test_worker_imports_all_dependencies(self):
        """Verifica que todas as dependências do worker são importáveis."""
        from price_watchdog.alerts.alert_service import AlertService
        from price_watchdog.alerts.email_notifier import EmailNotifier
        from price_watchdog.comparator.comparator import PriceComparator
        from price_watchdog.models.dataclasses import (
            PriceCheckMessage,
            ScrapeResult,
        )
        from price_watchdog.queue.consumer import SQSConsumer
        from price_watchdog.storage.price_store import PriceStore
        from price_watchdog.storage.screenshot_store import ScreenshotStore
        from price_watchdog.worker.worker import Worker

        # Todos importados sem erro
        assert Worker is not None
        assert SQSConsumer is not None
        assert PriceComparator is not None
        assert PriceStore is not None
        assert ScreenshotStore is not None
        assert AlertService is not None
        assert EmailNotifier is not None

    def test_worker_wiring_with_mocks(self):
        """Verifica que o worker conecta dependências corretamente."""
        from price_watchdog.alerts.alert_service import AlertService
        from price_watchdog.alerts.email_notifier import EmailNotifier
        from price_watchdog.comparator.comparator import PriceComparator
        from price_watchdog.main_worker import StubScraper
        from price_watchdog.queue.consumer import SQSConsumer
        from price_watchdog.storage.price_store import PriceStore
        from price_watchdog.storage.screenshot_store import ScreenshotStore
        from price_watchdog.worker.worker import Worker

        # Instanciar dependências
        consumer = SQSConsumer()
        scraper = StubScraper()
        comparator = PriceComparator()
        price_store = PriceStore()
        screenshot_store = ScreenshotStore()
        alert_service = AlertService()
        email_notifier = EmailNotifier()

        # Instanciar worker com dependências
        worker = Worker(
            consumer=consumer,
            scraper=scraper,
            comparator=comparator,
            price_store=price_store,
            screenshot_store=screenshot_store,
            alert_service=alert_service,
            email_notifier=email_notifier,
        )

        # Verificar que tudo foi conectado
        assert worker._consumer is consumer
        assert worker._scraper is scraper
        assert worker._comparator is comparator
        assert worker._price_store is price_store
        assert worker._screenshot_store is screenshot_store
        assert worker._alert_service is alert_service
        assert worker._email_notifier is email_notifier

    @pytest.mark.asyncio
    async def test_stub_scraper_returns_failed(self):
        """Verifica que StubScraper retorna resultado de falha."""
        from price_watchdog.main_worker import StubScraper
        from price_watchdog.models.dataclasses import PriceCheckMessage

        scraper = StubScraper()
        message = PriceCheckMessage(
            product_config_id="test-id",
            competitor_id="comp-id",
            competitor_name="Test Competitor",
            product_name="Test Product",
            page_url="https://example.com",
            extraction_strategy="css_selector",
            selector_or_pattern=".price",
            our_price=99.90,
            cycle_id="cycle-id",
        )

        result = await scraper.scrape(message)

        assert result.extraction_status == "failed"
        assert result.extracted_price is None
        assert "stub" in result.failure_reason.lower() or "não implementado" in result.failure_reason.lower()

    def test_get_scraper_returns_object_with_scrape_method(self):
        """Verifica que _get_scraper retorna objeto com método scrape."""
        from price_watchdog.main_worker import _get_scraper

        scraper = _get_scraper()
        # Deve retornar algo com método scrape (real ou stub)
        assert hasattr(scraper, "scrape")
        assert callable(scraper.scrape)

    @pytest.mark.asyncio
    async def test_worker_main_runs_and_shuts_down(self):
        """Verifica que main() do worker inicia e responde a shutdown."""
        from price_watchdog.main_worker import main

        with (
            patch(
                "price_watchdog.main_worker.SQSConsumer"
            ) as mock_consumer_cls,
            patch(
                "price_watchdog.main_worker.PriceComparator"
            ) as mock_comp,
            patch(
                "price_watchdog.main_worker.PriceStore"
            ) as mock_store,
            patch(
                "price_watchdog.main_worker.ScreenshotStore"
            ) as mock_ss,
            patch(
                "price_watchdog.main_worker.AlertService"
            ) as mock_alert,
            patch(
                "price_watchdog.main_worker.EmailNotifier"
            ) as mock_notifier,
            patch(
                "price_watchdog.main_worker._get_scraper"
            ) as mock_get_scraper,
            patch(
                "price_watchdog.main_worker.Worker"
            ) as mock_worker_cls,
        ):
            mock_worker = MagicMock()
            # run() é async, deve resolver rapidamente
            mock_worker.run = AsyncMock(
                side_effect=asyncio.CancelledError
            )
            mock_worker_cls.return_value = mock_worker

            mock_get_scraper.return_value = MagicMock()

            task = asyncio.create_task(main())

            # Dar tempo para inicializar
            await asyncio.sleep(0.1)

            # Cancelar task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verificar que Worker foi instanciado com dependências
            mock_worker_cls.assert_called_once()


class TestConfigIntegration:
    """Testes de integração da configuração com os entrypoints."""

    def test_config_has_monitoring_interval_hours(self):
        """Config deve ter monitoring_interval_hours para o scheduler."""
        from price_watchdog.config import settings

        assert hasattr(settings, "monitoring_interval_hours")
        assert settings.monitoring_interval_hours == 12

    def test_config_has_recipients_list(self):
        """Config deve ter recipients_list para envio de emails."""
        from price_watchdog.config import settings

        assert hasattr(settings, "recipients_list")
        assert isinstance(settings.recipients_list, list)

    def test_config_has_alert_thresholds(self):
        """Config deve ter thresholds de alerta."""
        from price_watchdog.config import settings

        assert hasattr(settings, "alert_drop_threshold")
        assert hasattr(settings, "alert_increase_threshold")
        assert settings.alert_drop_threshold == 5.0
        assert settings.alert_increase_threshold == 10.0

    def test_config_has_aws_settings(self):
        """Config deve ter configurações AWS."""
        from price_watchdog.config import settings

        assert hasattr(settings, "sqs_queue_url")
        assert hasattr(settings, "s3_bucket")
        assert hasattr(settings, "ses_from_email")
        assert hasattr(settings, "db_url")
