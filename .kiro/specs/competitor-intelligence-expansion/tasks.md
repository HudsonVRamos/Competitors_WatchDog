# Implementation Plan: Expansão de Inteligência Competitiva

## Overview

Implementação da expansão do Price Watchdog para capturar inteligência competitiva (composição de pacotes e comunicação comercial) via extração com Claude Sonnet no Amazon Bedrock. A implementação segue uma abordagem incremental: primeiro os modelos de dados e persistência, depois o extrator de IA com validação, em seguida a integração com o ciclo existente, e finalmente detecção de mudanças e relatórios.

## Tasks

- [x] 1. Modelos de dados e migração de banco
  - [x] 1.1 Criar entidades SQLAlchemy para inteligência competitiva
    - Criar arquivo `src/price_watchdog/models/intelligence_entities.py`
    - Implementar `CompetitorIntelligenceRecord` com campos: id, cycle_id, competitor_id, extraction_status, failure_reason, commercial_keywords (ARRAY), home_banner_description, commercial_positioning_summary, extraction_latency_ms, retry_count, extracted_at, created_at
    - Implementar `PackageComposition` com campos: id, intelligence_record_id, plan_name, default_price, promotional_price, promotional_period_months, linear_channels, simultaneous_screens, has_fiber, fiber_speed_mbps, has_mobile_internet, mobile_speed_mbps, bundled_streaming_1, bundled_streaming_2, bundled_streaming_3
    - Adicionar UniqueConstraint em (cycle_id, competitor_id) para CompetitorIntelligenceRecord
    - Adicionar relationships entre as entidades e com Competitor/PriceCycle existentes
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 1.2 Estender entidade Competitor com campos de inteligência
    - Adicionar campo `intelligence_enabled` (Boolean, default=False) na entidade Competitor em `src/price_watchdog/models/entities.py`
    - Adicionar campo `intelligence_home_url` (String(2048), nullable=True) na entidade Competitor
    - _Requirements: 8.1, 8.4_

  - [x] 1.3 Estender entidade PriceCycle com contadores de inteligência
    - Adicionar campos `intelligence_attempted`, `intelligence_succeeded`, `intelligence_failed` (Integer, default=0) no modelo PriceCycle em `src/price_watchdog/models/entities.py`
    - _Requirements: 4.4_

  - [x] 1.4 Criar migração Alembic para as novas tabelas e campos
    - Gerar migração Alembic com `alembic revision --autogenerate -m "add_competitor_intelligence_tables"`
    - Incluir criação das tabelas `competitor_intelligence_records` e `package_compositions`
    - Incluir alterações na tabela `competitors` (novos campos intelligence_enabled e intelligence_home_url)
    - Incluir alterações na tabela `price_cycles` (novos contadores)
    - _Requirements: 3.1, 3.2, 3.4_

- [x] 2. Dataclasses e mensagens
  - [x] 2.1 Criar dataclasses de inteligência competitiva
    - Criar arquivo `src/price_watchdog/models/intelligence_dataclasses.py`
    - Implementar `PackageCompositionData` com todos os campos de composição
    - Implementar `CommercialCommunicationData` com keywords, banner_description, positioning_summary e status fields
    - Implementar `IntelligenceExtractionResult` com success, status, package_compositions, commercial_communication, failure_reason, retry_count, latency_ms
    - Implementar `IntelligenceAlert` com tipo, competitor_name, attribute_name, previous_value, current_value, plan_name
    - _Requirements: 1.1, 2.1, 7.3_

  - [x] 2.2 Estender PriceCheckMessage com campos de inteligência
    - Adicionar campos `intelligence_enabled: bool = False` e `intelligence_home_url: str | None = None` na dataclass PriceCheckMessage em `src/price_watchdog/queue/messages.py`
    - _Requirements: 4.1_

