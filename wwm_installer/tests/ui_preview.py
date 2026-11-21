"""Zrzuty ekranu pełnego okna (offscreen) w kilku stanach. Używa lokalnego serwera i fałszywej gry."""
import functools
import http.server
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import wwmpl.core as core
from conftest import World
from wwmpl.app import MainWindow

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ui")
out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp())
world = World(tmp)
world.publish()
world.install_game_files("en")
world.install_game_files("de")
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(world.repo))
handler.log_message = lambda *a, **k: None
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}/"

core.find_game_path = lambda platform: str(world.game)
import wwmpl.app as appmod
appmod.find_game_path = core.find_game_path

app = QApplication([])
appmod.SCREEN_MARGIN = -200
w = MainWindow(base_url=base)
w.show()


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def shot(name):
    w.grab().save(str(out / f"{name}.png"))


pump(2.5)
shot("1_start_day")

# hover na przycisku instalacji
btn = w.btn_install
btn._hover = 1.0
btn._sweep = 0.4
btn.update()
shot("2_hover")
btn._hover = 0.0
btn._sweep = 1.0

# przełączenie na niemiecki -> noc
w.seg_language.set_value("de")
pump(3.0)
shot("3_german_night")
w.seg_language.set_value("en")
pump(2.5)

# instalacja (dialog sukcesu zostanie zamknięty timerem)
from wwmpl.widgets import MessageDialog
from PySide6.QtCore import QTimer


def close_dialogs():
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, MessageDialog) and widget.isVisible():
            widget.grab().save(str(out / "6_dialog.png"))
            widget.accept()


timer = QTimer()
timer.timeout.connect(close_dialogs)
timer.start(300)
w.run_install()
pump(0.3)
shot("4_installing")
pump(1.2)
shot("5_after_install_dawn")
print("status:", w.status.state if w.status else None, "| mood:", w.scene.mood.name, "| detail:", w.detail.text())
pump(1.5)
shot("5b_dialog_moment")
pump(4.0)
print("version file:", core.read_version_file(world.game))
print("pkg translated:", world.pkg("en").read_bytes() == world.translated("en", "main"))
shot("7_idle_after")
