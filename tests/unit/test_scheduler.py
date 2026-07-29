"""Testes unitários para PriceWatchdogScheduler.

Valida:
- Inicialização com intervalo padrão e customizado
- start() configura e inicia o scheduler
- stop() encerra o scheduler gracefully
- _run_cycle_wrapper() chama coordinator.run_cycle()
- Tratamento de erros no wrapper não interrompe o scheduler
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from price_watchdog.scheduler.scheduler import PriceWatchdogScheduler


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Cria mock do PriceMonitoringCoordinator."""
    coordinator = MagicMock()
    coordinator.run_cycle = AsyncMock()
    return coordinator


@pytest.fixture
def scheduler(mock_coordinator: MagicMock) -> PriceWatchdogScheduler:
    """Cria instância do scheduler com coordinator mock."""
    return PriceWatchdogScheduler(
        coordinator=mock_coordinator, interval_hours=12
    )


class TestSchedulerInit:
    """Testes de inicialização do PriceWatchdogScheduler."""

    def test_default_interval(
        self, mock_coordinator: MagicMock
    ) -> None:
        """Intervalo padrão deve ser 12 horas."""
        sched = PriceWatchdogScheduler(coordinator=mock_coordinator)
        assert sched._interval_hours == 12

    def test_custom_interval(
        self, mock_coordinator: MagicMock
    ) -> None:
        """Intervalo customizado deve ser respeitado."""
        sched = PriceWatchdogScheduler(
            coordinator=mock_coordinator, interval_hours=6
        )
        assert sched._interval_hours == 6

    def test_coordinator_stored(
        self, mock_coordinator: MagicMock
    ) -> None:
        """Coordinator deve ser armazenado internamente."""
        sched = PriceWatchdogScheduler(coordinator=mock_coordinator)
        assert sched._coordinator is mock_coordinator

    def test_scheduler_created(
        self, mock_coordinator: MagicMock
    ) -> None:
        """AsyncIOScheduler deve ser criado na inicialização."""
        sched = PriceWatchdogScheduler(coordinator=mock_coordinator)
        assert sched._scheduler is not None


class TestSchedulerStart:
    """Testes do método start()."""

    def test_start_adds_job_and_starts(
        self, scheduler: PriceWatchdogScheduler
    ) -> None:
        """start() deve adicionar job e iniciar o scheduler."""
        with patch.object(
            scheduler._scheduler, "add_job"
        ) as mock_add_job, patch.object(
            scheduler._scheduler, "start"
        ) as mock_start:
            scheduler.start()

            mock_add_job.assert_called_once()
            mock_start.assert_called_once()

    def test_start_configures_interval_trigger(
        self, mock_coordinator: MagicMock
    ) -> None:
        """start() deve configurar IntervalTrigger com intervalo correto."""
        sched = PriceWatchdogScheduler(
            coordinator=mock_coordinator, interval_hours=8
        )

        with patch.object(
            sched._scheduler, "add_job"
        ) as mock_add_job, patch.object(sched._scheduler, "start"):
            sched.start()

            call_kwargs = mock_add_job.call_args
            trigger = call_kwargs.kwargs.get(
                "trigger"
            ) or call_kwargs[1].get("trigger")

            # Verificar que o trigger é IntervalTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            assert isinstance(trigger, IntervalTrigger)

    def test_start_uses_correct_job_id(
        self, scheduler: PriceWatchdogScheduler
    ) -> None:
        """start() deve usar ID fixo para o job."""
        with patch.object(
            scheduler._scheduler, "add_job"
        ) as mock_add_job, patch.object(scheduler._scheduler, "start"):
            scheduler.start()

            call_kwargs = mock_add_job.call_args
            job_id = call_kwargs.kwargs.get("id") or call_kwargs[1].get(
                "id"
            )
            assert job_id == "price_watchdog_cycle"

    def test_start_uses_replace_existing(
        self, scheduler: PriceWatchdogScheduler
    ) -> None:
        """start() deve usar replace_existing=True."""
        with patch.object(
            scheduler._scheduler, "add_job"
        ) as mock_add_job, patch.object(scheduler._scheduler, "start"):
            scheduler.start()

            call_kwargs = mock_add_job.call_args
            replace = call_kwargs.kwargs.get(
                "replace_existing"
            ) or call_kwargs[1].get("replace_existing")
            assert replace is True


class TestSchedulerStop:
    """Testes do método stop()."""

    def test_stop_shuts_down_running_scheduler(
        self, scheduler: PriceWatchdogScheduler
    ) -> None:
        """stop() deve encerrar scheduler em execução."""
        # Substituir o scheduler interno por um mock que simula running=True
        mock_internal_scheduler = MagicMock()
        mock_internal_scheduler.running = True
        scheduler._scheduler = mock_internal_scheduler

        scheduler.stop()

        mock_internal_scheduler.shutdown.assert_called_once_with(wait=True)

    def test_stop_does_nothing_if_not_running(
        self, scheduler: PriceWatchdogScheduler
    ) -> None:
        """stop() não deve chamar shutdown se scheduler não está rodando."""
        mock_internal_scheduler = MagicMock()
        mock_internal_scheduler.running = False
        scheduler._scheduler = mock_internal_scheduler

        scheduler.stop()

        mock_internal_scheduler.shutdown.assert_not_called()


class TestRunCycleWrapper:
    """Testes do método _run_cycle_wrapper()."""

    @pytest.mark.asyncio
    async def test_calls_coordinator_run_cycle(
        self,
        scheduler: PriceWatchdogScheduler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Wrapper deve chamar coordinator.run_cycle()."""
        mock_cycle = MagicMock()
        mock_cycle.id = 1
        mock_cycle.status = "running"
        mock_coordinator.run_cycle.return_value = mock_cycle

        await scheduler._run_cycle_wrapper()

        mock_coordinator.run_cycle.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(
        self,
        scheduler: PriceWatchdogScheduler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Wrapper deve capturar exceções sem relançar."""
        mock_coordinator.run_cycle.side_effect = RuntimeError(
            "Erro de conexão"
        )

        # Não deve lançar exceção
        await scheduler._run_cycle_wrapper()

        mock_coordinator.run_cycle.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_cycle_result(
        self,
        scheduler: PriceWatchdogScheduler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Wrapper deve logar resultado do ciclo."""
        mock_cycle = MagicMock()
        mock_cycle.id = 42
        mock_cycle.status = "completed"
        mock_coordinator.run_cycle.return_value = mock_cycle

        with patch(
            "price_watchdog.scheduler.scheduler.logger"
        ) as mock_logger:
            await scheduler._run_cycle_wrapper()

            # Deve ter pelo menos um log info
            assert mock_logger.info.called

    @pytest.mark.asyncio
    async def test_logs_error_on_exception(
        self,
        scheduler: PriceWatchdogScheduler,
        mock_coordinator: MagicMock,
    ) -> None:
        """Wrapper deve logar erro quando exceção ocorre."""
        mock_coordinator.run_cycle.side_effect = ValueError(
            "Falha inesperada"
        )

        with patch(
            "price_watchdog.scheduler.scheduler.logger"
        ) as mock_logger:
            await scheduler._run_cycle_wrapper()

            mock_logger.error.assert_called_once()
