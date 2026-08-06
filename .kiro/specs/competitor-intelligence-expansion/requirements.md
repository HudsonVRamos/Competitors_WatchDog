# Requirements Document

## Introduction

A **Expansão de Inteligência Competitiva** amplia o escopo do Price Watchdog para capturar, além de preços e planos, informações detalhadas sobre **composição de pacotes** (canais lineares, telas simultâneas, fibra, internet móvel, streamings incluídos) e **comunicação comercial** (palavras-chave, banners, posicionamento) dos sites concorrentes listados na aba "LISTA CONCORRENCIA BR". Essas informações são extraídas via IA (Claude Sonnet via Bedrock) a partir de screenshots e conteúdo textual das páginas, e persistidas para análise comparativa pelo time de marketing.

## Glossary

- **Competitor_Intelligence_Record**: Registro completo de inteligência competitiva contendo dados de composição de pacote e comunicação comercial extraídos de um concorrente em um determinado ciclo
- **Package_Composition**: Conjunto de atributos estruturados que descrevem a composição de um pacote de TV/streaming: preço default, preço promocional, duração promocional, número de canais lineares, número de telas simultâneas, presença e velocidade de fibra, presença e velocidade de internet móvel, e streamings incluídos
- **Commercial_Communication**: Conjunto de atributos que descrevem a comunicação comercial de um concorrente: palavras-chave dos textos comerciais na home, descrição do conteúdo visual do banner principal e resumo do posicionamento comercial
- **Default_Price**: Preço regular do pacote sem desconto promocional aplicado
- **Promotional_Price**: Preço com desconto temporário vigente para atração de novos clientes
- **Promotional_Period**: Duração em meses durante a qual o preço promocional é válido antes de retornar ao preço default
- **Linear_Channels**: Canais de TV tradicionais transmitidos em grade de programação linear (não on-demand)
- **Simultaneous_Screens**: Número máximo de dispositivos que podem acessar o serviço ao mesmo tempo em uma mesma assinatura
- **Fiber_Combo**: Indicação de que o pacote inclui serviço de internet via fibra óptica como parte da oferta combinada
- **Mobile_Internet_Combo**: Indicação de que o pacote inclui serviço de internet móvel (4G/5G) como parte da oferta combinada
- **Bundled_Streaming**: Serviço de streaming de terceiros (Netflix, Disney+, Paramount+, etc.) incluído como benefício no pacote do concorrente
- **Home_Banner**: Imagem principal de destaque na página inicial do concorrente, geralmente com oferta comercial ou campanha promocional
- **Commercial_Keywords**: Palavras e termos-chave presentes nos textos comerciais da página inicial que indicam a estratégia de comunicação do concorrente
- **Intelligence_Cycle**: Ciclo de coleta de inteligência competitiva, executado em conjunto com o PriceCycle existente, que adiciona a extração de composição e comunicação ao fluxo já existente de preços
- **Competitor_Site**: Site de concorrente cadastrado na lista "LISTA CONCORRENCIA BR" da planilha de estudo de concorrência
- **AI_Intelligence_Extractor**: Componente especializado que utiliza Claude Sonnet via Bedrock para extrair informações estruturadas de composição e comunicação a partir de screenshots e conteúdo de página

## Requirements

### Requirement 1: Extração de Composição de Pacotes via IA

**User Story:** Como analista de marketing, eu quero que o sistema extraia automaticamente os atributos de composição de cada pacote dos concorrentes, para que eu possa comparar ofertas de forma estruturada sem visitar cada site manualmente.

#### Acceptance Criteria

