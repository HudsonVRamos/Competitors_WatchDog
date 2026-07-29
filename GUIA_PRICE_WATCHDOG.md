# Guia para Novo Projeto: Price Watchdog (Monitoramento de Preços de Concorrentes)

## Contexto

Este documento serve como referência para iniciar um novo projeto inspirado no **Brand Watchdog** (DGO_SKY_WATCHDOG), mas com foco em **monitoramento e comparação de preços** de sites concorrentes. Use este guia como steering file no novo workspace.

---

## 1. Visão Geral do Novo Sistema

**Price Watchdog** é um sistema automatizado que:
- Acessa sites de concorrentes periodicamente
- Extrai preços de produtos/serviços
- Compara com os seus preços atuais
- Gera relatórios de diferenças e tendências
- Alerta quando concorrentes mudam preços significativamente

---

## 2. Arquitetura Recomendada (Baseada no Brand Watchdog)

### 2.1 Diagrama Simplificado

```
┌─────────────────────────────────────────────────────────────────┐
│                    AWS Account (us-east-1)                        │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Orchestration Layer (Coordinator)              │  │
│  │                                                            │  │
│  │  APScheduler ──→ PriceMonitoringCoordinator                │  │
│  │                    ├─ SQSPublisher (batch de 10)            │  │
│  │                    └─ CycleConsolidator (polling 30s)       │  │
│  └───────────────────────────┬───────────────────────────────┘  │
│                              │                                   │
│                  ┌───────────▼───────────┐                      │
│                  │   SQS Queue           │                      │
│                  │   price-watchdog-tasks │                      │
│                  └───────────┬───────────┘                      │
│                              │                                   │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │          Processing Layer (ECS Fargate Workers 1-5)        │  │
│  │                                                            │  │
│  │  Worker: Chromium → Extração → Comparação → DB             │  │
│  │                                                            │  │
│  │  Cada Worker:                                              │  │
│  │  - Acessa 1 site por vez                                   │  │
│  │  - Extrai preços via scraping (seletores CSS ou IA)        │  │
│  │  - Compara com preço de referência (seu preço)             │  │
│  │  - Persiste resultado no banco                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐            │
│  │  Aurora   │ │    S3    │ │ Bedrock  │ │  SES   │            │
│  │PostgreSQL│ │Evidências│ │(opcional)│ │ Email  │            │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Componentes Principais

| Componente | Responsabilidade |
|------------|-----------------|
| `PriceMonitoringCoordinator` | Inicia ciclo, publica na fila, consolida resultados |
| `SQSPublisher` | Publica mensagens em batches de 10 |
| `SQSConsumer` | Recebe 1 msg por vez, gerencia visibility |
| `PriceWorker` | Acessa site, extrai preço, compara, persiste |
| `PriceScraper` | Navega no site e extrai preços (Playwright) |
| `PriceExtractor` | Estratégias de extração (CSS selectors, regex, IA) |
| `PriceComparator` | Compara preço extraído com preço de referência |
| `PriceStore` | Persiste histórico de preços no banco |
| `AlertNotifier` | Envia email quando variação excede threshold |
| `ReportGenerator` | Gera relatório Excel com comparações |

---

## 3. Modelos de Dados

### 3.1 Entidades Principais

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Competitor:
    """Site concorrente monitorado."""
    id: str
    name: str  # Ex: "Concorrente A"
    base_url: str  # Ex: "https://concorrente-a.com.br"
    is_active: bool = True
    created_at: datetime = None


@dataclass
class ProductConfig:
    """Produto/serviço a ser monitorado em um concorrente."""
    id: str
    competitor_id: str
    product_name: str  # Ex: "Plano Básico 200Mbps"
    page_url: str  # URL específica onde o preço aparece
    extraction_strategy: str  # "css_selector" | "regex" | "ai"
    selector_or_pattern: str  # CSS selector ou regex
    our_price: float  # Nosso preço para comparação
    currency: str = "BRL"
    is_active: bool = True


@dataclass
class PriceRecord:
    """Registro de preço extraído."""
    id: str
    product_config_id: str
    competitor_id: str
    extracted_price: float | None
    our_price: float  # Preço nosso no momento da extração
    price_difference: float | None  # extracted - our_price
    price_difference_pct: float | None  # % de diferença
    extraction_status: str  # "success" | "failed" | "not_found"
    failure_reason: str | None
    screenshot_s3_key: str | None  # Evidência
    extracted_at: datetime
    cycle_id: str


@dataclass
class PriceCycle:
    """Ciclo de monitoramento de preços."""
    id: str
    started_at: datetime
    ended_at: datetime | None
    status: str  # "running" | "completed" | "failed"
    products_checked: int
    products_succeeded: int
    products_failed: int
    alerts_triggered: int


@dataclass
class PriceAlert:
    """Alerta de variação de preço."""
    id: str
    price_record_id: str
    alert_type: str  # "price_drop" | "price_increase" | "new_price"
    threshold_pct: float  # Threshold configurado
    actual_difference_pct: float
    notified_at: datetime | None
    recipients: list[str]
```

