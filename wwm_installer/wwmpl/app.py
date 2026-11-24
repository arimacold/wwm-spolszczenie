"""Okno główne instalatora (PySide6)."""
from __future__ import annotations

import ctypes
import io
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QBoxLayout, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from . import core, logs, settings
from .core import (AUTHORS, COFFEE_URL, DEFAULT_VARIANT, LANGUAGES, RAW_URL, VARIANTS, variant_url, STEAM_GUIDE_URL, Cancelled, Journal, OperationError, Status,
                   compute_status, describe_game_folder, find_game_path, game_lock, is_valid_game_path,
                   is_steam_path, resolve_game_root)
from .operations import Engine, fetch_server_version
from .scene import FxOverlay, SceneWidget, make_cursor, make_icon
from .widgets import (TITLE_FAMILIES, AuthorsFlyout, GlassCard, GlowButton, CountdownToast, IconTile, LogPanel, MessageDialog, PathPill, VariantPicker, ProgressTrack, Segmented,
                      ShadowLabel, StatusBadge, TitleBar, Theme, body_font)

APP_VERSION = "2.2.0"
MOOD_FOR_LANGUAGE = {"en": "day", "de": "night"}
STATUS_COLORS = {"other_variant": "#ffc94d", "current": "#3ddc84", "outdated": "#ffc94d", "incomplete": "#ffc94d", "legacy": "#ffc94d",
                 "unknown": "#ffc94d", "none": "#ff7a7a", "no_game": "#ff5d5d", "error": "#ff7a7a"}
SIZES = {"wide": (880, 760), "tall": (600, 890)}
SCREEN_MARGIN = 40   # tyle wolnego miejsca musi zostać na ekranie (pasek zadań, ramki)


class Bridge(QObject):
    """Most wątek roboczy → interfejs (sygnały są kolejkowane do wątku GUI)."""
    progress = Signal(float, str)
    status = Signal(int, object)
    done = Signal(str, object)
    failed = Signal(str, str)
    info = Signal(str, str)
    ask = Signal(object, object)      # (lista plików, pudełko z odpowiedzią) – pytanie „użyć mimo to?"
    finished = Signal()


def small_label(text: str, bold: bool = False, alpha: int = 215, size: float = 10.0) -> QLabel:
    label = QLabel(text)
    label.setFont(body_font(size, bold=bold))
    label.setStyleSheet(f"color: rgba(255,255,255,{alpha}); background: transparent;")
    return label


