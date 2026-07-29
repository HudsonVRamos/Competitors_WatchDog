"""Persistência de PriceRecords no Aurora PostgreSQL."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from price_watchdog.database import get_session
from price_watchdog.models.entities import PriceRecord

logger = logging.getLogger(__name__)


class PriceStore:
    """Persistência de PriceRecords no Aurora PostgreSQL."""

    async def save_record(self, record: PriceRecord) -> None:
        """Persiste um PriceRecord no banco de dados.

        Args:
            record: Instância de PriceRecord a ser persistida.
        """
        async with get_session() as session:
            session.add(record)
            logger.info(
                "PriceRecord salvo: product_config_id=%s, cycle_id=%s, status=%s",
                record.product_config_id,
                record.cycle_id,
                record.extraction_status,
            )

    async def get_cycle_records(self, cycle_id: str) -> list[PriceRecord]:
        """Busca todos os PriceRecords de um ciclo.

        Args:
            cycle_id: ID do ciclo de monitoramento.

        Returns:
            Lista de PriceRecords associados ao ciclo.
        """
        async with get_session() as session:
            stmt = (
                select(PriceRecord)
                .where(PriceRecord.cycle_id == cycle_id)
                .order_by(PriceRecord.extracted_at)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            logger.info(
                "Encontrados %d records para cycle_id=%s",
                len(records),
                cycle_id,
            )
            return records

    async def get_previous_price(self, product_config_id: str) -> float | None:
        """Busca último preço extraído com sucesso para um produto.

        Retorna o preço mais recente onde extraction_status == 'success'.

        Args:
            product_config_id: ID da configuração do produto.

        Returns:
            O último preço extraído com sucesso, ou None se não houver histórico.
        """
        async with get_session() as session:
            stmt = (
                select(PriceRecord.extracted_price)
                .where(
                    PriceRecord.product_config_id == product_config_id,
                    PriceRecord.extraction_status == "success",
                )
                .order_by(PriceRecord.extracted_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            price = result.scalar_one_or_none()
            if price is not None:
                logger.info(
                    "Preço anterior encontrado para product_config_id=%s: %.2f",
                    product_config_id,
                    price,
                )
            else:
                logger.info(
                    "Nenhum preço anterior encontrado para product_config_id=%s",
                    product_config_id,
                )
            return price