- [x] 3. Checkpoint - Validar modelos e estrutura base
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. AI Intelligence Extractor — Validação e parsing
  - [x] 4.1 Implementar validação de composição de pacotes
    - Criar arquivo `src/price_watchdog/scraper/intelligence_extractor.py`
    - Implementar método `_validate_composition(self, comp: dict) -> tuple[bool, str]` que valida: Default_Price entre 0.01 e 99999.99, Promotional_Price ≤ Default_Price quando presente, Promotional_Period entre 1 e 36, campos numéricos ≥ 0
    - Campos null devem ser aceitos sem marcar erro
    - _Requirements: 1.2, 1.3_

  - [x] 4.2 Write property test para validação de composição (Property 1)
    - **Property 1: Validação de composição de pacotes aceita dados válidos e rejeita inválidos**
    - **Validates: Requirements 1.2, 5.2**
    - Criar em `tests/properties/test_intelligence_properties.py`
    - Gerar composições com Hypothesis variando Default_Price, Promotional_Price, periods e campos numéricos

  - [x] 4.3 Implementar validação de keywords e comunicação comercial
    - Implementar `_validate_keywords(self, keywords: list[str]) -> tuple[list[str], str]` — aceita 3-15 keywords com max 50 chars cada, retorna "não identificado" se < 3
    - Implementar `_validate_banner(self, description: str) -> str` — trunca a 500 chars
    - Implementar `_validate_positioning(self, summary: str) -> str` — trunca a 1000 chars
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

  - [x] 4.4 Write property test para validação de keywords (Property 4)
    - **Property 4: Validação de keywords aceita listas de 3-15 com max 50 chars**
    - **Validates: Requirements 2.2, 2.3**

  - [x] 4.5 Write property test para truncamento de banner (Property 5)
    - **Property 5: Truncamento de banner description a 500 caracteres**
    - **Validates: Requirements 2.4**

  - [x] 4.6 Implementar normalização de nomes de streaming
    - Implementar `_normalize_streaming_name(self, name: str) -> str` — remove sufixos de tier (Basic, Premium, Standard), aplica capitalização oficial
    - Implementar `_normalize_streamings(self, streamings: list[str]) -> list[str]` — limita a 3 itens, normaliza cada nome
    - _Requirements: 9.2, 9.4, 9.5_

  - [x] 4.7 Write property test para normalização de streamings (Property 10)
    - **Property 10: Normalização de nomes de streaming — truncamento a 3 e remoção de sufixos**
    - **Validates: Requirements 9.2, 9.4**

  - [x] 4.8 Implementar parsing de resposta JSON e validação de schema
    - Implementar `_validate_schema(self, data: dict) -> tuple[bool, str]` — valida presença de "package_composition" e "commercial_communication", tipos corretos
    - Implementar `_parse_packages(self, packages_data: list[dict]) -> list[PackageCompositionData]` — parseia até 20 pacotes, aplica validação individual
    - Implementar `_parse_communication(self, comm_data: dict) -> CommercialCommunicationData` — parseia comunicação com validações
    - _Requirements: 5.1, 5.2, 1.4_

  - [x] 4.9 Write property test para campos null (Property 2)
    - **Property 2: Campos null não marcam extração como falha**
    - **Validates: Requirements 1.3**

  - [x] 4.10 Write property test para parsing de múltiplos pacotes (Property 3)
    - **Property 3: Parsing de múltiplos pacotes com limite de 20**
    - **Validates: Requirements 1.4**

- [x] 5. AI Intelligence Extractor — Prompt e invocação Bedrock
  - [x] 5.1 Implementar construção do prompt estruturado
    - Implementar `_build_prompt(self) -> str` no AIIntelligenceExtractor
    - O prompt deve: solicitar resposta exclusivamente em JSON, incluir o schema esperado com descrição de cada campo, incluir 1 exemplo few-shot completo, incluir regras de preenchimento (null para campos não identificados), especificar o modelo Claude Sonnet utilizado
    - _Requirements: 5.1, 5.3, 5.4, 5.5_

  - [x] 5.2 Implementar invocação do Bedrock com retry e timeout
    - Implementar `_invoke_bedrock(self, screenshot_bytes: bytes, prompt: str) -> dict` usando aioboto3 bedrock-runtime
    - Implementar retry para erros retentáveis (5xx, 429, timeout) com backoff exponencial 2s, 4s, 8s (máximo 3 tentativas)
    - Implementar retry para erros de schema (até 2 tentativas adicionais com feedback do erro no prompt)
    - Implementar timeout global de 120s com abort e cancelamento de tentativas pendentes
    - Classificar erros: 4xx (exceto 429) e schema violations esgotadas → falha imediata
    - _Requirements: 10.2, 10.3, 10.5, 5.3_

  - [x] 5.3 Write property test para erros não-retentáveis (Property 14)
    - **Property 14: Erros não-retentáveis causam falha imediata sem retry**
    - **Validates: Requirements 10.3**

  - [x] 5.4 Implementar método principal `extract()`
    - Implementar `async def extract(self, screenshot_bytes, competitor_name, home_url) -> IntelligenceExtractionResult`
    - Orquestrar: build prompt → invoke bedrock → validate schema → parse packages → parse communication → retornar resultado
    - Tratar status "no_packages_found" quando nenhum pacote identificado (sem marcar falha)
    - Medir latência total e contagem de retries
    - _Requirements: 1.1, 1.5, 2.1_

