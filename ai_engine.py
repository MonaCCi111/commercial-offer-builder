import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
import pandas as pd

SYSTEM_PROMPT = """Ты — эксперт-аудитор по оцифровке строительных смет, чеков и накладных для компании в сфере отопления и водоснабжения.
Твоя единственная цель — извлечь ВСЕ товарные позиции из предоставленного документа и вернуть их в строгом JSON формате.

КРИТИЧЕСКИЕ ПРАВИЛА ИЗВЛЕЧЕНИЯ (СТРОГО СОБЛЮДАТЬ):
1. ЗАПРЕЩАЕТСЯ ПРОПУСКАТЬ ПОЗИЦИИ: Ты должен извлечь каждую строку с товаром. Если в документе 150 товаров, в твоем ответе должно быть ровно 150 объектов. Не объединяй разные позиции в одну.
2. ФИЛЬТРАЦИЯ МУСОРА: Игнорируй реквизиты компаний, адреса, общие итоги (суммы в конце), скидки, подписи и печати. Извлекай только конкретную номенклатуру (трубы, фитинги, котлы, краны, услуги монтажа и т.д.).
3. РАБОТА С ЦЕНОЙ (p): Если в документе не указана цена за единицу товара (например, это просто записка от монтажника), обязательно установи значение ключа "p" равным 0. Не пытайся угадать цену из своих знаний.
4. ПРОВЕРКА СОМНЕНИЙ (r, rr): Устанавливай флаг "r" в true ТОЛЬКО в следующих случаях:
   - Текст (особенно рукописный) размыт, и ты не уверен в названии или цифрах.
   - Единица измерения нетипична или отсутствует.
   - Если "r" = true, в поле "rr" кратко напиши причину (например: "Плохо видно цену", "Неразборчивый почерк"). Если сомнений нет, "r" = false, а "rr" = "".
"""

class DocumentProcessor:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("Критическая ошибка: API ключ не найден в .env.")

        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-3.1-flash-lite-preview"

        item_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "n": types.Schema(type=types.Type.STRING, description="Наименование товара"),
                "u": types.Schema(type=types.Type.STRING, description="Единица измерения"),
                "q": types.Schema(type=types.Type.NUMBER, description="Количество"),
                "p": types.Schema(type=types.Type.NUMBER,
                                  description="Цена за единицу (если в документе нет цены, верни 0)"),
                "r": types.Schema(type=types.Type.BOOLEAN,
                                  description="Флаг сомнения: true, если есть малейшие сомнения по поводу корректности этой позиции"),
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

        print("Инициализация DocumentProcessor успешна.")

    def _convert_excel_to_csv(self, file_path: str) -> str:
        try:
            df = pd.read_excel(file_path)
            return df.to_csv(index=False)
        except Exception as e:
            raise RuntimeError(f"Ошибка при чтении Excel файла {file_path}")

    def process_document(self, file_path: str) -> str:
        _, ext = os.path.splitext(file_path.lower())
        contents = []

        try:
            if ext in ['.xlsx', '.xls']:
                csv_data = self._convert_excel_to_csv(file_path)
                contents = [csv_data]
                uploaded_file = None

            elif ext in ['.pdf', '.jpg', '.jpeg', '.png']:
                uploaded_file = self.client.files.upload(file=file_path)
                contents = [uploaded_file]

            else:
                raise ValueError(f"Неподдерживаемый формат файла: {ext}")

            print("Ожидание ответа от нейросети...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=self.base_config
            )

            return response.text

        except Exception as e:
            return f'{{"error": "Ошибка обработки: {str(e)}"}}'

        finally:
            if 'uploaded_file' in locals() and uploaded_file is not None:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                    print("Временный файл удален с сервера.")
                except Exception as e:
                    print(f"Не удалось удалить файл с сервера: {e}")

    def test_connection(self):
        try:
            print("Отправка тестового запроса...")
            response = self.client.models.generate_content(
                model=self.model_name,
                contents="Верни JSON с одним ключом 'status' и значением 'ok'",
                config=self.config
            )
            return response.text
        except Exception as e:
            return f"Ошибка подключения: {e}"


if __name__ == "__main__":
    processor = DocumentProcessor()
    print("Ответ сервера:", processor.test_connection())
