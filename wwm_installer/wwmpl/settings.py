"""Drobne ustawienia użytkownika (np. wybrany układ okna) w %LOCALAPPDATA%\\WWM-Spolszczenie\\settings.json."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    return Path(base) / "WWM-Spolszczenie" / "settings.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**values) -> None:
    try:
        data = load()
        data.update(values)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # ustawienia są dodatkiem – brak zapisu nie może psuć programu