- [x] 6. Checkpoint - Validar extrator de inteligência
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Persistência de dados de inteligência
  - [x] 7.1 Implementar IntelligenceStore
    - Criar arquivo `src/price_watchdog/storage/intelligence_store.py`
    - Implementar `async def save_record(self, record: CompetitorIntelligenceRecord) -> None` com retry (1s, 2s, 4s) e tratamento de erro de persistência
    - Implementar `async def get_previous_record(self, competitor_id: str) -> CompetitorIntelligenceRecord | None` — busca último registro com status != "failed"
    - Implementar `async def get_records_for_cycle(self, cycle_id: str) -> list[CompetitorIntelligenceRecord]`
    - Garantir append-only (INSERT sem UPDATE/DELETE de registros anteriores)
    - _Requirements: 3.1, 3.5, 3.6_

  - [x] 7.2 Write property test para persistência append-only (Property 6)
    - **Property 6: Persistência append-only preserva registros anteriores**
    - **Validates: Requirements 3.5**

- [x] 8. Integração com Worker e ciclo existente
  - [x] 8.1 Implementar validação de URL de inteligência
    - Adicionar método `validate_intelligence_url(url: str) -> bool` em `src/price_watchdog/registry/competitor_manager.py`
    - Validar esquema http/https com domínio válido, máximo 2048 caracteres
    - _Requirements: 8.5_

  - [x] 8.2 Write property test para validação de URL (Property 9)
    - **Property 9: Validação de URL intelligence_home_url**
    - **Validates: Requirements 8.5**

  - [x] 8.3 Estender Worker com processamento de inteligência
    - Adicionar método `async def _process_intelligence(self, screenshot_bytes, competitor_id, competitor_name, cycle_id, home_url)` em `src/price_watchdog/worker/worker.py`
    - Envolver em try/except isolado — qualquer exceção é logada sem impactar preços
    - Utilizar screenshot já capturado (sem nova navegação)
    - Se screenshot indisponível: registrar "failed" com razão "screenshot_unavailable"
    - Chamar AIIntelligenceExtractor.extract() e persistir resultado via IntelligenceStore
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 10.1_

  - [x] 8.4 Write property test para isolamento de falhas (Property 8)
    - **Property 8: Isolamento — falhas de inteligência não impactam preços**
    - **Validates: Requirements 4.3, 10.1**

  - [x] 8.5 Estender Coordinator para incluir flag de inteligência nas mensagens
    - Modificar `src/price_watchdog/coordinator/coordinator.py` para incluir `intelligence_enabled` e `intelligence_home_url` nas mensagens SQS publicadas
    - Usar `intelligence_home_url` configurada ou fallback para `url_base` quando intelligence_enabled=true e home_url não configurada
    - Filtrar apenas concorrentes com intelligence_enabled=true para extração
    - _Requirements: 4.1, 8.2, 8.3, 8.6_

  - [x] 8.6 Write property test para filtragem por intelligence_enabled (Property 7)
    - **Property 7: Filtragem por intelligence_enabled**
    - **Validates: Requirements 4.1, 8.2, 8.3**

  - [x] 8.7 Estender CycleConsolidator com contadores de inteligência
    - Modificar `src/price_watchdog/coordinator/cycle_consolidator.py` para calcular e persistir contadores: intelligence_attempted, intelligence_succeeded, intelligence_failed
    - _Requirements: 4.4_

- [x] 9. Checkpoint - Validar integração com ciclo existente
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Detecção de mudanças e alertas
  - [x] 10.1 Implementar ChangeDetector para composição de pacotes
    - Criar arquivo `src/price_watchdog/comparator/change_detector.py`
    - Implementar `_compare_compositions(self, current, previous) -> list[IntelligenceAlert]` — compara cada atributo de cada pacote, gera alerta por atributo alterado com valor anterior/atual
    - Tratar primeiro registro como baseline (sem gerar alertas)
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 10.2 Write property test para detecção de mudanças em composição (Property 11)
    - **Property 11: Detecção de mudanças em composição de pacotes**
    - **Validates: Requirements 7.1, 7.3**

  - [x] 10.3 Implementar ChangeDetector para comunicação comercial
    - Implementar `_calculate_keyword_change_pct(self, current, previous) -> float` — calcula % de mudança baseado na interseção dos conjuntos
    - Implementar `_calculate_text_similarity(self, text_a, text_b) -> float` — calcula similaridade textual para banner
    - Implementar `_compare_communication(self, current, previous) -> list[IntelligenceAlert]` — gera alerta "communication_change" se keywords mudaram > 50% OU banner similarity < 60%
    - _Requirements: 7.4_

  - [x] 10.4 Write property test para detecção de mudanças em comunicação (Property 12)
    - **Property 12: Detecção de mudanças significativas em comunicação comercial**
    - **Validates: Requirements 7.4**

  - [x] 10.5 Implementar método principal detect_changes e integrar com alertas
    - Implementar `async def detect_changes(self, current, competitor_id) -> list[IntelligenceAlert]`
    - Buscar registro anterior via IntelligenceStore.get_previous_record()
    - Chamar EmailNotifier existente para enviar alertas de inteligência (tipo "package_composition_change" e "communication_change")
    - Integrar chamada no Worker após persistência bem-sucedida
    - _Requirements: 7.1, 7.5_

