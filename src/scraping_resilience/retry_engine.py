"""RetryEngine - Motor de retry com backoff exponencial.

Executa operações críticas com até 3 tentativas e delays crescentes
seguindo backoff exponencial (2s, 4s, 8s por padrão).

Classifica erros em:
- Erros de rede (TimeoutError, DNS, connection reset) -> NETWORK_ERROR
- Erros de scraper (falha de interação, elemento não encontrado)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

from src.scraping_resilience.errors import NetworkError
from src.scraping_resilience.models import RetryResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryEngine:
    """Executa etapas críticas com retry automático.

    Aplica backoff exponencial entre tentativas:
    delay = base_delay_seconds * exponential_base^(attempt - 1)

    Com valores padrão (base=2.0, exp=2.0):
    - Tentativa 1: sem delay (execução imediata)
    - Tentativa 2: delay de 2s (2 * 2^0)
    - Tentativa 3: delay de 4s (2 * 2^1)

    Total máximo de delay: 2 + 4 = 6s (entre tentativas 1→2 e 2→3)
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_seconds: float = 2.0,
        exponential_base: float = 2.0,
    ) -> None:
        """Inicializa o RetryEngine.

        Args:
            max_attempts: Número máximo de tentativas (padrão: 3).
            base_delay_seconds: Delay base em segundos (padrão: 2.0).
            exponential_base: Base do expoente para backoff (padrão: 2.0).
        """
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.exponential_base = exponential_base

    def _classify_error(self, error: BaseException) -> str:
        """Classifica um erro como NETWORK_ERROR ou SCRAPER_ERROR.

        Erros de rede incluem:
        - TimeoutError (timeout de conexão)
        - ConnectionError (connection reset, refused, etc.)
        - OSError com "DNS" ou "reset" na mensagem

        Args:
            error: A exceção a ser classificada.

        Returns:
            "NETWORK_ERROR" ou "SCRAPER_ERROR".
        """
        # NetworkError já classificado pelo módulo
        if isinstance(error, NetworkError):
            return "NETWORK_ERROR"

        # TimeoutError (timeout de conexão, asyncio.TimeoutError)
        if isinstance(error, TimeoutError):
            return "NETWORK_ERROR"

        # ConnectionError (connection reset, refused, etc.)
        if isinstance(error, ConnectionError):
            return "NETWORK_ERROR"

        # OSError com indicadores de rede (DNS failure, reset)
        if isinstance(error, OSError):
            msg = str(error).lower()
            if "dns" in msg or "reset" in msg:
                return "NETWORK_ERROR"

        return "SCRAPER_ERROR"

    def _calculate_delay(self, attempt: int) -> float:
        """Calcula o delay para a próxima tentativa.

        Formula: base_delay_seconds * exponential_base^(attempt - 1)

        Com valores padrão:
        - Após tentativa 1: 2 * 2^0 = 2s
        - Após tentativa 2: 2 * 2^1 = 4s
        - Após tentativa 3: 2 * 2^2 = 8s

        Args:
            attempt: Número da tentativa atual (1-indexed).

        Returns:
            Delay em segundos antes da próxima tentativa.
        """
        return self.base_delay_seconds * (
            self.exponential_base ** (attempt - 1)
        )

    async def execute(
        self,
        operation: Callable[..., Awaitable[T]],
        operation_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> RetryResult:
        """Executa operação com até max_attempts tentativas.

        Backoff: base_delay * exponential_base^(attempt-1)
        Delays padrão: 2s, 4s, 8s

        Args:
            operation: Função assíncrona a ser executada.
            operation_name: Nome descritivo da operação (para logs).
            *args: Argumentos posicionais para a operação.
            **kwargs: Argumentos nomeados para a operação.

        Returns:
            RetryResult com success=True e result no primeiro sucesso,
            ou success=False com todas as mensagens de erro se todas
            tentativas falharem.
        """
        errors: list[str] = []
        total_delay_ms: int = 0

        for attempt in range(1, self.max_attempts + 1):
            try:
                logger.info(
                    "RetryEngine: tentativa %d/%d para '%s'",
                    attempt,
                    self.max_attempts,
                    operation_name,
                )

                result = await operation(*args, **kwargs)

                logger.info(
                    "RetryEngine: '%s' concluída com sucesso "
                    "na tentativa %d/%d",
                    operation_name,
                    attempt,
                    self.max_attempts,
                )

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt,
                    errors=errors,
                    total_delay_ms=total_delay_ms,
                )

            except Exception as exc:
                error_type = self._classify_error(exc)
                error_msg = (
                    f"Tentativa {attempt}/{self.max_attempts} "
                    f"[{error_type}]: {type(exc).__name__}: {exc}"
                )
                errors.append(error_msg)

                logger.warning(
                    "RetryEngine: falha na tentativa %d/%d "
                    "para '%s' - %s: %s (classificação: %s)",
                    attempt,
                    self.max_attempts,
                    operation_name,
                    type(exc).__name__,
                    str(exc),
                    error_type,
                )

                # Se não é a última tentativa, aplica backoff
                if attempt < self.max_attempts:
                    delay = self._calculate_delay(attempt)
                    delay_ms = int(delay * 1000)
                    total_delay_ms += delay_ms

                    logger.info(
                        "RetryEngine: aguardando %.1fs antes "
                        "da próxima tentativa para '%s'",
                        delay,
                        operation_name,
                    )

                    await asyncio.sleep(delay)

        # Todas as tentativas falharam
        # Determinar classificação final baseada no último erro
        last_error_type = "SCRAPER_ERROR"
        if errors:
            last_msg = errors[-1]
            if "NETWORK_ERROR" in last_msg:
                last_error_type = "NETWORK_ERROR"

        logger.error(
            "RetryEngine: todas as %d tentativas falharam para '%s' "
            "(classificação final: %s). Erros: %s",
            self.max_attempts,
            operation_name,
            last_error_type,
            errors,
        )

        return RetryResult(
            success=False,
            result=None,
            attempts=self.max_attempts,
            errors=errors,
            total_delay_ms=total_delay_ms,
        )
