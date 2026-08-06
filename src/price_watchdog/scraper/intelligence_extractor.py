"""Extrator de inteligência competitiva via Amazon Bedrock.

Componente dedicado para extração de dados estruturados de composição
de pacotes e comunicação comercial dos concorrentes, utilizando
Claude Sonnet via Bedrock com screenshots full-page.

Separado do AIExtractor de preços para evitar acoplamento.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time

import aioboto3
from botocore.exceptions import ClientError

from price_watchdog.models.intelligence_dataclasses import (  # noqa: F401
    IntelligenceExtractionResult,
    PackageCompositionData,
    CommercialCommunicationData,
)

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Erro de validação de schema na resposta do Bedrock.

    Levantada quando a resposta JSON do Bedrock é válida como JSON
    mas não atende ao schema esperado (campos obrigatórios ausentes,
    tipos incorretos, etc.).
    """

    pass


class AIIntelligenceExtractor:
    """Extrator de inteligência competitiva via Bedrock.

    Responsável por extrair composição de pacotes e comunicação
    comercial de screenshots de páginas de concorrentes usando
    Claude Sonnet no Amazon Bedrock.

    Attributes:
        MODEL_ID: Identificador do modelo no Bedrock
        MAX_RETRIES_RETRYABLE: Máximo de retries para erros retentáveis
        MAX_RETRIES_SCHEMA: Máximo de retries para erros de schema
        TIMEOUT_SECONDS: Timeout global em segundos
        BACKOFF_BASE: Base para backoff exponencial em segundos
    """

    MODEL_ID = "us.anthropic.claude-sonnet-4-6"
    MAX_RETRIES_RETRYABLE = 3
    MAX_RETRIES_SCHEMA = 2
    TIMEOUT_SECONDS = 120
    BACKOFF_BASE = 2  # 2s, 4s, 8s

    # Mapa de nomes oficiais de serviços de streaming conhecidos
    # para normalização de capitalização
    KNOWN_STREAMINGS: dict[str, str] = {
        "netflix": "Netflix",
        "disney+": "Disney+",
        "paramount+": "Paramount+",
        "amazon prime video": "Amazon Prime Video",
        "globoplay": "Globoplay",
        "star+": "Star+",
        "hbo max": "HBO Max",
        "apple tv+": "Apple TV+",
    }

    # Sufixos de tier/plano a serem removidos (case-insensitive)
    TIER_SUFFIXES: list[str] = [
        "basic",
        "premium",
        "standard",
        "plus",
    ]

    def __init__(self, region_name: str = "us-east-1") -> None:
        """Inicializa o AIIntelligenceExtractor.

        Args:
            region_name: Região AWS para o Bedrock.
        """
        self._region_name = region_name

    def _normalize_streaming_name(self, name: str) -> str:
        """Normaliza o nome de um serviço de streaming.

        Remove sufixos de tier/plano (Basic, Premium, Standard, Plus)
        e aplica a capitalização oficial para serviços conhecidos.
        Para serviços desconhecidos, aplica capitalização title case.

        Args:
            name: Nome bruto do streaming (ex: "netflix premium",
                "DISNEY+ basic", "hbo max standard").

        Returns:
            Nome normalizado (ex: "Netflix", "Disney+", "HBO Max").

        Examples:
            >>> extractor._normalize_streaming_name("netflix premium")
            'Netflix'
            >>> extractor._normalize_streaming_name("DISNEY+ basic")
            'Disney+'
            >>> extractor._normalize_streaming_name("hbo max standard")
            'HBO Max'
            >>> extractor._normalize_streaming_name("Mubi")
            'Mubi'
        """
        if not name or not name.strip():
            return name

        # Trabalhar com versão limpa
        cleaned = name.strip()

        # Remover sufixos de tier (case-insensitive)
        # Usa regex para remover sufixo no final da string
        for suffix in self.TIER_SUFFIXES:
            pattern = re.compile(
                r"\s+" + re.escape(suffix) + r"\s*$",
                re.IGNORECASE,
            )
            cleaned = pattern.sub("", cleaned)

        # Strip novamente após remoção de sufixo
        cleaned = cleaned.strip()

        if not cleaned:
            return name.strip()

        # Verificar se é um serviço conhecido (case-insensitive)
        cleaned_lower = cleaned.lower()
        if cleaned_lower in self.KNOWN_STREAMINGS:
            return self.KNOWN_STREAMINGS[cleaned_lower]

        # Para serviços desconhecidos: capitalizar primeira letra
        # de cada palavra (title case)
        return cleaned.title()

    def _normalize_streamings(
        self, streamings: list[str]
    ) -> list[str]:
        """Normaliza lista de nomes de streaming.

        Limita a no máximo 3 itens e normaliza cada nome usando
        _normalize_streaming_name.

        Args:
            streamings: Lista de nomes brutos de streamings.

        Returns:
            Lista normalizada com no máximo 3 itens.

        Examples:
            >>> extractor._normalize_streamings(
            ...     ["netflix premium", "disney+ basic", "paramount+",
            ...      "hbo max"])
            ['Netflix', 'Disney+', 'Paramount+']
            >>> extractor._normalize_streamings([])
            []
        """
        if not streamings:
            return []

        # Limitar a 3 itens
        limited = streamings[:3]

        # Normalizar cada nome
        return [
            self._normalize_streaming_name(name)
            for name in limited
        ]

    def _validate_composition(
        self, comp: dict
    ) -> tuple[bool, str]:
        """Valida os dados de composição de um pacote.

        Verifica que os campos numéricos estão dentro dos limites
        aceitáveis. Campos com valor None/null são aceitos sem erro.

        Args:
            comp: Dicionário com os dados de composição do pacote.

        Returns:
            Tupla (is_valid, reason) onde is_valid é True se válido,
            reason é string vazia quando válido ou mensagem do erro.
        """
        # Validar default_price
        default_price = comp.get("default_price")
        if default_price is not None:
            if not isinstance(default_price, (int, float)):
                return (
                    False,
                    "default_price deve ser numérico, recebido: "
                    f"{type(default_price).__name__}",
                )
            if default_price < 0.01 or default_price > 99999.99:
                return (
                    False,
                    "default_price deve estar entre 0.01 e "
                    f"99999.99, recebido: {default_price}",
                )

        # Validar promotional_price
        promotional_price = comp.get("promotional_price")
        if promotional_price is not None:
            if not isinstance(promotional_price, (int, float)):
                return (
                    False,
                    "promotional_price deve ser numérico, "
                    f"recebido: {type(promotional_price).__name__}",
                )
            if (
                promotional_price < 0.01
                or promotional_price > 99999.99
            ):
                return (
                    False,
                    "promotional_price deve estar entre 0.01 e "
                    f"99999.99, recebido: {promotional_price}",
                )
            # promotional_price <= default_price
            if (
                default_price is not None
                and promotional_price > default_price
            ):
                return (
                    False,
                    f"promotional_price ({promotional_price}) não "
                    f"pode ser maior que default_price "
                    f"({default_price})",
                )

        # Validar promotional_period_months
        promotional_period = comp.get("promotional_period_months")
        if promotional_period is not None:
            if not isinstance(promotional_period, int):
                return (
                    False,
                    "promotional_period_months deve ser inteiro, "
                    f"recebido: {type(promotional_period).__name__}",
                )
            if promotional_period < 1 or promotional_period > 36:
                return (
                    False,
                    "promotional_period_months deve estar entre "
                    f"1 e 36, recebido: {promotional_period}",
                )

        # Validar campos inteiros não-negativos
        non_negative_fields = [
            "linear_channels",
            "simultaneous_screens",
            "fiber_speed_mbps",
            "mobile_speed_mbps",
        ]

        for field_name in non_negative_fields:
            value = comp.get(field_name)
            if value is not None:
                if not isinstance(value, int):
                    return (
                        False,
                        f"{field_name} deve ser inteiro, recebido: "
                        f"{type(value).__name__}",
                    )
                if value < 0:
                    return (
                        False,
                        f"{field_name} deve ser >= 0, "
                        f"recebido: {value}",
                    )

        return (True, "")

    def _validate_keywords(
        self, keywords: list[str]
    ) -> tuple[list[str], str]:
        """Valida lista de palavras-chave comerciais.

        Aceita listas de 3 a 15 keywords com max 50 chars cada.
        Retorna "não identificado" se houver menos de 3 keywords.

        Args:
            keywords: Lista de palavras-chave extraídas pelo Bedrock.

        Returns:
            Tupla (validated_keywords, status) onde status é
            "identified" ou "não identificado".
        """
        if not keywords or not isinstance(keywords, list):
            return ([], "não identificado")

        # Truncar cada keyword a 50 chars e filtrar vazias
        validated: list[str] = []
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            truncated = kw[:50]
            if truncated.strip():
                validated.append(truncated)

        # Limitar a 15 keywords
        validated = validated[:15]

        # Mínimo de 3 keywords para considerar válido
        if len(validated) < 3:
            return ([], "não identificado")

        return (validated, "identified")

    def _validate_banner(self, description: str) -> str:
        """Valida e trunca descrição do banner a 500 caracteres.

        Args:
            description: Descrição textual do banner.

        Returns:
            Descrição truncada a no máximo 500 caracteres.
        """
        if not isinstance(description, str):
            return ""
        return description[:500]

    def _validate_positioning(self, summary: str) -> str:
        """Valida e trunca resumo de posicionamento a 1000 chars.

        Args:
            summary: Resumo do posicionamento comercial.

        Returns:
            Resumo truncado a no máximo 1000 caracteres.
        """
        if not isinstance(summary, str):
            return ""
        return summary[:1000]

    def _build_prompt(self) -> str:
        """Constrói o prompt estruturado para extração de inteligência.

        O prompt solicita ao modelo Claude Sonnet via Bedrock que
        analise o screenshot de uma página de concorrente e retorne
        dados estruturados em JSON contendo composição de pacotes
        e comunicação comercial.

        O prompt inclui:
        - Instrução para resposta exclusivamente em JSON válido
        - Schema esperado com descrição de cada campo
        - 1 exemplo few-shot completo com valores ilustrativos
        - Regras de preenchimento (null para campos não identificados)
        - Identificação do modelo utilizado

        Returns:
            String com o prompt completo formatado.
        """
        return f"""Você é o modelo {self.MODEL_ID} operando via Amazon Bedrock.

Sua tarefa é analisar o screenshot da página de um concorrente de telecomunicações/TV por assinatura e extrair informações estruturadas sobre composição de pacotes e comunicação comercial.

IMPORTANTE: Responda EXCLUSIVAMENTE com um JSON válido. Não inclua texto adicional, markdown, blocos de código, explicações ou qualquer wrapper antes ou depois do JSON. A resposta deve começar com {{ e terminar com }}.

## Schema JSON Esperado

A resposta deve conter exatamente dois objetos de topo:

{{
  "package_composition": [
    {{
      "plan_name": "string — Nome do plano/pacote conforme exibido na página (obrigatório)",
      "default_price": "float | null — Preço regular mensal em reais (R$), sem desconto promocional. Valor entre 0.01 e 99999.99",
      "promotional_price": "float | null — Preço promocional mensal em reais (R$), deve ser menor ou igual ao default_price. Valor entre 0.01 e 99999.99",
      "promotional_period_months": "int | null — Duração em meses do período promocional, entre 1 e 36",
      "linear_channels": "int | null — Número de canais de TV linear incluídos no pacote, inteiro >= 0",
      "simultaneous_screens": "int | null — Número máximo de telas/dispositivos simultâneos permitidos, inteiro >= 0",
      "has_fiber": "bool | null — Se o pacote inclui internet via fibra óptica (true/false)",
      "fiber_speed_mbps": "int | null — Velocidade da fibra em Mbps, inteiro >= 0",
      "has_mobile_internet": "bool | null — Se o pacote inclui internet móvel 4G/5G (true/false)",
      "mobile_speed_mbps": "int | null — Velocidade da internet móvel em Mbps, inteiro >= 0",
      "bundled_streamings": "list[string] — Lista com até 3 nomes de serviços de streaming incluídos no pacote (ex: Netflix, Disney+, Paramount+). Usar apenas o nome-base sem sufixos de plano (Basic, Premium, Standard). Lista vazia se nenhum streaming incluído"
    }}
  ],
  "commercial_communication": {{
    "commercial_keywords": "list[string] — Lista de 3 a 15 palavras-chave/termos comerciais presentes nos textos visíveis da página (ofertas, benefícios, diferenciais, calls-to-action). Cada keyword com no máximo 50 caracteres",
    "home_banner_description": "string | null — Descrição textual do banner principal (acima da dobra): tema visual, oferta destacada e call-to-action. Até 500 caracteres",
    "commercial_positioning_summary": "string | null — Resumo do posicionamento comercial geral da página em até 300 caracteres"
  }}
}}

## Regras de Preenchimento

1. Use null para qualquer campo cujo valor não possa ser identificado na página
2. Liste até 20 pacotes em "package_composition" (os mais relevantes primeiro)
3. Para "commercial_keywords": extraia de 3 a 15 palavras-chave. Se não identificar ao menos 3, retorne lista vazia []
4. Para "bundled_streamings": liste até 3 serviços de streaming por pacote, na ordem de aparição na página (de cima para baixo, esquerda para direita). Use apenas o nome-base do serviço (ex: "Netflix" e não "Netflix Premium")
5. O campo "plan_name" é obrigatório — se não identificar o nome do plano, use uma descrição identificadora baseada no conteúdo visível
6. Preços devem ser numéricos (sem símbolo R$), usando ponto como separador decimal (ex: 99.90)
7. Se a página não contiver nenhum pacote identificável, retorne "package_composition" como lista vazia []

## Exemplo de Resposta (few-shot)

{{
  "package_composition": [
    {{
      "plan_name": "Plano Família HD",
      "default_price": 159.90,
      "promotional_price": 119.90,
      "promotional_period_months": 12,
      "linear_channels": 180,
      "simultaneous_screens": 4,
      "has_fiber": true,
      "fiber_speed_mbps": 600,
      "has_mobile_internet": true,
      "mobile_speed_mbps": 50,
      "bundled_streamings": ["Netflix", "Disney+", "Globoplay"]
    }},
    {{
      "plan_name": "Plano Básico",
      "default_price": 89.90,
      "promotional_price": null,
      "promotional_period_months": null,
      "linear_channels": 80,
      "simultaneous_screens": 2,
      "has_fiber": true,
      "fiber_speed_mbps": 300,
      "has_mobile_internet": false,
      "mobile_speed_mbps": null,
      "bundled_streamings": ["Globoplay"]
    }}
  ],
  "commercial_communication": {{
    "commercial_keywords": ["melhor custo-benefício", "fibra ultra rápida", "streaming grátis", "sem fidelidade", "instalação grátis", "4K incluso", "Wi-Fi 6"],
    "home_banner_description": "Banner principal com fundo azul degradê exibindo família assistindo TV. Oferta de Black Friday: Plano Família HD por R$119,90/mês nos primeiros 12 meses. CTA: Assine agora com instalação grátis.",
    "commercial_positioning_summary": "Posicionamento focado em custo-benefício familiar com internet de alta velocidade e streamings incluídos. Comunicação agressiva de preço promocional."
  }}
}}

Agora analise o screenshot fornecido e extraia as informações seguindo rigorosamente o schema e as regras acima."""

    def _validate_schema(
        self, data: dict
    ) -> tuple[bool, str]:
        """Valida schema da resposta JSON do Bedrock.

        Verifica a presença das chaves de topo obrigatórias
        ("package_composition" e "commercial_communication") e
        que seus tipos estão corretos (list e dict, respectivamente).

        Args:
            data: Dicionário parseado da resposta JSON do Bedrock.

        Returns:
            Tupla (is_valid, reason) onde is_valid é True se o schema
            é válido, e reason é string vazia quando válido ou mensagem
            descritiva do erro encontrado.

        Examples:
            >>> extractor._validate_schema({
            ...     "package_composition": [],
            ...     "commercial_communication": {}
            ... })
            (True, '')
            >>> extractor._validate_schema({"package_composition": []})
            (False, 'Campo obrigatório ausente: commercial_communication')
        """
        # Verificar presença de "package_composition"
        if "package_composition" not in data:
            return (
                False,
                "Campo obrigatório ausente: package_composition",
            )

        # Verificar tipo de "package_composition"
        if not isinstance(data["package_composition"], list):
            return (
                False,
                "package_composition deve ser uma lista, "
                f"recebido: {type(data['package_composition']).__name__}",
            )

        # Verificar presença de "commercial_communication"
        if "commercial_communication" not in data:
            return (
                False,
                "Campo obrigatório ausente: commercial_communication",
            )

        # Verificar tipo de "commercial_communication"
        if not isinstance(data["commercial_communication"], dict):
            return (
                False,
                "commercial_communication deve ser um dicionário, "
                f"recebido: {type(data['commercial_communication']).__name__}",
            )

        return (True, "")

    def _parse_packages(
        self, packages_data: list[dict]
    ) -> list[PackageCompositionData]:
        """Parseia lista de pacotes da resposta JSON do Bedrock.

        Limita a no máximo 20 pacotes. Para cada pacote, valida usando
        _validate_composition e, se válido, cria um PackageCompositionData.
        Pacotes inválidos ou sem plan_name são ignorados com log de warning.

        Args:
            packages_data: Lista de dicionários com dados de pacotes
                retornados pelo Bedrock.

        Returns:
            Lista de PackageCompositionData com no máximo 20 itens.

        Examples:
            >>> extractor._parse_packages([{
            ...     "plan_name": "Plano X",
            ...     "default_price": 99.90,
            ...     "bundled_streamings": ["Netflix"]
            ... }])
            [PackageCompositionData(plan_name='Plano X', ...)]
        """
        if not packages_data:
            return []

        # Limitar a 20 pacotes
        limited = packages_data[:20]
        result: list[PackageCompositionData] = []

        for i, pkg in enumerate(limited):
            if not isinstance(pkg, dict):
                logger.warning(
                    "Pacote %d ignorado: não é um dicionário", i
                )
                continue

            # Verificar plan_name obrigatório
            plan_name = pkg.get("plan_name")
            if not plan_name or not isinstance(plan_name, str):
                logger.warning(
                    "Pacote %d ignorado: plan_name ausente ou inválido",
                    i,
                )
                continue

            plan_name = plan_name.strip()
            if not plan_name:
                logger.warning(
                    "Pacote %d ignorado: plan_name vazio", i
                )
                continue

            # Validar composição
            is_valid, reason = self._validate_composition(pkg)
            if not is_valid:
                logger.warning(
                    "Pacote %d ('%s') ignorado: %s",
                    i,
                    plan_name,
                    reason,
                )
                continue

            # Normalizar streamings
            raw_streamings = pkg.get("bundled_streamings", [])
            if not isinstance(raw_streamings, list):
                raw_streamings = []
            normalized_streamings = self._normalize_streamings(
                raw_streamings
            )

            # Criar PackageCompositionData
            composition = PackageCompositionData(
                plan_name=plan_name,
                default_price=pkg.get("default_price"),
                promotional_price=pkg.get("promotional_price"),
                promotional_period_months=pkg.get(
                    "promotional_period_months"
                ),
                linear_channels=pkg.get("linear_channels"),
                simultaneous_screens=pkg.get("simultaneous_screens"),
                has_fiber=pkg.get("has_fiber"),
                fiber_speed_mbps=pkg.get("fiber_speed_mbps"),
                has_mobile_internet=pkg.get("has_mobile_internet"),
                mobile_speed_mbps=pkg.get("mobile_speed_mbps"),
                bundled_streamings=normalized_streamings,
            )
            result.append(composition)

        return result

    def _parse_communication(
        self, comm_data: dict
    ) -> CommercialCommunicationData:
        """Parseia dados de comunicação comercial da resposta JSON.

        Extrai e valida keywords, banner description e positioning
        summary usando os métodos de validação dedicados.

        Args:
            comm_data: Dicionário com dados de comunicação comercial
                retornados pelo Bedrock.

        Returns:
            CommercialCommunicationData com campos validados e status
            apropriados.

        Examples:
            >>> extractor._parse_communication({
            ...     "commercial_keywords": ["oferta", "fibra", "streaming"],
            ...     "home_banner_description": "Banner Black Friday",
            ...     "commercial_positioning_summary": "Foco em preço"
            ... })
            CommercialCommunicationData(...)
        """
        # Extrair e validar keywords
        raw_keywords = comm_data.get("commercial_keywords", [])
        if not isinstance(raw_keywords, list):
            raw_keywords = []
        validated_keywords, keywords_status = (
            self._validate_keywords(raw_keywords)
        )

        # Extrair e validar banner description
        raw_banner = comm_data.get("home_banner_description", "")
        banner_description = self._validate_banner(raw_banner)

        # Determinar banner_status
        if banner_description.strip():
            banner_status = "identified"
        else:
            banner_status = "não identificado"

        # Extrair e validar positioning summary
        raw_positioning = comm_data.get(
            "commercial_positioning_summary", ""
        )
        positioning_summary = self._validate_positioning(
            raw_positioning
        )

        return CommercialCommunicationData(
            commercial_keywords=validated_keywords,
            home_banner_description=banner_description,
            commercial_positioning_summary=positioning_summary,
            keywords_status=keywords_status,
            banner_status=banner_status,
        )

    def _classify_error(self, error: Exception) -> str:
        """Classifica um erro para determinar a estratégia de retry.

        Categoriza erros em três tipos:
        - "retryable": erros transientes que podem ser recuperados
          com retry (5xx, 429, timeout, erros de rede)
        - "non_retryable": erros permanentes que não se resolvem
          com retry (4xx exceto 429, erros fatais)
        - "schema_error": resposta JSON válida mas com campos
          obrigatórios ausentes ou tipos incorretos

        Args:
            error: Exceção capturada durante invocação do Bedrock.

        Returns:
            String com a classificação: "retryable",
            "non_retryable" ou "schema_error".
        """
        # Erros de timeout do asyncio
        if isinstance(error, (asyncio.TimeoutError,)):
            return "retryable"

        # Erros de conexão
        if isinstance(error, (ConnectionError, OSError)):
            return "retryable"

        # ClientError do botocore (HTTP errors do Bedrock)
        if isinstance(error, ClientError):
            response = error.response or {}
            status_code = (
                response
                .get("ResponseMetadata", {})
                .get("HTTPStatusCode", 0)
            )
            # HTTP 429 (throttling) é retentável
            if status_code == 429:
                return "retryable"
            # HTTP 5xx é retentável
            if 500 <= status_code < 600:
                return "retryable"
            # HTTP 4xx (exceto 429) é não-retentável
            if 400 <= status_code < 500:
                return "non_retryable"

        # Erros de validação de schema
        if isinstance(error, SchemaValidationError):
            return "schema_error"

        # Erros de JSON inválido (não parseável)
        if isinstance(error, (json.JSONDecodeError, ValueError)):
            return "non_retryable"

        # Default: considerar retentável para erros desconhecidos
        return "retryable"

    async def _invoke_bedrock(
        self,
        screenshot_bytes: bytes,
        prompt: str,
    ) -> dict:
        """Invoca o Bedrock com screenshot e prompt.

        Envia screenshot como imagem base64 e prompt como texto
        ao Claude Sonnet via Bedrock Messages API. Implementa:
        - Retry para erros retentáveis (5xx, 429, timeout) com
          backoff exponencial: 2s, 4s, 8s (máx 3 tentativas)
        - Retry para erros de schema (até 2 tentativas adicionais
          com feedback do erro no prompt)
        - Timeout global de 120s com abort e cancelamento

        Classificação de erros:
        - Retentável: HTTP 5xx, HTTP 429, timeout, ConnectionError
        - Não-retentável: HTTP 4xx (exceto 429), schema esgotado
        - Schema retry: JSON válido mas campos obrigatórios ausentes

        Args:
            screenshot_bytes: Screenshot em formato PNG/JPEG.
            prompt: Prompt estruturado para extração.

        Returns:
            Dicionário com a resposta JSON parseada do Bedrock.

        Raises:
            asyncio.TimeoutError: Se timeout global de 120s for
                atingido.
            ClientError: Se erro não-retentável do Bedrock após
                esgotamento de retries.
            SchemaValidationError: Se schema retry esgotado.
        """
        image_base64 = base64.b64encode(
            screenshot_bytes
        ).decode("utf-8")

        current_prompt = prompt
        schema_retries = 0
        retryable_retries = 0

        async def _do_invoke() -> dict:
            """Lógica interna de invocação com retry."""
            nonlocal current_prompt, schema_retries
            nonlocal retryable_retries

            while True:
                try:
                    # Chamar Bedrock
                    response_data = (
                        await self._call_bedrock_api(
                            image_base64, current_prompt
                        )
                    )

                    # Extrair texto JSON da resposta
                    parsed = self._extract_json_from_response(
                        response_data
                    )

                    # Validar schema básico
                    is_valid, reason = (
                        self._validate_schema(parsed)
                    )
                    if not is_valid:
                        # Schema inválido — tentar re-prompt
                        schema_retries += 1
                        if (
                            schema_retries
                            > self.MAX_RETRIES_SCHEMA
                        ):
                            raise SchemaValidationError(
                                "Schema inválido após "
                                f"{self.MAX_RETRIES_SCHEMA} "
                                f"retries: {reason}"
                            )
                        logger.warning(
                            "Schema retry %d/%d: %s",
                            schema_retries,
                            self.MAX_RETRIES_SCHEMA,
                            reason,
                        )
                        # Re-prompt com feedback do erro
                        current_prompt = (
                            f"{prompt}\n\n"
                            "ATENÇÃO: Sua resposta anterior "
                            "teve erro de validação: "
                            f"{reason}\n"
                            "Por favor, corrija e retorne "
                            "um JSON válido conforme o "
                            "schema solicitado."
                        )
                        continue

                    return parsed

                except SchemaValidationError:
                    raise

                except Exception as e:
                    error_type = self._classify_error(e)

                    if error_type == "non_retryable":
                        raise

                    if error_type == "retryable":
                        retryable_retries += 1
                        if (
                            retryable_retries
                            > self.MAX_RETRIES_RETRYABLE
                        ):
                            raise
                        # Backoff exponencial: 2s, 4s, 8s
                        delay = (
                            self.BACKOFF_BASE
                            ** retryable_retries
                        )
                        logger.warning(
                            "Retry retentável %d/%d, "
                            "aguardando %ds: %s",
                            retryable_retries,
                            self.MAX_RETRIES_RETRYABLE,
                            delay,
                            str(e),
                        )
                        await asyncio.sleep(delay)
                        continue

                    # schema_error vindo de _classify_error
                    # (não deveria chegar aqui, mas tratar)
                    raise

        try:
            return await asyncio.wait_for(
                _do_invoke(),
                timeout=self.TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timeout global de %ds atingido na invocação "
                "do Bedrock",
                self.TIMEOUT_SECONDS,
            )
            raise asyncio.TimeoutError(
                f"Timeout global de {self.TIMEOUT_SECONDS}s "
                "excedido"
            )

    async def _call_bedrock_api(
        self,
        image_base64: str,
        prompt: str,
    ) -> dict:
        """Realiza chamada HTTP ao Bedrock invoke_model.

        Monta o request body no formato Messages API do Claude
        e invoca o modelo configurado.

        Args:
            image_base64: Imagem codificada em base64.
            prompt: Texto do prompt a enviar.

        Returns:
            Dicionário JSON da resposta do Bedrock.
        """
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        session = aioboto3.Session()
        async with session.client(
            "bedrock-runtime",
            region_name=self._region_name,
        ) as bedrock_client:
            response = await bedrock_client.invoke_model(
                modelId=self.MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            response_body = await response["body"].read()
            return json.loads(response_body)

    def _extract_json_from_response(
        self, response_data: dict
    ) -> dict:
        """Extrai e parseia JSON do conteúdo da resposta Bedrock.

        A resposta do Bedrock Messages API contém um array
        "content" com blocos de texto. Este método extrai o
        primeiro bloco de texto e parseia como JSON.

        Args:
            response_data: Resposta raw do Bedrock.

        Returns:
            Dicionário parseado do JSON contido na resposta.

        Raises:
            ValueError: Se a resposta não contiver texto ou
                JSON válido.
        """
        content = response_data.get("content", [])
        if not content:
            raise ValueError(
                "Resposta do Bedrock sem conteúdo"
            )

        text_response = ""
        for block in content:
            if block.get("type") == "text":
                text_response = block.get("text", "")
                break

        if not text_response:
            raise ValueError(
                "Resposta do Bedrock sem texto"
            )

        # Tentar parsear o texto completo como JSON
        text_stripped = text_response.strip()
        if text_stripped.startswith("{"):
            try:
                return json.loads(text_stripped)
            except json.JSONDecodeError:
                pass

        # Tentar extrair JSON do texto (pode ter wrappers)
        json_match = re.search(
            r"\{.*\}", text_response, re.DOTALL
        )
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        raise ValueError(
            "Resposta do Bedrock não contém JSON válido"
        )

    async def extract(
        self,
        screenshot_bytes: bytes,
        competitor_name: str,
        home_url: str | None = None,
    ) -> IntelligenceExtractionResult:
        """Método principal de extração de inteligência competitiva.

        Orquestra todo o fluxo de extração: construção do prompt,
        invocação do Bedrock, validação de schema, parsing de
        pacotes e comunicação comercial.

        Mede a latência total da operação e trata cenário de
        nenhum pacote encontrado (status "no_packages_found")
        sem marcar como falha.

        Args:
            screenshot_bytes: Screenshot full-page em PNG/JPEG
                da página do concorrente.
            competitor_name: Nome do concorrente (para logging
                e contexto).
            home_url: URL da home do concorrente (opcional,
                para logging).

        Returns:
            IntelligenceExtractionResult com dados extraídos ou
            informações de falha.

        Examples:
            >>> result = await extractor.extract(
            ...     screenshot_bytes=b"...",
            ...     competitor_name="Claro",
            ...     home_url="https://www.claro.com.br"
            ... )
            >>> result.success
            True
            >>> result.status
            'success'
        """
        start_time = time.perf_counter()
        retry_count = 0

        try:
            logger.info(
                "Iniciando extração de inteligência para '%s'"
                " (url=%s)",
                competitor_name,
                home_url or "N/A",
            )

            # 1. Construir prompt estruturado
            prompt = self._build_prompt()

            # 2. Invocar Bedrock com screenshot e prompt
            # _invoke_bedrock implementa retry interno e
            # retorna o dict parseado ou levanta exceção
            response_data = await self._invoke_bedrock(
                screenshot_bytes, prompt
            )

            # 3. Validar schema da resposta
            # (já validado dentro de _invoke_bedrock, mas
            # verificamos novamente por segurança)
            is_valid, reason = self._validate_schema(response_data)
            if not is_valid:
                # Schema inválido após retries de _invoke_bedrock
                latency_ms = (
                    (time.perf_counter() - start_time) * 1000
                )
                logger.warning(
                    "Schema inválido para '%s': %s",
                    competitor_name,
                    reason,
                )
                return IntelligenceExtractionResult(
                    success=False,
                    status="failed",
                    package_compositions=[],
                    commercial_communication=None,
                    failure_reason=(
                        f"Schema inválido: {reason}"
                    ),
                    retry_count=retry_count,
                    latency_ms=latency_ms,
                )

            # 4. Parsear pacotes
            packages = self._parse_packages(
                response_data["package_composition"]
            )

            # 5. Parsear comunicação comercial
            communication = self._parse_communication(
                response_data["commercial_communication"]
            )

            # 6. Determinar status
            # Se a lista de pacotes está vazia E o response
            # retornou package_composition vazia: no_packages_found
            raw_packages = response_data["package_composition"]
            if not packages and (
                not raw_packages or len(raw_packages) == 0
            ):
                status = "no_packages_found"
                logger.info(
                    "Nenhum pacote encontrado para '%s'",
                    competitor_name,
                )
            else:
                status = "success"

            # 7. Calcular latência
            latency_ms = (
                (time.perf_counter() - start_time) * 1000
            )

            logger.info(
                "Extração concluída para '%s': status=%s, "
                "pacotes=%d, latência=%.0fms",
                competitor_name,
                status,
                len(packages),
                latency_ms,
            )

            return IntelligenceExtractionResult(
                success=True,
                status=status,
                package_compositions=packages,
                commercial_communication=communication,
                failure_reason=None,
                retry_count=retry_count,
                latency_ms=latency_ms,
            )

        except Exception as e:
            # Qualquer exceção não tratada: retornar falha
            latency_ms = (
                (time.perf_counter() - start_time) * 1000
            )
            logger.error(
                "Falha na extração de inteligência para '%s': "
                "%s",
                competitor_name,
                str(e),
                exc_info=True,
            )
            return IntelligenceExtractionResult(
                success=False,
                status="failed",
                package_compositions=[],
                commercial_communication=None,
                failure_reason=str(e),
                retry_count=retry_count,
                latency_ms=latency_ms,
            )
