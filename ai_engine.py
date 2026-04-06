import os
from google import genai
from google.genai import types
from dotenv import load_dotenv


class DocumentProcessor:
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("Критическая ошибка: API ключ не найден в .env.")

        # 1. Создаем изолированного клиента вместо глобальной конфигурации
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-3.1-flash-lite-preview"

        # 2. Настройки генерации теперь упаковываются в специальный класс GenerateContentConfig
        self.config = types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        )

        print("Инициализация DocumentProcessor успешна.")

    def test_connection(self):
        try:
            print("Отправка тестового запроса...")
            # 3. Вызов идет через client.models, куда передаются модель, контент и конфиг
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