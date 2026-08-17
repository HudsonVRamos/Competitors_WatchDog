"""Worker principal para processamento de mensagens de extração de preço.

Consome mensagens da fila SQS, executa scraping, compara preços,
persiste resultados e confirma processamento. Implementa degradação
graciosa: falhas individuais não interrompem o loop.

Requirements: 12.1, 12.2, 12.3, 2.4
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

from price_watchdog.alerts.alert_service import AlertService
from price_watchdog.alerts.email_notifier import EmailNotifier
from price_watchdog.comparator.change_detector import ChangeDetector
from price_watchdog.comparator.comparator import PriceComparator
from price_watchdog.config import settings
from price_watchdog.models.dataclasses import (
    AlertThresholds,
    MultiPriceExtractionResult,
    PriceCheckMessage,
    ScrapeResult,
)
from price_watchdog.models.entities import PriceRecord, ProductConfig
from price_watchdog.models.intelligence_entities import (
    CompetitorIntelligenceRecord,
    PackageComposition,
)
from price_watchdog.queue.consumer import SQSConsumer
from price_watchdog.registry.competitor_manager import CompetitorManager
from price_watchdog.scraper.intelligence_extractor import (
    AIIntelligenceExtractor,
)
from price_watchdog.storage.intelligence_store import IntelligenceStore
from price_watchdog.storage.price_store import PriceStore
from price_watchdog.storage.screenshot_store import ScreenshotStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Intervalo de renovação de visibility timeout (segundos)
_VISIBILITY_RENEWAL_INTERVAL = 30

# Intervalo de sleep quando não há mensagens na fila (segundos)
_NO_MESSAGE_SLEEP = 2


class ScraperProtocol(Protocol):
    """Protocolo para o scraper de preços.

    Qualquer objeto com métodos assíncronos scrape(message) e
    scrape_all(message) satisfaz este protocolo.
    """

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Executa scraping de preço para a mensagem fornecida."""
        ...

    async def scrape_all(
        self, message: PriceCheckMessage
    ) -> MultiPriceExtractionResult:
        """Extrai todos os planos/preços da página."""
        ...


