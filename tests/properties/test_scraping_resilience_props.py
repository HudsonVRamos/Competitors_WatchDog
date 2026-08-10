"""Property-based tests para o módulo Scraping Resilience.

Feature: scraping-resilience
Testes de propriedade usando Hypothesis para validar invariantes
dos componentes de resiliência do PriceScraper.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.scraping_resilience.intelligent_wait import IntelligentWaitManager
from src.scraping_resilience.models import WaitResult
from src.scraping_resilience.retry_engine import RetryEngine


# ============================================================================
# Helpers para Property 1: Wait Cascade Ordering
# ============================================================================


def _make_mock_page(
    networkidle_succeeds: bool,
    selector_succeeds: bool,
    visible_succeeds: bool,
) -> tuple[AsyncMock, list[str]]:
    """Cria mock de Page do Playwright com comportamento configurável.

    Retorna a page mock e uma lista mutável que registra a ordem
    em que as estratégias foram tentadas.
    """
    call_order: list[str] = []
    page = AsyncMock()

    # Estratégia 1: networkidle via wait_for_load_state
    async def mock_wait_for_load_state(
        state: str, timeout: int = 30_000
    ) -> None:
        call_order.append("networkidle")
        if not networkidle_succeeds:
            raise PlaywrightTimeoutError("networkidle timeout")

    page.wait_for_load_state = AsyncMock(
        side_effect=mock_wait_for_load_state
    )

    # Estratégia 2: waitForSelector
    async def mock_wait_for_selector(
        selector: str, timeout: int = 15_000
    ) -> None:
        call_order.append("selector")
        if not selector_succeeds:
            raise PlaywrightTimeoutError(
                f"selector timeout: {selector}"
            )

    page.wait_for_selector = AsyncMock(
        side_effect=mock_wait_for_selector
    )

    # Estratégia 3: toBeVisible via locator
    mock_locator = MagicMock()
    mock_first = AsyncMock()
    mock_locator.first = mock_first
    page.locator = MagicMock(return_value=mock_locator)

    return page, call_order


# ============================================================================
# Property 1: Wait Cascade Ordering
# ============================================================================


@pytest.mark.property
class TestWaitCascadeOrdering:
    """Property 1: Wait cascade aplica estratégias na ordem correta.

    Feature: scraping-resilience
    Validates: Requirements 1.1, 1.3

    Para qualquer combinação de condições de página (networkidle
    atingido ou não, seletores críticos encontrados ou não, elementos
    visíveis ou não), o IntelligentWaitManager SHALL aplicar as
    estratégias na ordem: networkidle primeiro, depois waitForSelector,
    depois toBeVisible, e retornar a primeira que obteve sucesso.
    """

    @given(
        networkidle_succeeds=st.booleans(),
        selector_succeeds=st.booleans(),
        visible_succeeds=st.booleans(),
    )
    @settings(max_examples=50)
    async def test_networkidle_success_returns_networkidle(
        self,
        networkidle_succeeds: bool,
        selector_succeeds: bool,
        visible_succeeds: bool,
    ) -> None:
        """Quando networkidle tem sucesso, strategy_used == 'networkidle'.

        **Validates: Requirements 1.1, 1.3**
        """
        if not networkidle_succeeds:
            return

        page, call_order = _make_mock_page(
            networkidle_succeeds=True,
            selector_succeeds=selector_succeeds,
            visible_succeeds=visible_succeeds,
        )

        manager = IntelligentWaitManager()
        result = await manager.wait_for_page_ready(
            page=page,
            critical_selectors=[".price-card"],
        )

        assert result.success is True
        assert result.strategy_used == "networkidle"
        assert result.timeout_occurred is False
        # networkidle deve ser a primeira (e única) estratégia tentada
        assert call_order[0] == "networkidle"

    @given(
        selector_succeeds=st.booleans(),
        visible_succeeds=st.booleans(),
    )
    @settings(max_examples=50)
    async def test_selector_success_when_networkidle_fails(
        self,
        selector_succeeds: bool,
        visible_succeeds: bool,
    ) -> None:
        """Quando networkidle falha e selector sucede, strategy == 'selector'.

        **Validates: Requirements 1.1, 1.3**
        """
        if not selector_succeeds:
            return

        page, call_order = _make_mock_page(
            networkidle_succeeds=False,
            selector_succeeds=True,
            visible_succeeds=visible_succeeds,
        )

        manager = IntelligentWaitManager()
        result = await manager.wait_for_page_ready(
            page=page,
            critical_selectors=[".price-card"],
        )

        assert result.success is True
        assert result.strategy_used == "selector"
        assert result.timeout_occurred is False
        # networkidle deve ser tentado primeiro, depois selector
        assert call_order[0] == "networkidle"
        assert "selector" in call_order

    @given(visible_succeeds=st.booleans())
    @settings(max_examples=20)
    async def test_visible_success_when_others_fail(
        self, visible_succeeds: bool
    ) -> None:
        """Quando networkidle e selector falham, visible é tentado.

        **Validates: Requirements 1.1, 1.3**
        """
        if not visible_succeeds:
            return

        page, call_order = _make_mock_page(
            networkidle_succeeds=False,
            selector_succeeds=False,
            visible_succeeds=True,
        )

        with patch(
            "src.scraping_resilience.intelligent_wait.expect"
        ) as mock_expect:

            def sync_expect(locator):
                call_order.append("visible")
                mock_obj = MagicMock()
                mock_obj.to_be_visible = AsyncMock()
                return mock_obj

            mock_expect.side_effect = sync_expect

            manager = IntelligentWaitManager()
            result = await manager.wait_for_page_ready(
                page=page,
                critical_selectors=[".price-card"],
            )

        assert result.success is True
        assert result.strategy_used == "visible"
        assert result.timeout_occurred is False
        # Ordem: networkidle → selector → visible
        assert call_order[0] == "networkidle"
        assert "selector" in call_order
        assert "visible" in call_order

    @given(
        networkidle_succeeds=st.just(False),
        selector_succeeds=st.just(False),
        visible_succeeds=st.just(False),
    )
    @settings(max_examples=5)
    async def test_all_fail_returns_timeout(
        self,
        networkidle_succeeds: bool,
        selector_succeeds: bool,
        visible_succeeds: bool,
    ) -> None:
        """Quando todas as estratégias falham, timeout_occurred == True.

        **Validates: Requirements 1.1, 1.3**
        """
        page, call_order = _make_mock_page(
            networkidle_succeeds=False,
            selector_succeeds=False,
            visible_succeeds=False,
        )

        with patch(
            "src.scraping_resilience.intelligent_wait.expect"
        ) as mock_expect:

            def sync_expect(locator):
                call_order.append("visible")
                mock_obj = MagicMock()
                mock_obj.to_be_visible = AsyncMock(
                    side_effect=PlaywrightTimeoutError(
                        "visible timeout"
                    )
                )
                return mock_obj

            mock_expect.side_effect = sync_expect

            manager = IntelligentWaitManager()
            result = await manager.wait_for_page_ready(
                page=page,
                critical_selectors=[".price-card"],
            )

        assert result.success is False
        assert result.timeout_occurred is True
        # Todas as estratégias devem ter sido tentadas na ordem
        assert call_order[0] == "networkidle"
        assert "selector" in call_order
        assert "visible" in call_order

    @given(
        networkidle_succeeds=st.booleans(),
        selector_succeeds=st.booleans(),
        visible_succeeds=st.booleans(),
    )
    @settings(max_examples=50)
    async def test_order_always_networkidle_selector_visible(
        self,
        networkidle_succeeds: bool,
        selector_succeeds: bool,
        visible_succeeds: bool,
    ) -> None:
        """Ordem é SEMPRE networkidle → selector → visible.

        **Validates: Requirements 1.1, 1.3**

        Independente de quais estratégias têm sucesso ou falham, a
        ordem em que são tentadas deve ser estritamente: networkidle
        primeiro, selector depois, visible por último.
        """
        page, call_order = _make_mock_page(
            networkidle_succeeds=networkidle_succeeds,
            selector_succeeds=selector_succeeds,
            visible_succeeds=visible_succeeds,
        )

        with patch(
            "src.scraping_resilience.intelligent_wait.expect"
        ) as mock_expect:

            def sync_expect(locator):
                call_order.append("visible")
                mock_obj = MagicMock()
                if visible_succeeds:
                    mock_obj.to_be_visible = AsyncMock()
                else:
                    mock_obj.to_be_visible = AsyncMock(
                        side_effect=PlaywrightTimeoutError(
                            "visible timeout"
                        )
                    )
                return mock_obj

            mock_expect.side_effect = sync_expect

            manager = IntelligentWaitManager()
            result = await manager.wait_for_page_ready(
                page=page,
                critical_selectors=[".price-card"],
            )

        # Verifica que a ordem está correta
        expected_order = ["networkidle", "selector", "visible"]

        for i in range(len(call_order) - 1):
            current_idx = expected_order.index(call_order[i])
            next_idx = expected_order.index(call_order[i + 1])
            assert current_idx <= next_idx, (
                f"Ordem incorreta: {call_order[i]} "
                f"(idx={current_idx}) veio antes de "
                f"{call_order[i + 1]} (idx={next_idx}). "
                f"Sequência completa: {call_order}"
            )

        # networkidle SEMPRE é tentado primeiro
        assert call_order[0] == "networkidle"

        # Se networkidle falhou, selector deve ter sido tentado
        if not networkidle_succeeds:
            assert "selector" in call_order

        # Se ambos falharam, visible deve ter sido tentado
        if not networkidle_succeeds and not selector_succeeds:
            assert "visible" in call_order


@pytest.mark.property
class TestRetryEngineLimitsAndBackoff:
    """Property 3: Retry engine respeita limites e backoff exponencial.

    *For any* operação crítica que falha N vezes, o RetryEngine SHALL
    executar exatamente min(N, max_attempts) tentativas, com delays
    crescentes seguindo backoff exponencial, e o resultado final SHALL
    conter todas as razões de erro quando todas falharem.

    **Validates: Requirements 2.1, 2.3**
    """

    @given(
        max_attempts=st.integers(min_value=1, max_value=5),
        base_delay=st.floats(
            min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        exponential_base=st.floats(
            min_value=1.1, max_value=3.0, allow_nan=False, allow_infinity=False
        ),
        fail_count=st.integers(min_value=1, max_value=7),
    )
    @settings(max_examples=100)
    async def test_all_failures_attempts_equal_max(
        self,
        max_attempts: int,
        base_delay: float,
        exponential_base: float,
        fail_count: int,
    ) -> None:
        """Quando todas as tentativas falham, attempts == max_attempts.

        **Validates: Requirements 2.1, 2.3**

        Se fail_count >= max_attempts, a operação falha em todas as
        tentativas e o resultado deve ter attempts == max_attempts.
        """
        # Garantir que fail_count >= max_attempts (todas falham)
        effective_fail_count = max(fail_count, max_attempts)

        call_count = 0

        async def failing_operation() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"Erro na tentativa {call_count}")

        engine = RetryEngine(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            exponential_base=exponential_base,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(
                failing_operation, "test_operation"
            )

        assert result.success is False
        assert result.attempts == max_attempts
        assert call_count == max_attempts

    @given(
        max_attempts=st.integers(min_value=2, max_value=5),
        base_delay=st.floats(
            min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        exponential_base=st.floats(
            min_value=1.1, max_value=3.0, allow_nan=False, allow_infinity=False
        ),
        fail_count=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    async def test_eventual_success_attempts_correct(
        self,
        max_attempts: int,
        base_delay: float,
        exponential_base: float,
        fail_count: int,
    ) -> None:
        """Quando operação eventualmente tem sucesso, attempts == fail_count + 1.

        **Validates: Requirements 2.1, 2.3**

        Se fail_count < max_attempts, a operação falha fail_count vezes
        e depois tem sucesso. O resultado deve ter
        attempts == fail_count + 1.
        """
        # Garantir que fail_count < max_attempts (sucesso eventual)
        effective_fail_count = min(fail_count, max_attempts - 1)

        call_count = 0

        async def eventually_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= effective_fail_count:
                raise RuntimeError(
                    f"Erro na tentativa {call_count}"
                )
            return "sucesso"

        engine = RetryEngine(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            exponential_base=exponential_base,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(
                eventually_succeeds, "test_operation"
            )

        assert result.success is True
        assert result.attempts == effective_fail_count + 1
        assert result.result == "sucesso"

    @given(
        max_attempts=st.integers(min_value=1, max_value=5),
        base_delay=st.floats(
            min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        exponential_base=st.floats(
            min_value=1.1, max_value=3.0, allow_nan=False, allow_infinity=False
        ),
        fail_count=st.integers(min_value=1, max_value=7),
    )
    @settings(max_examples=100)
    async def test_errors_list_has_correct_count(
        self,
        max_attempts: int,
        base_delay: float,
        exponential_base: float,
        fail_count: int,
    ) -> None:
        """Lista de erros contém exatamente min(fail_count, max_attempts) entradas.

        **Validates: Requirements 2.1, 2.3**

        Quando todas falham, errors tem max_attempts entradas.
        Quando sucesso eventual, errors tem fail_count entradas.
        """
        # Determinar se todas falham ou sucesso eventual
        all_fail = fail_count >= max_attempts
        effective_fail_count = (
            max_attempts if all_fail else fail_count
        )

        call_count = 0

        async def operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= effective_fail_count:
                raise RuntimeError(
                    f"Erro na tentativa {call_count}"
                )
            return "sucesso"

        engine = RetryEngine(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            exponential_base=exponential_base,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(
                operation, "test_operation"
            )

        expected_errors = min(fail_count, max_attempts)
        assert len(result.errors) == expected_errors

    @given(
        max_attempts=st.integers(min_value=2, max_value=5),
        base_delay=st.floats(
            min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        exponential_base=st.floats(
            min_value=1.1, max_value=3.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    async def test_total_delay_matches_exponential_backoff(
        self,
        max_attempts: int,
        base_delay: float,
        exponential_base: float,
    ) -> None:
        """total_delay_ms segue soma de backoff exponencial.

        **Validates: Requirements 2.1, 2.3**

        O delay total deve corresponder à soma:
        sum(base_delay * exp_base^(i-1) * 1000) para i em 1..attempts-1

        Com padrão (base=2, exp=2):
        - Após tentativa 1: delay = 2 * 2^0 = 2s = 2000ms
        - Após tentativa 2: delay = 2 * 2^1 = 4s = 4000ms
        - Total para 3 tentativas: 2000 + 4000 = 6000ms
        """
        call_count = 0

        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"Erro {call_count}")

        engine = RetryEngine(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            exponential_base=exponential_base,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(
                always_fails, "test_operation"
            )

        # Calcular delay esperado: soma de delays entre tentativas
        # Delay entre tentativa i e i+1 = base_delay * exp_base^(i-1)
        # Apenas max_attempts-1 delays (entre cada par de tentativas)
        expected_delay_ms = sum(
            int(base_delay * (exponential_base ** (i - 1)) * 1000)
            for i in range(1, max_attempts)
        )

        assert result.total_delay_ms == expected_delay_ms

    @given(
        max_attempts=st.integers(min_value=1, max_value=5),
        base_delay=st.floats(
            min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        exponential_base=st.floats(
            min_value=1.1, max_value=3.0, allow_nan=False, allow_infinity=False
        ),
        fail_count=st.integers(min_value=0, max_value=7),
    )
    @settings(max_examples=100)
    async def test_success_correlates_with_fail_count(
        self,
        max_attempts: int,
        base_delay: float,
        exponential_base: float,
        fail_count: int,
    ) -> None:
        """result.success correlaciona com fail_count < max_attempts.

        **Validates: Requirements 2.1, 2.3**

        Se fail_count < max_attempts, a operação deve ter sucesso.
        Se fail_count >= max_attempts, a operação deve falhar.
        """
        call_count = 0

        async def operation() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= fail_count:
                raise RuntimeError(
                    f"Erro na tentativa {call_count}"
                )
            return "sucesso"

        engine = RetryEngine(
            max_attempts=max_attempts,
            base_delay_seconds=base_delay,
            exponential_base=exponential_base,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine.execute(
                operation, "test_operation"
            )

        if fail_count < max_attempts:
            assert result.success is True
        else:
            assert result.success is False


# --- Imports adicionais para Property 15 ---
import re
import string

from scraping_resilience.cookie_injector import GeolocationCookieInjector

# Estratégias de geração de texto para URL-encoding

# Texto genérico unicode (inclui acentos, espaços, emojis, etc.)
_any_text = st.text(min_size=0, max_size=200)

# Texto realista para nomes de cidades brasileiras
_brazilian_text = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
    ),
)

# Texto ASCII-only (letras e dígitos)
_ascii_alnum = st.text(
    min_size=1,
    max_size=100,
    alphabet=string.ascii_letters + string.digits,
)


@pytest.mark.property
class TestCookieURLEncodingRoundTrip:
    """Property 15: CookieConfig URL-encoding round-trip.

    **Validates: Requirements 11.1, 11.7**

    For any CookieConfig válido com url_encode=True cujo value contenha
    caracteres especiais (acentos, espaços, parênteses, cedilhas e
    outros caracteres não-ASCII), a aplicação de URL-encoding seguida
    de URL-decoding SHALL produzir um valor idêntico ao original; e
    para qualquer CookieConfig com url_encode=False, o value SHALL ser
    preservado sem transformação.
    """

    @given(value=_any_text)
    @settings(max_examples=200)
    def test_encode_decode_round_trip_any_text(
        self, value: str
    ) -> None:
        """Round-trip: decode(encode(value)) == value.

        **Validates: Requirements 11.1, 11.7**

        Para qualquer string Unicode, encoding seguido de decoding
        produz o valor original sem perda de dados.
        """
        injector = GeolocationCookieInjector()
        encoded = injector.encode_cookie_value(value)
        decoded = injector.decode_cookie_value(encoded)

        assert decoded == value, (
            f"Round-trip falhou: original={value!r}, "
            f"encoded={encoded!r}, decoded={decoded!r}"
        )

    @given(value=_brazilian_text)
    @settings(max_examples=200)
    def test_encode_decode_round_trip_brazilian_text(
        self, value: str
    ) -> None:
        """Round-trip com texto brasileiro (acentos, cedilhas).

        **Validates: Requirements 11.1, 11.7**

        Verifica round-trip com caracteres típicos de nomes
        brasileiros: acentos (ã, ó, í, ç), espaços, parênteses.
        """
        injector = GeolocationCookieInjector()
        encoded = injector.encode_cookie_value(value)
        decoded = injector.decode_cookie_value(encoded)

        assert decoded == value, (
            f"Round-trip falhou para texto brasileiro: "
            f"original={value!r}, encoded={encoded!r}, "
            f"decoded={decoded!r}"
        )

    @given(value=_ascii_alnum)
    @settings(max_examples=100)
    def test_encode_ascii_alnum_preserves_value(
        self, value: str
    ) -> None:
        """ASCII alphanumeric: encode não altera o resultado.

        **Validates: Requirements 11.1, 11.7**

        Para valores contendo apenas letras ASCII e dígitos, o
        encoding não deve modificar o valor (são URL-safe).
        """
        injector = GeolocationCookieInjector()
        encoded = injector.encode_cookie_value(value)

        assert encoded == value, (
            f"Encoding alterou valor ASCII-only: "
            f"original={value!r}, encoded={encoded!r}"
        )

    @given(value=_any_text)
    @settings(max_examples=200)
    def test_encoded_value_is_url_safe(
        self, value: str
    ) -> None:
        """Valor encoded contém apenas caracteres URL-safe.

        **Validates: Requirements 11.1, 11.7**

        O resultado do encoding deve conter apenas ASCII
        alfanuméricos, '-', '_', '.', '~' e sequências %XX.
        Não deve conter espaços, acentos ou não-ASCII.
        """
        injector = GeolocationCookieInjector()
        encoded = injector.encode_cookie_value(value)

        # urllib.parse.quote(safe="") produz: letras, dígitos,
        # '-', '_', '.', '~' e sequências %XX
        url_safe_pattern = re.compile(
            r"^[A-Za-z0-9\-_.~%]*$"
        )
        assert url_safe_pattern.match(encoded), (
            f"Encoded contém chars não URL-safe: "
            f"original={value!r}, encoded={encoded!r}"
        )



# ============================================================================
# Property 16: Cookie Injection Flow Ordering
# ============================================================================


async def _simulate_cookie_injection_flow(
    injector: GeolocationCookieInjector,
    browser_context: AsyncMock,
    page: AsyncMock,
    site_config: dict,
    url: str,
    modal_selector: str,
    modal_suppressed: bool,
    cascade_interactor: AsyncMock,
    call_log: list[str],
) -> None:
    """Simula o fluxo de orquestração de cookie injection.

    Fluxo esperado:
    1. inject_cookies (ANTES de page.goto)
    2. page.goto
    3. verify_modal_suppressed
    4. Se modal NÃO suprimido → cascade_interactor.interact()
    """
    # Passo 1: Injetar cookies ANTES da navegação
    result = await injector.inject_cookies(browser_context, site_config)
    call_log.append("inject_cookies")

    # Passo 2: Navegar
    await page.goto(url)
    call_log.append("page_goto")

    # Passo 3: Verificar se modal foi suprimido
    suppressed = await injector.verify_modal_suppressed(
        page, modal_selector
    )
    call_log.append("verify_modal_suppressed")

    # Passo 4: Se modal não foi suprimido, invocar cascade
    if not suppressed:
        await cascade_interactor.interact(page, modal_selector)
        call_log.append("cascade_interact")


def _make_site_config_with_cookies(num_cookies: int) -> dict:
    """Cria um site_config com N cookies de geolocalização."""
    cookies = []
    for i in range(num_cookies):
        cookies.append({
            "name": f"Cookie{i}",
            "value": f"value_{i}",
            "domain": ".example.com",
            "path": "/",
            "url_encode": False,
        })
    return {"geolocation_cookies": cookies}


@pytest.mark.property
class TestCookieInjectionFlowOrdering:
    """Property 16: Cookie injection flow respeita ordenação e fallback.

    Feature: scraping-resilience
    **Validates: Requirements 11.2, 11.4, 11.5**

    For any site com cookies de geolocalização configurados:
    1. Cookies são injetados ANTES de page.goto() (ordering invariant)
    2. Quando verify_modal_suppressed() retorna True (modal não
       apareceu), a Cascade_Strategy NÃO é invocada
    3. Quando verify_modal_suppressed() retorna False (modal apareceu),
       a Cascade_Strategy É invocada como fallback
    """

    @given(
        has_cookies=st.booleans(),
        modal_suppressed=st.booleans(),
        num_cookies=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    async def test_cookies_injected_before_navigation(
        self,
        has_cookies: bool,
        modal_suppressed: bool,
        num_cookies: int,
    ) -> None:
        """Cookies são injetados ANTES de page.goto().

        **Validates: Requirements 11.2, 11.4, 11.5**

        Independente de quantos cookies existem ou se o modal
        é suprimido, inject_cookies SEMPRE precede page.goto()
        no call_log.
        """
        effective_cookies = num_cookies if has_cookies else 0
        site_config = _make_site_config_with_cookies(
            effective_cookies
        )

        # Mocks
        browser_context = AsyncMock()
        page = AsyncMock()
        cascade_interactor = AsyncMock()
        call_log: list[str] = []

        # Configurar verify_modal_suppressed via mock do page
        if modal_suppressed:
            # Modal NÃO aparece → wait_for_selector levanta timeout
            page.wait_for_selector = AsyncMock(
                side_effect=PlaywrightTimeoutError(
                    "modal not found"
                )
            )
        else:
            # Modal aparece → wait_for_selector retorna normalmente
            page.wait_for_selector = AsyncMock(
                return_value=MagicMock()
            )

        injector = GeolocationCookieInjector()
        await _simulate_cookie_injection_flow(
            injector=injector,
            browser_context=browser_context,
            page=page,
            site_config=site_config,
            url="https://example.com/plans",
            modal_selector=".modal-location",
            modal_suppressed=modal_suppressed,
            cascade_interactor=cascade_interactor,
            call_log=call_log,
        )

        # PROPRIEDADE: inject_cookies SEMPRE antes de page_goto
        inject_idx = call_log.index("inject_cookies")
        goto_idx = call_log.index("page_goto")
        assert inject_idx < goto_idx, (
            f"inject_cookies (idx={inject_idx}) deveria vir "
            f"antes de page_goto (idx={goto_idx}). "
            f"Call log: {call_log}"
        )

    @given(
        num_cookies=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    async def test_modal_suppressed_no_cascade(
        self,
        num_cookies: int,
    ) -> None:
        """Quando modal é suprimido, Cascade_Strategy NÃO é invocada.

        **Validates: Requirements 11.2, 11.4, 11.5**

        Quando verify_modal_suppressed() retorna True (modal não
        apareceu), o fallback via Cascade_Strategy não deve ser
        chamado.
        """
        site_config = _make_site_config_with_cookies(num_cookies)

        # Mocks
        browser_context = AsyncMock()
        page = AsyncMock()
        cascade_interactor = AsyncMock()
        call_log: list[str] = []

        # Modal NÃO aparece → TimeoutError (significa suprimido)
        page.wait_for_selector = AsyncMock(
            side_effect=PlaywrightTimeoutError(
                "modal not found"
            )
        )

        injector = GeolocationCookieInjector()
        await _simulate_cookie_injection_flow(
            injector=injector,
            browser_context=browser_context,
            page=page,
            site_config=site_config,
            url="https://gigamaisfibra.com.br/planos",
            modal_selector=".modal-cidade",
            modal_suppressed=True,
            cascade_interactor=cascade_interactor,
            call_log=call_log,
        )

        # PROPRIEDADE: cascade_interact NÃO está no call_log
        assert "cascade_interact" not in call_log, (
            f"Cascade foi invocada mesmo com modal suprimido. "
            f"Call log: {call_log}"
        )
        # Cascade interactor.interact() não deve ter sido chamado
        cascade_interactor.interact.assert_not_called()

    @given(
        num_cookies=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    async def test_modal_not_suppressed_cascade_invoked(
        self,
        num_cookies: int,
    ) -> None:
        """Quando modal aparece, Cascade_Strategy É invocada.

        **Validates: Requirements 11.2, 11.4, 11.5**

        Quando verify_modal_suppressed() retorna False (modal
        apareceu apesar dos cookies), o fallback via
        Cascade_Strategy DEVE ser chamado.
        """
        site_config = _make_site_config_with_cookies(num_cookies)

        # Mocks
        browser_context = AsyncMock()
        page = AsyncMock()
        cascade_interactor = AsyncMock()
        call_log: list[str] = []

        # Modal APARECE → wait_for_selector retorna normalmente
        page.wait_for_selector = AsyncMock(
            return_value=MagicMock()
        )

        injector = GeolocationCookieInjector()
        await _simulate_cookie_injection_flow(
            injector=injector,
            browser_context=browser_context,
            page=page,
            site_config=site_config,
            url="https://gigamaisfibra.com.br/planos",
            modal_selector=".modal-cidade",
            modal_suppressed=False,
            cascade_interactor=cascade_interactor,
            call_log=call_log,
        )

        # PROPRIEDADE: cascade_interact ESTÁ no call_log
        assert "cascade_interact" in call_log, (
            f"Cascade NÃO foi invocada com modal não suprimido. "
            f"Call log: {call_log}"
        )
        # Cascade interactor.interact() deve ter sido chamado
        cascade_interactor.interact.assert_called_once()

    @given(
        has_cookies=st.booleans(),
        modal_suppressed=st.booleans(),
        num_cookies=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    async def test_verify_modal_after_navigation(
        self,
        has_cookies: bool,
        modal_suppressed: bool,
        num_cookies: int,
    ) -> None:
        """verify_modal_suppressed é chamado APÓS page.goto().

        **Validates: Requirements 11.2, 11.4, 11.5**

        A verificação de supressão de modal só faz sentido após
        a navegação para a URL do concorrente.
        """
        effective_cookies = num_cookies if has_cookies else 0
        site_config = _make_site_config_with_cookies(
            effective_cookies
        )

        # Mocks
        browser_context = AsyncMock()
        page = AsyncMock()
        cascade_interactor = AsyncMock()
        call_log: list[str] = []

        if modal_suppressed:
            page.wait_for_selector = AsyncMock(
                side_effect=PlaywrightTimeoutError(
                    "modal not found"
                )
            )
        else:
            page.wait_for_selector = AsyncMock(
                return_value=MagicMock()
            )

        injector = GeolocationCookieInjector()
        await _simulate_cookie_injection_flow(
            injector=injector,
            browser_context=browser_context,
            page=page,
            site_config=site_config,
            url="https://example.com/plans",
            modal_selector=".modal-location",
            modal_suppressed=modal_suppressed,
            cascade_interactor=cascade_interactor,
            call_log=call_log,
        )

        # PROPRIEDADE: verify_modal_suppressed APÓS page_goto
        goto_idx = call_log.index("page_goto")
        verify_idx = call_log.index("verify_modal_suppressed")
        assert goto_idx < verify_idx, (
            f"page_goto (idx={goto_idx}) deveria vir antes de "
            f"verify_modal_suppressed (idx={verify_idx}). "
            f"Call log: {call_log}"
        )


# ============================================================================
# Property 8: Content Validation detecta corretamente idioma e moeda
# ============================================================================

from scraping_resilience.content_validator import (
    ContentValidator,
    PT_INDICATORS,
    EN_INDICATORS,
)

# Estratégias de geração para indicadores de idioma e moeda

_pt_indicators_strategy = st.sampled_from(PT_INDICATORS)
_en_indicators_strategy = st.sampled_from(EN_INDICATORS)

# Preços em BRL (ex: "R$ 29,90", "R$ 199,90")
_brl_prices_strategy = st.builds(
    lambda reais, centavos: f"R$ {reais},{centavos:02d}",
    reais=st.integers(min_value=1, max_value=999),
    centavos=st.integers(min_value=0, max_value=99),
)

# Preços em USD (ex: "US$ 6.99", "US$ 19.99")
_usd_prices_strategy = st.builds(
    lambda dollars, cents: f"US$ {dollars}.{cents:02d}",
    dollars=st.integers(min_value=1, max_value=999),
    cents=st.integers(min_value=0, max_value=99),
)


def _build_page_text(
    pt_terms: list[str],
    en_terms: list[str],
    brl_prices: list[str],
    usd_prices: list[str],
) -> str:
    """Constrói texto de página simulado a partir de indicadores."""
    parts = []
    for term in pt_terms:
        parts.append(f"Confira: {term} agora")
    for term in en_terms:
        parts.append(f"Check out: {term} now")
    for price in brl_prices:
        parts.append(f"A partir de {price}/mês")
    for price in usd_prices:
        parts.append(f"Starting at {price}/month")
    return "\n".join(parts)


@pytest.mark.property
class TestContentValidationLanguageAndCurrency:
    """Property 8: Content validation detecta corretamente idioma e moeda.

    Feature: scraping-resilience
    **Validates: Requirements 8.1, 8.2, 9.1, 9.2**

    For any texto de página contendo indicadores de idioma (termos em
    português como "Assista", "Planos", "Assinar" ou em inglês como
    "Unlimited", "Watch", "Starting at") e indicadores de moeda (R$ ou
    US$), o ContentValidator SHALL detectar corretamente o idioma e a
    moeda predominante, e SHALL classificar como GEO_MISMATCH quando
    idioma é inglês ou moeda é USD, com razão descritiva listando os
    indicadores encontrados.
    """

    @given(
        pt_terms=st.lists(
            _pt_indicators_strategy, min_size=2, max_size=5, unique=True
        ),
        en_terms=st.lists(
            _en_indicators_strategy, min_size=0, max_size=1, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_more_pt_indicators_detected_language_pt(
        self,
        pt_terms: list[str],
        en_terms: list[str],
    ) -> None:
        """Quando mais indicadores PT que EN, detected_language == "pt".

        **Validates: Requirements 8.1, 8.2**
        """
        # Garantir que PT > EN
        if len(pt_terms) <= len(en_terms):
            return

        page_text = _build_page_text(
            pt_terms=pt_terms,
            en_terms=en_terms,
            brl_prices=[],
            usd_prices=[],
        )

        validator = ContentValidator()
        result = validator.detect_language_indicators(page_text)

        assert result.detected_language == "pt", (
            f"Esperado 'pt' mas obteve '{result.detected_language}'. "
            f"PT terms={pt_terms}, EN terms={en_terms}"
        )

    @given(
        pt_terms=st.lists(
            _pt_indicators_strategy, min_size=0, max_size=1, unique=True
        ),
        en_terms=st.lists(
            _en_indicators_strategy, min_size=2, max_size=6, unique=True
        ),
    )
    @settings(max_examples=100)
    def test_more_en_indicators_detected_language_en(
        self,
        pt_terms: list[str],
        en_terms: list[str],
    ) -> None:
        """Quando mais indicadores EN que PT, detected_language == "en".

        **Validates: Requirements 8.1, 8.2**
        """
        # Garantir que EN > PT
        if len(en_terms) <= len(pt_terms):
            return

        page_text = _build_page_text(
            pt_terms=pt_terms,
            en_terms=en_terms,
            brl_prices=[],
            usd_prices=[],
        )

        validator = ContentValidator()
        result = validator.detect_language_indicators(page_text)

        assert result.detected_language == "en", (
            f"Esperado 'en' mas obteve '{result.detected_language}'. "
            f"PT terms={pt_terms}, EN terms={en_terms}"
        )

    @given(
        brl_prices=st.lists(
            _brl_prices_strategy, min_size=1, max_size=5
        ),
    )
    @settings(max_examples=100)
    def test_brl_prices_detected_currency_brl(
        self,
        brl_prices: list[str],
    ) -> None:
        """Quando preços BRL presentes (sem USD), detected_currency == "BRL".

        **Validates: Requirements 9.1, 9.2**
        """
        page_text = _build_page_text(
            pt_terms=[],
            en_terms=[],
            brl_prices=brl_prices,
            usd_prices=[],
        )

        validator = ContentValidator()
        result = validator.detect_currency(page_text)

        assert result.detected_currency == "BRL", (
            f"Esperado 'BRL' mas obteve '{result.detected_currency}'. "
            f"BRL prices={brl_prices}"
        )

    @given(
        usd_prices=st.lists(
            _usd_prices_strategy, min_size=1, max_size=5
        ),
    )
    @settings(max_examples=100)
    def test_usd_prices_without_brl_detected_currency_usd(
        self,
        usd_prices: list[str],
    ) -> None:
        """Quando preços USD presentes sem BRL, detected_currency == "USD".

        **Validates: Requirements 9.1, 9.2**
        """
        page_text = _build_page_text(
            pt_terms=[],
            en_terms=[],
            brl_prices=[],
            usd_prices=usd_prices,
        )

        validator = ContentValidator()
        result = validator.detect_currency(page_text)

        assert result.detected_currency == "USD", (
            f"Esperado 'USD' mas obteve '{result.detected_currency}'. "
            f"USD prices={usd_prices}"
        )

    @given(
        pt_terms=st.lists(
            _pt_indicators_strategy, min_size=0, max_size=5, unique=True
        ),
        en_terms=st.lists(
            _en_indicators_strategy, min_size=0, max_size=6, unique=True
        ),
        brl_prices=st.lists(
            _brl_prices_strategy, min_size=0, max_size=5
        ),
        usd_prices=st.lists(
            _usd_prices_strategy, min_size=0, max_size=5
        ),
    )
    @settings(max_examples=200)
    def test_confidence_between_0_and_1(
        self,
        pt_terms: list[str],
        en_terms: list[str],
        brl_prices: list[str],
        usd_prices: list[str],
    ) -> None:
        """Confiança está sempre entre 0.0 e 1.0 inclusive.

        **Validates: Requirements 8.1, 8.2**
        """
        page_text = _build_page_text(
            pt_terms=pt_terms,
            en_terms=en_terms,
            brl_prices=brl_prices,
            usd_prices=usd_prices,
        )

        validator = ContentValidator()
        result = validator.detect_language_indicators(page_text)

        assert 0.0 <= result.confidence <= 1.0, (
            f"Confiança fora do range [0, 1]: {result.confidence}. "
            f"PT terms={pt_terms}, EN terms={en_terms}"
        )


# ============================================================================
# Property 9: URL Redirect Detection
# ============================================================================

from scraping_resilience.content_validator import ContentValidator
from scraping_resilience.models import RedirectCheckResult


# Estratégias de geração para URLs e padrões esperados
_expected_patterns = st.sampled_from(["/br/", "/pt/", "/brasil/"])

# Gerar domínios válidos para compor URLs
_domains = st.from_regex(
    r"[a-z]{3,10}\.(com|net|org)(\.[a-z]{2})?",
    fullmatch=True,
)

# Gerar paths que NÃO contêm nenhum dos padrões esperados
_path_segments = st.from_regex(
    r"/[a-z0-9]{1,15}",
    fullmatch=True,
)


@st.composite
def _url_with_pattern_in_path(draw: st.DrawFn) -> tuple[str, str]:
    """Gera (url, expected_pattern) onde o pattern ESTÁ no path."""
    domain = draw(_domains)
    pattern = draw(_expected_patterns)
    # Gerar path que contém o pattern esperado
    prefix = draw(
        st.from_regex(r"/[a-z0-9]{0,10}", fullmatch=True)
    )
    suffix = draw(
        st.from_regex(r"[a-z0-9]{0,10}", fullmatch=True)
    )
    path = f"{prefix}{pattern}{suffix}"
    url = f"https://{domain}{path}"
    return url, pattern


@st.composite
def _url_without_pattern_in_path(
    draw: st.DrawFn,
) -> tuple[str, str]:
    """Gera (url, expected_pattern) onde o pattern NÃO está no path."""
    domain = draw(_domains)
    pattern = draw(_expected_patterns)
    # Gerar segmentos de path que não contêm nenhum dos patterns
    num_segments = draw(st.integers(min_value=1, max_value=4))
    # Usar caracteres que não formam os patterns /br/, /pt/, /brasil/
    segments = [
        draw(
            st.from_regex(
                r"/[acdfghjklmnqsuvwxyz0-9]{1,10}",
                fullmatch=True,
            )
        )
        for _ in range(num_segments)
    ]
    path = "".join(segments)
    # Garantir que o pattern não está no path gerado
    if pattern in path:
        # Fallback: usar path garantidamente sem pattern
        path = "/plans/streaming/offers"
    url = f"https://{domain}{path}"
    return url, pattern


@pytest.mark.property
class TestURLRedirectDetection:
    """Property 9: URL redirect detection identifica divergências.

    Feature: scraping-resilience
    **Validates: Requirements 9.3**

    For any par de URLs (configurada, final), o RedirectChecker SHALL
    classificar como redirecionamento quando: o domínio difere, ou o
    path esperado (ex: "/br/") não está presente na URL final; e SHALL
    não classificar como redirecionamento quando a URL final contém o
    path esperado no mesmo domínio.
    """

    @given(data=_url_with_pattern_in_path())
    @settings(max_examples=200)
    def test_url_with_expected_pattern_not_redirected(
        self,
        data: tuple[str, str],
    ) -> None:
        """Quando URL contém expected_pattern no path → redirected == False.

        **Validates: Requirements 9.3**

        Se a URL final contém o path esperado, o sistema NÃO deve
        classificar como redirecionamento.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.redirected is False, (
            f"URL com pattern '{pattern}' no path foi "
            f"classificada como redirecionamento. "
            f"URL: {url}"
        )

    @given(data=_url_without_pattern_in_path())
    @settings(max_examples=200)
    def test_url_without_expected_pattern_is_redirected(
        self,
        data: tuple[str, str],
    ) -> None:
        """Quando URL NÃO contém expected_pattern no path → redirected == True.

        **Validates: Requirements 9.3**

        Se a URL final não contém o path esperado, o sistema DEVE
        classificar como redirecionamento.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.redirected is True, (
            f"URL sem pattern '{pattern}' no path NÃO foi "
            f"classificada como redirecionamento. "
            f"URL: {url}"
        )

    @given(data=_url_with_pattern_in_path())
    @settings(max_examples=100)
    def test_final_url_always_equals_input(
        self,
        data: tuple[str, str],
    ) -> None:
        """final_url no resultado sempre é igual à URL de entrada.

        **Validates: Requirements 9.3**

        O campo final_url do resultado deve preservar exatamente
        a URL que foi passada como argumento.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.final_url == url, (
            f"final_url no resultado ({result.final_url}) "
            f"difere da URL de entrada ({url})"
        )

    @given(data=_url_without_pattern_in_path())
    @settings(max_examples=100)
    def test_final_url_equals_input_when_redirected(
        self,
        data: tuple[str, str],
    ) -> None:
        """final_url preservada mesmo quando classificado como redirect.

        **Validates: Requirements 9.3**

        Independente da classificação, o campo final_url deve
        conter a URL fornecida sem alteração.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.final_url == url

    @given(
        data=st.one_of(
            _url_with_pattern_in_path(),
            _url_without_pattern_in_path(),
        )
    )
    @settings(max_examples=200)
    def test_expected_pattern_always_preserved(
        self,
        data: tuple[str, str],
    ) -> None:
        """expected_pattern no resultado sempre é igual ao input pattern.

        **Validates: Requirements 9.3**

        O campo expected_pattern do resultado deve preservar
        exatamente o padrão que foi passado como argumento.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.expected_pattern == pattern, (
            f"expected_pattern no resultado "
            f"({result.expected_pattern}) difere do "
            f"pattern de entrada ({pattern})"
        )

    @given(data=_url_without_pattern_in_path())
    @settings(max_examples=100)
    def test_mismatch_reason_not_none_when_redirected(
        self,
        data: tuple[str, str],
    ) -> None:
        """Quando redirected == True, mismatch_reason não é None.

        **Validates: Requirements 9.3**

        Toda classificação de redirecionamento deve incluir uma
        razão descritiva do porquê o redirect foi detectado.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.redirected is True
        assert result.mismatch_reason is not None, (
            f"mismatch_reason é None para URL redirecionada. "
            f"URL: {url}, pattern: {pattern}"
        )
        assert len(result.mismatch_reason) > 0, (
            f"mismatch_reason está vazio para URL redirecionada. "
            f"URL: {url}, pattern: {pattern}"
        )

    @given(data=_url_with_pattern_in_path())
    @settings(max_examples=100)
    def test_mismatch_reason_none_when_not_redirected(
        self,
        data: tuple[str, str],
    ) -> None:
        """Quando redirected == False, mismatch_reason é None.

        **Validates: Requirements 9.3**

        Se não há redirecionamento, não há razão para reportar.
        """
        url, pattern = data
        validator = ContentValidator()
        result = validator.check_url_redirect(url, pattern)

        assert result.redirected is False
        assert result.mismatch_reason is None, (
            f"mismatch_reason não é None para URL sem redirect. "
            f"URL: {url}, pattern: {pattern}, "
            f"reason: {result.mismatch_reason}"
        )


# ============================================================================
# Property 4: Health Check Scoring
# ============================================================================

from src.scraping_resilience.health_check_scorer import HealthCheckScorer
from src.scraping_resilience.models import (
    ContentValidationResult,
    HealthCheckScore,
)


@pytest.mark.property
class TestHealthCheckScoring:
    """Property 4: Health check scoring classifica corretamente.

    Feature: scraping-resilience
    **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

    For any combinação de (erro de rede presente ou não, validação de
    conteúdo válida ou não com tipo de falha geo, extração bem-sucedida
    ou não), o HealthCheckScorer SHALL atribuir exatamente um dos scores
    {SUCCESS, GEO_MISMATCH, GEO_REDIRECT, SCRAPER_ERROR, NETWORK_ERROR}
    seguindo a prioridade: NETWORK_ERROR > GEO_REDIRECT > GEO_MISMATCH >
    SCRAPER_ERROR > SUCCESS, e SHALL incluir razão descritiva não-vazia
    quando o score for GEO_MISMATCH ou GEO_REDIRECT, e SHALL sinalizar
    extração como "skipped" quando score for GEO_MISMATCH ou GEO_REDIRECT.
    """

    @given(
        network_error=st.booleans(),
        extraction_success=st.booleans(),
        validation_score=st.sampled_from(
            [None, HealthCheckScore.SUCCESS,
             HealthCheckScore.GEO_MISMATCH,
             HealthCheckScore.GEO_REDIRECT]
        ),
    )
    @settings(max_examples=100)
    def test_network_error_always_yields_network_error(
        self,
        network_error: bool,
        extraction_success: bool,
        validation_score: HealthCheckScore | None,
    ) -> None:
        """Priority: network_error=True always yields NETWORK_ERROR.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Independente dos valores de extraction_success e
        validation_score, quando network_error=True o resultado
        DEVE ser NETWORK_ERROR (prioridade máxima).
        """
        if not network_error:
            return

        # Montar validation_result se validation_score não é None
        validation_result = None
        if validation_score is not None:
            validation_result = ContentValidationResult(
                is_valid=(validation_score == HealthCheckScore.SUCCESS),
                health_check_score=validation_score,
                reason=(
                    f"teste {validation_score.value}"
                    if validation_score != HealthCheckScore.SUCCESS
                    else None
                ),
            )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=True,
        )

        assert score == HealthCheckScore.NETWORK_ERROR
        assert extraction_skipped is False

    @given(
        extraction_success=st.booleans(),
    )
    @settings(max_examples=50)
    def test_geo_redirect_yields_geo_redirect_when_no_network_error(
        self,
        extraction_success: bool,
    ) -> None:
        """Priority: GEO_REDIRECT in validation yields GEO_REDIRECT.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Quando network_error=False e validation_result indica
        GEO_REDIRECT, o resultado DEVE ser GEO_REDIRECT
        independente de extraction_success.
        """
        validation_result = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_REDIRECT,
            reason="URL redirecionada para /us/gift-cards",
        )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_REDIRECT
        assert extraction_skipped is True
        assert reason is not None
        assert len(reason) > 0

    @given(
        extraction_success=st.booleans(),
    )
    @settings(max_examples=50)
    def test_geo_mismatch_yields_geo_mismatch_when_no_network_or_redirect(
        self,
        extraction_success: bool,
    ) -> None:
        """Priority: GEO_MISMATCH yields GEO_MISMATCH when no network/redirect.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Quando network_error=False e validation_result indica
        GEO_MISMATCH, o resultado DEVE ser GEO_MISMATCH
        independente de extraction_success.
        """
        validation_result = ContentValidationResult(
            is_valid=False,
            health_check_score=HealthCheckScore.GEO_MISMATCH,
            reason="idioma inglês detectado, moeda USD",
        )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=False,
        )

        assert score == HealthCheckScore.GEO_MISMATCH
        assert extraction_skipped is True
        assert reason is not None
        assert len(reason) > 0

    @given(
        network_error=st.booleans(),
        extraction_success=st.booleans(),
        validation_score=st.sampled_from(
            [None, HealthCheckScore.SUCCESS,
             HealthCheckScore.GEO_MISMATCH,
             HealthCheckScore.GEO_REDIRECT]
        ),
    )
    @settings(max_examples=200)
    def test_reason_non_empty_for_geo_scores(
        self,
        network_error: bool,
        extraction_success: bool,
        validation_score: HealthCheckScore | None,
    ) -> None:
        """Reason non-empty: when result is GEO_MISMATCH or GEO_REDIRECT.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Quando o score final é GEO_MISMATCH ou GEO_REDIRECT, a
        razão DEVE ser não-None e ter comprimento > 0.
        """
        validation_result = None
        if validation_score is not None:
            validation_result = ContentValidationResult(
                is_valid=(validation_score == HealthCheckScore.SUCCESS),
                health_check_score=validation_score,
                reason=(
                    f"razão para {validation_score.value}"
                    if validation_score != HealthCheckScore.SUCCESS
                    else None
                ),
            )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=network_error,
        )

        if score in (
            HealthCheckScore.GEO_MISMATCH,
            HealthCheckScore.GEO_REDIRECT,
        ):
            assert reason is not None, (
                f"Razão é None para score={score.value}"
            )
            assert len(reason) > 0, (
                f"Razão é vazia para score={score.value}"
            )

    @given(
        network_error=st.booleans(),
        extraction_success=st.booleans(),
        validation_score=st.sampled_from(
            [None, HealthCheckScore.SUCCESS,
             HealthCheckScore.GEO_MISMATCH,
             HealthCheckScore.GEO_REDIRECT]
        ),
    )
    @settings(max_examples=200)
    def test_extraction_skipped_for_geo_scores(
        self,
        network_error: bool,
        extraction_success: bool,
        validation_score: HealthCheckScore | None,
    ) -> None:
        """Extraction skipped: when result is GEO_MISMATCH or GEO_REDIRECT.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Quando o score final é GEO_MISMATCH ou GEO_REDIRECT,
        extraction_skipped DEVE ser True.
        """
        validation_result = None
        if validation_score is not None:
            validation_result = ContentValidationResult(
                is_valid=(validation_score == HealthCheckScore.SUCCESS),
                health_check_score=validation_score,
                reason=(
                    f"razão para {validation_score.value}"
                    if validation_score != HealthCheckScore.SUCCESS
                    else None
                ),
            )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=network_error,
        )

        if score in (
            HealthCheckScore.GEO_MISMATCH,
            HealthCheckScore.GEO_REDIRECT,
        ):
            assert extraction_skipped is True, (
                f"extraction_skipped deveria ser True para "
                f"score={score.value}, mas é {extraction_skipped}"
            )

    @given(
        network_error=st.booleans(),
        extraction_success=st.booleans(),
        validation_score=st.sampled_from(
            [None, HealthCheckScore.SUCCESS,
             HealthCheckScore.GEO_MISMATCH,
             HealthCheckScore.GEO_REDIRECT]
        ),
    )
    @settings(max_examples=200)
    def test_extraction_not_skipped_for_non_geo_scores(
        self,
        network_error: bool,
        extraction_success: bool,
        validation_score: HealthCheckScore | None,
    ) -> None:
        """Extraction NOT skipped for SUCCESS/SCRAPER_ERROR/NETWORK_ERROR.

        **Validates: Requirements 2.4, 5.1, 5.3, 5.4**

        Quando o score final é SUCCESS, SCRAPER_ERROR ou
        NETWORK_ERROR, extraction_skipped DEVE ser False.
        """
        validation_result = None
        if validation_score is not None:
            validation_result = ContentValidationResult(
                is_valid=(validation_score == HealthCheckScore.SUCCESS),
                health_check_score=validation_score,
                reason=(
                    f"razão para {validation_score.value}"
                    if validation_score != HealthCheckScore.SUCCESS
                    else None
                ),
            )

        scorer = HealthCheckScorer()
        score, reason, extraction_skipped = scorer.score(
            validation_result=validation_result,
            extraction_success=extraction_success,
            network_error=network_error,
        )

        if score in (
            HealthCheckScore.SUCCESS,
            HealthCheckScore.SCRAPER_ERROR,
            HealthCheckScore.NETWORK_ERROR,
        ):
            assert extraction_skipped is False, (
                f"extraction_skipped deveria ser False para "
                f"score={score.value}, mas é {extraction_skipped}"
            )


# ============================================================================
# Property 10: Cascade Strategy aplica estratégias em ordem e para na
#              primeira bem-sucedida
# ============================================================================

from src.scraping_resilience.component_interactor import (
    CustomComponentInteractor,
)
from src.scraping_resilience.models import ComponentType, InteractionResult


def _make_mock_strategy(
    name: str,
    can_handle: bool,
    succeeds: bool,
    call_log: list[str],
) -> AsyncMock:
    """Cria uma mock strategy com comportamento configurável.

    Args:
        name: Identificador da estratégia (para rastreio de ordem).
        can_handle: Se a estratégia pode lidar com o componente.
        succeeds: Se a interação tem sucesso (só relevante se can_handle=True).
        call_log: Lista mutável para registrar ordem de chamadas.

    Returns:
        AsyncMock que implementa ComponentInteractionStrategy.
    """
    strategy = AsyncMock()

    async def mock_can_handle(page, selector):
        call_log.append(f"{name}:can_handle")
        return can_handle

    async def mock_interact(page, selector, value):
        call_log.append(f"{name}:interact")
        return InteractionResult(
            success=succeeds,
            strategy_used=name,
            component_type=ComponentType.UNKNOWN,
            error=None if succeeds else f"{name}_failed",
        )

    strategy.can_handle = AsyncMock(side_effect=mock_can_handle)
    strategy.interact = AsyncMock(side_effect=mock_interact)

    return strategy


@pytest.mark.property
class TestCascadeStrategyOrdering:
    """Property 10: Cascade strategy aplica estratégias em ordem e para
    na primeira bem-sucedida.

    Feature: scraping-resilience
    **Validates: Requirements 7.1, 7.4**

    For any sequência de N estratégias onde a K-ésima (K ≤ N) é a
    primeira que pode lidar com o componente e tem sucesso, o
    CustomComponentInteractor SHALL tentar exatamente K estratégias
    na ordem definida e retornar o resultado da K-ésima; e quando
    todas as N falham, SHALL retornar erro com código
    "custom_dropdown_interaction_failed".
    """

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
        success_index=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=100)
    async def test_stops_at_first_successful_strategy(
        self,
        num_strategies: int,
        success_index: int,
    ) -> None:
        """Para na K-ésima estratégia quando é a primeira bem-sucedida.

        **Validates: Requirements 7.1, 7.4**

        Dado N estratégias e a K-ésima (0-indexed) como primeira
        que pode lidar E tem sucesso, o interactor deve tentar
        exatamente as estratégias 0..K e parar.
        """
        # Ajustar success_index para estar dentro do range válido
        effective_success_idx = success_index % num_strategies
        call_log: list[str] = []

        # Criar estratégias mock: anteriores a K não podem lidar ou falham,
        # K pode lidar e tem sucesso, posteriores não devem ser chamadas
        strategies = []
        for i in range(num_strategies):
            if i < effective_success_idx:
                # Anteriores: podem tentar can_handle mas retornam False
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=False,
                        succeeds=False,
                        call_log=call_log,
                    )
                )
            elif i == effective_success_idx:
                # K-ésima: pode lidar e tem sucesso
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=True,
                        succeeds=True,
                        call_log=call_log,
                    )
                )
            else:
                # Posteriores: não devem ser chamadas
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=True,
                        succeeds=True,
                        call_log=call_log,
                    )
                )

        # Substituir _strategies do interactor com nossos mocks
        interactor = CustomComponentInteractor()
        interactor._strategies = strategies

        page = AsyncMock()
        # Mock detect_component_type para não depender do DOM
        page.wait_for_selector = AsyncMock(return_value=None)

        result = await interactor.interact(
            page=page,
            selector=".dropdown",
            desired_value="São Paulo",
        )

        # PROPRIEDADE 1: Resultado é sucesso
        assert result.success is True, (
            f"Esperava sucesso na strategy_{effective_success_idx}, "
            f"mas resultado foi failure. Call log: {call_log}"
        )

        # PROPRIEDADE 2: Estratégia usada é a K-ésima
        assert result.strategy_used == f"strategy_{effective_success_idx}", (
            f"Esperava strategy_used='strategy_{effective_success_idx}', "
            f"mas obteve '{result.strategy_used}'. Call log: {call_log}"
        )

        # PROPRIEDADE 3: Estratégias posteriores a K NÃO foram chamadas
        for i in range(effective_success_idx + 1, num_strategies):
            assert f"strategy_{i}:can_handle" not in call_log, (
                f"strategy_{i} foi chamada mesmo após sucesso em "
                f"strategy_{effective_success_idx}. Call log: {call_log}"
            )

        # PROPRIEDADE 4: Ordem é estritamente crescente (0, 1, ..., K)
        can_handle_calls = [
            entry for entry in call_log
            if entry.endswith(":can_handle")
        ]
        for i in range(len(can_handle_calls) - 1):
            current_name = can_handle_calls[i].split(":")[0]
            next_name = can_handle_calls[i + 1].split(":")[0]
            current_idx = int(current_name.split("_")[1])
            next_idx = int(next_name.split("_")[1])
            assert current_idx < next_idx, (
                f"Ordem de chamada incorreta: {current_name} → "
                f"{next_name}. Call log: {call_log}"
            )

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    async def test_all_fail_returns_custom_dropdown_error(
        self,
        num_strategies: int,
    ) -> None:
        """Quando todas as N estratégias falham, retorna erro correto.

        **Validates: Requirements 7.1, 7.4**

        Quando todas as estratégias podem lidar (can_handle=True)
        mas falham (interact retorna success=False), o resultado
        final deve ter error="custom_dropdown_interaction_failed".
        """
        call_log: list[str] = []

        # Todas as estratégias podem lidar mas falham
        strategies = []
        for i in range(num_strategies):
            strategies.append(
                _make_mock_strategy(
                    name=f"strategy_{i}",
                    can_handle=True,
                    succeeds=False,
                    call_log=call_log,
                )
            )

        interactor = CustomComponentInteractor()
        interactor._strategies = strategies

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        result = await interactor.interact(
            page=page,
            selector=".dropdown",
            desired_value="São Paulo",
        )

        # PROPRIEDADE: Resultado é falha com erro específico
        assert result.success is False, (
            f"Esperava failure quando todas falham. "
            f"Call log: {call_log}"
        )
        assert result.error == "custom_dropdown_interaction_failed", (
            f"Esperava erro 'custom_dropdown_interaction_failed', "
            f"mas obteve '{result.error}'. Call log: {call_log}"
        )

        # PROPRIEDADE: TODAS as estratégias foram tentadas
        for i in range(num_strategies):
            assert f"strategy_{i}:can_handle" in call_log, (
                f"strategy_{i} não foi tentada. Call log: {call_log}"
            )
            assert f"strategy_{i}:interact" in call_log, (
                f"strategy_{i}:interact não foi chamada. "
                f"Call log: {call_log}"
            )

    @given(
        num_strategies=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=50)
    async def test_all_cant_handle_returns_error(
        self,
        num_strategies: int,
    ) -> None:
        """Quando nenhuma estratégia pode lidar, retorna erro.

        **Validates: Requirements 7.1, 7.4**

        Quando todas as estratégias retornam can_handle=False,
        o resultado deve ser erro (nenhuma interação tentada).
        """
        call_log: list[str] = []

        # Nenhuma estratégia pode lidar com o componente
        strategies = []
        for i in range(num_strategies):
            strategies.append(
                _make_mock_strategy(
                    name=f"strategy_{i}",
                    can_handle=False,
                    succeeds=False,
                    call_log=call_log,
                )
            )

        interactor = CustomComponentInteractor()
        interactor._strategies = strategies

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        result = await interactor.interact(
            page=page,
            selector=".dropdown",
            desired_value="São Paulo",
        )

        # PROPRIEDADE: Resultado é falha
        assert result.success is False, (
            f"Esperava failure quando nenhuma pode lidar. "
            f"Call log: {call_log}"
        )
        assert result.error == "custom_dropdown_interaction_failed", (
            f"Esperava erro 'custom_dropdown_interaction_failed', "
            f"mas obteve '{result.error}'. Call log: {call_log}"
        )

        # PROPRIEDADE: can_handle foi chamado para todas
        for i in range(num_strategies):
            assert f"strategy_{i}:can_handle" in call_log, (
                f"strategy_{i}:can_handle não foi chamada. "
                f"Call log: {call_log}"
            )

        # PROPRIEDADE: interact NÃO foi chamado (nenhuma pode lidar)
        interact_calls = [
            entry for entry in call_log
            if entry.endswith(":interact")
        ]
        assert len(interact_calls) == 0, (
            f"interact foi chamado mesmo sem can_handle=True. "
            f"Interact calls: {interact_calls}"
        )

    @given(
        num_strategies=st.integers(min_value=2, max_value=5),
        success_index=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=100)
    async def test_exactly_k_strategies_tried_in_order(
        self,
        num_strategies: int,
        success_index: int,
    ) -> None:
        """Exatamente K estratégias são tentadas na ordem 0..K-1.

        **Validates: Requirements 7.1, 7.4**

        Quando a K-ésima (0-indexed) estratégia é a primeira que
        pode lidar e tem sucesso, exatamente K+1 chamadas de
        can_handle devem ocorrer (0 até K inclusive).
        """
        effective_success_idx = success_index % num_strategies
        call_log: list[str] = []

        strategies = []
        for i in range(num_strategies):
            if i < effective_success_idx:
                # Pode lidar mas falha (para testar que tenta seguinte)
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=True,
                        succeeds=False,
                        call_log=call_log,
                    )
                )
            elif i == effective_success_idx:
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=True,
                        succeeds=True,
                        call_log=call_log,
                    )
                )
            else:
                strategies.append(
                    _make_mock_strategy(
                        name=f"strategy_{i}",
                        can_handle=True,
                        succeeds=True,
                        call_log=call_log,
                    )
                )

        interactor = CustomComponentInteractor()
        interactor._strategies = strategies

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        result = await interactor.interact(
            page=page,
            selector=".dropdown",
            desired_value="São Paulo",
        )

        # Contar can_handle calls
        can_handle_calls = [
            entry for entry in call_log
            if entry.endswith(":can_handle")
        ]

        # Exatamente K+1 chamadas de can_handle (indices 0..K)
        expected_can_handle_count = effective_success_idx + 1
        assert len(can_handle_calls) == expected_can_handle_count, (
            f"Esperava {expected_can_handle_count} can_handle calls, "
            f"mas obteve {len(can_handle_calls)}. "
            f"success_index={effective_success_idx}, "
            f"Call log: {call_log}"
        )

        # Resultado é a K-ésima estratégia
        assert result.success is True
        assert result.strategy_used == f"strategy_{effective_success_idx}"


# ============================================================================
# Property 11: Component Type Detection
# ============================================================================

from scraping_resilience.component_interactor import (
    CustomComponentInteractor,
)
from scraping_resilience.models import ComponentType


# Estratégias de geração para atributos DOM

# Tag names possíveis (inclui select nativo e outras tags)
_tag_names = st.sampled_from(
    ["select", "div", "span", "input", "button", "ul", "li"]
)

# Roles possíveis (inclui combobox e outros/nenhum)
_roles = st.sampled_from(
    ["combobox", "listbox", "menu", "option", "textbox", ""]
)

# Classes CSS indicativas de frameworks de componentes
_framework_classes = st.sampled_from(
    [
        "react-select__control",
        "react-select__menu",
        "MuiSelect-root",
        "MuiAutocomplete-root",
        "select2-container",
        "select2-selection",
        "custom-dropdown",
        "form-control",
        "",
    ]
)


def _make_component_page_mock(
    tag_name: str, role: str, class_name: str
) -> AsyncMock:
    """Cria mock de Page que simula atributos DOM de um elemento."""
    page = AsyncMock()
    element = AsyncMock()

    async def mock_evaluate(js_expr: str) -> str:
        if "tagName" in js_expr:
            return tag_name
        if "role" in js_expr or "getAttribute('role')" in js_expr:
            return role
        if "className" in js_expr:
            return class_name
        return ""

    element.evaluate = mock_evaluate
    page.wait_for_selector = AsyncMock(return_value=element)
    return page


def _expected_component_type(
    tag_name: str, role: str, class_name: str
) -> ComponentType:
    """Calcula o ComponentType esperado segundo a prioridade de detecção.

    Prioridade:
    1. Tag <select> → NATIVE_SELECT
    2. role="combobox" → COMBOBOX
    3. Classe contendo "react-select" → REACT_SELECT
    4. Classe contendo "MuiSelect" ou "MuiAutocomplete" → MATERIAL_UI
    5. Classe contendo "select2" → SELECT2
    6. Nenhum padrão → UNKNOWN
    """
    if tag_name == "select":
        return ComponentType.NATIVE_SELECT
    if role == "combobox":
        return ComponentType.COMBOBOX
    if "react-select" in class_name:
        return ComponentType.REACT_SELECT
    if "MuiSelect" in class_name or "MuiAutocomplete" in class_name:
        return ComponentType.MATERIAL_UI
    if "select2" in class_name:
        return ComponentType.SELECT2
    return ComponentType.UNKNOWN


@pytest.mark.property
class TestComponentTypeDetection:
    """Property 11: Component type detection classifica corretamente por atributos DOM.

    Feature: scraping-resilience
    **Validates: Requirements 7.5, 10.1**

    For any conjunto de atributos DOM de um elemento (presença de tag
    select, atributo role="combobox", classe contendo "react-select",
    classe contendo "MuiSelect"/"MuiAutocomplete", classe contendo
    "select2"), o detector SHALL classificar o componente no tipo correto:
    NATIVE_SELECT, REACT_SELECT, MATERIAL_UI, SELECT2 ou COMBOBOX
    respectivamente; e UNKNOWN quando nenhum padrão é reconhecido.
    """

    @given(
        tag_name=_tag_names,
        role=_roles,
        class_name=_framework_classes,
    )
    @settings(max_examples=200)
    async def test_detection_matches_priority_rules(
        self,
        tag_name: str,
        role: str,
        class_name: str,
    ) -> None:
        """Detecção segue regras de prioridade definidas.

        **Validates: Requirements 7.5, 10.1**

        Para qualquer combinação de (tag_name, role, class_name),
        o tipo detectado DEVE corresponder à regra de maior
        prioridade satisfeita.
        """
        page = _make_component_page_mock(tag_name, role, class_name)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".some-selector"
        )
        expected = _expected_component_type(tag_name, role, class_name)

        assert detected == expected, (
            f"Detecção incorreta: tag={tag_name!r}, role={role!r}, "
            f"class={class_name!r} → detectou {detected.value}, "
            f"esperado {expected.value}"
        )

    @given(
        role=_roles,
        class_name=_framework_classes,
    )
    @settings(max_examples=50)
    async def test_native_select_tag_always_native(
        self,
        role: str,
        class_name: str,
    ) -> None:
        """Tag <select> SEMPRE resulta em NATIVE_SELECT (prioridade máxima).

        **Validates: Requirements 7.5, 10.1**

        Independente dos valores de role e class_name, se a tag
        é "select", o tipo DEVE ser NATIVE_SELECT.
        """
        page = _make_component_page_mock("select", role, class_name)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".dropdown"
        )

        assert detected == ComponentType.NATIVE_SELECT, (
            f"Tag select com role={role!r} e class={class_name!r} "
            f"deveria ser NATIVE_SELECT, mas foi {detected.value}"
        )

    @given(
        tag_name=st.sampled_from(["div", "span", "input", "button"]),
        class_name=_framework_classes,
    )
    @settings(max_examples=50)
    async def test_combobox_role_when_not_select_tag(
        self,
        tag_name: str,
        class_name: str,
    ) -> None:
        """role="combobox" em tag não-select resulta em COMBOBOX.

        **Validates: Requirements 7.5, 10.1**

        Quando tag não é "select" mas role é "combobox", o tipo
        DEVE ser COMBOBOX (segunda prioridade).
        """
        page = _make_component_page_mock(tag_name, "combobox", class_name)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".combobox-element"
        )

        assert detected == ComponentType.COMBOBOX, (
            f"Tag {tag_name!r} com role=combobox e "
            f"class={class_name!r} deveria ser COMBOBOX, "
            f"mas foi {detected.value}"
        )

    @given(
        tag_name=st.sampled_from(["div", "span", "input", "button"]),
        role=st.sampled_from(["listbox", "menu", "option", "textbox", ""]),
    )
    @settings(max_examples=50)
    async def test_react_select_class_detection(
        self,
        tag_name: str,
        role: str,
    ) -> None:
        """Classe "react-select" (sem tag select/role combobox) → REACT_SELECT.

        **Validates: Requirements 7.5, 10.1**

        Quando tag não é "select", role não é "combobox" e classe
        contém "react-select", o tipo DEVE ser REACT_SELECT.
        """
        page = _make_component_page_mock(
            tag_name, role, "react-select__control"
        )
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".react-dropdown"
        )

        assert detected == ComponentType.REACT_SELECT, (
            f"Tag {tag_name!r} com role={role!r} e classe "
            f"react-select deveria ser REACT_SELECT, "
            f"mas foi {detected.value}"
        )

    @given(
        tag_name=st.sampled_from(["div", "span", "input", "button"]),
        role=st.sampled_from(["listbox", "menu", "option", "textbox", ""]),
        mui_class=st.sampled_from(
            ["MuiSelect-root", "MuiAutocomplete-root",
             "MuiSelect-select", "MuiAutocomplete-popper"]
        ),
    )
    @settings(max_examples=50)
    async def test_material_ui_class_detection(
        self,
        tag_name: str,
        role: str,
        mui_class: str,
    ) -> None:
        """Classe MuiSelect/MuiAutocomplete → MATERIAL_UI.

        **Validates: Requirements 7.5, 10.1**

        Quando tag não é "select", role não é "combobox", sem
        "react-select" na classe, mas classe contém "MuiSelect"
        ou "MuiAutocomplete", o tipo DEVE ser MATERIAL_UI.
        """
        page = _make_component_page_mock(tag_name, role, mui_class)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".mui-dropdown"
        )

        assert detected == ComponentType.MATERIAL_UI, (
            f"Tag {tag_name!r} com role={role!r} e classe "
            f"{mui_class!r} deveria ser MATERIAL_UI, "
            f"mas foi {detected.value}"
        )

    @given(
        tag_name=st.sampled_from(["div", "span", "input", "button"]),
        role=st.sampled_from(["listbox", "menu", "option", "textbox", ""]),
        select2_class=st.sampled_from(
            ["select2-container", "select2-selection",
             "select2-hidden-accessible"]
        ),
    )
    @settings(max_examples=50)
    async def test_select2_class_detection(
        self,
        tag_name: str,
        role: str,
        select2_class: str,
    ) -> None:
        """Classe "select2" → SELECT2.

        **Validates: Requirements 7.5, 10.1**

        Quando tag não é "select", role não é "combobox", sem
        "react-select" ou "Mui*" na classe, mas classe contém
        "select2", o tipo DEVE ser SELECT2.
        """
        page = _make_component_page_mock(tag_name, role, select2_class)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".select2-element"
        )

        assert detected == ComponentType.SELECT2, (
            f"Tag {tag_name!r} com role={role!r} e classe "
            f"{select2_class!r} deveria ser SELECT2, "
            f"mas foi {detected.value}"
        )

    @given(
        tag_name=st.sampled_from(["div", "span", "input", "button"]),
        role=st.sampled_from(["listbox", "menu", "option", "textbox", ""]),
        class_name=st.sampled_from(
            ["custom-dropdown", "form-control", "my-widget", ""]
        ),
    )
    @settings(max_examples=50)
    async def test_no_pattern_results_in_unknown(
        self,
        tag_name: str,
        role: str,
        class_name: str,
    ) -> None:
        """Sem padrão reconhecido → UNKNOWN.

        **Validates: Requirements 7.5, 10.1**

        Quando nenhuma regra de detecção é satisfeita (tag não é
        "select", role não é "combobox", classe não contém nenhum
        framework conhecido), o tipo DEVE ser UNKNOWN.
        """
        page = _make_component_page_mock(tag_name, role, class_name)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".unknown-element"
        )

        assert detected == ComponentType.UNKNOWN, (
            f"Tag {tag_name!r} com role={role!r} e classe "
            f"{class_name!r} deveria ser UNKNOWN, "
            f"mas foi {detected.value}"
        )

    @given(
        tag_name=_tag_names,
        role=_roles,
        class_name=_framework_classes,
    )
    @settings(max_examples=200)
    async def test_result_always_valid_component_type(
        self,
        tag_name: str,
        role: str,
        class_name: str,
    ) -> None:
        """Resultado é SEMPRE um valor válido de ComponentType.

        **Validates: Requirements 7.5, 10.1**

        Para qualquer combinação de atributos DOM, o resultado
        DEVE ser um dos valores definidos no enum ComponentType.
        """
        page = _make_component_page_mock(tag_name, role, class_name)
        interactor = CustomComponentInteractor()

        detected = await interactor.detect_component_type(
            page, ".any-selector"
        )

        valid_types = {ct for ct in ComponentType}
        assert detected in valid_types, (
            f"Tipo detectado {detected!r} não é um "
            f"ComponentType válido. Atributos: tag={tag_name!r}, "
            f"role={role!r}, class={class_name!r}"
        )


# ============================================================================
# Property 12: City selection com fallback para primeira disponível
# ============================================================================

from src.scraping_resilience.component_interactor import (
    CustomComponentInteractor,
)
from src.scraping_resilience.models import (
    ComponentType,
    InteractionResult,
)

# Estratégias de geração para listas de cidades

# Nomes de cidades brasileiras realistas (sem "São Paulo")
_other_cities = st.sampled_from([
    "Rio de Janeiro",
    "Belo Horizonte",
    "Curitiba",
    "Porto Alegre",
    "Salvador",
    "Fortaleza",
    "Recife",
    "Brasília",
    "Manaus",
    "Goiânia",
    "Campinas",
    "Florianópolis",
    "Vitória",
    "Belém",
    "Natal",
])

# Gerar lista de cidades que NÃO contém "São Paulo"
_cities_without_sp = st.lists(
    _other_cities, min_size=1, max_size=8, unique=True
)

# Gerar lista de cidades que CONTÉM "São Paulo"
_cities_with_sp = st.builds(
    lambda cities, insert_pos: (
        cities[:insert_pos] + ["São Paulo"] + cities[insert_pos:]
    ),
    cities=st.lists(
        _other_cities, min_size=0, max_size=7, unique=True
    ),
    insert_pos=st.integers(min_value=0, max_value=7),
).filter(lambda lst: "São Paulo" in lst)


def _make_tracking_strategy(
    accepted_values: list[str],
    attempted_values: list[str],
) -> AsyncMock:
    """Cria uma estratégia mock que rastreia valores tentados.

    A estratégia aceita interagir com qualquer componente (can_handle=True)
    e tem sucesso apenas quando o valor está em accepted_values.
    Registra todos os valores tentados em attempted_values.
    """
    strategy = AsyncMock()
    strategy.can_handle = AsyncMock(return_value=True)

    async def mock_interact(
        page, selector: str, value: str
    ) -> InteractionResult:
        attempted_values.append(value)
        if value in accepted_values:
            return InteractionResult(
                success=True,
                strategy_used="mock_strategy",
                component_type=ComponentType.NATIVE_SELECT,
            )
        return InteractionResult(
            success=False,
            strategy_used="mock_strategy",
            component_type=ComponentType.NATIVE_SELECT,
            error=f"value '{value}' not in available cities",
        )

    strategy.interact = AsyncMock(side_effect=mock_interact)
    return strategy


@pytest.mark.property
class TestCitySelectionWithFallback:
    """Property 12: City selection com fallback para primeira disponível.

    Feature: scraping-resilience
    **Validates: Requirements 7.2**

    For any lista de cidades disponíveis em um dropdown, o sistema
    SHALL selecionar "São Paulo" quando presente na lista, e SHALL
    selecionar a primeira cidade não-vazia e não-desabilitada quando
    "São Paulo" não está disponível.
    """

    @given(cities=_cities_with_sp)
    @settings(max_examples=100)
    async def test_sao_paulo_selected_when_present(
        self,
        cities: list[str],
    ) -> None:
        """Quando "São Paulo" está na lista, desired_value é usado.

        **Validates: Requirements 7.2**

        Se a lista de cidades contém "São Paulo", o interactor
        deve tentar "São Paulo" como desired_value e ter sucesso
        sem recorrer ao fallback.
        """
        attempted_values: list[str] = []
        mock_strategy = _make_tracking_strategy(
            accepted_values=cities,
            attempted_values=attempted_values,
        )

        interactor = CustomComponentInteractor()
        # Substituir estratégias por nossa mock
        interactor._strategies = [mock_strategy]

        page = AsyncMock()
        # Mock detect_component_type
        page.wait_for_selector = AsyncMock(return_value=None)

        fallback_city = cities[0] if cities[0] != "São Paulo" else (
            cities[1] if len(cities) > 1 else None
        )

        result = await interactor.interact(
            page=page,
            selector=".city-dropdown",
            desired_value="São Paulo",
            fallback_value=fallback_city,
        )

        assert result.success is True
        # "São Paulo" deve ser o primeiro valor tentado
        assert attempted_values[0] == "São Paulo", (
            f"Primeiro valor tentado deveria ser 'São Paulo', "
            f"mas foi '{attempted_values[0]}'. "
            f"Cidades disponíveis: {cities}"
        )
        # O resultado deve ter sucesso sem necessitar do fallback
        assert "São Paulo" in attempted_values

    @given(cities=_cities_without_sp)
    @settings(max_examples=100)
    async def test_fallback_used_when_sao_paulo_absent(
        self,
        cities: list[str],
    ) -> None:
        """Quando "São Paulo" NÃO está na lista, fallback_value é usado.

        **Validates: Requirements 7.2**

        Se a lista de cidades NÃO contém "São Paulo", o interactor
        deve primeiro tentar "São Paulo" (que falhará), e então
        recorrer ao fallback_value (primeira cidade disponível).
        """
        attempted_values: list[str] = []
        mock_strategy = _make_tracking_strategy(
            accepted_values=cities,
            attempted_values=attempted_values,
        )

        interactor = CustomComponentInteractor()
        interactor._strategies = [mock_strategy]

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        # Fallback é a primeira cidade disponível na lista
        fallback_city = cities[0]

        result = await interactor.interact(
            page=page,
            selector=".city-dropdown",
            desired_value="São Paulo",
            fallback_value=fallback_city,
        )

        assert result.success is True
        # "São Paulo" deve ter sido tentado primeiro (e falhado)
        assert attempted_values[0] == "São Paulo", (
            f"Primeiro valor tentado deveria ser 'São Paulo', "
            f"mas foi '{attempted_values[0]}'. "
            f"Cidades: {cities}"
        )
        # Fallback deve ter sido tentado depois
        assert fallback_city in attempted_values, (
            f"Fallback '{fallback_city}' deveria ter sido tentado. "
            f"Valores tentados: {attempted_values}"
        )
        # Fallback deve vir APÓS "São Paulo" na sequência
        sp_idx = attempted_values.index("São Paulo")
        fb_idx = attempted_values.index(fallback_city)
        assert sp_idx < fb_idx, (
            f"'São Paulo' (idx={sp_idx}) deveria vir antes do "
            f"fallback '{fallback_city}' (idx={fb_idx}). "
            f"Sequência: {attempted_values}"
        )

    @given(cities=_cities_without_sp)
    @settings(max_examples=100)
    async def test_fallback_is_first_available_city(
        self,
        cities: list[str],
    ) -> None:
        """O fallback_value passado ao interactor é a primeira cidade.

        **Validates: Requirements 7.2**

        Quando "São Paulo" não está disponível, o fallback deve ser
        a primeira cidade não-vazia e não-desabilitada da lista,
        que é cities[0]. Verificamos que o valor usado como fallback
        é exatamente o primeiro da lista.
        """
        attempted_values: list[str] = []
        mock_strategy = _make_tracking_strategy(
            accepted_values=cities,
            attempted_values=attempted_values,
        )

        interactor = CustomComponentInteractor()
        interactor._strategies = [mock_strategy]

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        # A primeira cidade não-vazia da lista
        first_city = cities[0]

        result = await interactor.interact(
            page=page,
            selector=".city-dropdown",
            desired_value="São Paulo",
            fallback_value=first_city,
        )

        assert result.success is True
        # O valor que teve sucesso deve ser o first_city (fallback)
        # pois "São Paulo" não está em cities
        successful_value = next(
            v for v in attempted_values if v in cities
        )
        assert successful_value == first_city, (
            f"Valor que teve sucesso deveria ser '{first_city}' "
            f"(primeira cidade), mas foi '{successful_value}'. "
            f"Cidades: {cities}"
        )

    @given(
        cities=_cities_with_sp,
    )
    @settings(max_examples=50)
    async def test_no_fallback_attempted_when_desired_succeeds(
        self,
        cities: list[str],
    ) -> None:
        """Quando desired_value tem sucesso, fallback NÃO é tentado.

        **Validates: Requirements 7.2**

        Se "São Paulo" é encontrado com sucesso na primeira tentativa,
        o sistema não deve tentar nenhum valor de fallback.
        """
        attempted_values: list[str] = []
        mock_strategy = _make_tracking_strategy(
            accepted_values=cities,
            attempted_values=attempted_values,
        )

        interactor = CustomComponentInteractor()
        interactor._strategies = [mock_strategy]

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        fallback_city = "Curitiba"

        result = await interactor.interact(
            page=page,
            selector=".city-dropdown",
            desired_value="São Paulo",
            fallback_value=fallback_city,
        )

        assert result.success is True
        # Apenas "São Paulo" deve ter sido tentado
        assert len(attempted_values) == 1, (
            f"Deveria haver apenas 1 tentativa (São Paulo), "
            f"mas houve {len(attempted_values)}: {attempted_values}"
        )
        assert attempted_values[0] == "São Paulo"
        # fallback NÃO deve estar nos valores tentados
        assert fallback_city not in attempted_values

    @given(
        cities=_cities_without_sp,
        extra_empty_entries=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=50)
    async def test_all_strategies_fail_returns_error(
        self,
        cities: list[str],
        extra_empty_entries: int,
    ) -> None:
        """Quando nenhuma cidade é aceita, retorna erro de interação.

        **Validates: Requirements 7.2**

        Se o desired_value ("São Paulo") não está disponível E o
        fallback_value também não é aceito pelas estratégias, o
        resultado deve indicar falha com o código de erro
        "custom_dropdown_interaction_failed".
        """
        attempted_values: list[str] = []
        # Estratégia que NÃO aceita nenhum valor
        mock_strategy = _make_tracking_strategy(
            accepted_values=[],  # Nenhum valor aceito
            attempted_values=attempted_values,
        )

        interactor = CustomComponentInteractor()
        interactor._strategies = [mock_strategy]

        page = AsyncMock()
        page.wait_for_selector = AsyncMock(return_value=None)

        fallback_city = cities[0]

        result = await interactor.interact(
            page=page,
            selector=".city-dropdown",
            desired_value="São Paulo",
            fallback_value=fallback_city,
        )

        assert result.success is False
        assert result.error == "custom_dropdown_interaction_failed"
        # Ambos valores devem ter sido tentados
        assert "São Paulo" in attempted_values
        assert fallback_city in attempted_values


# ============================================================================
# Property 7: Screenshots seguem padrão de nomenclatura e numeração sequencial
# ============================================================================

# Imports para Property 7
from scraping_resilience.step_screenshotter import (
    StepScreenshotter,
    _sanitize_description,
)

# Estratégias de geração para screenshot naming

# competitor_id: texto alfanumérico simples (sem / para evitar path injection)
_competitor_id_st = st.from_regex(r"[a-z][a-z0-9_]{2,20}", fullmatch=True)

# cycle_id: padrão UUID-like ou numérico
_cycle_id_st = st.from_regex(r"[a-z0-9\-]{5,36}", fullmatch=True)

# Descrições com caracteres variados (acentos, espaços, especiais)
_step_descriptions_st = st.text(
    min_size=1,
    max_size=60,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        whitelist_characters="_- ",
    ),
)

# Lista de descrições (representa N capturas sequenciais)
_descriptions_list_st = st.lists(
    _step_descriptions_st,
    min_size=1,
    max_size=20,
)

# Regex para validar padrão de S3 key de screenshot
_S3_KEY_PATTERN = re.compile(
    r"^[^/]+/[^/]+/step_\d{3}_[a-z0-9_]+\.png$"
)


@pytest.mark.property
class TestScreenshotNamingSequential:
    """Property 7: Screenshots seguem padrão de nomenclatura e numeração sequencial.

    Feature: scraping-resilience
    **Validates: Requirements 4.2, 4.3**

    For any sequência de N capturas de screenshot para um mesmo
    concorrente/ciclo, os nomes SHALL seguir o padrão
    "{competitor_id}/{cycle_id}/step_{n:03d}_{descricao}.png" e os
    números de step SHALL ser estritamente crescentes (1, 2, ..., N)
    sem lacunas.
    """

    @given(
        competitor_id=_competitor_id_st,
        cycle_id=_cycle_id_st,
        descriptions=_descriptions_list_st,
    )
    @settings(max_examples=100)
    def test_s3_key_matches_regex_pattern(
        self,
        competitor_id: str,
        cycle_id: str,
        descriptions: list[str],
    ) -> None:
        """S3 key corresponde ao padrão {comp}/{cycle}/step_\\d{3}_{desc}.png.

        **Validates: Requirements 4.2, 4.3**

        Para qualquer competitor_id, cycle_id e lista de descrições,
        cada S3 key gerada por _build_s3_key() deve corresponder ao
        padrão regex esperado.
        """
        screenshotter = StepScreenshotter(
            competitor_id=competitor_id,
            cycle_id=cycle_id,
        )

        for step_number, desc in enumerate(descriptions, start=1):
            s3_key = screenshotter._build_s3_key(step_number, desc)

            assert _S3_KEY_PATTERN.match(s3_key), (
                f"S3 key não corresponde ao padrão esperado: "
                f"key={s3_key!r}, competitor_id={competitor_id!r}, "
                f"cycle_id={cycle_id!r}, step={step_number}, "
                f"desc={desc!r}"
            )

    @given(
        competitor_id=_competitor_id_st,
        cycle_id=_cycle_id_st,
        descriptions=_descriptions_list_st,
    )
    @settings(max_examples=100)
    def test_step_numbers_increase_monotonically(
        self,
        competitor_id: str,
        cycle_id: str,
        descriptions: list[str],
    ) -> None:
        """Números de step são estritamente crescentes.

        **Validates: Requirements 4.2, 4.3**

        Para qualquer sequência de N capturas, os step numbers
        extraídos das S3 keys devem ser 1, 2, ..., N (monotonicamente
        crescentes sem repetição).
        """
        screenshotter = StepScreenshotter(
            competitor_id=competitor_id,
            cycle_id=cycle_id,
        )

        step_numbers: list[int] = []
        for step_number, desc in enumerate(descriptions, start=1):
            s3_key = screenshotter._build_s3_key(step_number, desc)

            # Extrair step number da key
            match = re.search(r"step_(\d{3})_", s3_key)
            assert match is not None, (
                f"Não foi possível extrair step number de: {s3_key!r}"
            )
            extracted_step = int(match.group(1))
            step_numbers.append(extracted_step)

        # Verificar que é estritamente crescente
        for i in range(1, len(step_numbers)):
            assert step_numbers[i] > step_numbers[i - 1], (
                f"Step numbers não são estritamente crescentes: "
                f"step[{i-1}]={step_numbers[i-1]}, "
                f"step[{i}]={step_numbers[i]}. "
                f"Sequência completa: {step_numbers}"
            )

    @given(
        competitor_id=_competitor_id_st,
        cycle_id=_cycle_id_st,
        descriptions=_descriptions_list_st,
    )
    @settings(max_examples=100)
    def test_no_gaps_in_numbering(
        self,
        competitor_id: str,
        cycle_id: str,
        descriptions: list[str],
    ) -> None:
        """Numeração sequencial sem lacunas (1, 2, ..., N).

        **Validates: Requirements 4.2, 4.3**

        Para N capturas bem-sucedidas, os step numbers devem formar
        a sequência exata [1, 2, 3, ..., N] sem nenhuma lacuna.
        """
        screenshotter = StepScreenshotter(
            competitor_id=competitor_id,
            cycle_id=cycle_id,
        )

        step_numbers: list[int] = []
        for step_number, desc in enumerate(descriptions, start=1):
            s3_key = screenshotter._build_s3_key(step_number, desc)

            match = re.search(r"step_(\d{3})_", s3_key)
            assert match is not None
            step_numbers.append(int(match.group(1)))

        # Sequência esperada: [1, 2, 3, ..., N]
        expected = list(range(1, len(descriptions) + 1))
        assert step_numbers == expected, (
            f"Numeração com lacunas: esperado={expected}, "
            f"obtido={step_numbers}"
        )

    @given(
        competitor_id=_competitor_id_st,
        cycle_id=_cycle_id_st,
        descriptions=_descriptions_list_st,
    )
    @settings(max_examples=100)
    def test_key_contains_competitor_and_cycle(
        self,
        competitor_id: str,
        cycle_id: str,
        descriptions: list[str],
    ) -> None:
        """S3 key contém competitor_id e cycle_id.

        **Validates: Requirements 4.2, 4.3**

        Para qualquer combinação de competitor_id e cycle_id, cada
        S3 key gerada deve conter ambos identificadores como prefixo
        no formato "{competitor_id}/{cycle_id}/...".
        """
        screenshotter = StepScreenshotter(
            competitor_id=competitor_id,
            cycle_id=cycle_id,
        )

        for step_number, desc in enumerate(descriptions, start=1):
            s3_key = screenshotter._build_s3_key(step_number, desc)

            # Verificar que a key começa com competitor_id/cycle_id/
            expected_prefix = f"{competitor_id}/{cycle_id}/"
            assert s3_key.startswith(expected_prefix), (
                f"S3 key não começa com prefix esperado: "
                f"key={s3_key!r}, "
                f"expected_prefix={expected_prefix!r}"
            )


# ============================================================================
# Property 6: Diagnostic Artifact Respeita Limites e Contém Campos Obrigatórios
# ============================================================================

from scraping_resilience.diagnostics_collector import DiagnosticsCollector
from scraping_resilience.models import DiagnosticArtifact


@pytest.mark.property
class TestDiagnosticArtifactLimits:
    """Property 6: Diagnostic artifact respeita limites e contém campos obrigatórios.

    Feature: scraping-resilience
    **Validates: Requirements 3.3, 3.4**

    For any cenário de erro com HTML de tamanho arbitrário e lista de
    elementos de tamanho arbitrário, o DiagnosticsCollector SHALL produzir
    um artefato contendo: HTML truncado a no máximo 5MB, screenshot,
    URL final, lista de no máximo 100 elementos (com tag, id, classes cada)
    e mensagem de erro; e a chave S3 SHALL seguir o padrão
    "diagnostics/{competitor_id}/{cycle_id}/".
    """

    @given(
        html_size=st.integers(min_value=0, max_value=10_000_000),
    )
    @settings(max_examples=100)
    async def test_capture_html_always_within_5mb(
        self,
        html_size: int,
    ) -> None:
        """HTML capturado é sempre truncado a no máximo 5MB.

        **Validates: Requirements 3.3, 3.4**

        Para qualquer tamanho de HTML gerado (0 a 10MB), o método
        _capture_html() deve retornar bytes com tamanho ≤ 5MB
        (5 * 1024 * 1024 = 5_242_880 bytes).
        """
        # Gerar HTML com tamanho exato
        html_content = "x" * html_size

        # Mock da page que retorna HTML de tamanho específico
        page = AsyncMock()
        page.content = AsyncMock(return_value=html_content)

        collector = DiagnosticsCollector()
        result = await collector._capture_html(page)

        max_size = 5 * 1024 * 1024  # 5MB
        assert len(result) <= max_size, (
            f"HTML capturado excede 5MB: {len(result)} bytes "
            f"(input: {html_size} bytes)"
        )

    @given(
        element_count=st.integers(min_value=0, max_value=500),
    )
    @settings(max_examples=100)
    async def test_capture_elements_always_within_100(
        self,
        element_count: int,
    ) -> None:
        """Lista de elementos capturados é sempre limitada a 100.

        **Validates: Requirements 3.3, 3.4**

        Para qualquer quantidade de elementos na página (0 a 500),
        o método _capture_elements() deve retornar no máximo 100
        elementos.
        """
        # Gerar lista de elementos simulados
        elements = [
            {"tag": f"div", "id": f"el-{i}", "classes": f"cls-{i}"}
            for i in range(element_count)
        ]

        # Mock da page com evaluate retornando a lista
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=elements)

        collector = DiagnosticsCollector()
        result = await collector._capture_elements(page)

        assert len(result) <= 100, (
            f"Elementos capturados excedem 100: {len(result)} "
            f"(input: {element_count} elementos)"
        )

    @given(
        element_count=st.integers(min_value=0, max_value=500),
    )
    @settings(max_examples=100)
    async def test_captured_elements_contain_required_fields(
        self,
        element_count: int,
    ) -> None:
        """Cada elemento capturado contém tag, id e classes.

        **Validates: Requirements 3.3, 3.4**

        Para qualquer lista de elementos retornada, cada elemento
        deve ser um dict contendo as chaves: 'tag', 'id' e 'classes'.
        """
        elements = [
            {"tag": f"span", "id": f"item-{i}", "classes": f"c-{i}"}
            for i in range(element_count)
        ]

        page = AsyncMock()
        page.evaluate = AsyncMock(return_value=elements)

        collector = DiagnosticsCollector()
        result = await collector._capture_elements(page)

        for elem in result:
            assert "tag" in elem, (
                f"Elemento sem campo 'tag': {elem}"
            )
            assert "id" in elem, (
                f"Elemento sem campo 'id': {elem}"
            )
            assert "classes" in elem, (
                f"Elemento sem campo 'classes': {elem}"
            )

    @given(
        competitor_id=st.text(
            min_size=1, max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_",
            ),
        ),
        cycle_id=st.text(
            min_size=1, max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_",
            ),
        ),
        html_size=st.integers(min_value=0, max_value=10_000_000),
        element_count=st.integers(min_value=0, max_value=500),
    )
    @settings(max_examples=50)
    async def test_s3_key_follows_diagnostics_prefix_pattern(
        self,
        competitor_id: str,
        cycle_id: str,
        html_size: int,
        element_count: int,
    ) -> None:
        """Chave S3 segue padrão "diagnostics/{competitor_id}/{cycle_id}/".

        **Validates: Requirements 3.3, 3.4**

        Para qualquer competitor_id e cycle_id válidos, as chaves S3
        geradas (html e screenshot) devem começar com o prefixo
        "diagnostics/{competitor_id}/{cycle_id}/".
        """
        html_content = "a" * html_size
        elements = [
            {"tag": "div", "id": f"e-{i}", "classes": ""}
            for i in range(element_count)
        ]

        # Mock da page
        page = AsyncMock()
        page.content = AsyncMock(return_value=html_content)
        page.screenshot = AsyncMock(return_value=b"fake-screenshot-data")
        page.url = "https://example.com/final-url"
        page.evaluate = AsyncMock(return_value=elements)

        # Mock S3 para não fazer upload real
        mock_s3_client = AsyncMock()
        mock_s3_client.put_object = AsyncMock()

        collector = DiagnosticsCollector()

        # Patch do upload para capturar as keys geradas
        html_keys: list[str] = []
        screenshot_keys: list[str] = []

        original_upload_html = collector._upload_html
        original_upload_screenshot = collector._upload_screenshot

        async def mock_upload_html(html_bytes, prefix, timestamp):
            if not html_bytes:
                return None
            ts_safe = collector._safe_timestamp(timestamp)
            key = f"{prefix}/html_{ts_safe}.html"
            html_keys.append(key)
            return key

        async def mock_upload_screenshot(screenshot_bytes, prefix, timestamp):
            if not screenshot_bytes:
                return None
            ts_safe = collector._safe_timestamp(timestamp)
            key = f"{prefix}/screenshot_{ts_safe}.png"
            screenshot_keys.append(key)
            return key

        collector._upload_html = mock_upload_html
        collector._upload_screenshot = mock_upload_screenshot

        artifact = await collector.capture_diagnostic(
            page=page,
            error="Test error message",
            competitor_id=competitor_id,
            cycle_id=cycle_id,
        )

        expected_prefix = f"diagnostics/{competitor_id}/{cycle_id}/"

        # Verificar HTML S3 key
        if artifact.html_s3_key is not None:
            assert artifact.html_s3_key.startswith(expected_prefix), (
                f"HTML S3 key não segue padrão: {artifact.html_s3_key} "
                f"(esperado prefixo: {expected_prefix})"
            )

        # Verificar screenshot S3 key
        if artifact.screenshot_s3_key is not None:
            assert artifact.screenshot_s3_key.startswith(expected_prefix), (
                f"Screenshot S3 key não segue padrão: "
                f"{artifact.screenshot_s3_key} "
                f"(esperado prefixo: {expected_prefix})"
            )

    @given(
        html_size=st.integers(min_value=0, max_value=10_000_000),
        element_count=st.integers(min_value=0, max_value=500),
    )
    @settings(max_examples=50)
    async def test_diagnostic_artifact_contains_all_mandatory_fields(
        self,
        html_size: int,
        element_count: int,
    ) -> None:
        """Artefato diagnóstico contém todos os campos obrigatórios.

        **Validates: Requirements 3.3, 3.4**

        O DiagnosticArtifact retornado deve conter: html_s3_key (ou None),
        screenshot_s3_key (ou None), final_url (string), elements_found
        (lista), error_message (string não-vazia) e timestamp (string).
        """
        html_content = "b" * html_size
        elements = [
            {"tag": "p", "id": f"p-{i}", "classes": "text"}
            for i in range(element_count)
        ]
        error_msg = "Simulated scraping error"

        page = AsyncMock()
        page.content = AsyncMock(return_value=html_content)
        page.screenshot = AsyncMock(return_value=b"png-data")
        page.url = "https://competitor.com/plans"
        page.evaluate = AsyncMock(return_value=elements)

        collector = DiagnosticsCollector()

        # Mock uploads para não depender de S3
        collector._upload_html = AsyncMock(
            return_value="diagnostics/comp/cycle/html_test.html"
        )
        collector._upload_screenshot = AsyncMock(
            return_value="diagnostics/comp/cycle/screenshot_test.png"
        )

        artifact = await collector.capture_diagnostic(
            page=page,
            error=error_msg,
            competitor_id="comp-test",
            cycle_id="cycle-001",
        )

        # Campos obrigatórios presentes
        assert isinstance(artifact, DiagnosticArtifact)
        assert isinstance(artifact.final_url, str)
        assert isinstance(artifact.elements_found, list)
        assert isinstance(artifact.error_message, str)
        assert artifact.error_message == error_msg
        assert isinstance(artifact.timestamp, str)
        assert len(artifact.timestamp) > 0

        # Limites respeitados
        assert len(artifact.elements_found) <= 100


# ============================================================================
# Property 5: Structured log contém todos os campos obrigatórios
# ============================================================================

import json
import logging

from hypothesis import HealthCheck

from src.scraping_resilience.structured_logger import (
    ScrapeExecutionLog,
    ScrapeSuccessLog,
    StructuredLogger,
)


@pytest.mark.property
class TestStructuredLogCompleteness:
    """Property 5: Structured log contém todos os campos obrigatórios.

    Feature: scraping-resilience
    **Validates: Requirements 3.1, 3.2**

    For any resultado de execução de scraping (sucesso ou falha), o log
    estruturado SHALL conter todos os campos obrigatórios:
    - Log de execução: event, url, page_title, load_time_ms, price_count,
      plan_count, detected_language, detected_currency
    - Log de sucesso: event, health_check_score, prices_extracted,
      screenshots_count
    E todos os valores devem ser JSON-serializáveis (sem crashes).
    """

    @given(
        url=st.text(min_size=1, max_size=200),
        page_title=st.text(min_size=0, max_size=200),
        load_time_ms=st.integers(min_value=0, max_value=60000),
        price_count=st.integers(min_value=0, max_value=1000),
        plan_count=st.integers(min_value=0, max_value=100),
        detected_language=st.text(min_size=1, max_size=20),
        detected_currency=st.text(min_size=1, max_size=10),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_execution_log_contains_all_mandatory_fields(
        self,
        url: str,
        page_title: str,
        load_time_ms: int,
        price_count: int,
        plan_count: int,
        detected_language: str,
        detected_currency: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution JSON sempre contém todos os campos obrigatórios.

        **Validates: Requirements 3.1, 3.2**

        Para qualquer combinação válida de campos de execução, o JSON
        produzido deve conter: event, url, page_title, load_time_ms,
        price_count, plan_count, detected_language, detected_currency.
        """
        caplog.clear()

        execution = ScrapeExecutionLog(
            url=url,
            page_title=page_title,
            load_time_ms=load_time_ms,
            price_count=price_count,
            plan_count=plan_count,
            detected_language=detected_language,
            detected_currency=detected_currency,
        )

        logger = StructuredLogger(logger_name="test_prop5_execution")

        with caplog.at_level(logging.INFO, logger="test_prop5_execution"):
            logger.log_execution(execution)

        assert len(caplog.records) >= 1, "Nenhum log registrado"

        log_text = caplog.records[-1].message
        payload = json.loads(log_text)

        # Campos obrigatórios do log de execução
        mandatory_fields = [
            "event",
            "url",
            "page_title",
            "load_time_ms",
            "price_count",
            "plan_count",
            "detected_language",
            "detected_currency",
        ]

        for field in mandatory_fields:
            assert field in payload, (
                f"Campo obrigatório '{field}' ausente no log de execução. "
                f"Campos presentes: {list(payload.keys())}"
            )

        # Verificar que os valores correspondem ao input
        assert payload["event"] == "scrape_execution"
        assert payload["url"] == url
        assert payload["page_title"] == page_title
        assert payload["load_time_ms"] == load_time_ms
        assert payload["price_count"] == price_count
        assert payload["plan_count"] == plan_count
        assert payload["detected_language"] == detected_language
        assert payload["detected_currency"] == detected_currency

    @given(
        health_check_score=st.text(min_size=1, max_size=30),
        prices_extracted=st.integers(min_value=0, max_value=1000),
        screenshots_count=st.integers(min_value=0, max_value=50),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_success_log_contains_all_mandatory_fields(
        self,
        health_check_score: str,
        prices_extracted: int,
        screenshots_count: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success JSON sempre contém todos os campos obrigatórios.

        **Validates: Requirements 3.1, 3.2**

        Para qualquer combinação válida de campos de sucesso, o JSON
        produzido deve conter: event, health_check_score,
        prices_extracted, screenshots_count.
        """
        caplog.clear()

        success = ScrapeSuccessLog(
            health_check_score=health_check_score,
            prices_extracted=prices_extracted,
            screenshots_count=screenshots_count,
        )

        logger = StructuredLogger(logger_name="test_prop5_success")

        with caplog.at_level(logging.INFO, logger="test_prop5_success"):
            logger.log_success(success)

        assert len(caplog.records) >= 1, "Nenhum log registrado"

        log_text = caplog.records[-1].message
        payload = json.loads(log_text)

        # Campos obrigatórios do log de sucesso
        mandatory_fields = [
            "event",
            "health_check_score",
            "prices_extracted",
            "screenshots_count",
        ]

        for field in mandatory_fields:
            assert field in payload, (
                f"Campo obrigatório '{field}' ausente no log de sucesso. "
                f"Campos presentes: {list(payload.keys())}"
            )

        # Verificar que os valores correspondem ao input
        assert payload["event"] == "scrape_success"
        assert payload["health_check_score"] == health_check_score
        assert payload["prices_extracted"] == prices_extracted
        assert payload["screenshots_count"] == screenshots_count

    @given(
        url=st.text(min_size=1, max_size=200),
        page_title=st.text(min_size=0, max_size=200),
        load_time_ms=st.integers(min_value=0, max_value=60000),
        price_count=st.integers(min_value=0, max_value=1000),
        plan_count=st.integers(min_value=0, max_value=100),
        detected_language=st.text(min_size=1, max_size=20),
        detected_currency=st.text(min_size=1, max_size=10),
    )
    @settings(
        max_examples=200,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_execution_log_is_json_serializable(
        self,
        url: str,
        page_title: str,
        load_time_ms: int,
        price_count: int,
        plan_count: int,
        detected_language: str,
        detected_currency: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Todos os valores do log de execução são JSON-serializáveis.

        **Validates: Requirements 3.1, 3.2**

        Para qualquer input arbitrário (incluindo caracteres especiais,
        emojis, unicode), o log_execution não deve crashar e o output
        deve ser JSON parseável.
        """
        caplog.clear()

        execution = ScrapeExecutionLog(
            url=url,
            page_title=page_title,
            load_time_ms=load_time_ms,
            price_count=price_count,
            plan_count=plan_count,
            detected_language=detected_language,
            detected_currency=detected_currency,
        )

        logger = StructuredLogger(logger_name="test_prop5_serializable")

        with caplog.at_level(logging.INFO, logger="test_prop5_serializable"):
            # Não deve lançar exceção
            logger.log_execution(execution)

        assert len(caplog.records) >= 1, "Nenhum log registrado"

        log_text = caplog.records[-1].message

        # Deve ser JSON parseável sem exceção
        parsed = json.loads(log_text)
        assert isinstance(parsed, dict)

        # Round-trip: re-serializar não deve crashar
        re_serialized = json.dumps(parsed, ensure_ascii=False)
        re_parsed = json.loads(re_serialized)
        assert re_parsed == parsed


# ============================================================================
# Property 13: Tab Plan Consolidation Merge sem Perda
# ============================================================================

from scraping_resilience.competitor_flows.vivo_tv import VivoTVFlow
from scraping_resilience.intelligent_wait import IntelligentWaitManager


# Estratégias para gerar listas de planos simulando tabs da Vivo TV

_plan_name_strategy = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
    ),
)


