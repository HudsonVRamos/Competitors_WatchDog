"""Testes de integração para fluxos completos de scraping resilience.

Valida que os módulos funcionam corretamente em conjunto, testando
os fluxos end-to-end para cada concorrente com mocks de dependências
externas (Playwright page, S3).

Requirements: 6.1, 7.1, 8.2, 9.2, 11.4, 11.5
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scraping_resilience.component_interactor import CustomComponentInteractor
from scraping_resilience.content_validator import ContentValidator
from scraping_resilience.cookie_injector import GeolocationCookieInjector
from scraping_resilience.diagnostics_collector import DiagnosticsCollector
from scraping_resilience.health_check_scorer import HealthCheckScorer
from scraping_resilience.intelligent_wait import IntelligentWaitManager
from scraping_resilience.models import (
    ComponentType,
    ContentValidationResult,
    CookieInjectionResult,
    HealthCheckScore,
    InteractionResult,
)
from scraping_resilience.step_screenshotter import StepScreenshotter

# Fluxos de concorrentes
from scraping_resilience.competitor_flows.giga_fibra import GigaFibraFlow
from scraping_resilience.competitor_flows.netflix import NetflixFlow
from scraping_resilience.competitor_flows.paramount import ParamountFlow
from scraping_resilience.competitor_flows.vivo_tv import VivoTVFlow

# Região e bucket padrão para testes
TEST_REGION = "us-east-1"
TEST_BUCKET = "price-watchdog-diagnostics-test"
TEST_SCREENSHOTS_BUCKET = "price-watchdog-screenshots-test"


@pytest.fixture(autouse=True)
def aws_credentials():
    """Configura credenciais fake para moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = TEST_REGION
    yield


def _mock_page(
    url: str = "https://example.com",
    body_text: str = "",
    title: str = "Test Page",
) -> AsyncMock:
    """Cria mock de Playwright Page com comportamento padrão.

    Args:
        url: URL retornada por page.url.
        body_text: Texto retornado por page.inner_text("body").
        title: Título retornado por page.title().

    Returns:
        AsyncMock configurado como Page do Playwright.
    """
    page = AsyncMock()
    page.url = url
    page.title = AsyncMock(return_value=title)
    page.inner_text = AsyncMock(return_value=body_text)
    page.content = AsyncMock(
        return_value=f"<html><body>{body_text}</body></html>"
    )
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\nfakedata")
    page.evaluate = AsyncMock(return_value=[])
    page.wait_for_selector = AsyncMock(return_value=None)

    # Locator mock para tabs e seletores
    locator_mock = AsyncMock()
    locator_mock.count = AsyncMock(return_value=0)
    locator_mock.first = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)
    page.get_by_text = MagicMock(return_value=locator_mock)

    return page


def _mock_page_with_tabs(tab_plans: dict[str, list[dict]]) -> AsyncMock:
    """Cria mock de Page que simula navegação de tabs Vivo TV.

    Args:
        tab_plans: Dict mapeando nome da tab para lista de planos.
            Ex: {"TV Online": [{"name": "Plano 1"}]}

    Returns:
        AsyncMock que simula clique em tabs e mudança de conteúdo.
    """
    page = _mock_page(url="https://www.vivo.com.br/tv")
    current_tab = {"name": None}

    def make_tab_locator(tab_name):
        """Cria locator mock para uma tab específica."""
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=1)
        loc.first = AsyncMock()
        loc.first.click = AsyncMock()
        return loc

    def get_by_text_side_effect(text, **kwargs):
        loc = make_tab_locator(text)
        current_tab["name"] = text
        return loc

    page.get_by_text = MagicMock(side_effect=get_by_text_side_effect)

    # Simular locator que retorna planos baseado na tab atual
    def locator_side_effect(selector):
        tab = current_tab["name"]
        plans = tab_plans.get(tab, [])
        loc = AsyncMock()
        loc.count = AsyncMock(return_value=len(plans))

        for i, plan in enumerate(plans):
            nth_mock = AsyncMock()
            nth_mock.inner_text = AsyncMock(
                return_value=plan.get("name", f"Plano {i}")
            )
            loc.nth = MagicMock(return_value=nth_mock)
        return loc

    page.locator = MagicMock(side_effect=locator_side_effect)
    return page


