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
from price_watchdog.comparator.comparator import PriceComparator
from price_watchdog.models.dataclasses import (
    AlertThresholds,
    MultiPriceExtractionResult,
    PriceCheckMessage,
    ScrapeResult,
)
from price_watchdog.models.entities import PriceRecord, ProductConfig
from price_watchdog.queue.consumer import SQSConsumer
from price_watchdog.registry.competitor_manager import CompetitorManager
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
        """
        self._consumer = consumer
        self._scraper = scraper
        self._comparator = comparator
        self._price_store = price_store
        self._screenshot_store = screenshot_store
        self._alert_service = alert_service
        self._email_notifier = email_notifier
        self._competitor_manager = competitor_manager
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
                plan_price = plan["price"]

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

                # Comparar preços
                comparison = self._comparator.compare(
                    plan_price, our_price
                )

                record = PriceRecord(
                    product_config_id=config_id,
                    competitor_id=message.competitor_id,
                    cycle_id=message.cycle_id,
                    extracted_price=plan_price,
                    our_price=our_price,
                    price_difference=(
                        comparison.absolute_difference
                    ),
                    price_difference_pct=(
                        comparison.percentage_difference
                    ),
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

            if scrape_result.extraction_status == "success":
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

            # Criar e persistir PriceRecord
            record = PriceRecord(
                product_config_id=message.product_config_id,
                competitor_id=message.competitor_id,
                cycle_id=message.cycle_id,
                extracted_price=extracted_price,
                our_price=message.our_price,
                price_difference=price_difference,
                price_difference_pct=price_difference_pct,
                extraction_status=scrape_result.extraction_status,
                failure_reason=scrape_result.failure_reason,
                screenshot_s3_key=(
                    screenshot_s3_key
                    or scrape_result.screenshot_s3_key
                ),
            )

            await self._price_store.save_record(record)

            logger.info(
                "PriceRecord persistido: product_config_id=%s, "
                "status=%s, preço=%s",
                message.product_config_id,
                scrape_result.extraction_status,
                extracted_price,
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
