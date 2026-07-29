# Implementation Plan: Price Watchdog

## Overview

Implementação do sistema Price Watchdog — monitoramento automatizado de preços de concorrentes (SKY+ e DGO) usando arquitetura distribuída com ECS Fargate, SQS, Aurora PostgreSQL, S3 e Bedrock. O plano segue uma abordagem incremental, começando pela estrutura base e modelos de dados, passando por cada módulo funcional (scraper, comparator, alerts, reports), e finalizando com integração e orquestração.

## Tasks

- [x] 1. Configurar estrutura do projeto e dependências
  - [x] 1.1 Criar estrutura de diretórios e arquivos de configuração
    - Criar `pyproject.toml` com dependências: sqlalchemy[asyncio], asyncpg, playwright, boto3, aioboto3, openpyxl, apscheduler, tenacity, pydantic-settings
    - Criar dependências de dev: pytest, pytest-asyncio, hypothesis, moto[sqs,s3,ses], testcontainers
    - Criar estrutura de pastas: `src/price_watchdog/{coordinator,queue,scraper,comparator,storage,alerts,reports,registry,scheduler,models}/`
    - Criar `tests/{properties,unit,integration}/`
    - Criar `__init__.py` em todos os pacotes
    - _Requirements: 13.3_

  - [x] 1.2 Definir modelos de dados SQLAlchemy e dataclasses
    - Implementar entidades em `src/price_watchdog/models/entities.py`: Competitor, ProductConfig, PriceCycle, PriceRecord, PriceAlert
    - Implementar DTOs em `src/price_watchdog/models/dataclasses.py`: ScrapeResult, ExtractionResult, ValidationResult, PriceCheckMessage, PriceComparison, AlertThresholds
    - Configurar Base declarativa e relacionamentos conforme ER diagram do design
    - _Requirements: 11.1, 11.2_

  - [x] 1.3 Criar módulo de configuração e conexão com banco
    - Implementar `src/price_watchdog/config.py` com pydantic-settings para variáveis de ambiente (DB_URL, SQS_QUEUE_URL, S3_BUCKET, SES_FROM_EMAIL, etc.)
    - Implementar `src/price_watchdog/database.py` com async session factory usando asyncpg
    - Implementar Alembic migrations para criar schema inicial
    - _Requirements: 11.2_

- [x] 2. Implementar módulo de parsing e extração de preços
  - [x] 2.1 Implementar PriceParser
    - Criar `src/price_watchdog/scraper/price_parser.py`
    - Implementar `parse(text: str) -> float | None` com suporte ao Brazilian_Price_Format
    - Implementar `clean(text: str) -> str` para remoção de caracteres inválidos
    - Tratar variações: "R$ 1.299,90", "1299,90", "R$1.299,90", "1.299,90"
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 2.2 Write property tests for PriceParser (Properties 1 e 2)
    - **Property 1: Round-trip de parsing de preço brasileiro**
    - **Property 2: Texto sem padrão de preço retorna None**
    - **Validates: Requirements 6.1, 6.2, 6.3**

  - [x] 2.3 Implementar extractors (CSS, Regex, AI)
    - Criar `src/price_watchdog/scraper/extractors.py`
    - Implementar `BaseExtractor` (ABC) com método `extract(page, selector_or_pattern, product_name) -> ExtractionResult`
    - Implementar `CSSSelectorExtractor`: usa page.query_selector + PriceParser
    - Implementar `RegexExtractor`: aplica regex no page.content() + PriceParser
    - Implementar `AIExtractor`: captura screenshot, envia ao Bedrock, valida confidence >= 80%
    - Implementar retry com tenacity no AIExtractor (3x, backoff exponencial)
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4_

  - [x] 2.4 Write property test for AIExtractor confidence threshold (Property 9)
    - **Property 9: Threshold de confidence do AI Extractor**
    - **Validates: Requirements 5.2, 5.3**

  - [x] 2.5 Implementar PriceScraper
    - Criar `src/price_watchdog/scraper/scraper.py`
    - Implementar navegação com Playwright (timeout 30s)
    - Implementar captura de screenshot full-page (max 5000px)
    - Implementar seleção de estratégia de extração baseada em extraction_strategy
    - Coordenar fluxo: navegar → screenshot → extrair → retornar ScrapeResult
    - _Requirements: 3.1, 3.4, 7.1_

