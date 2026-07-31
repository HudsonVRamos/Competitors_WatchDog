"""Script para atualizar estratégias de extração dos concorrentes.

Atualiza os ProductConfigs para usar estratégia "ai_all" que extrai
TODOS os planos de uma página de concorrente em uma única chamada
ao Claude, em vez de buscar 1 produto por vez.
"""

import asyncio
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Atualiza estratégias de extração no banco para ai_all."""
    from price_watchdog.database import get_session
    from price_watchdog.models.entities import ProductConfig

    logger.info("Atualizando estratégias para ai_all...")

    async with get_session() as session:
        # Atualizar URL da Claro TV+
        from price_watchdog.models.entities import Competitor

        stmt_claro = select(Competitor).where(
            Competitor.name == "Claro TV+"
        )
        result_claro = await session.execute(stmt_claro)
        claro = result_claro.scalar_one_or_none()

        if claro:
            # Atualizar base_url e page_url dos configs
            claro.base_url = "https://www.claro.com.br/claro-tv-mais/box"

            configs_stmt = select(ProductConfig).where(
                ProductConfig.competitor_id == claro.id
            )
            configs_result = await session.execute(configs_stmt)
            configs = list(configs_result.scalars().all())

            for config in configs:
                config.page_url = (
                    "https://www.claro.com.br/claro-tv-mais/box"
                )
                config.extraction_strategy = "ai_all"
                config.selector_or_pattern = ""
                logger.info(
                    "  Claro: %s -> URL atualizada", config.product_name
                )

            logger.info("Claro TV+ URL atualizada para claro.com.br/claro-tv-mais/box")

        # Buscar TODOS os ProductConfigs e setar ai_all
        all_configs_stmt = select(ProductConfig).options(
            selectinload(ProductConfig.competitor)
        )
        all_configs_result = await session.execute(all_configs_stmt)
        all_configs = list(all_configs_result.scalars().all())

        for config in all_configs:
            competitor_name = (
                config.competitor.name
                if config.competitor
                else ""
            )

            # Todos usam ai_all - extração multi-plano
            config.extraction_strategy = "ai_all"
            config.selector_or_pattern = ""
            logger.info(
                "  %s (%s) -> ai_all",
                config.product_name,
                competitor_name,
            )

        logger.info(
            "Todos os %d ProductConfigs atualizados para ai_all.",
            len(all_configs),
        )

    logger.info("Atualização concluída.")


if __name__ == "__main__":
    asyncio.run(main())
