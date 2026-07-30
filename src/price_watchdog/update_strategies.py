"""Script para atualizar estratégias de extração dos concorrentes.

Atualiza os ProductConfigs com estratégias mais adequadas baseado
nos resultados reais de scraping. Muda Claro TV+ para regex
(CSS selectors genéricos não funcionam) e ajusta os padrões.
"""

import asyncio
import logging
import sys

from sqlalchemy import select, update

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
    from price_watchdog.models.entities import Competitor, ProductConfig

    logger.info("Atualizando estratégias de extração...")

    async with get_session() as session:
        # Buscar Claro TV+
        stmt = select(Competitor).where(Competitor.name == "Claro TV+")
        result = await session.execute(stmt)
        claro = result.scalar_one_or_none()

        if claro:
            configs_stmt = select(ProductConfig).where(
                ProductConfig.competitor_id == claro.id
            )
            configs_result = await session.execute(configs_stmt)
            configs = list(configs_result.scalars().all())

            for config in configs:
                config.extraction_strategy = "regex"
                # Regex mais flexível: aceita R$ com ou sem espaço, 
                # com &nbsp; ou espaço normal, preços de 2-3 dígitos
                config.selector_or_pattern = (
                    r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})"
                )
                logger.info(
                    "  Atualizado: %s -> regex (flexível)", config.product_name
                )

            logger.info("Claro TV+ atualizada.")
        else:
            logger.warning("Claro TV+ não encontrada no banco.")

        # Buscar HBO Max Brasil
        stmt = select(Competitor).where(Competitor.name == "HBO Max Brasil")
        result = await session.execute(stmt)
        hbo = result.scalar_one_or_none()

        if hbo:
            configs_stmt = select(ProductConfig).where(
                ProductConfig.competitor_id == hbo.id
            )
            configs_result = await session.execute(configs_stmt)
            configs = list(configs_result.scalars().all())

            for config in configs:
                config.extraction_strategy = "regex"
                # HBO Max tem preços no formato R$XX,XX/mês
                config.selector_or_pattern = (
                    r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})"
                )
                logger.info(
                    "  Atualizado: %s -> regex", config.product_name
                )

            logger.info("HBO Max Brasil atualizada para regex.")
        else:
            logger.warning("HBO Max Brasil não encontrada no banco.")

    logger.info("Atualização concluída.")


if __name__ == "__main__":
    asyncio.run(main())
