"""Módulo de detecção de mudanças em inteligência competitiva.

Compara registros consecutivos de composição de pacotes e comunicação
comercial para gerar alertas quando mudanças são detectadas.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from price_watchdog.models.intelligence_dataclasses import (
    IntelligenceAlert,
)
from price_watchdog.models.intelligence_entities import (
    CompetitorIntelligenceRecord,
    PackageComposition,
)

if TYPE_CHECKING:
    from price_watchdog.storage.intelligence_store import (
        IntelligenceStore,
    )

logger = logging.getLogger(__name__)

# Atributos comparáveis de PackageComposition
_COMPOSITION_ATTRIBUTES = [
    "default_price",
    "promotional_price",
    "promotional_period_months",
    "linear_channels",
    "simultaneous_screens",
    "has_fiber",
    "fiber_speed_mbps",
    "has_mobile_internet",
    "mobile_speed_mbps",
    "bundled_streaming_1",
    "bundled_streaming_2",
    "bundled_streaming_3",
]


class ChangeDetector:
    """Detecta mudanças em composição e comunicação comercial.

    Attributes:
        _intelligence_store: Store para buscar registros anteriores.
    """

    def __init__(
        self,
        intelligence_store: IntelligenceStore | None = None,
    ) -> None:
        """Inicializa ChangeDetector com dependências.

        Args:
            intelligence_store: Store para buscar o registro
                anterior de inteligência. Necessário para o
                método detect_changes.
        """
        self._intelligence_store = intelligence_store

    async def detect_changes(
        self,
        current: CompetitorIntelligenceRecord,
        competitor_id: str,
    ) -> list[IntelligenceAlert]:
        """Detecta mudanças entre registro atual e anterior.

        Busca o registro anterior bem-sucedido do concorrente via
        IntelligenceStore e compara composição de pacotes e
        comunicação comercial. Se não houver registro anterior,
        trata como baseline e retorna lista vazia (sem alertas).

        Args:
            current: Registro de inteligência atual persistido.
            competitor_id: ID do concorrente.

        Returns:
            Lista de IntelligenceAlert com mudanças detectadas.
            Lista vazia se for o primeiro registro (baseline)
            ou se ocorrer erro na comparação.
        """
        if self._intelligence_store is None:
            logger.warning(
                "IntelligenceStore não configurado no "
                "ChangeDetector. Sem detecção de mudanças."
            )
            return []

        try:
            previous = (
                await self._intelligence_store.get_previous_record(
                    competitor_id
                )
            )

            # Primeiro registro = baseline, sem alertas
            if previous is None:
                logger.info(
                    "Primeiro registro de inteligência para "
                    "competitor_id=%s. Baseline registrado.",
                    competitor_id,
                )
                return []

            # Comparar composições de pacotes
            composition_alerts = self._compare_compositions(
                current=current.packages,
                previous=previous.packages,
            )

            # Comparar comunicação comercial
            communication_alerts = self._compare_communication(
                current=current,
                previous=previous,
            )

            # Combinar alertas e preencher competitor_name
            all_alerts = composition_alerts + communication_alerts

            # Obter nome do concorrente do registro atual
            competitor_name = ""
            if hasattr(current, "competitor") and current.competitor:
                competitor_name = current.competitor.name or ""

            for alert in all_alerts:
                alert.competitor_name = competitor_name

            if all_alerts:
                logger.info(
                    "Mudanças detectadas para competitor_id=%s: "
                    "%d alertas de composição, "
                    "%d alertas de comunicação",
                    competitor_id,
                    len(composition_alerts),
                    len(communication_alerts),
                )

            return all_alerts

        except Exception as exc:
            # Erros na comparação: log + skip (não gera alerta falso)
            logger.error(
                "Erro ao detectar mudanças para "
                "competitor_id=%s: %s",
                competitor_id,
                exc,
                exc_info=True,
            )
            return []

    def _compare_compositions(
        self,
        current: list[PackageComposition],
        previous: list[PackageComposition] | None,
    ) -> list[IntelligenceAlert]:
        """Compara composições de pacotes entre registros consecutivos.

        Para cada pacote presente em current e previous (matched por
        plan_name), compara cada atributo e gera um alerta por atributo
        alterado. Pacotes novos (em current mas não em previous) geram
        alertas para cada atributo não-null.

        Se previous é None ou lista vazia (primeiro registro = baseline),
        retorna lista vazia sem gerar alertas.

        Args:
            current: Lista de PackageComposition do registro atual.
            previous: Lista de PackageComposition do registro anterior,
                ou None se for o primeiro registro (baseline).

        Returns:
            Lista de IntelligenceAlert com alertas de mudança detectados.
        """
        # Baseline: sem registro anterior, não gera alertas
        if not previous:
            return []

        alerts: list[IntelligenceAlert] = []

        # Indexar pacotes anteriores por plan_name para busca rápida
        previous_by_name: dict[str, PackageComposition] = {
            pkg.plan_name: pkg for pkg in previous
        }

        for current_pkg in current:
            prev_pkg = previous_by_name.get(current_pkg.plan_name)

            if prev_pkg is None:
                # Pacote novo: gerar alerta para cada atributo não-null
                alerts.extend(
                    self._alerts_for_new_package(current_pkg)
                )
            else:
                # Pacote existente: comparar cada atributo
                alerts.extend(
                    self._alerts_for_changed_package(
                        current_pkg, prev_pkg
                    )
                )

        return alerts

    def _alerts_for_new_package(
        self, package: PackageComposition
    ) -> list[IntelligenceAlert]:
        """Gera alertas para um pacote novo (sem equivalente anterior).

        Cada atributo não-null do pacote gera um alerta com
        previous_value=None e current_value preenchido.

        Args:
            package: PackageComposition novo sem registro anterior.

        Returns:
            Lista de alertas para atributos não-null.
        """
        alerts: list[IntelligenceAlert] = []

        for attr_name in _COMPOSITION_ATTRIBUTES:
            current_value = getattr(package, attr_name, None)
            if current_value is not None:
                alerts.append(
                    IntelligenceAlert(
                        alert_type="package_composition_change",
                        competitor_name="",  # preenchido externamente
                        attribute_name=attr_name,
                        previous_value=None,
                        current_value=str(current_value),
                        plan_name=package.plan_name,
                    )
                )

        return alerts

    def _alerts_for_changed_package(
        self,
        current_pkg: PackageComposition,
        prev_pkg: PackageComposition,
    ) -> list[IntelligenceAlert]:
        """Gera alertas para atributos que mudaram entre dois pacotes.

        Compara cada atributo e gera alerta quando o valor atual difere
        do valor anterior.

        Args:
            current_pkg: Pacote do registro atual.
            prev_pkg: Pacote do registro anterior.

        Returns:
            Lista de alertas para atributos que mudaram.
        """
        alerts: list[IntelligenceAlert] = []

        for attr_name in _COMPOSITION_ATTRIBUTES:
            current_value = getattr(current_pkg, attr_name, None)
            previous_value = getattr(prev_pkg, attr_name, None)

            if current_value != previous_value:
                alerts.append(
                    IntelligenceAlert(
                        alert_type="package_composition_change",
                        competitor_name="",  # preenchido externamente
                        attribute_name=attr_name,
                        previous_value=(
                            str(previous_value)
                            if previous_value is not None
                            else None
                        ),
                        current_value=(
                            str(current_value)
                            if current_value is not None
                            else None
                        ),
                        plan_name=current_pkg.plan_name,
                    )
                )

        return alerts

    # --- Métodos para comparação de comunicação comercial ---

    def _calculate_keyword_change_pct(
        self, current: list[str], previous: list[str]
    ) -> float:
        """Calcula percentual de mudança entre dois conjuntos de keywords.

        Usa distância de Jaccard: 1.0 - (|interseção| / |união|).
        Retorna 0.0 quando ambos são idênticos e 1.0 quando são
        completamente diferentes.

        Args:
            current: Lista de keywords do registro atual.
            previous: Lista de keywords do registro anterior.

        Returns:
            Float entre 0.0 e 1.0 representando a fração de mudança.
            0.0 = idênticos, 1.0 = completamente diferentes.
        """
        current_set = set(kw.lower().strip() for kw in current)
        previous_set = set(kw.lower().strip() for kw in previous)

        union = current_set | previous_set
        if not union:
            return 0.0

        intersection = current_set & previous_set
        return 1.0 - (len(intersection) / len(union))

    def _calculate_text_similarity(
        self, text_a: str, text_b: str
    ) -> float:
        """Calcula similaridade textual entre dois textos.

        Usa SequenceMatcher da stdlib para calcular a razão de
        similaridade entre as strings.

        Args:
            text_a: Primeiro texto para comparação.
            text_b: Segundo texto para comparação.

        Returns:
            Float entre 0.0 e 1.0 onde 1.0 = idênticos.
            Se ambos forem vazios, retorna 1.0 (idênticos).
            Se apenas um for vazio, retorna 0.0.
        """
        # Tratar strings vazias
        if not text_a and not text_b:
            return 1.0
        if not text_a or not text_b:
            return 0.0

        return SequenceMatcher(None, text_a, text_b).ratio()

    def _compare_communication(
        self,
        current: CompetitorIntelligenceRecord,
        previous: CompetitorIntelligenceRecord,
    ) -> list[IntelligenceAlert]:
        """Compara comunicação comercial entre registros consecutivos.

        Gera alerta "communication_change" se:
        - Keywords mudaram mais de 50% (change_pct > 0.5)
        - OU banner similarity é inferior a 60% (< 0.6)

        Pode retornar 0, 1 ou 2 alertas (um para keywords, um para
        banner).

        Args:
            current: Registro de inteligência atual.
            previous: Registro de inteligência anterior.

        Returns:
            Lista de IntelligenceAlert (0 a 2 alertas).
        """
        alerts: list[IntelligenceAlert] = []

        # Comparar keywords
        current_keywords = current.commercial_keywords or []
        previous_keywords = previous.commercial_keywords or []

        if current_keywords or previous_keywords:
            keyword_change_pct = self._calculate_keyword_change_pct(
                current_keywords, previous_keywords
            )
            if keyword_change_pct > 0.5:
                alerts.append(
                    IntelligenceAlert(
                        alert_type="communication_change",
                        competitor_name="",  # preenchido externamente
                        attribute_name="commercial_keywords",
                        previous_value=", ".join(previous_keywords),
                        current_value=", ".join(current_keywords),
                        plan_name=None,
                    )
                )

        # Comparar banner
        current_banner = current.home_banner_description or ""
        previous_banner = previous.home_banner_description or ""

        if current_banner or previous_banner:
            banner_similarity = self._calculate_text_similarity(
                current_banner, previous_banner
            )
            if banner_similarity < 0.6:
                alerts.append(
                    IntelligenceAlert(
                        alert_type="communication_change",
                        competitor_name="",  # preenchido externamente
                        attribute_name="home_banner_description",
                        previous_value=previous_banner,
                        current_value=current_banner,
                        plan_name=None,
                    )
                )

        return alerts
