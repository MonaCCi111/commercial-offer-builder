import os
import json
import threading
from collections.abc import generator

import customtkinter as ctk
from tkinter import filedialog, messagebox

from param import output

from ai_engine import DocumentProcessor
from excel_generator import OfferGenerator

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class TeplomirApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Генератор КП")
        self.geometry("500x300")
        self.resizable(False, False)
        self.selected_files = []

        self.title_label = ctk.CTkLabel(self, text = "Автоматизация формирования КП",
                                        font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.pack(pady=(20, 10))

        self.btn_select = ctk.CTkButton(self, text="Выбрать файлы (PDF, JPG, XLSX...)",
                                        command = self.select_files)
        self.btn_select.pack(pady=10)

        self.lbl_files = ctk.CTkLabel(self, text= "Файлы не выбраны", text_color="gray")
        self.lbl_files.pack(pady=(0,10))

        self.btn_start = ctk.CTkButton(self, text="Сгенерировать КП", command=self.start_processing, state="disabled",
                                       fg_color="green", hover_color="darkgreen")

        self.progress = ctk.CTkProgressBar(self, width=400)
        self.progress.pack(pady=15)
        self.progress.set(0)

        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self.lbl_status.pack(pady=5)

    def select_files(self):
        file_paths = filedialog.askopenfilename(
            title="Выберите документы",
            filetypes=[("Documents", "*.pdf *.jpg *.jpeg *.png *.xlsx *.xls")]
        )
        if file_paths:
            self.selected_files = list(file_paths)
            self.lbl_files.configure(text=f"Выбрано файлов: {len(self.selected_files)}", text_color="black")
            self.btn_start.configure(state="normal")

    def start_processing(self):
        self.btn_select.configure(state="disabled")
        self.btn_start.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="Инициализация нейросети...")

        thread = threading.Thread(target=self.progress_files_thread)
        thread.start()

    def process_files_thread(self):
        all_extracted_items = []

        try:
            processor = DocumentProcessor()
            generator = OfferGenerator()

            total_files = len(self.selected_files)

            for i, file_path in enumerate(self.selected_files):
                filename = os.path.basename(file_path)

                self.after(0, self.lbl_status.configure, {"text": f"Обработка {i+1} из {total_files}: {filename}"})

                response_str = processor.process_document(file_path)

                try:
                    data = json.loads(response_str)
                    if isinstance(data, dict) and "error" in data:
                        print(f"Ошибка в файле {filename}: {data['error']}")
                        continue

                    all_extracted_items.extend(data)
                except json.JSONDecodeError:
                    print(f"Ошибка парсинга ответа для файна {filename}")

                progress_val = (i + 1) / total_files

                self.after(0, self.progress.set, progress_val)

            self.after(0, self.lbl_status.configure, {"text": "Сборка Excel файла..."})

            final_json_str = json.dumps(all_extracted_items)

            output_name = "Коммерческое предложение.xlsx"
            generator.generate(final_json_str, output_path=output_name)

            self.after(0, self.lbl_status.configure, {"text": f"Готово! Сохранено как {output_name}",
                                                      "text_color": "green"})
            self.after(0, messagebox.showinfo, "Успех",
                       f"Коммерческое предложение успешно создано!\nФайл: {output_name}")

        except Exception as e:
            self.after(0, self.lbl_status.configure, {"text": "Произошла ошибка", "text_color": "red"})
            self.after(0, messagebox.showerror, "Ошибка", str(e))

        finally:
            self.after(0, self.btn_select.configure, {"state": "normal"})
            self.after(0, self.lbl_files.configure, {"text": "Файлы не выбраны", "text_color": "gray"})
            self.after(0, self.progress.set, 0)
            self.selected_files = []

if __name__ == "__main__":
    app = TeplomirApp()
    app.mainloop()