---

## 4. Estratégias de Extração de Preço

O sistema deve suportar múltiplas estratégias porque cada concorrente tem um site diferente:

### 4.1 CSS Selector (mais simples e rápido)

```python
class CSSSelectorExtractor:
    """Extrai preço via CSS selector."""
    
    async def extract(self, page, selector: str) -> float | None:
        element = await page.query_selector(selector)
        if element:
            text = await element.text_content()
            return self._parse_price(text)
        return None
    
    def _parse_price(self, text: str) -> float | None:
        """Parseia texto de preço brasileiro: R$ 89,90 → 89.90"""
        import re
        # Remove tudo exceto números, vírgula e ponto
        cleaned = re.sub(r'[^\d,.]', '', text)
        # Formato brasileiro: 1.234,56
        cleaned = cleaned.replace('.', '').replace(',', '.')
        try:
            return float(cleaned)
        except ValueError:
            return None
```

### 4.2 Regex (para estruturas conhecidas)

```python
class RegexExtractor:
    """Extrai preço via regex no HTML da página."""
    
    async def extract(self, page, pattern: str) -> float | None:
        html = await page.content()
        match = re.search(pattern, html)
        if match:
            return self._parse_price(match.group(1))
        return None
```

### 4.3 IA / Bedrock (para sites complexos ou dinâmicos)

```python
class AIExtractor:
    """Extrai preço via análise de screenshot com IA (Bedrock)."""
    
    async def extract(self, screenshot_bytes: bytes, product_name: str) -> float | None:
        prompt = f"""
        Analise este screenshot de um site de telecomunicações.
        Encontre o preço do produto/plano: "{product_name}"
        
        Responda APENAS com o JSON:
        {{"price": 89.90, "confidence": 95, "found": true}}
        
        Se não encontrar o preço, responda:
        {{"price": null, "confidence": 0, "found": false}}
        """
        # Invocar Bedrock com screenshot + prompt
        response = await self._bedrock_client.invoke_model(screenshot_bytes, prompt)
        return response.get("price")
```

---

## 5. Configuração do Projeto

### 5.1 Estrutura de Diretórios

```
price_watchdog/
├── __init__.py
├── main.py                      # Entry point do Coordinator
├── worker.py                    # Entry point do Worker ECS
├── config.py                    # Dataclasses de configuração
├── coordinator/
│   ├── coordinator.py           # PriceMonitoringCoordinator
│   └── cycle_consolidator.py   # Consolida resultados
├── scraper/
│   ├── scraper.py              # PriceScraper (Playwright)
│   └── extractors.py           # CSSSelectorExtractor, RegexExtractor, AIExtractor
├── comparator/
│   └── comparator.py           # PriceComparator
├── queue/
│   ├── publisher.py            # SQSPublisher
│   ├── consumer.py             # SQSConsumer
│   └── messages.py             # PriceCheckMessage dataclass
├── storage/
│   ├── price_store.py          # Persistência de preços
│   └── screenshot_store.py     # Evidências em S3
├── alerts/
│   ├── alert_service.py        # Lógica de alertas
│   └── email_notifier.py       # Envio de emails (SES)
├── reports/
│   └── excel_report.py         # Relatório Excel comparativo
├── models/
│   ├── database.py             # SQLAlchemy engine/session
│   ├── entities.py             # Modelos SQLAlchemy
│   └── dataclasses.py          # DTOs e dataclasses
├── registry/
│   └── competitor_manager.py   # CRUD de concorrentes e produtos
└── scheduler/
    └── scheduler.py            # APScheduler
```

### 5.2 config.yaml

```yaml
# Price Watchdog - Configuração
scraper:
  viewport_width: 1920
  page_timeout_seconds: 30
  max_screenshot_height_px: 5000

extraction:
  default_strategy: "css_selector"
  ai_model_id: "us.anthropic.claude-sonnet-4-6"
  ai_region: "us-east-1"
  confidence_threshold: 80

alerts:
  provider: "ses"
  ses_region: "us-east-1"
  ses_sender: ""  # via env
  recipients: []  # via env
  # Thresholds de alerta
  price_drop_threshold_pct: 5.0    # Alerta se concorrente baixou > 5%
  price_increase_threshold_pct: 10.0  # Alerta se concorrente subiu > 10%

schedule:
  interval_hours: 12  # Checar preços 2x por dia

storage:
  database_url: ""  # via env
  s3_bucket: ""  # via env
  s3_region: "us-east-1"
  price_retention_days: 365  # Manter 1 ano de histórico
  screenshot_retention_days: 30

queue:
  queue_url: ""  # via env
  visibility_timeout_seconds: 120

worker:
  processing_timeout_seconds: 60
  visibility_renew_interval_seconds: 30
```

