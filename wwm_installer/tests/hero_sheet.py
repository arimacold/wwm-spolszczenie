"""Arkusz klatek bohatera (offscreen): każda scenka w kilku momentach, skoki i finał z flagą.
Użycie: python tests/hero_sheet.py [plik.png] [zima|lato]"""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from wwmpl.character import CLIPS, Hero

app = QApplication([])
random.seed(3)
Z, CW, CH = 3.0, 120, 112
season = sys.argv[2] if len(sys.argv) > 2 else ""
WINTER, SUMMER = (1.0 if season == "zima" else 0.0), (1.0 if season == "lato" else 0.0)


def make(mode="patrol"):
    h = Hero()
    h.set_rails({"title": (0, 4000, 100), "bar": (0, 4000, 100)})
    h.x, h.y = 2000, 100
    h.season = (WINTER, SUMMER)
    if mode != "patrol":
        h.mode, h.rail = mode, "bar"
    return h


def run(h, seconds):
    for _ in range(int(seconds * 60)):
        h.update(1 / 60)


cells = []
h = make(); h.p_state, h.run_left, h.vx = "run", 99, 92; run(h, 0.5); cells.append(("bieg", h))
h = make(); h.p_state, h.run_left, h.vx = "run", 99, 92; run(h, 0.62); cells.append(("bieg 2", h))
acts = {"wave": (0.3, 0.5), "bow": (0.2, 0.6), "twirl": (0.3, 0.55), "kata": (0.12, 0.3, 0.43, 0.56, 0.7, 0.8),
        "look": (0.3, 0.7), "drink": (0.36, 0.5), "meditate": (0.5,), "stretch": (0.35, 0.62), "kick": (0.24, 0.45),
        "shiver": (0.5,), "fan": (0.5,), "ready": (0.6,), "shrug": (0.4,)}
for act, fracs in acts.items():
    for frac in fracs:
        h = make()
        h.idle_left = 99
        h._start_action(act)
        run(h, CLIPS[act].dur * frac)
        cells.append((f"{act} {frac}", h))
for kind, u in (("hop", 0.4), ("flip", 0.35), ("flip", 0.6), ("cheer", 0.4)):
    h = make()
    h._start_jump((h.x, h.y), 1.0, 30, kind, pre=0)
    run(h, u)
    cells.append((f"skok {kind} {u}", h))
for sec, label in ((0.7, "dobiega"), (1.25, "wbija"), (1.6, "wbita"), (2.4, "radość")):
    h = make("celebrate"); h.set_progress(1.0)
    h.rails = {"title": (0, 4000, 100), "bar": (0, 2040, 100)}
    run(h, sec); cells.append((label, h))

cols = 6
rows = (len(cells) + cols - 1) // cols
img = QImage(int(cols * CW * Z), int(rows * CH * Z), QImage.Format_ARGB32)
img.fill(QColor("#8fb4d6"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
for i, (label, hero) in enumerate(cells):
    cx, cy = (i % cols) * CW * Z, (i // cols) * CH * Z
    p.save()
    p.translate(cx, cy)
    p.scale(Z, Z)
    p.translate(CW / 2 - hero.x, 0)
    p.fillRect(int(hero.x - CW / 2), 100, CW, 12, QColor("#6d8fb3"))
    hero.draw(p, QColor("#2f6f8f"), QColor("#d6403f"), WINTER, SUMMER)
    p.restore()
    p.setPen(QColor("white"))
    p.drawText(int(cx + 6), int(cy + 16), label)
p.end()
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/hero_sheet.png")
img.save(str(out))
print("saved", out, img.width(), img.height())
