"""Scraping Resilience - Módulo de resiliência para scraping de concorrentes.

Fornece mecanismos robustos de navegação, detecção de geolocalização,
interação com componentes customizados e diagnóstico avançado para o
PriceScraper do Price Watchdog.

Componentes principais:
- IntelligentWaitManager: Esperas inteligentes baseadas em condição
- RetryEngine: Retry automático com backoff exponencial
- ContentValidator: Validação de região/idioma/moeda
- GeolocationCookieInjector: Injeção de cookies de localização pré-navegação
- CustomComponentInteractor: Interação com componentes de UI não-nativos
- DiagnosticsCollector: Coleta de artefatos diagnósticos em erro
- StepScreenshotter: Screenshots sequenciais por etapa de navegação
- HealthCheckScorer: Classificação de saúde por execução
"""
