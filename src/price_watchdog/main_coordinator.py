"""Entrypoint do serviço Coordinator do Price Watchdog.

Inicializa todas as dependências do Coordinator (SQSPublisher,
PriceStore, ExcelReportGenerator, EmailNotifier, CycleConsolidator,
CompetitorManager, PriceMonitoringCoordinator), cria o scheduler
e executa o seed de concorrentes iniciais na primeira execução.

Configuração de graceful shutdown via SIGTERM/SIGINT para
encerramento limpo no ECS Fargate.

Requirements: 13.1
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

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

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Função principal assíncrona do Coordinator.

    Inicializa dependências, executa seed de concorrentes,
    inicia o scheduler e aguarda sinal de shutdown.
    """
    logger.info("Iniciando Price Watchdog Coordinator...")

    # Inicializar dependências
    publisher = SQSPublisher()
    price_store = PriceStore()
    report_generator = ExcelReportGenerator()
    email_notifier = EmailNotifier()
    competitor_manager = CompetitorManager()

    consolidator = CycleConsolidator(
        price_store=price_store,
        report_generator=report_generator,
        email_notifier=email_notifier,
    )

    coordinator = PriceMonitoringCoordinator(
        publisher=publisher,
        consolidator=consolidator,
        price_store=price_store,
        competitor_manager=competitor_manager,
    )

    scheduler = PriceWatchdogScheduler(
        coordinator=coordinator,
        interval_hours=settings.monitoring_interval_hours,
    )

    # Seed de concorrentes iniciais
    logger.info("Executando seed de concorrentes iniciais...")
    try:
        await seed_initial_competitors()
        logger.info("Seed de concorrentes concluído.")
    except Exception:
        logger.error(
            "Falha no seed de concorrentes iniciais.",
            exc_info=True,
        )

    # Iniciar scheduler
    scheduler.start()
    logger.info(
        "Scheduler iniciado com intervalo de %dh.",
        settings.monitoring_interval_hours,
    )

    # Configurar graceful shutdown
    shutdown_event = asyncio.Event()

    def _handle_shutdown(signum: int, frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info(
            "Sinal %s recebido. Iniciando shutdown graceful...",
            sig_name,
        )
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    # Aguardar sinal de shutdown
    logger.info("Coordinator em execução. Aguardando sinal de parada...")
    await shutdown_event.wait()

    # Encerrar scheduler
    logger.info("Parando scheduler...")
    scheduler.stop()
    logger.info("Price Watchdog Coordinator encerrado com sucesso.")


if __name__ == "__main__":
    asyncio.run(main())
