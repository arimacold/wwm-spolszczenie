"""Testy dymne okna (Qt offscreen): przepływ instalacji, zmiana nastroju, zamknięcie w trakcie pracy."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

import wwmpl.app as appmod
import wwmpl.core as core
import wwmpl.operations as operations


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@pytest.fixture
def window(qapp, world, server, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(appmod, "SCREEN_MARGIN", -200)   # wirtualny ekran testowy ma 800 px — udajemy wysoki monitor
    world.publish()
    world.install_game_files("en")
    world.install_game_files("de")
    monkeypatch.setattr(appmod, "find_game_path", lambda platform: str(world.game))
    monkeypatch.setattr(appmod.MainWindow, "show_message", lambda self, *a, **k: None)  # bez blokujących dialogów
    monkeypatch.setattr(appmod.MainWindow, "ask_use_anyway", lambda self, names: False)
    w = appmod.MainWindow(base_url=server)
    w.show()
    assert pump(lambda: w.status is not None)
    yield w
    w.busy = False
    w.closing = False
    w.scene.timer.stop()
    w.hide()
    w.deleteLater()


def test_initial_status_and_buttons(window):
    assert window.status.state == "none"
    assert window.btn_install.isEnabled()
    assert not window.btn_launch.isEnabled() and not window.btn_restore.isEnabled()


def test_language_switch_changes_mood(window):
    window.seg_language.set_value("de")
    assert window.language == "de" and window.scene.mood.name == "night"
    window.seg_language.set_value("en")
    assert window.scene.mood.name == "day"


def test_install_then_restore_through_the_window(window, world):
    window.run_install()
    assert pump(lambda: not window.busy and window.status and window.status.state == "current")
    assert window.scene.mood.name == "dawn"          # po instalacji: świt
    assert window.scene.hero.mode == "celebrate"
    assert world.pkg("en").read_bytes() == world.translated("en", "main")
    assert window.btn_launch.isEnabled() and window.btn_restore.isEnabled()
    window.run_restore()
    assert pump(lambda: not window.busy and window.status and window.status.state == "none")
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_closing_during_work_cancels_and_restores(window, world, monkeypatch):
    def slow_install(self):
        self.progress(0.1, "powoli…")
        deadline = time.time() + 10
        while time.time() < deadline:
            self.check_cancelled()
            time.sleep(0.02)

    monkeypatch.setattr(operations.Engine, "install", slow_install)
    window.run_install()
    assert pump(lambda: window.busy and window.detail.text() == "powoli…")
    window.request_close()
    assert window.closing
    assert pump(lambda: not window.busy and not window.isVisible())
    assert world.pkg("en").read_bytes() == world.original("en", "main")


def test_error_path_keeps_window_usable(window, world):
    world.publish(tamper=world.name("en", "main"))       # uszkodzony plik na serwerze = prawdziwy błąd
    window.run_install()
    assert pump(lambda: not window.busy and window.detail.text() == "Operacja nie powiodła się.")
    assert window.btn_install.isEnabled()
    assert window.scene.hero.mode == "patrol"


def test_newer_game_asks_and_declining_cancels(window, world, monkeypatch):
    asked = []
    monkeypatch.setattr(appmod.MainWindow, "ask_use_anyway", lambda self, names: asked.append(names) or False)
    world.pkg("en").write_bytes(b"gra po aktualizacji")
    window.run_install()
    assert pump(lambda: not window.busy and window.detail.text() == "Anulowano operację.")
    assert asked == [[world.name("en", "main")]]
    assert world.pkg("en").read_bytes() == b"gra po aktualizacji"
    assert window.btn_install.isEnabled()


def test_newer_game_asks_and_accepting_installs(window, world, monkeypatch):
    monkeypatch.setattr(appmod.MainWindow, "ask_use_anyway", lambda self, names: True)
    world.pkg("en").write_bytes(b"gra po aktualizacji")
    window.run_install()
    assert pump(lambda: not window.busy and window.detail.text().startswith("Zainstalowano"))
    assert world.pkg("en").read_bytes() == world.translated("en", "main")


def test_german_pack_notice(window, world, monkeypatch):
    shown = []
    monkeypatch.setattr(appmod.MainWindow, "show_message", lambda self, title, *a, **k: shown.append(title))
    world.diff("de").unlink(missing_ok=True)                 # gra nie pobrała jeszcze pakietu niemieckiego
    window.on_language("de")
    assert "Najpierw uruchom grę" in window.hint.text()
    assert pump(lambda: shown == ["Najpierw pobierz pakiet niemiecki"], 2)
    window.on_language("en")
    assert "Po instalacji" in window.hint.text()
    world.diff("de").parent.mkdir(parents=True, exist_ok=True)
    world.diff("de").write_bytes(world.original("de", "diff"))   # pakiet pobrany – bez komunikatu
    shown.clear()
    window.on_language("de")
    pump(lambda: False, 0.5)
    assert shown == [] and "Po instalacji" in window.hint.text()


def _inside(window):
    """Wszystkie widoczne widgety muszą mieścić się w oknie i nie wystawać poza kartę/okno."""
    outside = []
    for child in window.scene.findChildren(QWidget):
        if child is window.flyout or not child.isVisible():
            continue
        top_left = child.mapTo(window.scene, child.rect().topLeft())
        right, bottom = top_left.x() + child.width(), top_left.y() + child.height()
        if top_left.x() < 0 or top_left.y() < 0 or right > window.width() + 1 or bottom > window.height() + 1:
            outside.append((type(child).__name__, top_left.x(), top_left.y(), right, bottom))
    return outside


def test_layouts_switch_and_everything_fits(window):
    from wwmpl import settings
    assert window.layout_mode == "tall" and (window.width(), window.height()) == (600, 830) and not _inside(window)
    window.toggle_layout()
    pump(lambda: False, 0.3)
    assert window.layout_mode == "wide" and (window.width(), window.height()) == (880, 720)
    assert not _inside(window), _inside(window)
    assert window.scene.width() == 880 and window.overlay.width() == 880
    rails = window.scene.hero.rails
    assert 0 < rails["title"][0] < rails["title"][1] < 880 and 0 < rails["bar"][0] < rails["bar"][1] < 880
    assert settings.load()["layout"] == "wide"          # wybór jest zapamiętany
    assert window.btn_install.y() == window.btn_launch.y()
    window.toggle_layout()
    pump(lambda: False, 0.3)
    # przyciski ułożone pionowo, pełna szerokość
    assert window.layout_mode == "tall" and window.btn_install.y() < window.btn_launch.y() < window.btn_restore.y()
    assert not _inside(window)


def test_layout_is_restored_on_start(qapp, world, server, monkeypatch, tmp_path):
    from wwmpl import settings
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(appmod, "SCREEN_MARGIN", -200)
    settings.save(layout="wide")
    monkeypatch.setattr(appmod, "find_game_path", lambda platform: None)
    w = appmod.MainWindow(base_url=server)
    w.show()
    pump(lambda: False, 0.3)
    assert (w.width(), w.height()) == (880, 720) and not _inside(w)
    w.scene.timer.stop()
    w.hide()


def test_titlebar_buttons_take_the_press_and_close_works(window):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    started = []
    window.titlebar.mousePressEvent = lambda e: started.append(True)   # tak wygląda start przeciągania okna
    for button in (window.titlebar.btn_close, window.titlebar.btn_min, window.titlebar.btn_layout):
        press = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), button.mapToGlobal(QPointF(5, 5)),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier, QPointingDevice.primaryPointingDevice())
        press.setAccepted(False)
        QApplication.sendEvent(button, press)
        assert press.isAccepted()
    assert not started
    from PySide6.QtTest import QTest
    QTest.mouseClick(window.titlebar.btn_close, Qt.LeftButton, pos=QPointF(8, 8).toPoint())
    assert pump(lambda: not window.isVisible(), 2)


def test_low_screen_falls_back_to_wide(qapp, monkeypatch, tmp_path):
    from wwmpl import settings
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata2"))
    monkeypatch.setattr(appmod, "SCREEN_MARGIN", -200)
    assert appmod.MainWindow.initial_layout() == "tall"                 # domyślnie pionowy
    monkeypatch.setattr(appmod, "SCREEN_MARGIN", 100_000)               # ekran „za niski"
    assert appmod.MainWindow.initial_layout() == "wide"
    settings.save(layout="tall")
    assert appmod.MainWindow.initial_layout() == "wide"                 # zapamiętany pion nie wymusza okna większego niż ekran


def test_hero_acts_and_planting_flag(qapp):
    from PySide6.QtGui import QImage, QPainter, QColor
    from wwmpl.character import Hero
    h = Hero()
    h.set_rails({"title": (20, 400, 100), "bar": (20, 400, 100)})
    seen = set()
    for _ in range(60 * 90):                      # 90 s patrolu: pojawiają się różne scenki, bez wyjątków
        h.update(1 / 60)
        if h.act:
            seen.add(h.act)
    assert len(seen) >= 3
    h.set_mode("celebrate"); h.set_progress(1.0)
    for _ in range(60 * 4):
        h.update(1 / 60)
    assert h.plant_progress() == 1.0
    img = QImage(300, 150, QImage.Format_ARGB32); img.fill(QColor("black"))
    p = QPainter(img)
    for act in (None, "wave", "bow", "twirl", "slash"):
        h.act, h.act_t, h.act_dur = act, 0.5, 1.0
        h.draw(p, QColor("#2f6f8f"), QColor("#d6403f"))
    p.end()
    h.set_mode("patrol")
    assert h.plant_progress() == 0.0               # po zmianie trybu flaga wraca do ręki
