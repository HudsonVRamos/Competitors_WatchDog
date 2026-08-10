"""Testes unitários para GeolocationCookieInjector - encode/decode."""

import pytest

from scraping_resilience.cookie_injector import GeolocationCookieInjector


class TestEncodeCookieValue:
    """Testes para encode_cookie_value()."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    def test_encode_sao_paulo(self) -> None:
        """Espaço e acento ã são codificados corretamente."""
        result = self.injector.encode_cookie_value("São Paulo")
        assert result == "S%C3%A3o%20Paulo"

    def test_encode_territorio(self) -> None:
        """Acento ó e espaço são codificados corretamente."""
        result = self.injector.encode_cookie_value("Território 06")
        assert result == "Territ%C3%B3rio%2006"

    def test_encode_brasilia_samambaia(self) -> None:
        """Acento í, espaço e parênteses são codificados."""
        result = self.injector.encode_cookie_value(
            "Brasília (Samambaia)"
        )
        assert result == "Bras%C3%ADlia%20%28Samambaia%29"

    def test_encode_ascii_simples(self) -> None:
        """Texto ASCII sem caracteres especiais permanece inalterado."""
        result = self.injector.encode_cookie_value("PF")
        assert result == "PF"

    def test_encode_string_vazia(self) -> None:
        """String vazia retorna string vazia."""
        result = self.injector.encode_cookie_value("")
        assert result == ""

    def test_encode_cedilha(self) -> None:
        """Cedilha (ç) é codificada corretamente."""
        result = self.injector.encode_cookie_value("Ação")
        assert result == "A%C3%A7%C3%A3o"

    def test_encode_numero_puro(self) -> None:
        """Números puros não são alterados."""
        result = self.injector.encode_cookie_value("12345")
        assert result == "12345"


class TestDecodeCookieValue:
    """Testes para decode_cookie_value()."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    def test_decode_sao_paulo(self) -> None:
        """Decodifica São Paulo corretamente."""
        result = self.injector.decode_cookie_value("S%C3%A3o%20Paulo")
        assert result == "São Paulo"

    def test_decode_territorio(self) -> None:
        """Decodifica Território 06 corretamente."""
        result = self.injector.decode_cookie_value(
            "Territ%C3%B3rio%2006"
        )
        assert result == "Território 06"

    def test_decode_brasilia_samambaia(self) -> None:
        """Decodifica Brasília (Samambaia) corretamente."""
        result = self.injector.decode_cookie_value(
            "Bras%C3%ADlia%20%28Samambaia%29"
        )
        assert result == "Brasília (Samambaia)"

    def test_decode_string_sem_encoding(self) -> None:
        """String sem percent-encoding retorna inalterada."""
        result = self.injector.decode_cookie_value("PF")
        assert result == "PF"

    def test_decode_string_vazia(self) -> None:
        """String vazia retorna string vazia."""
        result = self.injector.decode_cookie_value("")
        assert result == ""

    def test_roundtrip_encode_decode(self) -> None:
        """Encode seguido de decode retorna o valor original."""
        original = "São Paulo (Centro)"
        encoded = self.injector.encode_cookie_value(original)
        decoded = self.injector.decode_cookie_value(encoded)
        assert decoded == original