1. WHEN um Worker processa um Competitor_Site, THE AI_Intelligence_Extractor SHALL enviar o screenshot full-page e o conteúdo textual da página ao Amazon Bedrock com um prompt solicitando a extração dos seguintes atributos para cada pacote identificado: Default_Price, Promotional_Price, Promotional_Period, número de Linear_Channels, número de Simultaneous_Screens, presença de Fiber_Combo, velocidade da fibra em Mbps, presença de Mobile_Internet_Combo, velocidade da internet móvel em Mbps, e até 3 Bundled_Streamings
2. WHEN o Bedrock retornar os dados de composição, THE AI_Intelligence_Extractor SHALL validar que Default_Price é um valor numérico entre 0.01 e 99999.99, que Promotional_Price quando presente é um valor numérico entre 0.01 e 99999.99 e menor ou igual ao Default_Price do mesmo pacote, que Promotional_Period quando presente é um inteiro entre 1 e 36 meses, e que os demais campos numéricos (canais, telas, velocidades) são inteiros não-negativos
3. IF o Bedrock não identificar um atributo específico na página (por exemplo, o concorrente não informa número de canais), THEN THE AI_Intelligence_Extractor SHALL registrar o campo como null sem marcar a extração como falha
4. WHEN múltiplos pacotes são identificados na mesma página, THE AI_Intelligence_Extractor SHALL retornar uma lista com a composição de cada pacote separadamente (até no máximo 20 pacotes por página), associando cada um ao nome do plano correspondente
5. IF o Bedrock não identificar nenhum pacote na página analisada, THEN THE AI_Intelligence_Extractor SHALL registrar a extração com status "no_packages_found" e razão descritiva, sem marcar como falha do sistema

### Requirement 2: Extração de Comunicação Comercial via IA

**User Story:** Como analista de marketing, eu quero que o sistema capture a comunicação comercial das homes dos concorrentes, para que eu possa monitorar posicionamento, campanhas e mensagens-chave da concorrência.

#### Acceptance Criteria

1. WHEN um Worker processa um Competitor_Site, THE AI_Intelligence_Extractor SHALL analisar a página inicial (home) do concorrente e extrair: uma lista de Commercial_Keywords presentes nos textos comerciais, uma descrição textual do conteúdo visual do Home_Banner principal (o primeiro banner de destaque visível na área acima da dobra), e um resumo do posicionamento comercial geral da página com no máximo 300 caracteres
2. WHEN o Bedrock retorna Commercial_Keywords, THE AI_Intelligence_Extractor SHALL retornar uma lista de no mínimo 3 e no máximo 15 palavras-chave, cada uma com no máximo 50 caracteres, que representam a estratégia de comunicação identificada com base em termos presentes nos textos visíveis da página (ofertas, benefícios, diferenciais e calls-to-action)
3. IF o Bedrock retornar menos de 3 Commercial_Keywords, THEN THE AI_Intelligence_Extractor SHALL registrar o campo commercial_keywords como "não identificado" com a razão "conteúdo comercial insuficiente para extração"
4. WHEN o Bedrock descreve o Home_Banner, THE AI_Intelligence_Extractor SHALL retornar uma descrição textual de até 500 caracteres contendo: tema visual, oferta destacada e call-to-action identificado
5. IF a página do concorrente não possuir banner ou comunicação comercial identificável, THEN THE AI_Intelligence_Extractor SHALL registrar o campo como "não identificado" com a razão da ausência em até 200 caracteres

### Requirement 3: Persistência de Dados de Inteligência Competitiva

**User Story:** Como analista de dados, eu quero que as informações de composição e comunicação sejam persistidas de forma estruturada no banco de dados, para que eu possa consultar histórico e gerar análises comparativas ao longo do tempo.

#### Acceptance Criteria

1. WHEN uma extração de inteligência competitiva é concluída com sucesso para um concorrente, THE System SHALL persistir um Competitor_Intelligence_Record no banco Aurora PostgreSQL vinculado ao cycle_id, competitor_id e timestamp da extração, contendo um registro único por combinação de cycle_id e competitor_id
2. THE Database SHALL armazenar os dados de Package_Composition com colunas individuais para cada atributo (Default_Price, Promotional_Price, Promotional_Period, Linear_Channels, Simultaneous_Screens, Fiber_Combo, velocidade da fibra, Mobile_Internet_Combo, velocidade da internet móvel, e Bundled_Streamings), suportando múltiplos pacotes por Competitor_Intelligence_Record com cada pacote identificado pelo nome do plano
3. THE Database SHALL armazenar os dados de Commercial_Communication em campos dedicados: commercial_keywords (array de texto com até 15 elementos), home_banner_description (texto de até 500 caracteres) e commercial_positioning_summary (texto de até 1000 caracteres)
4. THE Database SHALL reter Competitor_Intelligence_Records por pelo menos 365 dias para permitir análise de evolução de ofertas e posicionamento ao longo do tempo
5. WHEN um novo Competitor_Intelligence_Record é persistido, THE System SHALL manter os registros anteriores intactos para preservar o histórico de mudanças, sem atualizar ou remover registros de ciclos anteriores
6. IF a persistência de um Competitor_Intelligence_Record falhar por erro de conexão ou constraint do banco, THEN THE System SHALL realizar até 3 tentativas com backoff exponencial (1s, 2s, 4s) e, caso todas falhem, registrar a falha com status "persistence_failed" e a razão do erro nos logs sem impactar o processamento dos demais concorrentes do ciclo

