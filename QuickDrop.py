import customtkinter as ctk
import requests
import threading
import time
import re
import random
import string
import json
import os
import sys
import math
import struct
import wave
import winsound
from tkinter import messagebox

SETTINGS_FILE = "temp_mail_settings.json"
DEFAULT_SETTINGS = {
    "theme": "System",
    "color_theme": "blue",
    "proxy_enabled": False,
    "proxy_address": "",
    "proxy_port": "",
    "last_custom_name": "",
    "copy_from": True,
    "copy_subject": True,
    "copy_body": True,
    "auto_show_last": True
}

ALLOWED_COLORS = ["blue", "green", "dark-blue"]

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            loaded = json.load(f)
        settings = DEFAULT_SETTINGS.copy()
        settings.update(loaded)
        if settings["color_theme"] not in ALLOWED_COLORS:
            settings["color_theme"] = "blue"
        return settings
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

class ConsoleWindow(ctk.CTkToplevel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("Консоль")
        self.geometry("600x400")
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self.textbox = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(size=12))
        self.textbox.pack(fill="both", expand=True, padx=10, pady=(10, 5))

        button_frame = ctk.CTkFrame(self)
        button_frame.pack(fill="x", padx=10, pady=(0, 10))

        clear_btn = ctk.CTkButton(button_frame, text="Очистить", command=self.clear)
        clear_btn.pack(side="right", padx=5)

        self.log("Консоль готова")

    def log(self, message):
        self.textbox.insert("end", message + "\n")
        self.textbox.see("end")

    def clear(self):
        self.textbox.delete("1.0", "end")

class TempMailApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.console_window = None

        self.settings = load_settings()
        self.proxy_dict = None
        self.apply_proxy()

        self.title("QuickDrop 2.1")
        self.geometry("680x780")
        self.minsize(600, 720)

        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme(self.settings["color_theme"])
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)

        self.token = None
        self.account_id = None
        self.email_address = ctk.StringVar(value="")
        self.available_domains = []
        self.selected_domain = ctk.StringVar(value="")

        self.messages_list = []
        self.unread_count = 0
        self.processed_ids = set()
        self.seen_contents = set()
        self.current_message_index = -1

        self.stop_polling = threading.Event()
        self.poll_thread = None

        self.status_var = ctk.StringVar(value="Готов к работе")
        self.is_generating = False
        self.input_locked = False

        self.build_ui()
        self.load_domains()
        self.toggle_detail_view()

    def apply_proxy(self):
        if self.settings.get("proxy_enabled"):
            addr = self.settings.get("proxy_address", "").strip()
            port = self.settings.get("proxy_port", "").strip()
            if addr and port:
                self.proxy_dict = {
                    "http": f"http://{addr}:{port}",
                    "https": f"http://{addr}:{port}"
                }
            else:
                self.proxy_dict = None
        else:
            self.proxy_dict = None

    def load_domains(self):
        try:
            resp = requests.get("https://api.mail.tm/domains", proxies=self.proxy_dict, timeout=10)
            resp.raise_for_status()
            self.available_domains = [d["domain"] for d in resp.json()["hydra:member"]]
            if self.available_domains:
                self.selected_domain.set(self.available_domains[0])
                self.log(f"Доступные домены: {', '.join(self.available_domains)}")
        except Exception as e:
            self.log(f"Ошибка загрузки доменов: {e}")
            self.available_domains = ["web-library.net"]
            self.selected_domain.set("web-library.net")

        if hasattr(self, 'domain_menu'):
            self.domain_menu.configure(values=self.available_domains)
            if self.available_domains and self.selected_domain.get() not in self.available_domains:
                self.selected_domain.set(self.available_domains[0])

    def build_ui(self):
        top_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="transparent")
        top_frame.pack(fill="x", padx=20, pady=(15, 5))

        title_label = ctk.CTkLabel(top_frame, text="QuickDrop 2.1",
                                   font=ctk.CTkFont(size=22, weight="bold"))
        title_label.pack(side="left", padx=10, pady=10)

        settings_btn = ctk.CTkButton(top_frame, text="⚙️", width=45, height=45,
                                     command=self.open_settings, corner_radius=8)
        settings_btn.pack(side="right", padx=10, pady=10)

        self.tabview = ctk.CTkTabview(self, corner_radius=12, command=self.on_tab_change)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=10)

        self.tab_main = self.tabview.add("Почта")
        self.tab_inbox = self.tabview.add("Входящие")

        self.inbox_tab_button = self.tabview._segmented_button._buttons_dict["Входящие"]

        self.build_main_tab()
        self.build_inbox_tab()

        status_frame = ctk.CTkFrame(self, corner_radius=8, height=35)
        status_frame.pack(fill="x", padx=20, pady=(0, 10))
        status_frame.pack_propagate(False)
        self.status_label = ctk.CTkLabel(status_frame, textvariable=self.status_var,
                                         anchor="w", font=ctk.CTkFont(size=13))
        self.status_label.pack(side="left", padx=15, pady=5)

    def on_tab_change(self):
        if self.tabview.get() == "Почта":
            self.toggle_detail_view()
            if self.settings.get("auto_show_last", True) and self.messages_list:
                self.display_message_details(self.messages_list[-1])

    def toggle_detail_view(self):
        if self.settings.get("auto_show_last", True) and self.messages_list:
            self.detail_frame.pack(fill="both", expand=True, padx=20, pady=10)
            self.info_frame.pack_forget()
        else:
            self.detail_frame.pack_forget()
            self.info_frame.pack(fill="both", expand=True, padx=20, pady=10)

    def build_main_tab(self):
        top_section = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        top_section.pack(fill="x", padx=20, pady=(15, 5))

        name_frame = ctk.CTkFrame(top_section, fg_color="transparent")
        name_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(name_frame, text="Имя ящика:", font=ctk.CTkFont(size=13)).pack(side="left")
        self.custom_name_entry = ctk.CTkEntry(name_frame, width=200, placeholder_text="оставьте пустым для случайного")
        self.custom_name_entry.pack(side="left", padx=10)
        last_name = self.settings.get("last_custom_name", "")
        if last_name:
            self.custom_name_entry.insert(0, last_name)
        self.custom_name_entry.bind("<Return>", lambda event: self.generate_email())

        domain_frame = ctk.CTkFrame(top_section, fg_color="transparent")
        domain_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(domain_frame, text="@", font=ctk.CTkFont(size=13)).pack(side="left")
        self.domain_menu = ctk.CTkOptionMenu(domain_frame, values=self.available_domains,
                                             variable=self.selected_domain, width=160)
        self.domain_menu.pack(side="left", padx=10)

        btn_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=10)

        self.generate_btn = ctk.CTkButton(btn_frame, text="Создать почту", height=42,
                                          font=ctk.CTkFont(size=14, weight="bold"),
                                          command=self.generate_email, corner_radius=8)
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.stop_btn = ctk.CTkButton(btn_frame, text="Остановить проверку", height=42,
                                      fg_color="gray", command=self.stop_checking, corner_radius=8)
        self.stop_btn.pack(side="right", fill="x", expand=True, padx=(5, 0))

        self.progress = ctk.CTkProgressBar(self.tab_main, mode="indeterminate", height=8, corner_radius=4)
        self.progress.pack(padx=20, pady=8, fill="x")
        self.progress.set(0)

        addr_frame = ctk.CTkFrame(self.tab_main, fg_color="transparent")
        addr_frame.pack(fill="x", padx=20, pady=5)

        self.email_entry = ctk.CTkEntry(addr_frame, textvariable=self.email_address,
                                        state="readonly", font=ctk.CTkFont(size=14), height=35)
        self.email_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(addr_frame, text="📋", width=45, height=35,
                      command=lambda: self.copy_to_clipboard(self.email_address.get()),
                      corner_radius=6).pack(side="right")

        # Информационная панель
        self.info_frame = ctk.CTkFrame(self.tab_main, corner_radius=10, fg_color="#2b2b2b")
        lines = [
            "                   Отправка писем с временной почты пока невозможна.",
            "                   Все письма принимаются с задержкой от 5 до 30 секунд.",
            "                   Большинство параметров можно изменить в настройках.",
            "                   Приложение тестируется, возможны небольшие баги."
        ]
        for line in lines:
            lbl = ctk.CTkLabel(self.info_frame, text=line, anchor="w",
                               font=ctk.CTkFont(size=13), text_color="#cccccc")
            lbl.pack(fill="x", padx=15, pady=4)

        # Детальная панель письма
        self.detail_frame = ctk.CTkFrame(self.tab_main, corner_radius=10)

        info_grid = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        info_grid.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(info_grid, text="От:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=0, column=0, sticky="w", padx=5)
        self.from_label = ctk.CTkLabel(info_grid, text="", font=ctk.CTkFont(size=13))
        self.from_label.grid(row=0, column=1, sticky="w", padx=5)

        ctk.CTkLabel(info_grid, text="Тема:", font=ctk.CTkFont(weight="bold", size=13)).grid(row=1, column=0, sticky="w", padx=5)
        self.subject_label = ctk.CTkLabel(info_grid, text="", font=ctk.CTkFont(size=13))
        self.subject_label.grid(row=1, column=1, sticky="w", padx=5)

        code_frame = ctk.CTkFrame(self.detail_frame, fg_color="transparent")
        code_frame.pack(fill="x", padx=15, pady=5)

        self.extracted_code = ctk.StringVar(value="")
        code_entry = ctk.CTkEntry(code_frame, textvariable=self.extracted_code,
                                  state="readonly", font=ctk.CTkFont(size=16, weight="bold"), justify="center", height=35)
        code_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(code_frame, text="📋", width=45, height=35,
                      command=lambda: self.copy_to_clipboard(self.extracted_code.get()),
                      corner_radius=6).pack(side="right")

        body_label = ctk.CTkLabel(self.detail_frame, text="Содержимое письма:", anchor="w", font=ctk.CTkFont(weight="bold", size=13))
        body_label.pack(fill="x", padx=15, pady=(10, 0))
        self.body_textbox = ctk.CTkTextbox(self.detail_frame, height=160, wrap="word", font=ctk.CTkFont(size=12))
        self.body_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.body_textbox.configure(state="disabled")

    def build_inbox_tab(self):
        main_inbox_frame = ctk.CTkFrame(self.tab_inbox)
        main_inbox_frame.pack(fill="both", expand=True, padx=15, pady=15)

        self.inbox_scroll = ctk.CTkScrollableFrame(main_inbox_frame, label_text="История писем", corner_radius=10)
        self.inbox_scroll.pack(fill="both", expand=True)

        self.inbox_detail_frame = ctk.CTkFrame(main_inbox_frame, corner_radius=10)
        self.inbox_detail_frame.pack_forget()

    def refresh_inbox_ui(self):
        for widget in self.inbox_scroll.winfo_children():
            widget.destroy()

        if not self.messages_list:
            ctk.CTkLabel(self.inbox_scroll, text="Писем пока нет", font=ctk.CTkFont(size=13)).pack(pady=20)
            return

        for i, msg in enumerate(reversed(self.messages_list)):
            orig_index = len(self.messages_list) - 1 - i
            is_unread = not msg.get("read", False)
            bg_color = "#2b2b2b" if is_unread else self.inbox_scroll.cget("fg_color")
            if ctk.get_appearance_mode() == "Light":
                bg_color = "#e8e8e8" if is_unread else "#f5f5f5"

            msg_frame = ctk.CTkFrame(self.inbox_scroll, corner_radius=8, fg_color=bg_color)
            msg_frame.pack(fill="x", pady=3, padx=5)

            from_addr = msg.get("from", "Неизвестно")
            subject = msg.get("subject", "Без темы")
            date_str = msg.get("date", "")
            if len(date_str) > 19:
                date_str = date_str[:19]

            text_line = f"{from_addr} | {subject} | {date_str}"
            lbl = ctk.CTkLabel(msg_frame, text=text_line, anchor="w", font=ctk.CTkFont(size=12))
            lbl.pack(side="left", fill="x", expand=True, padx=10, pady=6)

            view_btn = ctk.CTkButton(msg_frame, text="👁", width=35, height=28,
                                     command=lambda idx=orig_index: self.show_inbox_detail(idx),
                                     corner_radius=6)
            view_btn.pack(side="right", padx=8, pady=4)

            lbl.bind("<Button-1>", lambda e, idx=orig_index: self.show_inbox_detail(idx))
            msg_frame.bind("<Button-1>", lambda e, idx=orig_index: self.show_inbox_detail(idx))

    def show_inbox_detail(self, index):
        if 0 <= index < len(self.messages_list):
            msg = self.messages_list[index]
            if not msg.get("read", False):
                msg["read"] = True
                self.unread_count = max(0, self.unread_count - 1)
                self.update_inbox_badge()
                self.refresh_inbox_ui()

            self.status_var.set(f"Просмотр письма от {msg.get('from', '')}")
            self.current_message_index = index
            self.inbox_scroll.pack_forget()
            self.build_inbox_detail_view(msg)
            self.inbox_detail_frame.pack(fill="both", expand=True)

    def build_inbox_detail_view(self, msg):
        for widget in self.inbox_detail_frame.winfo_children():
            widget.destroy()

        ctk.CTkLabel(self.inbox_detail_frame, text="От: " + msg.get("from", ""),
                     font=ctk.CTkFont(weight="bold", size=13)).pack(anchor="w", padx=15, pady=(10, 5))
        ctk.CTkLabel(self.inbox_detail_frame, text="Тема: " + msg.get("subject", ""),
                     font=ctk.CTkFont(weight="bold", size=13)).pack(anchor="w", padx=15, pady=5)

        body = msg.get("body", "")
        code = self.extract_verification_code(body)
        code_text = code if code else ""
        ctk.CTkLabel(self.inbox_detail_frame, text="Извлечённый код: " + code_text,
                     font=ctk.CTkFont(size=13)).pack(anchor="w", padx=15, pady=5)
        if code:
            ctk.CTkButton(self.inbox_detail_frame, text="📋 Код", width=60,
                          command=lambda: self.copy_to_clipboard(code),
                          corner_radius=6).pack(anchor="w", padx=15, pady=2)

        body_textbox = ctk.CTkTextbox(self.inbox_detail_frame, height=160, wrap="word", font=ctk.CTkFont(size=12))
        body_textbox.insert("1.0", body)
        body_textbox.configure(state="disabled")
        body_textbox.pack(fill="both", expand=True, padx=15, pady=5)

        btn_frame = ctk.CTkFrame(self.inbox_detail_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(5, 10))
        ctk.CTkButton(btn_frame, text="Назад к списку", command=self.hide_inbox_detail, corner_radius=6).pack(side="left")
        ctk.CTkButton(btn_frame, text="Копировать", command=lambda: self.copy_selected_parts(msg), corner_radius=6).pack(side="right", padx=5)

        note_label = ctk.CTkLabel(self.inbox_detail_frame, text="Что копируется, можно настроить в настройках",
                                  font=ctk.CTkFont(size=9), text_color="gray")
        note_label.pack(pady=(0, 5))

    def hide_inbox_detail(self):
        self.inbox_detail_frame.pack_forget()
        self.inbox_scroll.pack(fill="both", expand=True)
        self.update_status_after_view()
        self.update_inbox_badge()
        self.refresh_inbox_ui()

    def update_status_after_view(self):
        if self.unread_count > 0:
            self.status_var.set(f"Ожидание писем... ({self.unread_count} новых)")
        else:
            self.status_var.set("Ожидание писем...")

    def copy_selected_parts(self, msg):
        parts = []
        if self.settings.get("copy_from", True):
            parts.append("От: " + msg.get("from", ""))
        if self.settings.get("copy_subject", True):
            parts.append("Тема: " + msg.get("subject", ""))
        if self.settings.get("copy_body", True):
            parts.append("Сообщение: " + msg.get("body", ""))
        if parts:
            self.copy_to_clipboard("\n".join(parts))

    def display_message_details(self, msg):
        self.from_label.configure(text=msg.get("from", ""))
        self.subject_label.configure(text=msg.get("subject", ""))
        body = msg.get("body", "")
        self.body_textbox.configure(state="normal")
        self.body_textbox.delete("1.0", "end")
        self.body_textbox.insert("1.0", body)
        self.body_textbox.configure(state="disabled")
        code = self.extract_verification_code(body)
        self.extracted_code.set(code if code else "")

    def update_inbox_badge(self):
        text = "Входящие"
        if self.unread_count > 0:
            text += f" ({self.unread_count})"
        self.inbox_tab_button.configure(text=text)

    def mark_all_read(self):
        for msg in self.messages_list:
            msg["read"] = True
        self.unread_count = 0
        self.update_inbox_badge()
        self.refresh_inbox_ui()
        self.status_var.set("Ожидание писем...")
        self.log("Все письма отмечены как прочитанные")

    def generate_email(self):
        if self.is_generating or self.input_locked:
            return
        custom_name = self.custom_name_entry.get().strip()
        if custom_name:
            if not re.match(r'^[a-zA-Z0-9]+$', custom_name):
                answer = messagebox.askyesno("Недопустимое имя",
                                             "Имя содержит недопустимые символы (только латиница и цифры). Сгенерировать случайное имя?")
                if answer:
                    self.custom_name_entry.delete(0, "end")
                else:
                    return

        self.is_generating = True
        self.input_locked = True
        self.custom_name_entry.configure(state="disabled")
        self.generate_btn.configure(state="disabled")
        self.settings["last_custom_name"] = custom_name
        save_settings(self.settings)

        self.status_var.set("Создание почты...")
        self.progress.start()
        threading.Thread(target=self._create_account, args=(custom_name,), daemon=True).start()

    def _create_account(self, custom_name=""):
        try:
            domain = self.selected_domain.get()
            if not domain:
                domain = self.available_domains[0] if self.available_domains else "web-library.net"

            if custom_name and re.match(r'^[a-zA-Z0-9]+$', custom_name):
                username = custom_name
            else:
                username = "user" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

            password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            address = f"{username}@{domain}"

            account_data = {"address": address, "password": password}
            resp = self._api_post("https://api.mail.tm/accounts", account_data)

            if resp.status_code == 201:
                account = resp.json()
                self.account_id = account["id"]
            elif resp.status_code == 422:
                answer = self._ask_name_conflict()
                if answer:
                    username = "user" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                    address = f"{username}@{domain}"
                    account_data = {"address": address, "password": password}
                    resp = self._api_post("https://api.mail.tm/accounts", account_data)
                    if resp.status_code != 201:
                        raise Exception(f"Не удалось создать аккаунт (ошибка {resp.status_code})")
                    account = resp.json()
                    self.account_id = account["id"]
                else:
                    self.status_var.set("Имя занято, введите новое")
                    self.after(0, self.unlock_inputs)
                    return
            else:
                raise Exception(f"Ошибка создания аккаунта: {resp.status_code}")

            resp = self._api_post("https://api.mail.tm/token", account_data)
            resp.raise_for_status()
            self.token = resp.json()["token"]

            self.email_address.set(address)
            self.status_var.set(f"Почта {address} готова. Ожидание писем...")
            self.log(f"Создан адрес: {address}")

            self.start_polling()
            self.after(0, self.generation_success)

        except Exception as e:
            self.status_var.set(f"Ошибка: {str(e)}")
            self.log(f"Ошибка создания: {str(e)}")
            self.after(0, self.unlock_inputs)

    def _api_post(self, url, json_data, max_retries=3):
        for attempt in range(max_retries):
            try:
                resp = requests.post(url, json=json_data, proxies=self.proxy_dict, timeout=10)
                if resp.status_code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                return resp
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise e
        return resp

    def _ask_name_conflict(self):
        self.answer_event = threading.Event()
        self.answer_value = False
        self.after(0, self._show_name_conflict_dialog)
        self.answer_event.wait()
        return self.answer_value

    def _show_name_conflict_dialog(self):
        result = messagebox.askyesno("Имя занято", "Это имя уже используется. Сгенерировать случайное имя?")
        self.answer_value = result
        self.answer_event.set()

    def generation_success(self):
        self.progress.stop()
        self.generate_btn.configure(state="normal")
        self.input_locked = True
        self.custom_name_entry.configure(state="disabled")

    def unlock_inputs(self):
        self.is_generating = False
        self.input_locked = False
        self.progress.stop()
        self.generate_btn.configure(state="normal")
        self.custom_name_entry.configure(state="normal")

    def start_polling(self):
        self.stop_polling.clear()
        self.progress.start()
        self.input_locked = True
        self.custom_name_entry.configure(state="disabled")
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()
        self.stop_btn.configure(state="normal")

    def stop_checking(self):
        self.stop_polling.set()
        self.progress.stop()
        self.status_var.set("Проверка остановлена")
        self.unlock_inputs()
        self.log("Проверка почты остановлена пользователем")

    def _poll_loop(self):
        while not self.stop_polling.is_set():
            try:
                headers = {"Authorization": f"Bearer {self.token}"}
                resp = requests.get("https://api.mail.tm/messages", headers=headers,
                                    proxies=self.proxy_dict, timeout=10)
                if resp.status_code == 429:
                    time.sleep(10)
                    continue
                resp.raise_for_status()
                messages = resp.json()["hydra:member"]

                for msg_summary in messages:
                    msg_id = msg_summary["id"]
                    if msg_id not in self.processed_ids:
                        resp_msg = requests.get(f"https://api.mail.tm/messages/{msg_id}",
                                                headers=headers, proxies=self.proxy_dict, timeout=10)
                        if resp_msg.status_code == 429:
                            time.sleep(10)
                            continue
                        resp_msg.raise_for_status()
                        full_msg = resp_msg.json()

                        text_part = full_msg.get("text")
                        html_part = full_msg.get("html")
                        if isinstance(text_part, list):
                            text_part = " ".join(text_part)
                        if isinstance(html_part, list):
                            html_part = " ".join(html_part)
                        body = text_part or html_part or ""
                        sender = full_msg["from"]["address"]
                        content_key = (sender, body)
                        if content_key in self.seen_contents:
                            self.processed_ids.add(msg_id)
                            continue

                        self.seen_contents.add(content_key)
                        new_msg = {
                            "id": msg_id,
                            "from": sender,
                            "subject": full_msg.get("subject", "Без темы"),
                            "body": body,
                            "date": full_msg.get("createdAt", ""),
                            "read": False
                        }
                        self.messages_list.append(new_msg)
                        self.processed_ids.add(msg_id)
                        self.unread_count += 1
                        self.after(0, self.on_new_message)
                time.sleep(5)
            except Exception as e:
                self.log(f"Ошибка опроса: {e}")
                time.sleep(5)

        self.after(0, lambda: self.progress.stop())

    def on_new_message(self):
        self.refresh_inbox_ui()
        self.update_inbox_badge()
        self.status_var.set(f"Новых писем: {self.unread_count}")
        if self.settings.get("auto_show_last", True) and self.messages_list:
            self.display_message_details(self.messages_list[-1])
            self.detail_frame.pack(fill="both", expand=True, padx=20, pady=10)
            self.info_frame.pack_forget()
        self.play_notification_sound()

    def play_notification_sound(self):
        try:
            volume = 0.5
            duration = 0.15
            freq = 800
            sample_rate = 22050
            num_samples = int(sample_rate * duration)
            samples = []
            for i in range(num_samples):
                t = i / sample_rate
                envelope = max(0, 1 - i / num_samples)
                value = int(32767 * volume * envelope * math.sin(2 * math.pi * freq * t))
                samples.append(struct.pack('<h', value))
            wav_data = io.BytesIO()
            with wave.open(wav_data, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(b''.join(samples))
            winsound.PlaySound(wav_data.getvalue(), winsound.SND_MEMORY)
        except Exception:
            pass

    def extract_verification_code(self, text):
        if not isinstance(text, str):
            text = " ".join(text) if isinstance(text, list) else str(text)
        patterns = [r'\b(\d{4,8})\b', r'\b([A-Z0-9]{6,8})\b']
        for p in patterns:
            match = re.search(p, text)
            if match:
                return match.group(1)
        return None

    def copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log(f"Скопировано: {text}")

    def open_settings(self):
        settings_win = ctk.CTkToplevel(self)
        settings_win.title("Настройки QuickDrop 2.1")
        settings_win.geometry("440x560")
        settings_win.grab_set()
        settings_win.resizable(False, False)

        scroll_frame = ctk.CTkScrollableFrame(settings_win, label_text="", corner_radius=10)
        scroll_frame.pack(fill="both", expand=True, padx=15, pady=15)

        ctk.CTkLabel(scroll_frame, text="Тема оформления:", font=ctk.CTkFont(weight="bold", size=13)).pack(pady=(10, 5))
        theme_var = ctk.StringVar(value=self.settings["theme"])
        ctk.CTkOptionMenu(scroll_frame, values=["System", "Light", "Dark"],
                          variable=theme_var, width=200,
                          command=lambda val: self.change_theme(val)).pack(pady=5)

        ctk.CTkLabel(scroll_frame, text="Цветовая схема (требует перезапуска):",
                     font=ctk.CTkFont(weight="bold", size=13)).pack(pady=(15, 5))
        color_var = ctk.StringVar(value=self.settings["color_theme"])
        color_menu = ctk.CTkOptionMenu(scroll_frame, values=ALLOWED_COLORS, variable=color_var, width=200)
        color_menu.pack(pady=5)

        ctk.CTkLabel(scroll_frame, text="Прокси", font=ctk.CTkFont(weight="bold", size=13)).pack(pady=(15, 5))
        proxy_frame = ctk.CTkFrame(scroll_frame)
        proxy_frame.pack(fill="x", pady=5)

        proxy_enabled_var = ctk.BooleanVar(value=self.settings["proxy_enabled"])
        ctk.CTkCheckBox(proxy_frame, text="Использовать HTTP-прокси",
                        variable=proxy_enabled_var).pack(anchor="w", pady=5)

        addr_frame = ctk.CTkFrame(proxy_frame, fg_color="transparent")
        addr_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(addr_frame, text="Адрес:").pack(side="left")
        addr_entry = ctk.CTkEntry(addr_frame, width=150)
        addr_entry.insert(0, self.settings.get("proxy_address", ""))
        addr_entry.pack(side="left", padx=5)

        port_frame = ctk.CTkFrame(proxy_frame, fg_color="transparent")
        port_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(port_frame, text="Порт:").pack(side="left")
        port_entry = ctk.CTkEntry(port_frame, width=80)
        port_entry.insert(0, self.settings.get("proxy_port", ""))
        port_entry.pack(side="left", padx=5)

        ctk.CTkLabel(scroll_frame, text="Копирование при просмотре",
                     font=ctk.CTkFont(weight="bold", size=13)).pack(pady=(15, 5))
        copy_from_var = ctk.BooleanVar(value=self.settings.get("copy_from", True))
        copy_subj_var = ctk.BooleanVar(value=self.settings.get("copy_subject", True))
        copy_body_var = ctk.BooleanVar(value=self.settings.get("copy_body", True))
        ctk.CTkCheckBox(scroll_frame, text="Копировать адрес отправителя", variable=copy_from_var).pack(anchor="w", padx=20)
        ctk.CTkCheckBox(scroll_frame, text="Копировать тему", variable=copy_subj_var).pack(anchor="w", padx=20)
        ctk.CTkCheckBox(scroll_frame, text="Копировать текст письма", variable=copy_body_var).pack(anchor="w", padx=20)

        ctk.CTkLabel(scroll_frame, text="Отображение", font=ctk.CTkFont(weight="bold", size=13)).pack(pady=(15, 5))
        auto_show_var = ctk.BooleanVar(value=self.settings.get("auto_show_last", True))
        ctk.CTkCheckBox(scroll_frame, text="Автоматически показывать последнее письмо на главной",
                        variable=auto_show_var).pack(anchor="w", padx=20)

        def save():
            old_color = self.settings["color_theme"]
            self.settings["theme"] = theme_var.get()
            self.settings["color_theme"] = color_var.get()
            self.settings["proxy_enabled"] = proxy_enabled_var.get()
            self.settings["proxy_address"] = addr_entry.get().strip()
            self.settings["proxy_port"] = port_entry.get().strip()
            self.settings["copy_from"] = copy_from_var.get()
            self.settings["copy_subject"] = copy_subj_var.get()
            self.settings["copy_body"] = copy_body_var.get()
            self.settings["auto_show_last"] = auto_show_var.get()
            self.apply_proxy()
            save_settings(self.settings)
            ctk.set_appearance_mode(self.settings["theme"])
            if self.settings["color_theme"] != old_color:
                if messagebox.askyesno("Перезапуск", "Цвет изменится после перезапуска. Перезапустить сейчас?"):
                    settings_win.destroy()
                    self.restart_app()
                else:
                    messagebox.showinfo("Информация", "Новый цвет будет применён при следующем запуске.")
            self.log("Настройки обновлены")
            self.toggle_detail_view()
            settings_win.destroy()

        ctk.CTkButton(scroll_frame, text="Сохранить", command=save, corner_radius=8).pack(pady=10)
        ctk.CTkButton(scroll_frame, text="Открыть консоль", command=self.open_console, corner_radius=8).pack(pady=5)

    def restart_app(self):
        self.stop_polling.set()
        self.destroy()
        os.execv(sys.executable, ['python'] + sys.argv)

    def change_theme(self, theme):
        ctk.set_appearance_mode(theme)
        self.settings["theme"] = theme

    def open_console(self):
        if self.console_window is None or not self.console_window.winfo_exists():
            self.console_window = ConsoleWindow(self)
        self.console_window.deiconify()
        self.console_window.lift()

    def log(self, message):
        if hasattr(self, 'console_window') and self.console_window is not None and self.console_window.winfo_exists():
            self.console_window.log(message)
        else:
            print(f"[LOG] {message}")

    def on_closing(self):
        self.stop_polling.set()
        if self.token and self.account_id:
            try:
                headers = {"Authorization": f"Bearer {self.token}"}
                requests.delete(f"https://api.mail.tm/accounts/{self.account_id}",
                                headers=headers, proxies=self.proxy_dict, timeout=5)
                self.log("Аккаунт удалён")
            except:
                pass
        self.destroy()

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print(error_msg)
    if hasattr(TempMailApp, '_instance') and TempMailApp._instance.console_window:
        TempMailApp._instance.log(error_msg)
    else:
        print(error_msg)

sys.excepthook = handle_exception

if __name__ == "__main__":
    app = TempMailApp()
    TempMailApp._instance = app
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()