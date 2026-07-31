"""PriceScraper — coordena navegação, screenshot e extração de preços.

Usa Playwright com Chromium headless para:
1. Navegar até a URL com viewport 1920x720
2. Scroll incremental para forçar lazy-loading (até 8000px)
3. Voltar ao topo e capturar full_page screenshot
4. Resize da imagem para limites do Bedrock (max 8000px, max 4.5MB)
5. Executar estratégia de extração (regex ou AI)

Requirements: 3.1, 3.4, 7.1
"""

from __future__ import annotations

import asyncio
import logging
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


class PriceScraper:
    """Navega páginas e coordena extração de preços.

    Cria um browser novo para cada request (evita acúmulo de memória).
    Usa scroll incremental para carregar lazy content antes do screenshot.
    """

    def __init__(self) -> None:
        """Inicializa o PriceScraper."""
        pass

    async def scrape(self, message: PriceCheckMessage) -> ScrapeResult:
        """Executa navegação, screenshot full-page e extração.

        Fluxo:
        1. Abre browser com viewport 1920x720
        2. Navega até URL (wait domcontentloaded, timeout 60s)
        3. Scroll incremental para forçar lazy-loading
        4. Volta ao topo e captura full_page=True
        5. Resize se necessário (Bedrock limits)
        6. Executa estratégia de extração

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
        browser = None
        page: Page | None = None

        try:
            # 1. Abrir browser com viewport pequeno
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
                    "X-Forwarded-For": "177.71.164.1",
                },
            )
            page = await context.new_page()

            # 2. Navegar até a URL
            try:
                response = await page.goto(
                    message.page_url,
                    timeout=_NAVIGATION_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                if response and response.status >= 400:
                    logger.error(
                        "HTTP %d para '%s'", response.status, message.page_url
                    )
                    return ScrapeResult(
                        extraction_status="failed",
                        failure_reason=f"HTTP {response.status}",
                    )
                logger.info("Página carregada: %s", message.page_url)
            except Exception as nav_error:
                logger.error(
                    "Erro de navegação para '%s': %s",
                    message.page_url, nav_error,
                )
                return ScrapeResult(
                    extraction_status="failed",
                    failure_reason=f"Erro de navegação: {str(nav_error)}",
                )

            # Esperar network idle antes do scroll
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # Timeout OK

            # Se é site da Vivo, inserir CEP para desbloquear preços
            if "vivo.com.br" in message.page_url:
                await self._fill_vivo_cep(page)

            # 3. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 4. Voltar ao topo e capturar full_page screenshot
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(10000)  # 10s para garantir renderização completa (Vivo TV)

            screenshot_bytes = await page.screenshot(
                full_page=True,
                type="png",
                timeout=60000,
            )
            logger.info(
                "Screenshot full-page capturado: %d bytes",
                len(screenshot_bytes),
            )

            # 5. Resize para limites do Bedrock
            screenshot_bytes = self._resize_for_bedrock(screenshot_bytes)

            # 6. Executar estratégia de extração
            extractor = self._get_extractor(message.extraction_strategy)
            extraction_result = await extractor.extract(
                page,
                message.selector_or_pattern,
                message.product_name,
            )

            # Montar ScrapeResult
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
                message.product_name, e, exc_info=True,
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

    async def scrape_all(
        self, message: PriceCheckMessage
    ) -> MultiPriceExtractionResult:
        """Extrai TODOS os planos/preços de uma página de concorrente.

        Fluxo idêntico ao scrape() para navegação, mas usa
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

        playwright_instance = None
        browser = None
        page: Page | None = None

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
            logger.info("Browser Chromium inicializado (multi).")

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
                    "X-Forwarded-For": "177.71.164.1",
                },
            )
            page = await context.new_page()

            # 2. Navegar até a URL
            try:
                response = await page.goto(
                    message.page_url,
                    timeout=_NAVIGATION_TIMEOUT_MS,
                    wait_until="domcontentloaded",
                )
                if response and response.status >= 400:
                    logger.error(
                        "HTTP %d para '%s'",
                        response.status,
                        message.page_url,
                    )
                    return MultiPriceExtractionResult(
                        success=False,
                        failure_reason=(
                            f"HTTP {response.status}"
                        ),
                    )
                logger.info(
                    "Página carregada (multi): %s",
                    message.page_url,
                )
            except Exception as nav_error:
                logger.error(
                    "Erro de navegação para '%s': %s",
                    message.page_url,
                    nav_error,
                )
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason=(
                        f"Erro de navegação: {str(nav_error)}"
                    ),
                )

            # Esperar network idle antes do scroll
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass  # Timeout OK

            # Se é site da Vivo, inserir CEP para desbloquear preços
            if "vivo.com.br" in message.page_url:
                await self._fill_vivo_cep(page)

            # 3. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 4. Voltar ao topo
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(10000)  # 10s para garantir renderização completa (Vivo TV)

            # 5. Usar AIExtractor.extract_all
            extractor = AIExtractor()
            result = await extractor.extract_all(
                page, message.competitor_name
            )

            return result

        except Exception as e:
            logger.error(
                "Erro inesperado durante scraping multi de '%s': %s",
                message.competitor_name,
                e,
                exc_info=True,
            )
            return MultiPriceExtractionResult(
                success=False,
                failure_reason=f"Erro inesperado: {str(e)}",
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

    async def _fill_vivo_cep(self, page: Page) -> None:
        """Insere CEP no site da Vivo para desbloquear preços.

        O site da Vivo exige CEP para mostrar preços. Este método
        clica em "Trocar localização" e insere o CEP de Taboão da Serra/SP.

        Args:
            page: Página Playwright já navegada.
        """
        try:
            logger.info("Vivo TV: tentando inserir CEP 06764040...")

            # Tentar clicar no botão "Trocar localização"
            location_btn = await page.query_selector(
                'a:has-text("Trocar localização"), '
                'button:has-text("Trocar localização"), '
                '[data-testid="change-location"], '
                '.location-change'
            )

            if location_btn:
                await location_btn.click()
                await page.wait_for_timeout(2000)

            # Procurar campo de CEP
            cep_input = await page.query_selector(
                'input[placeholder*="CEP"], '
                'input[name*="cep"], '
                'input[id*="cep"], '
                'input[type="tel"][maxlength="9"], '
                'input[type="tel"][maxlength="8"]'
            )

            if cep_input:
                await cep_input.click()
                await cep_input.fill("06764040")
                await page.wait_for_timeout(1000)

                # Tentar pressionar Enter ou clicar botão de confirmar
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)

                logger.info("Vivo TV: CEP 06764040 inserido com sucesso")
            else:
                # Tentar via JavaScript diretamente
                await page.evaluate("""
                    () => {
                        const inputs = document.querySelectorAll('input');
                        for (const input of inputs) {
                            if (input.placeholder && input.placeholder.toLowerCase().includes('cep')) {
                                input.value = '06764040';
                                input.dispatchEvent(new Event('input', {bubbles: true}));
                                input.dispatchEvent(new Event('change', {bubbles: true}));
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                await page.wait_for_timeout(3000)
                logger.info("Vivo TV: CEP inserido via JS fallback")

        except Exception as e:
            logger.warning(
                "Vivo TV: falha ao inserir CEP: %s", e
            )

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

            # Esperar conteúdo carregar
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=5000
                )
            except Exception:
                pass  # Timeout é OK, alguns sites nunca ficam idle

            await asyncio.sleep(0.3)
            previous_height = current_height

        logger.info(
            "Scroll concluído: altura final %dpx",
            await page.evaluate("document.body.scrollHeight"),
        )

    def _resize_for_bedrock(self, image_bytes: bytes) -> bytes:
        """Resize screenshot para limites do Bedrock.

        - Se > 8000px em qualquer dimensão → redimensiona proporcionalmente
        - Se > 4.5MB → converte para JPEG quality 80

        Args:
            image_bytes: Bytes do screenshot PNG.

        Returns:
            Bytes da imagem (ajustada ou original).
        """
        try:
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            width, height = img.size
            resized = False

            # Redimensionar se excede 8000px
            if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                ratio = min(
                    _MAX_IMAGE_DIMENSION / width,
                    _MAX_IMAGE_DIMENSION / height,
                )
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                resized = True
                logger.info(
                    "Imagem redimensionada de %dx%d para %dx%d",
                    width, height, new_width, new_height,
                )

            # Salvar como PNG
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            result = buffer.getvalue()

            # Se ainda > 4.5MB, converter para JPEG quality 80
            if len(result) > _MAX_IMAGE_SIZE_BYTES:
                buffer = BytesIO()
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(buffer, format="JPEG", quality=80)
                result = buffer.getvalue()
                logger.info(
                    "Imagem convertida para JPEG: %d bytes", len(result)
                )

            if resized:
                return result
            return image_bytes

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
