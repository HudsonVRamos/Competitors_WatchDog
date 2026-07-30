"""Script para executar um ciclo único de monitoramento.

Útil para testes manuais e debugging. Executa run_cycle()
uma vez e encerra.
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Executa um ciclo único de monitoramento."""
    from price_watchdog.alerts.email_notifier import EmailNotifier
    from price_watchdog.coordinator.coordinator import PriceMonitoringCoordinator
    from price_watchdog.coordinator.cycle_consolidator import CycleConsolidator
    from price_watchdog.queue.publisher import SQSPublisher
    from price_watchdog.registry.competitor_manager import CompetitorManager
    from price_watchdog.reports.excel_report import ExcelReportGenerator
    from price_watchdog.storage.price_store import PriceStore

    logger.info("Executando ciclo único de monitoramento...")

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

    cycle = await coordinator.run_cycle()
    logger.info(
        "Ciclo criado: id=%s, status=%s, total_products=%d",
        cycle.id,
        cycle.status,
        cycle.total_products,
    )


if __name__ == "__main__":
    asyncio.run(main())
