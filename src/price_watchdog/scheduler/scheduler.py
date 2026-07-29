"""Agendador de ciclos de monitoramento de preços.

Utiliza APScheduler (AsyncIOScheduler) para disparar ciclos
periódicos de monitoramento via PriceMonitoringCoordinator.

Requirements: 1.1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from price_watchdog.coordinator.coordinator import (
        PriceMonitoringCoordinator,
    )

logger = logging.getLogger(__name__)


class PriceWatchdogScheduler:
    """Agendamento de ciclos via APScheduler.

    Configura e gerencia um AsyncIOScheduler que dispara
    o método run_cycle() do coordinator no intervalo configurado.

    Attributes:
        _coordinator: Instância do PriceMonitoringCoordinator.
        _interval_hours: Intervalo em horas entre ciclos.
        _scheduler: Instância do AsyncIOScheduler.
    """

    def __init__(
        self,
        coordinator: PriceMonitoringCoordinator,
        interval_hours: int = 12,
    ) -> None:
        """Inicializa o scheduler com o coordinator e intervalo.

        Args:
            coordinator: Orquestrador de ciclos de monitoramento.
            interval_hours: Intervalo em horas entre execuções (padrão 12h).
        """
        self._coordinator = coordinator
        self._interval_hours = interval_hours
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Inicia scheduler com intervalo configurado.

        Adiciona o job com IntervalTrigger e execução imediata
        na primeira vez (next_run_time=None faz disparar imediatamente
        ao usar misfire_grace_time).
        """
        self._scheduler.add_job(
            self._run_cycle_wrapper,
            trigger=IntervalTrigger(hours=self._interval_hours),
            id="price_watchdog_cycle",
            name="Ciclo de monitoramento de preços",
            replace_existing=True,
        )

        self._scheduler.start()

        logger.info(
            "Scheduler iniciado com intervalo de %dh",
            self._interval_hours,
        )

    def stop(self) -> None:
        """Para scheduler gracefully.

        Encerra o scheduler aguardando jobs em execução
        finalizarem antes de parar completamente.
        """
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler parado com sucesso")
        else:
            logger.warning(
                "Tentativa de parar scheduler que não está em execução"
            )

    async def _run_cycle_wrapper(self) -> None:
        """Wrapper para executar run_cycle com tratamento de erro.

        Captura exceções para que falhas em um ciclo não
        interrompam o agendamento dos próximos ciclos.
        """
        logger.info("Iniciando ciclo de monitoramento agendado")
        try:
            cycle = await self._coordinator.run_cycle()
            logger.info(
                "Ciclo agendado concluído: id=%s, status=%s",
                cycle.id,
                cycle.status,
            )
        except Exception as e:
            logger.error(
                "Erro inesperado durante ciclo agendado: %s",
                str(e),
                exc_info=True,
            )
