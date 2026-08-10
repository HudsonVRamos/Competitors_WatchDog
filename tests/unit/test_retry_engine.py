"""Testes unitários para o RetryEngine.

Verifica o comportamento do motor de retry com backoff exponencial,
classificação de erros e coleta de razões no RetryResult.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.scraping_resilience.errors import NetworkError, ScrapingError
from src.scraping_resilience.models import RetryResult
from src.scraping_resilience.retry_engine import RetryEngine


@pytest.mark.unit
class TestRetryEngineSuccess:
    """Testes para cenários de sucesso do RetryEngine."""

    async def test_sucesso_na_primeira_tentativa(self) -> None:
        """Operação bem-sucedida na primeira tentativa retorna imediatamente."""
        engine = RetryEngine()
        operation = AsyncMock(return_value="resultado_ok")

        result = await engine.execute(operation, "test_op")

        assert result.success is True
        assert result.result == "resultado_ok"
        assert result.attempts == 1
        assert result.errors == []
        assert result.total_delay_ms == 0
        operation.assert_called_once()

    async def test_sucesso_na_segunda_tentativa(self) -> None:
        """Operação falha uma vez e sucede na segunda tentativa."""
        engine = RetryEngine()
        operation = AsyncMock(
            side_effect=[ValueError("erro temporário"), "sucesso"]
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert result.success is True
        assert result.result == "sucesso"
        assert result.attempts == 2
        assert len(result.errors) == 1
        assert "SCRAPER_ERROR" in result.errors[0]

    async def test_sucesso_na_terceira_tentativa(self) -> None:
        """Operação falha duas vezes e sucede na terceira."""
        engine = RetryEngine()
        operation = AsyncMock(
            side_effect=[
                ValueError("erro 1"),
                RuntimeError("erro 2"),
                "terceira_vez",
            ]
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert result.success is True
        assert result.result == "terceira_vez"
        assert result.attempts == 3
        assert len(result.errors) == 2

    async def test_argumentos_passados_para_operacao(self) -> None:
        """Args e kwargs são repassados corretamente à operação."""
        engine = RetryEngine()
        operation = AsyncMock(return_value="ok")

        await engine.execute(
            operation, "test_op", "arg1", "arg2", key="value"
        )

        operation.assert_called_once_with("arg1", "arg2", key="value")


@pytest.mark.unit
class TestRetryEngineFailure:
    """Testes para cenários de falha completa do RetryEngine."""

    async def test_todas_tentativas_falham(self) -> None:
        """Quando todas tentativas falham, retorna success=False."""
        engine = RetryEngine(max_attempts=3)
        operation = AsyncMock(
            side_effect=[
                ValueError("erro 1"),
                ValueError("erro 2"),
                ValueError("erro 3"),
            ]
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert result.success is False
        assert result.result is None
        assert result.attempts == 3
        assert len(result.errors) == 3
        assert "erro 1" in result.errors[0]
        assert "erro 2" in result.errors[1]
        assert "erro 3" in result.errors[2]

    async def test_erros_contem_tipo_e_mensagem(self) -> None:
        """Mensagens de erro contêm tipo da exceção e mensagem."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=ValueError("detalhe do erro")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "ValueError" in result.errors[0]
        assert "detalhe do erro" in result.errors[0]


