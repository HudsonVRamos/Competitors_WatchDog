"""CloudBrowserProvider — conexão com Scraping Browser Cloud (Bright Data).

Encapsula a lógica de conexão via CDP (Chrome DevTools Protocol)
a um browser remoto gerenciado por serviço cloud, que oferece:
- IP residencial embutido (geo-targeting Brasil)
- Anti-detect fingerprinting automático
- CAPTCHA solving integrado
- Bypass de WAF e anti-bot

A integração é transparente: após conectar, o código Playwright
funciona exatamente igual ao browser local.

Compatível com: Bright Data, Scrapeless, Browserless.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class CloudBrowserProvider(str, Enum):
    """Provedores de Scraping Browser Cloud suportados."""

    BRIGHT_DATA = "bright_data"
    SCRAPELESS = "scrapeless"
    BROWSERLESS = "browserless"


class BrowserStrategy(str, Enum):
    """Estratégias de browser disponíveis para scraping."""

    # Browser local padrão (Chromium headless no container)
    LOCAL = "local"

    # Scraping Browser Cloud (via CDP)
    CLOUD = "cloud"

    # Proxy residencial + browser local
    RESIDENTIAL_PROXY = "residential_proxy"


@dataclass
class CloudBrowserConfig:
    """Configuração para conexão com Scraping Browser Cloud.

    Attributes:
        provider: Provedor do serviço (bright_data, scrapeless, browserless).
        endpoint: URL WebSocket do endpoint CDP.
        username: Usuário de autenticação.
        password: Senha de autenticação.
        country: Código do país para geo-targeting (padrão: br).
        timeout_ms: Timeout para conexão em milissegundos.
    """

    provider: CloudBrowserProvider = CloudBrowserProvider.BRIGHT_DATA
    endpoint: str = ""
    username: str = ""
    password: str = ""
    country: str = "br"
    timeout_ms: int = 120_000  # 2 minutos (cloud browser é mais lento)

    @classmethod
    def from_env(cls) -> "CloudBrowserConfig":
        """Carrega configuração a partir de variáveis de ambiente.

        Variáveis esperadas:
        - CLOUD_BROWSER_PROVIDER: bright_data | scrapeless | browserless
        - CLOUD_BROWSER_ENDPOINT: URL WSS completa (opcional, monta automaticamente)
        - CLOUD_BROWSER_USERNAME: Usuário (zone username do Bright Data)
        - CLOUD_BROWSER_PASSWORD: Senha da zone
        - CLOUD_BROWSER_COUNTRY: País para geo-targeting (padrão: br)
        - CLOUD_BROWSER_TIMEOUT_MS: Timeout em ms (padrão: 120000)
        """
        provider_str = os.environ.get(
            "CLOUD_BROWSER_PROVIDER", "bright_data"
        )
        try:
            provider = CloudBrowserProvider(provider_str)
        except ValueError:
            logger.warning(
                "Provedor '%s' não reconhecido, usando bright_data",
                provider_str,
            )
            provider = CloudBrowserProvider.BRIGHT_DATA

        return cls(
            provider=provider,
            endpoint=os.environ.get("CLOUD_BROWSER_ENDPOINT", ""),
            username=os.environ.get("CLOUD_BROWSER_USERNAME", ""),
            password=os.environ.get("CLOUD_BROWSER_PASSWORD", ""),
            country=os.environ.get("CLOUD_BROWSER_COUNTRY", "br"),
            timeout_ms=int(
                os.environ.get("CLOUD_BROWSER_TIMEOUT_MS", "120000")
            ),
        )

    @property
    def is_configured(self) -> bool:
        """Verifica se as credenciais estão configuradas."""
        if self.provider == CloudBrowserProvider.SCRAPELESS:
            # Scrapeless precisa apenas da API key (armazenada em password)
            return bool(self.password)
        if self.provider == CloudBrowserProvider.BROWSERLESS:
            # Browserless precisa apenas do token (armazenada em password)
            return bool(self.password)
        # Bright Data precisa de username + password
        return bool(self.username and self.password)

    @property
    def websocket_url(self) -> str:
        """Monta a URL WebSocket de conexão baseada no provedor.

        Returns:
            URL WSS completa para conexão via CDP.
        """
        if self.endpoint:
            return self.endpoint

        if self.provider == CloudBrowserProvider.BRIGHT_DATA:
            auth = f"{self.username}:{self.password}"
            return f"wss://{auth}@brd.superproxy.io:9222"

        elif self.provider == CloudBrowserProvider.SCRAPELESS:
            # Scrapeless usa token como query parameter
            from urllib.parse import urlencode
            params = urlencode({
                "token": self.password,  # API key vai como "password"
                "sessionTTL": 180,
                "proxyCountry": self.country.upper(),
            })
            return f"wss://browser.scrapeless.com/api/v2/browser?{params}"

        elif self.provider == CloudBrowserProvider.BROWSERLESS:
            return f"wss://chrome.browserless.io?token={self.password}"

        # Fallback: Bright Data
        auth = f"{self.username}:{self.password}"
        return f"wss://{auth}@brd.superproxy.io:9222"


# Domínios que requerem cloud browser (geo-blocking + anti-bot)
_CLOUD_BROWSER_DOMAINS: set[str] = {
    "netflix.com",
    "paramountplus.com",
    "primevideo.com",
    "globoplay.globo.com",
    "liggavc.com.br",
}

# Domínios com apenas geo-blocking (proxy residencial é suficiente)
_RESIDENTIAL_PROXY_DOMAINS: set[str] = set()


def get_browser_strategy(url: str) -> BrowserStrategy:
    """Determina qual estratégia de browser usar para uma URL.

    Args:
        url: URL do site a ser scrapeado.

    Returns:
        Estratégia de browser recomendada.
    """
    for domain in _CLOUD_BROWSER_DOMAINS:
        if domain in url:
            return BrowserStrategy.CLOUD

    for domain in _RESIDENTIAL_PROXY_DOMAINS:
        if domain in url:
            return BrowserStrategy.RESIDENTIAL_PROXY

    return BrowserStrategy.LOCAL


class CloudBrowserManager:
    """Gerencia conexões com Scraping Browser Cloud.

    Responsabilidades:
    - Conectar via CDP ao browser cloud
    - Configurar viewport e locale compatíveis com o projeto
    - Fornecer página pronta para scraping
    - Gerenciar lifecycle (connect/disconnect)

    Uso:
        async with CloudBrowserManager() as manager:
            browser, context, page = await manager.connect()
            await page.goto("https://netflix.com/br/")
            # ... scraping normal ...
    """

    def __init__(self, config: CloudBrowserConfig | None = None) -> None:
        """Inicializa com configuração (carrega do env se não fornecida)."""
        self._config = config or CloudBrowserConfig.from_env()
        self._playwright = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "CloudBrowserManager":
        """Inicia Playwright instance."""
        self._playwright = await async_playwright().start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Fecha browser e Playwright."""
        await self.disconnect()

    async def connect(
        self,
        viewport_width: int = 1920,
        viewport_height: int = 720,
    ) -> tuple[Browser, BrowserContext, Page]:
        """Conecta ao Scraping Browser Cloud via CDP.

        Configura viewport, locale e headers para simular
        navegação brasileira.

        Args:
            viewport_width: Largura do viewport (padrão 1920).
            viewport_height: Altura do viewport (padrão 720).

        Returns:
            Tuple (browser, context, page) prontos para scraping.

        Raises:
            ConnectionError: Se não conseguir conectar ao browser cloud.
            ValueError: Se credenciais não estiverem configuradas.
        """
        if not self._config.is_configured:
            raise ValueError(
                "Cloud Browser não configurado. "
                "Defina CLOUD_BROWSER_USERNAME e CLOUD_BROWSER_PASSWORD."
            )

        if not self._playwright:
            self._playwright = await async_playwright().start()

        ws_url = self._config.websocket_url
        # Log sem expor credenciais
        if "@" in ws_url:
            safe_url = ws_url.split("@")[-1]
        elif "token=" in ws_url:
            # Scrapeless: esconder o token
            safe_url = ws_url.split("?")[0] + "?token=***&..."
        else:
            safe_url = ws_url
        logger.info(
            "Conectando ao Cloud Browser: provider=%s, endpoint=%s",
            self._config.provider.value,
            safe_url,
        )

        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(
                ws_url,
                timeout=self._config.timeout_ms,
            )
            logger.info("Cloud Browser conectado com sucesso.")
        except Exception as e:
            logger.error(
                "Falha ao conectar ao Cloud Browser: %s", e
            )
            raise ConnectionError(
                f"Não foi possível conectar ao Cloud Browser "
                f"({self._config.provider.value}): {e}"
            ) from e

        # O Bright Data já fornece um context padrão ao conectar
        # Mas precisamos configurar viewport e locale
        if self._browser.contexts:
            context = self._browser.contexts[0]
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            context = await self._browser.new_context(
                viewport={
                    "width": viewport_width,
                    "height": viewport_height,
                },
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

        # Configurar viewport na page existente
        await page.set_viewport_size(
            {"width": viewport_width, "height": viewport_height}
        )

        logger.info(
            "Cloud Browser pronto: viewport=%dx%d, country=%s",
            viewport_width,
            viewport_height,
            self._config.country,
        )

        return self._browser, context, page

    async def disconnect(self) -> None:
        """Desconecta do browser cloud e limpa recursos."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("Erro ao fechar cloud browser: %s", e)
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning("Erro ao parar playwright: %s", e)
            self._playwright = None

        logger.info("Cloud Browser desconectado.")
