"""Podgląd sceny w trybie offscreen: zapisuje PNG dla każdego nastroju i stanu bohatera."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QWidget
from wwmpl.scene import FxOverlay, SceneWidget

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/preview")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
root = QWidget()
root.resize(880, 660)
scene = SceneWidget(root)
scene.resize(880, 660)
overlay = FxOverlay(scene, root)
overlay.resize(880, 660)
scene.hero.set_rails({"title": (200, 680, 170), "bar": (120, 760, 468)})


def advance(seconds, step=1 / 60):
    n = int(seconds / step)
    for _ in range(n):
        scene._last = time.perf_counter() - step
        scene.tick()


def shot(name):
    root.grab().save(str(out / f"{name}.png"))


advance(2.0)
shot("day")
t0 = time.perf_counter()
for _ in range(60):
    root.grab()
print("ms / klatka (grab):", (time.perf_counter() - t0) / 60 * 1000)
scene.set_mood("night")
advance(4.0)
shot("night")
scene.set_mood("dawn")
advance(4.0)
shot("dawn")
scene.set_mood("day")
scene.hero.set_mode("bar")
scene.hero.set_progress(0.45)
advance(3.0)
shot("hero_bar")
scene.hero.set_mode("celebrate")
advance(1.3)
shot("hero_celebrate")
scene.hero.set_mode("patrol")
advance(3.0)
shot("hero_patrol")
