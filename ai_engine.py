import os
import time
import json
import tempfile
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from dotenv import load_dotenv
import pandas as pd

SYSTEM_PROMPT = """Ты — эксперт-аудитор по оцифровке строительных смет, чеков и накладных для компании в сфере отопления и водоснабжения.
Твоя единственная цель — извлечь ВСЕ товарные позиции из предоставленного документа и вернуть их в строгом JSON формате.

КРИТИЧЕСКИЕ ПРАВИЛА ИЗВЛЕЧЕНИЯ (СТРОГО СОБЛЮДАТЬ):
1. ЗАПРЕЩАЕТСЯ ПРОПУСКАТЬ ПОЗИЦИИ: Ты должен извлечь каждую строку с товаром. Если в документе 150 товаров, в твоем ответе должно быть ровно 150 объектов. Не объединяй разные позиции в одну.
2. ФИЛЬТРАЦИЯ МУСОРА: Игнорируй реквизиты компаний, адреса, общие итоги (суммы в конце), скидки, подписи и печати. Извлекай только конкретную номенклатуру (трубы, фитинги, котлы, краны, услуги монтажа и т.д.).
3. ПУСТЫЕ СТРАНИЦЫ: Если на странице НЕТ конкретных товаров (например, это титульный лист, акт сверки или страница только с реквизитами/печатями), просто верни пустой массив: [].
4. ЕДИНИЦЫ ИЗМЕРЕНИЯ (u): Всегда приводи единицы измерения к строчным (маленьким) буквам. Например: "шт.", "м.", "упак.", "компл.".
5. РАБОТА С ЦЕНОЙ (p): Если в документе не указана цена за единицу товара, обязательно установи значение ключа "p" равным 0. Не пытайся угадать цену.
6. ПРОВЕРКА СОМНЕНИЙ (r, rr): Устанавливай флаг "r" в true в каждом случае если сомневаешься в том, правильно ли обработал позицию, например:
   - Текст размыт, и ты не уверен в названии или цифрах.
   - Единица измерения нетипична или отсутствует.
   - Если "r" = true, в поле "rr" кратко напиши причину. Если сомнений нет, "r" = false, а "rr" = "".
"""


class DocumentProcessor:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("Критическая ошибка: API ключ не найден в .env.")

        WORKER_URL = os.getenv("WORKER_URL")

        self.client = genai.Client(
            api_key=api_key,
            http_options={
                'base_url': WORKER_URL,
                'timeout': 600000
            }
        )

        self.model_name = "gemini-2.5-flash"

        item_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "n": types.Schema(type=types.Type.STRING, description="Наименование товара"),
                "u": types.Schema(type=types.Type.STRING, description="Единица измерения (строчными буквами)"),
                "q": types.Schema(type=types.Type.NUMBER, description="Количество"),
                "p": types.Schema(type=types.Type.NUMBER, description="Цена за единицу (если нет цены, верни 0)"),
                "r": types.Schema(type=types.Type.BOOLEAN, description="Флаг сомнения"),
                "rr": types.Schema(type=types.Type.STRING, description="Причина сомнения (иначе пустая строка)"),
            },
            required=["n", "u", "q", "p", "r", "rr"]
        )

        response_schema = types.Schema(
            type=types.Type.ARRAY,
            items=item_schema
        )

        self.base_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=response_schema
        )

        print("Инициализация DocumentProcessor (Cloudflare Edition + Chunking) успешна.")

    def _convert_excel_to_csv(self, file_path: str) -> str:
        try:
            df = pd.read_excel(file_path)
            return df.to_csv(index=False)
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении Excel файла {file_path}")

    def _process_file_direct(self, file_path: str, is_csv_text=False) -> list:
        """Отправляет один файл/чанк и возвращает list словарей."""
        uploaded_file = None
        contents = []

        try:
            if is_csv_text:
                contents = [file_path]
            else:
                uploaded_file = self.client.files.upload(file=file_path)
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded_file = self.client.files.get(name=uploaded_file.name)

                if uploaded_file.state.name == "FAILED":
                    raise ValueError("Внутренняя ошибка Google при чтении файла.")
                contents = [uploaded_file]

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=self.base_config
                    )

                    data = json.loads(response.text)
                    return data if isinstance(data, list) else []

                except Exception as api_err:
                    error_str = str(api_err).upper()
                    if any(err in error_str for err in ["503", "UNAVAILABLE", "429", "QUOTA"]):
                        if attempt < max_retries - 1:
                            sleep_time = 3 * (2 ** attempt)
                            print(f"Сервер Google занят (Попытка {attempt + 1}). Ждем {sleep_time} сек...")
                            time.sleep(sleep_time)
                            continue
                    raise api_err
        finally:
            if uploaded_file is not None:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

    def process_document(self, file_path: str) -> str:
        _, ext = os.path.splitext(file_path.lower())
        all_items = []

        try:
            if ext in ['.xlsx', '.xls']:
                csv_data = self._convert_excel_to_csv(file_path)
                all_items.extend(self._process_file_direct(csv_data, is_csv_text=True))

            elif ext in ['.jpg', '.jpeg', '.png']:
                print(f"Обработка изображения {os.path.basename(file_path)}...")
                all_items.extend(self._process_file_direct(file_path, is_csv_text=False))

            elif ext == '.pdf':
                print(f"Нарезка PDF {os.path.basename(file_path)} на куски...")
                reader = PdfReader(file_path)
                total_pages = len(reader.pages)
                chunk_size = 3

                for i in range(0, total_pages, chunk_size):
                    end_page = min(i + chunk_size, total_pages)
                    print(f" -> Отправка страниц {i + 1}-{end_page} из {total_pages}...")

                    writer = PdfWriter()
                    for j in range(i, end_page):
                        writer.add_page(reader.pages[j])

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        writer.write(tmp.name)
                        tmp_path = tmp.name

                    try:
                        chunk_items = self._process_file_direct(tmp_path, is_csv_text=False)
                        all_items.extend(chunk_items)
                    finally:
                        os.remove(tmp_path)

            else:
                raise ValueError(f"Неподдерживаемый формат файла: {ext}")

            return json.dumps(all_items)

        except Exception as e:
            return f'{{"error": "Ошибка обработки: {str(e)}"}}'