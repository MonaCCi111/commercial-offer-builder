import os
import time
import json
import tempfile

from docutils.nodes import target
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
import pandas as pd
from pathlib import Path

from config import config


class DocumentProcessor:
    def __init__(self):
        api_key = config.get("GEMINI_API_KEY")
        WORKER_URL = config.get("WORKER_URL")
        self.model_lite = config.get("MODEL_LITE")
        self.model_vision = config.get("MODEL_VISION")
        timeout_ms = config.get("TIMEOUT_MS")
        self.system_prompt = config.prompt
        self.analyzer_prompt = config.analyzer_prompt

        if not api_key:
            raise ValueError("Критическая ошибка: API ключ не найден в .env.")

        self.client = genai.Client(
            api_key=api_key,
            http_options={
                'base_url': WORKER_URL,
                'timeout': timeout_ms
            }
        )

        self.item_schema = types.Schema(
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

        self.response_schema = types.Schema(
            type=types.Type.ARRAY,
            items=self.item_schema
        )

        # self.base_config = types.GenerateContentConfig(
        #     system_instruction=system_prompt,
        #     temperature=0.1,
        #     response_mime_type="application/json",
        #     response_schema=response_schema
        # )

        print("Инициализация DocumentProcessor")

    def _analyze_file(self, file_path: str, model_name: str, is_csv_text=False) -> str:
        """Анализирует начало документа и возвращает текстовую инструкцию"""
        uploaded_file = None
        contents = []

        analyzer_config = types.GenerateContentConfig(
            system_instruction=self.analyzer_prompt,
            temperature=0.1,
            response_mime_type="text/plain"
        )

        try:
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    if not is_csv_text and uploaded_file is None:
                        uploaded_file = self.client.files.upload(file=file_path)
                        while uploaded_file.state.name == "PROCESSING":
                            time.sleep(2)
                            uploaded_file = self.client.files.get(name=uploaded_file.name)

                        if uploaded_file.state.name == "FAILED":
                            raise ValueError("Ошибка Google при чтении файла для общего анализа.")

                    contents = [file_path] if is_csv_text else [uploaded_file]

                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=analyzer_config
                    )
                    return response.text
                except Exception as api_err:
                    error_str = str(api_err).upper()
                    if any(err in error_str for err in ["503", "502", "504", "UNAVAILABLE", "429", "QUOTA", "10060",
                                                        "10054", "10053", "TIMEOUT", "TIMED OUT", "READ OPERATION",
                                                        "CONNECT", "DISCONNECT", "CONNECTION ABORTED"]):
                        if attempt <= max_retries:
                            sleep_time = 3 * (2 ** attempt)
                            print(f"    [БРОНЯ АНАЛИТИКА] Сбой сети. Попытка {attempt + 1}. Ждём {sleep_time} сек..")
                            time.sleep(sleep_time)
                            continue
                    raise api_err
        except Exception as e:
            print(f"    [Ошибка анализа: {e}]")
            return "Анализ не удался. Ищи колонки с ценой (приоритет: цена со скидкой -> цена с НДС -> просто цена) и количеством самостоятельно. Постарайся вдумчиво обработать баги отображения."
        finally:
            if uploaded_file is not None:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

    def _convert_excel_to_csv(self, file_path: str) -> str:
        try:
            df = pd.read_excel(file_path)
            return df.to_csv(index=False)
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении Excel файла {file_path}")

    def _process_file_direct(self, file_path: str, file_name: str, model_name: str, is_csv_text=False, instruction_context="") -> list:
        uploaded_file = None
        contents = []

        dynamic_prompt =  f"Название текущего файла: {file_name}\n" + self.system_prompt
        if instruction_context:
            dynamic_prompt += f"\n\n--- ИНСТРУКЦИЯ ОТ АНАЛИТИКА ПО ЭТОМУ ДОКУМЕНТУ ---\n{instruction_context}"

        parser_config = types.GenerateContentConfig(
            system_instruction=dynamic_prompt,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=self.response_schema
        )

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
                        model=model_name,
                        contents=contents,
                        config=parser_config
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

    def process_document(self, file_path: str, status_callback=None) -> str:
        def notify(msg):
            print(msg)
            if status_callback:
                status_callback(msg)

        _, ext = os.path.splitext(file_path.lower())
        all_items = []

        file_name = Path(file_path).name

        try:
            if ext in ['.jpg', '.jpeg', '.png']:
                target_model = self.model_vision
            else:
                target_model = self.model_lite

            if ext in ['.xlsx', '.xls']:
                notify(f"Обработка Excel файла {os.path.basename(file_path)}...")

                # Читаем ВСЕ листы (sheet_name=None возвращает словарь {имя_листа: датафрейм})
                sheets_dict = pd.read_excel(file_path, sheet_name=None)

                for sheet_name, df in sheets_dict.items():
                    # Удаляем полностью пустые строки, чтобы не тратить токены
                    df = df.dropna(how='all')
                    if df.empty:
                        continue

                    total_rows = len(df)
                    chunk_size = config.get("EXCEL_CHUNK_SIZE")
                    excel_head = config.get("EXCEL_HEAD")

                    notify(f" -> [Анализ] Изучаем структуру листа '{sheet_name}' (первые {excel_head} строк)...")
                    head_csv = df.head(excel_head).to_csv(index=False)
                    analyzer_rules = self._analyze_file(head_csv, target_model, is_csv_text=True)
                    notify(f"    [Аналитик] Правила:\n{analyzer_rules}\n")

                    notify(f" -> Лист '{sheet_name}': {total_rows} строк. Нарезка на чанки...")

                    for i in range(0, total_rows, chunk_size):
                        end_row = min(i + chunk_size, total_rows)
                        notify(f"    -> Отправка строк {i + 1}-{end_row}...")

                        chunk_df = df.iloc[i:end_row]
                        csv_data = chunk_df.to_csv(index=False)

                        chunk_items = self._process_file_direct(csv_data, file_name, target_model,
                                                                is_csv_text=True,
                                                                instruction_context=analyzer_rules)
                        all_items.extend(chunk_items)

                        time.sleep(4)

            elif ext in ['.jpg', '.jpeg', '.png']:
                notify(f"Обработка изображения {os.path.basename(file_path)}...")
                all_items.extend(self._process_file_direct(file_path, file_name, target_model,
                                                           is_csv_text=False))

            elif ext == '.pdf':
                notify(f"Нарезка PDF {os.path.basename(file_path)} на куски...")
                reader = PdfReader(file_path)
                total_pages = len(reader.pages)
                chunk_size = config.get("PDF_CHUNK_SIZE")

                notify(f" -> [Анализ] Изучаем структуру документа (первые страницы)...")
                writer_analyzer = PdfWriter()
                pages_to_analyze = min(config.get("PDF_HEAD"), total_pages)
                for p in range(pages_to_analyze):
                    writer_analyzer.add_page(reader.pages[p])

                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_analyzer:
                    writer_analyzer.write(tmp_analyzer.name)
                    analyzer_path = tmp_analyzer.name

                try:
                    analyzer_rules = self._analyze_file(analyzer_path, target_model,
                                                        is_csv_text=False)
                    notify(f"    [Аналитик] Правила:\n{analyzer_rules}\n")
                finally:
                    os.remove(analyzer_path)

                for i in range(0, total_pages, chunk_size):
                    end_page = min(i + chunk_size, total_pages)
                    notify(f" -> Отправка страниц {i + 1}-{end_page} из {total_pages}...")

                    writer = PdfWriter()
                    for j in range(i, end_page):
                        writer.add_page(reader.pages[j])

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        writer.write(tmp.name)
                        tmp_path = tmp.name

                    try:
                        chunk_items = self._process_file_direct(tmp_path, file_name, target_model,
                                                                is_csv_text=False, instruction_context=analyzer_rules)
                        all_items.extend(chunk_items)
                    finally:
                        os.remove(tmp_path)
                        notify("Охлаждение 4 сек перед следующей страницей...")
                        time.sleep(4)

            else:
                raise ValueError(f"Неподдерживаемый формат файла: {ext}")

            return json.dumps(all_items)

        except Exception as e:
            return f'{{"error": "Ошибка обработки: {str(e)}"}}'