### Requirement 4: Integração com Ciclo de Monitoramento Existente

**User Story:** Como engenheiro de sistemas, eu quero que a extração de inteligência competitiva seja integrada ao ciclo de monitoramento existente, para que não haja duplicação de acessos aos sites dos concorrentes e o fluxo se mantenha coeso.

#### Acceptance Criteria

1. WHEN um PriceCycle é iniciado pelo Coordinator, THE System SHALL incluir a extração de inteligência competitiva (composição + comunicação) como etapa subsequente à extração de preços no processamento de cada Competitor_Site que possua o flag de inteligência competitiva habilitado, reutilizando o screenshot já capturado na etapa de preços
2. WHEN o Worker já capturou o screenshot full-page para extração de preços, THE Worker SHALL reutilizar o mesmo screenshot para a extração de inteligência competitiva, evitando uma segunda navegação ao site
3. IF a extração de inteligência competitiva falhar para um concorrente, THEN THE Worker SHALL registrar a falha no Competitor_Intelligence_Record com status "failed" e a razão do erro (até 500 caracteres), sem impactar a extração de preços do mesmo ciclo
4. WHEN o PriceCycle é concluído, THE Coordinator SHALL incluir nos metadados do ciclo os contadores: total de extrações de inteligência tentadas, total de extrações com sucesso e total de extrações com falha
5. IF o screenshot full-page não estiver disponível para um Competitor_Site (por exemplo, porque a captura falhou durante a extração de preços), THEN THE Worker SHALL registrar a extração de inteligência como "failed" com razão "screenshot_unavailable" sem tentar uma nova navegação ao site

### Requirement 5: Prompt Estruturado para Extração via Bedrock

**User Story:** Como desenvolvedor, eu quero que o prompt enviado ao Bedrock seja estruturado e específico para cada tipo de dado, para que a IA retorne respostas consistentes e parseáveis em JSON.

#### Acceptance Criteria

1. THE AI_Intelligence_Extractor SHALL enviar ao Bedrock um prompt que solicite a resposta exclusivamente em formato JSON válido (sem texto adicional, markdown ou wrappers), com schema pré-definido contendo dois objetos de topo: "package_composition" e "commercial_communication"
2. WHEN o Bedrock retornar uma resposta, THE AI_Intelligence_Extractor SHALL extrair o conteúdo JSON da resposta e validar contra o schema esperado (presença de campos obrigatórios e tipos corretos conforme definidos nos atributos de Package_Composition e Commercial_Communication) antes de persistir os dados
3. IF o JSON retornado pelo Bedrock não corresponder ao schema esperado (campos obrigatórios ausentes, tipos incorretos, ou resposta não-parseável como JSON), THEN THE AI_Intelligence_Extractor SHALL realizar até 2 tentativas adicionais incluindo no prompt a indicação do erro de validação encontrado, antes de marcar a extração como "failed"
4. THE AI_Intelligence_Extractor SHALL incluir no prompt pelo menos 1 exemplo completo de resposta esperada (few-shot) contendo valores ilustrativos para todos os campos do schema, para guiar o modelo na estruturação correta dos dados
5. THE AI_Intelligence_Extractor SHALL incluir no prompt a instrução explícita do modelo Claude Sonnet via Bedrock utilizado (conforme configurado), o schema JSON esperado com descrição de cada campo e tipo de dado, e as regras de preenchimento (incluindo uso de null para campos não identificados na página)

### Requirement 6: Relatório de Inteligência Competitiva