- [x] 3. Implementar módulo de comparação de preços
  - [x] 3.1 Implementar PriceComparator
    - Criar `src/price_watchdog/comparator/comparator.py`
    - Implementar `compare(extracted_price, our_price) -> PriceComparison`
    - Calcular diferença absoluta e percentual conforme fórmulas do design
    - _Requirements: 8.1_

  - [x] 3.2 Write property test for PriceComparator (Property 3)
    - **Property 3: Cálculo de comparação de preços**
    - **Validates: Requirements 8.1**

- [x] 4. Checkpoint - Verificar módulos base
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implementar módulo de storage
  - [x] 5.1 Implementar PriceStore
    - Criar `src/price_watchdog/storage/price_store.py`
    - Implementar `save_record(record: PriceRecord)` com async session
    - Implementar `get_cycle_records(cycle_id)` para buscar records de um ciclo
    - Implementar `get_previous_price(product_config_id)` para buscar último preço extraído com sucesso
    - _Requirements: 8.2, 8.3_

  - [x] 5.2 Implementar ScreenshotStore
    - Criar `src/price_watchdog/storage/screenshot_store.py`
    - Implementar `upload(screenshot_bytes, cycle_id, competitor_id) -> str` com S3 key contendo cycle_id, competitor_id e timestamp
    - Tratar falha de upload graciosamente (log + continuar)
    - _Requirements: 7.2, 7.3, 7.4_

  - [x] 5.3 Write property test for ScreenshotStore S3 key (Property 10)
    - **Property 10: S3 key contém componentes de identificação**
    - **Validates: Requirements 7.2**

- [x] 6. Implementar módulo de fila SQS
  - [x] 6.1 Implementar SQSPublisher
    - Criar `src/price_watchdog/queue/publisher.py`
    - Implementar `publish_batch(messages, batch_size=10)` com batches de 10 mensagens
    - Implementar `publish_all(messages)` dividindo em múltiplos batches
    - _Requirements: 1.2, 2.1_

  - [x] 6.2 Implementar SQSConsumer
    - Criar `src/price_watchdog/queue/consumer.py`
    - Implementar `receive_message() -> PriceCheckMessage | None`
    - Implementar `renew_visibility(receipt_handle, timeout=120)`
    - Implementar `acknowledge(receipt_handle)` para remoção da fila
    - _Requirements: 2.2, 2.4_

  - [x] 6.3 Implementar PriceCheckMessage serialização/deserialização
    - Criar `src/price_watchdog/queue/messages.py`
    - Implementar serialização para JSON (para envio SQS)
    - Implementar deserialização de JSON (para recebimento SQS)
    - Validar presença de todos os campos obrigatórios
    - _Requirements: 2.1_

  - [x] 6.4 Write property tests for SQS message serialization and batching (Properties 6 e 7)
    - **Property 6: Mensagem SQS contém todos os campos obrigatórios (serialização round-trip)**
    - **Property 7: Batching de publicação SQS**
    - **Validates: Requirements 2.1, 1.2**

- [x] 7. Implementar módulo de alertas
  - [x] 7.1 Implementar AlertService
    - Criar `src/price_watchdog/alerts/alert_service.py`
    - Implementar `evaluate(current_price, previous_price, our_price, thresholds) -> PriceAlert | None`
    - Lógica: gerar alerta "price_drop" se queda > threshold_drop (5%), "price_increase" se aumento > threshold_increase (10%)
    - Comparação baseada em variação entre preço atual e preço anterior do concorrente
    - _Requirements: 9.1, 9.2_

  - [x] 7.2 Write property test for AlertService thresholds (Property 4)
    - **Property 4: Alertas baseados em thresholds de variação**
    - **Validates: Requirements 9.1, 9.2**

  - [x] 7.3 Implementar detecção de 3 falhas consecutivas
    - Adicionar lógica em AlertService para verificar se um competitor acumula 3+ falhas consecutivas
    - Gerar alerta "extraction_strategy_outdated" quando detectado
    - _Requirements: 15.6_

  - [x] 7.4 Write property test for consecutive failure detection (Property 13)
    - **Property 13: Detecção de 3 falhas consecutivas por competitor**
    - **Validates: Requirements 15.6**

  - [x] 7.5 Implementar EmailNotifier
    - Criar `src/price_watchdog/alerts/email_notifier.py`
    - Implementar `send_alert(alert, recipients)` com retry 3x backoff exponencial via SES
    - Implementar `send_report(report_bytes, cycle, recipients)` para envio de relatório como anexo
    - _Requirements: 9.3, 9.4_