class TestVivoTVIntegration:
    """Testes de integração para Vivo TV: 3 tabs navegadas com sucesso.

    Valida o fluxo completo de navegação de tabs:
    1. Localiza cada tab pelo texto
    2. Clica na tab
    3. Aguarda mudança de conteúdo
    4. Captura screenshot
    5. Extrai planos
    6. Consolida resultados sem duplicatas

    Validates: Requirements 6.1
    """

    @pytest.mark.asyncio
    async def test_three_tabs_navigated_successfully(self):
        """Navega pelas 3 tabs e consolida planos de todas."""
        # Configurar page mock com tabs e planos distintos
        tab_plans = {
            "TV Online": [{"name": "Plano Start"}],
            "TV por Assinatura": [{"name": "Plano Premium"}],
            "Vivo Fibra + TV": [{"name": "Plano Combo"}],
        }
        page = _mock_page_with_tabs(tab_plans)

        # Mock do wait_manager que sempre indica mudança de conteúdo
        wait_manager = AsyncMock(spec=IntelligentWaitManager)
        wait_manager.wait_for_content_change = AsyncMock(
            return_value=True
        )

        # Mock do screenshotter que sempre tem sucesso
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(
            return_value="vivo/cycle-1/step_001_tab.png"
        )

        # Executar fluxo
        flow = VivoTVFlow(wait_manager, screenshotter)
        result = await flow.navigate_tabs(page)

        # Verificar que 3 tabs foram processadas
        assert wait_manager.wait_for_content_change.call_count == 3
        assert screenshotter.capture.call_count == 3

        # Verificar planos consolidados
        assert len(result) == 3
        plan_names = [p["name"] for p in result]
        assert "Plano Start" in plan_names
        assert "Plano Premium" in plan_names
        assert "Plano Combo" in plan_names

    @pytest.mark.asyncio
    async def test_tab_not_found_continues_to_next(self):
        """Se uma tab não for encontrada, prossegue para a próxima."""
        page = _mock_page(url="https://www.vivo.com.br/tv")

        # Apenas uma tab encontrada (TV Online)

        def get_by_text_side_effect(text, **kwargs):
            loc = AsyncMock()
            if text == "TV Online":
                loc.count = AsyncMock(return_value=1)
                loc.first = AsyncMock()
                loc.first.click = AsyncMock()
            else:
                loc.count = AsyncMock(return_value=0)
            return loc

        page.get_by_text = MagicMock(
            side_effect=get_by_text_side_effect
        )

        # Locator para planos retorna 1 plano
        plan_loc = AsyncMock()
        plan_loc.count = AsyncMock(return_value=1)
        nth_mock = AsyncMock()
        nth_mock.inner_text = AsyncMock(return_value="Plano Online")
        plan_loc.nth = MagicMock(return_value=nth_mock)
        page.locator = MagicMock(return_value=plan_loc)

        wait_manager = AsyncMock(spec=IntelligentWaitManager)
        wait_manager.wait_for_content_change = AsyncMock(
            return_value=True
        )

        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = VivoTVFlow(wait_manager, screenshotter)
        result = await flow.navigate_tabs(page)

        # Apenas 1 tab processada, mas fluxo não falhou
        assert len(result) >= 1
        assert result[0]["name"] == "Plano Online"

    @pytest.mark.asyncio
    async def test_deduplication_removes_duplicates(self):
        """Planos duplicados entre tabs são removidos na consolidação."""
        page = _mock_page(url="https://www.vivo.com.br/tv")

        # Todas as tabs retornam o mesmo plano
        def get_by_text_side_effect(text, **kwargs):
            loc = AsyncMock()
            loc.count = AsyncMock(return_value=1)
            loc.first = AsyncMock()
            loc.first.click = AsyncMock()
            return loc

        page.get_by_text = MagicMock(
            side_effect=get_by_text_side_effect
        )

        plan_loc = AsyncMock()
        plan_loc.count = AsyncMock(return_value=1)
        nth_mock = AsyncMock()
        nth_mock.inner_text = AsyncMock(return_value="Plano Duplicado")
        plan_loc.nth = MagicMock(return_value=nth_mock)
        page.locator = MagicMock(return_value=plan_loc)

        wait_manager = AsyncMock(spec=IntelligentWaitManager)
        wait_manager.wait_for_content_change = AsyncMock(
            return_value=True
        )

        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = VivoTVFlow(wait_manager, screenshotter)
        result = await flow.navigate_tabs(page)

        # Deve retornar apenas 1 plano (deduplicado)
        assert len(result) == 1
        assert result[0]["name"] == "Plano Duplicado"


