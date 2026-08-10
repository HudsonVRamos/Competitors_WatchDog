"""GeolocationCookieInjector - Injeta cookies de geolocalização pré-navegação.

Injeta cookies de geolocalização no contexto do browser ANTES da navegação
para contornar popups de seleção de cidade/região.

Suporta:
- Múltiplos cookies interdependentes por site (ex: Giga+ Fibra usa 5 cookies)
- URL-encoding automático (percent-encoding) para valores especiais
- Verificação de supressão de modal após page load
- Fallback para Cascade Strategy quando cookie não suprime modal
"""

from __future__ import annotations

import logging
from urllib.parse import quote, unquote

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scraping_resilience.models import CookieConfig, CookieInjectionResult

logger = logging.getLogger(__name__)


class GeolocationCookieInjector:
    """Injeta cookies de geolocalização antes da navegação.

    Suporta múltiplos cookies interdependentes (ex: Giga+ Fibra usa 5 cookies
    que trabalham em conjunto) e aplica URL-encoding quando
    CookieConfig.url_encode=True.
    """

    def encode_cookie_value(self, value: str) -> str:
        """Aplica URL-encoding (percent-encoding) ao valor do cookie.

        Usa urllib.parse.quote() com safe="" para codificar todos os
        caracteres especiais incluindo espaços, acentos, parênteses
        e cedilhas.

        Exemplos:
            "São Paulo" → "S%C3%A3o%20Paulo"
            "Território 06" → "Territ%C3%B3rio%2006"
            "Brasília (Samambaia)" → "Bras%C3%ADlia%20%28Samambaia%29"
        """
        return quote(value, safe="")

    def decode_cookie_value(self, encoded_value: str) -> str:
        """Decodifica valor de cookie URL-encoded de volta ao texto original.

        Usa urllib.parse.unquote() para reverter o encoding.

        Exemplos:
            "S%C3%A3o%20Paulo" → "São Paulo"
            "Territ%C3%B3rio%2006" → "Território 06"
        """
        return unquote(encoded_value)

    def get_cookies_for_site(
        self, site_config: dict
    ) -> list[CookieConfig]:
        """Retorna lista de cookies configurados para o site.

        Espera que site_config tenha uma chave 'geolocation_cookies'
        com lista de dicts contendo name, value, domain, path (opcional)
        e url_encode (opcional).
        Returns lista vazia se nenhum cookie está configurado.
        """
        cookies_data = site_config.get("geolocation_cookies", [])
        cookies = []
        for cookie_data in cookies_data:
            cookies.append(CookieConfig(
                name=cookie_data["name"],
                value=cookie_data["value"],
                domain=cookie_data["domain"],
                path=cookie_data.get("path", "/"),
                url_encode=cookie_data.get("url_encode", False),
            ))
        return cookies

    def prepare_cookie_for_injection(
        self, cookie_config: CookieConfig
    ) -> dict[str, str]:
        """Prepara um CookieConfig para injeção no Playwright.

        Se cookie_config.url_encode=True, aplica encoding ao value.
        Retorna dict no formato esperado por browser_context.add_cookies().

        Returns:
            {"name": ..., "value": ..., "domain": ..., "path": ...}
        """
        value = cookie_config.value
        if cookie_config.url_encode:
            value = self.encode_cookie_value(value)
        return {
            "name": cookie_config.name,
            "value": value,
            "domain": cookie_config.domain,
            "path": cookie_config.path,
        }

    async def inject_cookies(
        self,
        browser_context: BrowserContext,
        site_config: dict,
    ) -> CookieInjectionResult:
        """Injeta Geolocation_Cookies configurados no browser context.

        DEVE ser chamado ANTES de page.goto().
        Para cada cookie configurado:
        1. Se url_encode=True, aplica urllib.parse.quote() ao value
        2. Adiciona o cookie via browser_context.add_cookies()

        Returns:
            CookieInjectionResult com status da injeção e contagem.
        """
        cookies = self.get_cookies_for_site(site_config)
        if not cookies:
            logger.debug("Nenhum cookie de geolocalização configurado para o site.")
            return CookieInjectionResult(
                cookies_injected=False, cookies_count=0
            )

        prepared_cookies = []
        for cookie_config in cookies:
            prepared = self.prepare_cookie_for_injection(cookie_config)
            prepared_cookies.append(prepared)

        await browser_context.add_cookies(prepared_cookies)
        logger.info(
            "Cookies de geolocalização injetados: %d cookie(s).",
            len(prepared_cookies),
        )

        return CookieInjectionResult(
            cookies_injected=True,
            cookies_count=len(prepared_cookies),
        )

    async def verify_modal_suppressed(
        self,
        page: Page,
        modal_selector: str,
        timeout_ms: int = 5_000,
    ) -> bool:
        """Verifica se o modal de localização foi suprimido após page load.

        Aguarda brevemente e verifica se o modal NÃO aparece.
        Returns True se modal foi suprimido (cookie funcionou).
        Returns False se modal apareceu (precisa fallback).
        """
        try:
            await page.wait_for_selector(
                modal_selector, timeout=timeout_ms, state="visible"
            )
            # Modal apareceu — cookie não suprimiu
            logger.info(
                "Modal de localização detectado (seletor: %s). Fallback necessário.",
                modal_selector,
            )
            return False
        except PlaywrightTimeoutError:
            # Modal NÃO apareceu dentro do timeout — cookie funcionou
            logger.info(
                "Modal de localização NÃO apareceu (seletor: %s). Cookie suprimiu com sucesso.",
                modal_selector,
            )
            return True
