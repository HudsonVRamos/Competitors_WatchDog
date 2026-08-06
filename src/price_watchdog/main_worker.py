"""Entrypoint do serviço Worker do Price Watchdog.

Inicializa todas as dependências do Worker (SQSConsumer, PriceScraper,
PriceComparator, PriceStore, ScreenshotStore, AlertService, EmailNotifier),
cria a instância do Worker e executa o loop principal.

Configuração de graceful shutdown via SIGTERM/SIGINT para
encerramento limpo no ECS Fargate.

Requirements: 13.1
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING

from price_watchdog.alerts.alert_service import AlertService
from price_watchdog.alerts.email_notifier import EmailNotifier
from price_watchdog.comparator.change_detector import ChangeDetector
from price_watchdog.comparator.comparator import PriceComparator
from price_watchdog.models.dataclasses import PriceCheckMessage, ScrapeResult
from price_watchdog.queue.consumer import SQSConsumer
from price_watchdog.storage.intelligence_store import IntelligenceStore
from price_watchdog.storage.price_store import PriceStore
from price_watchdog.storage.screenshot_store import ScreenshotStore
from price_watchdog.worker.worker import Worker

if TYPE_CHECKING:
    pass

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


class StubScraper:
    """Scraper stub para uso enquanto o PriceScraper não está implementado.

    Retorna sempre um ScrapeResult com status "failed" e razão indicando
    que o scraper real ainda não foi integrado. Será substituído pelo
    PriceScraper real quando disponível.
    """

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Retorna resultado de falha indicando scraper não implementado.

        Args:
            message: Mensagem de extração de preço recebida.

        Returns:
            ScrapeResult com status "failed".
        """
        logger.warning(
            "StubScraper em uso — PriceScraper não implementado. "
            "product_config_id=%s",
            message.product_config_id,
        )
        return ScrapeResult(
            extraction_status="failed",
            extracted_price=None,
            screenshot_bytes=None,
            screenshot_s3_key=None,
            failure_reason="PriceScraper não implementado (stub)",
        )


def _get_scraper():
    """Retorna o scraper disponível (real ou stub).

    Tenta importar o PriceScraper real. Se não estiver
    disponível, retorna o StubScraper.

    Returns:
        Instância de PriceScraper ou StubScraper.
    """
    try:
        from price_watchdog.scraper.scraper import PriceScraper

        logger.info("PriceScraper real carregado com sucesso.")
        return PriceScraper()
    except (ImportError, ModuleNotFoundError):
        logger.warning(
            "PriceScraper não disponível. Usando StubScraper."
        )
        return StubScraper()


async def main() -> None:
    """Função principal assíncrona do Worker.

    Inicializa dependências, cria o Worker e executa o loop
    principal até receber sinal de shutdown.
    """
    logger.info("Iniciando Price Watchdog Worker...")

    # Inicializar dependências
    consumer = SQSConsumer()
    scraper = _get_scraper()
    comparator = PriceComparator()
    price_store = PriceStore()
    screenshot_store = ScreenshotStore()
    alert_service = AlertService()
    email_notifier = EmailNotifier()
    intelligence_store = IntelligenceStore()
    change_detector = ChangeDetector(
        intelligence_store=intelligence_store,
    )

    worker = Worker(
        consumer=consumer,
        scraper=scraper,
        comparator=comparator,
        price_store=price_store,
        screenshot_store=screenshot_store,
        alert_service=alert_service,
        email_notifier=email_notifier,
        intelligence_store=intelligence_store,
        change_detector=change_detector,
    )

    # Configurar graceful shutdown
    def _handle_shutdown(signum: int, frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info(
            "Sinal %s recebido. Iniciando shutdown graceful...",
            sig_name,
        )
        worker.stop()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    # Iniciar loop do worker
    logger.info("Worker em execução. Aguardando mensagens...")
    await worker.run()

    logger.info("Price Watchdog Worker encerrado com sucesso.")


if __name__ == "__main__":
    asyncio.run(main())
