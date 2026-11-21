"""Arkusz klatek bohatera (offscreen): każda scenka i celebracja z flagą w powiększeniu."""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from wwmpl.character import Hero

app = QApplication([])
random.seed(3)
Z, CW, CH = 3.0, 150, 120
frames = []   # (label, hero snapshot params)


def make(mode="patrol"):
    h = Hero()
    h.set_rails({"title": (20, 400, 100), "bar": (20, 400, 100)})
    h.set_mode(mode)
    h.placed = True
    h.rail = "title" if mode == "patrol" else "bar"
    h.x, h.y = 60, 100
    return h


def run(h, seconds):
    for _ in range(int(seconds * 60)):
        h.update(1 / 60)


cells = []
h = make(); h.sub, h.sub_time = "run", 99; run(h, 0.6); cells.append(("bieg", h))
for act in ("wave", "bow", "twirl", "slash"):
    for frac in (0.3, 0.45, 0.6):
        h = make(); h.sub, h.sub_time = "idle", 99
        h.act, h.act_t, h.act_dur = act, Hero.ACTS[act] * frac, Hero.ACTS[act]
        h.last_act = act
        run_dt = 0.0
        h.t = 1.0 + frac * 3
        cells.append((f"{act} {frac}", h))
for sec, label in ((0.2, "dobiega"), (0.9, "wbija"), (1.3, "wbita"), (2.0, "hop")):
    h = make("celebrate"); h.set_progress(1.0); h.x = 40
    h.rails = {"title": (20, 400, 100), "bar": (20, 130, 100)}
    run(h, sec); cells.append((label, h))

cols = 5
rows = (len(cells) + cols - 1) // cols
img = QImage(int(cols * CW * Z / 1), int(rows * CH * Z / 1), QImage.Format_ARGB32)
img.fill(QColor("#8fb4d6"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
for i, (label, hero) in enumerate(cells):
    cx, cy = (i % cols) * CW * Z, (i // cols) * CH * Z
    p.save()
    p.translate(cx, cy)
    p.scale(Z, Z)
    p.translate(CW / 2 - hero.x if hero.mode == "patrol" else 30, 0)
    hero.draw(p, QColor("#2f6f8f"), QColor("#d6403f"))
    p.restore()
    p.setPen(QColor("white"))
    p.drawText(int(cx + 6), int(cy + 16), label)
p.end()
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hero_sheet.png")
img.save(str(out))
print("saved", out, img.width(), img.height())
