import os
import winreg
import requests
import stat
import webbrowser
import time
import winsound
import customtkinter as ctk
from tkinter import messagebox, filedialog

GITHUB_USER = "arimacold" 
REPO_NAME = "wwm-spolszczenie"
RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{REPO_NAME}/main/"
STEAM_GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3619908590"
COFFEE_URL = "https://buycoffee.to/arima"

class WWMInstaller(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Where Winds Meet - Instalator")
        self.geometry("600x780")
        ctk.set_appearance_mode("dark")
        
        self.version_var = ctk.StringVar(value="steam")
        self.lang_var = ctk.StringVar(value="en")
        self.game_path = self.find_game_path()
        
        self.setup_ui()
        self.update_status()

    def find_game_path(self):
        v = self.version_var.get()
        path = None
        if v == "steam":
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
                steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
                path = os.path.join(steam_path, "steamapps", "common", "Where Winds Meet")
            except: pass
        else:
            potential = [
                r"C:\Program Files\wwm\wwm_standard",
                r"C:\Program Files\wwm\wwm_lite",
                r"C:\Program Files (x86)\wwm\wwm_standard",
                r"C:\Program Files (x86)\wwm\wwm_lite",
                r"C:\NetEase\WWM\wwm_standard",
                r"C:\NetEase\WWM\wwm_lite",
                r"C:\NetEase Games\WWM\wwm_standard",
                r"C:\NetEase Games\WWM\wwm_lite",
                r"C:\Games\Where Winds Meet\wwm_standard",
                r"C:\Games\Where Winds Meet\wwm_lite",
                r"D:\Games\Where Winds Meet\wwm_standard",
                r"D:\Games\Where Winds Meet\wwm_lite",
                r"E:\Games\Where Winds Meet\wwm_standard",
                r"E:\Games\Where Winds Meet\wwm_lite",
                r"C:\WWM\wwm_standard",
                r"C:\WWM\wwm_lite",
                r"D:\WWM\wwm_standard",
                r"D:\WWM\wwm_lite",
                r"C:\Program Files\Epic Games\WhereWindsMeet\wwm_standard",
                r"C:\Program Files (x86)\Epic Games\WhereWindsMeet\wwm_standard",
                r"D:\Epic Games\WhereWindsMeet\wwm_standard",
                r"C:\Users\Public\Games\Where Winds Meet\wwm_standard",
                r"C:\Users\Public\Games\Where Winds Meet\wwm_lite"
            ]
            for p in potential:
                if os.path.exists(p): 
                    path = p
                    break
        
        return os.path.abspath(os.path.normpath(path)) if path and os.path.exists(path) else None

    def refresh_path(self):
        self.game_path = self.find_game_path()
        self.update_status()

    def browse_path(self):
        path = filedialog.askdirectory(title="Wskaż folder główny gry Where Winds Meet")
        if path:
            self.game_path = os.path.abspath(os.path.normpath(path))
            self.update_status()

    def setup_ui(self):
        ctk.CTkLabel(self, text="Instalator spolszczenia do gry\nWhere Winds Meet", 
                      font=("Segoe UI", 26, "bold")).pack(pady=(30, 10))
        
        ctk.CTkFrame(self, height=2, fg_color="#3b8ed0", width=300).pack(pady=5)

        self.plat_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        self.plat_frame.pack(pady=10, padx=40, fill="x")
        ctk.CTkLabel(self.plat_frame, text="Wybierz wersję gry:", font=("Segoe UI", 13)).pack(pady=5)
        
        self.rb_steam = ctk.CTkRadioButton(self.plat_frame, text="Steam", variable=self.version_var, value="steam", 
                            command=self.refresh_path, border_color="#555555", fg_color="#3b8ed0", 
                            hover_color="#5fa3d9", border_width_checked=6)
        self.rb_steam.pack(side="left", padx=60, pady=10)
        self.rb_launcher = ctk.CTkRadioButton(self.plat_frame, text="Launcher / Epic", variable=self.version_var, value="launcher", 
                            command=self.refresh_path, border_color="#555555", fg_color="#3b8ed0", 
                            hover_color="#5fa3d9", border_width_checked=6)
        self.rb_launcher.pack(side="right", padx=60, pady=10)

        self.lang_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        self.lang_frame.pack(pady=10, padx=40, fill="x")
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

        self.status_box = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        self.status_box.pack(pady=10, padx=40, fill="x")
        self.local_ver_label = ctk.CTkLabel(self.status_box, text="Twoja wersja: Sprawdzanie...", font=("Segoe UI", 15, "bold"))
        self.local_ver_label.pack(pady=(12, 2))
        self.server_ver_label = ctk.CTkLabel(self.status_box, text="Wersja na serwerze: ...", font=("Segoe UI", 12))
        self.server_ver_label.pack(pady=(0, 12))

        self.progress_container = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_container.pack(pady=(15, 0), padx=60, fill="x")
        self.progress = ctk.CTkProgressBar(self.progress_container, height=14, fg_color="#1e1e1e", progress_color="#3b8ed0")
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.percentage_label = ctk.CTkLabel(self.progress_container, text="0%", font=("Segoe UI", 12, "bold"), width=50)
        self.percentage_label.pack(side="right", padx=(10, 0))

        self.detail_label = ctk.CTkLabel(self, text="Oczekiwanie na start...", font=("Segoe UI", 11), text_color="#888888")
        self.detail_label.pack(pady=(2, 10))

        self.btn_install = ctk.CTkButton(self, text="ZAINSTALUJ / AKTUALIZUJ", command=self.run_install, 
                                          height=55, font=("Segoe UI", 18, "bold"), fg_color="#3b8ed0", hover_color="#2c6e9e")
        self.btn_install.pack(pady=5, padx=60, fill="x")

        self.btn_restore = ctk.CTkButton(self, text="PRZYWRÓĆ ORYGINALNE TŁUMACZENIE", command=self.run_restore, 
                                          height=40, font=("Segoe UI", 13, "bold"), fg_color="#3d3d3d", hover_color="#4d4d4d")
        self.btn_restore.pack(pady=5, padx=60, fill="x")

        self.tool_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.tool_frame.pack(pady=15)
        ctk.CTkButton(self.tool_frame, text="📁 Zmień folder", width=110, command=self.browse_path, fg_color="transparent", border_width=1).pack(side="left", padx=8)
        ctk.CTkButton(self.tool_frame, text="🔍 Otwórz folder", width=110, command=lambda: os.startfile(self.game_path) if self.game_path else None, fg_color="transparent", border_width=1).pack(side="left", padx=8)

        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(side="bottom", fill="x", pady=20)
        ctk.CTkButton(self.footer, text="📖 Poradnik Steam", command=lambda: webbrowser.open(STEAM_GUIDE_URL), fg_color="#171a21", hover_color="#2a2e38").pack(side="left", padx=30)
        ctk.CTkButton(self.footer, text="☕ Wesprzyj projekt", command=lambda: webbrowser.open(COFFEE_URL), fg_color="#4d4d4d", hover_color="#5d5d5d").pack(side="right", padx=30)

    def update_status(self):
        if not self.game_path:
            self.local_ver_label.configure(text="NIE ODNALEZIONO GRY!", text_color="#e74c3c")
            return
        
        v_path = os.path.join(self.game_path, "Package", "HD", "oversea", "locale", "polish_version.txt")
        local_v = "Brak"
        if os.path.exists(v_path):
            with open(v_path, "r") as f: local_v = f.read().strip()
        
        try:
            r = requests.get(f"{RAW_URL}version.txt", timeout=5)
            server_v = r.text.strip() if r.status_code == 200 else "???"
        except: server_v = "Błąd połączenia"

        if local_v == "Brak":
            self.local_ver_label.configure(text="STATUS: BRAK SPOLSZCZENIA!", text_color="#ff4d4d")
        elif server_v > local_v:
            self.local_ver_label.configure(text=f"DOSTĘPNA AKTUALIZACJA (Masz: {local_v})", text_color="#f1c40f")
        else:
            self.local_ver_label.configure(text=f"TŁUMACZENIE AKTUALNE ({local_v})", text_color="#2ecc71")
        self.server_ver_label.configure(text=f"Najnowsza wersja na serwerze: {server_v}")

    def show_finish_screen(self):
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

        is_launcher = self.version_var.get() == "launcher"
        p1 = os.path.join(self.game_path, "Package", "HD", "oversea", "locale")
        p2 = os.path.join(self.game_path, "LocalData", "Patch", "HD", "oversea", "locale")
        files = [f"translate_words_map_{lang}", f"translate_words_map_{lang}_diff"]
        self.set_progress(0.05, "Inicjalizacja...")

        try:
            for i, f_name in enumerate(files):
                sub = "orginal" if mode == "orginal" else lang
                self.set_progress(0.1 + (i * 0.4), f"Pobieranie: {f_name}...")
                res = requests.get(f"{RAW_URL}files/{sub}/{f_name}", timeout=30)
                
                if res.status_code == 200:
                    for folder in [p1, p2]:
                        target = os.path.abspath(os.path.join(folder, f_name))
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        
                        if os.path.exists(target): 
                            os.chmod(target, stat.S_IWRITE)
                            
                        with open(target, "wb") as f: 
                            f.write(res.content)
                            
                        if mode == "files":
                            if folder == p2:
                                os.chmod(target, stat.S_IREAD)
                            elif is_launcher:
                                os.chmod(target, stat.S_IREAD)
                        else:
                            os.chmod(target, stat.S_IWRITE)
                else: raise Exception(f"Błąd pobierania {f_name}")

            if mode == "files":
                rv = requests.get(f"{RAW_URL}version.txt", timeout=5)
                v_file = os.path.abspath(os.path.join(p1, "polish_version.txt"))
                if os.path.exists(v_file): os.chmod(v_file, stat.S_IWRITE)
                with open(v_file, "w") as f: f.write(rv.text.strip())
                self.set_progress(1.0, "Zakończono!")
                self.update_status(); self.show_finish_screen()
            else:
                v_file = os.path.abspath(os.path.join(p1, "polish_version.txt"))
                if os.path.exists(v_file): 
                    os.chmod(v_file, stat.S_IWRITE)
                    os.remove(v_file)
                self.set_progress(1.0, "Przywrócono!")
                self.update_status(); messagebox.showinfo("Sukces", "Oryginał przywrócony.")
        except Exception as e:
            self.set_progress(0, "Błąd."); messagebox.showerror("Błąd", str(e))

    def run_install(self): self.install_logic("files")
    def run_restore(self): self.install_logic("orginal")

if __name__ == "__main__":
    app = WWMInstaller()
    app.mainloop()