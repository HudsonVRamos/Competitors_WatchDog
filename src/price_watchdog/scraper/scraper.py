"""PriceScraper — coordena navegação, screenshot e extração de preços.

Navega até a URL do concorrente usando Playwright com Chromium headless,
captura screenshot como evidência, e executa a estratégia de extração
configurada (CSS selector, regex ou AI).

Requirements: 3.1, 3.4, 7.1
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright, Page

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
        pass

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Executa navegação, screenshot e extração de preço.

        Cria um browser novo para cada request para evitar
        acumular memória entre páginas pesadas.

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
        playwright_instance = None
        browser: Browser | None = None
        page: Page | None = None

        try:
            # Criar browser isolado para este request
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

            # 2. Capturar screenshot (viewport apenas, não full-page para economizar memória)
            try:
                screenshot_bytes = await page.screenshot(
                    full_page=False,
                    type="png",
                )
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
