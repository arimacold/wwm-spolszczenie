"""Dziennik instalatora: plik z rotacją w %LOCALAPPDATA%\\WWM-Spolszczenie\\logs + bufor dla panelu w oknie.

Logi mają pomagać przy zgłoszeniach problemów: zawierają wersje, wykryte ścieżki, decyzje instalatora,
sumy kontrolne i pełne błędy. Nie zapisujemy w nich niczego wrażliwego (brak danych konta, tokenów itp.).
"""
from __future__ import annotations

import collections
import logging
import logging.handlers
import os
import platform
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

LOGGER_NAME = "wwmpl"
MAX_LINES = 600
_listeners: list = []
_buffer: collections.deque = collections.deque(maxlen=MAX_LINES)
_lock = threading.Lock()
_configured = False


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "WWM-Spolszczenie" if base else Path.home() / ".config" / "WWM-Spolszczenie"
    return root / "logs"


def log_file() -> Path:
    return log_dir() / "instalator.log"


class _MemoryHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # pragma: no cover - formatowanie nie może zatrzymać instalatora
            return
        with _lock:
            _buffer.append(line)
            listeners = list(_listeners)
        for listener in listeners:
            try:
                listener(line)
            except Exception:
                pass


def setup(app_version: str = "") -> logging.Logger:
    """Konfiguruje logowanie raz na proces. Błąd zapisu pliku nie blokuje programu (zostaje bufor w pamięci)."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger
    _configured = True
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    memory = _MemoryHandler()
    memory.setFormatter(fmt)
    logger.addHandler(memory)
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_file(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    except OSError as error:
        logger.warning("Nie można zapisać pliku logu (%s) – logi tylko w pamięci.", error)
    logger.info("=" * 60)
    logger.info("Start instalatora %s", app_version)
    logger.info("System: %s %s (%s), Python %s", platform.system(), platform.release(), platform.machine(),
                sys.version.split()[0])
    return logger


def get() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def recent() -> list:
    with _lock:
        return list(_buffer)


def subscribe(listener: Callable[[str], None]) -> None:
    with _lock:
        _listeners.append(listener)


def unsubscribe(listener: Callable[[str], None]) -> None:
    with _lock:
        if listener in _listeners:
            _listeners.remove(listener)


def report_text(extra: Optional[dict] = None) -> str:
    """Tekst do skopiowania przy zgłoszeniu: nagłówek z kontekstem + ostatnie linie logu."""
    head = ["=== WWM Spolszczenie – raport z instalatora ===",
            f"System: {platform.system()} {platform.release()} ({platform.machine()})"]
    for key, value in (extra or {}).items():
        head.append(f"{key}: {value}")
    head.append(f"Plik logu: {log_file()}")
    head.append("")
    return "\n".join(head + recent())
