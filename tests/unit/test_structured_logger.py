"""Testes unitários para o StructuredLogger.

Verifica que:
1. log_execution produz JSON com todos os campos obrigatórios (Req 3.1)
2. log_success produz JSON com todos os campos obrigatórios (Req 3.2)
3. log_error produz JSON com campo de erro
4. Todas as saídas JSON são parseáveis
"""

from __future__ import annotations

import json
import logging

import pytest

from src.scraping_resilience.structured_logger import (
    ScrapeExecutionLog,
    ScrapeSuccessLog,
    StructuredLogger,
)


@pytest.fixture
def logger_with_handler(
    caplog: pytest.LogCaptureFixture,
) -> StructuredLogger:
    """StructuredLogger configurado para captura via caplog."""
    return StructuredLogger(logger_name="test_structured_logger")


@pytest.fixture
def sample_execution_log() -> ScrapeExecutionLog:
    """Exemplo de log de execução com todos os campos."""
    return ScrapeExecutionLog(
        url="https://www.netflix.com/br/",
        page_title="Netflix Brasil - Assista a séries e filmes",
        load_time_ms=3200,
        price_count=4,
        plan_count=4,
        detected_language="pt",
        detected_currency="BRL",
    )


@pytest.fixture
def sample_success_log() -> ScrapeSuccessLog:
    """Exemplo de log de sucesso com todos os campos."""
    return ScrapeSuccessLog(
        health_check_score="SUCCESS",
        prices_extracted=4,
        screenshots_count=3,
    )


