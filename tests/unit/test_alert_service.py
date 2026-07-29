"""Testes unitários para AlertService.check_consecutive_failures."""

import pytest

from price_watchdog.alerts.alert_service import AlertService


class TestCheckConsecutiveFailures:
    """Testes para detecção de falhas consecutivas."""

    def setup_method(self) -> None:
        """Configura instância do AlertService para cada teste."""
        self.service = AlertService()

    def test_three_failures_returns_true(self) -> None:
        """3 falhas consecutivas recentes devem gerar alerta."""
        statuses = ["failed", "failed", "failed", "success"]
        assert self.service.check_consecutive_failures(statuses) is True

    def test_three_not_found_returns_true(self) -> None:
        """3 status 'not_found' consecutivos geram alerta."""
        statuses = ["not_found", "not_found", "not_found"]
        assert self.service.check_consecutive_failures(statuses) is True

    def test_mixed_failures_returns_true(self) -> None:
        """Mix de 'failed' e 'not_found' conta como falhas."""
        statuses = ["failed", "not_found", "failed", "success"]
        assert self.service.check_consecutive_failures(statuses) is True

    def test_two_failures_returns_false(self) -> None:
        """Menos de 3 falhas consecutivas não geram alerta."""
        statuses = ["failed", "failed", "success", "failed"]
        assert self.service.check_consecutive_failures(statuses) is False

    def test_success_first_returns_false(self) -> None:
        """Sucesso no ciclo mais recente não gera alerta."""
        statuses = ["success", "failed", "failed", "failed"]
        assert self.service.check_consecutive_failures(statuses) is False

    def test_empty_list_returns_false(self) -> None:
        """Lista vazia não gera alerta."""
        assert self.service.check_consecutive_failures([]) is False

    def test_fewer_than_threshold_items_returns_false(self) -> None:
        """Lista menor que threshold não pode gerar alerta."""
        statuses = ["failed", "failed"]
        assert self.service.check_consecutive_failures(statuses) is False

    def test_custom_threshold(self) -> None:
        """Threshold customizado deve ser respeitado."""
        statuses = ["failed", "failed", "failed", "failed", "failed"]
        assert self.service.check_consecutive_failures(
            statuses, threshold=5
        ) is True

    def test_custom_threshold_not_met(self) -> None:
        """Threshold customizado não atingido retorna False."""
        statuses = ["failed", "failed", "failed", "failed"]
        assert self.service.check_consecutive_failures(
            statuses, threshold=5
        ) is False

    def test_all_success_returns_false(self) -> None:
        """Todos os ciclos com sucesso não geram alerta."""
        statuses = ["success", "success", "success", "success"]
        assert self.service.check_consecutive_failures(statuses) is False

    def test_failure_after_success_not_counted(self) -> None:
        """Falhas após um sucesso não contam na contagem."""
        statuses = [
            "success", "failed", "failed", "failed", "failed"
        ]
        assert self.service.check_consecutive_failures(statuses) is False

    def test_exactly_three_failures_all_list(self) -> None:
        """Exatamente 3 itens todos com falha gera alerta."""
        statuses = ["failed", "not_found", "failed"]
        assert self.service.check_consecutive_failures(statuses) is True
