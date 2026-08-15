"""PriceScraper — coordena navegação, screenshot e extração de preços.

Usa Playwright com Chromium headless para:
1. Injetar cookies de geolocalização (quando configurado)
2. Navegar até a URL com retry automático
3. Aguardar página pronta com waits inteligentes (sem sleeps fixos)
4. Capturar screenshots em etapas críticas
5. Validar conteúdo (idioma/moeda/região)
6. Interagir com componentes customizados (se necessário)
7. Scroll incremental para forçar lazy-loading (até 8000px)
8. Capturar full_page screenshot e resize para Bedrock
9. Executar estratégia de extração
10. Calcular Health Check Score

Requirements: 1.1, 1.4, 2.1, 3.1, 3.4, 4.1, 5.1, 7.1, 11.2
"""

from __future__ import annotations

import logging
import os
import time
from io import BytesIO

from playwright.async_api import async_playwright, Page

from price_watchdog.models.dataclasses import (
    MultiPriceExtractionResult,
    PriceCheckMessage,
    ScrapeResult,
)
from price_watchdog.scraper.extractors import (
    AIExtractor,
    BaseExtractor,
    CSSSelectorExtractor,
    RegexExtractor,
)

# Scraping Resilience modules
from scraping_resilience.cloud_browser import (
    BrowserStrategy,
    CloudBrowserConfig,
    CloudBrowserManager,
    get_browser_strategy,
)
from scraping_resilience.component_interactor import CustomComponentInteractor
from scraping_resilience.content_validator import ContentValidator
from scraping_resilience.cookie_injector import GeolocationCookieInjector
from scraping_resilience.diagnostics_collector import DiagnosticsCollector
from scraping_resilience.health_check_scorer import HealthCheckScorer
from scraping_resilience.intelligent_wait import IntelligentWaitManager
from scraping_resilience.retry_engine import RetryEngine
from scraping_resilience.step_screenshotter import StepScreenshotter
from scraping_resilience.structured_logger import (
    ScrapeExecutionLog,
    ScrapeSuccessLog,
    StructuredLogger,
)

# Competitor-specific flows
from scraping_resilience.competitor_flows.giga_fibra import GigaFibraFlow
from scraping_resilience.competitor_flows.globoplay import GloboplayFlow
from scraping_resilience.competitor_flows.vivo_tv import VivoTVFlow

logger = logging.getLogger(__name__)

# Timeout de navegação (60 segundos)
_NAVIGATION_TIMEOUT_MS = 60_000

# Limite de altura do scroll (8000px)
_MAX_SCROLL_HEIGHT = 8000

# Viewport
_VIEWPORT_WIDTH = 1920
_VIEWPORT_HEIGHT = 720

# Limites do Bedrock para imagens
_MAX_IMAGE_DIMENSION = 8000
_MAX_IMAGE_SIZE_BYTES = 4_500_000

# Seletores críticos por concorrente (para IntelligentWaitManager)
_CRITICAL_SELECTORS: dict[str, list[str]] = {
    "vivo": ["[class*='plan']", "[class*='card']", "[class*='offer']"],
    "giga": ["[class*='card']", "[class*='plan']", "[class*='plano']"],
    "netflix": ["[class*='plan']", "[class*='price']"],
    "paramount": ["[class*='plan']", "[class*='price']"],
    "sky": ["[class*='card']", "[class*='plan']", "[class*='price']", "[class*='combo']"],
    "globoplay": ["[class*='offer']", "[class*='plan']", "[class*='price']", "[class*='card']"],
}


def _get_site_key(url: str) -> str | None:
    """Retorna a chave do site com base na URL para lookup de configs."""
    if "vivo.com.br" in url:
        return "vivo"
    if "gigamaisfibra.com.br" in url:
        return "giga"
    if "netflix.com" in url:
        return "netflix"
    if "paramountplus.com" in url:
        return "paramount"
    if "sky.com.br" in url:
        return "sky"
    if "globoplay.globo.com" in url:
        return "globoplay"
    return None


