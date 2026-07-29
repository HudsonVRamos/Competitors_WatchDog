"""Parser de preços em formato monetário brasileiro (R$ X.XXX,XX).

Responsável por converter textos contendo preços no formato brasileiro
para valores float, tratando separadores de milhares e decimais.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Padrão para encontrar preço brasileiro no texto.
# Duas alternativas:
# 1) Com separador de milhar: 1.299,90 ou 1.299
# 2) Sem separador de milhar: 1299,90 ou 1299
PRICE_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?)"  # Com milhar
    r"|"
    r"(\d+(?:,\d{1,2}))"                    # Sem milhar, com decimal
    r"|"
    r"(\d+)"                                 # Apenas dígitos
)


class PriceParser:
    """Parser de preços em formato brasileiro (R$ X.XXX,XX)."""

    @staticmethod
    def parse(text: str) -> float | None:
        """Converte texto de preço brasileiro para float.

        Suporta variações como:
        - "R$ 1.299,90" -> 1299.90
        - "R$1.299,90" -> 1299.90
        - "1.299,90" -> 1299.90
        - "1299,90" -> 1299.90
        - "R$ 99,90" -> 99.90

        Args:
            text: Texto contendo preço em formato brasileiro.

        Returns:
            Valor float do preço ou None se não puder converter.
        """
        if not text or not text.strip():
            return None

        try:
            cleaned = PriceParser.clean(text)

            # Remover símbolo R$ (com ou sem espaço)
            cleaned = re.sub(r"R\$\s*", "", cleaned)

            if not cleaned.strip():
                return None

            match = PRICE_PATTERN.search(cleaned)
            if not match:
                logger.warning(
                    "Não foi possível extrair preço do texto: %r",
                    text,
                )
                return None

            # Pegar o grupo que deu match (um dos três)
            price_str = (
                match.group(1) or match.group(2) or match.group(3)
            )

            if not price_str:
                logger.warning(
                    "Não foi possível extrair preço do texto: %r",
                    text,
                )
                return None

            # Remover pontos (separador de milhares)
            price_str = price_str.replace(".", "")
            # Substituir vírgula por ponto (separador decimal)
            price_str = price_str.replace(",", ".")

            result = float(price_str)
            return result

        except (ValueError, AttributeError):
            logger.warning(
                "Falha ao parsear preço do texto: %r", text
            )
            return None

    @staticmethod
    def clean(text: str) -> str:
        """Remove caracteres não-numéricos exceto ponto, vírgula e R$.

        Mantém dígitos, pontos, vírgulas e o símbolo R$ para que o
        padrão de preço possa ser detectado pelo regex.

        Args:
            text: Texto bruto potencialmente com caracteres inválidos.

        Returns:
            Texto limpo contendo apenas caracteres relevantes para
            parsing de preço.
        """
        # Remover caracteres que não são: dígitos, ponto, vírgula,
        # R, $, espaço
        cleaned = re.sub(r"[^\d.,R$\s]", "", text)
        return cleaned.strip()
