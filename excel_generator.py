import json
import os.path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.styles.builtins import total


class OfferGenerator:
    def __init__(self, template_path=None):
        self.template_path = template_path

        # Задаем цвета для подсветки (в формате ARGB)
        # Красный (FFC7CE) - для флага сомнения (r == True)
        self.color_doubt = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
        # Желтый (FFF2CC) - для позиций без цены (p == 0)
        self.color_no_price = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")

    def generate(self, data_json_str: str, output_path="commercial_offer.xlsx") -> str:
        try:
            data = json.loads(data_json_str)
        except json.JSONDecodeError:
            raise ValueError(f"Ошибка парсинга. ИИ вернул невалидный JSON: {data_json_str}")

        if self.template_path and os.path.exists(self.template_path):
            wb = load_workbook(self.template_path)
            ws = wb.active
            start_row = 15
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Коммерческое предложение от ТЕПЛОМИР"
            start_row=2

            headers = ["Наименование", "Ед. изм.", "Кол-во", "Цена", "Сумма", "Примечание (ИИ)"]
            ws.append(headers)
            for col_num in range(1,7):
                cell = ws.cell(row=1, column=col_num)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal="center")

        current_row = start_row
        for item in data:
            name= item.get("n", "")
            unit = item.get("u", "")
            quantity = item.get("q", 0)
            price = item.get("p", 0)
            doubt = item.get("r", False)
            reason = item.get("rr", "")

            ws.cell(row=current_row, column=1, value=name)
            ws.cell(row=current_row, column=2, value=unit)
            ws.cell(row=current_row, column=3, value=quantity)

            price_cell = ws.cell(row=current_row, column=4)
            sum_cell = ws.cell(row=current_row, column=5)
            note_cell = ws.cell(row=current_row, column=6)

            if price == 0:
                price_cell.value = ""
                sum_cell.value = ""
                for col in range(1,7):
                    ws.cell(row=current_row, column=col).fill = self.color_no_price
            else:
                price_cell.value = price
            sum_cell.value = f"=C{current_row}*D{current_row}"

            if doubt:
                note_cell.value = reason
                for col in range(1,7):
                    ws.cell(row=current_row, column=col).fill = self.color_doubt

            current_row += 1

        total_row = current_row + 1
        ws.cell(row=total_row, column=4, value="ИТОГО:").font = Font(bold=True)
        end_data_row = current_row - 1
        if end_data_row >= start_row:
            total_sum_formula = f"=SUM(E{start_row}:E{end_data_row})"
            ws.cell(row=total_row, column=5, value=total_sum_formula).font = Font(bold=True)
        ws.column_dimensions['A'].width = 50
        ws.column_dimensions['B'].width = 10
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 15
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 35

        wb.save(output_path)
        return output_path
