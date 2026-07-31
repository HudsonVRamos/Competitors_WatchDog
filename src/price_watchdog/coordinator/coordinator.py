"""Orquestrador principal de ciclos de monitoramento de preços.

O PriceMonitoringCoordinator é responsável por iniciar ciclos,
buscar configurações ativas, publicar tarefas na fila SQS e
tratar falhas durante o processo de publicação.

Requirements: 1.1, 1.2, 1.5
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from price_watchdog.database import get_session
from price_watchdog.models.dataclasses import PriceCheckMessage
from price_watchdog.models.entities import PriceCycle
from price_watchdog.queue.publisher import SQSPublisher
from price_watchdog.registry.competitor_manager import CompetitorManager
from price_watchdog.storage.price_store import PriceStore

if TYPE_CHECKING:
    from price_watchdog.coordinator.cycle_consolidator import (
        CycleConsolidator,
    )

logger = logging.getLogger(__name__)


class PriceMonitoringCoordinator:
    """Orquestrador principal de ciclos de monitoramento de preços.

    Responsável por:
    - Criar um novo PriceCycle a cada execução
    - Buscar configurações ativas de produtos
    - Publicar mensagens SQS para processamento pelos workers
    - Tratar falhas de publicação marcando o ciclo como "failed"

    Attributes:
        _publisher: Instância de SQSPublisher para envio de mensagens.
        _consolidator: Instância de CycleConsolidator para consolidação.
        _price_store: Instância de PriceStore para persistência.
        _competitor_manager: Instância de CompetitorManager para configs.
    """

    def __init__(
        self,
        publisher: SQSPublisher,
        consolidator: CycleConsolidator,
        price_store: PriceStore,
        competitor_manager: CompetitorManager,
    ) -> None:
        """Inicializa o coordinator com suas dependências.

        Args:
            publisher: Publisher SQS para envio de mensagens em batch.
            consolidator: Consolidador de ciclos (forward reference).
            price_store: Store para persistência de records.
            competitor_manager: Manager para busca de configs ativos.
        """
        self._publisher = publisher
        self._consolidator = consolidator
        self._price_store = price_store
        self._competitor_manager = competitor_manager

    async def run_cycle(self) -> PriceCycle:
        """Inicia e gerencia um ciclo completo de monitoramento.

        Fluxo:
        1. Cria novo PriceCycle com status="running"
        2. Persiste o ciclo no banco de dados
        3. Busca todos os ProductConfigs ativos
        4. Atualiza total_products no ciclo
        5. Publica tarefas na fila SQS
        6. Em caso de falha, marca ciclo como "failed"

        Returns:
            O PriceCycle criado (com status "running" ou "failed").
        """
        cycle = PriceCycle(
            started_at=datetime.utcnow(),
            status="running",
            total_products=0,
            products_succeeded=0,
            products_failed=0,
            alerts_triggered=0,
        )

        async with get_session() as session:
            session.add(cycle)
            await session.flush()
            cycle_id = cycle.id

        logger.info(
            "Novo ciclo de monitoramento iniciado: id=%s",
            cycle_id,
        )

        try:
            # Buscar configurações ativas
            configs = (
                await self._competitor_manager.get_active_configs()
            )

            logger.info(
                "Configs ativos encontrados: %d", len(configs)
            )

            # Atualizar total_products no ciclo
            async with get_session() as session:
                from sqlalchemy import select

                stmt = select(PriceCycle).where(
                    PriceCycle.id == cycle_id
                )
                result = await session.execute(stmt)
                cycle = result.scalar_one()
                cycle.total_products = len(configs)

            # Publicar tarefas na fila
            published = await self._publish_tasks(cycle, configs)

            logger.info(
                "Ciclo %s: %d tarefas publicadas com sucesso",
                cycle_id,
                published,
            )

        except Exception as e:
            logger.error(
                "Falha durante publicação no ciclo %s: %s",
                cycle_id,
                str(e),
                exc_info=True,
            )

            # Marcar ciclo como failed
            async with get_session() as session:
                from sqlalchemy import select

                stmt = select(PriceCycle).where(
                    PriceCycle.id == cycle_id
                )
                result = await session.execute(stmt)
                cycle = result.scalar_one()
                cycle.status = "failed"
                cycle.ended_at = datetime.utcnow()

            logger.info(
                "Ciclo %s marcado como 'failed'", cycle_id
            )

        return cycle

    async def _publish_tasks(
        self,
        cycle: PriceCycle,
        configs: list,
    ) -> int:
        """Publica mensagens SQS agrupadas por concorrente.

        Para configs com estratégia "ai_all", agrupa por competitor_id
        e envia 1 mensagem por concorrente. Para outras estratégias,
        envia 1 mensagem por ProductConfig (comportamento original).

        Args:
            cycle: O PriceCycle corrente.
            configs: Lista de ProductConfig ativos.

        Returns:
            Quantidade total de mensagens publicadas com sucesso.
        """
        if not configs:
            logger.info(
                "Nenhum config ativo para publicar no ciclo %s",
                cycle.id,
            )
            return 0

        messages: list[PriceCheckMessage] = []

        # Agrupar configs "ai_all" por competitor_id
        ai_all_by_competitor: dict[str, list] = {}
        individual_configs: list = []

        for config in configs:
            if config.extraction_strategy == "ai_all":
                comp_id = str(config.competitor_id)
                if comp_id not in ai_all_by_competitor:
                    ai_all_by_competitor[comp_id] = []
                ai_all_by_competitor[comp_id].append(config)
            else:
                individual_configs.append(config)

        # 1 mensagem por concorrente para ai_all
        for comp_id, comp_configs in ai_all_by_competitor.items():
            first_config = comp_configs[0]
            message = PriceCheckMessage(
                product_config_id=str(first_config.id),
                competitor_id=comp_id,
                competitor_name=(
                    first_config.competitor.name
                    if first_config.competitor
                    else ""
                ),
                product_name="",  # Todos os planos
                page_url=first_config.page_url,
                extraction_strategy="ai_all",
                selector_or_pattern="",
                our_price=first_config.our_price,
                cycle_id=str(cycle.id),
                multi_extraction=True,
            )
            messages.append(message)

        logger.info(
            "Agrupados %d concorrentes para extração multi-plano",
            len(ai_all_by_competitor),
        )

        # 1 mensagem por config para estratégias individuais
        for config in individual_configs:
            message = PriceCheckMessage(
                product_config_id=str(config.id),
                competitor_id=str(config.competitor_id),
                competitor_name=(
                    config.competitor.name
                    if config.competitor
                    else ""
                ),
                product_name=config.product_name,
                page_url=config.page_url,
                extraction_strategy=config.extraction_strategy,
                selector_or_pattern=config.selector_or_pattern,
                our_price=config.our_price,
                cycle_id=str(cycle.id),
                multi_extraction=False,
            )
            messages.append(message)

        logger.info(
            "Publicando %d mensagens para ciclo %s "
            "(%d multi-plano, %d individuais)",
            len(messages),
            cycle.id,
            len(ai_all_by_competitor),
            len(individual_configs),
        )

        total_sent = await self._publisher.publish_all(
            messages, batch_size=10
        )

        return total_sent
