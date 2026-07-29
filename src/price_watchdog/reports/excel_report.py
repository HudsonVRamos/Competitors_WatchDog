"""Gerador de relatório comparativo em Excel com formatação Traffic Light.

Este módulo implementa a geração de relatórios Excel consolidados
ao final de cada ciclo de monitoramento. Utiliza openpyxl para criar
planilhas com formatação condicional por cores (verde/amarelo/vermelho)
indicando a posição competitiva de cada produto.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from price_watchdog.models.entities import PriceCycle, PriceRecord


@dataclass
class ReportRow:
    """Linha individual do relatório comparativo.

    Desacopla a geração do relatório das relações SQLAlchemy,
    permitindo uso independente do contexto de sessão do banco.

    Attributes:
        competitor_name: Nome do concorrente
        product_name: Nome do produto monitorado
        our_price: Nosso preço de referência
        extracted_price: Preço extraído do concorrente
        price_difference: Diferença absoluta (extracted - our)
        price_difference_pct: Diferença percentual
    """

    competitor_name: str
    product_name: str
    our_price: float
    extracted_price: float
    price_difference: float
    price_difference_pct: float


# Cores do Traffic Light Report
_GREEN_FILL = PatternFill(
    start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"
)
_YELLOW_FILL = PatternFill(
    start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"
)
_RED_FILL = PatternFill(
    start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"
)

# Colunas do relatório
_COLUMNS = [
    "Concorrente",
    "Produto",
    "Nosso Preço",
    "Preço Deles",
    "Diferença (R$)",
    "Diferença (%)",
    "Status",
]


class ExcelReportGenerator:
    """Gerador de relatório comparativo em Excel.

    Gera arquivos Excel com formatação Traffic Light para indicar
    a posição competitiva de cada produto em relação aos concorrentes.

    Cores:
        - Verde: somos mais baratos que o concorrente
        - Amarelo: diferença inferior a 5% (atenção)
        - Vermelho: nosso preço é mais de 5% acima do concorrente
    """

    def generate(
        self, records: list[PriceRecord], cycle: PriceCycle
    ) -> bytes:
        """Gera arquivo Excel com formatação Traffic Light.

        Filtra apenas records com extraction_status == "success"
        e gera uma planilha com as colunas obrigatórias e formatação
        condicional por cores.

        Args:
            records: Lista de PriceRecords do ciclo (pode incluir
                falhas, que serão filtradas).
            cycle: PriceCycle correspondente ao relatório.

        Returns:
            Conteúdo do arquivo Excel em bytes.
        """
        rows = self._build_rows(records)
        wb = Workbook()
        ws = wb.active
        ws.title = "Comparativo de Preços"

        self._write_header(ws, cycle)
        self._write_data(ws, rows)
        self._adjust_column_widths(ws)

        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def generate_from_rows(
        self, rows: list[ReportRow], cycle: PriceCycle
    ) -> bytes:
        """Gera arquivo Excel a partir de ReportRows pré-construídos.

        Útil quando os dados já foram extraídos das entidades
        e não há sessão SQLAlchemy disponível.

        Args:
            rows: Lista de ReportRow com dados do relatório.
            cycle: PriceCycle correspondente ao relatório.

        Returns:
            Conteúdo do arquivo Excel em bytes.
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Comparativo de Preços"

        self._write_header(ws, cycle)
        self._write_data(ws, rows)
        self._adjust_column_widths(ws)

        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def _build_rows(self, records: list[PriceRecord]) -> list[ReportRow]:
        """Converte PriceRecords em ReportRows filtrando apenas sucessos.

        Args:
            records: Lista de PriceRecords (inclui falhas).

        Returns:
            Lista de ReportRow apenas com registros bem-sucedidos.
        """
        rows: list[ReportRow] = []
        for record in records:
            if record.extraction_status != "success":
                continue

            # Acessar nome do concorrente via relationships
            competitor_name = ""
            if (
                record.product_config
                and record.product_config.competitor
            ):
                competitor_name = (
                    record.product_config.competitor.name
                )

            product_name = ""
            if record.product_config:
                product_name = record.product_config.product_name

            rows.append(
                ReportRow(
                    competitor_name=competitor_name,
                    product_name=product_name,
                    our_price=record.our_price,
                    extracted_price=record.extracted_price,
                    price_difference=record.price_difference,
                    price_difference_pct=record.price_difference_pct,
                )
            )
        return rows

    def _write_header(self, ws, cycle: PriceCycle) -> None:
        """Escreve cabeçalho do relatório com informações do ciclo.

        Args:
            ws: Worksheet ativa do openpyxl.
            cycle: PriceCycle com metadados do ciclo.
        """
        # Título do relatório
        ws["A1"] = "Relatório Comparativo de Preços"
        ws["A1"].font = Font(bold=True, size=14)

        # Informações do ciclo
        started = ""
        if cycle.started_at:
            started = cycle.started_at.strftime("%d/%m/%Y %H:%M")
        ws["A2"] = f"Ciclo: {started}"
        ws["A2"].font = Font(size=10, italic=True)

        # Cabeçalhos das colunas (linha 4)
        header_font = Font(bold=True, size=11)
        for col_idx, col_name in enumerate(_COLUMNS, start=1):
            cell = ws.cell(row=4, column=col_idx, value=col_name)
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

    def _write_data(self, ws, rows: list[ReportRow]) -> None:
        """Escreve dados do relatório com formatação Traffic Light.

        Args:
            ws: Worksheet ativa do openpyxl.
            rows: Lista de ReportRow com os dados.
        """
        for row_idx, row_data in enumerate(rows, start=5):
            ws.cell(
                row=row_idx, column=1, value=row_data.competitor_name
            )
            ws.cell(
                row=row_idx, column=2, value=row_data.product_name
            )
            ws.cell(
                row=row_idx, column=3, value=row_data.our_price
            ).number_format = '#,##0.00'
            ws.cell(
                row=row_idx, column=4, value=row_data.extracted_price
            ).number_format = '#,##0.00'
            ws.cell(
                row=row_idx, column=5, value=row_data.price_difference
            ).number_format = '#,##0.00'
            ws.cell(
                row=row_idx,
                column=6,
                value=row_data.price_difference_pct,
            ).number_format = '0.00"%"'

            # Determinar status e aplicar traffic light
            status = self._get_status(row_data.price_difference_pct)
            ws.cell(row=row_idx, column=7, value=status)

            self._apply_traffic_light(
                ws, row_idx, row_data.price_difference_pct
            )

    def _apply_traffic_light(
        self, worksheet, row: int, pct_diff: float
    ) -> None:
        """Aplica formatação condicional por cores (Traffic Light).

        Regras:
            - Verde: our_price < extracted_price (pct_diff > 0,
              concorrente é mais caro, somos competitivos)
            - Amarelo: diferença absoluta inferior a 5%
              (-5 < pct_diff <= 0, estamos ligeiramente acima)
            - Vermelho: our_price mais de 5% acima do concorrente
              (pct_diff <= -5)

        Nota: pct_diff = (extracted - our) / our * 100
            - Positivo: concorrente cobra mais (somos mais baratos)
            - Negativo: concorrente cobra menos (somos mais caros)

        Args:
            worksheet: Worksheet do openpyxl.
            row: Número da linha a ser formatada.
            pct_diff: Diferença percentual calculada.
        """
        if pct_diff > 0:
            # Concorrente cobra mais — somos competitivos
            fill = _GREEN_FILL
        elif pct_diff > -5:
            # Diferença absoluta inferior a 5% — atenção
            fill = _YELLOW_FILL
        else:
            # Nosso preço mais de 5% acima — não competitivo
            fill = _RED_FILL

        for col in range(1, len(_COLUMNS) + 1):
            worksheet.cell(row=row, column=col).fill = fill

    def _get_status(self, pct_diff: float) -> str:
        """Retorna o texto de status baseado na diferença percentual.

        Args:
            pct_diff: Diferença percentual (extracted - our) / our * 100.

        Returns:
            "Competitivo", "Atenção" ou "Não Competitivo".
        """
        if pct_diff > 0:
            return "Competitivo"
        elif pct_diff > -5:
            return "Atenção"
        else:
            return "Não Competitivo"

    def _adjust_column_widths(self, ws) -> None:
        """Ajusta largura das colunas baseado no conteúdo.

        Args:
            ws: Worksheet do openpyxl.
        """
        min_widths = [18, 25, 14, 14, 16, 14, 18]
        for col_idx, min_width in enumerate(min_widths, start=1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = min_width
