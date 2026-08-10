"""Hierarquia de exceções para o módulo Scraping Resilience.

Exceções específicas para classificação de erros durante o scraping:
- ScrapingError: Exceção base para todos os erros de scraping
- NetworkError: Erros de conectividade (timeout, DNS, connection reset)
- GeoMismatchError: Conteúdo em idioma/moeda incorretos (IP americano)
- GeoRedirectError: Redirecionamento para conteúdo de outra região
- ComponentInteractionError: Falha na interação com componentes de UI
"""

from __future__ import annotations


class ScrapingError(Exception):
    """Exceção base para todos os erros de scraping.

    Attributes:
        message: Descrição do erro ocorrido.
        competitor_id: Identificador do concorrente sendo processado.
        cycle_id: Identificador do ciclo de execução.
    """

    def __init__(
        self,
        message: str,
        competitor_id: str | None = None,
        cycle_id: str | None = None,
    ) -> None:
        self.message = message
        self.competitor_id = competitor_id
        self.cycle_id = cycle_id
        super().__init__(message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.competitor_id:
            parts.append(f"competitor_id={self.competitor_id}")
        if self.cycle_id:
            parts.append(f"cycle_id={self.cycle_id}")
        return " | ".join(parts)


class NetworkError(ScrapingError):
    """Erro de conectividade durante o scraping.

    Classificado como NETWORK_ERROR no Health Check Score.
    Inclui timeout de conexão, DNS failure, connection reset.

    Attributes:
        original_error: Exceção original que causou o erro de rede.
        retry_count: Número de tentativas realizadas antes da falha definitiva.
    """

    def __init__(
        self,
        message: str,
        competitor_id: str | None = None,
        cycle_id: str | None = None,
        original_error: BaseException | None = None,
        retry_count: int | None = None,
    ) -> None:
        super().__init__(message, competitor_id=competitor_id, cycle_id=cycle_id)
        self.original_error = original_error
        self.retry_count = retry_count

    def __str__(self) -> str:
        base = super().__str__()
        extras: list[str] = []
        if self.retry_count is not None:
            extras.append(f"retry_count={self.retry_count}")
        if self.original_error is not None:
            extras.append(f"original_error={type(self.original_error).__name__}: {self.original_error}")
        if extras:
            return f"{base} | {' | '.join(extras)}"
        return base


class GeoMismatchError(ScrapingError):
    """Conteúdo carregado em idioma ou moeda incorreta.

    Classificado como GEO_MISMATCH no Health Check Score.
    Ocorre quando o IP americano do worker faz a página servir
    conteúdo em inglês/USD ao invés de português/BRL.

    Attributes:
        indicators: Lista de indicadores encontrados na página (termos em inglês, símbolos USD, etc.).
        detected_language: Idioma detectado na página (ex: "en", "pt").
        detected_currency: Moeda detectada na página (ex: "USD", "BRL").
    """

    def __init__(
        self,
        message: str,
        indicators: list[str],
        competitor_id: str | None = None,
        cycle_id: str | None = None,
        detected_language: str | None = None,
        detected_currency: str | None = None,
    ) -> None:
        super().__init__(message, competitor_id=competitor_id, cycle_id=cycle_id)
        self.indicators = indicators
        self.detected_language = detected_language
        self.detected_currency = detected_currency

    def __str__(self) -> str:
        base = super().__str__()
        extras: list[str] = []
        if self.detected_language:
            extras.append(f"detected_language={self.detected_language}")
        if self.detected_currency:
            extras.append(f"detected_currency={self.detected_currency}")
        if self.indicators:
            extras.append(f"indicators={self.indicators}")
        if extras:
            return f"{base} | {' | '.join(extras)}"
        return base


class GeoRedirectError(ScrapingError):
    """Redirecionamento para conteúdo de outra região.

    Classificado como GEO_REDIRECT no Health Check Score.
    Ocorre quando o CDN redireciona para URL ou conteúdo diferente
    do esperado (ex: página de gift card ao invés de planos).

    Attributes:
        final_url: URL final após o redirecionamento.
        expected_url_pattern: Padrão de URL esperado (ex: "/br/").
        indicators: Lista de indicadores de conteúdo redirecionado encontrados.
    """

    def __init__(
        self,
        message: str,
        final_url: str,
        indicators: list[str],
        competitor_id: str | None = None,
        cycle_id: str | None = None,
        expected_url_pattern: str | None = None,
    ) -> None:
        super().__init__(message, competitor_id=competitor_id, cycle_id=cycle_id)
        self.final_url = final_url
        self.expected_url_pattern = expected_url_pattern
        self.indicators = indicators

    def __str__(self) -> str:
        base = super().__str__()
        extras: list[str] = [f"final_url={self.final_url}"]
        if self.expected_url_pattern:
            extras.append(f"expected_url_pattern={self.expected_url_pattern}")
        if self.indicators:
            extras.append(f"indicators={self.indicators}")
        return f"{base} | {' | '.join(extras)}"


class ComponentInteractionError(ScrapingError):
    """Falha na interação com componente de UI customizado.

    Classificado como SCRAPER_ERROR no Health Check Score.
    Ocorre quando nenhuma estratégia da Cascade Strategy consegue
    interagir com o componente (dropdown, combobox, select).

    Attributes:
        component_type: Tipo do componente detectado (ex: "react_select", "material_ui", "unknown").
        strategy_attempted: Última estratégia tentada ou "all" quando todas falharam.
        selector: Seletor CSS/role utilizado para localizar o componente.
    """

    def __init__(
        self,
        message: str,
        component_type: str,
        strategy_attempted: str,
        competitor_id: str | None = None,
        cycle_id: str | None = None,
        selector: str | None = None,
    ) -> None:
        super().__init__(message, competitor_id=competitor_id, cycle_id=cycle_id)
        self.component_type = component_type
        self.strategy_attempted = strategy_attempted
        self.selector = selector

    def __str__(self) -> str:
        base = super().__str__()
        extras: list[str] = [
            f"component_type={self.component_type}",
            f"strategy_attempted={self.strategy_attempted}",
        ]
        if self.selector:
            extras.append(f"selector={self.selector}")
        return f"{base} | {' | '.join(extras)}"
