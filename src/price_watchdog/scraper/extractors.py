"""Extractors para extração de preços de páginas web.

Implementa três estratégias de extração:
- CSSSelectorExtractor: extrai preço via CSS selector
- RegexExtractor: extrai preço via regex no HTML
- AIExtractor: extrai preço via screenshot + Amazon Bedrock (Claude)

Cada extractor implementa a interface BaseExtractor e retorna um ExtractionResult.
"""

import base64
import json
import logging
import re
from abc import ABC, abstractmethod

import aioboto3
from playwright.async_api import Page
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from price_watchdog.models.dataclasses import (
    ExtractionResult,
    MultiPriceExtractionResult,
)
from price_watchdog.scraper.price_parser import PriceParser

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Interface base para estratégias de extração de preço."""

    @abstractmethod
    async def extract(
        self, page: Page, selector_or_pattern: str, product_name: str
    ) -> ExtractionResult:
        """Extrai preço da página usando a estratégia específica.

        Args:
            page: Página Playwright já navegada.
            selector_or_pattern: Seletor CSS, padrão regex ou descrição do produto
                dependendo da estratégia.
            product_name: Nome do produto sendo monitorado.

        Returns:
            ExtractionResult com o preço extraído ou razão de falha.
        """
        ...


class CSSSelectorExtractor(BaseExtractor):
    """Extrai preço via CSS selector usando Playwright + PriceParser.

    Localiza o elemento na página pelo seletor CSS configurado,
    obtém o texto do elemento e parseia no formato brasileiro.
    """

    async def extract(
        self, page: Page, selector: str, product_name: str
    ) -> ExtractionResult:
        """Extrai preço usando CSS selector.

        Args:
            page: Página Playwright já navegada.
            selector: Seletor CSS para localizar o elemento de preço.
            product_name: Nome do produto sendo monitorado.

        Returns:
            ExtractionResult com sucesso e preço, ou falha com razão.
        """
        try:
            element = await page.query_selector(selector)

            if element is None:
                logger.warning(
                    "CSS selector '%s' não encontrou elemento para produto '%s'",
                    selector,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason=f"Seletor CSS '{selector}' não encontrou nenhum elemento na página",
                )

            text_content = await element.text_content()

            if not text_content or not text_content.strip():
                logger.warning(
                    "Elemento encontrado pelo selector '%s' está vazio para produto '%s'",
                    selector,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason="Elemento encontrado pelo seletor CSS não contém texto",
                )

            price = PriceParser.parse(text_content)

            if price is None:
                logger.warning(
                    "Não foi possível parsear preço do texto '%s' para produto '%s'",
                    text_content,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason=f"Texto '{text_content}' não contém preço válido no formato brasileiro",
                )

            logger.info(
                "Preço extraído via CSS selector para '%s': R$ %.2f",
                product_name,
                price,
            )
            return ExtractionResult(success=True, price=price)

        except Exception as e:
            logger.error(
                "Erro ao extrair preço via CSS selector para '%s': %s",
                product_name,
                str(e),
            )
            return ExtractionResult(
                success=False,
                failure_reason=f"Erro na extração CSS: {str(e)}",
            )


class RegexExtractor(BaseExtractor):
    """Extrai preço via regex aplicado no conteúdo HTML da página.

    Obtém o HTML completo da página, aplica o padrão regex configurado
    e parseia o grupo de captura encontrado usando PriceParser.
    """

    async def extract(
        self, page: Page, pattern: str, product_name: str
    ) -> ExtractionResult:
        """Extrai preço usando regex no HTML.

        Args:
            page: Página Playwright já navegada.
            pattern: Padrão regex com grupo de captura para o preço.
            product_name: Nome do produto sendo monitorado.

        Returns:
            ExtractionResult com sucesso e preço, ou falha com razão.
        """
        try:
            html_content = await page.content()

            if not html_content:
                logger.warning(
                    "Conteúdo da página está vazio para produto '%s'",
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason="Conteúdo HTML da página está vazio",
                )

            match = re.search(pattern, html_content)

            if match is None:
                # Fallback: buscar no texto visível da página
                # (sites SPA podem ter preços renderizados via JS
                # que aparecem no texto mas não no HTML source)
                logger.info(
                    "Regex não encontrou no HTML, tentando texto visível para '%s'",
                    product_name,
                )
                try:
                    visible_text = await page.inner_text("body")
                    match = re.search(pattern, visible_text)
                except Exception:
                    pass

            if match is None:
                logger.warning(
                    "Regex '%s' não encontrou correspondência para produto '%s'",
                    pattern,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason=f"Padrão regex '{pattern}' não encontrou correspondência no HTML",
                )

            # Usar o primeiro grupo de captura, ou o match completo
            price_text = match.group(1) if match.lastindex else match.group(0)

            price = PriceParser.parse(price_text)

            if price is None:
                logger.warning(
                    "Não foi possível parsear preço do match '%s' para produto '%s'",
                    price_text,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    failure_reason=f"Texto '{price_text}' capturado pelo regex não contém preço válido",
                )

            logger.info(
                "Preço extraído via regex para '%s': R$ %.2f",
                product_name,
                price,
            )
            return ExtractionResult(success=True, price=price)

        except re.error as e:
            logger.error(
                "Padrão regex inválido '%s' para produto '%s': %s",
                pattern,
                product_name,
                str(e),
            )
            return ExtractionResult(
                success=False,
                failure_reason=f"Padrão regex inválido: {str(e)}",
            )
        except Exception as e:
            logger.error(
                "Erro ao extrair preço via regex para '%s': %s",
                product_name,
                str(e),
            )
            return ExtractionResult(
                success=False,
                failure_reason=f"Erro na extração regex: {str(e)}",
            )


class AIExtractor(BaseExtractor):
    """Extrai preço via screenshot + Amazon Bedrock (Claude Sonnet).

    Captura um screenshot da página, envia ao Bedrock com prompt
    solicitando identificação do preço do produto, e valida que
    a confidence retornada é >= 80%.

    Implementa retry com tenacity (3 tentativas, backoff exponencial)
    para falhas de rede ou timeout do Bedrock.
    """

    # Modelo Claude Sonnet 4.6 no Bedrock (inference profile)
    MODEL_ID = "us.anthropic.claude-sonnet-4-6"
    MIN_CONFIDENCE = 30.0

    def __init__(self, region_name: str = "us-east-1") -> None:
        """Inicializa o AIExtractor.

        Args:
            region_name: Região AWS para o Bedrock.
        """
        self._region_name = region_name

    async def extract(
        self, page: Page, product_description: str, product_name: str
    ) -> ExtractionResult:
        """Extrai preço usando screenshot + Bedrock AI.

        O PriceScraper já fez scroll e capturou full-page screenshot.
        Aqui capturamos um screenshot do viewport atual (que mostra
        a página toda renderizada) e enviamos ao Bedrock.

        Args:
            page: Página Playwright já navegada e scrollada.
            product_description: Descrição adicional do produto para o prompt.
            product_name: Nome do produto sendo monitorado.

        Returns:
            ExtractionResult com preço e confidence, ou falha com razão.
        """
        try:
            # Capturar screenshot full-page (scraper já fez scroll)
            screenshot_bytes = await page.screenshot(full_page=True)

            if not screenshot_bytes:
                return ExtractionResult(
                    success=False,
                    failure_reason="Falha ao capturar screenshot da página",
                )

            # Resize para Bedrock (max 8000px, max 4.5MB)
            screenshot_bytes = self._resize_image_if_needed(screenshot_bytes)

            # Chamar Bedrock com retry
            result = await self._invoke_bedrock_with_retry(
                screenshot_bytes, product_name, product_description
            )

            return result

        except Exception as e:
            logger.error(
                "Erro ao extrair preço via AI para '%s': %s",
                product_name,
                str(e),
            )
            return ExtractionResult(
                success=False,
                failure_reason=f"Erro na extração AI: {str(e)}",
            )

    async def extract_all(
        self, page: Page, competitor_name: str
    ) -> MultiPriceExtractionResult:
        """Extrai TODOS os planos e preços visíveis na página.

        Captura screenshot full-page e texto da página, e pede ao
        Claude para listar todos os planos/preços encontrados.
        O texto da página é incluído como contexto adicional para
        casos onde os preços não são visíveis no screenshot (ex:
        preços carregados dinamicamente, texto pequeno, etc.).

        Args:
            page: Página Playwright já navegada e scrollada.
            competitor_name: Nome do concorrente (para contexto).

        Returns:
            MultiPriceExtractionResult com lista de planos encontrados.
        """
        try:
            # Capturar screenshot full-page
            screenshot_bytes = await page.screenshot(full_page=True)

            if not screenshot_bytes:
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason="Falha ao capturar screenshot da página",
                )

            # Resize para Bedrock (max 8000px, max 4.5MB)
            screenshot_bytes = self._resize_image_if_needed(
                screenshot_bytes
            )

            # Capturar texto da página como contexto adicional
            try:
                page_text = await page.inner_text("body")
                # Truncar a 8000 chars para não exceder token limit
                if len(page_text) > 8000:
                    page_text = page_text[:8000]
            except Exception:
                page_text = ""

            # Chamar Bedrock com prompt multi-plano + texto
            result = await self._invoke_bedrock_all_with_retry(
                screenshot_bytes, competitor_name, page_text
            )
            result.screenshot_bytes = screenshot_bytes

            return result

        except Exception as e:
            logger.error(
                "Erro ao extrair todos os preços via AI para '%s': %s",
                competitor_name,
                str(e),
            )
            return MultiPriceExtractionResult(
                success=False,
                failure_reason=f"Erro na extração AI multi: {str(e)}",
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    async def _invoke_bedrock_all_with_retry(
        self,
        screenshot_bytes: bytes,
        competitor_name: str,
        page_text: str = "",
    ) -> MultiPriceExtractionResult:
        """Invoca Bedrock para extração multi-plano com retry.

        Args:
            screenshot_bytes: Bytes do screenshot capturado.
            competitor_name: Nome do concorrente.
            page_text: Texto extraído da página (contexto adicional).

        Returns:
            MultiPriceExtractionResult com planos encontrados.
        """
        try:
            response = await self._call_bedrock_all(
                screenshot_bytes, competitor_name, page_text
            )
            return response
        except Exception as e:
            logger.warning(
                "Tentativa de chamada ao Bedrock (all) falhou "
                "para '%s': %s",
                competitor_name,
                str(e),
            )
            raise

    async def _call_bedrock_all(
        self,
        screenshot_bytes: bytes,
        competitor_name: str,
        page_text: str = "",
    ) -> MultiPriceExtractionResult:
        """Chama Bedrock pedindo TODOS os planos/preços da página.

        Args:
            screenshot_bytes: Bytes do screenshot.
            competitor_name: Nome do concorrente.
            page_text: Texto extraído da página (contexto adicional).

        Returns:
            MultiPriceExtractionResult parseado da resposta.
        """
        image_base64 = base64.b64encode(
            screenshot_bytes
        ).decode("utf-8")

        prompt = (
            "Analise esta screenshot de uma página web de um "
            "provedor de TV/streaming brasileiro. "
            "Liste TODOS os planos e seus preços mensais "
            "visíveis na página. "
            "Se houver parcelamento (ex: 12x R$34,90/mês), "
            "retorne o valor da parcela mensal. "
            "\n\nRetorne APENAS um JSON no formato: "
            '{"plans": [{"name": "Nome do Plano", '
            '"price": "R$ XX,XX"}, ...]}'
            "\n\nSe não encontrar nenhum plano/preço, retorne: "
            '{"plans": []}'
        )

        # Incluir texto da página como contexto adicional
        if page_text:
            prompt += (
                "\n\n--- TEXTO EXTRAÍDO DA PÁGINA (contexto "
                "adicional caso os preços não sejam visíveis no "
                "screenshot) ---\n"
                f"{page_text}"
            )

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
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
            "bedrock-runtime", region_name=self._region_name
        ) as bedrock_client:
            response = await bedrock_client.invoke_model(
                modelId=self.MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            response_body = await response["body"].read()
            response_json = json.loads(response_body)

        return self._parse_bedrock_all_response(
            response_json, competitor_name
        )

    def _parse_bedrock_all_response(
        self, response_json: dict, competitor_name: str
    ) -> MultiPriceExtractionResult:
        """Parseia resposta do Bedrock para extração multi-plano.

        Args:
            response_json: JSON de resposta do Bedrock.
            competitor_name: Nome do concorrente.

        Returns:
            MultiPriceExtractionResult com planos parseados.
        """
        try:
            content = response_json.get("content", [])
            if not content:
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason="Resposta do Bedrock sem conteúdo",
                )

            text_response = ""
            for block in content:
                if block.get("type") == "text":
                    text_response = block.get("text", "")
                    break

            if not text_response:
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason="Resposta do Bedrock sem texto",
                )

            # Extrair JSON da resposta
            json_match = re.search(
                r"\{[^{}]*\"plans\"\s*:\s*\[.*?\]\s*\}",
                text_response,
                re.DOTALL,
            )
            if not json_match:
                json_match = re.search(
                    r"\{.*\}", text_response, re.DOTALL
                )

            if not json_match:
                return MultiPriceExtractionResult(
                    success=False,
                    failure_reason=(
                        "Resposta do Bedrock não contém JSON válido"
                    ),
                )

            result_data = json.loads(json_match.group())
            raw_plans = result_data.get("plans", [])

            if not raw_plans:
                return MultiPriceExtractionResult(
                    success=True,
                    plans=[],
                    failure_reason=(
                        "AI não encontrou planos/preços na página"
                    ),
                )

            # Parsear preços de cada plano
            parsed_plans: list[dict] = []
            for plan in raw_plans:
                plan_name = plan.get("name", "").strip()
                price_text = plan.get("price", "")

                if not plan_name or not price_text:
                    continue

                price = PriceParser.parse(str(price_text))
                if price is not None:
                    parsed_plans.append(
                        {"name": plan_name, "price": price}
                    )
                else:
                    logger.warning(
                        "Não foi possível parsear preço '%s' "
                        "do plano '%s' (%s)",
                        price_text,
                        plan_name,
                        competitor_name,
                    )

            logger.info(
                "Extração multi-plano para '%s': %d planos "
                "encontrados",
                competitor_name,
                len(parsed_plans),
            )

            return MultiPriceExtractionResult(
                success=len(parsed_plans) > 0,
                plans=parsed_plans,
                failure_reason=(
                    None
                    if parsed_plans
                    else "Nenhum preço pôde ser parseado"
                ),
            )

        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as e:
            logger.error(
                "Erro ao parsear resposta multi do Bedrock "
                "para '%s': %s",
                competitor_name,
                str(e),
            )
            return MultiPriceExtractionResult(
                success=False,
                failure_reason=(
                    f"Erro ao parsear resposta AI: {str(e)}"
                ),
            )

    def _resize_image_if_needed(
        self, image_bytes: bytes, max_dimension: int = 8000
    ) -> bytes:
        """Redimensiona imagem se exceder limites do Bedrock.

        Args:
            image_bytes: Bytes da imagem PNG.
            max_dimension: Dimensão máxima permitida.

        Returns:
            Bytes da imagem (redimensionada ou original).
        """
        try:
            from io import BytesIO
            from PIL import Image

            img = Image.open(BytesIO(image_bytes))
            width, height = img.size

            if width <= max_dimension and height <= max_dimension:
                # Checar tamanho do arquivo (Bedrock max = 5MB)
                if len(image_bytes) <= 5_000_000:
                    return image_bytes
                # Dimensões OK mas arquivo muito grande → converter para JPEG
                buffer = BytesIO()
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(buffer, format="JPEG", quality=75)
                result = buffer.getvalue()
                logger.info("Convertido para JPEG (size): %d bytes", len(result))
                return result

            # Redimensionar se necessário
            if width > max_dimension or height > max_dimension:
                scale = min(max_dimension / width, max_dimension / height)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img = img.resize((new_width, new_height), Image.LANCZOS)
                logger.info(
                    "Imagem redimensionada de %dx%d para %dx%d",
                    width, height, new_width, new_height,
                )

            # Salvar como PNG
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            result = buffer.getvalue()

            # Se > 5MB, converter para JPEG
            if len(result) > 5_000_000:
                buffer = BytesIO()
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(buffer, format="JPEG", quality=80)
                result = buffer.getvalue()
                logger.info("Convertido para JPEG: %d bytes", len(result))

            return result
        except ImportError:
            logger.warning("Pillow não disponível")
            return image_bytes
        except Exception as e:
            logger.warning("Falha ao redimensionar: %s", e)
            return image_bytes

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    async def _invoke_bedrock_with_retry(
        self,
        screenshot_bytes: bytes,
        product_name: str,
        product_description: str,
    ) -> ExtractionResult:
        """Invoca o Bedrock com retry (3x, backoff exponencial).

        Args:
            screenshot_bytes: Bytes do screenshot capturado.
            product_name: Nome do produto.
            product_description: Descrição adicional do produto.

        Returns:
            ExtractionResult com o resultado da análise AI.

        Raises:
            Exception: Se a chamada ao Bedrock falhar após todas as tentativas.
        """
        try:
            response = await self._call_bedrock(
                screenshot_bytes, product_name, product_description
            )
            return response
        except Exception as e:
            logger.warning(
                "Tentativa de chamada ao Bedrock falhou para '%s': %s",
                product_name,
                str(e),
            )
            raise

    async def _call_bedrock(
        self,
        screenshot_bytes: bytes,
        product_name: str,
        product_description: str,
    ) -> ExtractionResult:
        """Realiza chamada ao Amazon Bedrock com a imagem.

        Args:
            screenshot_bytes: Bytes do screenshot.
            product_name: Nome do produto.
            product_description: Descrição adicional.

        Returns:
            ExtractionResult parseado da resposta do Bedrock.
        """
        image_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")

        prompt = (
            f"Analise esta screenshot de uma página web brasileira e identifique o preço "
            f"do produto '{product_name}'."
        )
        if product_description:
            prompt += f" Contexto: {product_description}."
        prompt += (
            "\n\nIMPORTANTE: O preço está em Reais brasileiros (R$). "
            "Procure por valores no formato R$ XX,XX ou R$XX,XX/mês. "
            "Se houver parcelamento como '12x R$34,90/mês', retorne o valor da parcela (34,90)."
            "\n\nRetorne APENAS um JSON no formato: "
            '{"price": "valor no formato R$ X.XXX,XX", "confidence": número de 0 a 100}'
            "\n\nSe não encontrar o preço do produto específico, retorne: "
            '{"price": null, "confidence": 0}'
        )

        # Corpo da requisição para Claude via Bedrock (Messages API)
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
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
            "bedrock-runtime", region_name=self._region_name
        ) as bedrock_client:
            response = await bedrock_client.invoke_model(
                modelId=self.MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body),
            )

            response_body = await response["body"].read()
            response_json = json.loads(response_body)

        # Parsear resposta do Claude
        return self._parse_bedrock_response(response_json, product_name)

    def _parse_bedrock_response(
        self, response_json: dict, product_name: str
    ) -> ExtractionResult:
        """Parseia a resposta do Bedrock e valida confidence.

        Args:
            response_json: JSON de resposta do Bedrock.
            product_name: Nome do produto.

        Returns:
            ExtractionResult com preço validado ou falha.
        """
        try:
            # Extrair texto da resposta (Messages API format)
            content = response_json.get("content", [])
            if not content:
                return ExtractionResult(
                    success=False,
                    failure_reason="Resposta do Bedrock sem conteúdo",
                )

            text_response = ""
            for block in content:
                if block.get("type") == "text":
                    text_response = block.get("text", "")
                    break

            if not text_response:
                return ExtractionResult(
                    success=False,
                    failure_reason="Resposta do Bedrock sem texto",
                )

            # Extrair JSON da resposta (pode estar entre ```json ... ```)
            json_match = re.search(
                r"\{[^}]*\"price\"[^}]*\"confidence\"[^}]*\}",
                text_response,
                re.DOTALL,
            )
            if not json_match:
                # Tentar parse direto
                json_match = re.search(r"\{.*\}", text_response, re.DOTALL)

            if not json_match:
                return ExtractionResult(
                    success=False,
                    failure_reason="Resposta do Bedrock não contém JSON válido",
                )

            result_data = json.loads(json_match.group())
            price_text = result_data.get("price")
            confidence = float(result_data.get("confidence", 0))

            # Validar: se retornou preço, aceitar independente da confidence
            # (o Claude é conservador com confidence em páginas longas)
            if price_text is None:
                return ExtractionResult(
                    success=False,
                    confidence=confidence,
                    failure_reason="AI não identificou preço na página",
                )

            price = PriceParser.parse(str(price_text))

            if price is None:
                return ExtractionResult(
                    success=False,
                    confidence=confidence,
                    failure_reason=f"Preço '{price_text}' retornado pela AI não pôde ser parseado",
                )

            logger.info(
                "Preço extraído via AI para '%s': R$ %.2f (confidence: %.1f%%)",
                product_name,
                price,
                confidence,
            )
            return ExtractionResult(
                success=True, price=price, confidence=confidence
            )

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                "Erro ao parsear resposta do Bedrock para '%s': %s",
                product_name,
                str(e),
            )
            return ExtractionResult(
                success=False,
                failure_reason=f"Erro ao parsear resposta AI: {str(e)}",
            )
