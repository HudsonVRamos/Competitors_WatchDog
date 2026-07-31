"""Script para atualizar estratégias de extração dos concorrentes.

Atualiza os ProductConfigs com estratégias mais adequadas baseado
nos resultados reais de scraping. Muda Claro TV+ para regex
(CSS selectors genéricos não funcionam) e ajusta os padrões.
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
    """Atualiza estratégias de extração no banco."""
    from price_watchdog.database import get_session
    from price_watchdog.models.entities import ProductConfig

    logger.info("Atualizando estratégias de extração...")

    async with get_session() as session:
        # Buscar TODOS os ProductConfigs
        all_configs_stmt = select(ProductConfig).options(
            selectinload(ProductConfig.competitor)
        )
        all_configs_result = await session.execute(all_configs_stmt)
        all_configs = list(all_configs_result.scalars().all())

        for config in all_configs:
            competitor_name = config.competitor.name if config.competitor else ""

            # Todos usam AI (Claude 4.6) - scraper faz scroll+full_page
            config.extraction_strategy = "ai"
            config.selector_or_pattern = (
                f"Encontre o preço mensal do '{config.product_name}'. "
                "O preço está em formato brasileiro (R$ XX,XX ou R$XX,XX/mês). "
                "Se houver parcelamento (12x R$XX,XX/mês), retorne o valor da parcela mensal."
            )
            logger.info(
                "  %s (%s) -> ai", config.product_name, competitor_name
            )

        logger.info(
            "Todos os %d ProductConfigs atualizados para AI com scroll.",
            len(all_configs),
        )

    logger.info("Atualização concluída.")


if __name__ == "__main__":
    asyncio.run(main())