@pytest.mark.unit
class TestRetryEngineBackoff:
    """Testes para o backoff exponencial do RetryEngine."""

    async def test_delays_padrao_2s_4s(self) -> None:
        """Com 3 tentativas falhando, delays são 2s e 4s."""
        engine = RetryEngine(
            max_attempts=3,
            base_delay_seconds=2.0,
            exponential_base=2.0,
        )
        operation = AsyncMock(
            side_effect=[
                ValueError("1"),
                ValueError("2"),
                ValueError("3"),
            ]
        )

        with patch(
            "src.scraping_resilience.retry_engine.asyncio.sleep"
        ) as mock_sleep:
            result = await engine.execute(operation, "test_op")

        # Delay após tentativa 1: 2 * 2^0 = 2s
        # Delay após tentativa 2: 2 * 2^1 = 4s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2.0)
        mock_sleep.assert_any_call(4.0)

    async def test_total_delay_ms_acumulado(self) -> None:
        """total_delay_ms acumula corretamente os delays."""
        engine = RetryEngine(
            max_attempts=3,
            base_delay_seconds=2.0,
            exponential_base=2.0,
        )
        operation = AsyncMock(
            side_effect=[
                ValueError("1"),
                ValueError("2"),
                ValueError("3"),
            ]
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        # 2000ms + 4000ms = 6000ms
        assert result.total_delay_ms == 6000

    async def test_custom_backoff_parameters(self) -> None:
        """Parâmetros customizados de backoff são respeitados."""
        engine = RetryEngine(
            max_attempts=3,
            base_delay_seconds=1.0,
            exponential_base=3.0,
        )
        operation = AsyncMock(
            side_effect=[
                ValueError("1"),
                ValueError("2"),
                ValueError("3"),
            ]
        )

        with patch(
            "src.scraping_resilience.retry_engine.asyncio.sleep"
        ) as mock_sleep:
            result = await engine.execute(operation, "test_op")

        # Delay após tentativa 1: 1 * 3^0 = 1s
        # Delay após tentativa 2: 1 * 3^1 = 3s
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(3.0)
        # total: 1000 + 3000 = 4000ms
        assert result.total_delay_ms == 4000

    async def test_sem_delay_apos_ultima_tentativa(self) -> None:
        """Não aplica delay após a última tentativa (falha definitiva)."""
        engine = RetryEngine(max_attempts=2)
        operation = AsyncMock(
            side_effect=[ValueError("1"), ValueError("2")]
        )

        with patch(
            "src.scraping_resilience.retry_engine.asyncio.sleep"
        ) as mock_sleep:
            await engine.execute(operation, "test_op")

        # Apenas 1 sleep (entre tentativa 1 e 2)
        assert mock_sleep.call_count == 1


@pytest.mark.unit
class TestRetryEngineErrorClassification:
    """Testes para classificação de erros no RetryEngine."""

    async def test_timeout_error_classificado_como_network(self) -> None:
        """TimeoutError é classificado como NETWORK_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(side_effect=TimeoutError("timeout"))

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "NETWORK_ERROR" in result.errors[0]

    async def test_connection_error_classificado_como_network(
        self,
    ) -> None:
        """ConnectionError é classificado como NETWORK_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=ConnectionError("connection reset")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "NETWORK_ERROR" in result.errors[0]

    async def test_os_error_dns_classificado_como_network(self) -> None:
        """OSError com 'DNS' na mensagem é classificado como NETWORK_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=OSError("DNS resolution failed")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "NETWORK_ERROR" in result.errors[0]

    async def test_os_error_reset_classificado_como_network(self) -> None:
        """OSError com 'reset' na mensagem é classificado como NETWORK_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=OSError("Connection reset by peer")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "NETWORK_ERROR" in result.errors[0]

    async def test_network_error_custom_classificado_como_network(
        self,
    ) -> None:
        """NetworkError do módulo é classificado como NETWORK_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=NetworkError("falha de rede")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "NETWORK_ERROR" in result.errors[0]

    async def test_value_error_classificado_como_scraper(self) -> None:
        """ValueError é classificado como SCRAPER_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=ValueError("elemento não encontrado")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "SCRAPER_ERROR" in result.errors[0]

    async def test_os_error_sem_dns_ou_reset_eh_scraper(self) -> None:
        """OSError sem 'DNS' ou 'reset' é classificado como SCRAPER_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=OSError("permission denied")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "SCRAPER_ERROR" in result.errors[0]

    async def test_scraping_error_base_classificado_como_scraper(
        self,
    ) -> None:
        """ScrapingError (base) é classificado como SCRAPER_ERROR."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(
            side_effect=ScrapingError("falha no scraper")
        )

        with patch("src.scraping_resilience.retry_engine.asyncio.sleep"):
            result = await engine.execute(operation, "test_op")

        assert "SCRAPER_ERROR" in result.errors[0]


@pytest.mark.unit
class TestRetryEngineEdgeCases:
    """Testes para casos de borda do RetryEngine."""

    async def test_max_attempts_1_sem_retry(self) -> None:
        """Com max_attempts=1, não há retry (apenas uma tentativa)."""
        engine = RetryEngine(max_attempts=1)
        operation = AsyncMock(side_effect=ValueError("falha"))

        with patch(
            "src.scraping_resilience.retry_engine.asyncio.sleep"
        ) as mock_sleep:
            result = await engine.execute(operation, "test_op")

        assert result.success is False
        assert result.attempts == 1
        assert len(result.errors) == 1
        mock_sleep.assert_not_called()

    async def test_sucesso_imediato_sem_delay(self) -> None:
        """Sucesso na primeira tentativa não gera nenhum delay."""
        engine = RetryEngine()
        operation = AsyncMock(return_value=42)

        with patch(
            "src.scraping_resilience.retry_engine.asyncio.sleep"
        ) as mock_sleep:
            result = await engine.execute(operation, "test_op")

        assert result.total_delay_ms == 0
        mock_sleep.assert_not_called()
