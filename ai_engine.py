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
1. ЗАПРЕЩАЕТСЯ ПРОПУСКАТЬ ПОЗИЦИИ: Ты должен извлечь каждую строку с товаром.
2. ФИЛЬТРАЦИЯ МУСОРА: Игнорируй реквизиты компаний, адреса, общие итоги (суммы в конце), скидки, подписи и печати. Извлекай только конкретную номенклатуру (трубы, фитинги, котлы, краны, услуги монтажа и т.д.).
3. ПУСТЫЕ СТРАНИЦЫ: Если на странице НЕТ конкретных товаров (например, это титульный лист, акт сверки или страница только с реквизитами/печатями), просто верни пустой массив: [].
4. ЕДИНИЦЫ ИЗМЕРЕНИЯ (u): Всегда приводи единицы измерения к строчным (маленьким) буквам. Например: "шт.", "м.", "упак.", "компл.".
5. РАБОТА С ЦЕНОЙ (p): Если в документе не указана цена за единицу товара, обязательно установи значение ключа "p" равным 0. Не пытайся угадать цену.
6. ПРОВЕРКА СОМНЕНИЙ (r, rr): Устанавливай флаг "r" в true ТОЛЬКО в следующих случаях:
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

        # Возвращаем твой Cloudflare Worker
        WORKER_URL = os.getenv("WORKER_URL")

        self.client = genai.Client(
            api_key=api_key,
            http_options={
                'base_url': WORKER_URL,
                'timeout': 60000  # <--- УМЕНЬШИЛИ ДО 60 СЕКУНД
            }
        )

        self.model_name = os.getenv("MODEL_NAME")

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

        print("Инициализация DocumentProcessor (Cloudflare + 1-Page Chunking + Armor) успешна.")

    def _convert_excel_to_csv(self, file_path: str) -> str:
        try:
            df = pd.read_excel(file_path)
            return df.to_csv(index=False)
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении Excel файла {file_path}")

    def _process_file_direct(self, file_path: str, is_csv_text=False) -> list:
        uploaded_file = None
        contents = []

        # Оборачиваем весь процесс во ВНЕШНИЙ try, чтобы finally сработал только один раз в конце
        try:
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    # 1. Загрузка файла
                    if not is_csv_text and uploaded_file is None:
                        uploaded_file = self.client.files.upload(file=file_path)
                        while uploaded_file.state.name == "PROCESSING":
                            time.sleep(2)
                            uploaded_file = self.client.files.get(name=uploaded_file.name)

                        if uploaded_file.state.name == "FAILED":
                            raise ValueError("Внутренняя ошибка Google при чтении файла.")

                    # Формируем контент для отправки
                    if is_csv_text:
                        contents = [file_path]
                    else:
                        contents = [uploaded_file]

                    # 2. Генерация ответа
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=self.base_config
                    )

                    data = json.loads(response.text)
                    return data if isinstance(data, list) else []

                except Exception as api_err:
                    error_str = str(api_err).upper()

                    # Перехватчик ошибок
                    if any(err in error_str for err in
                           ["503", "502", "504", "UNAVAILABLE", "429", "QUOTA", "10060", "10054", "10053", "TIMEOUT",
                            "TIMED OUT", "READ OPERATION", "CONNECT", "DISCONNECT", "CONNECTION ABORTED"]):
                        if attempt < max_retries - 1:
                            sleep_time = 3 * (2 ** attempt)
                            print(
                                f"    [БРОНЯ] Сбой сети (Код: {error_str[:35]}...). Попытка {attempt + 1} из {max_retries}. Ждем {sleep_time} сек...")
                            time.sleep(sleep_time)
                            continue

                    raise api_err
        finally:
            # Теперь очистка срабатывает строго ОДИН РАЗ после всех попыток или успешной отработки
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
                print(f"Обработка Excel файла {os.path.basename(file_path)}...")

                # Читаем ВСЕ листы (sheet_name=None возвращает словарь {имя_листа: датафрейм})
                sheets_dict = pd.read_excel(file_path, sheet_name=None)

                for sheet_name, df in sheets_dict.items():
                    # Удаляем полностью пустые строки, чтобы не тратить токены
                    df = df.dropna(how='all')
                    if df.empty:
                        continue

                    total_rows = len(df)
                    # Берем по 40 строк за раз, чтобы ИИ 100% успевал их вернуть без обрывов
                    chunk_size = 100

                    print(f" -> Лист '{sheet_name}': {total_rows} строк. Нарезка на чанки...")

                    for i in range(0, total_rows, chunk_size):
                        end_row = min(i + chunk_size, total_rows)
                        print(f"    -> Отправка строк {i + 1}-{end_row}...")

                        # Вырезаем кусок датафрейма и переводим в CSV
                        chunk_df = df.iloc[i:end_row]
                        csv_data = chunk_df.to_csv(index=False)

                        # Отправляем текст напрямую
                        chunk_items = self._process_file_direct(csv_data, is_csv_text=True)
                        all_items.extend(chunk_items)

                        # Та же пауза для защиты от Rate Limit (429 ошибка)
                        time.sleep(4)

            elif ext in ['.jpg', '.jpeg', '.png']:
                print(f"Обработка изображения {os.path.basename(file_path)}...")
                all_items.extend(self._process_file_direct(file_path, is_csv_text=False))

            elif ext == '.pdf':
                print(f"Нарезка PDF {os.path.basename(file_path)} на куски...")
                reader = PdfReader(file_path)
                total_pages = len(reader.pages)
                chunk_size = 3  # Строго 1 страница, чтобы не упираться в лимит токенов

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
                        # <--- УВЕЛИЧИЛИ ПАУЗУ МЕЖДУ СТРАНИЦАМИ
                        print("Охлаждение 4 сек перед следующей страницей...")
                        time.sleep(4)

            else:
                raise ValueError(f"Неподдерживаемый формат файла: {ext}")

            return json.dumps(all_items)

        except Exception as e:
            return f'{{"error": "Ошибка обработки: {str(e)}"}}'