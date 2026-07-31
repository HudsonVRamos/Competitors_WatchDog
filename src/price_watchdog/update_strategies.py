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

            if "HBO Max" in competitor_name:
                # HBO Max: preços no formato "12x R$XX,XX/mês"
                # Regex captura o valor após "12x R$"
                config.extraction_strategy = "regex"
                config.selector_or_pattern = (
                    r"12x\s*R\$\s*(\d[\d.]*,\d{2})"
                )
                logger.info(
                    "  %s -> regex (12x R$XX,XX)", config.product_name
                )
            else:
                # Claro e Vivo: usar regex (funciona perfeitamente)
                config.extraction_strategy = "regex"
                config.selector_or_pattern = (
                    r"R\$\s*(\d[\d.]*,\d{2})"
                )
                logger.info(
                    "  %s -> regex", config.product_name
                )

        logger.info(
            "Estratégias atualizadas: HBO Max=ai, Claro/Vivo=regex"
        )

    logger.info("Atualização concluída.")


if __name__ == "__main__":
    asyncio.run(main())
