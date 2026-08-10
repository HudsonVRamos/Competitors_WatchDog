"""Testes unitários para GigaFibraFlow — cookie injection + fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraping_resilience.competitor_flows.giga_fibra import (
    GigaFibraFlow,
    PLANS_LOADED_SELECTOR,
)
from scraping_resilience.models import (
    CookieInjectionResult,
    InteractionResult,
    ComponentType,
)


@pytest.fixture
def cookie_injector():
    """Mock do GeolocationCookieInjector."""
    injector = AsyncMock()
    injector.inject_cookies = AsyncMock(
        return_value=CookieInjectionResult(
            cookies_injected=True, cookies_count=5
        )
    )
    injector.verify_modal_suppressed = AsyncMock(return_value=True)
    return injector


@pytest.fixture
def component_interactor():
    """Mock do CustomComponentInteractor."""
    interactor = AsyncMock()
    interactor.interact = AsyncMock(
        return_value=InteractionResult(
            success=True,
            strategy_used="native_select",
            component_type=ComponentType.NATIVE_SELECT,
        )
    )
    return interactor


@pytest.fixture
def screenshotter():
    """Mock do StepScreenshotter."""
    ss = AsyncMock()
    ss.capture = AsyncMock(return_value="s3-key/screenshot.png")
    return ss


@pytest.fixture
def browser_context():
    """Mock do BrowserContext."""
    return AsyncMock()


@pytest.fixture
def page():
    """Mock da Page Playwright."""
    p = AsyncMock()
    p.wait_for_selector = AsyncMock(return_value=MagicMock())
    return p


@pytest.fixture
def flow(cookie_injector, component_interactor, screenshotter):
    """Instância do GigaFibraFlow com mocks."""
    return GigaFibraFlow(
        cookie_injector=cookie_injector,
        component_interactor=component_interactor,
        screenshotter=screenshotter,
    )


class TestGigaFibraFlowCookieInjection:
    """Testes para injeção de cookies ANTES da navegação."""

    @pytest.mark.asyncio
    async def test_injeta_cookies_usando_config_giga_fibra(
        self, flow, cookie_injector, browser_context, page
    ):
        """Cookies são injetados usando GIGA_FIBRA_CONFIG."""
        await flow.execute(browser_context, page)

        cookie_injector.inject_cookies.assert_called_once()
        call_args = cookie_injector.inject_cookies.call_args
        # Primeiro argumento = browser_context
        assert call_args[0][0] is browser_context
        # Segundo argumento = site config (deve ser GIGA_FIBRA_CONFIG)
        config_used = call_args[0][1]
        assert config_used["name"] == "Giga+ Fibra"
        assert len(config_used["geolocation_cookies"]) == 5

    @pytest.mark.asyncio
    async def test_cookies_injetados_antes_de_verificar_modal(
        self, flow, cookie_injector, browser_context, page
    ):
        """inject_cookies é chamado antes de verify_modal_suppressed."""
        call_order = []

        async def track_inject(*args, **kwargs):
            call_order.append("inject_cookies")
            return CookieInjectionResult(
                cookies_injected=True, cookies_count=5
            )

        async def track_verify(*args, **kwargs):
            call_order.append("verify_modal_suppressed")
            return True

        cookie_injector.inject_cookies = AsyncMock(
            side_effect=track_inject
        )
        cookie_injector.verify_modal_suppressed = AsyncMock(
            side_effect=track_verify
        )

        await flow.execute(browser_context, page)

        assert call_order == [
            "inject_cookies",
            "verify_modal_suppressed",
        ]

    @pytest.mark.asyncio
    async def test_resultado_contagem_cookies(
        self, flow, cookie_injector, browser_context, page
    ):
        """O resultado da injeção reflete 5 cookies injetados."""
        cookie_injector.inject_cookies = AsyncMock(
            return_value=CookieInjectionResult(
                cookies_injected=True, cookies_count=5
            )
        )

        result = await flow.execute(browser_context, page)
        assert result["success"] is True


class TestGigaFibraFlowModalSuppressed:
    """Testes para cenário onde cookie suprimiu o modal."""

    @pytest.mark.asyncio
    async def test_modal_suprimido_prossegue_sem_interacao(
        self, flow, cookie_injector, component_interactor,
        browser_context, page
    ):
        """Quando modal suprimido, NÃO usa Cascade Strategy."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )

        result = await flow.execute(browser_context, page)

        assert result["success"] is True
        assert result["modal_suppressed"] is True
        assert result["fallback_used"] is False
        component_interactor.interact.assert_not_called()

    @pytest.mark.asyncio
    async def test_modal_suprimido_captura_screenshot(
        self, flow, cookie_injector, screenshotter,
        browser_context, page
    ):
        """Screenshot capturado com descrição correta quando sucesso."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )

        await flow.execute(browser_context, page)

        # Verifica que capture foi chamado com a descrição correta
        screenshotter.capture.assert_called()
        descriptions = [
            call.args[1]
            for call in screenshotter.capture.call_args_list
        ]
        assert "after_cookie_injection_success" in descriptions


class TestGigaFibraFlowFallback:
    """Testes para cenário onde modal apareceu (fallback necessário)."""

    @pytest.mark.asyncio
    async def test_modal_detectado_usa_cascade_strategy(
        self, flow, cookie_injector, component_interactor,
        browser_context, page
    ):
        """Quando modal aparece, invoca Cascade Strategy como fallback."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )

        result = await flow.execute(browser_context, page)

        assert result["fallback_used"] is True
        component_interactor.interact.assert_called_once()

    @pytest.mark.asyncio
    async def test_cascade_strategy_recebe_sao_paulo(
        self, flow, cookie_injector, component_interactor,
        browser_context, page
    ):
        """Cascade Strategy tenta selecionar 'São Paulo'."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )

        await flow.execute(browser_context, page)

        call_kwargs = component_interactor.interact.call_args
        assert call_kwargs.kwargs["desired_value"] == "São Paulo"

    @pytest.mark.asyncio
    async def test_cascade_strategy_usa_modal_selector(
        self, flow, cookie_injector, component_interactor,
        browser_context, page
    ):
        """Cascade Strategy usa o modal_selector da config."""
        from scraping_resilience.site_configs.giga_fibra import (
            GIGA_FIBRA_CONFIG,
        )

        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )

        await flow.execute(browser_context, page)

        call_args = component_interactor.interact.call_args
        assert call_args[0][1] == GIGA_FIBRA_CONFIG["modal_selector"]

    @pytest.mark.asyncio
    async def test_cascade_falha_retorna_erro(
        self, flow, cookie_injector, component_interactor,
        browser_context, page
    ):
        """Se Cascade Strategy falhar, retorna success=False com erro."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )
        component_interactor.interact = AsyncMock(
            return_value=InteractionResult(
                success=False,
                strategy_used="all",
                component_type=ComponentType.UNKNOWN,
                error="custom_dropdown_interaction_failed",
            )
        )

        result = await flow.execute(browser_context, page)

        assert result["success"] is False
        assert result["error"] == "custom_dropdown_interaction_failed"
        assert result["fallback_used"] is True

    @pytest.mark.asyncio
    async def test_fallback_captura_screenshots(
        self, flow, cookie_injector, component_interactor,
        screenshotter, browser_context, page
    ):
        """Fallback captura screenshots antes e depois da interação."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )

        await flow.execute(browser_context, page)

        descriptions = [
            call.args[1]
            for call in screenshotter.capture.call_args_list
        ]
        assert "modal_detected" in descriptions
        assert "after_dropdown_interaction" in descriptions


class TestGigaFibraFlowPlansValidation:
    """Testes para validação de planos carregados."""

    @pytest.mark.asyncio
    async def test_plans_loaded_true_quando_selector_encontrado(
        self, flow, cookie_injector, browser_context, page
    ):
        """plans_loaded=True quando elementos de plano são encontrados."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )
        # page.wait_for_selector retorna um elemento (planos carregados)
        page.wait_for_selector = AsyncMock(
            return_value=MagicMock()
        )

        result = await flow.execute(browser_context, page)

        assert result["plans_loaded"] is True

    @pytest.mark.asyncio
    async def test_plans_loaded_false_quando_timeout(
        self, flow, cookie_injector, browser_context, page
    ):
        """plans_loaded=False quando nenhum plano encontrado (timeout)."""
        from playwright.async_api import (
            TimeoutError as PlaywrightTimeoutError,
        )

        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError(
                "Timeout 10000ms exceeded."
            )
        )

        result = await flow.execute(browser_context, page)

        assert result["success"] is True
        assert result["plans_loaded"] is False

    @pytest.mark.asyncio
    async def test_plans_validation_usa_selector_correto(
        self, flow, cookie_injector, browser_context, page
    ):
        """Validação de planos usa o PLANS_LOADED_SELECTOR."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )

        await flow.execute(browser_context, page)

        # Verificar que wait_for_selector foi chamado com o seletor
        page.wait_for_selector.assert_called_with(
            PLANS_LOADED_SELECTOR,
            timeout=10_000,
            state="visible",
        )


class TestGigaFibraFlowIntegration:
    """Testes que validam o fluxo completo end-to-end com mocks."""

    @pytest.mark.asyncio
    async def test_fluxo_completo_modal_suprimido(
        self, flow, cookie_injector, component_interactor,
        screenshotter, browser_context, page
    ):
        """Fluxo completo quando cookie suprime modal com sucesso."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )

        result = await flow.execute(browser_context, page)

        # Verifica resultado final
        assert result == {
            "success": True,
            "modal_suppressed": True,
            "fallback_used": False,
            "plans_loaded": True,
        }

        # Verifica que Cascade Strategy NÃO foi chamada
        component_interactor.interact.assert_not_called()

        # Verifica que pelo menos 1 screenshot foi capturado
        assert screenshotter.capture.call_count >= 1

    @pytest.mark.asyncio
    async def test_fluxo_completo_fallback_sucesso(
        self, flow, cookie_injector, component_interactor,
        screenshotter, browser_context, page
    ):
        """Fluxo completo quando fallback resolve o modal."""
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )
        component_interactor.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
            )
        )

        result = await flow.execute(browser_context, page)

        assert result == {
            "success": True,
            "modal_suppressed": False,
            "fallback_used": True,
            "plans_loaded": True,
        }

        # Verifica que Cascade Strategy FOI chamada
        component_interactor.interact.assert_called_once()

        # Verifica screenshots: modal_detected + after_dropdown_interaction
        assert screenshotter.capture.call_count >= 2
