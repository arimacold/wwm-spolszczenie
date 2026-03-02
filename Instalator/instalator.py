import os
import winreg
import requests
import stat
import webbrowser
import time
import winsound  # Biblioteka do dźwięków systemowych
import customtkinter as ctk
from tkinter import messagebox, filedialog

# --- KONFIGURACJA ---
GITHUB_USER = "arimacold" 
REPO_NAME = "wwm-spolszczenie"
RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{REPO_NAME}/main/"
STEAM_GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3619908590"
COFFEE_URL = "https://buycoffee.to/arima"

class WWMInstaller(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Where Winds Meet - Instalator")
        self.geometry("600x680")
        ctk.set_appearance_mode("dark")
        
        self.game_path = self.find_game_path()
        self.lang_var = ctk.StringVar(value="en")
        
        self.setup_ui()
        self.update_status()

    def find_game_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
            path = os.path.join(steam_path, "steamapps", "common", "Where Winds Meet")
            return path if os.path.exists(path) else None
        except: return None

    def browse_path(self):
        path = filedialog.askdirectory(title="Wskaż folder główny gry Where Winds Meet")
        if path:
            self.game_path = path
            self.update_status()

    def setup_ui(self):
        # Nagłówek
        ctk.CTkLabel(self, text="Instalator spolszczenia do gry\nWhere Winds Meet", 
                     font=("Segoe UI", 26, "bold")).pack(pady=(30, 10))
        
        ctk.CTkFrame(self, height=2, fg_color="#3b8ed0", width=300).pack(pady=5)

        # Wybór języka
        self.lang_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        self.lang_frame.pack(pady=20, padx=40, fill="x")
        ctk.CTkLabel(self.lang_frame, text="Wybierz język gry do podmiany:", font=("Segoe UI", 13)).pack(pady=5)
        
        self.rb_en = ctk.CTkRadioButton(self.lang_frame, text="Angielski (EN)", 
                                        variable=self.lang_var, value="en", 
                                        border_color="#555555", fg_color="#3b8ed0", 
                                        hover_color="#5fa3d9", border_width_checked=6)
        self.rb_en.pack(side="left", padx=60, pady=15)
        
        self.rb_de = ctk.CTkRadioButton(self.lang_frame, text="Niemiecki (DE)", 
                                        variable=self.lang_var, value="de", 
                                        border_color="#555555", fg_color="#3b8ed0", 
                                        hover_color="#5fa3d9", border_width_checked=6)
        self.rb_de.pack(side="right", padx=60, pady=15)

        # Sekcja statusu wersji
        self.status_box = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        self.status_box.pack(pady=10, padx=40, fill="x")
        
        self.local_ver_label = ctk.CTkLabel(self.status_box, text="Twoja wersja: Sprawdzanie...", font=("Segoe UI", 15, "bold"))
        self.local_ver_label.pack(pady=(12, 2))
        
        self.server_ver_label = ctk.CTkLabel(self.status_box, text="Wersja na serwerze: ...", font=("Segoe UI", 12))
        self.server_ver_label.pack(pady=(0, 12))

        # Pasek postępu - Poprawione centrowanie
        self.progress_container = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_container.pack(pady=(15, 0), padx=60, fill="x") # Zwiększony margines boczny dla lepszego balansu
        
        self.progress = ctk.CTkProgressBar(self.progress_container, height=14, fg_color="#1e1e1e", progress_color="#3b8ed0")
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True)
        
        self.percentage_label = ctk.CTkLabel(self.progress_container, text="0%", font=("Segoe UI", 12, "bold"), width=50)
        self.percentage_label.pack(side="right", padx=(10, 0))

        # Status szczegółowy
        self.detail_label = ctk.CTkLabel(self, text="Oczekiwanie na start...", font=("Segoe UI", 11), text_color="#888888")
        self.detail_label.pack(pady=(2, 10))

        # Przyciski akcji
        self.btn_install = ctk.CTkButton(self, text="ZAINSTALUJ / AKTUALIZUJ", command=self.run_install, 
                                         height=55, font=("Segoe UI", 18, "bold"), fg_color="#3b8ed0", hover_color="#2c6e9e")
        self.btn_install.pack(pady=5, padx=60, fill="x")

        self.btn_restore = ctk.CTkButton(self, text="PRZYWRÓĆ ORYGINALNE TŁUMACZENIE", command=self.run_restore, 
                                         height=40, font=("Segoe UI", 13, "bold"), fg_color="#3d3d3d", hover_color="#4d4d4d")
        self.btn_restore.pack(pady=5, padx=60, fill="x")

        # Narzędzia
        self.tool_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.tool_frame.pack(pady=15)
        ctk.CTkButton(self.tool_frame, text="📁 Zmień folder", width=110, command=self.browse_path, fg_color="transparent", border_width=1).pack(side="left", padx=8)
        ctk.CTkButton(self.tool_frame, text="🔍 Otwórz folder", width=110, command=lambda: os.startfile(self.game_path) if self.game_path else None, fg_color="transparent", border_width=1).pack(side="left", padx=8)

        # Stopka
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(side="bottom", fill="x", pady=20)
        ctk.CTkButton(self.footer, text="📖 Poradnik Steam", command=lambda: webbrowser.open(STEAM_GUIDE_URL), fg_color="#171a21", hover_color="#2a2e38").pack(side="left", padx=30)
        ctk.CTkButton(self.footer, text="☕ Wesprzyj projekt", command=lambda: webbrowser.open(COFFEE_URL), fg_color="#4d4d4d", hover_color="#5d5d5d").pack(side="right", padx=30)

    def update_status(self):
        v_path = os.path.join(self.game_path, "Package", "HD", "oversea", "locale", "polish_version.txt") if self.game_path else None
        local_v = "Brak"
        if v_path and os.path.exists(v_path):
            with open(v_path, "r") as f: local_v = f.read().strip()

        try:
            r = requests.get(f"{RAW_URL}version.txt", timeout=5)
            server_v = r.text.strip() if r.status_code == 200 else "???"
        except:
            server_v = "Błąd połączenia"

        if not self.game_path:
            self.local_ver_label.configure(text="NIE ODNALEZIONO GRY!", text_color="#e74c3c")
        elif local_v == "Brak":
            self.local_ver_label.configure(text="STATUS: BRAK SPOLSZCZENIA!", text_color="#ff4d4d")
        elif server_v > local_v:
            self.local_ver_label.configure(text=f"DOSTĘPNA AKTUALIZACJA (Masz: {local_v})", text_color="#f1c40f")
        else:
            self.local_ver_label.configure(text=f"TŁUMACZENIE AKTUALNE ({local_v})", text_color="#2ecc71")

        self.server_ver_label.configure(text=f"Najnowsza wersja na serwerze: {server_v}")

    def show_finish_screen(self):
        # Dźwięk powiadomienia Windows
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        
        finish_win = ctk.CTkToplevel(self)
        finish_win.title("Instalacja zakończona")
        finish_win.geometry("450x300")
        finish_win.attributes("-topmost", True)
        finish_win.resizable(False, False)
        
        ctk.CTkLabel(finish_win, text="Sukces! 🎉", font=("Segoe UI", 22, "bold")).pack(pady=20)
        ctk.CTkLabel(finish_win, text="Dziękuję za zainstalowanie spolszczenia.\n\nJeżeli podoba ci się projekt możesz go wesprzeć na:", 
                     font=("Segoe UI", 12), justify="center").pack(pady=10)
        
        ctk.CTkButton(finish_win, text="☕ Postaw kawę dla Arima", fg_color="#FF813F", text_color="black", font=("Segoe UI", 14, "bold"),
                       command=lambda: webbrowser.open(COFFEE_URL)).pack(pady=20)

    def set_progress(self, val, detail_text):
        self.progress.set(val)
        self.percentage_label.configure(text=f"{int(val * 100)}%")
        self.detail_label.configure(text=detail_text)
        self.update()

    def install_logic(self, mode="files"):
        lang = self.lang_var.get()
        if not self.game_path:
            messagebox.showerror("Błąd", "Wskaż folder gry przed instalacją!")
            return

        p1 = os.path.join(self.game_path, "Package", "HD", "oversea", "locale")
        p2 = os.path.join(self.game_path, "LocalData", "Patch", "HD", "oversea", "locale")
        files = [f"translate_words_map_{lang}", f"translate_words_map_{lang}_diff"]
        
        self.set_progress(0.05, "Inicjalizacja połączenia...")

        try:
            for i, f_name in enumerate(files):
                sub = "orginal" if mode == "orginal" else lang
                self.set_progress(0.1 + (i * 0.4), f"Pobieranie: {f_name}...")
                res = requests.get(f"{RAW_URL}files/{sub}/{f_name}")
                
                if res.status_code == 200:
                    t1 = os.path.join(p1, f_name)
                    if os.path.exists(t1): os.chmod(t1, stat.S_IWRITE)
                    with open(t1, "wb") as f: f.write(res.content)

                    if "_diff" in f_name:
                        self.set_progress(0.4 + (i * 0.4), "Instalowanie poprawki...")
                        t2 = os.path.join(p2, f_name)
                        if os.path.exists(t2): os.chmod(t2, stat.S_IWRITE)
                        with open(t2, "wb") as f: f.write(res.content)
                        if mode == "files": os.chmod(t2, stat.S_IREAD)

            if mode == "files":
                rv = requests.get(f"{RAW_URL}version.txt")
                with open(os.path.join(p1, "polish_version.txt"), "w") as f: f.write(rv.text.strip())
                self.set_progress(1.0, "Instalacja zakończona!")
                self.update_status()
                self.show_finish_screen()
            else:
                v_file = os.path.join(p1, "polish_version.txt")
                if os.path.exists(v_file): os.remove(v_file)
                self.set_progress(1.0, "Oryginał przywrócony!")
                self.update_status()
                messagebox.showinfo("Sukces", "Przywrócono oryginalne pliki gry.")
                
        except Exception as e:
            self.set_progress(0, "Wystąpił błąd.")
            messagebox.showerror("Błąd", str(e))

    def run_install(self): self.install_logic("files")
    def run_restore(self): self.install_logic("orginal")

if __name__ == "__main__":
    app = WWMInstaller()
    app.mainloop()