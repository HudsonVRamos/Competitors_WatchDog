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
                await self._navigate_vivo_tabs(page)

            # Se é site do Giga+ Fibra, selecionar cidade São Paulo
            if "gigamaisfibra.com.br" in message.page_url:
                await self._fill_giga_location(page)

            # 3. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 3.5 Expandir accordions/FAQs para revelar conteúdo oculto
            await self._expand_accordions(page)

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
                await self._navigate_vivo_tabs(page)

            # Se é site do Giga+ Fibra, selecionar cidade São Paulo
            if "gigamaisfibra.com.br" in message.page_url:
                await self._fill_giga_location(page)

            # 3. Scroll incremental para forçar lazy-loading
            await self._scroll_page(page)

            # 3.5 Expandir accordions/FAQs para revelar conteúdo oculto
            await self._expand_accordions(page)

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
            await page.wait_for_timeout(5000)

            # Esperar network idle
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            logger.info("Vivo TV: página recarregada com localização SP")

        except Exception as e:
            logger.warning(
                "Vivo TV: falha ao setar localização: %s", e
            )

    async def _navigate_vivo_tabs(self, page: Page) -> None:
        """Navega pelas tabs de ofertas da Vivo para capturar todos os planos.

        O site da Vivo tem 3 seções de ofertas em tabs:
        - TV Online
        - TV por Assinatura
        - Vivo Fibra + TV

        Clica em cada tab para forçar o carregamento do conteúdo,
        garantindo que o screenshot final e a extração por IA
        capturem informações de todas as categorias.

        Args:
            page: Página Playwright já com localização SP definida.
        """
        try:
            logger.info("Vivo TV: navegando pelas tabs de ofertas...")

            # Esperar as tabs carregarem (demora uns segundos)
            await page.wait_for_timeout(5000)

            # Buscar tabs/botões de navegação de ofertas
            tab_texts = [
                "TV Online",
                "TV por Assinatura",
                "Vivo Fibra + TV",
                "Fibra + TV",
                "TV + Fibra",
            ]

            tabs_clicked = 0
            for tab_text in tab_texts:
                try:
                    # Tentar clicar na tab pelo texto
                    tab = await page.query_selector(
                        f"text='{tab_text}'"
                    )
                    if tab:
                        await tab.click(timeout=3000)
                        tabs_clicked += 1
                        # Esperar conteúdo carregar
                        await page.wait_for_timeout(3000)
                        try:
                            await page.wait_for_load_state(
                                "networkidle", timeout=8000
                            )
                        except Exception:
                            pass
                        logger.info(
                            "Vivo TV: tab '%s' clicada",
                            tab_text,
                        )
                except Exception:
                    pass

            # Se não encontrou tabs por texto, tentar seletores genéricos
            if tabs_clicked == 0:
                try:
                    tabs = await page.query_selector_all(
                        "[role='tab'], "
                        "[class*='tab-item'], "
                        "[class*='tab-link'], "
                        "nav [class*='item']"
                    )
                    for tab in tabs[:5]:
                        try:
                            await tab.click(timeout=2000)
                            tabs_clicked += 1
                            await page.wait_for_timeout(2000)
                        except Exception:
                            pass
                except Exception:
                    pass

            if tabs_clicked > 0:
                logger.info(
                    "Vivo TV: %d tabs de ofertas navegadas",
                    tabs_clicked,
                )
            else:
                logger.info(
                    "Vivo TV: nenhuma tab de ofertas encontrada"
                )

            # Voltar para a primeira tab para screenshot completo
            # (ou deixar na última que foi clicada)
            await page.wait_for_timeout(2000)

        except Exception as e:
            logger.warning(
                "Vivo TV: falha ao navegar tabs: %s", e
            )

    async def _fill_giga_location(self, page: Page) -> None:
        """Seleciona São Paulo no popup de localização do Giga+ Fibra.

        O site exibe um modal "Onde você está?" com um dropdown
        de cidades. Interage com o popup para selecionar São Paulo.
        Se São Paulo não estiver disponível, seleciona a primeira
        opção disponível no dropdown.

        Args:
            page: Página Playwright já navegada.
        """
        try:
            logger.info(
                "Giga+ Fibra: verificando popup de localização..."
            )

            # Aguardar popup aparecer (até 8s)
            popup_visible = False
            try:
                await page.wait_for_selector(
                    "text='Onde você está'",
                    timeout=8000,
                )
                popup_visible = True
            except Exception:
                # Popup pode não aparecer (cookie já setado)
                logger.info(
                    "Giga+ Fibra: popup de localização não apareceu, "
                    "continuando normalmente."
                )

            if not popup_visible:
                return

            logger.info(
                "Giga+ Fibra: popup detectado, selecionando cidade..."
            )

            # Tentar interagir com o select/dropdown de cidade
            # Estratégia 1: select element nativo
            select_found = False
            try:
                select_el = await page.wait_for_selector(
                    "select", timeout=3000
                )
                if select_el:
                    # Tentar selecionar "São Paulo" por label
                    try:
                        await page.select_option(
                            "select",
                            label="São Paulo",
                        )
                        select_found = True
                        logger.info(
                            "Giga+ Fibra: São Paulo selecionado "
                            "via <select>"
                        )
                    except Exception:
                        # São Paulo não disponível, selecionar
                        # primeira opção não-vazia
                        logger.info(
                            "Giga+ Fibra: São Paulo não disponível"
                            ", selecionando primeira opção..."
                        )
                        first_option = await page.evaluate("""
                            () => {
                                const sel = document.querySelector(
                                    'select'
                                );
                                if (!sel) return null;
                                for (let i = 0; i < sel.options.length; i++) {
                                    const opt = sel.options[i];
                                    if (opt.value && opt.value !== ''
                                        && !opt.disabled) {
                                        return opt.value;
                                    }
                                }
                                return null;
                            }
                        """)
                        if first_option:
                            await page.select_option(
                                "select", value=first_option
                            )
                            select_found = True
                            logger.info(
                                "Giga+ Fibra: primeira opção "
                                "selecionada: %s",
                                first_option,
                            )
            except Exception:
                pass

            # Estratégia 2: input com autocomplete/typeahead
            if not select_found:
                try:
                    input_el = await page.query_selector(
                        "input[placeholder*='cidade'], "
                        "input[placeholder*='Selecione'], "
                        "input[type='text']"
                    )
                    if input_el:
                        await input_el.click()
                        await input_el.fill("São Paulo")
                        await page.wait_for_timeout(1500)

                        # Tentar clicar em "São Paulo"
                        try:
                            await page.click(
                                "text='São Paulo'",
                                timeout=3000,
                            )
                            select_found = True
                            logger.info(
                                "Giga+ Fibra: São Paulo selecionado "
                                "via input typeahead"
                            )
                        except Exception:
                            # Fallback: limpar e clicar na primeira
                            # opção da lista
                            logger.info(
                                "Giga+ Fibra: São Paulo não encontrado"
                                ", selecionando primeira opção..."
                            )
                            await input_el.fill("")
                            await input_el.click()
                            await page.wait_for_timeout(1500)
                            try:
                                first_item = await page.query_selector(
                                    "li:not([aria-disabled='true']), "
                                    "[role='option']:not([aria-disabled])"
                                )
                                if first_item:
                                    await first_item.click()
                                    select_found = True
                                    logger.info(
                                        "Giga+ Fibra: primeira opção "
                                        "selecionada via typeahead"
                                    )
                            except Exception:
                                pass
                except Exception:
                    pass

            # Estratégia 3: dropdown customizado
            if not select_found:
                try:
                    dropdown_trigger = await page.query_selector(
                        "[class*='select'], [class*='dropdown'], "
                        "[role='combobox'], [role='listbox']"
                    )
                    if dropdown_trigger:
                        await dropdown_trigger.click()
                        await page.wait_for_timeout(1000)

                        # Tentar São Paulo primeiro
                        try:
                            await page.click(
                                "text='São Paulo'", timeout=2000
                            )
                            select_found = True
                            logger.info(
                                "Giga+ Fibra: São Paulo selecionado "
                                "via dropdown customizado"
                            )
                        except Exception:
                            # Fallback: primeira opção visível
                            try:
                                first_opt = await page.query_selector(
                                    "[role='option'], li, "
                                    ".dropdown-item, "
                                    "[class*='option']"
                                )
                                if first_opt:
                                    await first_opt.click()
                                    select_found = True
                                    logger.info(
                                        "Giga+ Fibra: primeira opção "
                                        "selecionada via dropdown"
                                    )
                            except Exception:
                                pass
                except Exception:
                    pass

            if not select_found:
                logger.warning(
                    "Giga+ Fibra: não conseguiu selecionar cidade"
                )

            # Clicar no botão OK/Confirmar para fechar o popup
            try:
                ok_button = await page.query_selector(
                    "button:text('OK'), button:text('Ok'), "
                    "button:text('Confirmar'), "
                    "button[type='submit']"
                )
                if ok_button:
                    await ok_button.click()
                    logger.info("Giga+ Fibra: botão OK clicado")
                else:
                    await page.click(
                        "button:has-text('OK')", timeout=3000
                    )
            except Exception:
                logger.warning(
                    "Giga+ Fibra: não encontrou botão de confirmação"
                )

            # Aguardar página recarregar com conteúdo regional
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_load_state(
                    "networkidle", timeout=10000
                )
            except Exception:
                pass

            logger.info(
                "Giga+ Fibra: localização São Paulo configurada"
            )

        except Exception as e:
            logger.warning(
                "Giga+ Fibra: falha ao interagir com popup de "
                "localização: %s",
                e,
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
            # APENAS em elementos que parecem FAQ/accordion
            # (evita botões de navegação, "Saiba mais", etc.)
            aria_buttons = await page.query_selector_all(
                "[aria-expanded='false'][class*='accord'], "
                "[aria-expanded='false'][class*='faq'], "
                "[aria-expanded='false'][class*='question'], "
                "[aria-expanded='false'][class*='collapse'], "
                "[aria-expanded='false'][role='button']"
                "[aria-controls]"
            )
            aria_count = 0
            for btn in aria_buttons[:10]:  # Max 10
                try:
                    # Timeout curto: 2s por click
                    await btn.click(timeout=2000)
                    aria_count += 1
                    await page.wait_for_timeout(200)
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
