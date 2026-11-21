#!/usr/bin/env python3
"""Generuje assets/ikona.ico (wielorozmiarowa) z tej samej grafiki, której używa okno aplikacji.
Wymaga: PySide6 i Pillow.   python tools/make_icon.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from PIL import Image
from PySide6.QtWidgets import QApplication

from wwmpl.scene import make_icon

app = QApplication([])
assets = root / "assets"
assets.mkdir(exist_ok=True)
png = assets / "ikona.png"
make_icon(256).save(str(png))
Image.open(png).save(assets / "ikona.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Zapisano", assets / "ikona.ico")
