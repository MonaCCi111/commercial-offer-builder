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
ANALYZER_PROMPT_PATH = os.path.join(BASE_DIR, "analyzer_prompt.txt")

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

ANALYZER_PROMPT = """Ты — Аналитик структуры документов. 
Твоя задача — изучить предоставленные тебе страницы или строки документа (фрагмент) и написать краткую, но исчерпывающую текстовую инструкцию (шпаргалку) для второго агента-парсера, который будет извлекать товары из документа.

Что нужно найти и описать:
1. КАРТА КОЛОНОК: Опиши структуру таблицы. Распиши в каких номерах колонок что находится. Опиши так все колонки
2. ПРАВИЛО ЦЕНЫ (СТРОГИЙ ПРИОРИТЕТ): Ищи нужную цену по правилу: 1) "Цена со скидкой", 2) "Цена с НДС", 3) Просто Цена. Напиши парсеру четко, например: "Брать цену из колонки X (Цена с НДС)".
3. АНОМАЛИИ: Обрати внимание на странный формат чисел (например, баги 1С с количеством вида "100.000 0" вместо 100 , слипшиеся строки или цены вида 1'987.12). Опиши, как Парсеру правильно очищать эти данные.

Верни только понятный текст-инструкцию. Не пиши никаких комментариев вроде "Конечно, вот ваша структура...". Будь краток и конкретен."
"""

# Базовые настройки по умолчанию
DEFAULT_CONFIG = {
    "GEMINI_API_KEY": "",
    "WORKER_URL": "",
    "MODEL_NAME": "gemini-2.5-flash",
    "TIMEOUT_MS": 60000,
    "EXCEL_CHUNK_SIZE": 100,
    "PDF_CHUNK_SIZE": 3,
    "EXCEL_HEAD": 100,
    "PDF_HEAD": 2
}

class AppConfig:
    def __init__(self):
        self.settings = DEFAULT_CONFIG.copy()
        self.prompt = DEFAULT_PROMPT
        self.analyzer_prompt = ANALYZER_PROMPT
        self._load_config()
        self._load_prompt()
        self._load_analyzer_prompt()

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

    def _load_analyzer_prompt(self):
        if os.path.exists(ANALYZER_PROMPT_PATH):
            try:
                with open(ANALYZER_PROMPT_PATH, 'r', encoding='utf-8') as f:
                    self.analyzer_prompt = f.read()
            except Exception as e:
                print(f"Ошибка чтения analyzer_prompt.txt: {e}. Используется базовый промпт.")
        else:
            self._save_analyzer_prompt()

    def _save_analyzer_prompt(self):
        try:
            with open(ANALYZER_PROMPT_PATH, 'w', encoding='utf-8') as f:
                f.write(ANALYZER_PROMPT)
        except Exception as e:
            print(f"Ошибка создания analyzer_prompt.txt: {e}")


    def get(self, key):
        return self.settings.get(key)

# Создаем глобальный объект настроек
config = AppConfig()