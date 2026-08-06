"""Módulo de notificação por email via Amazon SES."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aioboto3
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from price_watchdog.alerts.alert_service import PriceAlert
from price_watchdog.config import settings
from price_watchdog.models.entities import PriceCycle
from price_watchdog.models.intelligence_dataclasses import (
    IntelligenceAlert,
)

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Envio de emails via Amazon SES."""

    def __init__(self) -> None:
        self._session = aioboto3.Session()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _send_raw_email(self, raw_message: bytes) -> None:
        """Envia email raw via SES com retry automático."""
        async with self._session.client("ses") as ses:
            await ses.send_raw_email(
                Source=settings.ses_from_email,
                RawMessage={"Data": raw_message},
            )

    async def send_alert(
        self, alert: PriceAlert, recipients: list[str]
    ) -> None:
        """Envia email de alerta com retry (3x, backoff exponencial).

        Args:
            alert: Alerta de preço a ser notificado.
            recipients: Lista de destinatários do email.
        """
        if not recipients:
            logger.warning("Nenhum destinatário configurado para alerta.")
            return

        subject = self._build_alert_subject(alert)
        body = self._build_alert_body(alert)

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = settings.ses_from_email
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "html", "utf-8"))

        try:
            await self._send_raw_email(msg.as_bytes())
            logger.info(
                "Alerta enviado com sucesso para %s: %s",
                recipients,
                alert.alert_type,
            )
        except Exception:
            logger.error(
                "Falha ao enviar alerta após 3 tentativas: %s",
                alert.alert_type,
                exc_info=True,
            )

    async def send_report(
        self,
        report_bytes: bytes,
        cycle: PriceCycle,
        recipients: list[str],
        intelligence_all_failed: bool = False,
    ) -> None:
        """Envia relatório Excel como anexo.

        Args:
            report_bytes: Bytes do arquivo Excel gerado.
            cycle: Ciclo de monitoramento associado ao relatório.
            recipients: Lista de destinatários do email.
            intelligence_all_failed: Se True, inclui indicação de
                que a extração de inteligência falhou para todos
                os concorrentes.
        """
        if not recipients:
            logger.warning(
                "Nenhum destinatário configurado para relatório."
            )
            return

        subject = self._build_report_subject(cycle)
        body = self._build_report_body(
            cycle, intelligence_all_failed=intelligence_all_failed
        )

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = settings.ses_from_email
        msg["To"] = ", ".join(recipients)

        # Corpo do email
        msg.attach(MIMEText(body, "html", "utf-8"))

        # Anexo Excel
        attachment = MIMEApplication(report_bytes)
        filename = f"relatorio_ciclo_{cycle.id}.xlsx"
        attachment.add_header(
            "Content-Disposition", "attachment", filename=filename
        )
        attachment.add_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet",
        )
        msg.attach(attachment)

        try:
            await self._send_raw_email(msg.as_bytes())
            logger.info(
                "Relatório do ciclo %s enviado para %s",
                cycle.id,
                recipients,
            )
        except Exception:
            logger.error(
                "Falha ao enviar relatório do ciclo %s após 3 tentativas",
                cycle.id,
                exc_info=True,
            )

    def _build_alert_subject(self, alert: PriceAlert) -> str:
        """Constrói o assunto do email de alerta."""
        type_label = {
            "price_drop": "⬇️ Queda de Preço",
            "price_increase": "⬆️ Aumento de Preço",
            "extraction_strategy_outdated": "⚠️ Estratégia Desatualizada",
        }
        label = type_label.get(alert.alert_type, alert.alert_type)
        return f"[Price Watchdog] {label} - {alert.actual_difference_pct:+.1f}%"

    def _build_alert_body(self, alert: PriceAlert) -> str:
        """Constrói o corpo HTML do email de alerta."""
        type_description = {
            "price_drop": "Queda de preço detectada",
            "price_increase": "Aumento de preço detectado",
            "extraction_strategy_outdated": (
                "Estratégia de extração possivelmente desatualizada"
            ),
        }
        description = type_description.get(
            alert.alert_type, alert.alert_type
        )

        return f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2 style="color: #333;">{description}</h2>
    <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Tipo de Alerta
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.alert_type}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Variação Detectada
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.actual_difference_pct:+.2f}%
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Threshold Configurado
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.threshold_pct:.2f}%
            </td>
        </tr>
    </table>
    <p style="color: #666; margin-top: 20px; font-size: 12px;">
        Este alerta foi gerado automaticamente pelo Price Watchdog.
    </p>