**User Story:** Como analista de marketing, eu quero receber um relatório consolidado com os dados de composição e comunicação de todos os concorrentes, para que eu possa comparar ofertas e estratégias em um único documento.

#### Acceptance Criteria

1. WHEN um PriceCycle com extração de inteligência competitiva é concluído, THE Report_Generator SHALL gerar uma aba adicional no relatório Excel do ciclo contendo os dados de composição de pacotes de todos os concorrentes que tiveram extração bem-sucedida, com uma linha por pacote identificado
2. THE Report_Generator SHALL organizar os dados de composição em colunas: Concorrente, Nome do Pacote, Preço Default, Preço Promocional, Duração Promo (meses), Canais Lineares, Telas Simultâneas, Fibra (Sim/Não), Velocidade Fibra (Mbps), Internet Móvel (Sim/Não), Velocidade Móvel (Mbps), Streaming 1, Streaming 2, Streaming 3, exibindo células vazias para atributos não identificados (null)
3. THE Report_Generator SHALL incluir uma aba separada de "Comunicação Comercial" com colunas: Concorrente, Palavras-chave (separadas por vírgula), Descrição Banner, Resumo Posicionamento
4. WHEN o relatório é gerado, THE Report_Generator SHALL enviar o arquivo Excel como anexo no email de consolidação do ciclo para os destinatários configurados na lista de alertas do sistema
5. IF nenhum concorrente do ciclo tiver extração de inteligência competitiva bem-sucedida, THEN THE Report_Generator SHALL omitir as abas de inteligência competitiva do relatório e incluir no email de consolidação uma indicação de que a extração de inteligência falhou para todos os concorrentes

### Requirement 7: Detecção de Mudanças em Ofertas

**User Story:** Como gerente de marketing, eu quero ser alertado quando concorrentes alterarem a composição dos seus pacotes ou sua comunicação comercial, para que eu possa reagir rapidamente a movimentos da concorrência.

#### Acceptance Criteria

1. WHEN um novo Competitor_Intelligence_Record com status de sucesso é persistido, THE System SHALL comparar os dados de Package_Composition com o registro anterior bem-sucedido (status diferente de "failed") do mesmo concorrente e identificar mudanças em qualquer atributo
2. IF o Competitor_Intelligence_Record persistido for o primeiro registro bem-sucedido para um determinado concorrente (sem registro anterior disponível), THEN THE System SHALL registrar os dados como baseline sem gerar alerta de mudança
3. WHEN uma mudança é detectada na composição de pacotes (novo streaming adicionado, mudança de preço promocional, alteração de canais, telas ou velocidades), THE Alert_Service SHALL criar um alerta do tipo "package_composition_change" contendo: nome do atributo alterado, valor anterior, valor atual e nome do pacote afetado
4. WHEN uma mudança significativa é detectada na Commercial_Communication (mais de 50% das palavras-chave mudaram ou a descrição do Home_Banner possui menos de 60% de similaridade textual com a descrição anterior), THE Alert_Service SHALL criar um alerta do tipo "communication_change"
5. WHEN um alerta de inteligência competitiva é criado, THE Email_Notifier SHALL enviar um email em até 5 minutos para os destinatários configurados contendo: nome do concorrente, tipo de mudança, valor anterior, valor atual e data/hora da detecção

### Requirement 8: Configuração de Sites a Monitorar

**User Story:** Como analista de marketing, eu quero poder cadastrar e gerenciar a lista de sites concorrentes a monitorar para inteligência competitiva, para que novos concorrentes possam ser adicionados conforme a planilha "LISTA CONCORRENCIA BR" é atualizada.

#### Acceptance Criteria