@pytest.mark.unit
class TestLogExecution:
    """Testes para log_execution — campos obrigatórios (Req 3.1)."""

    def test_log_execution_produz_json_valido(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution produz saída JSON parseável."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        assert len(caplog.records) == 1
        payload = json.loads(caplog.records[0].message)
        assert isinstance(payload, dict)

    def test_log_execution_contem_event_type(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'event' com valor 'scrape_execution'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["event"] == "scrape_execution"

    def test_log_execution_contem_url(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'url'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["url"] == "https://www.netflix.com/br/"

    def test_log_execution_contem_page_title(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'page_title'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        expected = "Netflix Brasil - Assista a séries e filmes"
        assert payload["page_title"] == expected

    def test_log_execution_contem_load_time_ms(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'load_time_ms' numérico."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["load_time_ms"] == 3200
        assert isinstance(payload["load_time_ms"], int)

    def test_log_execution_contem_price_count(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'price_count' numérico."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["price_count"] == 4
        assert isinstance(payload["price_count"], int)

    def test_log_execution_contem_plan_count(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'plan_count' numérico."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["plan_count"] == 4
        assert isinstance(payload["plan_count"], int)

    def test_log_execution_contem_detected_language(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'detected_language'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["detected_language"] == "pt"

    def test_log_execution_contem_detected_currency(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution inclui campo 'detected_currency'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["detected_currency"] == "BRL"

    def test_log_execution_contem_todos_campos_obrigatorios(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution contém todos os 7 campos obrigatórios + event."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        payload = json.loads(caplog.records[0].message)
        campos_obrigatorios = {
            "event",
            "url",
            "page_title",
            "load_time_ms",
            "price_count",
            "plan_count",
            "detected_language",
            "detected_currency",
        }
        assert campos_obrigatorios.issubset(payload.keys())

    def test_log_execution_com_caracteres_unicode(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution suporta caracteres Unicode (acentos, cedilhas)."""
        execution = ScrapeExecutionLog(
            url="https://www.gigamaisfibra.com.br/planos",
            page_title="Giga+ Fibra — Planos de Internet São Paulo",
            load_time_ms=1500,
            price_count=6,
            plan_count=3,
            detected_language="pt",
            detected_currency="BRL",
        )

        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(execution)

        payload = json.loads(caplog.records[0].message)
        assert "São Paulo" in payload["page_title"]


@pytest.mark.unit
class TestLogSuccess:
    """Testes para log_success — campos obrigatórios (Req 3.2)."""

    def test_log_success_produz_json_valido(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success produz saída JSON parseável."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        assert len(caplog.records) == 1
        payload = json.loads(caplog.records[0].message)
        assert isinstance(payload, dict)

    def test_log_success_contem_event_type(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success inclui campo 'event' com valor 'scrape_success'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["event"] == "scrape_success"

    def test_log_success_contem_health_check_score(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success inclui campo 'health_check_score'."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["health_check_score"] == "SUCCESS"

    def test_log_success_contem_prices_extracted(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success inclui campo 'prices_extracted' numérico."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["prices_extracted"] == 4
        assert isinstance(payload["prices_extracted"], int)

    def test_log_success_contem_screenshots_count(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success inclui campo 'screenshots_count' numérico."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        payload = json.loads(caplog.records[0].message)
        assert payload["screenshots_count"] == 3
        assert isinstance(payload["screenshots_count"], int)

    def test_log_success_contem_todos_campos_obrigatorios(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success contém todos os 3 campos obrigatórios + event."""
        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        payload = json.loads(caplog.records[0].message)
        campos_obrigatorios = {
            "event",
            "health_check_score",
            "prices_extracted",
            "screenshots_count",
        }
        assert campos_obrigatorios.issubset(payload.keys())


@pytest.mark.unit
class TestLogError:
    """Testes para log_error — campo de erro."""

    def test_log_error_produz_json_valido(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error produz saída JSON parseável."""
        with caplog.at_level(logging.ERROR, logger="test_structured_logger"):
            logger_with_handler.log_error("Timeout ao navegar")

        assert len(caplog.records) == 1
        payload = json.loads(caplog.records[0].message)
        assert isinstance(payload, dict)

    def test_log_error_contem_event_type(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error inclui campo 'event' com valor 'scrape_error'."""
        with caplog.at_level(logging.ERROR, logger="test_structured_logger"):
            logger_with_handler.log_error("Erro de conexão")

        payload = json.loads(caplog.records[0].message)
        assert payload["event"] == "scrape_error"

    def test_log_error_contem_campo_error(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error inclui campo 'error' com a mensagem."""
        with caplog.at_level(logging.ERROR, logger="test_structured_logger"):
            logger_with_handler.log_error("DNS resolution failed")

        payload = json.loads(caplog.records[0].message)
        assert payload["error"] == "DNS resolution failed"

    def test_log_error_com_kwargs_extras(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error inclui campos adicionais passados via kwargs."""
        with caplog.at_level(logging.ERROR, logger="test_structured_logger"):
            logger_with_handler.log_error(
                "Falha na extração",
                url="https://example.com",
                competitor_id="netflix",
                attempt=3,
            )

        payload = json.loads(caplog.records[0].message)
        assert payload["error"] == "Falha na extração"
        assert payload["url"] == "https://example.com"
        assert payload["competitor_id"] == "netflix"
        assert payload["attempt"] == 3

    def test_log_error_usa_nivel_error(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_error usa nível ERROR no logging."""
        with caplog.at_level(logging.DEBUG, logger="test_structured_logger"):
            logger_with_handler.log_error("Erro crítico")

        assert caplog.records[0].levelno == logging.ERROR


@pytest.mark.unit
class TestStructuredLoggerJsonParseability:
    """Testes para garantir que todas as saídas JSON são parseáveis."""

    def test_execution_log_json_roundtrip(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log de execução sobrevive roundtrip JSON."""
        execution = ScrapeExecutionLog(
            url="https://www.paramountplus.com/br/",
            page_title="Paramount+ Brasil",
            load_time_ms=2800,
            price_count=3,
            plan_count=3,
            detected_language="pt",
            detected_currency="BRL",
        )

        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_execution(execution)

        raw = caplog.records[0].message
        # Parse e re-serialize para verificar integridade
        parsed = json.loads(raw)
        reserialized = json.dumps(parsed, ensure_ascii=False)
        reparsed = json.loads(reserialized)
        assert parsed == reparsed

    def test_success_log_json_roundtrip(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log de sucesso sobrevive roundtrip JSON."""
        success = ScrapeSuccessLog(
            health_check_score="GEO_MISMATCH",
            prices_extracted=0,
            screenshots_count=2,
        )

        with caplog.at_level(logging.INFO, logger="test_structured_logger"):
            logger_with_handler.log_success(success)

        raw = caplog.records[0].message
        parsed = json.loads(raw)
        reserialized = json.dumps(parsed, ensure_ascii=False)
        reparsed = json.loads(reserialized)
        assert parsed == reparsed

    def test_error_log_json_roundtrip(
        self,
        logger_with_handler: StructuredLogger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Log de erro sobrevive roundtrip JSON."""
        with caplog.at_level(logging.ERROR, logger="test_structured_logger"):
            logger_with_handler.log_error(
                "Conexão resetada pelo servidor",
                url="https://www.vivotv.com.br/",
            )

        raw = caplog.records[0].message
        parsed = json.loads(raw)
        reserialized = json.dumps(parsed, ensure_ascii=False)
        reparsed = json.loads(reserialized)
        assert parsed == reparsed

    def test_log_execution_usa_nivel_info(
        self,
        logger_with_handler: StructuredLogger,
        sample_execution_log: ScrapeExecutionLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_execution usa nível INFO no logging."""
        with caplog.at_level(logging.DEBUG, logger="test_structured_logger"):
            logger_with_handler.log_execution(sample_execution_log)

        assert caplog.records[0].levelno == logging.INFO

    def test_log_success_usa_nivel_info(
        self,
        logger_with_handler: StructuredLogger,
        sample_success_log: ScrapeSuccessLog,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """log_success usa nível INFO no logging."""
        with caplog.at_level(logging.DEBUG, logger="test_structured_logger"):
            logger_with_handler.log_success(sample_success_log)

        assert caplog.records[0].levelno == logging.INFO