class Worker:
    """Worker de processamento de mensagens de extração de preço.

    Implementa o loop principal que:
    1. Recebe mensagens da fila SQS
    2. Renova visibility timeout em background
    3. Executa scraping do preço
    4. Compara preço extraído com preço de referência
    5. Persiste PriceRecord no banco
    6. Confirma processamento (acknowledge)

    Em caso de falha no processamento de uma mensagem individual,
    registra um PriceRecord com status="failed" e continua o loop.

    Attributes:
        _consumer: Consumer SQS para recebimento de mensagens.
        _scraper: Scraper de preços (protocolo).
        _comparator: Comparador de preços.
        _price_store: Store de persistência de records.
        _screenshot_store: Store de screenshots no S3.
        _alert_service: Serviço de avaliação de alertas.
        _running: Flag de controle do loop principal.
    """

    def __init__(
        self,
        consumer: SQSConsumer,
        scraper: ScraperProtocol,
        comparator: PriceComparator,
        price_store: PriceStore,
        screenshot_store: ScreenshotStore,
        alert_service: AlertService,
        email_notifier: EmailNotifier | None = None,
        competitor_manager: CompetitorManager | None = None,
        intelligence_extractor: AIIntelligenceExtractor | None = None,
        intelligence_store: IntelligenceStore | None = None,
        change_detector: ChangeDetector | None = None,
    ) -> None:
        """Inicializa o Worker com suas dependências.

        Args:
            consumer: Consumer SQS para recebimento de mensagens.
            scraper: Objeto com método async scrape(message) -> ScrapeResult.
            comparator: Comparador de preços extraídos vs referência.
            price_store: Store para persistência de PriceRecords.
            screenshot_store: Store para upload de screenshots no S3.
            alert_service: Serviço de avaliação de alertas de preço.
            email_notifier: Notificador por email (opcional).
            competitor_manager: Manager para busca/criação de configs.
            intelligence_extractor: Extrator de inteligência
                competitiva (opcional).
            intelligence_store: Store de persistência de
                inteligência (opcional).
            change_detector: Detector de mudanças em inteligência
                competitiva (opcional).
        """
        self._consumer = consumer
        self._scraper = scraper
        self._comparator = comparator
        self._price_store = price_store
        self._screenshot_store = screenshot_store
        self._alert_service = alert_service
        self._email_notifier = email_notifier
        self._competitor_manager = competitor_manager
        self._intelligence_extractor = intelligence_extractor
        self._intelligence_store = intelligence_store
        self._change_detector = change_detector
        self._running = False

    async def run(self) -> None:
        """Loop principal do worker — executa até ser parado via stop().

        O loop:
        1. Tenta receber uma mensagem da fila SQS
        2. Se não há mensagem, aguarda brevemente e tenta novamente
        3. Se há mensagem, processa via _process_message
        4. Em caso de exceção inesperada no loop, loga e continua
        """
        self._running = True
        logger.info("Worker iniciado. Aguardando mensagens...")

        while self._running:
            try:
                message = await self._consumer.receive_message()

                if message is None:
                    await asyncio.sleep(_NO_MESSAGE_SLEEP)
                    continue

                # Extrair receipt_handle da mensagem
                receipt_handle: str = getattr(
                    message, "_receipt_handle", ""
                )

                if not receipt_handle:
                    logger.error(
                        "Mensagem sem receipt_handle, ignorando: "
                        "product_config_id=%s",
                        message.product_config_id,
                    )
                    continue

                await self._process_message(message, receipt_handle)

            except Exception as exc:
                logger.error(
                    "Erro inesperado no loop principal do worker: %s",
                    exc,
                    exc_info=True,
                )
                # Aguarda brevemente para evitar busy-loop em caso
                # de erros persistentes
                await asyncio.sleep(_NO_MESSAGE_SLEEP)

        logger.info("Worker encerrado.")

    async def _process_message(
        self,
        message: PriceCheckMessage,
        receipt_handle: str,
    ) -> None:
        """Processa uma única mensagem de extração de preço.

        Detecta se é extração multi-plano (ai_all) ou individual,
        e despacha para o handler adequado.

        Args:
            message: Mensagem de preço a ser processada.
            receipt_handle: Handle SQS para renovação/acknowledge.
        """
        if (
            message.multi_extraction
            or message.extraction_strategy == "ai_all"
        ):
            await self._process_multi_message(
                message, receipt_handle
            )
        else:
            await self._process_single_message(
                message, receipt_handle
            )

    async def _process_multi_message(
        self,
        message: PriceCheckMessage,
        receipt_handle: str,
    ) -> None:
        """Processa mensagem de extração multi-plano (ai_all).

        Fluxo:
        1. Inicia renovação de visibility timeout em background
        2. Executa scrape_all() para extrair todos os planos
        3. Upload de screenshot ao S3
        4. Para cada plano encontrado, busca ProductConfig
           correspondente (fuzzy match por nome) ou cria novo
        5. Persiste PriceRecord para cada plano
        6. Acknowledge da mensagem

        Args:
            message: Mensagem com dados do concorrente.
            receipt_handle: Handle SQS para renovação/acknowledge.
        """
        logger.info(
            "Processando mensagem multi-plano: "
            "competitor=%s, url=%s",
            message.competitor_name,
            message.page_url,
        )

        renewal_task = asyncio.create_task(
            self._renew_visibility_loop(receipt_handle)
        )

        try:
            # Executar scraping multi-plano
            multi_result = await self._scraper.scrape_all(message)

            # Upload de screenshot se disponível
            screenshot_s3_key: str | None = None
            if multi_result.screenshot_bytes:
                screenshot_s3_key = (
                    await self._screenshot_store.upload(
                        screenshot_bytes=(
                            multi_result.screenshot_bytes
                        ),
                        cycle_id=message.cycle_id,
                        competitor_id=message.competitor_id,
                    )
                )

            if not multi_result.success or not multi_result.plans:
                # Registrar falha geral
                logger.warning(
                    "Extração multi-plano falhou para '%s': %s",
                    message.competitor_name,
                    multi_result.failure_reason,
                )
                failed_record = PriceRecord(
                    product_config_id=message.product_config_id,
                    competitor_id=message.competitor_id,
                    cycle_id=message.cycle_id,
                    extracted_price=None,
                    our_price=message.our_price,
                    price_difference=None,
                    price_difference_pct=None,
                    extraction_status="failed",
                    failure_reason=multi_result.failure_reason,
                    screenshot_s3_key=screenshot_s3_key,
                )
                await self._price_store.save_record(failed_record)
                await self._consumer.acknowledge(receipt_handle)
                return

            # Buscar configs existentes do concorrente
            existing_configs = await self._get_competitor_configs(
                message.competitor_id
            )

            # Para cada plano encontrado, criar PriceRecord
            for plan in multi_result.plans:
                plan_name = plan["name"]
                plan_price = plan.get("price")

                # Pular planos sem preço extraído
                if plan_price is None:
                    logger.warning(
                        "Plano '%s' sem preço - pulando",
                        plan_name,
                    )
                    continue

                # Buscar config correspondente (fuzzy match)
                matched_config = self._match_config(
                    plan_name, existing_configs
                )

                if matched_config:
                    config_id = str(matched_config.id)
                    our_price = matched_config.our_price
                else:
                    # Criar novo ProductConfig dinamicamente
                    new_config = await self._create_config(
                        competitor_id=message.competitor_id,
                        plan_name=plan_name,
                        page_url=message.page_url,
                        price=plan_price,
                    )
                    config_id = str(new_config.id)
                    our_price = plan_price  # Sem referência ainda

                # Comparar preços (pular se our_price indisponível)
                if our_price and our_price > 0 and plan_price:
                    comparison = self._comparator.compare(
                        plan_price, our_price
                    )
                    price_diff = comparison.absolute_difference
                    price_diff_pct = comparison.percentage_difference
                else:
                    price_diff = None
                    price_diff_pct = None

                record = PriceRecord(
                    product_config_id=config_id,
                    competitor_id=message.competitor_id,
                    cycle_id=message.cycle_id,
                    extracted_price=plan_price,
                    our_price=our_price or plan_price,
                    price_difference=price_diff,
                    price_difference_pct=price_diff_pct,
                    extraction_status="success",
                    failure_reason=None,
                    screenshot_s3_key=screenshot_s3_key,
                )
                await self._price_store.save_record(record)

                logger.info(
                    "PriceRecord multi: plano='%s', "
                    "preço=R$ %.2f, config_id=%s",
                    plan_name,
                    plan_price,
                    config_id,
                )

                # Avaliar alertas
                await self._evaluate_alerts(
                    extracted_price=plan_price,
                    product_config_id=config_id,
                    our_price=our_price,
                )

            # Persistir composição de pacotes extraídos (sempre,
            # mesmo se intelligence_enabled — os dados de composição
            # do fluxo de preços são mais completos para os planos)
            await self._save_package_compositions(
                plans=multi_result.plans,
                competitor_id=message.competitor_id,
                cycle_id=message.cycle_id,
                competitor_name=message.competitor_name,
            )

            # Extração de inteligência competitiva (após preços)
            if message.intelligence_enabled:
                await self._process_intelligence(
                    screenshot_bytes=multi_result.screenshot_bytes,
                    competitor_id=message.competitor_id,
                    competitor_name=message.competitor_name,
                    cycle_id=message.cycle_id,
                    home_url=message.intelligence_home_url,
                )

            # Acknowledge
            await self._consumer.acknowledge(receipt_handle)

            logger.info(
                "Mensagem multi-plano acknowledged: "
                "competitor=%s, %d planos processados",
                message.competitor_name,
                len(multi_result.plans),
            )

        except Exception as exc:
            logger.error(
                "Falha ao processar mensagem multi: "
                "competitor=%s, erro=%s",
                message.competitor_name,
                exc,
                exc_info=True,
            )

            failed_record = PriceRecord(
                product_config_id=message.product_config_id,
                competitor_id=message.competitor_id,
                cycle_id=message.cycle_id,
                extracted_price=None,
                our_price=message.our_price,
                price_difference=None,
                price_difference_pct=None,
                extraction_status="failed",
                failure_reason=str(exc),
                screenshot_s3_key=None,
            )

            try:
                await self._price_store.save_record(failed_record)
            except Exception as persist_exc:
                logger.error(
                    "Falha ao persistir PriceRecord de erro "
                    "multi: competitor=%s, erro=%s",
                    message.competitor_name,
                    persist_exc,
                    exc_info=True,
                )

        finally:
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass

    async def _get_competitor_configs(
        self, competitor_id: str
    ) -> list[ProductConfig]:
        """Busca todos os ProductConfigs de um concorrente.

        Args:
            competitor_id: ID do concorrente.

        Returns:
            Lista de ProductConfigs do concorrente.
        """
        from sqlalchemy import select as sa_select

        from price_watchdog.database import get_session

        async with get_session() as session:
            stmt = (
                sa_select(ProductConfig)
                .where(
                    ProductConfig.competitor_id == competitor_id
                )
                .where(ProductConfig.is_active.is_(True))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    def _match_config(
        self,
        plan_name: str,
        configs: list[ProductConfig],
    ) -> ProductConfig | None:
        """Match fuzzy de nome do plano com ProductConfigs existentes.

        Compara normalizado (lowercase, sem espaços extras).
        Retorna o primeiro match onde o nome do config está contido
        no nome do plano ou vice-versa.

        Args:
            plan_name: Nome do plano extraído pelo AI.
            configs: Lista de ProductConfigs existentes.

        Returns:
            ProductConfig correspondente ou None.
        """
        plan_lower = plan_name.lower().strip()

        # Match exato primeiro
        for config in configs:
            if config.product_name.lower().strip() == plan_lower:
                return config

        # Match parcial (contém)
        for config in configs:
            config_lower = config.product_name.lower().strip()
            if (
                config_lower in plan_lower
                or plan_lower in config_lower
            ):
                return config

        return None

    async def _create_config(
        self,
        competitor_id: str,
        plan_name: str,
        page_url: str,
        price: float,
    ) -> ProductConfig:
        """Cria um novo ProductConfig para plano descoberto.

        Args:
            competitor_id: ID do concorrente.
            plan_name: Nome do plano descoberto.
            page_url: URL da página do concorrente.
            price: Preço extraído (usado como our_price inicial).

        Returns:
            ProductConfig criado e persistido.
        """
        from price_watchdog.database import get_session

        new_config = ProductConfig(
            competitor_id=competitor_id,
            product_name=plan_name,
            page_url=page_url,
            extraction_strategy="ai_all",
            selector_or_pattern="",
            our_price=price,
            is_active=True,
        )

        async with get_session() as session:
            session.add(new_config)
            await session.flush()
            logger.info(
                "Novo ProductConfig criado: "
                "plan='%s', config_id=%s",
                plan_name,
                new_config.id,
            )

        return new_config

    async def _process_single_message(
        self,
        message: PriceCheckMessage,
        receipt_handle: str,
    ) -> None:
        """Processa uma única mensagem de extração individual.

        Fluxo original:
        1. Inicia renovação de visibility timeout em background
        2. Executa scraping
        3. Se sucesso: compara preços e calcula diferenças
        4. Se screenshot capturado: faz upload ao S3
        5. Persiste PriceRecord
        6. Acknowledge da mensagem

        Args:
            message: Mensagem de preço a ser processada.
            receipt_handle: Handle SQS para renovação/acknowledge.
        """
        logger.info(
            "Processando mensagem: product_config_id=%s, "
            "competitor=%s, produto=%s",
            message.product_config_id,
            message.competitor_name,
            message.product_name,
        )

        # Iniciar renovação de visibility em background
        renewal_task = asyncio.create_task(
            self._renew_visibility_loop(receipt_handle)
        )

        try:
            # Executar scraping
            scrape_result = await self._scraper.scrape(message)

            # Variáveis para o PriceRecord
            extracted_price: float | None = None
            price_difference: float | None = None
            price_difference_pct: float | None = None
            screenshot_s3_key: str | None = None

            # Determinar extraction_status baseado no health check
            # Se score é GEO_MISMATCH ou GEO_REDIRECT, forçar "skipped"
            extraction_status = scrape_result.extraction_status
            if scrape_result.health_check_score in (
                "GEO_MISMATCH",
                "GEO_REDIRECT",
            ):
                extraction_status = "skipped"

            if extraction_status == "success":
                extracted_price = scrape_result.extracted_price

                # Comparar preços
                if extracted_price is not None:
                    comparison = self._comparator.compare(
                        extracted_price, message.our_price
                    )
                    price_difference = comparison.absolute_difference
                    price_difference_pct = (
                        comparison.percentage_difference
                    )

                    # Avaliar alertas de variação de preço
                    await self._evaluate_alerts(
                        extracted_price=extracted_price,
                        product_config_id=message.product_config_id,
                        our_price=message.our_price,
                    )

            # Upload de screenshot se disponível
            if scrape_result.screenshot_bytes:
                screenshot_s3_key = (
                    await self._screenshot_store.upload(
                        screenshot_bytes=scrape_result.screenshot_bytes,
                        cycle_id=message.cycle_id,
                        competitor_id=message.competitor_id,
                    )
                )

            # Criar e persistir PriceRecord com health check fields
            record = PriceRecord(
                product_config_id=message.product_config_id,
                competitor_id=message.competitor_id,
                cycle_id=message.cycle_id,
                extracted_price=extracted_price,
                our_price=message.our_price,
                price_difference=price_difference,
                price_difference_pct=price_difference_pct,
                extraction_status=extraction_status,
                failure_reason=scrape_result.failure_reason,
                screenshot_s3_key=(
                    screenshot_s3_key
                    or scrape_result.screenshot_s3_key
                ),
                health_check_score=(
                    scrape_result.health_check_score
                ),
                health_check_reason=(
                    scrape_result.health_check_reason
                ),
                diagnostic_s3_key=(
                    scrape_result.diagnostic_s3_key
                ),
            )

            await self._price_store.save_record(record)

            logger.info(
                "PriceRecord persistido: product_config_id=%s, "
                "status=%s, preço=%s, health_check=%s",
                message.product_config_id,
                extraction_status,
                extracted_price,
                scrape_result.health_check_score,
            )

            # Acknowledge — mensagem processada com sucesso
            await self._consumer.acknowledge(receipt_handle)

            logger.info(
                "Mensagem acknowledged: product_config_id=%s",
                message.product_config_id,
            )

        except Exception as exc:
            # Degradação graciosa: registrar falha e continuar
            logger.error(
                "Falha ao processar mensagem: "
                "product_config_id=%s, erro=%s",
                message.product_config_id,
                exc,
                exc_info=True,
            )

            # Registrar PriceRecord com status "failed"
            failed_record = PriceRecord(
                product_config_id=message.product_config_id,
                competitor_id=message.competitor_id,
                cycle_id=message.cycle_id,
                extracted_price=None,
                our_price=message.our_price,
                price_difference=None,
                price_difference_pct=None,
                extraction_status="failed",
                failure_reason=str(exc),
                screenshot_s3_key=None,
            )

            try:
                await self._price_store.save_record(failed_record)
                logger.info(
                    "PriceRecord de falha persistido: "
                    "product_config_id=%s",
                    message.product_config_id,
                )
            except Exception as persist_exc:
                logger.error(
                    "Falha ao persistir PriceRecord de erro: "
                    "product_config_id=%s, erro=%s",
                    message.product_config_id,
                    persist_exc,
                    exc_info=True,
                )

        finally:
            # Cancelar renovação de visibility
            renewal_task.cancel()
            try:
                await renewal_task
            except asyncio.CancelledError:
                pass

    async def _renew_visibility_loop(
        self, receipt_handle: str
    ) -> None:
        """Renova visibility timeout periodicamente em background.

        Executa a cada _VISIBILITY_RENEWAL_INTERVAL segundos até
        ser cancelada. Erros de renovação são logados mas não
        interrompem o processamento.

        Args:
            receipt_handle: Handle SQS da mensagem a renovar.
        """
        while True:
            await asyncio.sleep(_VISIBILITY_RENEWAL_INTERVAL)
            try:
                await self._consumer.renew_visibility(receipt_handle)
                logger.debug(
                    "Visibility renovada para receipt_handle=%s...",
                    receipt_handle[:20],
                )
            except Exception as exc:
                logger.warning(
                    "Falha ao renovar visibility: %s",
                    exc,
                )

    async def _save_package_compositions(
        self,
        plans: list[dict],
        competitor_id: str,
        cycle_id: str,
        competitor_name: str,
    ) -> None:
        """Persiste composição de pacotes extraídos na tabela package_compositions.

        Cria um CompetitorIntelligenceRecord (se não existir para este ciclo/competitor)
        e salva cada plano como PackageComposition vinculado a ele.

        Os dados de composição vêm do AI extractor no fluxo de preços multi-plano,
        garantindo que canais, fibra, streamings, telas e promo sejam persistidos.

        Args:
            plans: Lista de dicts com dados de cada plano extraído.
            competitor_id: ID do concorrente.
            cycle_id: ID do ciclo de monitoramento.
            competitor_name: Nome do concorrente (para logging).
        """
        try:
            if self._intelligence_store is None:
                logger.debug(
                    "IntelligenceStore não disponível, "
                    "ignorando persistência de composição: "
                    "competitor=%s",
                    competitor_name,
                )
                return

            if not plans:
                return

            # Criar record de inteligência para vincular os pacotes
            record = CompetitorIntelligenceRecord(
                cycle_id=cycle_id,
                competitor_id=competitor_id,
                extraction_status="success",
                failure_reason=None,
            )

            # Criar PackageComposition para cada plano com dados de composição
            for plan in plans:
                streamings = plan.get("streamings", []) or []
                pkg = PackageComposition(
                    plan_name=plan["name"],
                    default_price=plan.get("price"),
                    promotional_price=plan.get("promo_price"),
                    promotional_period_months=plan.get("promo_months"),
                    linear_channels=plan.get("channels"),
                    simultaneous_screens=plan.get("screens"),
                    has_fiber=plan.get("has_fiber"),
                    fiber_speed_mbps=plan.get("fiber_speed_mbps"),
                    has_mobile_internet=plan.get("has_mobile"),
                    mobile_speed_mbps=plan.get("mobile_speed_mbps"),
                    bundled_streaming_1=(
                        streamings[0] if len(streamings) > 0 else None
                    ),
                    bundled_streaming_2=(
                        streamings[1] if len(streamings) > 1 else None
                    ),
                    bundled_streaming_3=(
                        streamings[2] if len(streamings) > 2 else None
                    ),
                    bundled_streaming_4=(
                        streamings[3] if len(streamings) > 3 else None
                    ),
                    bundled_streaming_5=(
                        streamings[4] if len(streamings) > 4 else None
                    ),
                    bundled_streaming_6=(
                        streamings[5] if len(streamings) > 5 else None
                    ),
                    bundled_streaming_7=(
                        streamings[6] if len(streamings) > 6 else None
                    ),
                )
                record.packages.append(pkg)

            await self._intelligence_store.save_record(record)

            logger.info(
                "Composição de pacotes persistida: "
                "competitor=%s, cycle_id=%s, pacotes=%d",
                competitor_name,
                cycle_id,
                len(plans),
            )

        except Exception as exc:
            # Isolamento: falha na persistência de composição
            # não interrompe o fluxo de preços
            logger.error(
                "Falha ao persistir composição de pacotes "
                "(isolada): competitor=%s, cycle_id=%s, erro=%s",
                competitor_name,
                cycle_id,
                exc,
                exc_info=True,
            )

    async def _process_intelligence(
        self,
        screenshot_bytes: bytes | None,
        competitor_id: str,
        competitor_name: str,
        cycle_id: str,
        home_url: str | None,
    ) -> None:
        """Processa extração de inteligência competitiva para um concorrente.

        Reutiliza o screenshot já capturado para extração de preços,
        sem realizar nova navegação ao site. Toda a lógica é envolvida
        em try/except isolado — qualquer exceção é logada sem impactar
        o fluxo de preços.

        Se o screenshot não estiver disponível, registra um record com
        status "failed" e razão "screenshot_unavailable".

        Args:
            screenshot_bytes: Screenshot full-page já capturado
                (pode ser None).
            competitor_id: ID do concorrente.
            competitor_name: Nome do concorrente (para logging/extração).
            cycle_id: ID do ciclo de monitoramento.
            home_url: URL da home para extração de comunicação comercial.

        Requirements: 4.1, 4.2, 4.3, 4.5, 10.1
        """
        try:
            # Verificar se dependências de inteligência estão disponíveis
            if (
                self._intelligence_extractor is None
                or self._intelligence_store is None
            ):
                logger.warning(
                    "Inteligência habilitada mas extractor/store "
                    "não configurados para competitor=%s",
                    competitor_name,
                )
                return

            # Se screenshot indisponível: atualizar record existente ou criar falha
            if not screenshot_bytes:
                logger.warning(
                    "Screenshot indisponível para extração de "
                    "inteligência: competitor=%s, cycle_id=%s",
                    competitor_name,
                    cycle_id,
                )
                existing = await self._get_existing_intelligence_record(
                    cycle_id=cycle_id,
                    competitor_id=competitor_id,
                )
                if not existing:
                    failed_record = CompetitorIntelligenceRecord(
                        cycle_id=cycle_id,
                        competitor_id=competitor_id,
                        extraction_status="failed",
                        failure_reason="screenshot_unavailable",
                    )
                    await self._intelligence_store.save_record(
                        failed_record
                    )
                return

            # Chamar extrator de inteligência com screenshot existente
            logger.info(
                "Iniciando extração de inteligência: "
                "competitor=%s, cycle_id=%s",
                competitor_name,
                cycle_id,
            )

            result = await self._intelligence_extractor.extract(
                screenshot_bytes=screenshot_bytes,
                competitor_name=competitor_name,
                home_url=home_url,
            )

            # Criar record de inteligência a partir do resultado
            # OU buscar record existente (já criado pelo _save_package_compositions)
            existing_record = await self._get_existing_intelligence_record(
                cycle_id=cycle_id,
                competitor_id=competitor_id,
            )

            if existing_record:
                record = existing_record
                record.extraction_status = result.status
                record.failure_reason = result.failure_reason
                record.extraction_latency_ms = result.latency_ms
                record.retry_count = result.retry_count
            else:
                record = CompetitorIntelligenceRecord(
                    cycle_id=cycle_id,
                    competitor_id=competitor_id,
                    extraction_status=result.status,
                    failure_reason=result.failure_reason,
                    extraction_latency_ms=result.latency_ms,
                    retry_count=result.retry_count,
                )

            # Preencher dados de comunicação comercial se disponível
            if result.commercial_communication is not None:
                comm = result.commercial_communication
                if comm.keywords_status == "identified":
                    record.commercial_keywords = (
                        comm.commercial_keywords
                    )
                if comm.banner_status == "identified":
                    record.home_banner_description = (
                        comm.home_banner_description
                    )
                record.commercial_positioning_summary = (
                    comm.commercial_positioning_summary
                    if comm.commercial_positioning_summary
                    else None
                )

            # Criar PackageComposition entities a partir do resultado
            # (apenas se não existirem pacotes já vinculados ao record)
            if not record.packages:
                for pkg_data in result.package_compositions:
                    streamings = pkg_data.bundled_streamings or []
                    pkg_entity = PackageComposition(
                        plan_name=pkg_data.plan_name,
                        default_price=pkg_data.default_price,
                        promotional_price=pkg_data.promotional_price,
                        promotional_period_months=(
                            pkg_data.promotional_period_months
                        ),
                        linear_channels=pkg_data.linear_channels,
                        simultaneous_screens=(
                            pkg_data.simultaneous_screens
                        ),
                        has_fiber=pkg_data.has_fiber,
                        fiber_speed_mbps=pkg_data.fiber_speed_mbps,
                        has_mobile_internet=(
                            pkg_data.has_mobile_internet
                        ),
                        mobile_speed_mbps=pkg_data.mobile_speed_mbps,
                        bundled_streaming_1=(
                            streamings[0] if len(streamings) > 0
                            else None
                        ),
                        bundled_streaming_2=(
                            streamings[1] if len(streamings) > 1
                            else None
                        ),
                        bundled_streaming_3=(
                            streamings[2] if len(streamings) > 2
                            else None
                        ),
                        bundled_streaming_4=(
                            streamings[3] if len(streamings) > 3
                            else None
                        ),
                        bundled_streaming_5=(
                            streamings[4] if len(streamings) > 4
                            else None
                        ),
                        bundled_streaming_6=(
                            streamings[5] if len(streamings) > 5
                            else None
                        ),
                        bundled_streaming_7=(
                            streamings[6] if len(streamings) > 6
                            else None
                        ),
                    )
                    record.packages.append(pkg_entity)

            # Persistir via IntelligenceStore (insert ou update)
            if existing_record:
                await self._update_intelligence_record(record)
            else:
                await self._intelligence_store.save_record(record)

            logger.info(
                "Inteligência extraída e persistida: "
                "competitor=%s, status=%s, pacotes=%d, "
                "latência=%.0fms",
                competitor_name,
                result.status,
                len(result.package_compositions),
                result.latency_ms,
            )

            # Detectar mudanças se extração não falhou
            if result.status != "failed":
                await self._detect_and_notify_changes(
                    record=record,
                    competitor_id=competitor_id,
                    competitor_name=competitor_name,
                )

        except Exception as exc:
            # Isolamento total: qualquer exceção é logada
            # sem propagar para o fluxo de preços
            logger.error(
                "Falha na extração de inteligência "
                "(isolada, sem impacto em preços): "
                "competitor=%s, cycle_id=%s, erro=%s",
                competitor_name,
                cycle_id,
                exc,
                exc_info=True,
            )

    async def _get_existing_intelligence_record(
        self,
        cycle_id: str,
        competitor_id: str,
    ) -> CompetitorIntelligenceRecord | None:
        """Busca record de inteligência existente para ciclo/competitor.

        Args:
            cycle_id: ID do ciclo.
            competitor_id: ID do concorrente.

        Returns:
            Record existente ou None.
        """
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload

        from price_watchdog.database import get_session

        try:
            async with get_session() as session:
                stmt = (
                    sa_select(CompetitorIntelligenceRecord)
                    .options(
                        selectinload(
                            CompetitorIntelligenceRecord.packages
                        )
                    )
                    .where(
                        CompetitorIntelligenceRecord.cycle_id == cycle_id,
                        CompetitorIntelligenceRecord.competitor_id
                        == competitor_id,
                    )
                )
                result = await session.execute(stmt)
                record = result.scalar_one_or_none()
                if record:
                    # Expunge para usar fora da session
                    session.expunge(record)
                return record
        except Exception:
            return None

    async def _update_intelligence_record(
        self,
        record: CompetitorIntelligenceRecord,
    ) -> None:
        """Atualiza um CompetitorIntelligenceRecord existente.

        Faz merge do record com a sessão para persistir alterações.

        Args:
            record: Record já modificado a ser atualizado.
        """
        from price_watchdog.database import get_session

        try:
            async with get_session() as session:
                await session.merge(record)
            logger.info(
                "IntelligenceRecord atualizado: competitor_id=%s, "
                "cycle_id=%s",
                record.competitor_id,
                record.cycle_id,
            )
        except Exception as exc:
            logger.error(
                "Falha ao atualizar IntelligenceRecord: "
                "competitor_id=%s, cycle_id=%s, erro=%s",
                record.competitor_id,
                record.cycle_id,
                exc,
                exc_info=True,
            )

    async def _detect_and_notify_changes(
        self,
        record: CompetitorIntelligenceRecord,
        competitor_id: str,
        competitor_name: str,
    ) -> None:
        """Detecta mudanças em inteligência e envia alertas por email.

        Chama o ChangeDetector para comparar o registro atual com
        o anterior e, para cada alerta gerado, envia notificação
        via EmailNotifier. Falhas não interrompem o fluxo.

        Args:
            record: Registro de inteligência recém-persistido.
            competitor_id: ID do concorrente.
            competitor_name: Nome do concorrente para os alertas.
        """
        try:
            if self._change_detector is None:
                return

            alerts = await self._change_detector.detect_changes(
                current=record,
                competitor_id=competitor_id,
            )

            if not alerts:
                return

            # Preencher competitor_name nos alertas se não preenchido
            for alert in alerts:
                if not alert.competitor_name:
                    alert.competitor_name = competitor_name

            # Enviar notificação por email para cada alerta
            if self._email_notifier is not None:
                recipients = settings.recipients_list
                for alert in alerts:
                    try:
                        await (
                            self._email_notifier
                            .send_intelligence_alert(
                                alert=alert,
                                recipients=recipients,
                            )
                        )
                    except Exception as notify_exc:
                        logger.error(
                            "Falha ao enviar alerta de "
                            "inteligência: tipo=%s, "
                            "competitor=%s, erro=%s",
                            alert.alert_type,
                            competitor_name,
                            notify_exc,
                            exc_info=True,
                        )

            logger.info(
                "Detecção de mudanças concluída: "
                "competitor=%s, %d alertas enviados",
                competitor_name,
                len(alerts),
            )

        except Exception as exc:
            # Isolamento: erros na detecção não impactam nada
            logger.error(
                "Falha na detecção de mudanças "
                "(isolada): competitor=%s, erro=%s",
                competitor_name,
                exc,
                exc_info=True,
            )

    async def _evaluate_alerts(
        self,
        extracted_price: float,
        product_config_id: str,
        our_price: float,
    ) -> None:
        """Avalia se variação de preço justifica alerta e notifica.

        Busca preço anterior do concorrente, avalia thresholds e,
        se alerta for gerado, envia notificação por email.
        Falhas não interrompem o fluxo principal de processamento.

        Args:
            extracted_price: Preço atual extraído do concorrente.
            product_config_id: ID da configuração do produto.
            our_price: Nosso preço de referência.
        """
        try:
            previous_price = (
                await self._price_store.get_previous_price(
                    product_config_id
                )
            )

            alert = self._alert_service.evaluate(
                current_price=extracted_price,
                previous_price=previous_price,
                our_price=our_price,
                thresholds=AlertThresholds(),
            )

            if alert is not None:
                logger.warning(
                    "Alerta gerado: tipo=%s, variação=%.2f%%, "
                    "threshold=%.2f%%, product_config_id=%s",
                    alert.alert_type,
                    alert.actual_difference_pct,
                    alert.threshold_pct,
                    product_config_id,
                )

                # Enviar notificação por email se notifier disponível
                if self._email_notifier is not None:
                    try:
                        await self._email_notifier.send_alert(
                            alert=alert,
                            recipients=[],  # Configurável via settings
                        )
                    except Exception as notify_exc:
                        logger.error(
                            "Falha ao enviar notificação de alerta: "
                            "product_config_id=%s, erro=%s",
                            product_config_id,
                            notify_exc,
                            exc_info=True,
                        )

        except Exception as exc:
            logger.error(
                "Falha na avaliação de alertas: "
                "product_config_id=%s, erro=%s",
                product_config_id,
                exc,
                exc_info=True,
            )

    def stop(self) -> None:
        """Sinaliza o worker para encerrar o loop principal.

        O worker finalizará o processamento da mensagem atual
        (se houver) antes de parar.
        """
        logger.info("Sinal de parada recebido. Encerrando worker...")
        self._running = False
