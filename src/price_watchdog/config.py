"""Módulo de configuração do Price Watchdog usando pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configurações do sistema carregadas de variáveis de ambiente."""

    # Banco de dados
    db_url: str = "postgresql+asyncpg://localhost/price_watchdog"

    # AWS SQS
    sqs_queue_url: str = ""

    # AWS S3
    s3_bucket: str = ""

    # AWS SES
    ses_from_email: str = ""
    ses_recipients: str = ""  # comma-separated

    # AWS Bedrock
    bedrock_model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"

    # Monitoramento
    monitoring_interval_hours: int = 12

    # Thresholds de alerta
    alert_drop_threshold: float = 5.0
    alert_increase_threshold: float = 10.0

    @property
    def recipients_list(self) -> list[str]:
        """Retorna lista de destinatários a partir da string comma-separated."""
        if not self.ses_recipients:
            return []
        return [r.strip() for r in self.ses_recipients.split(",") if r.strip()]

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
    }


# Instância singleton para uso global
settings = Settings()