class TestGigaFibraCookieInjectionSuccess:
    """Testes de integração para Giga+ Fibra: cookie injection bem-sucedido.

    Valida que quando os cookies suprimem o modal de localização,
    o fluxo prossegue diretamente para extração sem usar Cascade Strategy.

    Validates: Requirements 7.1, 11.4, 11.5
    """

    @pytest.mark.asyncio
    async def test_modal_suppressed_skips_cascade(self):
        """Cookie injection suprime modal → extração direta sem dropdown."""
        page = _mock_page(
            url="https://www.gigamaisfibra.com.br/planos"
        )

        # Mock do cookie_injector: injeção bem-sucedida
        cookie_injector = AsyncMock(spec=GeolocationCookieInjector)
        cookie_injector.inject_cookies = AsyncMock(
            return_value=CookieInjectionResult(
                cookies_injected=True,
                cookies_count=5,
            )
        )
        # Modal NÃO apareceu (cookie funcionou)
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=True
        )

        # Mock do component_interactor (não deve ser chamado)
        component_interactor = AsyncMock(
            spec=CustomComponentInteractor
        )

        # Mock do screenshotter
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(
            return_value="giga/cycle-1/step_001.png"
        )

        # Mock browser context
        browser_context = AsyncMock()

        flow = GigaFibraFlow(
            cookie_injector, component_interactor, screenshotter
        )

        # page.wait_for_selector simula que planos estão carregados
        page.wait_for_selector = AsyncMock(return_value=True)

        result = await flow.execute(browser_context, page)

        # Verificar resultado
        assert result["success"] is True
        assert result["modal_suppressed"] is True
        assert result["fallback_used"] is False
        assert result["plans_loaded"] is True

        # Cookie injector foi chamado
        cookie_injector.inject_cookies.assert_called_once()
        cookie_injector.verify_modal_suppressed.assert_called_once()

        # Cascade Strategy NÃO foi invocada
        component_interactor.interact.assert_not_called()

        # Screenshot de sucesso capturado
        screenshotter.capture.assert_called()

    @pytest.mark.asyncio
    async def test_five_cookies_injected(self):
        """Verifica que 5 cookies interdependentes são injetados."""
        from scraping_resilience.site_configs.giga_fibra import (
            GIGA_FIBRA_CONFIG,
        )

        page = _mock_page(
            url="https://www.gigamaisfibra.com.br/planos"
        )
        page.wait_for_selector = AsyncMock(return_value=True)

        # Usar o injector real com browser context mockado
        cookie_injector = GeolocationCookieInjector()
        browser_context = AsyncMock()
        browser_context.add_cookies = AsyncMock()

        # Injetar cookies usando config real
        result = await cookie_injector.inject_cookies(
            browser_context, GIGA_FIBRA_CONFIG
        )

        # Verificar que 5 cookies foram injetados
        assert result.cookies_injected is True
        assert result.cookies_count == 5

        # Verificar que add_cookies foi chamado com lista de 5 cookies
        browser_context.add_cookies.assert_called_once()
        cookies_arg = browser_context.add_cookies.call_args[0][0]
        assert len(cookies_arg) == 5

        # Verificar nomes dos cookies
        cookie_names = [c["name"] for c in cookies_arg]
        assert "PlanCity" in cookie_names
        assert "PlanName" in cookie_names
        assert "PlanRegion" in cookie_names
        assert "PlanType" in cookie_names
        assert "redirectToWhatsapp" in cookie_names