class TestPrepareCookieForInjection:
    """Testes para prepare_cookie_for_injection()."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    def test_cookie_sem_encoding(self) -> None:
        """Cookie com url_encode=False retorna value inalterado."""
        from scraping_resilience.models import CookieConfig

        cookie = CookieConfig(
            name="city",
            value="São Paulo",
            domain=".example.com",
            path="/",
            url_encode=False,
        )
        result = self.injector.prepare_cookie_for_injection(cookie)
        assert result == {
            "name": "city",
            "value": "São Paulo",
            "domain": ".example.com",
            "path": "/",
        }

    def test_cookie_com_encoding(self) -> None:
        """Cookie com url_encode=True aplica percent-encoding ao value."""
        from scraping_resilience.models import CookieConfig

        cookie = CookieConfig(
            name="region",
            value="São Paulo",
            domain=".gigamaisfibra.com.br",
            path="/planos",
            url_encode=True,
        )
        result = self.injector.prepare_cookie_for_injection(cookie)
        assert result == {
            "name": "region",
            "value": "S%C3%A3o%20Paulo",
            "domain": ".gigamaisfibra.com.br",
            "path": "/planos",
        }

    def test_retorna_todas_as_chaves_esperadas(self) -> None:
        """Dict retornado contém exatamente name, value, domain, path."""
        from scraping_resilience.models import CookieConfig

        cookie = CookieConfig(
            name="loc",
            value="RJ",
            domain=".site.com",
        )
        result = self.injector.prepare_cookie_for_injection(cookie)
        assert set(result.keys()) == {"name", "value", "domain", "path"}

    def test_path_padrao_quando_nao_especificado(self) -> None:
        """CookieConfig com path padrão '/' é refletido no dict."""
        from scraping_resilience.models import CookieConfig

        cookie = CookieConfig(
            name="geo",
            value="BR",
            domain=".teste.com",
        )
        result = self.injector.prepare_cookie_for_injection(cookie)
        assert result["path"] == "/"

    def test_encoding_com_parenteses_e_cedilha(self) -> None:
        """Valores complexos com parênteses e cedilha são encodados."""
        from scraping_resilience.models import CookieConfig

        cookie = CookieConfig(
            name="cidade",
            value="Ação (teste)",
            domain=".dom.com",
            url_encode=True,
        )
        result = self.injector.prepare_cookie_for_injection(cookie)
        assert "%" in result["value"]
        assert result["name"] == "cidade"


class TestGetCookiesForSite:
    """Testes para get_cookies_for_site()."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    def test_retorna_lista_vazia_sem_config(self) -> None:
        """Site sem geolocation_cookies retorna lista vazia."""
        site_config: dict = {"url": "https://example.com"}
        result = self.injector.get_cookies_for_site(site_config)
        assert result == []

    def test_retorna_lista_vazia_com_lista_vazia(self) -> None:
        """Site com geolocation_cookies=[] retorna lista vazia."""
        site_config: dict = {"geolocation_cookies": []}
        result = self.injector.get_cookies_for_site(site_config)
        assert result == []

    def test_retorna_cookie_unico(self) -> None:
        """Site com um cookie configurado retorna lista com 1 item."""
        from scraping_resilience.models import CookieConfig

        site_config: dict = {
            "geolocation_cookies": [
                {
                    "name": "city",
                    "value": "São Paulo",
                    "domain": ".giga.com.br",
                }
            ]
        }
        result = self.injector.get_cookies_for_site(site_config)
        assert len(result) == 1
        assert isinstance(result[0], CookieConfig)
        assert result[0].name == "city"
        assert result[0].value == "São Paulo"
        assert result[0].domain == ".giga.com.br"
        assert result[0].path == "/"
        assert result[0].url_encode is False

    def test_retorna_multiplos_cookies(self) -> None:
        """Site com múltiplos cookies retorna lista completa."""
        site_config: dict = {
            "geolocation_cookies": [
                {
                    "name": "city",
                    "value": "São Paulo",
                    "domain": ".site.com",
                },
                {
                    "name": "state",
                    "value": "SP",
                    "domain": ".site.com",
                    "path": "/loja",
                    "url_encode": True,
                },
            ]
        }
        result = self.injector.get_cookies_for_site(site_config)
        assert len(result) == 2
        assert result[1].name == "state"
        assert result[1].path == "/loja"
        assert result[1].url_encode is True

    def test_path_padrao_quando_ausente(self) -> None:
        """Cookie sem path no dict usa '/' como padrão."""
        site_config: dict = {
            "geolocation_cookies": [
                {
                    "name": "loc",
                    "value": "RJ",
                    "domain": ".dom.com",
                }
            ]
        }
        result = self.injector.get_cookies_for_site(site_config)
        assert result[0].path == "/"

    def test_url_encode_padrao_false(self) -> None:
        """Cookie sem url_encode no dict usa False como padrão."""
        site_config: dict = {
            "geolocation_cookies": [
                {
                    "name": "loc",
                    "value": "RJ",
                    "domain": ".dom.com",
                }
            ]
        }
        result = self.injector.get_cookies_for_site(site_config)
        assert result[0].url_encode is False