### 5.3 Dependências (pyproject.toml)

```toml
[project]
name = "price-watchdog"
version = "0.1.0"
description = "Monitoramento automatizado de preços de concorrentes"
requires-python = ">=3.10"
dependencies = [
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "playwright>=1.40.0",
    "boto3>=1.34.0",
    "apscheduler>=3.10.0",
    "tenacity>=8.2.0",
    "pyyaml>=6.0.0",
    "openpyxl>=3.1.0",
    "Pillow>=10.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.23.0",
    "hypothesis>=6.92.0",
    "pytest-cov>=4.1.0",
    "moto[s3,sqs]>=5.0.0",
]
```

---

## 6. Fluxo de Execução

### 6.1 Ciclo de Monitoramento

```
1. APScheduler aciona PriceMonitoringCoordinator.run_cycle()
2. Coordinator busca todos os ProductConfig ativos
3. Publica 1 mensagem SQS por ProductConfig (batches de 10)
4. Registra ciclo no DB com status "dispatched"
5. Workers consomem mensagens em paralelo (1-5 tasks)
6. Cada Worker:
   a. Abre page com Playwright
   b. Navega até product_config.page_url
   c. Aplica estratégia de extração configurada
   d. Captura screenshot como evidência (upload S3)
   e. Compara preço extraído com our_price
   f. Persiste PriceRecord no banco
   g. Se variação > threshold → cria PriceAlert
7. CycleConsolidator detecta conclusão
8. Envia email com relatório consolidado (Excel)
```

### 6.2 Mensagem SQS

```python
@dataclass
class PriceCheckMessage:
    """Mensagem para processamento de um produto."""
    product_config_id: str
    competitor_id: str
    competitor_name: str
    product_name: str
    page_url: str
    extraction_strategy: str
    selector_or_pattern: str
    our_price: float
    cycle_id: str
```

---

## 7. Relatório Excel

Gerar um relatório comparativo com as colunas:

| Concorrente | Produto | Nosso Preço | Preço Deles | Diferença (R$) | Diferença (%) | Status |
|-------------|---------|-------------|-------------|----------------|---------------|--------|

Com formatação "farol":
- 🟢 Verde: nosso preço é menor (estamos competitivos)
- 🟡 Amarelo: diferença < 5% (atenção)
- 🔴 Vermelho: nosso preço é maior > 5% (perdendo competitividade)

---

## 8. Infraestrutura AWS (CloudFormation)

### 8.1 Recursos Necessários

| Recurso | Especificação |
|---------|---------------|
| ECS Cluster | Fargate |
| Coordinator Service | 1 task (scheduler) |
| Worker Service | 1-5 tasks (auto scaling) |
| SQS Queue | `price-watchdog-tasks` (visibility 120s) |
| DLQ | `price-watchdog-dlq` (maxReceiveCount=3) |
| Aurora PostgreSQL | Serverless v2 (0.5-2 ACU) |
| S3 Bucket | Screenshots/evidências (lifecycle 30 dias) |
| SES | Envio de alertas e relatórios |
| CloudWatch | Logs + Alarm na DLQ |

### 8.2 Dockerfile do Worker

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

WORKDIR /app

COPY pyproject.toml ./
RUN pip install .
RUN playwright install --with-deps chromium

COPY price_watchdog/ ./price_watchdog/
COPY config.yaml ./

RUN useradd -m -r appuser && chown -R appuser:appuser /app /opt/playwright
USER appuser