class TestGigaFibraCookieInjectionFailed:
    """Testes de integração para Giga+ Fibra: cookie injection falho.

    Valida que quando os cookies NÃO suprimem o modal, o fluxo
    recorre à Cascade Strategy (fallback via dropdown).

    Validates: Requirements 7.1, 11.4, 11.5
    """

    @pytest.mark.asyncio
    async def test_modal_detected_triggers_cascade_strategy(self):
        """Cookie não suprime modal → fallback para Cascade Strategy."""
        page = _mock_page(
            url="https://www.gigamaisfibra.com.br/planos"
        )
        page.wait_for_selector = AsyncMock(return_value=True)

        # Cookie injector: modal NÃO suprimido
        cookie_injector = AsyncMock(spec=GeolocationCookieInjector)
        cookie_injector.inject_cookies = AsyncMock(
            return_value=CookieInjectionResult(
                cookies_injected=True,
                cookies_count=5,
            )
        )
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False  # Modal APARECEU
        )

        # Component interactor: interação bem-sucedida via cascade
        component_interactor = AsyncMock(
            spec=CustomComponentInteractor
        )
        component_interactor.interact = AsyncMock(
            return_value=InteractionResult(
                success=True,
                strategy_used="react_select",
                component_type=ComponentType.REACT_SELECT,
                value_confirmed=True,
            )
        )

        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        browser_context = AsyncMock()

        flow = GigaFibraFlow(
            cookie_injector, component_interactor, screenshotter
        )
        result = await flow.execute(browser_context, page)

        # Verificar resultado
        assert result["success"] is True
        assert result["modal_suppressed"] is False
        assert result["fallback_used"] is True
        assert result["plans_loaded"] is True

        # Cascade Strategy FOI invocada como fallback
        component_interactor.interact.assert_called_once()
        call_kwargs = component_interactor.interact.call_args
        assert call_kwargs[1]["desired_value"] == "São Paulo"

    @pytest.mark.asyncio
    async def test_cascade_failure_returns_error(self):
        """Quando Cascade Strategy falha, retorna erro com razão."""
        page = _mock_page(
            url="https://www.gigamaisfibra.com.br/planos"
        )

        cookie_injector = AsyncMock(spec=GeolocationCookieInjector)
        cookie_injector.inject_cookies = AsyncMock(
            return_value=CookieInjectionResult(
                cookies_injected=True, cookies_count=5
            )
        )
        cookie_injector.verify_modal_suppressed = AsyncMock(
            return_value=False
        )

        # Cascade Strategy falha completamente
        component_interactor = AsyncMock(
            spec=CustomComponentInteractor
        )
        component_interactor.interact = AsyncMock(
            return_value=InteractionResult(
                success=False,
                strategy_used="all",
                component_type=ComponentType.UNKNOWN,
                error="custom_dropdown_interaction_failed",
            )
        )

        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")
        browser_context = AsyncMock()

        flow = GigaFibraFlow(
            cookie_injector, component_interactor, screenshotter
        )
        result = await flow.execute(browser_context, page)

        # Falha registrada corretamente
        assert result["success"] is False
        assert result["fallback_used"] is True
        assert result["plans_loaded"] is False
        assert "custom_dropdown_interaction_failed" in result["error"]


