"""Logging estruturado (JSON) para execuções de scraping.

Registra eventos de execução e sucesso com todos os campos obrigatórios
definidos nos Requirements 3.1 e 3.2:
- Log de execução: URL, título, tempo de carregamento, qtd preços,
  qtd planos, idioma detectado, moeda detectada
- Log de sucesso: health_check_score, contagem de preços extraídos,
  contagem de screenshots
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ScrapeExecutionLog:
    """Campos obrigatórios do log de execução (Requirement 3.1).

    Registra informações da execução de scraping para um site concorrente.
    """

    url: str
    page_title: str
    load_time_ms: int
    price_count: int
    plan_count: int
    detected_language: str
    detected_currency: str


@dataclass
class ScrapeSuccessLog:
    """Campos adicionais para log de conclusão com sucesso (Requirement 3.2).

    Registra informações de finalização bem-sucedida de uma execução.
    """

    health_check_score: str
    prices_extracted: int
    screenshots_count: int


class StructuredLogger:
    """Logger estruturado (JSON) para execuções de scraping.

    Utiliza o módulo `logging` padrão do Python com saída em formato JSON
    para facilitar parsing por ferramentas de observabilidade (CloudWatch,
    Datadog, etc).
    """

    def __init__(
        self, logger_name: str = "scraping_resilience"
    ) -> None:
        """Inicializa o logger estruturado.

        Args:
            logger_name: Nome do logger (namespace).
                Default: "scraping_resilience".
        """
        self._logger = logging.getLogger(logger_name)

    def log_execution(self, execution: ScrapeExecutionLog) -> None:
        """Loga campos da execução de scraping (Requirement 3.1).

        Registra: URL, título da página, tempo de carregamento (ms),
        quantidade de preços, quantidade de planos, idioma detectado
        e moeda detectada.

        Args:
            execution: Dataclass com os campos obrigatórios da execução.
        """
        payload = {"event": "scrape_execution", **asdict(execution)}
        self._logger.info(
            json.dumps(payload, ensure_ascii=False)
        )

    def log_success(self, success: ScrapeSuccessLog) -> None:
        """Loga campos de conclusão com sucesso (Requirement 3.2).

        Registra: health_check_score, contagem de preços extraídos
        e contagem de screenshots capturados.

        Args:
            success: Dataclass com os campos obrigatórios de sucesso.
        """
        payload = {"event": "scrape_success", **asdict(success)}
        self._logger.info(
            json.dumps(payload, ensure_ascii=False)
        )

    def log_error(self, error_message: str, **kwargs: Any) -> None:
        """Loga evento de erro durante scraping.

        Registra erro com campos adicionais opcionais para contexto.

        Args:
            error_message: Mensagem descritiva do erro.
            **kwargs: Campos adicionais de contexto (url, competitor_id, etc).
        """
        payload = {
            "event": "scrape_error",
            "error": error_message,
            **kwargs,
        }
        self._logger.error(
            json.dumps(payload, ensure_ascii=False)
        )