- [x] 8. Implementar módulo de relatórios
  - [x] 8.1 Implementar ExcelReportGenerator
    - Criar `src/price_watchdog/reports/excel_report.py`
    - Implementar `generate(records, cycle) -> bytes` usando openpyxl
    - Colunas: Concorrente, Produto, Nosso Preço, Preço Deles, Diferença (R$), Diferença (%), Status
    - Implementar `_apply_traffic_light(worksheet, row, pct_diff)` com formatação condicional (verde/amarelo/vermelho)
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 8.2 Write property test for Traffic Light classification (Property 5)
    - **Property 5: Classificação Traffic Light determinística**
    - **Validates: Requirements 10.2**

  - [x] 8.3 Write property test for report completeness (Property 15)
    - **Property 15: Relatório Excel contém todos os records do ciclo**
    - **Validates: Requirements 10.1**

- [x] 9. Checkpoint - Verificar módulos funcionais
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implementar módulo de registro de concorrentes
  - [x] 10.1 Implementar CompetitorManager
    - Criar `src/price_watchdog/registry/competitor_manager.py`
    - Implementar `get_active_configs() -> list[ProductConfig]` filtrando is_active=True
    - Implementar `register_competitor(competitor)` e `register_product_config(config)`
    - Implementar `validate_config(config) -> ValidationResult` (URL acessível + formato do seletor)
    - Implementar `update_our_price(config_id, new_price)` sem afetar histórico
    - Implementar cálculo de taxa de sucesso dos últimos 30 dias
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 15.7_

  - [x] 10.2 Write property tests for registry module (Properties 11, 12, 14)
    - **Property 11: Filtragem de configs ativos exclui inativos**
    - **Property 12: Atualização de preço não afeta registros históricos**
    - **Property 14: Taxa de sucesso calculada corretamente**
    - **Validates: Requirements 11.3, 14.4, 15.7**

  - [x] 10.3 Implementar seed de concorrentes iniciais
    - Implementar `seed_initial_competitors()` no CompetitorManager
    - Criar HBO Max Brasil, Claro TV+ e Vivo TV com URLs e estratégias de extração configuradas
    - Configurar estratégias específicas para cada site (CSS selectors, regex ou AI conforme estrutura)
    - Registrar metadados: data de última atualização da estratégia
    - _Requirements: 14.5, 15.1, 15.2, 15.3, 15.4, 15.5_

- [x] 11. Implementar Coordinator e ciclo de orquestração
  - [x] 11.1 Implementar PriceMonitoringCoordinator
    - Criar `src/price_watchdog/coordinator/coordinator.py`
    - Implementar `run_cycle() -> PriceCycle`: criar ciclo, buscar configs ativos, publicar tarefas
    - Implementar `_publish_tasks(cycle, configs)`: dividir em batches de 10 e publicar via SQSPublisher
    - Tratar falhas de publicação marcando ciclo como "failed"
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 11.2 Implementar CycleConsolidator
    - Criar `src/price_watchdog/coordinator/cycle_consolidator.py`
    - Implementar `wait_for_completion(cycle_id, poll_interval=30)`: polling até todos records processados
    - Implementar `consolidate(cycle)`: atualizar contadores, gerar relatório, enviar email
    - _Requirements: 1.3, 1.4_

  - [x] 11.3 Write property test for cycle consolidation counters (Property 8)
    - **Property 8: Contadores de consolidação de ciclo**
    - **Validates: Requirements 1.4**

