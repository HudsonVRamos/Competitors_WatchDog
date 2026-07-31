# Price Watchdog 🐕‍🦺

Sistema automatizado de monitoramento de preços de concorrentes da SKY+ e DGO no mercado brasileiro de TV e streaming.

## O que faz

- Acessa periodicamente os sites dos concorrentes usando Chromium headless
- Captura screenshots full-page como evidência visual
- Usa **Claude Sonnet 4.6 (Amazon Bedrock)** para extrair TODOS os planos e preços visíveis em cada página
- Persiste histórico de preços no Aurora PostgreSQL
- Gera alertas quando variações significativas são detectadas
- Envia relatório Excel consolidado por email via SES

## Concorrentes Monitorados

| Concorrente | URL | Status |
|-------------|-----|--------|
| HBO Max Brasil | https://www.hbomax.com/br/pt | ✅ Funcionando |
| Claro TV+ | https://www.claro.com.br/claro-tv-mais/box | ✅ Funcionando |
| Vivo TV | https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/tv | ⚠️ Requer IP brasileiro |

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                    ECS Cluster (Fargate)                      │
│  ┌──────────────────┐          ┌──────────────────────────┐ │
│  │   Coordinator    │          │     Worker (Chromium)     │ │
│  │  - APScheduler   │          │  - Playwright headless    │ │
│  │  - SQS Publisher │──SQS──▶ │  - Claude Sonnet 4.6      │ │
│  │  - Consolidator  │          │  - Scroll + Screenshot    │ │
│  └──────────────────┘          └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
         │                                │
         ▼                                ▼
┌─────────────────┐              ┌─────────────────┐
│ Aurora PostgreSQL│              │   S3 (Screenshots) │
│  - PriceRecords │              │  - Evidências visuais│
│  - Competitors  │              │  - Lifecycle 30 dias │
│  - PriceCycles  │              └─────────────────────┘
└─────────────────┘
```

## Como funciona o Scraping

1. **Abre Chromium headless** com viewport 1920x720, locale pt-BR, timezone São Paulo
2. **Navega** até a URL do concorrente (timeout 60s)
3. **Espera network idle** (15s) para JavaScript carregar
4. **Scroll incremental** — rola 720px por vez, espera lazy-loading, até 8000px
5. **Volta ao topo** e espera 10s para renderização final
6. **Captura full_page screenshot** (PNG, timeout 60s)
7. **Resize** se > 8000px ou > 5MB (converte para JPEG q75)
8. **Envia ao Claude Sonnet 4.6** com prompt: "Liste TODOS os planos e preços visíveis"
9. Claude retorna JSON: `{"plans": [{"name": "...", "price": "R$ XX,XX"}, ...]}`
10. **Persiste** PriceRecord para cada plano + upload do screenshot no S3

## Infraestrutura AWS

| Recurso | Identificador |
|---------|---------------|
| ECS Cluster | `brand-watchdog-cluster` (compartilhado) |
| ECR | `price-watchdog` |
| SQS Queue | `price-watchdog-tasks` |
| SQS DLQ | `price-watchdog-dlq` |
| S3 Bucket | `price-watchdog-screenshots-761018874615` |
| Aurora PostgreSQL | `brand-watchdog-cluster` (banco `brand_watchdog`) |
| CloudWatch Logs | `/ecs/price-watchdog` |
| CodeBuild | `price-watchdog-build` |
| Bedrock Model | `us.anthropic.claude-sonnet-4-6` |
| Região | us-east-1 |

## Estrutura do Projeto

```
src/price_watchdog/
├── coordinator/        # Orquestração de ciclos (12h)
│   ├── coordinator.py  # PriceMonitoringCoordinator
│   └── cycle_consolidator.py
├── worker/             # Processamento de mensagens SQS
│   └── worker.py       # Worker com multi-price extraction
├── scraper/            # Navegação e extração
│   ├── scraper.py      # PriceScraper (Playwright + scroll)
│   ├── extractors.py   # AIExtractor (Claude), CSS, Regex
│   └── price_parser.py # Parser de preços brasileiros
├── queue/              # SQS Publisher/Consumer
├── storage/            # PriceStore (DB) + ScreenshotStore (S3)
├── alerts/             # AlertService + EmailNotifier (SES)
├── reports/            # ExcelReportGenerator (Traffic Light)
├── registry/           # CompetitorManager + seed
├── scheduler/          # APScheduler (12h)
├── models/             # SQLAlchemy entities + dataclasses
├── main_coordinator.py # Entrypoint coordinator
├── main_worker.py      # Entrypoint worker
└── run_cycle_once.py   # Script para ciclo manual
```

## Deploy

### Build de imagens (CodeBuild)

```bash
aws codebuild start-build --project-name price-watchdog-build --region us-east-1
```

O CodeBuild puxa do GitHub (`HudsonVRamos/Competitors_WatchDog`), builda 2 imagens Docker e faz push para ECR:
- `price-watchdog:coordinator-latest`
- `price-watchdog:worker-latest`

### Rodar ciclo manualmente

```bash
aws ecs run-task \
  --cluster brand-watchdog-cluster \
  --task-definition price-watchdog-run-cycle:2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-0b2eed8647415c4ea,subnet-0d4f495de3fdf8e13],securityGroups=[sg-04a0fe5a84802d79a],assignPublicIp=DISABLED}" \
  --region us-east-1