class TestNetflixGeoMismatch:
    """Testes de integração para Netflix: GEO_MISMATCH com extração skipped.

    Valida que quando conteúdo em inglês/USD é detectado na Netflix,
    a extração é pulada e evidência diagnóstica é capturada.

    Validates: Requirements 8.2
    """

    @pytest.mark.asyncio
    async def test_english_content_triggers_geo_mismatch(self):
        """Conteúdo em inglês → GEO_MISMATCH, extração skipped."""
        # Página com conteúdo em inglês (indicadores EN)
        english_content = (
            "Unlimited movies, TV shows, and more. "
            "Watch anywhere. Cancel anytime. "
            "Starting at US$ 6.99/month. "
            "Join Now"
        )
        page = _mock_page(
            url="https://www.netflix.com/browse",
            body_text=english_content,
            title="Netflix - Watch TV Shows Online",
        )

        # Usar ContentValidator real (não mock)
        content_validator = ContentValidator()

        # Mocks para diagnostics e screenshotter
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        diagnostics.capture_diagnostic = AsyncMock()

        health_check_scorer = HealthCheckScorer()

        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = NetflixFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="netflix",
            cycle_id="cycle-test-001",
        )

        result = await flow.execute(page)

        # Verificar GEO_MISMATCH detectado
        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_MISMATCH"
        assert result["reason"] is not None
        assert "geo_mismatch" in result["reason"].lower()

        # Diagnóstico foi capturado
        diagnostics.capture_diagnostic.assert_called_once()

        # Screenshot de evidência capturado
        screenshotter.capture.assert_called()

    @pytest.mark.asyncio
    async def test_portuguese_content_allows_extraction(self):
        """Conteúdo em português/BRL → SUCCESS, extração prossegue."""
        # Página com conteúdo em português
        pt_content = (
            "Assista onde quiser. Cancele quando quiser. "
            "Planos e preços. A partir de R$ 18,90/mês. "
            "Assinar agora. Mensalidade sem compromisso."
        )
        page = _mock_page(
            url="https://www.netflix.com/br/",
            body_text=pt_content,
            title="Netflix Brasil - Assista filmes e séries",
        )

        content_validator = ContentValidator()
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        health_check_scorer = HealthCheckScorer()
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = NetflixFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="netflix",
            cycle_id="cycle-test-002",
        )

        result = await flow.execute(page)

        # Verificar SUCCESS
        assert result["success"] is True
        assert result["extraction_skipped"] is False
        assert result["health_check_score"] == "SUCCESS"

        # Diagnóstico NÃO foi capturado
        diagnostics.capture_diagnostic.assert_not_called()


class TestParamountGeoRedirect:
    """Testes de integração para Paramount+: GEO_REDIRECT com extração skipped.

    Valida que quando indicadores de redirecionamento para US são detectados
    (Gift Card, Walmart, etc.) ou a URL não contém /br/, a extração é
    pulada e evidência diagnóstica é capturada.

    Validates: Requirements 9.2
    """

    @pytest.mark.asyncio
    async def test_us_redirect_triggers_geo_redirect(self):
        """Conteúdo US (Gift Card, Walmart) → GEO_REDIRECT, skipped."""
        us_content = (
            "Gift Card - Paramount+ "
            "Available at Walmart, Best Buy, Sam's Club. "
            "Give the gift of great entertainment! "
            "Buy US$ 25 Gift Card now."
        )
        page = _mock_page(
            url="https://www.paramountplus.com/gift-cards/",
            body_text=us_content,
            title="Gift Cards | Paramount+",
        )

        content_validator = ContentValidator()
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        diagnostics.capture_diagnostic = AsyncMock()
        health_check_scorer = HealthCheckScorer()
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = ParamountFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="paramount",
            cycle_id="cycle-test-003",
        )

        result = await flow.execute(page)

        # Verificar GEO_REDIRECT detectado
        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_REDIRECT"
        assert result["reason"] is not None

        # Diagnóstico capturado
        diagnostics.capture_diagnostic.assert_called_once()

    @pytest.mark.asyncio
    async def test_url_without_br_triggers_geo_redirect(self):
        """URL sem /br/ detecta GEO_REDIRECT sem indicadores US."""
        # Conteúdo ambíguo mas URL não tem /br/
        content = "Plans and pricing. Subscribe now."
        page = _mock_page(
            url="https://www.paramountplus.com/us/plans/",
            body_text=content,
            title="Plans | Paramount+",
        )

        content_validator = ContentValidator()
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        diagnostics.capture_diagnostic = AsyncMock()
        health_check_scorer = HealthCheckScorer()
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = ParamountFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="paramount",
            cycle_id="cycle-test-004",
        )

        result = await flow.execute(page)

        # URL sem /br/ → GEO_REDIRECT
        assert result["success"] is False
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_REDIRECT"
        assert result["final_url"] is not None

    @pytest.mark.asyncio
    async def test_brazilian_content_allows_extraction(self):
        """Conteúdo brasileiro com URL /br/ → SUCCESS, extração prossegue."""
        br_content = (
            "Planos e preços do Paramount+. "
            "Assinar agora por R$ 14,90/mês. "
            "Cancele quando quiser. Mensalidade sem fidelidade."
        )
        page = _mock_page(
            url="https://www.paramountplus.com/br/planos/",
            body_text=br_content,
            title="Planos | Paramount+ Brasil",
        )

        content_validator = ContentValidator()
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        health_check_scorer = HealthCheckScorer()
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = ParamountFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="paramount",
            cycle_id="cycle-test-005",
        )

        result = await flow.execute(page)

        # Verificar SUCCESS
        assert result["success"] is True
        assert result["extraction_skipped"] is False
        assert result["health_check_score"] == "SUCCESS"

        # Diagnóstico NÃO capturado
        diagnostics.capture_diagnostic.assert_not_called()