- [x] 12. Implementar Worker e fluxo de processamento
  - [x] 12.1 Implementar Worker main loop
    - Criar `src/price_watchdog/worker/worker.py`
    - Implementar loop: receber mensagem → renovar visibility → scrape → comparar → persistir → acknowledge
    - Tratar falhas individuais sem interromper o loop (degradação graciosa)
    - Registrar PriceRecord com status "failed" + razão em caso de erro
    - _Requirements: 12.1, 12.2, 12.3, 2.4_

  - [x] 12.2 Implementar lógica de alertas no Worker
    - Após comparação, buscar preço anterior e avaliar thresholds via AlertService
    - Criar PriceAlert e disparar notificação se threshold excedido
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 13. Implementar módulo de agendamento
  - [x] 13.1 Implementar PriceWatchdogScheduler
    - Criar `src/price_watchdog/scheduler/scheduler.py`
    - Implementar `start()` e `stop()` com APScheduler
    - Configurar intervalo padrão de 12h
    - Integrar com PriceMonitoringCoordinator.run_cycle()
    - _Requirements: 1.1_

- [x] 14. Checkpoint - Verificar integração dos módulos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Implementar infraestrutura e entrypoints
  - [x] 15.1 Criar Dockerfiles
    - `Dockerfile.coordinator` com Python 3.10+ e dependências do coordinator
    - `Dockerfile.worker` com Python 3.10+, Playwright e Chromium headless instalados
    - Otimizar layers para cache de dependências
    - _Requirements: 13.1, 13.2_

  - [x] 15.2 Criar entrypoints da aplicação
    - `src/price_watchdog/main_coordinator.py`: inicializa dependências e inicia scheduler
    - `src/price_watchdog/main_worker.py`: inicializa dependências e inicia loop do worker
    - Configurar graceful shutdown para ambos
    - _Requirements: 13.1_

  - [x] 15.3 Criar template CloudFormation
    - Definir recursos: ECS Cluster, Task Definitions, Services, SQS Queue + DLQ, Aurora PostgreSQL Serverless v2, S3 Bucket (lifecycle 30 dias), SES, CloudWatch Alarms
    - Configurar auto scaling do worker service (1-5 tasks baseado em mensagens na fila)
    - Configurar alarme CloudWatch para mensagens na DLQ
    - _Requirements: 13.1, 13.3, 13.4, 2.3, 2.5, 7.3_

- [x] 16. Wiring final e testes de integração
  - [x] 16.1 Integrar todos os módulos nos entrypoints
    - Conectar todas as dependências no coordinator main
    - Conectar todas as dependências no worker main
    - Verificar que o fluxo completo funciona end-to-end com mocks
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 16.2 Write integration tests
    - Testar publicação e consumo de mensagem SQS (moto)
    - Testar upload/download de screenshot no S3 (moto)
    - Testar CRUD completo no PostgreSQL (testcontainers)
    - Testar scraping com página HTML mockada (Playwright fixture)
    - _Requirements: 2.1, 7.2, 11.1, 3.1_

- [x] 17. Final checkpoint - Validação completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requirements específicos para rastreabilidade
- Checkpoints garantem validação incremental a cada bloco de funcionalidade
- Property tests validam propriedades universais de corretude definidas no design
- Unit tests validam cenários específicos e edge cases
- O projeto usa Python 3.10+ com async/await e type hints em todo o código
- Biblioteca PBT: Hypothesis com mínimo de 100 iterações por propriedade

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1", "6.3"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.2", "6.1", "6.2"] },
    { "id": 4, "tasks": ["2.4", "2.5", "5.1", "5.2", "6.4"] },
    { "id": 5, "tasks": ["5.3", "7.1", "7.3", "8.1", "10.1"] },
    { "id": 6, "tasks": ["7.2", "7.4", "7.5", "8.2", "8.3", "10.2", "10.3"] },
    { "id": 7, "tasks": ["11.1", "11.2"] },
    { "id": 8, "tasks": ["11.3", "12.1"] },
    { "id": 9, "tasks": ["12.2", "13.1"] },
    { "id": 10, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 11, "tasks": ["16.1"] },
    { "id": 12, "tasks": ["16.2"] }
  ]
}
```
