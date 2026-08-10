"""Testes unitários para configuração de cookies do site Giga+ Fibra."""

import pytest

from scraping_resilience.cookie_injector import GeolocationCookieInjector
from scraping_resilience.site_configs.giga_fibra import GIGA_FIBRA_CONFIG


class TestGigaFibraConfig:
    """Testes para a configuração do site Giga+ Fibra."""

    def test_config_possui_nome_do_site(self) -> None:
        """Config contém o nome identificador do site."""
        assert GIGA_FIBRA_CONFIG["name"] == "Giga+ Fibra"

    def test_config_possui_base_url(self) -> None:
        """Config contém a URL base do site."""
        assert (
            GIGA_FIBRA_CONFIG["base_url"]
            == "https://www.gigamaisfibra.com.br"
        )

    def test_config_possui_modal_selector(self) -> None:
        """Config contém seletor para detecção de modal."""
        assert "modal_selector" in GIGA_FIBRA_CONFIG
        assert len(GIGA_FIBRA_CONFIG["modal_selector"]) > 0

    def test_config_possui_5_cookies(self) -> None:
        """Config contém exatamente 5 cookies interdependentes."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        assert len(cookies) == 5

    def test_cookie_plan_city(self) -> None:
        """Cookie PlanCity tem valor 329 (ID de São Paulo)."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        plan_city = next(
            c for c in cookies if c["name"] == "PlanCity"
        )
        assert plan_city["value"] == "329"
        assert plan_city["domain"] == ".gigamaisfibra.com.br"
        assert plan_city["path"] == "/"
        assert plan_city["url_encode"] is False

    def test_cookie_plan_name(self) -> None:
        """Cookie PlanName tem valor São Paulo com url_encode=True."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        plan_name = next(
            c for c in cookies if c["name"] == "PlanName"
        )
        assert plan_name["value"] == "São Paulo"
        assert plan_name["domain"] == ".gigamaisfibra.com.br"
        assert plan_name["path"] == "/"
        assert plan_name["url_encode"] is True

    def test_cookie_plan_region(self) -> None:
        """Cookie PlanRegion tem valor Território 02 com url_encode=True."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        plan_region = next(
            c for c in cookies if c["name"] == "PlanRegion"
        )
        assert plan_region["value"] == "Território 02"
        assert plan_region["domain"] == ".gigamaisfibra.com.br"
        assert plan_region["path"] == "/"
        assert plan_region["url_encode"] is True

    def test_cookie_plan_type(self) -> None:
        """Cookie PlanType tem valor PF com url_encode=False."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        plan_type = next(
            c for c in cookies if c["name"] == "PlanType"
        )
        assert plan_type["value"] == "PF"
        assert plan_type["domain"] == ".gigamaisfibra.com.br"
        assert plan_type["path"] == "/"
        assert plan_type["url_encode"] is False

    def test_cookie_redirect_to_whatsapp(self) -> None:
        """Cookie redirectToWhatsapp tem valor false."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        redirect = next(
            c for c in cookies if c["name"] == "redirectToWhatsapp"
        )
        assert redirect["value"] == "false"
        assert redirect["domain"] == ".gigamaisfibra.com.br"
        assert redirect["path"] == "/"
        assert redirect["url_encode"] is False

    def test_todos_cookies_mesmo_domain(self) -> None:
        """Todos os 5 cookies usam o mesmo domínio."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        for cookie in cookies:
            assert cookie["domain"] == ".gigamaisfibra.com.br"

    def test_todos_cookies_path_raiz(self) -> None:
        """Todos os 5 cookies usam path raiz '/'."""
        cookies = GIGA_FIBRA_CONFIG["geolocation_cookies"]
        for cookie in cookies:
            assert cookie["path"] == "/"

    def test_config_compativel_com_get_cookies_for_site(self) -> None:
        """Config pode ser carregada pelo GeolocationCookieInjector."""
        injector = GeolocationCookieInjector()
        cookies = injector.get_cookies_for_site(GIGA_FIBRA_CONFIG)
        assert len(cookies) == 5
        # Verifica que todos são CookieConfig válidos
        for cookie in cookies:
            assert hasattr(cookie, "name")
            assert hasattr(cookie, "value")
            assert hasattr(cookie, "domain")
            assert hasattr(cookie, "path")
            assert hasattr(cookie, "url_encode")

    def test_encoding_plan_name_gera_valor_correto(self) -> None:
        """PlanName com url_encode=True gera S%C3%A3o%20Paulo."""
        injector = GeolocationCookieInjector()
        cookies = injector.get_cookies_for_site(GIGA_FIBRA_CONFIG)
        plan_name = next(c for c in cookies if c.name == "PlanName")
        prepared = injector.prepare_cookie_for_injection(plan_name)
        assert prepared["value"] == "S%C3%A3o%20Paulo"

    def test_encoding_plan_region_gera_valor_correto(self) -> None:
        """PlanRegion com url_encode=True gera Territ%C3%B3rio%2002."""
        injector = GeolocationCookieInjector()
        cookies = injector.get_cookies_for_site(GIGA_FIBRA_CONFIG)
        plan_region = next(
            c for c in cookies if c.name == "PlanRegion"
        )
        prepared = injector.prepare_cookie_for_injection(plan_region)
        assert prepared["value"] == "Territ%C3%B3rio%2002"
