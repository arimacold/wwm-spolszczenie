import tkinter as tk
from tkinter import filedialog, messagebox
import os, shutil, requests, hashlib, json
from datetime import datetime

# =================== KONFIG ===================
REPO = "arimacold/wwm-spolszczenie"
FILES = ["translate_words_map_en", "translate_words_map_en_diff"]

BASE_URL = f"https://raw.githubusercontent.com/{REPO}/main"
FILES_URL = f"{BASE_URL}/files/"
CHECKSUMS_URL = f"{BASE_URL}/files/checksums.json"

STEAM_PATH = r"C:\Program Files (x86)\Steam"
BACKUP_DIR = "backup"

# =================== FUNKCJE ===================
def sha256(data):
    return hashlib.sha256(data).hexdigest()

def find_steam_game():
    vdf = os.path.join(STEAM_PATH, "steamapps", "libraryfolders.vdf")
    if not os.path.exists(vdf):
        return ""

    with open(vdf, encoding="utf-8") as f:
        txt = f.read()

    libs = []
    for line in txt.splitlines():
        if '"path"' in line:
            libs.append(line.split('"')[-2])

    for lib in libs:
        game = os.path.join(lib, "steamapps", "common", "Where Winds Meet", "Game", "Data")
        if os.path.exists(game):
            return game
    return ""

def backup(game_path):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(BACKUP_DIR, ts)
    os.makedirs(path, exist_ok=True)

    for f in FILES:
        src = os.path.join(game_path, f)
        if os.path.exists(src):
            shutil.copy2(src, path)

def restore(game_path):
    folder = filedialog.askdirectory(title="Wybierz backup")
    if not folder:
        return
    for f in FILES:
        shutil.copy2(os.path.join(folder, f), game_path)
    messagebox.showinfo("OK", "Przywrócono pliki")

def install():
    path = game_path_var.get()
    if not os.path.exists(path):
        messagebox.showerror("Błąd", "Zła ścieżka")
        return

    backup(path)

    checksums = requests.get(CHECKSUMS_URL).json()

    for f in FILES:
        r = requests.get(FILES_URL + f)
        if sha256(r.content) != checksums[f]:
            messagebox.showerror("Błąd", "Błąd sumy kontrolnej")
            return
        with open(os.path.join(path, f), "wb") as out:
            out.write(r.content)

    messagebox.showinfo("Sukces", "Spolszczenie zainstalowane")

# =================== GUI ===================
root = tk.Tk()
root.title("Spolszczenie Where Winds Meet")
root.geometry("560x240")

game_path_var = tk.StringVar(value=find_steam_game())

tk.Label(root, text="Folder gry (Game/Data):").pack()
tk.Entry(root, textvariable=game_path_var, width=70).pack()

tk.Button(root, text="Wybierz ręcznie",
          command=lambda: game_path_var.set(filedialog.askdirectory())).pack(pady=4)

tk.Button(root, text="Zainstaluj / Aktualizuj",
          command=install, bg="#4CAF50", fg="white").pack(pady=6)

tk.Button(root, text="Przywróć stare tłumaczenie",
          command=lambda: restore(game_path_var.get())).pack()

root.mainloop()
