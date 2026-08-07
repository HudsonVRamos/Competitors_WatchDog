# Problemas Identificados no Scraping de Concorrentes
## Data: 07/08/2026

---

## Problema Principal: Worker roda em IP americano (us-east-1)

O ECS Fargate está na região us-east-1. Mesmo configurando `locale=pt-BR`, `geolocation=São Paulo` e `timezone=America/Sao_Paulo` no Playwright, os CDNs dos sites detectam o IP americano e servem conteúdo localizado para EUA.

---

## Problemas por Concorrente

### 1. Vivo TV
**Problema:** A página carrega mas não navega pelas 3 tabs de ofertas (TV Online, TV por Assinatura, Vivo Fibra + TV). O screenshot mostra conteúdo genérico sem preços de planos.
**Observação na imagem:** Página aparece com banners e categorias mas sem os cards de preço das ofertas.
**Solução necessária:**
- Aumentar tempo de espera após carregar página (site pesado, SPA)
- Clicar explicitamente nas tabs "TV Online", "TV por Assinatura", "Vivo Fibra + TV"
- Capturar screenshot APÓS cada tab carregar (ou todas expandidas)
- Alternativa: usar URLs diretas por tipo de oferta se disponíveis

### 2. Netflix
**Problema:** Site serviu versão em inglês (US) ao invés de português. Mostra "Unlimited movies, TV shows, and more" e "Starting at US$ 6.99". FAQs em inglês ("How much does Netflix cost?", "What is Netflix?"). 
**URL configurada:** `https://www.netflix.com/br/`
**O que apareceu:** Versão americana com preço em USD
**Causa raiz:** CDN da Netflix detecta IP do worker (us-east-1) e redireciona para versão US independente do path `/br/`
**Solução necessária:**
- Usar proxy brasileiro (IP BR)
- OU aceitar limitação e documentar que preço capturado é em USD
- OU usar API pública da Netflix para preços BR (não existe oficialmente)
- A expansão de accordions está funcionando (FAQs visíveis) — se tivesse em PT mostraria preço em BRL

### 3. Paramount+
**Problema:** Site redirecionou para página de gift card americana ("GIVE THE GIFT OF STREAMING", "Available at these retailers: Walmart, Sam's Club, Best Buy, Amazon"). Nenhum plano ou preço brasileiro visível.
**URL configurada:** `https://www.paramountplus.com/br/`
**O que apareceu:** Página de gift card US com retailers americanos
**Causa raiz:** CDN do Paramount+ detecta IP americano e ignora o path `/br/`, redirecionando para versão US. O site possivelmente bloqueia acesso ao conteúdo BR de fora do Brasil.
**Solução necessária:**
- Proxy brasileiro (única solução viável)
- O Paramount+ tem geo-blocking agressivo para conteúdo regional

### 4. Giga+ Fibra
**Problema:** Popup "Onde você está?" apareceu mas a cidade não foi selecionada. A página mostra conteúdo sem preços (área de streamings, destaques do mês, mas sem ofertas de planos/preços).
**Observação na imagem:** Modal com dropdown "Selecione ou digite sua cidade" visível, com botão OK. Conteúdo por trás do popup sem preços.
**Causa raiz:** O seletor do dropdown pode ter formato diferente do esperado (dropdown customizado com classe específica da Giga+).
**Solução necessária:**
- Inspecionar o DOM real do site para encontrar o seletor correto do dropdown
- Pode ser um `<div class="custom-select">` ao invés de `<select>` nativo
- Testar com DevTools qual é o elemento exato

---

## Resumo de Soluções

| Problema | Solução | Complexidade |
|----------|---------|-------------|
| IP americano (Netflix, Paramount+) | Proxy brasileiro ou VPN no ECS | Alta — requer mudança de infra |
| Vivo tabs não navegadas | Melhorar seletores + aumentar wait times | Média |
| Giga+ popup não interagido | Inspecionar DOM e ajustar seletores | Média |
| Globoplay erro interno | Erro do próprio site (intermitente) | Não controlável |

---

## Opções para Resolver IP Americano

### Opção A: Proxy Brasileiro (Recomendada)
- Usar serviço de proxy residencial brasileiro (ex: Bright Data, Oxylabs)
- Configurar no Playwright via `proxy` no browser context
- Custo: ~$15-50/mês dependendo do volume

### Opção B: VPN no Container
- Instalar WireGuard/OpenVPN no Dockerfile
- Conectar a um servidor VPN no Brasil antes do scraping
- Mais complexo de manter, mas custo menor

### Opção C: EC2 em São Paulo (sa-east-1)
- Mover o worker para região sa-east-1
- IP será brasileiro nativo
- Desvantagem: latência maior para Bedrock (que fica em us-east-1)

### Opção D: AWS Global Accelerator / CloudFront
- Não resolve — os sites verificam o IP de origem real, não o edge

---

## Status Atual (o que funciona)

Sites com extração de inteligência funcionando corretamente:
- ✅ Claro TV+ (4 pacotes, 13 keywords)
- ✅ Disney+ (3 pacotes, 15 keywords) 
- ✅ HBO Max Brasil (3 pacotes, preços em BRL)
- ✅ Meli+ (3 pacotes com preços e streamings)
- ✅ Netflix (1 pacote — preço em USD por causa do IP)
- ✅ Sporty Net+ (1 pacote, R$29)
- ✅ Tim Play (3 pacotes com preços)
- ✅ Zapping TV (2 pacotes com preços promo)