</body>
</html>
"""

    def _build_report_subject(self, cycle: PriceCycle) -> str:
        """Constrói o assunto do email de relatório."""
        return (
            f"[Price Watchdog] Relatório do Ciclo - "
            f"{cycle.started_at.strftime('%d/%m/%Y %H:%M')}"
        )

    def _build_report_body(
        self,
        cycle: PriceCycle,
        intelligence_all_failed: bool = False,
    ) -> str:
        """Constrói o corpo HTML do email de relatório.

        Args:
            cycle: PriceCycle com metadados do ciclo.
            intelligence_all_failed: Se True, inclui indicação de
                falha na extração de inteligência competitiva.
        """
        ended = (
            cycle.ended_at.strftime("%d/%m/%Y %H:%M")
            if cycle.ended_at
            else "Em andamento"
        )

        intelligence_notice = ""
        if intelligence_all_failed:
            intelligence_notice = """
    <div style="background-color: #FFF3CD; border: 1px solid #FFEEBA; \
border-radius: 4px; padding: 12px; margin-top: 16px;">
        <strong style="color: #856404;">⚠️ Inteligência Competitiva</strong>
        <p style="color: #856404; margin: 4px 0 0 0; font-size: 13px;">
            A extração de inteligência competitiva falhou para todos os \
concorrentes neste ciclo. As abas de composição de pacotes e \
comunicação comercial foram omitidas do relatório.
        </p>
    </div>"""

        return f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2 style="color: #333;">Relatório de Monitoramento de Preços</h2>
    <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Ciclo ID
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {cycle.id}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Início
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {cycle.started_at.strftime('%d/%m/%Y %H:%M')}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Término
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {ended}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Total de Produtos
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {cycle.total_products}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Sucesso
            </td>
            <td style="padding: 8px; border: 1px solid #ddd; color: green;">
                {cycle.products_succeeded}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Falha
            </td>
            <td style="padding: 8px; border: 1px solid #ddd; color: red;">
                {cycle.products_failed}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold;">
                Alertas Disparados
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {cycle.alerts_triggered}
            </td>
        </tr>
    </table>{intelligence_notice}
    <p style="color: #666; margin-top: 20px;">
        O relatório Excel detalhado está em anexo.
    </p>
    <p style="color: #666; font-size: 12px;">
        Gerado automaticamente pelo Price Watchdog.
    </p>
</body>
</html>
"""

    async def send_intelligence_alert(
        self,
        alert: IntelligenceAlert,
        recipients: list[str],
    ) -> None:
        """Envia email de alerta de inteligência competitiva.

        Envia notificação para destinatários configurados quando
        mudanças são detectadas em composição de pacotes ou
        comunicação comercial de um concorrente.

        Args:
            alert: Alerta de inteligência competitiva.
            recipients: Lista de destinatários do email.
        """
        if not recipients:
            logger.warning(
                "Nenhum destinatário configurado para "
                "alerta de inteligência."
            )
            return

        subject = self._build_intelligence_alert_subject(alert)
        body = self._build_intelligence_alert_body(alert)

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = settings.ses_from_email
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "html", "utf-8"))

        try:
            await self._send_raw_email(msg.as_bytes())
            logger.info(
                "Alerta de inteligência enviado para %s: "
                "tipo=%s, concorrente=%s",
                recipients,
                alert.alert_type,
                alert.competitor_name,
            )
        except Exception:
            logger.error(
                "Falha ao enviar alerta de inteligência após "
                "3 tentativas: tipo=%s, concorrente=%s",
                alert.alert_type,
                alert.competitor_name,
                exc_info=True,
            )

    def _build_intelligence_alert_subject(
        self, alert: IntelligenceAlert
    ) -> str:
        """Constrói o assunto do email de alerta de inteligência."""
        type_label = {
            "package_composition_change": (
                "📦 Mudança em Composição de Pacote"
            ),
            "communication_change": (
                "📢 Mudança em Comunicação Comercial"
            ),
        }
        label = type_label.get(alert.alert_type, alert.alert_type)
        return (
            f"[Price Watchdog] {label} - "
            f"{alert.competitor_name}"
        )

    def _build_intelligence_alert_body(
        self, alert: IntelligenceAlert
    ) -> str:
        """Constrói o corpo HTML do email de alerta de inteligência."""
        now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

        plan_row = ""
        if alert.plan_name:
            plan_row = f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Plano
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.plan_name}
            </td>
        </tr>"""

        previous_display = (
            alert.previous_value if alert.previous_value else "N/A"
        )
        current_display = (
            alert.current_value if alert.current_value else "N/A"
        )

        type_description = {
            "package_composition_change": (
                "Mudança detectada na composição de pacote"
            ),
            "communication_change": (
                "Mudança detectada na comunicação comercial"
            ),
        }
        description = type_description.get(
            alert.alert_type, "Mudança detectada"
        )

        return f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2 style="color: #333;">{description}</h2>
    <table style="border-collapse: collapse; width: 100%; \
max-width: 600px;">
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Concorrente
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.competitor_name}
            </td>
        </tr>{plan_row}
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Atributo Alterado
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {alert.attribute_name}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Valor Anterior
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {previous_display}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Valor Atual
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {current_display}
            </td>
        </tr>
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd; \
font-weight: bold;">
                Data/Hora da Detecção
            </td>
            <td style="padding: 8px; border: 1px solid #ddd;">
                {now}
            </td>
        </tr>
    </table>
    <p style="color: #666; margin-top: 20px; font-size: 12px;">
        Este alerta foi gerado automaticamente pelo Price Watchdog
        — módulo de inteligência competitiva.
    </p>
</body>
</html>
"""