class TestInjectCookies:
    """Testes para inject_cookies() — método async."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    @pytest.mark.asyncio
    async def test_retorna_nao_injetado_quando_sem_cookies(self) -> None:
        """Site sem cookies configurados retorna cookies_injected=False."""
        from unittest.mock import AsyncMock

        browser_context = AsyncMock()
        site_config: dict = {"url": "https://example.com"}

        result = await self.injector.inject_cookies(browser_context, site_config)

        assert result.cookies_injected is False
        assert result.cookies_count == 0
        browser_context.add_cookies.assert_not_called()

    @pytest.mark.asyncio
    async def test_injeta_cookie_unico(self) -> None:
        """Injeta um cookie e retorna contagem correta."""
        from unittest.mock import AsyncMock

        browser_context = AsyncMock()
        site_config: dict = {
            "geolocation_cookies": [
                {
                    "name": "PlanType",
                    "value": "PF",
                    "domain": ".gigamaisfibra.com.br",
                }
            ]
        }

        result = await self.injector.inject_cookies(browser_context, site_config)

        assert result.cookies_injected is True
        assert result.cookies_count == 1
        browser_context.add_cookies.assert_called_once()
        cookies_arg = browser_context.add_cookies.call_args[0][0]
        assert len(cookies_arg) == 1
        assert cookies_arg[0]["name"] == "PlanType"
        assert cookies_arg[0]["value"] == "PF"

    @pytest.mark.asyncio
    async def test_injeta_multiplos_cookies_interdependentes(self) -> None:
        """Injeta 5 cookies da Giga+ Fibra e chama add_cookies uma vez."""
        from unittest.mock import AsyncMock

        browser_context = AsyncMock()
        site_config: dict = {
            "geolocation_cookies": [
                {"name": "PlanCity", "value": "499", "domain": ".gigamaisfibra.com.br"},
                {"name": "PlanName", "value": "São Paulo", "domain": ".gigamaisfibra.com.br", "url_encode": True},
                {"name": "PlanRegion", "value": "Território 06", "domain": ".gigamaisfibra.com.br", "url_encode": True},
                {"name": "PlanType", "value": "PF", "domain": ".gigamaisfibra.com.br"},
                {"name": "redirectToWhatsapp", "value": "false", "domain": ".gigamaisfibra.com.br"},
            ]
        }

        result = await self.injector.inject_cookies(browser_context, site_config)

        assert result.cookies_injected is True
        assert result.cookies_count == 5
        browser_context.add_cookies.assert_called_once()
        cookies_arg = browser_context.add_cookies.call_args[0][0]
        assert len(cookies_arg) == 5

    @pytest.mark.asyncio
    async def test_aplica_url_encoding_nos_cookies_configurados(self) -> None:
        """Cookies com url_encode=True têm valores encoded no dict final."""
        from unittest.mock import AsyncMock

        browser_context = AsyncMock()
        site_config: dict = {
            "geolocation_cookies": [
                {"name": "PlanName", "value": "São Paulo", "domain": ".giga.com.br", "url_encode": True},
                {"name": "PlanType", "value": "PF", "domain": ".giga.com.br", "url_encode": False},
            ]
        }

        await self.injector.inject_cookies(browser_context, site_config)

        cookies_arg = browser_context.add_cookies.call_args[0][0]
        assert cookies_arg[0]["value"] == "S%C3%A3o%20Paulo"
        assert cookies_arg[1]["value"] == "PF"

    @pytest.mark.asyncio
    async def test_retorna_lista_vazia_quando_geolocation_cookies_vazio(self) -> None:
        """Site com geolocation_cookies=[] retorna não injetado."""
        from unittest.mock import AsyncMock

        browser_context = AsyncMock()
        site_config: dict = {"geolocation_cookies": []}

        result = await self.injector.inject_cookies(browser_context, site_config)

        assert result.cookies_injected is False
        assert result.cookies_count == 0
        browser_context.add_cookies.assert_not_called()


class TestVerifyModalSuppressed:
    """Testes para verify_modal_suppressed() — método async."""

    def setup_method(self) -> None:
        self.injector = GeolocationCookieInjector()

    @pytest.mark.asyncio
    async def test_retorna_true_quando_modal_nao_aparece(self) -> None:
        """Modal não apareceu (timeout) = cookie funcionou = retorna True."""
        from unittest.mock import AsyncMock

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 5000ms exceeded.")
        )

        result = await self.injector.verify_modal_suppressed(
            page, "#modal-localizacao"
        )

        assert result is True
        page.wait_for_selector.assert_called_once_with(
            "#modal-localizacao", timeout=5_000, state="visible"
        )

    @pytest.mark.asyncio
    async def test_retorna_false_quando_modal_aparece(self) -> None:
        """Modal apareceu (seletor encontrado) = fallback necessário = retorna False."""
        from unittest.mock import AsyncMock, MagicMock

        page = AsyncMock()
        # Simula que wait_for_selector encontrou o modal (retorna o elemento)
        page.wait_for_selector = AsyncMock(return_value=MagicMock())

        result = await self.injector.verify_modal_suppressed(
            page, ".location-modal"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_respeita_timeout_customizado(self) -> None:
        """Timeout customizado é passado para wait_for_selector."""
        from unittest.mock import AsyncMock

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 10000ms exceeded.")
        )

        await self.injector.verify_modal_suppressed(
            page, "#modal", timeout_ms=10_000
        )

        page.wait_for_selector.assert_called_once_with(
            "#modal", timeout=10_000, state="visible"
        )

    @pytest.mark.asyncio
    async def test_timeout_padrao_5000ms(self) -> None:
        """Sem timeout explícito, usa 5000ms como padrão."""
        from unittest.mock import AsyncMock

        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError("Timeout 5000ms exceeded.")
        )

        await self.injector.verify_modal_suppressed(page, ".modal-geo")

        page.wait_for_selector.assert_called_once_with(
            ".modal-geo", timeout=5_000, state="visible"
        )