class MainWindow(QWidget):
    def __init__(self, base_url: str = RAW_URL):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window | Qt.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Where Winds Meet – Instalator")
        self.log = logs.setup(f"v{APP_VERSION}")
        app = QApplication.instance()
        if app is not None and "QToolTip" not in app.styleSheet():
            # dymki w stylu instalatora zamiast systemowych (jasnych)
            app.setStyleSheet(app.styleSheet() + """
                QToolTip { color: #ffffff; background-color: #141b36; border: 1px solid #ffc94d;
                           border-radius: 8px; padding: 7px 9px; font-size: 9.5pt; }""")
        self.layout_mode = self.initial_layout()
        self.win_w, self.win_h = SIZES[self.layout_mode]
        self.setFixedSize(self.win_w, self.win_h)
        self.base_url = base_url
        self.platform, self.language = "steam", "en"
        saved_variant = settings.load().get("variant")
        self.variant = saved_variant if saved_variant in VARIANTS else DEFAULT_VARIANT
        self.game_path: Optional[str] = None
        self.status: Optional[Status] = None
        self.busy = self.closing = False
        self.cancelled = threading.Event()
        self.generation = 0
        self.last_detail = ""

        Theme.hover_cursor = make_cursor(True)
        Theme.normal_cursor = make_cursor(False)
        Theme.icon = make_icon(64)
        self.setWindowIcon(QIcon(make_icon(256)))
        self.scene = SceneWidget(self, self.base_mood())
        self.scene.setGeometry(0, 0, self.win_w, self.win_h)
        self.scene.setCursor(Theme.normal_cursor)
        Theme.mood = self.scene.mood
        self._build_ui()
        self.overlay = FxOverlay(self.scene, self)
        self.overlay.setGeometry(0, 0, self.win_w, self.win_h)
        self.overlay.raise_()

        self.bridge = Bridge()
        self.bridge.progress.connect(self.on_progress)
        self.bridge.status.connect(self.on_status)
        self.bridge.done.connect(self.on_done)
        self.bridge.failed.connect(self.on_failed)
        self.bridge.info.connect(lambda title, text: self.show_message(title, text))
        self.bridge.ask.connect(self.on_ask)
        self.bridge.finished.connect(self.on_finished)

        self.scene.progress_source = self.track.displayed
        self.scene.hooks.append(self._frame)
        self.refresh_path()
        QTimer.singleShot(0, self.update_rails)

    def base_mood(self) -> str:
        """Motyw sceny: wariant fabularny = zima, pełny = dzień (EN) / noc (DE)."""
        if self.variant == "story":
            return "winter" if self.language == "en" else "winter_night"
        return MOOD_FOR_LANGUAGE[self.language]

    @staticmethod
    def initial_layout() -> str:
        """Pionowy jest domyślny; poziomy wybieramy, gdy ekran jest za niski albo użytkownik tak zdecydował."""
        saved = settings.load().get("layout")
        screen = QApplication.primaryScreen()
        room = screen.availableGeometry().height() if screen else 10_000
        fits_tall = room >= SIZES["tall"][1] + SCREEN_MARGIN
        if saved == "wide":
            return "wide"
        if saved == "tall" and fits_tall:
            return "tall"
        return "tall" if fits_tall else "wide"

    # ------------------------------------------------------------------ budowa UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self.scene)
        self.root_layout = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar("", self.scene)
        self.titlebar.btn_close.clicked.connect(self.request_close)
        self.titlebar.btn_layout.clicked.connect(self.toggle_layout)
        root.addWidget(self.titlebar)
        root.addSpacing(30)

        title_font = QFont()
        title_font.setFamilies(TITLE_FAMILIES)
        title_font.setPointSizeF(35)
        title_font.setBold(True)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0)
        self.title = ShadowLabel("Where Winds Meet", title_font, QColor("white"), self.scene)
        self.subtitle = ShadowLabel("INSTALATOR POLSKIEGO TŁUMACZENIA", body_font(10, bold=True, spacing=5.0),
                                    QColor(255, 255, 255, 235), self.scene)
        root.addWidget(self.title)
        root.addWidget(self.subtitle)
        root.addSpacing(12)

        body = QVBoxLayout()
        body.setContentsMargins(56, 0, 56, 0)
        body.setSpacing(0)
        self.body_layout = body
        root.addLayout(body)

        card = GlassCard(self.scene)
        grid = QGridLayout(card)
        grid.setContentsMargins(26, 18, 26, 16)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(7)
        self.card_grid = grid
        self.seg_platform = Segmented([("steam", "Steam"), ("launcher", "Epic / Launcher")], "steam", card)
        self.seg_language = Segmented([("en", "English"), ("de", "Deutsch")], "en", card)
        self.seg_platform.changed.connect(self.on_platform)
        self.seg_language.changed.connect(self.on_language)
        self.lbl_platform = small_label("PLATFORMA", True, 150, 8.5)
        self.lbl_language = small_label("JĘZYK GRY DO ZASTĄPIENIA", True, 150, 8.5)
        self.lbl_variant = small_label("WARIANT TŁUMACZENIA", True, 150, 8.5)
        self.variant_picker = VariantPicker([
            ("full", "Pełne", "Wszystko po polsku", "book", None),
            ("story", "Fabularne", "Fabuła po polsku, przedmioty EN", "scroll", "BETA"),
        ], self.variant, card)
        self.variant_picker.tips["story"] = (
            "Wersja w budowie – jeszcze niedopracowana.\n"
            "Wiele tekstów, które powinny być po polsku, jest wciąż po angielsku.\n"
            "Nazwy przedmiotów i menu celowo zostają po angielsku.")
        self.variant_picker.tips["full"] = "Pełne tłumaczenie: dialogi, opisy, przedmioty i menu po polsku."
        self.variant_picker.changed.connect(self.on_variant)
        self.hint = small_label("", False, 190, 9.5)
        self.hint.setContentsMargins(2, 6, 0, 4)     # oddech nad i pod podpowiedzią
        self.hint.setStyleSheet("color: rgba(255,255,255,190); background: transparent;")
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.pill = PathPill(card)
        self.btn_browse = GlowButton("Zmień folder", "ghost", height=38, size=9.5)
        self.btn_open = GlowButton("Otwórz", "ghost", height=38, size=9.5)
        self.btn_browse.setFixedWidth(116)
        self.btn_open.setFixedWidth(88)
        self.btn_browse.clicked.connect(self.browse_path)
        self.btn_open.clicked.connect(self.open_folder)
        path_row.addWidget(self.pill, 1)
        path_row.addWidget(self.btn_browse)
        path_row.addWidget(self.btn_open)
        self.path_row = path_row
        line = QFrame(card)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,40);")
        self.card_line = line
        self.badge = StatusBadge(card)
        body.addWidget(card)
        body.addSpacing(64)  # miejsce, w którym bohater skacze z tytułu na pasek (indeks 1, zmieniany w apply_layout)

        progress_card = GlassCard(self.scene)
        pv = QVBoxLayout(progress_card)
        pv.setContentsMargins(22, 16, 22, 10)
        pv.setSpacing(6)
        self.track = ProgressTrack(progress_card)
        self.detail = small_label("Gotowy.", False, 200, 9.5)
        self.detail.setAlignment(Qt.AlignCenter)
        pv.addWidget(self.track)
        pv.addWidget(self.detail)
        body.addWidget(progress_card)
        body.addSpacing(14)

        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setSpacing(12)
        self.btn_box = row
        self.btn_install = GlowButton("ZAINSTALUJ  /  AKTUALIZUJ", "primary", height=54, size=12.5)
        self.btn_launch = GlowButton("▶  URUCHOM GRĘ (PL)", "success", height=54, size=12)
        self.btn_install.clicked.connect(self.run_install)
        self.btn_launch.clicked.connect(self.run_launch)
        row.addWidget(self.btn_install, 3)
        row.addWidget(self.btn_launch, 2)
        body.addLayout(row)
        body.addSpacing(4)
        restore_row = QHBoxLayout()
        self.btn_restore = GlowButton("↺   PRZYWRÓĆ ORYGINALNE TŁUMACZENIE", "ghost", height=42, size=9.5)
        self.btn_restore.setFont(body_font(9.5, bold=True, spacing=0.6))
        self.btn_restore.setFixedWidth(330)
        self.btn_restore.clicked.connect(self.run_restore)
        restore_row.addStretch()
        restore_row.addWidget(self.btn_restore)
        restore_row.addStretch()
        body.addLayout(restore_row)
        root.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(40, 0, 40, 10)
        footer.setSpacing(12)
        self.tile_guide = IconTile("guide", "Poradnik Steam", self.scene)
        self.tile_support = IconTile("support", "Wesprzyj projekt", self.scene)
        self.tile_authors = IconTile("authors", "", self.scene)  # tooltip zastępuje wysuwane menu
        self.tile_guide.clicked.connect(lambda: webbrowser.open(STEAM_GUIDE_URL))
        self.tile_support.clicked.connect(lambda: webbrowser.open(COFFEE_URL))
        self.flyout = AuthorsFlyout(AUTHORS, self.scene)
        self.flyout.chosen.connect(self.on_author_link)
        self._flyout_hover = {"tile": False, "menu": False}
        self._flyout_timer = QTimer(self)
        self._flyout_timer.setSingleShot(True)
        self._flyout_timer.setInterval(260)
        self._flyout_timer.timeout.connect(self._flyout_check)
        self.tile_authors.hovered.connect(lambda on: self._flyout_hover_changed("tile", on))
        self.flyout.hovered.connect(lambda on: self._flyout_hover_changed("menu", on))
        version = small_label(f"v{APP_VERSION}", False, 120, 8.5)
        version.setFixedWidth(64)
        spacer = QWidget(self.scene)
        spacer.setFixedWidth(64)
        spacer_row = QHBoxLayout(spacer)
        spacer_row.setContentsMargins(0, 0, 0, 0)
        self.tile_logs = IconTile("logs", "Logi instalatora (przy zgłaszaniu problemu)", spacer, size=38)
        spacer_row.addStretch()
        spacer_row.addWidget(self.tile_logs)
        self.log_panel = LogPanel(self, self.log_context)   # rodzic = okno, żeby leżał nad warstwą z bohaterem
        self.tile_logs.clicked.connect(self.toggle_logs)
        footer.addWidget(version)
        footer.addStretch()
        for tile in (self.tile_guide, self.tile_support, self.tile_authors):
            footer.addWidget(tile)
        footer.addStretch()
        footer.addWidget(spacer)
        root.addLayout(footer)
        self.update_hint()
        self.apply_layout(self.layout_mode, initial=True)

    # ------------------------------------------------------------------ układ okna
    def toggle_layout(self) -> None:
        if not self.busy:
            self.apply_layout("tall" if self.layout_mode == "wide" else "wide")

    def apply_layout(self, mode: str, initial: bool = False) -> None:
        """Przestawia te same widgety: poziomy 880×720 albo pionowy 600×880 (jak w starym instalatorze)."""
        tall = mode == "tall"
        self.layout_mode = mode
        self.win_w, self.win_h = SIZES[mode]
        grid = self.card_grid
        while grid.count():
            grid.takeAt(0)
        if tall:
            grid.setContentsMargins(22, 18, 22, 20)
            grid.addWidget(self.lbl_platform, 0, 0)
            grid.addWidget(self.seg_platform, 0, 1, Qt.AlignRight)
            grid.addWidget(self.lbl_language, 1, 0)
            grid.addWidget(self.seg_language, 1, 1, Qt.AlignRight)
            grid.setColumnStretch(0, 1)
        else:
            grid.setContentsMargins(26, 18, 26, 20)
            grid.addWidget(self.lbl_platform, 0, 0)
            grid.addWidget(self.lbl_language, 0, 1)
            grid.addWidget(self.seg_platform, 1, 0)
            grid.addWidget(self.seg_language, 1, 1)
            grid.setColumnStretch(0, 0)
        grid.addWidget(self.lbl_variant, 2, 0, 1, 2)
        grid.addWidget(self.variant_picker, 3, 0, 1, 2)
        grid.addWidget(self.hint, 4, 0, 1, 2)
        grid.addLayout(self.path_row, 5, 0, 1, 2)
        grid.addWidget(self.card_line, 6, 0, 1, 2)
        grid.addWidget(self.badge, 7, 0, 1, 2)
        margin = 32 if tall else 56
        self.body_layout.setContentsMargins(margin, 0, margin, 0)
        self.body_layout.itemAt(1).spacerItem().changeSize(0, 50 if tall else 40)

        grid.setVerticalSpacing(9 if tall else 7)
        self.lbl_variant.setVisible(True)
        self.body_layout.invalidate()
        self.root_layout.itemAt(1).spacerItem().changeSize(0, 20 if tall else 22)
        if tall:
            self.btn_box.setDirection(QBoxLayout.TopToBottom)
            self.btn_box.setSpacing(8)
            self.btn_box.setStretch(0, 0)
            self.btn_box.setStretch(1, 0)
            self.btn_launch.setFixedHeight(50)
            self.btn_restore.setFixedWidth(self.win_w - 2 * margin)
        else:
            self.btn_box.setDirection(QBoxLayout.LeftToRight)
            self.btn_box.setSpacing(12)
            self.btn_box.setStretch(0, 3)
            self.btn_box.setStretch(1, 2)
            self.btn_launch.setFixedHeight(54)
            self.btn_restore.setFixedWidth(330)
        self.titlebar.btn_layout.tall = not tall   # ikona pokazuje układ docelowy
        self.titlebar.btn_layout.update()
        if hasattr(self, "overlay"):
            centre = self.frameGeometry().center() if self.isVisible() else None
            self.setFixedSize(self.win_w, self.win_h)
            self.scene.setGeometry(0, 0, self.win_w, self.win_h)
            self.overlay.setGeometry(0, 0, self.win_w, self.win_h)
            if centre is not None:
                geo = self.frameGeometry()
                geo.moveCenter(centre)
                area = (self.screen() or QApplication.primaryScreen()).availableGeometry()
                self.move(max(area.left(), min(geo.x(), area.right() - self.win_w)),
                          max(area.top(), min(geo.y(), area.bottom() - self.win_h)))
            self.flyout.hide()
            self.flyout.t = 0.0
            hero = self.scene.hero
            hero.placed, hero.jump, hero.rail = False, None, "title"
        self.scene.layout().activate()
        QTimer.singleShot(0, self.update_rails)
        QTimer.singleShot(80, self.update_rails)
        if hasattr(self, "log_panel"):
            QTimer.singleShot(90, self.place_log_panel)
        if not initial:
            settings.save(layout=mode)

    def log_context(self) -> dict:
        status = self.status.state if self.status else "—"
        return {"Instalator": f"v{APP_VERSION}", "Platforma": self.platform, "Język": self.language,
                "Wariant": self.variant, "Folder gry": self.game_path or "nie wykryto", "Status": status}

    def place_log_panel(self) -> None:
        footer_top = self.tile_guide.mapTo(self.scene, QPoint(0, 0)).y() - 10
        height = int(self.win_h * (0.50 if self.layout_mode == "tall" else 0.55))
        margin = 18
        self.log_panel.place(QRect(margin, max(46, footer_top - height), self.win_w - 2 * margin,
                                   min(height, footer_top - 46)))

    def toggle_logs(self) -> None:
        self.place_log_panel()
        self.log_panel.toggle()

    def _flyout_hover_changed(self, who: str, on: bool) -> None:
        self._flyout_hover[who] = on
        if on:
            self._flyout_timer.stop()
            self.open_flyout()
        else:
            self._flyout_timer.start()

    def on_author_link(self, kind: str, value: str) -> None:
        if kind == "steam":
            webbrowser.open(value)
        else:
            QApplication.clipboard().setText(value)
            self.flyout.flash(f"Skopiowano nick Discord: {value}")

    def open_flyout(self) -> None:
        tile = self.tile_authors.mapTo(self.scene, QPoint(0, 0))
        x = min(max(8, tile.x() + self.tile_authors.width() // 2 - self.flyout.width() // 2), self.win_w - self.flyout.width() - 8)
        self.flyout.move(x, tile.y() - self.flyout.height() - 6)
        self.flyout.open()

    def _flyout_check(self) -> None:
        if not any(self._flyout_hover.values()):
            self.flyout.close_menu()

    # --------------------------------------------------------------------- szyny
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.update_rails)

    def update_rails(self) -> None:
        s = self.scene
        origin = self.title.mapTo(s, QPoint(0, 0))
        x0 = origin.x() + self.title.text_left()
        tp = self.track.mapTo(s, QPoint(0, 0))
        s.hero.set_rails({
            "title": (x0 + 6, x0 + self.title.text_width() - 6, origin.y() + self.title.cap_top()),
            "bar": (tp.x() + 6, tp.x() + self.track.width() - 6, tp.y() + 3),
            "corner": self.close_button_center(),
        })

    def close_button_center(self) -> tuple:
        b = self.titlebar.btn_close
        c = b.mapTo(self.scene, QPoint(b.width() // 2, b.height() // 2))
        return (float(c.x()), float(c.y()))

    def _frame(self, dt: float) -> None:
        self.track.advance(dt)
        self.track.busy = self.busy
        self.badge.advance(dt)
        if self.scene.hero.rails.get("bar") is None:
            self.update_rails()

    # ------------------------------------------------------------- ścieżka i status
    def german_pack_missing(self) -> bool:
        """Pakiet niemiecki pobiera dopiero gra (po wybraniu języka) – bez niego nie ma jeszcze czego podmieniać."""
        if self.language != "de" or not self.game_path:
            return False
        return not (Path(self.game_path) / core.DIFF_DIR / core.expected_names("de")["diff"]).exists()

    def update_hint(self) -> None:
        if self.german_pack_missing():
            self.hint.setText("Najpierw uruchom grę i wybierz Deutsch, by pobrać pakiet językowy.")
        elif self.variant == "story":
            self.hint.setText(f"Wersja w budowie. Po instalacji wybierz w grze język: {LANGUAGES[self.language]}.")
        else:
            self.hint.setText(f"Po instalacji wybierz w ustawieniach gry język: {LANGUAGES[self.language]}.")

    def show_german_notice(self) -> None:
        if self.language == "de" and not self.busy and self.german_pack_missing():
            self.show_message(
                "Najpierw pobierz pakiet niemiecki",
                "Pakiet języka niemieckiego pobiera dopiero sama gra. Zanim zainstalujesz spolszczenie:\n\n"
                "1.  Uruchom grę.\n"
                "2.  W ustawieniach gry wybierz język Deutsch i poczekaj na pobranie pakietu.\n"
                "3.  Zamknij grę i wróć do instalatora.\n\n"
                "Bez tego instalator nie ma jeszcze czego podmienić.")

    def refresh_path(self) -> None:
        saved = settings.load().get(f"game_path_{self.platform}")
        if saved and self.platform == "launcher" and is_steam_path(saved):
            self.log.warning("Pomijam zapamiętany folder launchera, bo to instalacja ze Steam: %s", saved)
            saved = None
        if saved and is_valid_game_path(saved):
            self.game_path = saved
            self.log.info("Folder gry (%s) z ustawień: %s", self.platform, saved)
        else:
            self.game_path = find_game_path(self.platform)
            self.log.info("Folder gry (%s) wykryty automatycznie: %s", self.platform, self.game_path or "BRAK")
        if self.game_path:
            self.log.info("Zawartość: %s", describe_game_folder(self.game_path))
        self.pill.set_path(self.game_path)
        self.refresh_status()

    def refresh_status(self) -> None:
        self.update_hint()
        self.generation += 1
        generation, path, language, variant = self.generation, self.game_path, self.language, self.variant
        base = variant_url(self.base_url, variant)
        self.badge.set_status("Sprawdzanie…", "#9aa4c0", "", True)
        self.apply_enabled()

        def work():
            server = fetch_server_version(base)
            try:
                if path:
                    root = Path(path)
                    journal = Journal(root)
                    if journal.pending.exists():
                        with game_lock(root):
                            journal.recover()
                status = compute_status(Path(path) if path else None, language, server, variant)
            except (OSError, OperationError) as error:
                status = Status("error", "SPRAWDŹ STAN INSTALACJI", None, server)
                status.sub = str(error)
            self.bridge.status.emit(generation, status)

        threading.Thread(target=work, daemon=True).start()

    def on_status(self, generation: int, status: Status) -> None:
        if generation != self.generation:
            return
        self.status = status
        self.log.info("Status (%s/%s/%s): %s | lokalnie=%s serwer=%s", self.language, self.variant, self.platform,
                      status.state, status.local_version, status.server_version)
        sub = getattr(status, "sub", None)
        if sub is None:
            sub = ("Wskaż folder gry." if status.state == "no_game" else
                   f"Najnowsza wersja na serwerze: {status.server_version or 'brak połączenia'}")
        self.badge.set_status(status.message, STATUS_COLORS.get(status.state, "#9aa4c0"), sub,
                              status.state in ("outdated", "incomplete", "legacy", "other_variant"))
        self.apply_enabled()

    def apply_enabled(self) -> None:
        free = not self.busy
        state = self.status.state if self.status else None
        self.seg_platform.setEnabled(free)
        self.seg_language.setEnabled(free)
        self.variant_picker.setEnabled(free)
        self.btn_browse.setEnabled(free)
        self.btn_open.setEnabled(free and bool(self.game_path))
        self.btn_install.setEnabled(free and bool(self.game_path))
        self.btn_launch.setEnabled(free and state in ("current", "outdated", "unknown", "other_variant"))
        self.btn_restore.setEnabled(free and state in ("current", "outdated", "unknown", "incomplete", "other_variant"))

    # ---------------------------------------------------------------- akcje użytkownika
    def on_platform(self, value: str) -> None:
        self.platform = value
        self.refresh_path()

    def on_language(self, value: str) -> None:
        self.language = value
        self.scene.set_mood(self.base_mood())
        self.update_hint()
        self.refresh_status()
        if value == "de" and self.german_pack_missing():
            QTimer.singleShot(250, self.show_german_notice)

    def confirm_story_variant(self) -> bool:
        dialog = MessageDialog(
            self, "Wariant fabularny (BETA)",
            "Ten wariant jest jeszcze w budowie i nie jest dopracowany.\n\n"
            "Przetłumaczone są głównie dialogi i opisy fabularne, ale wiele tekstów, które powinny być po polsku, "
            "wciąż jest po angielsku. Nazwy przedmiotów i elementy menu celowo pozostają po angielsku.\n\n"
            "Jeśli chcesz kompletnego tłumaczenia, wybierz wariant Pełne.",
            "warn", ok_text="Rozumiem, wybieram", cancel_text="Wróć do Pełnego")
        return bool(dialog.exec())

    def on_variant(self, value: str) -> None:
        if value == "story" and not self.closing and not self.confirm_story_variant():
            self.variant_picker.set_value("full", emit=False)
            return
        self.variant = value
        settings.save(variant=value)
        self.scene.set_mood(self.base_mood())
        self.update_hint()
        self.refresh_status()

    def browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Wskaż folder gry Where Winds Meet (np. Where Winds Meet, wwm_standard lub wwm_lite)")
        if not path:
            return
        root = resolve_game_root(path)
        self.log.info("Ręcznie wskazano: %s -> rozpoznany folder gry: %s", path, root or "BRAK")
        if root is not None and self.platform == "launcher" and is_steam_path(root):
            self.log.warning("Przy platformie launcher wskazano folder ze Steam: %s", root)
            self.show_message(
                "To jest wersja ze Steam",
                "Wskazany folder to instalacja gry ze Steam, a wybrana platforma to Epic / Launcher.\n\n"
                "Jeśli grasz przez Steam – przełącz platformę na Steam.\n"
                "Jeśli grasz przez oficjalny launcher – wskaż folder „wwm_standard” lub „wwm_lite”.", "error")
            return
        if root is not None:
            self.game_path = str(root)
            settings.save(**{f"game_path_{self.platform}": self.game_path})
            self.log.info("Zawartość: %s", describe_game_folder(root))
            self.pill.set_path(self.game_path)
            self.refresh_status()
        else:
            self.show_message(
                "Nie znaleziono gry",
                "We wskazanym folderze ani obok niego nie znaleziono plików gry.\n\n"
                "Wskaż folder instalacji gry:\n"
                "• Steam / Epic – folder „Where Winds Meet” (z folderem Package),\n"
                "• oficjalny launcher – folder „wwm_standard” lub „wwm_lite” (z folderem LocalData).\n\n"
                "Jeśli gra była zainstalowana przed chwilą, uruchom ją raz, żeby pobrała pliki.", "error")

    def open_folder(self) -> None:
        opener = getattr(os, "startfile", None)
        if self.game_path and opener:
            opener(self.game_path)

    def show_message(self, title: str, text: str, kind: str = "info", extra=None) -> None:
        if self.closing:
            return
        MessageDialog(self, title, text, kind, extra).exec()

    def run_install(self) -> None:
        self.begin_work("install")

    def run_restore(self) -> None:
        self.begin_work("restore")

    def run_launch(self) -> None:
        self.begin_work("launch")

    # ------------------------------------------------------------------ praca w tle
    def begin_work(self, kind: str) -> None:
        if self.busy:
            return
        if not self.game_path:
            self.show_message("Błąd", "Wskaż folder gry przed rozpoczęciem.", "error")
            return
        self.busy = True
        self.cancelled.clear()
        self.apply_enabled()
        self.scene.set_mood("summer" if kind == "launch" else self.base_mood())   # gra startuje = lato
        self.track.shown = 0.0
        self.track.set_value(0.0)
        self.scene.hero.set_mode("bar")
        threading.Thread(target=self._worker, args=(kind, self.game_path, self.platform, self.language, self.variant),
                         daemon=True).start()

    def _worker(self, kind: str, path: str, platform: str, language: str, variant: str = DEFAULT_VARIANT) -> None:
        bridge = self.bridge
        def confirm(names: list) -> bool:
            """Wątek roboczy czeka na odpowiedź użytkownika (z możliwością przerwania)."""
            box = {"answer": False, "event": threading.Event()}
            bridge.ask.emit(names, box)
            while not box["event"].wait(0.2):
                if self.cancelled.is_set():
                    return False
            return bool(box["answer"])

        engine = Engine(path, language, bridge.progress.emit, self.cancelled, self.base_url,
                        notify=lambda text: bridge.info.emit("Informacja", text), confirm=confirm, variant=variant)
        try:
            if kind == "install":
                engine.install()
                bridge.done.emit("install", language)
            elif kind == "restore":
                bridge.done.emit("restore", engine.restore())
            else:
                bridge.done.emit("launch", engine.launch(path, platform))
        except Cancelled:
            self.log.info("%s: anulowano", kind)
            bridge.done.emit("cancelled", None)
        except OperationError as error:
            self.log.error("%s nie powiodło się: %s", kind, error)
            bridge.failed.emit("Błąd", str(error))
        except PermissionError:
            self.log.exception("Brak uprawnień podczas %s", kind)
            bridge.failed.emit("Brak uprawnień", "Odmowa dostępu! Uruchom instalator jako administrator "
                               "(prawy przycisk myszy → Uruchom jako administrator) i upewnij się, że gra jest wyłączona.")
        except requests.RequestException as error:
            self.log.exception("Błąd sieci podczas %s", kind)
            bridge.failed.emit("Błąd sieci", f"Sprawdź połączenie z internetem.\n\n{error}")
        except OSError as error:
            self.log.exception("Błąd pliku podczas %s", kind)
            bridge.failed.emit("Błąd pliku", f"{error}\n\nUpewnij się, że gra jest wyłączona.")
        except Exception as error:   # nieprzewidziany błąd: pełny ślad w logu, czytelny komunikat w oknie
            self.log.exception("Nieoczekiwany błąd podczas %s", kind)
            bridge.failed.emit("Nieoczekiwany błąd", f"{error}\n\nSzczegóły są w logach (ikona w stopce) – "
                               "skopiuj je i wyślij na Discordzie.")
        finally:
            bridge.finished.emit()

    def ask_use_anyway(self, names: list) -> bool:
        dialog = MessageDialog(
            self, "Nowsza wersja gry",
            "Spolszczenie nie zostało jeszcze zaktualizowane do najnowszej wersji gry "
            f"(plik: {', '.join(names)}).\n\n"
            "Możesz użyć spolszczenia mimo to: część tekstów może być niepełna lub zostać w oryginalnym języku, "
            "reszta będzie po polsku. Oryginał możesz w każdej chwili przywrócić.\n\nUżyć mimo to?",
            "warn", ok_text="Użyj mimo to", cancel_text="Anuluj")
        return bool(dialog.exec())

    def on_ask(self, names, box) -> None:
        answer = False
        try:
            if not self.closing:
                answer = self.ask_use_anyway(names)
        finally:
            box["answer"] = answer
            box["event"].set()

    def on_progress(self, value: float, text: str) -> None:
        self.track.set_value(value)
        self.detail.setText(text)
        self.last_detail = text

    def celebrate(self, seconds: float) -> None:
        self.scene.hero.set_mode("celebrate")
        QTimer.singleShot(int(seconds * 1000), lambda: None if self.busy else self.scene.hero.set_mode("patrol"))

    def on_done(self, kind: str, payload) -> None:
        if kind == "cancelled":
            self.detail.setText("Anulowano operację.")
            self.track.set_value(0.0)
        elif kind == "install":
            self.scene.set_mood("dawn" if self.variant == "full" else self.base_mood())
            self.celebrate(7.0)
            self.track.set_value(1.0)
            self.detail.setText(f"Zainstalowano. W grze wybierz {LANGUAGES[payload]}.")
            # krótka zwłoka, żeby przejście nastroju na świt i bieg bohatera było widać przed oknem
            QTimer.singleShot(1800, lambda: self.show_message(
                "Sukces!", "Dziękuję za zainstalowanie spolszczenia.\n\nJeżeli podoba Ci się projekt, możesz go wesprzeć.",
                "success", ("Postaw kawę dla Arima", lambda: webbrowser.open(COFFEE_URL))))
        elif kind == "restore":
            if payload:
                self.detail.setText("Przywracanie wymaga sprawdzenia plików.")
                self.track.set_value(0.0)
                self.show_message("Przywracanie niekompletne",
                                  f"Nie ruszono plików: {', '.join(payload)}.\nMogły zostać zmienione przez aktualizację gry. "
                                  "Sprawdź spójność plików gry w Steam lub launcherze.", "error")
            else:
                self.detail.setText("Przywrócono oryginalne pliki.")
                self.show_message("Przywrócono", "Przywrócono oryginalne pliki wybranego języka.")
        elif kind == "launch":
            self.track.set_value(1.0)
            self.log.info("Uruchomienie zakończone: %s", payload)
            QTimer.singleShot(400, self.offer_auto_close)

    COUNTDOWN = 10

    def offer_auto_close(self) -> None:
        """Spolszczenie siedzi już w grze: samuraj się żegna, a mały pasek odlicza do zamknięcia."""
        if self.closing or self.busy:
            self.celebrate(3.0)
            return
        self.update_rails()
        self.scene.hero.start_farewell(self.COUNTDOWN)
        toast = CountdownToast(self, self.COUNTDOWN)
        self._countdown = toast
        toast.finished_countdown.connect(self._farewell_strike)
        toast.cancelled.connect(self._farewell_cancelled)
        tile = self.tile_guide.mapTo(self, QPoint(0, 0))
        toast.start((self.win_w - toast.width()) // 2, tile.y() + self.tile_guide.height() // 2 - toast.height() // 2)

    def _farewell_cancelled(self) -> None:
        self.log.info("Użytkownik zostawił instalator otwarty")
        self.scene.hero.cancel_farewell()

    def _farewell_strike(self) -> None:
        """Zero: samuraj przecina krzyżyk, okno rozsypuje się i znika."""
        self.log.info("Automatyczne zamknięcie instalatora po udanym wstrzyknięciu")
        self.scene.hero.strike()
        cx, cy = self.close_button_center()

        def cut():
            self.overlay.slash_streak(cx, cy)
            self.overlay.shatter(cx, cy)
            self._fade = QVariantAnimation(self, duration=750, startValue=1.0, endValue=0.0)
            self._fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
            self._fade.finished.connect(self.close)
            self._fade.start()

        QTimer.singleShot(300, cut)

    def on_failed(self, title: str, text: str) -> None:
        self.detail.setText("Operacja nie powiodła się.")
        self.track.set_value(0.0)
        self.scene.hero.set_mode("patrol")
        self.show_message(title, text, "error")

    def on_finished(self) -> None:
        self.busy = False
        if self.closing:
            self.close()
            return
        if self.scene.hero.mode == "bar":
            self.scene.hero.set_mode("patrol")
        self.refresh_status()

    def changeEvent(self, event):
        # zminimalizowane okno nie animuje sceny – zero zużycia procesora w tle
        if event.type() == QEvent.WindowStateChange:
            if self.isMinimized():
                self.scene.timer.stop()
            elif not self.scene.timer.isActive():
                self.scene._last = time.perf_counter()
                self.scene.timer.start(16)
        super().changeEvent(event)

    # ------------------------------------------------------------------- zamykanie
    def request_close(self) -> None:
        if self.busy:
            self.closing = True
            self.cancelled.set()
            self.detail.setText("Anulowanie operacji i odzyskiwanie plików…")
        else:
            self.close()

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
            self.request_close()
        else:
            event.accept()
            QApplication.quit()


def main() -> int:
    if sys.stderr is None:  # EXE bez konsoli
        sys.stderr = io.StringIO()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("arima.wwm.spolszczenie.installer")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Where Winds Meet – Instalator spolszczenia")
    window = MainWindow()
    window.show()
    return app.exec()
