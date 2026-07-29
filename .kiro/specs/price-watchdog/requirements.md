# Requirements Document

## Introduction

O **Price Watchdog** é um sistema automatizado e containerizado que monitora periodicamente os preços de produtos e serviços em sites de concorrentes da SKY+ e DGO, compara com os preços próprios, gera relatórios comparativos e dispara alertas quando variações significativas são detectadas. O sistema opera em arquitetura de workers distribuídos (ECS Fargate), utiliza múltiplas estratégias de extração de preços (CSS selectors, regex e IA via Bedrock como fallback), e persiste histórico para análise de tendências.

## Glossary

- **Coordinator**: Serviço orquestrador que inicia ciclos de monitoramento, publica tarefas na fila SQS e consolida resultados ao final do ciclo
- **Worker**: Serviço containerizado (ECS Fargate) que consome mensagens da fila, acessa sites de concorrentes via navegador headless e extrai preços
- **PriceCycle**: Unidade lógica que agrupa todas as extrações de preço de uma execução programada do sistema
- **ProductConfig**: Configuração de um produto ou serviço específico a ser monitorado em um concorrente, incluindo URL, estratégia de extração e preço de referência
- **PriceRecord**: Registro individual contendo o preço extraído de um concorrente, o preço de referência próprio e os cálculos de diferença
- **PriceAlert**: Notificação gerada quando a variação de preço de um concorrente excede os thresholds configurados
- **Extraction_Strategy**: Método utilizado para extrair o preço de uma página web (css_selector, regex ou ai)
- **Competitor**: Empresa concorrente cujos preços de produtos e serviços são monitorados pelo sistema
- **DLQ**: Dead Letter Queue — fila que recebe mensagens que falharam após o número máximo de tentativas de processamento
- **Screenshot_Evidence**: Captura de tela da página do concorrente no momento da extração, armazenada no S3 como prova visual
- **Brazilian_Price_Format**: Formato monetário brasileiro (R$ X.XXX,XX) onde ponto separa milhares e vírgula separa decimais
- **Traffic_Light_Report**: Relatório Excel comparativo com formatação condicional em cores (verde, amarelo, vermelho) indicando competitividade
- **HBO_Max_Brasil**: Plataforma de streaming da Warner Bros. Discovery no Brasil (https://www.hbomax.com/br/pt), concorrente direta da DGO no segmento de streaming
- **Claro_TV_Plus**: Serviço de TV por assinatura e streaming da Claro (https://www.clarotvmais.com.br/home-landing), concorrente da SKY+ em pacotes de TV e combos
- **Vivo_TV**: Serviço de TV por assinatura da Vivo para residências (https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/tv), concorrente da SKY+ no segmento de TV paga residencial
- **Primary_Competitors**: Os três concorrentes iniciais configurados no sistema — HBO Max Brasil, Claro TV+ e Vivo TV — que representam os principais rivais da SKY+ e DGO no mercado brasileiro

## Requirements

### Requirement 1: Agendamento e Orquestração de Ciclos

**User Story:** Como analista de pricing, eu quero que o sistema execute ciclos de monitoramento automaticamente em intervalos configuráveis, para que os preços dos concorrentes sejam acompanhados sem intervenção manual.

#### Acceptance Criteria

1. WHEN o intervalo configurado (padrão 12 horas) é atingido, THE Coordinator SHALL iniciar um novo PriceCycle com status "running" e registrar o timestamp de início no banco de dados
2. WHEN um PriceCycle é iniciado, THE Coordinator SHALL buscar todos os ProductConfig com status ativo e publicar uma mensagem SQS para cada um, em batches de 10 mensagens
3. WHILE um PriceCycle está em execução, THE Coordinator SHALL verificar a cada 30 segundos se todos os PriceRecords do ciclo foram processados (sucesso ou falha)
4. WHEN todos os PriceRecords de um PriceCycle foram processados, THE Coordinator SHALL atualizar o status do ciclo para "completed", registrar o timestamp de término e os contadores de sucesso e falha
5. IF o Coordinator falhar durante a publicação das mensagens, THEN THE Coordinator SHALL registrar o erro, marcar o ciclo como "failed" e continuar operando para o próximo ciclo agendado

### Requirement 2: Distribuição de Tarefas via Fila

**User Story:** Como engenheiro de infraestrutura, eu quero que as tarefas de extração sejam distribuídas via fila SQS, para que os workers processem em paralelo de forma desacoplada e resiliente.

#### Acceptance Criteria

1. WHEN o Coordinator publica uma mensagem na fila, THE SQS_Publisher SHALL incluir no corpo da mensagem: product_config_id, competitor_id, competitor_name, product_name, page_url, extraction_strategy, selector_or_pattern, our_price e cycle_id
2. THE SQS_Queue SHALL ter visibility timeout de 120 segundos configurado para evitar reprocessamento durante a extração
3. WHEN uma mensagem falha 3 vezes consecutivas, THE SQS_Queue SHALL mover a mensagem para a DLQ
4. WHILE um Worker está processando uma mensagem, THE Worker SHALL renovar o visibility timeout a cada 30 segundos até a conclusão do processamento
5. IF a DLQ receber uma mensagem, THEN THE System SHALL gerar um alarme no CloudWatch

### Requirement 3: Extração de Preços via CSS Selector

**User Story:** Como analista de pricing, eu quero que o sistema extraia preços usando CSS selectors, para que a extração seja rápida e precisa em sites com estrutura HTML conhecida.

#### Acceptance Criteria

1. WHEN a extraction_strategy de um ProductConfig é "css_selector", THE PriceScraper SHALL navegar até a page_url utilizando Playwright com Chromium headless e aplicar o seletor CSS configurado
2. WHEN o elemento identificado pelo CSS selector contém texto com preço, THE CSS_Selector_Extractor SHALL parsear o texto no Brazilian_Price_Format e retornar o valor numérico como float
3. IF o CSS selector não encontrar nenhum elemento na página, THEN THE CSS_Selector_Extractor SHALL retornar status "not_found" com a razão da falha
4. IF o timeout de 30 segundos para carregamento da página for excedido, THEN THE PriceScraper SHALL abortar a navegação, registrar erro de timeout e retornar status "failed"

### Requirement 4: Extração de Preços via Regex

**User Story:** Como analista de pricing, eu quero que o sistema suporte extração via expressão regular, para que preços em estruturas HTML conhecidas mas sem seletores CSS confiáveis possam ser extraídos.

#### Acceptance Criteria

1. WHEN a extraction_strategy de um ProductConfig é "regex", THE Regex_Extractor SHALL obter o conteúdo HTML completo da página e aplicar o padrão regex configurado
2. WHEN o padrão regex encontrar uma correspondência, THE Regex_Extractor SHALL extrair o grupo de captura contendo o preço e parseá-lo no Brazilian_Price_Format
3. IF o padrão regex não encontrar correspondência no HTML, THEN THE Regex_Extractor SHALL retornar status "not_found" com a razão da falha

### Requirement 5: Extração de Preços via IA (Bedrock)

**User Story:** Como analista de pricing, eu quero que o sistema utilize IA como estratégia de fallback para sites complexos ou dinâmicos, para que nenhum concorrente fique sem monitoramento por limitação técnica.

#### Acceptance Criteria

1. WHEN a extraction_strategy de um ProductConfig é "ai", THE AI_Extractor SHALL capturar um screenshot da página e enviar ao Amazon Bedrock com um prompt solicitando a identificação do preço do produto especificado
2. WHEN o Bedrock retornar um preço com confidence igual ou superior a 80%, THE AI_Extractor SHALL aceitar o valor e retorná-lo como preço extraído
3. IF o Bedrock retornar confidence inferior a 80%, THEN THE AI_Extractor SHALL rejeitar a extração e retornar status "failed" com a razão "low_confidence"
4. IF a chamada ao Bedrock falhar por erro de rede ou timeout, THEN THE AI_Extractor SHALL realizar até 3 tentativas com backoff exponencial antes de retornar status "failed"

### Requirement 6: Parsing de Preço em Formato Brasileiro

**User Story:** Como desenvolvedor, eu quero que o sistema converta corretamente preços no formato monetário brasileiro para valores numéricos, para que as comparações sejam precisas independente da formatação de origem.

#### Acceptance Criteria

1. WHEN um texto de preço no formato "R$ X.XXX,XX" é recebido, THE Price_Parser SHALL remover o símbolo monetário, tratar o ponto como separador de milhares e a vírgula como separador decimal, retornando um float (exemplo: "R$ 1.299,90" resulta em 1299.90)
2. WHEN um texto de preço contém caracteres não numéricos além de ponto, vírgula e símbolo monetário, THE Price_Parser SHALL remover esses caracteres antes do parsing
3. IF o texto não puder ser convertido em valor numérico após limpeza, THEN THE Price_Parser SHALL retornar None e registrar o texto original no log para análise

### Requirement 7: Captura de Screenshot como Evidência

**User Story:** Como analista de pricing, eu quero que o sistema capture screenshots das páginas dos concorrentes durante a extração, para que haja evidência visual do preço no momento da coleta.

#### Acceptance Criteria

1. WHEN um Worker acessa a página de um concorrente para extração, THE PriceScraper SHALL capturar um screenshot full-page (limitado a 5000px de altura) antes de executar a extração
2. WHEN o screenshot é capturado, THE Screenshot_Store SHALL fazer upload para o bucket S3 configurado com uma chave que inclua o cycle_id, competitor_id e timestamp
3. THE S3_Bucket SHALL aplicar uma política de lifecycle que delete screenshots com mais de 30 dias automaticamente
4. IF o upload do screenshot para o S3 falhar, THEN THE Worker SHALL registrar o erro no log mas continuar o processamento da extração de preço normalmente

### Requirement 8: Comparação de Preços

**User Story:** Como analista de pricing, eu quero que o sistema compare automaticamente os preços extraídos com nossos preços de referência, para que eu possa identificar rapidamente onde estamos mais caros ou mais baratos.

#### Acceptance Criteria

1. WHEN um preço é extraído com sucesso, THE Price_Comparator SHALL calcular a diferença absoluta (preço_extraído - nosso_preço) e a diferença percentual ((preço_extraído - nosso_preço) / nosso_preço * 100)
2. WHEN a comparação é calculada, THE Price_Store SHALL persistir um PriceRecord contendo: preço extraído, preço de referência, diferença absoluta, diferença percentual, status de extração, cycle_id, screenshot_s3_key e timestamp
3. THE Price_Store SHALL reter PriceRecords por pelo menos 365 dias para permitir análise de tendências e sazonalidade

### Requirement 9: Alertas de Variação de Preço

**User Story:** Como gerente de pricing, eu quero ser alertado quando concorrentes alterarem preços significativamente, para que eu possa tomar decisões rápidas de reposicionamento.

#### Acceptance Criteria

1. WHEN o preço extraído de um concorrente apresentar queda superior ao threshold configurado (padrão 5%), THE Alert_Service SHALL criar um PriceAlert do tipo "price_drop"
2. WHEN o preço extraído de um concorrente apresentar aumento superior ao threshold configurado (padrão 10%), THE Alert_Service SHALL criar um PriceAlert do tipo "price_increase"
3. WHEN um PriceAlert é criado, THE Email_Notifier SHALL enviar um email via Amazon SES para todos os destinatários configurados, contendo: nome do concorrente, produto, preço anterior, preço atual e percentual de variação
4. IF o envio do email via SES falhar, THEN THE Email_Notifier SHALL realizar até 3 tentativas com backoff exponencial e registrar a falha no log

### Requirement 10: Relatório Comparativo em Excel

**User Story:** Como analista de pricing, eu quero receber um relatório Excel comparativo ao final de cada ciclo, para que eu possa analisar a posição competitiva de todos os produtos de forma consolidada.

#### Acceptance Criteria

1. WHEN um PriceCycle é concluído com status "completed", THE Report_Generator SHALL gerar um arquivo Excel contendo as colunas: Concorrente, Produto, Nosso Preço, Preço Deles, Diferença (R$), Diferença (%) e Status
2. THE Report_Generator SHALL aplicar formatação Traffic_Light_Report: verde quando nosso preço é menor que o concorrente, amarelo quando a diferença é inferior a 5%, e vermelho quando nosso preço é maior que 5% acima do concorrente
3. WHEN o relatório Excel é gerado, THE Report_Generator SHALL enviar o arquivo como anexo no email de consolidação do ciclo para os destinatários configurados

### Requirement 11: Persistência e Gestão de Dados

**User Story:** Como engenheiro de dados, eu quero que o sistema persista dados estruturados em Aurora PostgreSQL, para que haja confiabilidade, consultas eficientes e suporte a análises históricas.

#### Acceptance Criteria

1. THE Database SHALL armazenar as entidades: Competitor, ProductConfig, PriceRecord, PriceCycle e PriceAlert com relacionamentos referenciados por chave estrangeira
2. THE Database SHALL suportar operações assíncronas utilizando SQLAlchemy async com asyncpg como driver
3. WHEN um Competitor ou ProductConfig é desativado, THE System SHALL parar de incluí-lo em novos ciclos de monitoramento sem remover dados históricos

### Requirement 12: Resiliência e Degradação Graciosa

**User Story:** Como engenheiro de confiabilidade, eu quero que falhas em extrações individuais não comprometam o ciclo completo, para que o sistema continue operando mesmo quando um concorrente está instável.

#### Acceptance Criteria

1. IF um Worker falhar ao processar uma mensagem (timeout, erro de rede, site indisponível), THEN THE Worker SHALL registrar o PriceRecord com status "failed" e a razão da falha, e prosseguir para a próxima mensagem
2. IF a extração de preço falhar mas o screenshot foi capturado, THEN THE Worker SHALL persistir o screenshot no S3 para análise manual posterior
3. THE System SHALL completar o PriceCycle mesmo que parte das extrações tenha falhado, registrando os contadores de sucesso e falha no ciclo
4. WHEN uma mensagem é movida para a DLQ após 3 falhas, THE System SHALL registrar um log de nível ERROR com os detalhes da mensagem e as razões de cada falha

### Requirement 13: Infraestrutura Containerizada

**User Story:** Como engenheiro DevOps, eu quero que o sistema seja deployado em containers ECS Fargate, para que haja escalabilidade, isolamento e gerenciamento simplificado sem administrar servidores.

#### Acceptance Criteria

1. THE System SHALL ser deployado em um ECS Cluster Fargate com um serviço Coordinator (1 task) e um serviço Worker (1 a 5 tasks com auto scaling baseado em mensagens na fila)
2. THE Worker_Container SHALL incluir o Chromium instalado via Playwright para realizar navegação headless
3. THE Infrastructure SHALL ser definida como código utilizando CloudFormation, incluindo: ECS Cluster, SQS Queue com DLQ, Aurora PostgreSQL Serverless v2, bucket S3 e configuração SES
4. THE CloudWatch SHALL monitorar logs de todos os serviços e gerar alarmes quando mensagens chegarem à DLQ

### Requirement 14: Gestão de Concorrentes e Produtos

**User Story:** Como analista de pricing, eu quero poder cadastrar e configurar concorrentes e seus produtos para monitoramento, para que o sistema saiba quais sites acessar e quais preços extrair.

#### Acceptance Criteria

1. THE System SHALL permitir o cadastro de Competitors contendo: nome, URL base e status ativo/inativo
2. THE System SHALL permitir o cadastro de ProductConfigs associados a um Competitor, contendo: nome do produto, URL da página, estratégia de extração, seletor ou padrão, preço de referência próprio e moeda
3. WHEN um ProductConfig é cadastrado, THE System SHALL validar que a URL é acessível e que o seletor ou padrão está em formato válido para a estratégia escolhida
4. THE System SHALL permitir a atualização do preço de referência próprio (our_price) a qualquer momento sem afetar registros históricos
5. THE System SHALL ser inicialmente configurado com três concorrentes primários da SKY+ e DGO no mercado brasileiro de streaming/TV: HBO Max Brasil (https://www.hbomax.com/br/pt), Claro TV+ (https://www.clarotvmais.com.br/home-landing) e Vivo TV (https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/tv)

### Requirement 15: Configuração Inicial de Concorrentes e Estratégias de Extração

**User Story:** Como analista de pricing, eu quero que o sistema já venha pré-configurado com os três concorrentes primários e suas respectivas estratégias de extração, para que o monitoramento comece a funcionar imediatamente após o deploy sem necessidade de configuração manual.

#### Acceptance Criteria

1. WHEN o sistema é inicializado pela primeira vez, THE System SHALL criar automaticamente os registros de Competitor para HBO Max Brasil (URL base: https://www.hbomax.com/br/pt), Claro TV+ (URL base: https://www.clarotvmais.com.br/home-landing) e Vivo TV (URL base: https://vivo.com.br/para-voce/produtos-e-servicos/para-casa/tv) com status ativo
2. THE System SHALL armazenar para cada Competitor uma configuração de extraction_strategy específica, reconhecendo que cada site possui estrutura de página própria que requer seletores CSS, padrões regex ou análise via IA distintos
3. WHEN o HBO Max Brasil é monitorado, THE PriceScraper SHALL utilizar a estratégia de extração configurada para a estrutura de página do HBO Max, que apresenta planos de assinatura de streaming com preços em formato de card
4. WHEN o Claro TV+ é monitorado, THE PriceScraper SHALL utilizar a estratégia de extração configurada para a estrutura de página do Claro TV+, que apresenta pacotes de TV por assinatura e combos com internet
5. WHEN o Vivo TV é monitorado, THE PriceScraper SHALL utilizar a estratégia de extração configurada para a estrutura de página da Vivo, que apresenta produtos de TV para residências com diferentes faixas de preço
6. IF a estrutura de página de um concorrente mudar e a extração falhar em 3 ciclos consecutivos, THEN THE System SHALL gerar um alerta específico de "extraction_strategy_outdated" para que a equipe técnica atualize os seletores ou padrões
7. THE System SHALL manter um registro de metadados por Competitor indicando a data da última atualização da estratégia de extração e a taxa de sucesso dos últimos 30 dias
