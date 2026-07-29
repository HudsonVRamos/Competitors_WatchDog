"""Serviço de alertas para detecção de variações de preço e falhas."""

from __future__ import annotations

from dataclasses import dataclass

from price_watchdog.models.dataclasses import AlertThresholds


@dataclass
class PriceAlert:
    """Alerta gerado por variação significativa de preço.

    Attributes:
        alert_type: Tipo do alerta (price_drop, price_increase,
            extraction_strategy_outdated)
        threshold_pct: Percentual de threshold configurado
        actual_difference_pct: Diferença percentual real detectada
    """

    alert_type: str
    threshold_pct: float
    actual_difference_pct: float


class AlertService:
    """Lógica de detecção e criação de alertas de preço."""

    def evaluate(
        self,
        current_price: float,
        previous_price: float | None,
        our_price: float,
        thresholds: AlertThresholds,
    ) -> PriceAlert | None:
        """Avalia se variação de preço justifica alerta.

        Compara preço atual com preço anterior do concorrente.
        Gera alerta se a variação percentual exceder os thresholds.

        Args:
            current_price: Preço atual extraído do concorrente.
            previous_price: Preço anterior do concorrente (None se
                primeira extração).
            our_price: Nosso preço de referência.
            thresholds: Thresholds configurados para disparo.

        Returns:
            PriceAlert se variação exceder threshold, None caso
            contrário.
        """
        if previous_price is None:
            return None

        if previous_price == 0:
            return None

        pct_change = (
            (current_price - previous_price) / previous_price * 100
        )

        if pct_change < 0 and abs(pct_change) > thresholds.price_drop_pct:
            return PriceAlert(
                alert_type="price_drop",
                threshold_pct=thresholds.price_drop_pct,
                actual_difference_pct=pct_change,
            )

        if pct_change > 0 and pct_change > thresholds.price_increase_pct:
            return PriceAlert(
                alert_type="price_increase",
                threshold_pct=thresholds.price_increase_pct,
                actual_difference_pct=pct_change,
            )

        return None

    def check_consecutive_failures(
        self,
        extraction_statuses: list[str],
        threshold: int = 3,
    ) -> bool:
        """Verifica se há falhas consecutivas nos ciclos mais recentes.

        Analisa a sequência de status de extração de um competitor,
        ordenada do mais recente ao mais antigo, e determina se há
        falhas consecutivas suficientes para gerar um alerta de
        "extraction_strategy_outdated".

        Os status "failed" e "not_found" são considerados falhas.

        Args:
            extraction_statuses: Lista de status de extração ordenados
                do mais recente ao mais antigo.
            threshold: Número mínimo de falhas consecutivas para gerar
                alerta (padrão 3).

        Returns:
            True se há falhas consecutivas suficientes para gerar
            alerta "extraction_strategy_outdated".
        """
        if len(extraction_statuses) < threshold:
            return False

        failure_statuses = {"failed", "not_found"}
        consecutive_failures = 0

        for status in extraction_statuses:
            if status in failure_statuses:
                consecutive_failures += 1
            else:
                break

        return consecutive_failures >= threshold