def _make_plan(name: str, tab: str) -> dict:
    """Cria um dict de plano no formato retornado por _extract_tab_plans."""
    return {"name": name, "tab": tab, "raw_text": f"{name}\nR$ 99,90"}


@pytest.mark.property
class TestTabPlanConsolidation:
    """Property 13: Tab plan consolidation merge sem perda.

    Feature: scraping-resilience
    **Validates: Requirements 6.5**

    For any conjunto de listas de planos extraídos de N tabs distintas,
    a consolidação SHALL produzir uma lista final contendo todos os
    planos únicos de todas as tabs, sem duplicatas e sem perda de
    nenhum plano original.
    """

    @given(
        tab_plans=st.lists(
            st.lists(
                _plan_name_strategy,
                min_size=0,
                max_size=10,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_consolidation_contains_all_unique_plans(
        self, tab_plans: list[list[str]]
    ) -> None:
        """Consolidação contém todos os planos únicos de todas as tabs.

        **Validates: Requirements 6.5**

        Dado N listas de planos (uma por tab), a lista consolidada
        deve conter exatamente o conjunto de nomes únicos (case-insensitive,
        stripped) presentes em todas as tabs combinadas.
        """
        tab_names = [
            "TV Online", "TV por Assinatura", "Vivo Fibra + TV",
            "Tab Extra 1", "Tab Extra 2",
        ]

        # Montar lista completa de planos de todas as tabs
        all_plans: list[dict] = []
        for i, names in enumerate(tab_plans):
            tab_name = tab_names[i % len(tab_names)]
            for name in names:
                all_plans.append(_make_plan(name, tab_name))

        # Calcular nomes únicos esperados (mesma lógica de dedup)
        expected_unique_names: set[str] = set()
        for plan in all_plans:
            plan_name = plan.get("name", "").strip().lower()
            if plan_name:
                expected_unique_names.add(plan_name)

        # Usar _deduplicate_plans via instância com mocks
        wait_mgr = MagicMock()
        screenshotter = MagicMock()
        flow = VivoTVFlow(
            wait_manager=wait_mgr, screenshotter=screenshotter
        )

        result = flow._deduplicate_plans(all_plans)

        # Nomes retornados
        result_names = {
            p["name"].strip().lower() for p in result
        }

        # PROPRIEDADE: todos os nomes únicos estão presentes
        assert result_names == expected_unique_names, (
            f"Planos perdidos na consolidação. "
            f"Esperados: {expected_unique_names}, "
            f"Obtidos: {result_names}"
        )

    @given(
        plan_names=st.lists(
            _plan_name_strategy,
            min_size=1,
            max_size=20,
            unique=True,
        ),
        num_tabs=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=200)
    def test_no_duplicates_in_consolidated_list(
        self,
        plan_names: list[str],
        num_tabs: int,
    ) -> None:
        """Consolidação não contém nomes duplicados.

        **Validates: Requirements 6.5**

        Dado planos com nomes únicos distribuídos em N tabs
        (com repetições entre tabs), a lista consolidada não
        deve conter duplicatas (nomes repetidos).
        """
        tab_names = [
            "TV Online", "TV por Assinatura", "Vivo Fibra + TV",
            "Tab Extra 1", "Tab Extra 2",
        ]

        # Distribuir planos em múltiplas tabs com overlap
        all_plans: list[dict] = []
        for i, name in enumerate(plan_names):
            # Colocar cada plano em pelo menos uma tab
            tab_name = tab_names[i % num_tabs]
            all_plans.append(_make_plan(name, tab_name))

            # Adicionar duplicatas em outras tabs para testar dedup
            if i % 2 == 0 and num_tabs > 1:
                other_tab = tab_names[(i + 1) % num_tabs]
                all_plans.append(_make_plan(name, other_tab))

        wait_mgr = MagicMock()
        screenshotter = MagicMock()
        flow = VivoTVFlow(
            wait_manager=wait_mgr, screenshotter=screenshotter
        )

        result = flow._deduplicate_plans(all_plans)

        # Verificar que não há nomes duplicados
        result_names_lower = [
            p["name"].strip().lower() for p in result
        ]
        assert len(result_names_lower) == len(set(result_names_lower)), (
            f"Duplicatas encontradas na consolidação: "
            f"{result_names_lower}"
        )

    @given(
        tab_plans=st.lists(
            st.lists(
                _plan_name_strategy,
                min_size=0,
                max_size=10,
            ),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_consolidation_size_leq_total_unique(
        self, tab_plans: list[list[str]]
    ) -> None:
        """Tamanho da consolidação <= total de nomes únicos das tabs.

        **Validates: Requirements 6.5**

        A lista consolidada não pode ter mais elementos do que
        o número total de nomes únicos (case-insensitive, stripped)
        presentes nas tabs combinadas.
        """
        tab_names = [
            "TV Online", "TV por Assinatura", "Vivo Fibra + TV",
            "Tab Extra 1", "Tab Extra 2",
        ]

        all_plans: list[dict] = []
        for i, names in enumerate(tab_plans):
            tab_name = tab_names[i % len(tab_names)]
            for name in names:
                all_plans.append(_make_plan(name, tab_name))

        # Contar nomes únicos esperados
        unique_names: set[str] = set()
        for plan in all_plans:
            plan_name = plan.get("name", "").strip().lower()
            if plan_name:
                unique_names.add(plan_name)

        wait_mgr = MagicMock()
        screenshotter = MagicMock()
        flow = VivoTVFlow(
            wait_manager=wait_mgr, screenshotter=screenshotter
        )

        result = flow._deduplicate_plans(all_plans)

        assert len(result) <= len(unique_names), (
            f"Consolidação ({len(result)} itens) excede "
            f"nomes únicos ({len(unique_names)} itens)"
        )

    @given(
        plan_names=st.lists(
            _plan_name_strategy,
            min_size=1,
            max_size=15,
            unique=True,
        ),
    )
    @settings(max_examples=200)
    def test_consolidation_preserves_order(
        self, plan_names: list[str]
    ) -> None:
        """Consolidação preserva ordem de inserção original.

        **Validates: Requirements 6.5**

        Os planos na lista consolidada devem estar na mesma ordem
        relativa em que foram inseridos originalmente (primeira
        ocorrência preservada).
        """
        all_plans: list[dict] = []
        for name in plan_names:
            all_plans.append(_make_plan(name, "TV Online"))

        wait_mgr = MagicMock()
        screenshotter = MagicMock()
        flow = VivoTVFlow(
            wait_manager=wait_mgr, screenshotter=screenshotter
        )

        result = flow._deduplicate_plans(all_plans)

        # Ordem deve ser idêntica à inserção (sem duplicatas no input)
        result_names = [p["name"] for p in result]
        # Filtrar nomes válidos (não vazios após strip)
        expected_names = [
            n for n in plan_names if n.strip()
        ]

        assert result_names == expected_names, (
            f"Ordem não preservada. "
            f"Esperado: {expected_names}, Obtido: {result_names}"
        )


# ============================================================================
# Property 14: Content Change Detection
# ============================================================================


@pytest.mark.property
class TestContentChangeDetection:
    """Property 14: Content change detection identifica mudança após interação.

    Feature: scraping-resilience
    **Validates: Requirements 6.2**

    For any estado do DOM antes e depois de uma interação (conteúdo de
    um seletor de referência), o wait_for_content_change SHALL retornar
    true quando o conteúdo textual do seletor mudou, e false quando
    permanece idêntico após o timeout.
    """

    @given(
        old_content=st.text(min_size=0, max_size=500),
        new_content=st.text(min_size=0, max_size=500),
    )
    @settings(max_examples=200)
    async def test_returns_true_when_content_changed(
        self,
        old_content: str,
        new_content: str,
    ) -> None:
        """Retorna True quando o conteúdo muda após interação.

        **Validates: Requirements 6.2**

        Quando o texto do seletor de referência difere entre o
        momento da captura e a avaliação posterior, deve retornar True.
        """
        # Só testar quando conteúdo realmente muda
        if old_content == new_content:
            return

        page = AsyncMock()
        selector = ".plans-container"

        # Simular inner_text retornando old_content (captura inicial)
        mock_locator = MagicMock()
        mock_first = AsyncMock()
        mock_first.inner_text = AsyncMock(return_value=old_content)
        mock_locator.first = mock_first
        page.locator = MagicMock(return_value=mock_locator)

        # Simular wait_for_function retornando com sucesso
        # (conteúdo mudou — JS retorna true)
        page.wait_for_function = AsyncMock(return_value=None)

        manager = IntelligentWaitManager()
        result = await manager.wait_for_content_change(
            page=page,
            reference_selector=selector,
            timeout_ms=15_000,
        )

        assert result is True, (
            f"Deveria retornar True quando conteúdo muda. "
            f"old={old_content!r}, new={new_content!r}"
        )

        # Verificar que wait_for_function foi chamado com os args corretos
        page.wait_for_function.assert_called_once()
        call_args = page.wait_for_function.call_args
        # O segundo argumento posicional é [selector, previousContent]
        assert call_args[0][1] == [selector, old_content]

    @given(
        content=st.text(min_size=0, max_size=500),
    )
    @settings(max_examples=200)
    async def test_returns_false_when_content_unchanged(
        self,
        content: str,
    ) -> None:
        """Retorna False quando o conteúdo permanece idêntico (timeout).

        **Validates: Requirements 6.2**

        Quando o texto do seletor de referência não muda dentro do
        timeout, wait_for_content_change deve retornar False.
        """
        page = AsyncMock()
        selector = ".plans-container"

        # Simular inner_text retornando content (captura inicial)
        mock_locator = MagicMock()
        mock_first = AsyncMock()
        mock_first.inner_text = AsyncMock(return_value=content)
        mock_locator.first = mock_first
        page.locator = MagicMock(return_value=mock_locator)

        # Simular wait_for_function lançando timeout (conteúdo não mudou)
        page.wait_for_function = AsyncMock(
            side_effect=PlaywrightTimeoutError(
                "Timeout: content did not change"
            )
        )

        manager = IntelligentWaitManager()
        result = await manager.wait_for_content_change(
            page=page,
            reference_selector=selector,
            timeout_ms=15_000,
        )

        assert result is False, (
            f"Deveria retornar False quando conteúdo não muda. "
            f"content={content!r}"
        )

    @given(
        old_content=st.text(min_size=0, max_size=500),
        new_content=st.text(min_size=0, max_size=500),
        timeout_ms=st.integers(min_value=1000, max_value=30000),
    )
    @settings(max_examples=100)
    async def test_timeout_parameter_passed_correctly(
        self,
        old_content: str,
        new_content: str,
        timeout_ms: int,
    ) -> None:
        """Timeout é passado corretamente ao wait_for_function.

        **Validates: Requirements 6.2**

        O parâmetro timeout_ms deve ser repassado ao page.wait_for_function
        para que a espera respeite o limite configurado.
        """
        page = AsyncMock()
        selector = ".plans-container"

        mock_locator = MagicMock()
        mock_first = AsyncMock()
        mock_first.inner_text = AsyncMock(return_value=old_content)
        mock_locator.first = mock_first
        page.locator = MagicMock(return_value=mock_locator)

        # Simular sucesso (conteúdo mudou)
        page.wait_for_function = AsyncMock(return_value=None)

        manager = IntelligentWaitManager()
        await manager.wait_for_content_change(
            page=page,
            reference_selector=selector,
            timeout_ms=timeout_ms,
        )

        # Verificar que timeout foi passado ao wait_for_function
        call_kwargs = page.wait_for_function.call_args
        assert call_kwargs[1]["timeout"] == timeout_ms or (
            len(call_kwargs[0]) >= 3
            and call_kwargs[0][2] == timeout_ms
        ), (
            f"Timeout {timeout_ms} não foi passado ao "
            f"wait_for_function. Args: {call_kwargs}"
        )

    @given(
        content=st.text(min_size=0, max_size=500),
    )
    @settings(max_examples=100)
    async def test_graceful_on_reference_capture_failure(
        self,
        content: str,
    ) -> None:
        """Funciona graciosamente quando captura de referência falha.

        **Validates: Requirements 6.2**

        Se inner_text() do seletor de referência lançar exceção,
        o método deve usar string vazia como referência e prosseguir
        normalmente (não crashar).
        """
        page = AsyncMock()
        selector = ".plans-container"

        # Simular falha na captura de inner_text
        mock_locator = MagicMock()
        mock_first = AsyncMock()
        mock_first.inner_text = AsyncMock(
            side_effect=Exception("Element not found")
        )
        mock_locator.first = mock_first
        page.locator = MagicMock(return_value=mock_locator)

        # Simular sucesso no wait_for_function (conteúdo mudou)
        page.wait_for_function = AsyncMock(return_value=None)

        manager = IntelligentWaitManager()
        result = await manager.wait_for_content_change(
            page=page,
            reference_selector=selector,
            timeout_ms=15_000,
        )

        # Deve retornar True (conteúdo "mudou" a partir de referência vazia)
        assert result is True

        # Deve ter usado "" como conteúdo de referência
        call_args = page.wait_for_function.call_args
        assert call_args[0][1] == [selector, ""], (
            f"Deveria usar '' como referência quando captura falha. "
            f"Args: {call_args}"
        )