class TestDiagnosticsUploadS3:
    """Testes de integração para upload de diagnostics no S3 (moto mock).

    Valida que o DiagnosticsCollector faz upload de HTML e screenshot
    para S3 com as keys corretas no formato esperado.

    Usa mock do aioboto3 session para evitar conflito entre @mock_aws
    e funções async.

    Validates: Requirements 3.3, 3.4
    """

    @pytest.mark.asyncio
    async def test_diagnostics_upload_html_and_screenshot(self):
        """Upload de HTML e screenshot para S3 com prefixo correto."""
        # Página mock com conteúdo para diagnóstico
        page = _mock_page(
            url="https://www.example.com/error-page",
            body_text="Erro na página - conteúdo para diagnóstico",
        )
        page.content = AsyncMock(
            return_value="<html><body>Erro diagnóstico</body></html>"
        )
        page.screenshot = AsyncMock(
            return_value=b"\x89PNG\r\n\x1a\nscreenshot_data"
        )
        page.evaluate = AsyncMock(
            return_value=[
                {"tag": "div", "id": "main", "classes": "container"},
                {"tag": "span", "id": "", "classes": "error-msg"},
            ]
        )

        # Mock do S3 client async
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(return_value={})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        collector = DiagnosticsCollector(bucket=TEST_BUCKET)

        with patch.object(
            collector._session, "client", return_value=mock_context
        ):
            artifact = await collector.capture_diagnostic(
                page=page,
                error="Timeout ao carregar página",
                competitor_id="netflix",
                cycle_id="cycle-diag-001",
            )

        # Verificar artefato retornado
        assert artifact.final_url == "https://www.example.com/error-page"
        assert artifact.error_message == "Timeout ao carregar página"
        assert len(artifact.elements_found) == 2
        assert artifact.timestamp != ""

        # Verificar que S3 keys seguem o padrão correto
        assert artifact.html_s3_key is not None
        assert artifact.html_s3_key.startswith(
            "diagnostics/netflix/cycle-diag-001/"
        )
        assert artifact.html_s3_key.endswith(".html")

        assert artifact.screenshot_s3_key is not None
        assert artifact.screenshot_s3_key.startswith(
            "diagnostics/netflix/cycle-diag-001/"
        )
        assert artifact.screenshot_s3_key.endswith(".png")

        # Verificar que put_object foi chamado (HTML + screenshot = 2 vezes)
        assert mock_s3_client.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_diagnostics_objects_uploaded_to_s3(self):
        """Artefatos são enviados ao S3 com ContentType correto."""
        page = _mock_page(
            url="https://www.paramount.com/us/",
            body_text="Gift Card content",
        )
        page.content = AsyncMock(
            return_value="<html><body>Gift Card</body></html>"
        )
        page.screenshot = AsyncMock(return_value=b"\x89PNGdata")
        page.evaluate = AsyncMock(return_value=[])

        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(return_value={})

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        collector = DiagnosticsCollector(bucket=TEST_BUCKET)

        with patch.object(
            collector._session, "client", return_value=mock_context
        ):
            await collector.capture_diagnostic(
                page=page,
                error="GEO_REDIRECT detectado",
                competitor_id="paramount",
                cycle_id="cycle-diag-002",
            )

        # Verificar que put_object foi chamado com ContentType correto
        calls = mock_s3_client.put_object.call_args_list
        content_types = [
            c.kwargs.get("ContentType", "") for c in calls
        ]
        assert "text/html; charset=utf-8" in content_types
        assert "image/png" in content_types

        # Verificar bucket usado
        for call in calls:
            assert call.kwargs["Bucket"] == TEST_BUCKET

    @pytest.mark.asyncio
    async def test_html_truncated_to_5mb(self):
        """HTML maior que 5MB é truncado antes do upload."""
        # Página com HTML gigante (>5MB)
        large_content = "x" * (6 * 1024 * 1024)
        large_html = f"<html><body>{large_content}</body></html>"
        page = _mock_page(url="https://www.example.com/huge")
        page.content = AsyncMock(return_value=large_html)
        page.screenshot = AsyncMock(return_value=b"\x89PNGdata")
        page.evaluate = AsyncMock(return_value=[])

        uploaded_bodies = []

        async def capture_put_object(**kwargs):
            uploaded_bodies.append(kwargs.get("Body", b""))
            return {}

        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock(
            side_effect=capture_put_object
        )

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        collector = DiagnosticsCollector(bucket=TEST_BUCKET)

        with patch.object(
            collector._session, "client", return_value=mock_context
        ):
            await collector.capture_diagnostic(
                page=page,
                error="Page too large",
                competitor_id="test",
                cycle_id="cycle-large",
            )

        # Verificar que HTML uploaded é no máximo 5MB
        html_bodies = [
            b for b in uploaded_bodies if len(b) > 100
        ]
        if html_bodies:
            assert len(html_bodies[0]) <= 5 * 1024 * 1024