class PriceScraper:
    """Navega páginas e coordena extração de preços com resiliência.

    Integra módulos de scraping resilience:
    - IntelligentWaitManager: esperas baseadas em condição
    - RetryEngine: retry com backoff exponencial
    - GeolocationCookieInjector: cookies de localização pré-navegação
    - ContentValidator: validação de idioma/moeda/região
    - CustomComponentInteractor: interação com componentes não-nativos
    - StepScreenshotter: screenshots sequenciais
    - DiagnosticsCollector: artefatos diagnósticos em erro
    - HealthCheckScorer: classificação de saúde da execução

    Cria um browser novo para cada request (evita acúmulo de memória).
    Usa scroll incremental para carregar lazy content antes do screenshot.
    """

    def __init__(self) -> None:
        """Inicializa o PriceScraper com módulos de resiliência."""
        self._wait_manager = IntelligentWaitManager()
        self._retry_engine = RetryEngine()
        self._cookie_injector = GeolocationCookieInjector()
        self._content_validator = ContentValidator()
        self._component_interactor = CustomComponentInteractor()
        self._health_check_scorer = HealthCheckScorer()
        self._structured_logger = StructuredLogger()
        self._cloud_browser_config = CloudBrowserConfig.from_env()

    def _should_use_cloud_browser(self, url: str) -> bool:
        """Verifica se deve usar Cloud Browser para esta URL.

        Usa a feature flag CLOUD_BROWSER_ENABLED + checagem de domínio.

        Args:
            url: URL do site a ser scrapeado.

        Returns:
            True se deve usar cloud browser.
        """
        # Verificar se cloud browser está habilitado e configurado
        if not self._cloud_browser_config.is_configured:
            return False

        # Verificar feature flag
        cloud_enabled = os.environ.get(
            "CLOUD_BROWSER_ENABLED", "false"
        ).lower() in ("true", "1", "yes")
        if not cloud_enabled:
            return False

        # Verificar se o domínio requer cloud browser
        strategy = get_browser_strategy(url)
        return strategy == BrowserStrategy.CLOUD

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Executa navegação resiliente, screenshot e extração.

        Fluxo refatorado (conforme diagrama de sequência do design):
        1. Abre browser com viewport 1920x720
        2. Injeta cookies de geolocalização (se configurado)
        3. Navega até URL com retry automático
        4. Aguarda página pronta com IntelligentWaitManager
        5. Captura screenshot após carregamento
        6. Valida conteúdo (idioma/moeda/região)
        7. Interage com componentes se necessário (tabs, dropdowns)
        8. Scroll incremental para lazy-loading
        9. Captura screenshot antes de extração
        10. Executa estratégia de extração
        11. Calcula Health Check Score

        Args:
            message: Mensagem com dados do produto a ser scrapeado.

        Returns:
            ScrapeResult com preço extraído ou razão de falha.
        """
        logger.info(
            "Iniciando scraping: produto='%s', url='%s', estratégia='%s'",
            message.product_name,
            message.page_url,
            message.extraction_strategy,
        )

        start_time = time.perf_counter()
        screenshot_bytes: bytes | None = None
        playwright_instance = None
        browser = None
        page: Page | None = None
        network_error_occurred = False

        # Instanciar screenshotter e diagnostics para esta execução
        s3_bucket = os.environ.get(
            "S3_BUCKET", "price-watchdog-screenshots-761018874615"
        )
        screenshotter = StepScreenshotter(
            competitor_id=message.competitor_id,
            cycle_id=message.cycle_id,
            bucket=s3_bucket,
        )
        diagnostics = DiagnosticsCollector(bucket=s3_bucket)

        try:
            # 1. Abrir browser com viewport
            playwright_instance = await async_playwright().start()
            browser = await playwright_instance.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            logger.info("Browser Chromium inicializado.")

            context = await browser.new_context(
                viewport={"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                geolocation={"latitude": -23.5505, "longitude": -46.6333},
                permissions=["geolocation"],
                extra_http_headers={
                    "Accept-Language": "pt-BR,pt;q=0.9",
                },
            )
            page = await context.new_page()

            # 2. Injetar cookies de geolocalização (ANTES da navegação)
            site_config = self._get_site_config(message.page_url)
            if site_config:
                injection_result = await self._cookie_injector.inject_cookies(
                    context, site_config
                )
                logger.info(
                    "Cookies injetados: %d cookie(s)",
                    injection_result.cookies_count,
                )

            # 3. Navegar com retry automático
            nav_result = await self._retry_engine.execute(
                self._navigate_page, "navigation", page, message.page_url
            )

            if not nav_result.success:
                # Classificar como network error se retry esgotou
                network_error_occurred = True
                failure_reason = (
                    f"Navegação falhou após {nav_result.attempts} tentativas: "
                    f"{nav_result.errors[-1] if nav_result.errors else 'erro desconhecido'}"
                )
                logger.error(failure_reason)

                # Calcular health check score
                score, reason, _ = self._health_check_scorer.score(
                    validation_result=None,
                    extraction_success=False,
                    network_error=network_error_occurred,
                )

                return ScrapeResult(
                    extraction_status="failed",
                    failure_reason=failure_reason,
                )

            # Verificar status HTTP
            response = nav_result.result
            if response and response.status >= 400:
                logger.error(
                    "HTTP %d para '%s'", response.status, message.page_url
                )
                return ScrapeResult(
                    extraction_status="failed",
                    failure_reason=f"HTTP {response.status}",
                )

            logger.info("Página carregada: %s", message.page_url)

            # 4. Aguardar página pronta com waits inteligentes
            site_key = _get_site_key(message.page_url)
            critical_selectors = _CRITICAL_SELECTORS.get(site_key or "", None)
            wait_result = await self._wait_manager.wait_for_page_ready(
                page, critical_selectors=critical_selectors
            )
            logger.info(
                "Página pronta: estratégia='%s', tempo=%dms",
                wait_result.strategy_used,
                wait_result.elapsed_ms,
            )

            # 5. Screenshot após carregamento inicial
            await screenshotter.capture(page, "after_load")

            # 6. Validar conteúdo (idioma/moeda/região) para sites com risco geo
            validation_result = None
            if site_key in ("netflix", "paramount"):
                expected_url_pattern = "/br/" if site_key == "paramount" else None
                validation_result = await self._content_validator.validate(
                    page,
                    expected_language="pt",
                    expected_currency="BRL",
                    expected_url_pattern=expected_url_pattern,
                )

                # Se GEO_MISMATCH ou GEO_REDIRECT, skip extração
                if not validation_result.is_valid:
                    score, reason, extraction_skipped = self._health_check_scorer.score(
                        validation_result=validation_result,
                        extraction_success=False,
                        network_error=False,
                    )

                    # Capturar diagnóstico
                    await diagnostics.capture_diagnostic(
                        page,
                        reason or "geo_validation_failed",
                        message.competitor_id,
                        message.cycle_id,
                    )
                    await screenshotter.capture(page, "geo_validation_failed")

                    logger.warning(
                        "Extração skipped: score=%s, razão=%s",
                        score.value, reason,
                    )

                    return ScrapeResult(
                        extraction_status="skipped",
                        failure_reason=reason,
                    )

            # 7. Interação específica por concorrente
            if "vivo.com.br" in message.page_url:
                await self._fill_vivo_cep(page)
                # Usar VivoTVFlow para navegação de tabs
                vivo_flow = VivoTVFlow(self._wait_manager, screenshotter)
                await vivo_flow.navigate_tabs(page)

            if "gigamaisfibra.com.br" in message.page_url:
                # Usar GigaFibraFlow (cookie já injetado, verificar modal)
                giga_flow = GigaFibraFlow(
                    self._cookie_injector,
                    self._component_interactor,
                    screenshotter,
                )
                await giga_flow.execute(context, page)

            # 8. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 8.5 Expandir accordions/FAQs para revelar conteúdo oculto
            await self._expand_accordions(page)

            # 9. Voltar ao topo e aguardar renderização com wait inteligente
            await page.evaluate("window.scrollTo(0, 0)")
            await self._wait_manager.wait_for_page_ready(page)

            # Screenshot antes da extração
            await screenshotter.capture(page, "before_extraction")

            screenshot_bytes = await page.screenshot(
                full_page=True,
                type="png",
                timeout=60000,
            )
            logger.info(
                "Screenshot full-page capturado: %d bytes",
                len(screenshot_bytes),
            )

            # 10. Resize para limites do Bedrock
            screenshot_bytes = self._resize_for_bedrock(screenshot_bytes)

            # 11. Executar estratégia de extração
            extractor = self._get_extractor(message.extraction_strategy)
            extraction_result = await extractor.extract(
                page,
                message.selector_or_pattern,
                message.product_name,
            )

            # Calcular tempo total
            load_time_ms = int((time.perf_counter() - start_time) * 1000)

            # Health Check Score
            score, reason, extraction_skipped = self._health_check_scorer.score(
                validation_result=validation_result,
                extraction_success=extraction_result.success,
                network_error=False,
            )

            # Log estruturado de execução
            self._structured_logger.log_execution(ScrapeExecutionLog(
                url=message.page_url,
                page_title=await page.title(),
                load_time_ms=load_time_ms,
                price_count=1 if extraction_result.success else 0,
                plan_count=1 if extraction_result.success else 0,
                detected_language=(
                    validation_result.detected_language
                    if validation_result else "pt"
                ),
                detected_currency=(
                    validation_result.detected_currency
                    if validation_result else "BRL"
                ),
            ))

            # Montar ScrapeResult
            if extraction_result.success:
                logger.info(
                    "Extração bem-sucedida: produto='%s', preço=R$ %.2f",
                    message.product_name,
                    extraction_result.price,
                )

                # Log de sucesso
                self._structured_logger.log_success(ScrapeSuccessLog(
                    health_check_score=score.value,
                    prices_extracted=1,
                    screenshots_count=screenshotter.step_count,
                ))

                return ScrapeResult(
                    extraction_status="success",
                    extracted_price=extraction_result.price,
                    screenshot_bytes=screenshot_bytes,
                )
            else:
                logger.warning(
                    "Extração falhou: produto='%s', razão='%s'",
                    message.product_name,
                    extraction_result.failure_reason,
                )
                status = "not_found" if "não encontr" in (
                    extraction_result.failure_reason or ""
                ).lower() else "failed"

                return ScrapeResult(
                    extraction_status=status,
                    failure_reason=extraction_result.failure_reason,
                    screenshot_bytes=screenshot_bytes,
                )

        except Exception as e:
            logger.error(
                "Erro inesperado durante scraping de '%s': %s",
                message.product_name, e, exc_info=True,
            )

            # Capturar diagnóstico se page disponível
            if page:
                try:
                    await diagnostics.capture_diagnostic(
                        page, e, message.competitor_id, message.cycle_id
                    )
                except Exception:
                    pass

            return ScrapeResult(
                extraction_status="failed",
                failure_reason=f"Erro inesperado: {str(e)}",
                screenshot_bytes=screenshot_bytes,
            )
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright_instance:
                try:
                    await playwright_instance.stop()
                except Exception:
                    pass

    async def scrape_all(
        self, message: PriceCheckMessage
    ) -> MultiPriceExtractionResult:
        """Extrai TODOS os planos/preços de uma página de concorrente.

        Fluxo resiliente idêntico ao scrape() para navegação, mas usa
        AIExtractor.extract_all() para obter todos os planos de uma vez.

        Args:
            message: Mensagem com dados do concorrente (page_url, etc).

        Returns:
            MultiPriceExtractionResult com lista de planos encontrados.
        """
        logger.info(
            "Iniciando scraping multi-plano: "
            "concorrente='%s', url='%s'",
            message.competitor_name,
            message.page_url,
        )

        start_time = time.perf_counter()
        playwright_instance = None
        browser = None
        page: Page | None = None
        cloud_manager: CloudBrowserManager | None = None
        using_cloud_browser = False

        # Instanciar screenshotter e diagnostics para esta execução
        s3_bucket = os.environ.get(
            "S3_BUCKET", "price-watchdog-screenshots-761018874615"
        )
        screenshotter = StepScreenshotter(
            competitor_id=message.competitor_id,
            cycle_id=message.cycle_id,
            bucket=s3_bucket,
        )
        diagnostics = DiagnosticsCollector(bucket=s3_bucket)

        try:
            # 1. Abrir browser — decidir entre LOCAL e CLOUD
            using_cloud_browser = self._should_use_cloud_browser(
                message.page_url
            )

            if using_cloud_browser:
                # === CLOUD BROWSER (Bright Data / Scrapeless) ===
                logger.info(
                    "Usando Cloud Browser para: %s",
                    message.page_url,
                )
                cloud_manager = CloudBrowserManager(
                    self._cloud_browser_config
                )
                await cloud_manager.__aenter__()
                browser, context, page = await cloud_manager.connect(
                    viewport_width=_VIEWPORT_WIDTH,
                    viewport_height=_VIEWPORT_HEIGHT,
                )
                logger.info("Cloud Browser inicializado (multi).")
            else:
                # === BROWSER LOCAL (padrão) ===
                playwright_instance = await async_playwright().start()

                # Args anti-detect para SPAs que bloqueiam headless
                launch_args = [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ]

                browser = await playwright_instance.chromium.launch(
                    headless=True,
                    args=launch_args,
                )
                logger.info("Browser Chromium local inicializado (multi).")

                context = await browser.new_context(
                    viewport={
                        "width": _VIEWPORT_WIDTH,
                        "height": _VIEWPORT_HEIGHT,
                    },
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                    geolocation={
                        "latitude": -23.5505,
                        "longitude": -46.6333,
                    },
                    permissions=["geolocation"],
                    extra_http_headers={
                        "Accept-Language": "pt-BR,pt;q=0.9",
                    },
                )
                page = await context.new_page()

            # 1.5 Stealth: remover sinais de automação para SPAs (Globoplay)
            if "globoplay.globo.com" in message.page_url:
                await context.add_init_script("""
                    // Tentar remover webdriver (se configurável)
                    try {
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined,
                        });
                    } catch(e) {}
                    // Chrome runtime
                    if (!window.chrome) {
                        window.chrome = { runtime: {} };
                    }
                    // Permissions override
                    try {
                        const originalQuery = window.navigator.permissions.query;
                        window.navigator.permissions.query = (parameters) =>
                            parameters.name === 'notifications'
                                ? Promise.resolve({ state: Notification.permission })
                                : originalQuery(parameters);
                    } catch(e) {}
                    // Plugins
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                    // Languages
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['pt-BR', 'pt', 'en-US', 'en'],
                    });
                """)

            # 2. Injetar cookies de geolocalização (ANTES da navegação)
            # Pular se usando cloud browser (IP já é brasileiro)
            if not using_cloud_browser:
                site_config = self._get_site_config(message.page_url)
                if site_config:
                    injection_result = await self._cookie_injector.inject_cookies(
                        context, site_config
                    )
                    logger.info(
                        "Cookies injetados (multi): %d cookie(s)",
                        injection_result.cookies_count,
                    )

            # 3. Navegar com retry automático
            nav_result = await self._retry_engine.execute(
                self._navigate_page, "navigation_multi", page, message.page_url
            )

            if not nav_result.success:
                failure_reason = (
                    f"Navegação falhou após {nav_result.attempts} tentativas: "
                    f"{nav_result.errors[-1] if nav_result.errors else 'erro desconhecido'}"
                )
                logger.error(failure_reason)
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason=failure_reason,
                )

            # Verificar status HTTP
            response = nav_result.result
            if response and response.status >= 400:
                logger.error(
                    "HTTP %d para '%s'",
                    response.status,
                    message.page_url,
                )
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason=f"HTTP {response.status}",
                )

            logger.info(
                "Página carregada (multi): %s", message.page_url
            )

            # 4. Aguardar página pronta com waits inteligentes
            site_key = _get_site_key(message.page_url)
            critical_selectors = _CRITICAL_SELECTORS.get(site_key or "", None)
            wait_result = await self._wait_manager.wait_for_page_ready(
                page, critical_selectors=critical_selectors
            )
            logger.info(
                "Página pronta (multi): estratégia='%s', tempo=%dms",
                wait_result.strategy_used,
                wait_result.elapsed_ms,
            )

            # 5. Screenshot após carregamento
            await screenshotter.capture(page, "after_load")

            # 6. Validar conteúdo para sites com risco geo
            validation_result = None
            if site_key in ("netflix", "paramount"):
                expected_url_pattern = "/br/" if site_key == "paramount" else None
                validation_result = await self._content_validator.validate(
                    page,
                    expected_language="pt",
                    expected_currency="BRL",
                    expected_url_pattern=expected_url_pattern,
                )

                if not validation_result.is_valid:
                    score, reason, _ = self._health_check_scorer.score(
                        validation_result=validation_result,
                        extraction_success=False,
                        network_error=False,
                    )
                    await diagnostics.capture_diagnostic(
                        page,
                        reason or "geo_validation_failed",
                        message.competitor_id,
                        message.cycle_id,
                    )
                    logger.warning(
                        "Extração multi skipped: score=%s, razão=%s",
                        score.value, reason,
                    )
                    return MultiPriceExtractionResult(
                        success=False,
                        failure_reason=reason,
                    )

            # 7. Interação específica por concorrente
            vivo_accumulated_text: str = ""
            globoplay_text: str = ""

            if "vivo.com.br" in message.page_url:
                await self._fill_vivo_cep(page)
                vivo_flow = VivoTVFlow(self._wait_manager, screenshotter)
                await vivo_flow.navigate_tabs(page)
                vivo_accumulated_text = vivo_flow.accumulated_text

            if "gigamaisfibra.com.br" in message.page_url:
                giga_flow = GigaFibraFlow(
                    self._cookie_injector,
                    self._component_interactor,
                    screenshotter,
                )
                await giga_flow.execute(context, page)

            if "globoplay.globo.com" in message.page_url:
                globo_flow = GloboplayFlow(
                    self._wait_manager, screenshotter
                )
                globoplay_text = await globo_flow.execute(page)

            # 8. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 8.5 Expandir accordions/FAQs para revelar conteúdo oculto
            await self._expand_accordions(page)

            # 9. Voltar ao topo e aguardar renderização com wait inteligente
            await page.evaluate("window.scrollTo(0, 0)")
            await self._wait_manager.wait_for_page_ready(page)

            # 9.5 Wait extra para SPAs que demoram a renderizar preços
            if site_key == "sky":
                import asyncio as _asyncio
                await _asyncio.sleep(5)
                logger.info("Wait extra (5s) para SPA: %s", site_key)

            # Screenshot antes da extração
            await screenshotter.capture(page, "before_extraction")

            # 10. Usar AIExtractor.extract_all
            extractor = AIExtractor()

            # Combinar texto extra de flows específicos
            extra_text = vivo_accumulated_text or globoplay_text or ""

            result = await extractor.extract_all(
                page, message.competitor_name,
                extra_text=extra_text,
            )

            # Calcular tempo e log estruturado
            load_time_ms = int((time.perf_counter() - start_time) * 1000)
            score, reason, _ = self._health_check_scorer.score(
                validation_result=validation_result,
                extraction_success=result.success,
                network_error=False,
            )

            self._structured_logger.log_execution(ScrapeExecutionLog(
                url=message.page_url,
                page_title=await page.title(),
                load_time_ms=load_time_ms,
                price_count=len(result.plans) if result.success else 0,
                plan_count=len(result.plans) if result.success else 0,
                detected_language=(
                    validation_result.detected_language
                    if validation_result else "pt"
                ),
                detected_currency=(
                    validation_result.detected_currency
                    if validation_result else "BRL"
                ),
            ))

            if result.success:
                self._structured_logger.log_success(ScrapeSuccessLog(
                    health_check_score=score.value,
                    prices_extracted=len(result.plans),
                    screenshots_count=screenshotter.step_count,
                ))

            return result

        except Exception as e:
            logger.error(
                "Erro inesperado durante scraping multi de '%s': %s",
                message.competitor_name,
                e,
                exc_info=True,
            )

            # Capturar diagnóstico se page disponível
            if page:
                try:
                    await diagnostics.capture_diagnostic(
                        page, e, message.competitor_id, message.cycle_id
                    )
                except Exception:
                    pass

            return MultiPriceExtractionResult(
                success=False,
                failure_reason=f"Erro inesperado: {str(e)}",
            )
        finally:
            if using_cloud_browser and cloud_manager:
                try:
                    await cloud_manager.__aexit__(None, None, None)
                except Exception:
                    pass
            else:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                if playwright_instance:
                    try:
                        await playwright_instance.stop()
                    except Exception:
                        pass

    async def _fill_vivo_cep(self, page: Page) -> None:
        """Seta localização São Paulo no site da Vivo via cookie/localStorage.

        O site da Vivo usa IP-based geolocation. Como o worker roda nos EUA,
        preciso forçar a localização via cookie ou localStorage antes
        da página carregar os preços.

        Args:
            page: Página Playwright já navegada.
        """
        try:
            logger.info("Vivo TV: setando localização São Paulo via JS...")

            # Setar localStorage com localização de São Paulo
            await page.evaluate("""
                () => {
                    // Tentar setar localização via localStorage
                    localStorage.setItem('userLocation', JSON.stringify({
                        city: 'São Paulo',
                        state: 'SP',
                        cep: '06764040',
                        ddd: '11'
                    }));
                    localStorage.setItem('selectedCity', 'São Paulo');
                    localStorage.setItem('selectedState', 'SP');
                    localStorage.setItem('cep', '06764040');
                    localStorage.setItem('userCep', '06764040');
                    localStorage.setItem('location', 'SP');
                    localStorage.setItem('ddd', '11');
                }
            """)

            # Setar cookies de localização
            await page.context.add_cookies([
                {
                    "name": "user_location",
                    "value": "SP",
                    "domain": ".vivo.com.br",
                    "path": "/",
                },
                {
                    "name": "user_city",
                    "value": "Sao Paulo",
                    "domain": ".vivo.com.br",
                    "path": "/",
                },
                {
                    "name": "user_cep",
                    "value": "06764040",
                    "domain": ".vivo.com.br",
                    "path": "/",
                },
                {
                    "name": "user_ddd",
                    "value": "11",
                    "domain": ".vivo.com.br",
                    "path": "/",
                },
            ])

            # Recarregar a página para aplicar a localização
            await page.reload(wait_until="domcontentloaded")

            # Esperar página pronta com wait inteligente
            await self._wait_manager.wait_for_page_ready(page)

            logger.info("Vivo TV: página recarregada com localização SP")

        except Exception as e:
            logger.warning(
                "Vivo TV: falha ao setar localização: %s", e
            )

    async def _navigate_vivo_tabs(self, page: Page) -> None:
        """DEPRECATED — agora usa VivoTVFlow.

        Mantido como fallback caso o VivoTVFlow não seja adequado.
        Navega pelas tabs de ofertas da Vivo para capturar todos os planos.

        Args:
            page: Página Playwright já com localização SP definida.
        """
        # Delegado para VivoTVFlow — este método é mantido apenas
        # para compatibilidade reversa mas não é mais chamado diretamente.
        pass

    async def _fill_giga_location(self, page: Page) -> None:
        """DEPRECATED — agora usa GigaFibraFlow com cookie injection.

        O fluxo principal agora injeta cookies de geolocalização ANTES
        da navegação e usa GigaFibraFlow para verificar supressão do modal
        e fallback via Cascade Strategy. Este método é mantido apenas
        para compatibilidade reversa mas não é mais chamado diretamente.

        Args:
            page: Página Playwright já navegada.
        """
        # Delegado para GigaFibraFlow — não chamado diretamente.
        pass

    async def _navigate_page(self, page: Page, url: str):
        """Navega para URL com domcontentloaded wait.

        Usada como operação para o RetryEngine.

        Args:
            page: Página Playwright.
            url: URL destino.

        Returns:
            Response do Playwright.
        """
        response = await page.goto(
            url,
            timeout=_NAVIGATION_TIMEOUT_MS,
            wait_until="domcontentloaded",
        )
        return response

    def _get_site_config(self, url: str) -> dict | None:
        """Retorna configuração do site para cookie injection.

        Verifica se a URL corresponde a um site com cookies de
        geolocalização configurados.

        Args:
            url: URL da página.

        Returns:
            Dict de configuração do site ou None se não configurado.
        """
        if "gigamaisfibra.com.br" in url:
            from scraping_resilience.site_configs.giga_fibra import (
                GIGA_FIBRA_CONFIG,
            )
            return GIGA_FIBRA_CONFIG
        return None

    async def _scroll_page(self, page: Page) -> None:
        """Scroll incremental para forçar lazy-loading.

        Rola a página em incrementos do viewport, aguardando
        network idle a cada passo. Para quando atinge o fundo
        ou o limite de 8000px.

        Args:
            page: Página Playwright já navegada.
        """
        previous_height = 0

        while True:
            current_height = await page.evaluate(
                "document.body.scrollHeight"
            )

            if current_height == previous_height:
                break  # Nada novo carregou

            if current_height >= _MAX_SCROLL_HEIGHT:
                logger.info(
                    "Scroll atingiu limite de %dpx", _MAX_SCROLL_HEIGHT
                )
                break

            await page.evaluate(
                f"window.scrollBy(0, {_VIEWPORT_HEIGHT})"
            )

            # Esperar conteúdo carregar (condição-based, sem sleep fixo)
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=5000
                )
            except Exception:
                pass  # Timeout é OK, alguns sites nunca ficam idle

            # Aguardar brevemente via wait_for_timeout (Playwright-managed)
            await page.wait_for_timeout(300)
            previous_height = current_height

        logger.info(
            "Scroll concluído: altura final %dpx",
            await page.evaluate("document.body.scrollHeight"),
        )

    async def _expand_accordions(self, page: Page) -> None:
        """Expande todos os accordions/FAQs da página.

        Clica em elementos colapsáveis (details, accordions, FAQs)
        para revelar conteúdo oculto que pode conter preços ou
        informações de pacotes. Funciona genericamente para:
        - HTML5 <details>/<summary> (Apple TV+, etc.)
        - Accordions com aria-expanded="false"
        - Elementos com classe accordion/collapse/faq

        Usa timeouts curtos para evitar travamento em botões
        que acionam navegação ou modais pesados.

        Args:
            page: Página Playwright já carregada e scrollada.
        """
        try:
            # Estratégia 1: Abrir todos os <details> nativos do HTML5
            # (rápido, sem side-effects — apenas seta atributo)
            opened = await page.evaluate("""
                () => {
                    let count = 0;
                    document.querySelectorAll('details:not([open])').forEach(el => {
                        el.setAttribute('open', '');
                        count++;
                    });
                    return count;
                }
            """)
            if opened > 0:
                logger.info(
                    "Accordions: %d <details> expandidos", opened
                )

            # Estratégia 2: Clicar em aria-expanded="false"
            # Inclui botões dentro de seções FAQ (Netflix, etc.)
            aria_buttons = await page.query_selector_all(
                "[aria-expanded='false'][class*='accord'], "
                "[aria-expanded='false'][class*='faq'], "
                "[aria-expanded='false'][class*='question'], "
                "[aria-expanded='false'][class*='collapse'], "
                "[aria-expanded='false'][role='button']"
                "[aria-controls], "
                "button[aria-expanded='false']"
            )
            aria_count = 0
            for btn in aria_buttons[:15]:  # Max 15
                try:
                    # Verificar se é botão de FAQ (não navegação)
                    text = await btn.inner_text()
                    # Pular botões de nav/menu (curtos demais ou genéricos)
                    if len(text.strip()) < 5 or text.strip().lower() in (
                        "menu", "fechar", "abrir", "ver mais",
                        "saiba mais", "mostrar",
                    ):
                        continue
                    # Timeout curto: 2s por click
                    await btn.click(timeout=2000)
                    aria_count += 1
                    await page.wait_for_timeout(300)
                except Exception:
                    pass  # Skip se travar
            if aria_count > 0:
                logger.info(
                    "Accordions: %d aria-expanded clicados",
                    aria_count,
                )

            # Estratégia 3: Clicar em headers de FAQ
            faq_triggers = await page.query_selector_all(
                "[class*='accordion'] [class*='header'], "
                "[class*='accordion'] [class*='title'], "
                "[class*='faq'] [class*='question'], "
                "button[class*='accordion']"
            )
            faq_count = 0
            for trigger in faq_triggers[:10]:
                try:
                    await trigger.click(timeout=2000)
                    faq_count += 1
                    await page.wait_for_timeout(200)
                except Exception:
                    pass
            if faq_count > 0:
                logger.info(
                    "Accordions: %d FAQ triggers clicados",
                    faq_count,
                )

            # Aguardar animações
            total = opened + aria_count + faq_count
            if total > 0:
                await page.wait_for_timeout(1000)
                logger.info(
                    "Accordions expandidos: total %d elementos",
                    total,
                )

        except Exception as e:
            logger.warning(
                "Falha ao expandir accordions (não-crítico): %s", e
            )

    def _resize_for_bedrock(self, image_bytes: bytes) -> bytes:
        """Resize screenshot para limites do Bedrock.

        - Se > 8000px em qualquer dimensão → redimensiona proporcionalmente
        - Se > 5MB → converte para JPEG com quality decrescente até caber
        - Limite Bedrock: 5242880 bytes (5MB)

        Args:
            image_bytes: Bytes do screenshot PNG.

        Returns:
            Bytes da imagem (ajustada ou original).
        """
        try:
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            width, height = img.size

            # Redimensionar se excede 8000px
            if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                ratio = min(
                    _MAX_IMAGE_DIMENSION / width,
                    _MAX_IMAGE_DIMENSION / height,
                )
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                logger.info(
                    "Imagem redimensionada de %dx%d para %dx%d",
                    width, height, new_width, new_height,
                )

            # Salvar como PNG
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            result = buffer.getvalue()

            # Se > 4.5MB, converter para JPEG com quality decrescente
            if len(result) > _MAX_IMAGE_SIZE_BYTES:
                if img.mode == "RGBA":
                    img = img.convert("RGB")

                # Tentar qualidades decrescentes até caber
                for quality in (80, 60, 45, 30):
                    buffer = BytesIO()
                    img.save(buffer, format="JPEG", quality=quality)
                    result = buffer.getvalue()
                    if len(result) <= _MAX_IMAGE_SIZE_BYTES:
                        logger.info(
                            "Imagem convertida para JPEG q=%d: %d bytes",
                            quality, len(result),
                        )
                        break
                else:
                    # Se ainda não coube, reduzir dimensão pela metade
                    w, h = img.size
                    img = img.resize(
                        (w // 2, h // 2), Image.LANCZOS
                    )
                    buffer = BytesIO()
                    img.save(buffer, format="JPEG", quality=60)
                    result = buffer.getvalue()
                    logger.info(
                        "Imagem reduzida 50%% + JPEG q=60: %d bytes",
                        len(result),
                    )

            return result

        except ImportError:
            logger.warning("Pillow não disponível, sem resize")
            return image_bytes
        except Exception as e:
            logger.warning("Falha ao resize: %s", e)
            return image_bytes

    def _get_extractor(self, strategy: str) -> BaseExtractor:
        """Retorna o extractor adequado para a estratégia.

        Args:
            strategy: Nome da estratégia (css_selector, regex, ai, ai_all).

        Returns:
            Instância do extractor correspondente.
        """
        extractors: dict[str, BaseExtractor] = {
            "css_selector": CSSSelectorExtractor(),
            "regex": RegexExtractor(),
            "ai": AIExtractor(),
            "ai_all": AIExtractor(),
        }

        if strategy not in extractors:
            raise ValueError(
                f"Estratégia '{strategy}' não suportada. "
                f"Opções: {list(extractors.keys())}"
            )

        return extractors[strategy]
