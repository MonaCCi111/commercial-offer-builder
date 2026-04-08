import os
import sys
import json

# Определяем папку, откуда запущена программа (скрипт или скомпилированный .exe)
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROMPT_PATH = os.path.join(BASE_DIR, "prompt.txt")

# Базовый системный промпт по умолчанию
DEFAULT_PROMPT = """Ты — эксперт-аудитор по оцифровке смет, чеков и накладных для компании в сфере отопления и водоснабжения.
Твоя единственная цель — извлечь ВСЕ товарные позиции из предоставленного документа и вернуть их в строгом JSON формате.

КРИТИЧЕСКИЕ ПРАВИЛА ИЗВЛЕЧЕНИЯ (СТРОГО СОБЛЮДАТЬ):
1. ЗАПРЕЩАЕТСЯ ПРОПУСКАТЬ ПОЗИЦИИ: Ты должен извлечь каждую строку с товаром.
2. ФИЛЬТРАЦИЯ МУСОРА: Игнорируй реквизиты компаний, адреса, общие итоги (суммы в конце), скидки, подписи и печати. Извлекай только конкретную номенклатуру (трубы, фитинги, котлы, краны, услуги монтажа и т.д.).
3. ПУСТЫЕ СТРАНИЦЫ: Если на странице НЕТ конкретных товаров (например, это титульный лист, акт сверки или страница только с реквизитами/печатями), просто верни пустой массив: [].
4. ЕДИНИЦЫ ИЗМЕРЕНИЯ (u): Всегда приводи единицы измерения к строчным (маленьким) буквам. Например: "шт.", "м.", "упак.", "компл.".
5. РАБОТА С ЦЕНОЙ (p): Если в документе не указана цена за единицу товара, обязательно установи значение ключа "p" равным 0. Не пытайся угадать цену.
6. ПРОВЕРКА СОМНЕНИЙ (r, rr): Устанавливай флаг "r" в true каждый раз, когда сомневаешься в том, правильно ли обработал позицию:
   - Текст размыт, и ты не уверен в названии или цифрах.
   - Единица измерения нетипична или отсутствует.
   - Если "r" = true, в поле "rr" кратко напиши причину. Если сомнений нет, "r" = false, а "rr" = "".
"""

# Базовые настройки по умолчанию
DEFAULT_CONFIG = {
    "GEMINI_API_KEY": "",
    "WORKER_URL": "",
    "MODEL_NAME": "gemini-2.5-flash",
    "TIMEOUT_MS": 60000,
    "EXCEL_CHUNK_SIZE": 100,
    "PDF_CHUNK_SIZE": 3
}

class AppConfig:
    def __init__(self):
        self.settings = DEFAULT_CONFIG.copy()
        self.prompt = DEFAULT_PROMPT
        self._load_config()
        self._load_prompt()

    def _load_config(self):
        # Читаем config.json, если нет - создаем
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self.settings.update(user_config)
            except Exception as e:
                print(f"Ошибка чтения config.json: {e}. Используются базовые настройки.")
        else:
            self._save_config()

    def _save_config(self):
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Ошибка создания config.json: {e}")

    def _load_prompt(self):
        # Читаем prompt.txt, если нет - создаем
        if os.path.exists(PROMPT_PATH):
            try:
                with open(PROMPT_PATH, 'r', encoding='utf-8') as f:
                    self.prompt = f.read()
            except Exception as e:
                print(f"Ошибка чтения prompt.txt: {e}. Используется базовый промпт.")
        else:
            self._save_prompt()

    def _save_prompt(self):
        try:
            with open(PROMPT_PATH, 'w', encoding='utf-8') as f:
                f.write(DEFAULT_PROMPT)
        except Exception as e:
            print(f"Ошибка создания prompt.txt: {e}")

    def get(self, key):
        return self.settings.get(key)

# Создаем глобальный объект настроек
config = AppConfig()