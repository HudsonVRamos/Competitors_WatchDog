"""Testes unitários para ChangeDetector — comunicação comercial.

Valida os métodos _calculate_keyword_change_pct, _calculate_text_similarity
e _compare_communication conforme Requirement 7.4.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import MagicMock

import pytest

from price_watchdog.comparator.change_detector import ChangeDetector


class TestCalculateKeywordChangePct:
    """Testes para _calculate_keyword_change_pct."""

    def setup_method(self) -> None:
        self.detector = ChangeDetector()

    def test_keywords_identicos_retorna_zero(self) -> None:
        """Keywords idênticos devem ter 0% de mudança."""
        pct = self.detector._calculate_keyword_change_pct(
            ["a", "b", "c"], ["a", "b", "c"]
        )
        assert pct == 0.0

    def test_keywords_completamente_diferentes_retorna_um(self) -> None:
        """Keywords sem interseção devem ter 100% de mudança."""
        pct = self.detector._calculate_keyword_change_pct(
            ["a", "b"], ["c", "d"]
        )
        assert pct == 1.0

    def test_keywords_parcialmente_iguais(self) -> None:
        """Interseção parcial deve retornar valor proporcional."""
        # {a,b,c} vs {a,b,d} -> union=4, intersection=2 -> 1-2/4=0.5
        pct = self.detector._calculate_keyword_change_pct(
            ["a", "b", "c"], ["a", "b", "d"]
        )
        assert pct == pytest.approx(0.5)

    def test_ambas_listas_vazias_retorna_zero(self) -> None:
        """Duas listas vazias devem retornar 0.0 (sem mudança)."""
        pct = self.detector._calculate_keyword_change_pct([], [])
        assert pct == 0.0

    def test_case_insensitive(self) -> None:
        """Comparação deve ser case-insensitive."""
        pct = self.detector._calculate_keyword_change_pct(
            ["Netflix", "Disney"], ["netflix", "disney"]
        )
        assert pct == 0.0

    def test_strip_espaços(self) -> None:
        """Espaços em volta devem ser ignorados."""
        pct = self.detector._calculate_keyword_change_pct(
            [" promo ", "oferta"], ["promo", " oferta "]
        )
        assert pct == 0.0


class TestCalculateTextSimilarity:
    """Testes para _calculate_text_similarity."""

    def setup_method(self) -> None:
        self.detector = ChangeDetector()

    def test_textos_identicos_retorna_um(self) -> None:
        """Textos idênticos devem retornar 1.0."""
        sim = self.detector._calculate_text_similarity(
            "hello world", "hello world"
        )
        assert sim == 1.0

    def test_ambos_vazios_retorna_um(self) -> None:
        """Ambos vazios são considerados idênticos (1.0)."""
        sim = self.detector._calculate_text_similarity("", "")
        assert sim == 1.0

    def test_apenas_um_vazio_retorna_zero(self) -> None:
        """Se apenas um é vazio, retorna 0.0."""
        sim = self.detector._calculate_text_similarity("hello", "")
        assert sim == 0.0

        sim2 = self.detector._calculate_text_similarity("", "world")
        assert sim2 == 0.0

    def test_textos_completamente_diferentes(self) -> None:
        """Textos sem caracteres em comum devem ter similaridade baixa."""
        sim = self.detector._calculate_text_similarity("aaa", "zzz")
        assert sim < 0.6

    def test_textos_parcialmente_similares(self) -> None:
        """Textos com parte em comum devem ter similaridade intermediária."""
        sim = self.detector._calculate_text_similarity(
            "Black Friday 50% off", "Black Friday promoção"
        )
        assert 0.0 < sim < 1.0


class TestCompareCommunication:
    """Testes para _compare_communication."""

    def setup_method(self) -> None:
        self.detector = ChangeDetector()

    def _make_record(
        self,
        keywords: list[str] | None = None,
        banner: str | None = None,
    ) -> MagicMock:
        """Cria um mock de CompetitorIntelligenceRecord."""
        record = MagicMock()
        record.commercial_keywords = keywords
        record.home_banner_description = banner
        return record

    def test_keywords_diferentes_gera_alerta(self) -> None:
        """Keywords > 50% mudança gera alerta communication_change."""
        current = self._make_record(
            keywords=["promo", "oferta", "desconto"],
            banner="Mesmo banner",
        )
        previous = self._make_record(
            keywords=["fibra", "velocidade", "internet"],
            banner="Mesmo banner",
        )

        alerts = self.detector._compare_communication(current, previous)

        assert len(alerts) == 1
        assert alerts[0].alert_type == "communication_change"
        assert alerts[0].attribute_name == "commercial_keywords"

    def test_banner_muito_diferente_gera_alerta(self) -> None:
        """Banner com similaridade < 60% gera alerta."""
        current = self._make_record(
            keywords=["promo", "oferta", "desconto"],
            banner="Natal chegou com ofertas incríveis",
        )
        previous = self._make_record(
            keywords=["promo", "oferta", "desconto"],
            banner="Black Friday acabou, volte ano que vem",
        )

        alerts = self.detector._compare_communication(current, previous)

        # Deve gerar alerta para banner
        banner_alerts = [
            a for a in alerts
            if a.attribute_name == "home_banner_description"
        ]
        assert len(banner_alerts) == 1
        assert banner_alerts[0].alert_type == "communication_change"

    def test_ambos_diferentes_gera_dois_alertas(self) -> None:
        """Keywords e banner diferentes geram 2 alertas."""
        current = self._make_record(
            keywords=["promo", "desconto", "novidade"],
            banner="Natal chegou com tudo novo aqui",
        )
        previous = self._make_record(
            keywords=["fibra", "velocidade", "internet"],
            banner="Black Friday e promoções incríveis para você",
        )

        alerts = self.detector._compare_communication(current, previous)

        assert len(alerts) == 2
        types = {a.attribute_name for a in alerts}
        assert "commercial_keywords" in types
        assert "home_banner_description" in types

    def test_identicos_sem_alerta(self) -> None:
        """Keywords e banner idênticos não geram alertas."""
        current = self._make_record(
            keywords=["promo", "oferta", "desconto"],
            banner="Mesma descrição do banner",
        )
        previous = self._make_record(
            keywords=["promo", "oferta", "desconto"],
            banner="Mesma descrição do banner",
        )

        alerts = self.detector._compare_communication(current, previous)

        assert len(alerts) == 0

    def test_keywords_none_sem_alerta(self) -> None:
        """Keywords None em ambos não gera alerta."""
        current = self._make_record(keywords=None, banner=None)
        previous = self._make_record(keywords=None, banner=None)

        alerts = self.detector._compare_communication(current, previous)

        assert len(alerts) == 0

    def test_keywords_mudanca_exatamente_50_pct_sem_alerta(self) -> None:
        """Mudança de exatamente 50% (não > 50%) não gera alerta."""
        # {a,b,c} vs {a,b,d} -> union=4, inter=2 -> pct=0.5 (não > 0.5)
        current = self._make_record(
            keywords=["a", "b", "c"], banner=None
        )
        previous = self._make_record(
            keywords=["a", "b", "d"], banner=None
        )

        alerts = self.detector._compare_communication(current, previous)

        keyword_alerts = [
            a for a in alerts
            if a.attribute_name == "commercial_keywords"
        ]
        assert len(keyword_alerts) == 0

    def test_keywords_mudanca_acima_50_pct_gera_alerta(self) -> None:
        """Mudança > 50% gera alerta."""
        # {a,b,c,d} vs {a,e,f,g} -> union=7, inter=1 -> pct≈0.857 > 0.5
        current = self._make_record(
            keywords=["a", "b", "c", "d"], banner=None
        )
        previous = self._make_record(
            keywords=["a", "e", "f", "g"], banner=None
        )

        alerts = self.detector._compare_communication(current, previous)

        keyword_alerts = [
            a for a in alerts
            if a.attribute_name == "commercial_keywords"
        ]
        assert len(keyword_alerts) == 1