1. THE System SHALL permitir a habilitação de inteligência competitiva em um registro de Competitor existente através de um flag booleano (intelligence_enabled), cujo valor padrão é false para novos Competitors e para Competitors existentes que ainda não foram configurados
2. WHEN um Competitor tem o flag intelligence_enabled alterado para true, THE System SHALL incluí-lo nos ciclos de extração de composição e comunicação a partir do próximo PriceCycle iniciado após a alteração
3. WHEN um Competitor tem o flag intelligence_enabled alterado para false, THE System SHALL parar de extrair dados de composição e comunicação a partir do próximo PriceCycle iniciado após a alteração, sem remover dados históricos existentes
4. THE System SHALL permitir a configuração de uma URL específica da home (intelligence_home_url) para extração de comunicação comercial em cada Competitor, que pode ser diferente da URL base de preços do mesmo concorrente e deve ter no máximo 2048 caracteres
5. WHEN uma intelligence_home_url é configurada ou atualizada para um Competitor, THE System SHALL validar que a URL possui formato válido (esquema http ou https com domínio) antes de aceitar a configuração
6. IF a intelligence_home_url não for configurada para um Competitor com intelligence_enabled igual a true, THEN THE System SHALL utilizar a URL base (url_base) do Competitor como fallback para extração de comunicação comercial

### Requirement 9: Extração de Streamings Incluídos no Pacote

**User Story:** Como analista de marketing, eu quero identificar especificamente quais serviços de streaming estão incluídos nos pacotes dos concorrentes, para que eu possa avaliar a competitividade das ofertas combinadas.

#### Acceptance Criteria

1. WHEN o AI_Intelligence_Extractor analisa a composição de um pacote, THE AI_Intelligence_Extractor SHALL identificar e listar por nome cada Bundled_Streaming incluído no pacote (exemplos: Netflix, Disney+, Paramount+, Amazon Prime Video, Globoplay, Star+)
2. THE AI_Intelligence_Extractor SHALL registrar até 3 Bundled_Streamings por pacote, ordenados pela ordem de aparição na página do concorrente (de cima para baixo, da esquerda para a direita), descartando os demais caso mais de 3 sejam identificados
3. IF o pacote não incluir nenhum Bundled_Streaming, THEN THE AI_Intelligence_Extractor SHALL registrar o campo como lista vazia
4. WHEN um Bundled_Streaming é identificado, THE AI_Intelligence_Extractor SHALL registrar apenas o nome-base do serviço removendo sufixos de plano ou tier (por exemplo, "Netflix Basic", "Netflix Premium" e "netflix" devem ser registrados como "Netflix"), utilizando capitalização oficial do serviço (primeira letra maiúscula e grafia reconhecida pelo mercado)
5. IF o AI_Intelligence_Extractor identificar um serviço de streaming incluído no pacote cujo nome não corresponda a nenhum serviço de streaming reconhecido no mercado brasileiro, THEN THE AI_Intelligence_Extractor SHALL registrar o nome tal como apresentado na página, aplicando apenas a normalização de capitalização, e incluir o serviço na contagem de até 3 Bundled_Streamings

### Requirement 10: Resiliência na Extração de Inteligência

**User Story:** Como engenheiro de confiabilidade, eu quero que falhas na extração de inteligência competitiva não impactem o funcionamento do sistema de preços existente, para que a nova funcionalidade opere com degradação graciosa.

#### Acceptance Criteria

1. IF a extração de inteligência competitiva falhar para um concorrente (erro no Bedrock, timeout, resposta inválida), THEN THE Worker SHALL continuar o processamento normal de extração de preços sem interrupção, preservando todos os dados de preço já coletados naquele ciclo para o concorrente
2. IF a chamada ao Bedrock para inteligência competitiva falhar por erro retentável (erro de rede, timeout, HTTP 5xx ou throttling 429), THEN THE AI_Intelligence_Extractor SHALL realizar até 3 tentativas com backoff exponencial (2s, 4s, 8s) antes de registrar falha definitiva
3. IF a chamada ao Bedrock para inteligência competitiva falhar por erro não-retentável (resposta inválida, erro de validação de schema, HTTP 4xx exceto 429), THEN THE AI_Intelligence_Extractor SHALL registrar falha definitiva imediatamente sem realizar tentativas adicionais
4. THE System SHALL registrar as seguintes métricas da extração de inteligência separadamente das métricas de extração de preços: contagem de extrações com sucesso, contagem de extrações com falha, latência média de extração por concorrente e contagem de retries realizados, por ciclo
5. WHEN o tempo total de processamento de inteligência competitiva de um concorrente (incluindo todas as tentativas e tempos de backoff) exceder 120 segundos, THE AI_Intelligence_Extractor SHALL abortar a extração, cancelar tentativas pendentes e registrar timeout como razão de falha
