"""Testes unitários para o PriceParser.

Valida parsing de preços em formato brasileiro e limpeza de texto.
Requirements: 6.1, 6.2, 6.3
"""

import pytest

from price_watchdog.scraper.price_parser import PriceParser


class TestPriceParserParse:
    """Testes para o método parse()."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            # Formato completo com R$ e espaço
            ("R$ 1.299,90", 1299.90),
            # Formato com R$ sem espaço
            ("R$1.299,90", 1299.90),
            # Sem símbolo monetário, com milhar
            ("1.299,90", 1299.90),
            # Sem símbolo e sem milhar
            ("1299,90", 1299.90),
            # Valor simples
            ("R$ 99,90", 99.90),
            # Valor sem decimais
            ("R$ 1.299", 1299.0),
            # Valor com um decimal
            ("R$ 99,9", 99.9),
            # Milhões
            ("R$ 1.234.567,89", 1234567.89),
            # Preço embutido em texto
            ("por apenas R$ 49,90/mês", 49.90),
            # Valor inteiro sem separadores
            ("R$ 100", 100.0),
        ],
    )
    def test_parse_formatos_validos(
        self, text: str, expected: float
    ) -> None:
        """Testa parsing de formatos brasileiros válidos."""
        result = PriceParser.parse(text)
        assert result is not None
        assert abs(result - expected) < 0.01

    @pytest.mark.parametrize(
        "text",
        [
            "",             # String vazia
            "   ",          # Apenas espaços
            "abc",          # Texto sem dígitos
            "R$",           # Apenas símbolo
            "sem preço",    # Texto qualquer
        ],
    )
    def test_parse_retorna_none_para_texto_invalido(
        self, text: str
    ) -> None:
        """Testa que textos sem preço retornam None."""
        result = PriceParser.parse(text)
        assert result is None


class TestPriceParserClean:
    """Testes para o método clean()."""

    def test_clean_remove_caracteres_invalidos(self) -> None:
        """Testa remoção de caracteres especiais."""
        assert PriceParser.clean("R$ 1.299,90!") == "R$ 1.299,90"

    def test_clean_mantem_digitos_e_separadores(self) -> None:
        """Testa que dígitos, pontos e vírgulas são preservados."""
        assert PriceParser.clean("1.299,90") == "1.299,90"

    def test_clean_remove_tabs_e_newlines(self) -> None:
        """Testa remoção de whitespace extra (exceto espaço)."""
        result = PriceParser.clean("R$\t1.299,90\n")
        # Tabs e newlines são removidos
        assert "1.299,90" in result

    def test_clean_texto_com_html_entities(self) -> None:
        """Testa limpeza de texto com restos de HTML."""
        result = PriceParser.clean("&nbsp;R$ 99,90&lt;")
        # Mantém apenas R$, dígitos, ponto e vírgula
        assert "R$ 99,90" in result