- [x] 11. Relatório Excel de inteligência competitiva
  - [x] 11.1 Implementar aba "Composição de Pacotes" no relatório Excel
    - Estender `src/price_watchdog/reports/excel_report.py` com método para gerar aba de composição
    - Colunas: Concorrente, Nome do Pacote, Preço Default, Preço Promocional, Duração Promo (meses), Canais Lineares, Telas Simultâneas, Fibra (Sim/Não), Velocidade Fibra (Mbps), Internet Móvel (Sim/Não), Velocidade Móvel (Mbps), Streaming 1, Streaming 2, Streaming 3
    - Uma linha por pacote identificado, células vazias para atributos null
    - _Requirements: 6.1, 6.2_

  - [x] 11.2 Implementar aba "Comunicação Comercial" no relatório Excel
    - Adicionar aba separada com colunas: Concorrente, Palavras-chave (separadas por vírgula), Descrição Banner, Resumo Posicionamento
    - Uma linha por concorrente com extração bem-sucedida
    - _Requirements: 6.3_

  - [x] 11.3 Integrar abas de inteligência no fluxo de geração de relatório
    - Modificar fluxo de geração para incluir abas de inteligência quando houver dados disponíveis
    - Se nenhum concorrente tiver extração bem-sucedida: omitir abas e incluir indicação no email
    - Enviar Excel como anexo no email de consolidação via SES
    - _Requirements: 6.4, 6.5_

  - [x] 11.4 Write property test para relatório Excel (Property 13)
    - **Property 13: Relatório Excel contém abas de inteligência com estrutura correta**
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 12. Métricas e configuração final
  - [x] 12.1 Implementar registro de métricas de inteligência
    - Adicionar logging estruturado para métricas separadas: extrações com sucesso, com falha, latência média, total de retries por ciclo
    - Garantir métricas de inteligência separadas das métricas de preço existentes
    - _Requirements: 10.4_

  - [x] 12.2 Implementar habilitação/desabilitação de inteligência no CompetitorManager
    - Adicionar métodos `enable_intelligence(competitor_id, home_url=None)` e `disable_intelligence(competitor_id)` em `src/price_watchdog/registry/competitor_manager.py`
    - Garantir que disable não remove dados históricos
    - Validar URL antes de salvar (usar validate_intelligence_url)
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

- [x] 13. Final checkpoint - Validar implementação completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas com `*` são opcionais e podem ser puladas para um MVP mais rápido
- Cada task referencia requirements específicos para rastreabilidade
- Checkpoints garantem validação incremental
- Property tests validam propriedades universais de corretude definidas no design
- Unit tests validam exemplos específicos e edge cases
- O projeto já usa Hypothesis para PBT — seguir padrão existente em `tests/properties/`
- Linguagem de implementação: **Python** (conforme definido no design)
- O AI_Intelligence_Extractor é um componente separado do AIExtractor existente de preços, evitando acoplamento

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.2"] },
    { "id": 2, "tasks": ["1.4"] },
    { "id": 3, "tasks": ["4.1", "4.3", "4.6"] },
    { "id": 4, "tasks": ["4.2", "4.4", "4.5", "4.7", "4.8"] },
    { "id": 5, "tasks": ["4.9", "4.10", "5.1"] },
    { "id": 6, "tasks": ["5.2", "5.4"] },
    { "id": 7, "tasks": ["5.3", "7.1"] },
    { "id": 8, "tasks": ["7.2", "8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3"] },
    { "id": 10, "tasks": ["8.4", "8.5"] },
    { "id": 11, "tasks": ["8.6", "8.7"] },
    { "id": 12, "tasks": ["10.1", "10.3"] },
    { "id": 13, "tasks": ["10.2", "10.4", "10.5"] },
    { "id": 14, "tasks": ["11.1", "11.2"] },
    { "id": 15, "tasks": ["11.3", "11.4"] },
    { "id": 16, "tasks": ["12.1", "12.2"] }
  ]
}
```
