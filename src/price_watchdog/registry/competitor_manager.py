"""CRUD de concorrentes e configurações de produtos monitorados."""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select

from price_watchdog.database import get_session
from price_watchdog.models.dataclasses import ValidationResult
from price_watchdog.models.entities import (
    Competitor,
    PriceRecord,
    ProductConfig,
)

logger = logging.getLogger(__name__)


class CompetitorManager:
    """CRUD de concorrentes e configurações de produtos."""

    async def get_active_configs(self) -> list[ProductConfig]:
        """Retorna todos os ProductConfigs ativos.

        Returns:
            Lista de ProductConfig com is_active=True.
        """
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            stmt = (
                select(ProductConfig)
                .where(ProductConfig.is_active.is_(True))
                .options(selectinload(ProductConfig.competitor))
            )
            result = await session.execute(stmt)
            configs = list(result.scalars().all())
            logger.info(
                "Encontrados %d configs ativos", len(configs)
            )
            return configs

    async def register_competitor(
        self, competitor: Competitor
    ) -> Competitor:
        """Cadastra novo concorrente.

        Args:
            competitor: Instância de Competitor a ser cadastrada.

        Returns:
            O Competitor cadastrado com ID gerado.
        """
        async with get_session() as session:
            session.add(competitor)
            await session.flush()
            logger.info(
                "Concorrente cadastrado: id=%s, name=%s",
                competitor.id,
                competitor.name,
            )
            return competitor

    async def register_product_config(
        self, config: ProductConfig
    ) -> ProductConfig:
        """Cadastra novo produto para monitoramento.

        Args:
            config: Instância de ProductConfig a ser cadastrada.

        Returns:
            O ProductConfig cadastrado com ID gerado.
        """
        async with get_session() as session:
            session.add(config)
            await session.flush()
            logger.info(
                "ProductConfig cadastrado: id=%s, product=%s",
                config.id,
                config.product_name,
            )
            return config

    async def validate_config(
        self, config: ProductConfig
    ) -> ValidationResult:
        """Valida URL acessível e formato do seletor/padrão.

        Verifica:
        - URL no formato http/https válido
        - selector_or_pattern não vazio
        - Para css_selector: formato básico de seletor CSS
        - Para regex: compilação do padrão regex

        Args:
            config: ProductConfig a ser validado.

        Returns:
            ValidationResult indicando se é válido e erros.
        """
        errors: list[str] = []

        # Validar URL
        if not config.page_url:
            errors.append("page_url não pode ser vazio")
        else:
            parsed = urlparse(config.page_url)
            if parsed.scheme not in ("http", "https"):
                errors.append(
                    "page_url deve começar com http:// ou https://"
                )
            if not parsed.netloc:
                errors.append(
                    "page_url deve conter um domínio válido"
                )

        # Validar selector_or_pattern
        if not config.selector_or_pattern:
            errors.append(
                "selector_or_pattern não pode ser vazio"
            )
        else:
            strategy = config.extraction_strategy
            if strategy == "css_selector":
                errors.extend(
                    self._validate_css_selector(
                        config.selector_or_pattern
                    )
                )
            elif strategy == "regex":
                errors.extend(
                    self._validate_regex_pattern(
                        config.selector_or_pattern
                    )
                )
            # Para "ai" não há validação de padrão específico

        is_valid = len(errors) == 0
        if not is_valid:
            logger.warning(
                "Validação falhou para config: %s, erros: %s",
                config.product_name,
                errors,
            )
        return ValidationResult(is_valid=is_valid, errors=errors)

    def _validate_css_selector(
        self, selector: str
    ) -> list[str]:
        """Valida formato básico de seletor CSS.

        Args:
            selector: Seletor CSS a ser validado.

        Returns:
            Lista de erros encontrados (vazia se válido).
        """
        errors: list[str] = []
        css_pattern = re.compile(
            r'^[a-zA-Z#.\[\]:>\s\w\-="\'^~*|,()]+$'
        )
        if not css_pattern.match(selector):
            errors.append(
                "selector_or_pattern não é um seletor CSS válido"
            )
        return errors

    def _validate_regex_pattern(
        self, pattern: str
    ) -> list[str]:
        """Valida se o padrão regex compila corretamente.

        Args:
            pattern: Padrão regex a ser validado.

        Returns:
            Lista de erros encontrados (vazia se válido).
        """
        errors: list[str] = []
        try:
            re.compile(pattern)
        except re.error as e:
            errors.append(
                f"selector_or_pattern não é um regex válido: {e}"
            )
        return errors

    async def update_our_price(
        self, config_id: str, new_price: float
    ) -> None:
        """Atualiza preço de referência sem afetar histórico.

        Atualiza apenas o campo our_price do ProductConfig,
        sem modificar PriceRecords existentes.

        Args:
            config_id: ID do ProductConfig a ser atualizado.
            new_price: Novo preço de referência.
        """
        async with get_session() as session:
            stmt = select(ProductConfig).where(
                ProductConfig.id == config_id
            )
            result = await session.execute(stmt)
            config = result.scalar_one_or_none()
            if config is None:
                logger.warning(
                    "ProductConfig não encontrado: %s", config_id
                )
                return
            config.our_price = new_price
            config.updated_at = datetime.utcnow()
            logger.info(
                "Preço atualizado: config_id=%s, new_price=%.2f",
                config_id,
                new_price,
            )

    async def get_success_rate(
        self, competitor_id: str, days: int = 30
    ) -> float:
        """Calcula taxa de sucesso dos últimos N dias.

        Fórmula: (records com status "success" / total) * 100

        Args:
            competitor_id: ID do concorrente.
            days: Número de dias para considerar (padrão 30).

        Returns:
            Taxa de sucesso em porcentagem (0.0 se sem records).
        """
        async with get_session() as session:
            since = datetime.utcnow() - timedelta(days=days)

            # Total de records no período
            total_stmt = select(
                func.count(PriceRecord.id)
            ).where(
                PriceRecord.competitor_id == competitor_id,
                PriceRecord.extracted_at >= since,
            )
            total_result = await session.execute(total_stmt)
            total = total_result.scalar_one()

            if total == 0:
                logger.info(
                    "Nenhum record para competitor_id=%s "
                    "nos últimos %d dias",
                    competitor_id,
                    days,
                )
                return 0.0

            # Records com sucesso no período
            success_stmt = select(
                func.count(PriceRecord.id)
            ).where(
                PriceRecord.competitor_id == competitor_id,
                PriceRecord.extracted_at >= since,
                PriceRecord.extraction_status == "success",
            )
            success_result = await session.execute(success_stmt)
            success = success_result.scalar_one()

            rate = (success / total) * 100
            logger.info(
                "Taxa de sucesso competitor_id=%s: %.1f%% "
                "(%d/%d nos últimos %d dias)",
                competitor_id,
                rate,
                success,
                total,
                days,
            )
            return rate

    async def seed_initial_competitors(self) -> None:
        """Popula o banco com os concorrentes iniciais do sistema.

        Cria HBO Max Brasil, Claro TV+ e Vivo TV com suas
        respectivas configurações de produtos e estratégias de
        extração. A função é idempotente — verifica se cada
        concorrente já existe antes de criá-lo.

        Estratégias de extração por concorrente:
        - HBO Max Brasil: "ai" (site dinâmico com cards de planos)
        - Claro TV+: "css_selector" (HTML estruturado)
        - Vivo TV: "regex" (preços em texto HTML)

        Requirements: 14.5, 15.1, 15.2, 15.3, 15.4, 15.5
        """
        competitors_data = [
            {
                "name": "HBO Max Brasil",
                "base_url": "https://www.hbomax.com/br/pt",
                "products": [
                    {
                        "product_name": "Plano Básico HBO Max",
                        "page_url": (
                            "https://www.hbomax.com/br/pt"
                        ),
                        "extraction_strategy": "ai",
                        "selector_or_pattern": (
                            "Encontre o preço mensal do plano "
                            "Básico de assinatura do HBO Max "
                            "na página. O preço está em formato "
                            "brasileiro (R$ XX,XX) dentro de um "
                            "card de plano."
                        ),
                        "our_price": 34.90,
                        "currency": "BRL",
                    },
                    {
                        "product_name": "Plano Padrão HBO Max",
                        "page_url": (
                            "https://www.hbomax.com/br/pt"
                        ),
                        "extraction_strategy": "ai",
                        "selector_or_pattern": (
                            "Encontre o preço mensal do plano "
                            "Padrão de assinatura do HBO Max "
                            "na página. O preço está em formato "
                            "brasileiro (R$ XX,XX) dentro de um "
                            "card de plano."
                        ),
                        "our_price": 55.90,
                        "currency": "BRL",
                    },
                ],
            },
            {
                "name": "Claro TV+",
                "base_url": (
                    "https://www.clarotvmais.com.br/home-landing"
                ),
                "products": [
                    {
                        "product_name": (
                            "Pacote Claro TV+ Fácil HD"
                        ),
                        "page_url": (
                            "https://www.clarotvmais.com.br"
                            "/home-landing"
                        ),
                        "extraction_strategy": "css_selector",
                        "selector_or_pattern": (
                            "[data-testid='plan-price'], "
                            ".plan-card .price, "
                            ".offer-price"
                        ),
                        "our_price": 89.90,
                        "currency": "BRL",
                    },
                    {
                        "product_name": (
                            "Combo Claro TV+ Internet"
                        ),
                        "page_url": (
                            "https://www.clarotvmais.com.br"
                            "/home-landing"
                        ),
                        "extraction_strategy": "css_selector",
                        "selector_or_pattern": (
                            "[data-testid='combo-price'], "
                            ".combo-card .price, "
                            ".combo-offer-price"
                        ),
                        "our_price": 159.90,
                        "currency": "BRL",
                    },
                ],
            },
            {
                "name": "Vivo TV",
                "base_url": (
                    "https://vivo.com.br/para-voce/"
                    "produtos-e-servicos/para-casa/tv"
                ),
                "products": [
                    {
                        "product_name": "Vivo TV HD",
                        "page_url": (
                            "https://vivo.com.br/para-voce/"
                            "produtos-e-servicos/para-casa/tv"
                        ),
                        "extraction_strategy": "regex",
                        "selector_or_pattern": (
                            r"R\$\s*(\d{1,3}"
                            r"(?:\.\d{3})*,\d{2})"
                            r"(?:\s*/\s*m[eê]s)?"
                        ),
                        "our_price": 99.90,
                        "currency": "BRL",
                    },
                    {
                        "product_name": "Vivo TV Full HD",
                        "page_url": (
                            "https://vivo.com.br/para-voce/"
                            "produtos-e-servicos/para-casa/tv"
                        ),
                        "extraction_strategy": "regex",
                        "selector_or_pattern": (
                            r"R\$\s*(\d{1,3}"
                            r"(?:\.\d{3})*,\d{2})"
                            r"(?:\s*/\s*m[eê]s)?"
                        ),
                        "our_price": 149.90,
                        "currency": "BRL",
                    },
                ],
            },
        ]

        async with get_session() as session:
            for comp_data in competitors_data:
                # Verificar se já existe (idempotência)
                stmt = select(Competitor).where(
                    Competitor.name == comp_data["name"]
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing is not None:
                    logger.info(
                        "Concorrente '%s' já existe, "
                        "pulando seed.",
                        comp_data["name"],
                    )
                    continue

                # Criar concorrente
                now = datetime.utcnow()
                competitor = Competitor(
                    name=comp_data["name"],
                    base_url=comp_data["base_url"],
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(competitor)
                await session.flush()

                logger.info(
                    "Concorrente criado: %s (id=%s)",
                    competitor.name,
                    competitor.id,
                )

                # Criar configurações de produto
                for prod_data in comp_data["products"]:
                    product_config = ProductConfig(
                        competitor_id=competitor.id,
                        product_name=prod_data["product_name"],
                        page_url=prod_data["page_url"],
                        extraction_strategy=prod_data[
                            "extraction_strategy"
                        ],
                        selector_or_pattern=prod_data[
                            "selector_or_pattern"
                        ],
                        our_price=prod_data["our_price"],
                        currency=prod_data["currency"],
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(product_config)
                    logger.info(
                        "  ProductConfig criado: %s "
                        "(estratégia=%s)",
                        prod_data["product_name"],
                        prod_data["extraction_strategy"],
                    )

        logger.info(
            "Seed de concorrentes iniciais concluído."
        )


async def seed_initial_competitors() -> None:
    """Função de conveniência para executar o seed de concorrentes.

    Cria uma instância de CompetitorManager e executa o seed.
    Uso recomendado na inicialização do sistema.
    """
    manager = CompetitorManager()
    await manager.seed_initial_competitors()