class TestHealthCheckScorePersistence:
    """Testes de integração para persistência do Health Check Score.

    Valida que o HealthCheckScorer classifica corretamente e que o
    resultado pode ser persistido no PriceRecord (campos corretos).

    Validates: Requirements 5.1, 5.2, 5.4
    """

    def test_success_score_when_extraction_ok(self):
        """Extração bem-sucedida sem problemas geo → SUCCESS."""
        scorer = HealthCheckScorer()

        score, reason, skipped = scorer.score(
            validation_result=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
            ),
            extraction_success=True,
            network_error=False,
        )

        assert score == HealthCheckScore.SUCCESS
        assert reason is None
        assert skipped is False

    def test_geo_mismatch_skips_extraction(self):
        """GEO_MISMATCH → extração marcada como skipped."""
        scorer = HealthCheckScorer()

        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="geo_mismatch: idioma inglês detectado",
            detected_language="en",
            detected_currency="USD",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_MISMATCH
        assert reason is not None
        assert "geo_mismatch" in reason.lower()
        assert skipped is True

    def test_geo_redirect_skips_extraction(self):
        """GEO_REDIRECT → extração marcada como skipped."""
        scorer = HealthCheckScorer()

        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="geo_redirect: URL redirecionada para /us/",
            final_url="https://www.paramount.com/us/gift-cards",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_REDIRECT
        assert reason is not None
        assert "geo_redirect" in reason.lower()
        assert skipped is True

    def test_network_error_has_highest_priority(self):
        """NETWORK_ERROR tem prioridade sobre GEO_MISMATCH."""
        scorer = HealthCheckScorer()

        # Mesmo com validação GEO_MISMATCH, network error prevalece
        validation = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="geo_mismatch",
        )

        score, reason, skipped = scorer.score(
            validation_result=validation,
            extraction_success=False,
            network_error=True,
        )

        assert score == HealthCheckScore.NETWORK_ERROR
        assert skipped is False

    def test_scraper_error_when_extraction_fails(self):
        """Extração falha sem geo problems → SCRAPER_ERROR."""
        scorer = HealthCheckScorer()

        score, reason, skipped = scorer.score(
            validation_result=ContentValidationResult(
                is_valid=True,
                health_check_score=HealthCheckScore.SUCCESS,
            ),
            extraction_success=False,
            network_error=False,
        )

        assert score == HealthCheckScore.SCRAPER_ERROR
        assert skipped is False

    def test_score_result_can_be_serialized_for_persistence(self):
        """O score retornado é serializável para persistência no banco."""
        scorer = HealthCheckScorer()

        score, reason, skipped = scorer.score(
            validation_result=ContentValidationResult(
                is_valid=False,
                health_check_score=HealthCheckScore.GEO_MISMATCH,
                reason="geo_mismatch: inglês detectado",
            ),
            extraction_success=False,
            network_error=False,
        )

        # Simular campos que seriam persistidos no PriceRecord
        price_record_fields = {
            "health_check_score": score.value,
            "health_check_reason": reason,
            "extraction_skipped": skipped,
        }

        assert price_record_fields["health_check_score"] == "GEO_MISMATCH"
        assert isinstance(price_record_fields["health_check_reason"], str)
        assert price_record_fields["extraction_skipped"] is True


