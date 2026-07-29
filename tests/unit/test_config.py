"""Testes unitários para o módulo de configuração."""

import os

import pytest


class TestSettings:
    """Testes para a classe Settings."""

    def test_default_db_url(self):
        """Deve ter DB_URL padrão para PostgreSQL async."""
        from price_watchdog.config import Settings

        s = Settings()
        assert s.db_url == "postgresql+asyncpg://localhost/price_watchdog"

    def test_default_monitoring_interval(self):
        """Intervalo padrão de monitoramento deve ser 12 horas."""
        from price_watchdog.config import Settings

        s = Settings()
        assert s.monitoring_interval_hours == 12

    def test_default_alert_thresholds(self):
        """Thresholds padrão de alerta: drop 5%, increase 10%."""
        from price_watchdog.config import Settings

        s = Settings()
        assert s.alert_drop_threshold == 5.0
        assert s.alert_increase_threshold == 10.0

    def test_default_bedrock_model_id(self):
        """Deve ter model_id do Bedrock configurado."""
        from price_watchdog.config import Settings

        s = Settings()
        assert "claude" in s.bedrock_model_id.lower() or "anthropic" in s.bedrock_model_id.lower()

    def test_recipients_list_empty(self):
        """Lista de destinatários vazia quando não configurada."""
        from price_watchdog.config import Settings

        s = Settings(ses_recipients="")
        assert s.recipients_list == []

    def test_recipients_list_single(self):
        """Lista de destinatários com um email."""
        from price_watchdog.config import Settings

        s = Settings(ses_recipients="user@example.com")
        assert s.recipients_list == ["user@example.com"]

    def test_recipients_list_multiple(self):
        """Lista de destinatários com múltiplos emails comma-separated."""
        from price_watchdog.config import Settings

        s = Settings(ses_recipients="a@test.com, b@test.com, c@test.com")
        assert s.recipients_list == ["a@test.com", "b@test.com", "c@test.com"]

    def test_recipients_list_trims_whitespace(self):
        """Deve remover espaços em branco dos emails."""
        from price_watchdog.config import Settings

        s = Settings(ses_recipients="  a@test.com ,  b@test.com  ")
        assert s.recipients_list == ["a@test.com", "b@test.com"]

    def test_env_override(self, monkeypatch):
        """Variáveis de ambiente devem sobrescrever defaults."""
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://prod/watchdog")
        monkeypatch.setenv("MONITORING_INTERVAL_HOURS", "6")
        monkeypatch.setenv("ALERT_DROP_THRESHOLD", "3.5")

        from price_watchdog.config import Settings

        s = Settings()
        assert s.db_url == "postgresql+asyncpg://prod/watchdog"
        assert s.monitoring_interval_hours == 6
        assert s.alert_drop_threshold == 3.5