CMD ["python", "-m", "price_watchdog.worker"]
```

---

## 9. Diferenças em Relação ao Brand Watchdog

| Aspecto | Brand Watchdog | Price Watchdog |
|---------|---------------|----------------|
| O que monitora | Compliance visual (logos, texto) | Preços numéricos |
| Análise | IA multimodal (sempre) | CSS/Regex (primário) + IA (fallback) |
| Resultado | PASS/FAIL por regra | Preço extraído + comparação |
| Alerta | Violação de compliance | Variação de preço > threshold |
| Frequência | 1x/dia | 2x/dia (ou mais) |
| Complexidade | Alta (6 regras, análise visual) | Média (extração + comparação) |
| Custo Bedrock | Alto (todas as análises) | Baixo (só fallback quando CSS falha) |
| Workers | 1-10 (259 sites) | 1-5 (menos sites, processamento mais rápido) |

---

## 10. Plano de Implementação Sugerido (Tasks para Kiro Specs)

### Wave 0: Scaffolding
- Criar estrutura de diretórios
- Configurar pyproject.toml
- Implementar config.py com dataclasses

### Wave 1: Modelos e Banco
- Criar entidades SQLAlchemy (Competitor, ProductConfig, PriceRecord, PriceCycle, PriceAlert)
- Configurar engine/session async
- Criar migrações Alembic

### Wave 2: Scraper e Extractors
- Implementar PriceScraper com Playwright
- Implementar CSSSelectorExtractor
- Implementar RegexExtractor
- Implementar AIExtractor (opcional, pode ser Wave posterior)
- Implementar _parse_price para formato brasileiro (R$ X.XXX,XX)

### Wave 3: Comparator e Store
- Implementar PriceComparator
- Implementar PriceStore (persistência)
- Implementar ScreenshotStore (evidências S3)

### Wave 4: Queue e Worker
- Implementar SQSPublisher e SQSConsumer
- Implementar PriceWorker (loop principal)
- Configurar timeout e visibility renewal

### Wave 5: Coordinator e Scheduler
- Implementar PriceMonitoringCoordinator
- Implementar CycleConsolidator
- Integrar APScheduler

### Wave 6: Alertas e Relatórios
- Implementar AlertService (lógica de thresholds)
- Implementar EmailNotifier (SES)
- Implementar ExcelReportGenerator

### Wave 7: Infraestrutura
- CloudFormation (ECS, SQS, Aurora, S3)
- Dockerfile.worker
- buildspec para CodeBuild
- Deploy scripts

---

## 11. Dicas Importantes (Lições do Brand Watchdog)

1. **Timeout é crítico**: Sites de concorrentes podem ser lentos. Use timeout de 30s por página e cleanup do Chromium após timeout.

2. **Screenshots como evidência**: Sempre capture screenshot antes de extrair. Se der problema, você tem a prova visual.

3. **Retry em tudo**: SQS publish, Bedrock invoke, S3 upload, email send — tudo com retry 3x e backoff exponencial.

4. **DLQ para debug**: Mensagens que falham 3x vão para DLQ. Configure alarme no CloudWatch.

5. **Parse de preço brasileiro**: R$ 1.299,90 → 1299.90. Cuidado com formatos inconsistentes entre sites.

6. **Visibility timeout**: Se o processamento demora, renove o visibility timeout a cada 30s para evitar reprocessamento.

7. **Auto Scaling conservador**: Comece com 1-3 workers. Escale baseado em mensagens na fila.

8. **Custos**: Se usar IA apenas como fallback, o custo de Bedrock será muito baixo. A maior parte dos preços pode ser extraída com CSS selectors.

9. **Graceful degradation**: Se não conseguir extrair preço de um concorrente, registre como "failed" e continue. Nunca bloqueie o ciclo inteiro.

10. **Histórico de preços**: Mantenha pelo menos 365 dias. Isso permite análise de tendências e sazonalidade.

---

## 12. Exemplo de Configuração de Concorrente

```yaml
# competitors.yaml (pode ser carregado de DB ou arquivo)
competitors:
  - name: "Operadora X"
    base_url: "https://operadora-x.com.br"
    products:
      - name: "Internet 200Mbps"
        page_url: "https://operadora-x.com.br/planos"
        strategy: "css_selector"
        selector: ".plan-card[data-speed='200'] .price-value"
        our_price: 99.90

      - name: "Internet 500Mbps"
        page_url: "https://operadora-x.com.br/planos"
        strategy: "css_selector"
        selector: ".plan-card[data-speed='500'] .price-value"
        our_price: 149.90

  - name: "Operadora Y"
    base_url: "https://operadora-y.com.br"
    products:
      - name: "Plano Família 300Mbps"
        page_url: "https://operadora-y.com.br/internet/familia"
        strategy: "regex"
        pattern: "300\s*Mbps.*?R\$\s*([\d.,]+)"
        our_price: 119.90

  - name: "Operadora Z"
    base_url: "https://operadora-z.com.br"
    products:
      - name: "Combo Internet + TV"
        page_url: "https://operadora-z.com.br/combos"
        strategy: "ai"  # Site muito dinâmico, usar IA
        selector: "Combo Internet 300Mbps + TV com 150 canais"
        our_price: 199.90
```

---

## 13. Como Usar Este Guia no Outro Workspace

1. Copie este arquivo para o novo projeto como `.kiro/steering/architecture-reference.md`
2. Crie uma spec no Kiro com os requirements do Price Watchdog
3. Use o plano de implementação (seção 10) como base para as tasks
4. Adapte os modelos de dados (seção 3) ao seu domínio específico
5. Configure os concorrentes reais (seção 12) no banco ou YAML

O Kiro terá todo o contexto necessário para implementar o sistema de forma incremental e consistente com as boas práticas já validadas no Brand Watchdog.