class TestEndToEndOrdering:
    """Testes de integração para a ordenação correta de operações.

    Verifica que as operações ocorrem na ordem correta:
    inject_cookies → navigate → validate → interact_if_needed → extract

    Validates: Requirements 11.2, 11.4
    """

    @pytest.mark.asyncio
    async def test_cookies_injected_before_modal_check(self):
        """Cookies são injetados ANTES da verificação de modal."""
        page = _mock_page(
            url="https://www.gigamaisfibra.com.br/planos"
        )
        page.wait_for_selector = AsyncMock(return_value=True)

        # Rastrear ordem das chamadas
        call_order = []

        cookie_injector = AsyncMock(spec=GeolocationCookieInjector)

        async def mock_inject(*args, **kwargs):
            call_order.append("inject_cookies")
            return CookieInjectionResult(
                cookies_injected=True, cookies_count=5
            )

        async def mock_verify_modal(*args, **kwargs):
            call_order.append("verify_modal")
            return True  # Modal suprimido

        cookie_injector.inject_cookies = AsyncMock(
            side_effect=mock_inject
        )
        cookie_injector.verify_modal_suppressed = AsyncMock(
            side_effect=mock_verify_modal
        )

        component_interactor = AsyncMock(
            spec=CustomComponentInteractor
        )
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")
        browser_context = AsyncMock()

        flow = GigaFibraFlow(
            cookie_injector, component_interactor, screenshotter
        )
        await flow.execute(browser_context, page)

        # Cookies injetados ANTES da verificação de modal
        assert call_order.index("inject_cookies") < call_order.index(
            "verify_modal"
        )

    @pytest.mark.asyncio
    async def test_validation_before_extraction_netflix(self):
        """Validação de conteúdo ocorre ANTES de permitir extração."""
        # Conteúdo em inglês — extração deve ser impedida
        english_content = (
            "Watch anywhere. Starting at US$ 6.99. "
            "Unlimited movies."
        )
        page = _mock_page(
            url="https://www.netflix.com/",
            body_text=english_content,
        )

        content_validator = ContentValidator()
        diagnostics = AsyncMock(spec=DiagnosticsCollector)
        diagnostics.capture_diagnostic = AsyncMock()
        health_check_scorer = HealthCheckScorer()
        screenshotter = AsyncMock(spec=StepScreenshotter)
        screenshotter.capture = AsyncMock(return_value="key.png")

        flow = NetflixFlow(
            content_validator=content_validator,
            diagnostics_collector=diagnostics,
            health_check_scorer=health_check_scorer,
            screenshotter=screenshotter,
            competitor_id="netflix",
            cycle_id="cycle-order-001",
        )

        result = await flow.execute(page)

        # Validação detectou problema ANTES de extrair
        assert result["extraction_skipped"] is True
        assert result["health_check_score"] == "GEO_MISMATCH"

    @pytest.mark.asyncio
    async def test_url_encoding_applied_to_cookie_values(self):
        """Valores com acentos são URL-encoded antes da injeção."""
        from scraping_resilience.site_configs.giga_fibra import (
            GIGA_FIBRA_CONFIG,
        )

        injector = GeolocationCookieInjector()
        browser_context = AsyncMock()
        browser_context.add_cookies = AsyncMock()

        await injector.inject_cookies(browser_context, GIGA_FIBRA_CONFIG)

        # Verificar que valores foram encoded corretamente
        cookies_arg = browser_context.add_cookies.call_args[0][0]
        cookie_dict = {c["name"]: c["value"] for c in cookies_arg}

        # PlanName deve estar URL-encoded (São Paulo → S%C3%A3o%20Paulo)
        assert cookie_dict["PlanName"] == "S%C3%A3o%20Paulo"

        # PlanRegion deve estar URL-encoded
        assert "%C3%B3" in cookie_dict["PlanRegion"]  # 'ó' encoded

        # PlanCity (numérico) não deve ser encoded
        assert cookie_dict["PlanCity"] == "329"

        # PlanType (ASCII) não deve ser encoded
        assert cookie_dict["PlanType"] == "PF"
