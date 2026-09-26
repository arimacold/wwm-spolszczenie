import os
import winreg
import requests
import stat
import webbrowser
import time
import winsound
import threading
import shutil
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
        self.geometry("600x820")
        ctk.set_appearance_mode("dark")
        
        try:
            self.iconbitmap("ikona.ico")
        except Exception:
            pass

        self.version_var = ctk.StringVar(value="steam")
        self.lang_var = ctk.StringVar(value="en")
        self.game_path = self.find_game_path()
        
        self.setup_ui()
        self.update_status()

    def is_valid_game_path(self, path):
        if not path: return False
        return os.path.exists(os.path.join(path, "Package"))

    def find_game_path(self):
        v = self.version_var.get()
        path = None
        if v == "steam":
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
                steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
                steam_game = os.path.join(steam_path, "steamapps", "common", "Where Winds Meet")
                if self.is_valid_game_path(steam_game):
                    path = steam_game
            except: pass
        else:
            potential = [
                r"C:\Program Files\wwm\wwm_standard", r"C:\Program Files\wwm\wwm_lite",
                r"C:\Program Files (x86)\wwm\wwm_standard", r"C:\Program Files (x86)\wwm\wwm_lite",
                r"C:\NetEase\WWM\wwm_standard", r"C:\NetEase\WWM\wwm_lite",
                r"C:\NetEase Games\WWM\wwm_standard", r"C:\NetEase Games\WWM\wwm_lite",
                r"C:\Games\Where Winds Meet\wwm_standard", r"C:\Games\Where Winds Meet\wwm_lite",
                r"D:\Games\Where Winds Meet\wwm_standard", r"D:\Games\Where Winds Meet\wwm_lite",
                r"E:\Games\Where Winds Meet\wwm_standard", r"E:\Games\Where Winds Meet\wwm_lite",
                r"C:\WWM\wwm_standard", r"C:\WWM\wwm_lite",
                r"D:\WWM\wwm_standard", r"D:\WWM\wwm_lite",
                r"C:\Program Files\Epic Games\WhereWindsMeet\wwm_standard",
                r"C:\Program Files (x86)\Epic Games\WhereWindsMeet\wwm_standard",
                r"D:\Epic Games\WhereWindsMeet\wwm_standard",
                r"C:\Users\Public\Games\Where Winds Meet\wwm_standard",
                r"C:\Users\Public\Games\Where Winds Meet\wwm_lite"
            ]
            for p in potential:
                if self.is_valid_game_path(p): 
                    path = p
                    break
        
        return os.path.abspath(os.path.normpath(path)) if path and self.is_valid_game_path(path) else None

    def refresh_path(self):
        self.game_path = self.find_game_path()
        self.update_status()

    def browse_path(self):
        path = filedialog.askdirectory(title="Wskaż główny folder gry Where Winds Meet (ten z folderem Package)")
        if path:
            if self.is_valid_game_path(path):
                self.game_path = os.path.abspath(os.path.normpath(path))
                self.update_status()
            else:
                self.ui_msg_error("Zły folder", "We wskazanym folderze nie znaleziono plików gry!\nUpewnij się, że wybierasz główny katalog 'Where Winds Meet'.")

    def setup_ui(self):
        ctk.CTkLabel(self, text="Instalator spolszczenia do gry\nWhere Winds Meet", 
                      font=("Segoe UI", 26, "bold")).pack(pady=(25, 10))
        
        ctk.CTkFrame(self, height=2, fg_color="#3b8ed0", width=300).pack(pady=5)

        self.plat_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        self.plat_frame.pack(pady=8, padx=40, fill="x")
        ctk.CTkLabel(self.plat_frame, text="Wybierz platformę:", font=("Segoe UI", 13)).pack(pady=5)
        
        self.rb_steam = ctk.CTkRadioButton(self.plat_frame, text="Steam", variable=self.version_var, value="steam", 
                            command=self.refresh_path, border_color="#555555", fg_color="#3b8ed0", 
                            hover_color="#5fa3d9", border_width_checked=6)
        self.rb_steam.pack(side="left", padx=60, pady=10)
        self.rb_launcher = ctk.CTkRadioButton(self.plat_frame, text="Epic / Launcher", variable=self.version_var, value="launcher", 
                            command=self.refresh_path, border_color="#555555", fg_color="#3b8ed0", 
                            hover_color="#5fa3d9", border_width_checked=6)
        self.rb_launcher.pack(side="right", padx=60, pady=10)

        self.lang_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=10)
        self.lang_frame.pack(pady=8, padx=40, fill="x")
        ctk.CTkLabel(self.lang_frame, text="Wybierz język gry do podmiany:", font=("Segoe UI", 13)).pack(pady=5)
        
        self.rb_en = ctk.CTkRadioButton(self.lang_frame, text="Angielski (EN)", 
                                        variable=self.lang_var, value="en", 
                                        border_color="#555555", fg_color="#3b8ed0", 
                                        hover_color="#5fa3d9", border_width_checked=6)
        self.rb_en.pack(side="left", padx=60, pady=12)
        
        self.rb_de = ctk.CTkRadioButton(self.lang_frame, text="Niemiecki (DE)", 
                                        variable=self.lang_var, value="de", 
                                        border_color="#555555", fg_color="#3b8ed0", 
                                        hover_color="#5fa3d9", border_width_checked=6)
        self.rb_de.pack(side="right", padx=60, pady=12)

        self.status_box = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        self.status_box.pack(pady=8, padx=40, fill="x")
        self.local_ver_label = ctk.CTkLabel(self.status_box, text="Twoja wersja: Sprawdzanie...", font=("Segoe UI", 15, "bold"))
        self.local_ver_label.pack(pady=(10, 2))
        self.server_ver_label = ctk.CTkLabel(self.status_box, text="Wersja na serwerze: ...", font=("Segoe UI", 12))
        self.server_ver_label.pack(pady=(0, 10))

        self.progress_container = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_container.pack(pady=(5, 0), padx=60, fill="x")
        self.progress = ctk.CTkProgressBar(self.progress_container, height=14, fg_color="#1e1e1e", progress_color="#3b8ed0")
        self.progress.set(0)
        self.progress.pack(side="left", fill="x", expand=True)
        self.percentage_label = ctk.CTkLabel(self.progress_container, text="0%", font=("Segoe UI", 12, "bold"), width=50)
        self.percentage_label.pack(side="right", padx=(10, 0))

        self.detail_label = ctk.CTkLabel(self, text="Oczekiwanie na start...", font=("Segoe UI", 11), text_color="#888888")
        self.detail_label.pack(pady=(2, 8))

        self.btn_install = ctk.CTkButton(self, text="ZAINSTALUJ / AKTUALIZUJ", command=self.run_install, 
                                          height=48, font=("Segoe UI", 16, "bold"), fg_color="#3b8ed0", hover_color="#2c6e9e")
        self.btn_install.pack(pady=4, padx=60, fill="x")

        self.btn_launch = ctk.CTkButton(self, text="▶ URUCHOM GRĘ (PL)", command=self.run_launch, 
                                         height=42, font=("Segoe UI", 14, "bold"), fg_color="#27ae60", hover_color="#1e824c")
        self.btn_launch.pack(pady=4, padx=60, fill="x")

        self.btn_restore = ctk.CTkButton(self, text="PRZYWRÓĆ ORYGINALNE TŁUMACZENIE", command=self.run_restore, 
                                          height=36, font=("Segoe UI", 12, "bold"), fg_color="#3d3d3d", hover_color="#4d4d4d")
        self.btn_restore.pack(pady=4, padx=60, fill="x")

        self.tool_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.tool_frame.pack(pady=8)
        ctk.CTkButton(self.tool_frame, text="📁 Zmień folder", width=110, command=self.browse_path, fg_color="transparent", border_width=1).pack(side="left", padx=8)
        ctk.CTkButton(self.tool_frame, text="🔍 Otwórz folder", width=110, command=lambda: os.startfile(self.game_path) if self.game_path else None, fg_color="transparent", border_width=1).pack(side="left", padx=8)

        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(side="bottom", fill="x", pady=12)
        ctk.CTkButton(self.footer, text="📖 Poradnik Steam", command=lambda: webbrowser.open(STEAM_GUIDE_URL), fg_color="#171a21", hover_color="#2a2e38").pack(side="left", padx=30)
        ctk.CTkButton(self.footer, text="☕ Wesprzyj projekt", command=lambda: webbrowser.open(COFFEE_URL), fg_color="#4d4d4d", hover_color="#5d5d5d").pack(side="right", padx=30)

    def set_progress(self, val, detail_text):
        self.after(0, self._set_progress, val, detail_text)

    def _set_progress(self, val, detail_text):
        self.progress.set(val)
        self.percentage_label.configure(text=f"{int(val * 100)}%")
        self.detail_label.configure(text=detail_text)

    def ui_msg_info(self, title, msg):
        self.after(0, lambda: messagebox.showinfo(title, msg))

    def ui_msg_error(self, title, msg):
        self.after(0, lambda: messagebox.showerror(title, msg))

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
        self.after(0, self._show_finish_screen)

    def _show_finish_screen(self):
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

    def run_install(self): 
        self.toggle_buttons(False)
        threading.Thread(target=self.install_logic, args=("files",), daemon=True).start()
        
    def run_restore(self): 
        self.toggle_buttons(False)
        threading.Thread(target=self.install_logic, args=("orginal",), daemon=True).start()

    def run_launch(self):
        self.toggle_buttons(False)
        threading.Thread(target=self.launch_and_patch, daemon=True).start()

    def toggle_buttons(self, state=True):
        st = "normal" if state else "disabled"
        self.btn_install.configure(state=st)
        self.btn_restore.configure(state=st)
        self.btn_launch.configure(state=st)

    def download_file(self, url, target_path, base_progress, progress_share, file_name):
        res = requests.get(url, stream=True, timeout=15)
        if res.status_code == 200:
            total_size = int(res.headers.get('content-length', 0))
            downloaded = 0
            with open(target_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            current_fraction = downloaded / total_size
                            current_progress = base_progress + (current_fraction * progress_share)
                            self.set_progress(current_progress, f"Pobieranie: {file_name} ({int(downloaded/1024)}KB / {int(total_size/1024)}KB)")
        else:
            raise Exception(f"Błąd pobierania pliku {file_name} (Kod: {res.status_code})")

    def install_logic(self, mode="files"):
        lang = self.lang_var.get()
        if not self.game_path:
            self.ui_msg_error("Błąd", "Wskaż folder gry przed instalacją!")
            self.after(0, self.reset_buttons)
            return

        p1_package = os.path.join(self.game_path, "Package", "HD", "oversea", "locale")
        p2_localdata = os.path.join(self.game_path, "LocalData", "Patch", "HD", "oversea", "locale")
        
        safe_data_dir = os.path.join(self.game_path, "Spolszczenie_Data")
        
        files_main = [f"translate_words_map_{lang}", f"translate_words_map_{lang}__small"]
        files_diff = [f"translate_words_map_{lang}_diff", f"translate_words_map_{lang}__small_diff"]

        self.set_progress(0.05, "Inicjalizacja...")
        
        total_tasks = len(files_main) + len(files_diff)
        current_task = 0
        progress_per_task = 0.85 / total_tasks if total_tasks > 0 else 0

        try:
            for f_name in files_main:
                target = os.path.abspath(os.path.join(p1_package, f_name))
                backup = target + ".backup"
                os.makedirs(os.path.dirname(target), exist_ok=True)
                
                if mode == "files":
                    if os.path.exists(target) and not os.path.exists(backup):
                        shutil.copy2(target, backup)

                    if os.path.exists(target): os.chmod(target, stat.S_IWRITE)
                    
                    sub = lang
                    url = f"{RAW_URL}files/{sub}/{f_name}"
                    base_p = 0.1 + (current_task * progress_per_task)
                    self.download_file(url, target, base_p, progress_per_task, f_name)
                    current_task += 1
                
                else: 
                    self.set_progress(0.1 + (current_task * 0.4), f"Przywracanie: {f_name}...")
                    if os.path.exists(target):
                        os.chmod(target, stat.S_IWRITE)
                        os.remove(target)
                    
                    if os.path.exists(backup):
                        shutil.copy2(backup, target)
                    else:
                        url = f"{RAW_URL}files/orginal/{f_name}"
                        self.download_file(url, target, 0.1, 0.4, f_name)
                    current_task += 1

            os.makedirs(safe_data_dir, exist_ok=True)
            for f_name in files_diff:
                target = os.path.abspath(os.path.join(p2_localdata, f_name))
                pol_backup = os.path.join(safe_data_dir, f_name + ".pol")
                
                if mode == "files":
                    if os.path.exists(pol_backup): os.chmod(pol_backup, stat.S_IWRITE)
                    
                    sub = lang
                    url = f"{RAW_URL}files/{sub}/{f_name}"
                    base_p = 0.1 + (current_task * progress_per_task)
                    self.download_file(url, pol_backup, base_p, progress_per_task, f_name)
                    current_task += 1
                else:
                    self.set_progress(0.9, "Czyszczenie plików DIFF...")
                    for t in (target, pol_backup):
                        if os.path.exists(t):
                            try:
                                os.chmod(t, stat.S_IWRITE)
                                os.remove(t)
                            except: pass
                    current_task += 1

            v_file = os.path.abspath(os.path.join(p1_package, "polish_version.txt"))
            if mode == "files":
                rv = requests.get(f"{RAW_URL}version.txt", timeout=5)
                if os.path.exists(v_file): os.chmod(v_file, stat.S_IWRITE)
                with open(v_file, "w") as f: f.write(rv.text.strip())
                
                self.set_progress(1.0, "Zakończono!")
                self.after(0, self.update_status)
                self.show_finish_screen()
            else:
                if os.path.exists(v_file): 
                    os.chmod(v_file, stat.S_IWRITE)
                    os.remove(v_file)
                self.set_progress(1.0, "Przywrócono!")
                self.after(0, self.update_status)
                self.ui_msg_info("Sukces", "Oryginał przywrócony pomyślnie.\nPliki spolszczenia usunięto z gry.")
                
        except Exception as e:
            self.set_progress(0, "Błąd instalacji.")
            error_msg = str(e)
            if "Permission denied" in error_msg or "[WinError 5]" in error_msg:
                self.ui_msg_error("Brak uprawnień", "Odmowa dostępu! Uruchom instalator jako Administrator (Prawym przyciskiem myszy -> Uruchom jako administrator).")
            else:
                self.ui_msg_error("Błąd instalacji", f"Wystąpił problem:\n{error_msg}\n\nUpewnij się, że gra jest wyłączona!")
        finally:
            self.after(0, self.reset_buttons)

    def launch_and_patch(self):
        if not self.game_path:
            self.ui_msg_error("Błąd", "Wskaż folder gry przed uruchomieniem!")
            self.after(0, self.reset_buttons)
            return

        lang = self.lang_var.get()
        p2_localdata = os.path.join(self.game_path, "LocalData", "Patch", "HD", "oversea", "locale")
        target_diff = os.path.join(p2_localdata, f"translate_words_map_{lang}_diff")
        
        safe_data_dir = os.path.join(self.game_path, "Spolszczenie_Data")
        os.makedirs(safe_data_dir, exist_ok=True)
        pol_source = os.path.join(safe_data_dir, f"translate_words_map_{lang}_diff.pol")

        if not os.path.exists(pol_source):
            self.set_progress(0.05, "Inicjalizowanie plików injectora...")
            try:
                url = f"{RAW_URL}files/{lang}/translate_words_map_{lang}_diff"
                res = requests.get(url, stream=True, timeout=15)
                if res.status_code == 200:
                    with open(pol_source, "wb") as f:
                        for chunk in res.iter_content(chunk_size=8192):
                            if chunk: f.write(chunk)
                else:
                    self.ui_msg_error("Błąd", "Nie udało się pobrać pliku injectora. Kliknij 'ZAINSTALUJ / AKTUALIZUJ'.")
                    self.after(0, self.reset_buttons)
                    return
            except Exception as e:
                self.ui_msg_error("Błąd sieci", f"Upewnij się, że masz internet: {e}")
                self.after(0, self.reset_buttons)
                return

        # Wymuszamy na grze proces weryfikacji i pobierania pliku poprzez jego wcześniejsze usunięcie z aktywnego folderu
        if os.path.exists(target_diff):
            try:
                os.chmod(target_diff, stat.S_IWRITE)
                os.remove(target_diff)
            except Exception: pass

        self.set_progress(0.1, "Uruchamianie gry...")
        
        if self.version_var.get() == "steam":
            try:
                os.startfile("steam://rungameid/3564740")
            except Exception:
                self.ui_msg_info("Informacja", "Steam nie odpowiedział automatycznie. Uruchom grę ręcznie z biblioteki.")
        else:
            exe_names = ["WhereWindsMeet.exe", "WWM.exe", "WWM_Game.exe", "Launcher.exe"]
            exe_path = None
            
            for root, dirs, files in os.walk(self.game_path):
                if root[len(self.game_path):].count(os.sep) > 3:
                    continue
                for file in files:
                    if file in exe_names:
                        exe_path = os.path.join(root, file)
                        break
                if exe_path:
                    break
                    
            if exe_path:
                try:
                    os.startfile(exe_path)
                except Exception:
                    self.ui_msg_info("Informacja", "Nie udało się włączyć gry automatycznie. Uruchom ją ręcznie.")
            else:
                self.ui_msg_info("Informacja", "Nie znaleziono pliku .exe. Uruchom grę ręcznie ze swojej platformy.")

        self._watcher_thread(target_diff, pol_source)

    def _watcher_thread(self, target_diff, pol_source):
        self.set_progress(0.3, "Oczekiwanie na grę (Czas na ręczne włączenie: 5 minut)...")
        
        try:
            pol_size = os.path.getsize(pol_source)
        except Exception:
            pol_size = 0
            
        start_time = time.time()
        patched_once = False
        last_patch_time = time.time()

        # Czekamy maksymalnie 5 minut - skanujemy folder z ultrawysoką częstotliwością (0.1 sekundy)
        while time.time() - start_time < 300:
            time.sleep(0.1)
            
            if os.path.exists(target_diff):
                try:
                    current_size = os.path.getsize(target_diff)
                    # Jeżeli rozmiar pliku pobranego przez grę nie zgadza się z naszym (gra wrzuciła angielski oryginał)
                    if current_size != pol_size:
                        try:
                            os.chmod(target_diff, stat.S_IWRITE)
                            shutil.copy2(pol_source, target_diff)
                            patched_once = True
                            last_patch_time = time.time()
                            self.set_progress(0.8, "Wstrzykiwanie danych (Nie zamykaj programu)...")
                        except PermissionError:
                            # Gra aktualnie czyta/pisze plik (blokada) - pomijamy i próbujemy za 0.1s
                            pass
                except Exception:
                    pass
            
            # Bezpiecznik: Jeżeli udało się podmienić plik, i gra przez 8 sekund nie próbowała go cofnąć, to znaczy że przeszliśmy!
            if patched_once and (time.time() - last_patch_time > 8):
                self.set_progress(1.0, "Spolszczenie zaaplikowane w locie pomyślnie! Miłej gry.")
                self.after(0, self.reset_buttons)
                return

        # Jeśli pętla minęła i przez 5 minut nic się nie wydarzyło
        if not patched_once:
            self.set_progress(0, "Przekroczono czas. Uruchom grę na platformie szybciej.")
            try:
                if os.path.exists(target_diff): os.chmod(target_diff, stat.S_IWRITE)
                shutil.copy2(pol_source, target_diff)
            except Exception: pass
            
        self.after(0, self.reset_buttons)

    def reset_buttons(self):
        self.toggle_buttons(True)

if __name__ == "__main__":
    app = WWMInstaller()
    app.mainloop()