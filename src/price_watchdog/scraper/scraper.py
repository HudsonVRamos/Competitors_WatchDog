"""PriceScraper — coordena navegação, screenshot e extração de preços.

Navega até a URL do concorrente usando Playwright com Chromium headless,
captura screenshot como evidência, e executa a estratégia de extração
configurada (CSS selector, regex ou AI).

Requirements: 3.1, 3.4, 7.1
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright, Browser, Page

from price_watchdog.models.dataclasses import PriceCheckMessage, ScrapeResult
from price_watchdog.scraper.extractors import (
    AIExtractor,
    BaseExtractor,
    CSSSelectorExtractor,
    RegexExtractor,
)

logger = logging.getLogger(__name__)

# Timeout de navegação (30 segundos conforme spec)
_NAVIGATION_TIMEOUT_MS = 30_000

# Altura máxima do screenshot (5000px conforme spec)
_MAX_SCREENSHOT_HEIGHT = 5000


class PriceScraper:
    """Navega páginas e coordena extração de preços.

    Gerencia um browser Playwright compartilhado entre chamadas
    para evitar overhead de inicialização repetida.

    Fluxo:
    1. Navegar até a URL com timeout de 30s
    2. Capturar screenshot full-page (max 5000px)
    3. Selecionar extractor baseado na extraction_strategy
    4. Executar extração
    5. Retornar ScrapeResult com preço ou razão de falha
    """

    def __init__(self) -> None:
        """Inicializa o PriceScraper."""
        self._browser: Browser | None = None
        self._playwright = None

    async def _ensure_browser(self) -> Browser:
        """Garante que o browser está inicializado.

        Returns:
            Instância do Browser Playwright.
        """
        if self._browser is None or not self._browser.is_connected():
            logger.info("Inicializando Playwright + Chromium...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ],
            )
            logger.info("Browser Chromium inicializado.")
        return self._browser

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Executa navegação, screenshot e extração de preço.

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

        screenshot_bytes: bytes | None = None
        page: Page | None = None

        try:
            browser = await self._ensure_browser()
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # 1. Navegar até a URL com timeout de 30s
            try:
                await page.goto(
                    message.page_url,
                    timeout=_NAVIGATION_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                logger.info(
                    "Página carregada: %s", message.page_url
                )
            except Exception as nav_error:
                logger.error(
                    "Timeout ou erro de navegação para '%s': %s",
                    message.page_url,
                    nav_error,
                )
                return ScrapeResult(
                    extraction_status="failed",
                    failure_reason=f"Erro de navegação: {str(nav_error)}",
                )

            # Aguardar um pouco para conteúdo dinâmico carregar
            await page.wait_for_timeout(3000)

            # 2. Capturar screenshot full-page (max 5000px)
            try:
                screenshot_bytes = await page.screenshot(
                    full_page=True,
                    type="png",
                )
                # Limitar altura se necessário (Playwright já limita internamente)
                logger.info(
                    "Screenshot capturado: %d bytes",
                    len(screenshot_bytes),
                )
            except Exception as ss_error:
                logger.warning(
                    "Falha ao capturar screenshot: %s", ss_error
                )
                # Screenshot é opcional — continua a extração

            # 3. Selecionar extractor e executar extração
            extractor = self._get_extractor(message.extraction_strategy)
            extraction_result = await extractor.extract(
                page,
                message.selector_or_pattern,
                message.product_name,
            )

            # 4. Montar ScrapeResult
            if extraction_result.success:
                logger.info(
                    "Extração bem-sucedida: produto='%s', preço=R$ %.2f",
                    message.product_name,
                    extraction_result.price,
                )
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
                message.product_name,
                e,
                exc_info=True,
            )
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

    def _get_extractor(self, strategy: str) -> BaseExtractor:
        """Retorna o extractor adequado para a estratégia.

        Args:
            strategy: Nome da estratégia (css_selector, regex, ai).

        Returns:
            Instância do extractor correspondente.

        Raises:
            ValueError: Se a estratégia não é suportada.
        """
        extractors: dict[str, BaseExtractor] = {
            "css_selector": CSSSelectorExtractor(),
            "regex": RegexExtractor(),
            "ai": AIExtractor(),
        }

        if strategy not in extractors:
            raise ValueError(
                f"Estratégia de extração '{strategy}' não suportada. "
                f"Opções: {list(extractors.keys())}"
            )

        return extractors[strategy]

    async def close(self) -> None:
        """Fecha o browser e libera recursos."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser fechado.")
