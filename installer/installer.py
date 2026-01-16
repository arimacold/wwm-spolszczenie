import os
import shutil
import hashlib
import requests
import logging
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ================== KONFIG ==================
REPO = "arimacold/wwm-spolszczenie"
GITHUB_API = f"https://api.github.com/repos/{REPO}/releases/latest"
FILES_URL = f"https://raw.githubusercontent.com/{REPO}/main/files/"
CHECKSUMS_URL = FILES_URL + "checksums.json"

FILES = [
    "translate_words_map_en",
    "translate_words_map_en_diff"
]

STEAM_ROOT = r"C:\Program Files (x86)\Steam"
DEFAULT_GAME_ROOT = r"C:\Program Files (x86)\Steam\steamapps\common\Where Winds Meet"
LOCALE_SUBPATH = os.path.join("Package", "HD", "oversea", "locale")

LOCAL_VERSION_FILE = "installed_version.txt"

# ================== LOGI ==================
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/install.log",
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)

def log(msg):
    logging.info(msg)

# ================== NARZĘDZIA ==================
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def get_local_version():
    if not os.path.exists(LOCAL_VERSION_FILE):
        return "0.0.0"
    return open(LOCAL_VERSION_FILE, encoding="utf-8").read().strip()

def get_remote_version():
    r = requests.get(GITHUB_API, timeout=10)
    r.raise_for_status()
    return r.json()["tag_name"].replace("v", "")

def find_game_root():
    vdf = os.path.join(STEAM_ROOT, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf):
        with open(vdf, encoding="utf-8") as f:
            for line in f:
                if '"path"' in line:
                    lib = line.split('"')[-2]
                    candidate = os.path.join(lib, "steamapps", "common", "Where Winds Meet")
                    if os.path.exists(candidate):
                        return candidate
    return DEFAULT_GAME_ROOT

def get_locale_path(game_root):
    return os.path.join(game_root, LOCALE_SUBPATH)

def validate_game_root(game_root):
    return os.path.exists(get_locale_path(game_root))

# ================== BACKUP ==================
def backup_files(locale_path):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join("backup", ts)
    os.makedirs(backup_path, exist_ok=True)

    for f in FILES:
        src = os.path.join(locale_path, f)
        if os.path.exists(src):
            shutil.copy2(src, backup_path)

    log(f"Backup created: {backup_path}")

# ================== INSTALACJA ==================
def install(locale_path, progress_cb, remote_version):
    log("Installation started")
    backup_files(locale_path)

    progress_cb(20)
    checksums = requests.get(CHECKSUMS_URL, timeout=10).json()

    step = 60 // len(FILES)
    p = 20

    for f in FILES:
        r = requests.get(FILES_URL + f, timeout=20)
        if sha256(r.content) != checksums.get(f):
            raise Exception(f"Błąd sumy kontrolnej: {f}")

        with open(os.path.join(locale_path, f), "wb") as out:
            out.write(r.content)

        p += step
        progress_cb(p)

    with open(LOCAL_VERSION_FILE, "w", encoding="utf-8") as v:
        v.write(remote_version)

    progress_cb(100)
    log("Installation finished")

# ================== GUI ==================
root = tk.Tk()
root.title("Spolszczenie Where Winds Meet")
root.geometry("760x460")
root.resizable(False, False)

steps = ["info", "path", "install", "done"]
current_step = 0
update_available = False
remote_version = "0.0.0"

content = tk.Frame(root)
content.pack(fill="both", expand=True)

frames = {}

# ---------- STEROWANIE KROKAMI ----------
def show_step(i):
    global current_step
    current_step = i
    frames[steps[i]].tkraise()

    back_btn["state"] = "normal" if i > 0 else "disabled"
    next_btn["state"] = "disabled"

    if i == 0 and update_available:
        next_btn["state"] = "normal"
    elif i == 1 and validate_game_root(game_root_var.get()):
        next_btn["state"] = "normal"
    elif i == 2:
        next_btn["state"] = "normal"

    next_btn["text"] = "Zakończ" if i == len(steps) - 1 else "Dalej"

# ---------- INFO ----------
f_info = tk.Frame(content)
tk.Label(f_info, text="Spolszczenie Where Winds Meet", font=("Segoe UI", 18, "bold")).pack(pady=30)

status_label = tk.Label(f_info, font=("Segoe UI", 12))
status_label.pack(pady=10)

def auto_check_versions():
    global update_available, remote_version
    try:
        local = get_local_version()
        remote_version = get_remote_version()

        if remote_version > local:
            update_available = True
            status_label.config(
                text=f"❌ Aktualizacja dostępna\n\nZainstalowana: {local}\nNajnowsza: {remote_version}",
                fg="red"
            )
        else:
            update_available = False
            status_label.config(
                text=f"✔️ Masz aktualną wersję\n\nWersja: {local}",
                fg="green"
            )
    except Exception:
        update_available = False
        status_label.config(
            text="⚠️ Nie można sprawdzić wersji (brak internetu)",
            fg="orange"
        )

frames["info"] = f_info

# ---------- PATH ----------
f_path = tk.Frame(content)
tk.Label(f_path, text="Główny folder gry:", font=("Segoe UI", 14, "bold")).pack(pady=20)

game_root_var = tk.StringVar(value=find_game_root())
tk.Entry(f_path, textvariable=game_root_var, width=80).pack()

path_status = tk.Label(f_path, font=("Segoe UI", 10))
path_status.pack(pady=5)

def browse_root():
    folder = filedialog.askdirectory()
    if folder:
        game_root_var.set(folder)

tk.Button(f_path, text="Zmień...", command=browse_root).pack(pady=5)

def update_path_status(*_):
    if validate_game_root(game_root_var.get()):
        path_status.config(text="✔️ Folder gry poprawny", fg="green")
    else:
        path_status.config(text="❌ Nie znaleziono plików językowych", fg="red")

game_root_var.trace_add("write", update_path_status)
update_path_status()

frames["path"] = f_path

# ---------- INSTALL ----------
f_install = tk.Frame(content)
progress = ttk.Progressbar(f_install, length=500)
progress.pack(pady=60)

def set_progress(v):
    progress["value"] = v
    root.update_idletasks()

def start_install():
    install(get_locale_path(game_root_var.get()), set_progress, remote_version)
    show_step(3)

tk.Button(f_install, text="Rozpocznij instalację", command=start_install).pack()
frames["install"] = f_install

# ---------- DONE ----------
f_done = tk.Frame(content)
tk.Label(f_done, text="Instalacja zakończona pomyślnie!", font=("Segoe UI", 16, "bold")).pack(pady=80)
frames["done"] = f_done

# ---------- PLACE ----------
for f in frames.values():
    f.place(relwidth=1, relheight=1)

# ---------- NAV ----------
nav = tk.Frame(root)
nav.pack(fill="x", side="bottom")

back_btn = tk.Button(nav, text="Wstecz", width=12,
                     command=lambda: show_step(current_step - 1))
back_btn.pack(side="left", padx=10, pady=10)

next_btn = tk.Button(nav, text="Dalej", width=12,
                     command=lambda: (
                         root.destroy() if current_step == len(steps) - 1
                         else show_step(current_step + 1)
                     ))
next_btn.pack(side="right", padx=10, pady=10)

# ---------- START ----------
auto_check_versions()
show_step(0)
root.mainloop()
