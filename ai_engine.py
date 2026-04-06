import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
import pandas as pd


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
                "rr": types.Schema(type=types.Type.STRING, description="Причина сомнения (иначе пустая стркоа)"),
            },
            required=["n", "u", "q", "p", "r", "rr"]
        )

        response_schema = types.Schema(
            type=types.Type.ARRAY,
            items=item_schema
        )

        self.base_config = types.GenerateContentConfig(
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

    def process_document(self, file_path: str, system_prompt: str) -> str:
        _, ext = os.path.splitext(file_path.lower())
        contents = []

        try:
            if ext in ['.xlsx', '.xls']:
                csv_data = self._convert_excel_to_csv(file_path)
                contents = [system_prompt, csv_data]
                uploaded_file = None

            elif ext in ['.pdf', '.jpg', '.jpeg', '.png']:
                uploaded_file = self.client.files.upload(file=file_path)
                contents = [system_prompt, uploaded_file]

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
