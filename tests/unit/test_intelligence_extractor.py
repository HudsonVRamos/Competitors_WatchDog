"""Testes unitários para AIIntelligenceExtractor — normalização de streamings.

Valida os métodos _normalize_streaming_name e _normalize_streamings
conforme Requirements 9.2, 9.4, 9.5.
"""

import pytest

from price_watchdog.scraper.intelligence_extractor import (
    AIIntelligenceExtractor,
)


@pytest.fixture
def extractor() -> AIIntelligenceExtractor:
    """Cria instância do extractor para os testes."""
    return AIIntelligenceExtractor()


class TestNormalizeStreamingName:
    """Testes para _normalize_streaming_name."""

    def test_remove_suffix_basic(self, extractor: AIIntelligenceExtractor) -> None:
        """Remove sufixo 'Basic' e aplica capitalização oficial."""
        assert extractor._normalize_streaming_name("netflix basic") == "Netflix"

    def test_remove_suffix_premium(self, extractor: AIIntelligenceExtractor) -> None:
        """Remove sufixo 'Premium' e aplica capitalização oficial."""
        assert extractor._normalize_streaming_name("netflix premium") == "Netflix"

    def test_remove_suffix_standard(self, extractor: AIIntelligenceExtractor) -> None:
        """Remove sufixo 'Standard' e aplica capitalização oficial."""
        assert extractor._normalize_streaming_name("hbo max standard") == "HBO Max"

    def test_remove_suffix_plus(self, extractor: AIIntelligenceExtractor) -> None:
        """Remove sufixo 'Plus' como tier (não confundir com Disney+)."""
        assert extractor._normalize_streaming_name("netflix plus") == "Netflix"

    def test_disney_plus_basic(self, extractor: AIIntelligenceExtractor) -> None:
        """Disney+ com sufixo Basic → Disney+."""
        assert extractor._normalize_streaming_name("DISNEY+ basic") == "Disney+"

    def test_disney_plus_sem_sufixo(self, extractor: AIIntelligenceExtractor) -> None:
        """Disney+ sem sufixo → Disney+."""
        assert extractor._normalize_streaming_name("disney+") == "Disney+"

    def test_hbo_max_uppercase(self, extractor: AIIntelligenceExtractor) -> None:
        """HBO MAX em maiúsculas → HBO Max."""
        assert extractor._normalize_streaming_name("HBO MAX") == "HBO Max"

    def test_paramount_plus(self, extractor: AIIntelligenceExtractor) -> None:
        """Paramount+ normalizado."""
        assert extractor._normalize_streaming_name("paramount+") == "Paramount+"

    def test_amazon_prime_video(self, extractor: AIIntelligenceExtractor) -> None:
        """Amazon Prime Video normalizado."""
        assert extractor._normalize_streaming_name("amazon prime video") == "Amazon Prime Video"

    def test_globoplay(self, extractor: AIIntelligenceExtractor) -> None:
        """Globoplay normalizado."""
        assert extractor._normalize_streaming_name("GLOBOPLAY") == "Globoplay"

    def test_star_plus(self, extractor: AIIntelligenceExtractor) -> None:
        """Star+ normalizado."""
        assert extractor._normalize_streaming_name("star+") == "Star+"

    def test_apple_tv_plus(self, extractor: AIIntelligenceExtractor) -> None:
        """Apple TV+ normalizado."""
        assert extractor._normalize_streaming_name("apple tv+") == "Apple TV+"

    def test_servico_desconhecido_title_case(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Serviço desconhecido aplica title case."""
        assert extractor._normalize_streaming_name("mubi") == "Mubi"

    def test_servico_desconhecido_multiplas_palavras(
        self, extractor: AIIntelligenceExtractor
    ) -> None:
        """Serviço desconhecido com múltiplas palavras aplica title case."""
        assert extractor._normalize_streaming_name("lionsgate play") == "Lionsgate Play"

    def test_case_insensitive_suffix(self, extractor: AIIntelligenceExtractor) -> None:
        """Sufixos são removidos independente do case."""
        assert extractor._normalize_streaming_name("Netflix PREMIUM") == "Netflix"

    def test_whitespace_handling(self, extractor: AIIntelligenceExtractor) -> None:
        """Espaços extras são tratados corretamente."""
        assert extractor._normalize_streaming_name("  netflix  ") == "Netflix"

    def test_empty_string(self, extractor: AIIntelligenceExtractor) -> None:
        """String vazia retorna string vazia."""
        result = extractor._normalize_streaming_name("")
        assert result == ""

    def test_whitespace_only(self, extractor: AIIntelligenceExtractor) -> None:
        """String com apenas espaços retorna string com espaços (sem crash)."""
        result = extractor._normalize_streaming_name("   ")
        assert result == "   "


class TestNormalizeStreamings:
    """Testes para _normalize_streamings."""

    def test_lista_vazia(self, extractor: AIIntelligenceExtractor) -> None:
        """Lista vazia retorna lista vazia."""
        assert extractor._normalize_streamings([]) == []

    def test_um_item(self, extractor: AIIntelligenceExtractor) -> None:
        """Lista com 1 item normaliza corretamente."""
        result = extractor._normalize_streamings(["netflix premium"])
        assert result == ["Netflix"]

    def test_tres_itens(self, extractor: AIIntelligenceExtractor) -> None:
        """Lista com 3 itens mantém todos."""
        result = extractor._normalize_streamings(
            ["netflix", "disney+", "paramount+"]
        )
        assert result == ["Netflix", "Disney+", "Paramount+"]

    def test_mais_de_tres_itens_trunca(self, extractor: AIIntelligenceExtractor) -> None:
        """Lista com mais de 3 itens mantém apenas os 3 primeiros."""
        result = extractor._normalize_streamings(
            ["netflix", "disney+", "paramount+", "hbo max", "globoplay"]
        )
        assert result == ["Netflix", "Disney+", "Paramount+"]
        assert len(result) == 3

    def test_normaliza_cada_item(self, extractor: AIIntelligenceExtractor) -> None:
        """Cada item da lista é normalizado individualmente."""
        result = extractor._normalize_streamings(
            ["netflix premium", "DISNEY+ basic", "hbo max standard"]
        )
        assert result == ["Netflix", "Disney+", "HBO Max"]
