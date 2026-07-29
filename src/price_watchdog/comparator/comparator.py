"""Módulo de comparação de preços extraídos com preços de referência.

Calcula diferenças absolutas e percentuais entre o preço extraído
de um concorrente e o preço de referência próprio.
"""

from price_watchdog.models.dataclasses import PriceComparison


class PriceComparator:
    """Compara preço extraído com preço de referência."""

    def compare(
        self, extracted_price: float, our_price: float
    ) -> PriceComparison:
        """Calcula diferenças absoluta e percentual entre preços.

        Args:
            extracted_price: Preço extraído do concorrente.
            our_price: Nosso preço de referência.

        Returns:
            PriceComparison com os valores calculados.

        Raises:
            ValueError: Se our_price for zero (divisão por zero).
        """
        if our_price == 0:
            raise ValueError(
                "our_price não pode ser zero para cálculo percentual."
            )

        absolute_difference = extracted_price - our_price
        percentage_difference = (
            (extracted_price - our_price) / our_price * 100
        )

        return PriceComparison(
            extracted_price=extracted_price,
            our_price=our_price,
            absolute_difference=absolute_difference,
            percentage_difference=percentage_difference,
        )