```

### Atualizar estratégias no banco

```bash
aws ecs run-task \
  --cluster brand-watchdog-cluster \
  --task-definition price-watchdog-update-strategies:13 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-0b2eed8647415c4ea,subnet-0d4f495de3fdf8e13],securityGroups=[sg-04a0fe5a84802d79a],assignPublicIp=DISABLED}" \
  --region us-east-1
```

### Redeploy worker

```bash
aws ecs update-service \
  --cluster brand-watchdog-cluster \
  --service price-watchdog-worker \
  --force-new-deployment \
  --region us-east-1
```

## Configuração

Variáveis de ambiente (setadas na task definition ECS):

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `DB_URL` | Connection string PostgreSQL | `postgresql+asyncpg://user:pass@host:5432/db` |
| `SQS_QUEUE_URL` | URL da fila SQS | `https://sqs.us-east-1.amazonaws.com/...` |
| `S3_BUCKET` | Bucket para screenshots | `price-watchdog-screenshots-761018874615` |
| `SES_FROM_EMAIL` | Email remetente | `suporteott6@gmail.com` |
| `SES_REPORT_RECIPIENTS` | Destinatários (vírgula) | `user@company.com` |
| `MONITORING_INTERVAL_HOURS` | Intervalo entre ciclos | `12` |

## Testes

```bash
# Rodar todos os testes
.venv\Scripts\python -m pytest tests/ -v

# Apenas property tests (Hypothesis)
.venv\Scripts\python -m pytest tests/properties/ -v

# Apenas integration tests (moto)
.venv\Scripts\python -m pytest tests/integration/ -v
```

**266 testes** (204 unit + 43 property + 19 integration)

## Issue Conhecida: Vivo TV

O site da Vivo (`vivo.com.br`) usa geolocalização por IP server-side para mostrar preços. Como o worker roda em us-east-1 (Virginia/EUA), o site não reconhece como IP brasileiro e retorna a página sem preços.

**Tentativas que não funcionaram:**
- Locale pt-BR + timezone São Paulo no Playwright
- Geolocation API (-23.55, -46.63)
- Header X-Forwarded-For com IP brasileiro
- Cookies/localStorage de localização
- Inserção automática de CEP

**Soluções possíveis:**
1. Mover worker para sa-east-1 (São Paulo)
2. Usar proxy residencial brasileiro
3. Encontrar API interna da Vivo que retorna preços com parâmetro de CEP

## Resultados (último ciclo bem-sucedido)

| Concorrente | Planos Extraídos | Preços |
|-------------|-----------------|--------|
| HBO Max Brasil | Básico com Anúncios / Standard / Platinum | R$ 22,90 / R$ 34,90 / R$ 44,90 |
| Claro TV+ | Claro tv+ Box / Fibra 600M + Box / Premium | R$ 139,90 / R$ 219,90 / R$ 279,90 |
| Vivo TV | ⚠️ Pendente resolução de geolocalização | — |

## Licença

Interno — SKY Brasil / VRIO Engineering
