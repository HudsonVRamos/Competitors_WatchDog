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

from price_watchdog.models.dataclasses import ExtractionResult
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

        Scroll a página para encontrar seção de preços, captura
        screenshot do viewport (alta resolução), envia ao Bedrock
        e valida confidence.

        Args:
            page: Página Playwright já navegada.
            product_description: Descrição adicional do produto para o prompt.
            product_name: Nome do produto sendo monitorado.

        Returns:
            ExtractionResult com preço e confidence, ou falha com razão.
        """
        try:
            # Scroll pela página capturando screenshots parciais
            # até encontrar preços com confidence suficiente
            page_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = 1080
            max_scrolls = min(8, page_height // viewport_height + 1)

            best_result: ExtractionResult | None = None
            best_confidence = 0.0

            for i in range(max_scrolls):
                scroll_y = i * viewport_height
                await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await page.wait_for_timeout(500)

                # Capturar screenshot do viewport atual
                screenshot_bytes = await page.screenshot(full_page=False)

                if not screenshot_bytes:
                    continue

                # Chamar Bedrock com este viewport
                try:
                    result = await self._invoke_bedrock_with_retry(
                        screenshot_bytes, product_name, product_description
                    )

                    # Se encontrou preço com confidence suficiente, retorna
                    if result.success and result.confidence and result.confidence >= self.MIN_CONFIDENCE:
                        logger.info(
                            "Preço encontrado no scroll %d para '%s': confidence=%.1f%%",
                            i, product_name, result.confidence,
                        )
                        return result

                    # Guardar melhor resultado
                    if result.confidence and result.confidence > best_confidence:
                        best_confidence = result.confidence
                        best_result = result

                except Exception as e:
                    logger.warning(
                        "Scroll %d falhou para '%s': %s", i, product_name, e
                    )
                    continue

            # Se nenhum scroll deu confidence suficiente, retorna o melhor
            if best_result and best_result.success:
                return best_result

            # Nenhum preço encontrado em nenhum viewport
            logger.warning(
                "AI não encontrou preço em nenhum scroll para '%s' (melhor confidence: %.1f%%)",
                product_name, best_confidence,
            )
            return ExtractionResult(
                success=False,
                confidence=best_confidence,
                failure_reason="low_confidence",
            )

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

    def _resize_image_if_needed(
        self, image_bytes: bytes, max_dimension: int = 4000
    ) -> bytes:
        """Redimensiona imagem se exceder max_dimension pixels.

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
                return image_bytes

            # Calcular fator de escala
            scale = min(max_dimension / width, max_dimension / height)
            new_width = int(width * scale)
            new_height = int(height * scale)

            img = img.resize((new_width, new_height), Image.LANCZOS)

            buffer = BytesIO()
            img.save(buffer, format="PNG")
            logger.info(
                "Imagem redimensionada de %dx%d para %dx%d",
                width, height, new_width, new_height,
            )
            return buffer.getvalue()
        except ImportError:
            logger.warning(
                "Pillow não disponível, enviando imagem sem redimensionar"
            )
            return image_bytes
        except Exception as e:
            logger.warning(
                "Falha ao redimensionar imagem: %s", e
            )
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
            f"Analise esta screenshot de uma página web e identifique o preço "
            f"do produto '{product_name}'."
        )
        if product_description:
            prompt += f" Descrição adicional: {product_description}."
        prompt += (
            "\n\nRetorne APENAS um JSON no formato: "
            '{"price": "valor no formato R$ X.XXX,XX", "confidence": número de 0 a 100}'
            "\n\nSe não encontrar o preço, retorne: "
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

            # Validar confidence >= 80%
            if confidence < self.MIN_CONFIDENCE:
                logger.warning(
                    "Confidence %.1f%% abaixo do mínimo (%.1f%%) para '%s'",
                    confidence,
                    self.MIN_CONFIDENCE,
                    product_name,
                )
                return ExtractionResult(
                    success=False,
                    confidence=confidence,
                    failure_reason="low_confidence",
                )

            # Parsear preço se não for null
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
