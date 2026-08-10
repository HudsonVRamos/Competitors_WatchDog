"""Fluxo específico para Vivo TV — navegação de 3 tabs.

Identifica e clica sequencialmente nas tabs: "TV Online", "TV por Assinatura",
"Vivo Fibra + TV". Usa wait_for_content_change() para validar que conteúdo
mudou após cada clique. Captura screenshot independente por tab. Se tab não
encontrada ou sem mudança após 15s, loga warning e prossegue para próxima.
Consolida planos de todas as tabs em lista única sem duplicatas.
"""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Page

from src.scraping_resilience.intelligent_wait import IntelligentWaitManager
from src.scraping_resilience.step_screenshotter import StepScreenshotter

logger = logging.getLogger(__name__)

VIVO_TV_TABS: list[str] = ["TV Online", "TV por Assinatura", "Vivo Fibra + TV"]

# Seletores de referência para detectar mudança de conteúdo após clique em tab
CONTENT_CHANGE_SELECTORS: str = (
    ".plans-container, [class*='plan'], [class*='card'], "
    "[class*='offer'], [class*='price']"
)

# Timeout para aguardar mudança de conteúdo após clique em tab (ms)
CONTENT_CHANGE_TIMEOUT_MS: int = 15_000


class VivoTVFlow:
    """Navegação e extração para o site Vivo TV (3 tabs de ofertas).

    Navega sequencialmente pelas tabs "TV Online", "TV por Assinatura" e
    "Vivo Fibra + TV", aguardando mudança de conteúdo após cada clique,
    capturando screenshots independentes e consolidando planos sem duplicatas.

    Atributos:
        _wait_manager: Gerenciador de esperas inteligentes.
        _screenshotter: Capturador de screenshots sequenciais.
    """

    def __init__(
        self,
        wait_manager: IntelligentWaitManager,
        screenshotter: StepScreenshotter,
    ) -> None:
        """Inicializa o fluxo Vivo TV.

        Args:
            wait_manager: Instância de IntelligentWaitManager para aguardar
                mudanças de conteúdo após interações.
            screenshotter: Instância de StepScreenshotter para capturar
                evidências visuais de cada tab.
        """
        self._wait_manager = wait_manager
        self._screenshotter = screenshotter

    async def navigate_tabs(self, page: Page) -> list[dict[str, Any]]:
        """Navega pelas 3 tabs da Vivo TV e consolida planos.

        Para cada tab:
        1. Localiza o elemento da tab pelo texto
        2. Clica na tab
        3. Aguarda mudança de conteúdo (até 15s)
        4. Captura screenshot independente
        5. Extrai planos da tab atual

        Se uma tab não for encontrada ou o conteúdo não mudar após 15s,
        registra warning e prossegue para a próxima tab.

        Args:
            page: Página Playwright já carregada no site da Vivo TV.

        Returns:
            Lista consolidada de planos (dicts) sem duplicatas, extraídos
            de todas as tabs processadas com sucesso.
        """
        all_plans: list[dict[str, Any]] = []

        for tab_name in VIVO_TV_TABS:
            tab_plans = await self._process_tab(page, tab_name)
            all_plans.extend(tab_plans)

        # Consolidar e remover duplicatas
        deduplicated = self._deduplicate_plans(all_plans)
        logger.info(
            "Vivo TV: %d planos consolidados (de %d totais antes da dedup).",
            len(deduplicated),
            len(all_plans),
        )
        return deduplicated

    async def _process_tab(
        self, page: Page, tab_name: str
    ) -> list[dict[str, Any]]:
        """Processa uma tab individual: clique, espera, screenshot, extração.

        Args:
            page: Página Playwright.
            tab_name: Nome textual da tab a ser clicada.

        Returns:
            Lista de planos extraídos desta tab, ou lista vazia em caso de falha.
        """
        try:
            # Localizar a tab pelo texto
            tab_locator = page.get_by_text(tab_name, exact=False)
            tab_count = await tab_locator.count()

            if tab_count == 0:
                logger.warning(
                    "Tab '%s' não encontrada na página, pulando.", tab_name
                )
                return []

            # Clicar na tab (usar .first se houver múltiplos matches)
            await tab_locator.first.click()
            logger.info("Tab '%s' clicada.", tab_name)

            # Aguardar mudança de conteúdo
            content_changed = await self._wait_manager.wait_for_content_change(
                page,
                CONTENT_CHANGE_SELECTORS,
                timeout_ms=CONTENT_CHANGE_TIMEOUT_MS,
            )

            if not content_changed:
                logger.warning(
                    "Tab '%s': conteúdo não mudou após %d ms, pulando.",
                    tab_name,
                    CONTENT_CHANGE_TIMEOUT_MS,
                )
                return []

            # Capturar screenshot independente para esta tab
            await self._screenshotter.capture(page, f"tab_{tab_name}")

            # Extrair planos da tab atual
            tab_plans = await self._extract_tab_plans(page, tab_name)
            logger.info(
                "Tab '%s': %d planos extraídos.", tab_name, len(tab_plans)
            )
            return tab_plans

        except Exception as exc:
            logger.warning(
                "Erro ao processar tab '%s': %s. Prosseguindo para próxima.",
                tab_name,
                exc,
            )
            return []

    async def _extract_tab_plans(
        self, page: Page, tab_name: str
    ) -> list[dict[str, Any]]:
        """Extrai dados de planos da tab atualmente visível.

        Busca cards de plano na página e extrai nome e preço de cada um.
        A extração real de dados detalhados será delegada ao extrator
        principal do PriceScraper; aqui extraímos estrutura básica para
        consolidação e deduplicação.

        Args:
            page: Página Playwright no estado da tab já carregada.
            tab_name: Nome da tab atual (usado como metadado).

        Returns:
            Lista de dicts com dados dos planos encontrados.
            Cada dict contém ao mínimo: {"name": str, "tab": str}.
        """
        plans: list[dict[str, Any]] = []

        # Seletores para cards de plano (priorizando semânticos)
        plan_selectors = [
            "[class*='plan']",
            "[class*='card']",
            "[class*='offer']",
            "[data-testid*='plan']",
        ]

        for selector in plan_selectors:
            locator = page.locator(selector)
            count = await locator.count()

            if count > 0:
                for i in range(count):
                    element = locator.nth(i)
                    try:
                        text = await element.inner_text()
                        plan_name = self._extract_plan_name(text)
                        if plan_name:
                            plans.append({
                                "name": plan_name,
                                "tab": tab_name,
                                "raw_text": text.strip(),
                            })
                    except Exception:
                        continue
                # Se encontrou planos com primeiro seletor, usa
                if plans:
                    break

        return plans

    def _extract_plan_name(self, text: str) -> str:
        """Extrai o nome do plano a partir do texto bruto de um card.

        Usa a primeira linha não-vazia como nome do plano.

        Args:
            text: Texto completo do card de plano.

        Returns:
            Nome do plano extraído, ou string vazia se não identificado.
        """
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return lines[0] if lines else ""

    def _deduplicate_plans(
        self, plans: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Remove planos duplicados baseando-se no nome do plano.

        Mantém a primeira ocorrência de cada plano (preserva ordem de
        inserção). Planos com mesmo nome vindos de tabs diferentes são
        considerados duplicatas.

        Args:
            plans: Lista completa de planos de todas as tabs.

        Returns:
            Lista sem duplicatas, preservando ordem original.
        """
        seen_names: set[str] = set()
        unique_plans: list[dict[str, Any]] = []

        for plan in plans:
            plan_name = plan.get("name", "").strip().lower()
            if plan_name and plan_name not in seen_names:
                seen_names.add(plan_name)
                unique_plans.append(plan)

        return unique_plans
