"""Własne widgety w stylu „szkło + wiatr": przyciski, przełączniki, pasek postępu, status, okna dialogowe."""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BODY_FONT = "Segoe UI"
TITLE_FAMILIES = ["Palatino Linotype", "Book Antiqua", "Georgia", "Times New Roman", "serif"]


class Theme:
    """Globalny dostęp do bieżącego nastroju sceny (kolory akcentu) i kursorów."""
    mood = None
    hover_cursor = None
    normal_cursor = None
    icon: Optional[QPixmap] = None

    @classmethod
    def color(cls, key: str, alpha: float = 1.0) -> QColor:
        if cls.mood is not None:
            return cls.mood.color(key, alpha)
        c = QColor("#3b9be0")
        c.setAlphaF(alpha)
        return c


def body_font(size: float, bold: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont(BODY_FONT)
    f.setPointSizeF(size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def with_alpha(c: QColor, a: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, a)))
    return out


class ShadowLabel(QWidget):
    """Tekst z miękkim cieniem i obrysem – czytelny na każdym tle sceny.
    Wyśrodkowanie liczone po rzeczywistym obrysie liter (nie po szerokości z odstępami),
    opcjonalnie z pionowym gradientem (np. biało-czerwonym)."""

    def __init__(self, text: str, font: QFont, color: QColor = QColor("white"), parent=None, gradient=None):
        super().__init__(parent)
        self.text, self._font, self.color, self.gradient = text, font, color, gradient
        self._cache: Optional[QPixmap] = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedHeight(int(QFontMetrics(font).height() * 1.25))
        self._path = QPainterPath()
        self._path.addText(0, 0, font, text)
        self._ink = self._path.boundingRect()

    def _baseline(self) -> float:
        fm = QFontMetrics(self._font)
        return (self.height() - fm.height()) / 2 + fm.ascent()

    def text_width(self) -> float:
        return self._ink.width()

    def text_left(self) -> float:
        return (self.width() - self._ink.width()) / 2

    def cap_top(self) -> float:
        """Górna krawędź najwyższych liter (w układzie widgetu)."""
        return self._baseline() + self._ink.top()

    def _render(self) -> QPixmap:
        """Tekst z obrysem jest drogi w rysowaniu, więc renderujemy go raz do bufora."""
        dpr = self.devicePixelRatioF()
        pixmap = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.translate(self.text_left() - self._ink.left(), self._baseline())
        for width, alpha, dy in ((7, 0.10, 3), (4.5, 0.18, 2), (2.5, 0.28, 1)):
            p.setPen(QPen(QColor(8, 14, 40, int(255 * alpha)), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._path.translated(0, dy))
        p.setPen(Qt.NoPen)
        if self.gradient:
            g = QLinearGradient(0, self._ink.top(), 0, self._ink.bottom())
            for stop, color in self.gradient:
                g.setColorAt(stop, QColor(color))
            p.setBrush(QBrush(g))
        else:
            p.setBrush(self.color)
        p.drawPath(self._path)
        p.end()
        return pixmap

    def resizeEvent(self, event):
        self._cache = None

    def paintEvent(self, event):
        if self._cache is None:
            self._cache = self._render()
        QPainter(self).drawPixmap(0, 0, self._cache)


class GlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(14, 20, 40, 212))
        g.setColorAt(1, QColor(8, 12, 28, 226))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.2))
        p.drawRoundedRect(r, 16, 16)
        top = QLinearGradient(0, r.top(), r.width(), r.top())
        top.setColorAt(0, with_alpha(Theme.color("accent2"), 0.0))
        top.setColorAt(0.5, with_alpha(Theme.color("accent2"), 0.9))
        top.setColorAt(1, with_alpha(Theme.color("accent2"), 0.0))
        p.setPen(QPen(QBrush(top), 1.6))
        p.drawLine(QPointF(r.left() + 24, r.top()), QPointF(r.right() - 24, r.top()))


class GlowButton(QPushButton):
    def __init__(self, text: str, kind: str = "primary", parent=None, height: int = 44, size: float = 11.5):
        super().__init__(text, parent)
        self.kind = kind
        self._hover = 0.0
        self._sweep = 1.0
        self.setFixedHeight(height)
        self.setFont(body_font(size, bold=kind in ("primary", "success")))
        self.setFocusPolicy(Qt.NoFocus)
        if Theme.hover_cursor is not None:
            self.setCursor(Theme.hover_cursor)
        self._anim = QVariantAnimation(self, duration=170, startValue=0.0, endValue=1.0)
        self._anim.valueChanged.connect(self._set_hover)
        self._sweep_anim = QVariantAnimation(self, duration=850, startValue=0.0, endValue=1.0)
        self._sweep_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._sweep_anim.valueChanged.connect(self._set_sweep)

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def _set_sweep(self, v):
        self._sweep = float(v)
        self.update()

    def enterEvent(self, event):
        if self.isEnabled():
            self._anim.setDirection(QVariantAnimation.Forward)
            self._anim.start()
            self._sweep_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.setDirection(QVariantAnimation.Backward)
        self._anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        hv = self._hover if self.isEnabled() else 0.0
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        if self.isDown():
            r.translate(0, 1)
        radius = min(13.0, r.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        text_color = QColor(255, 255, 255, 255 if self.isEnabled() else 120)
        if self.kind in ("primary", "success"):
            base = Theme.color("accent") if self.kind == "primary" else QColor("#2fc474")
            if not self.isEnabled():
                base = QColor(96, 104, 128)
            top_c = base.lighter(int(108 + 14 * hv))
            bot_c = base.darker(int(138 - 10 * hv))
            for i in range(5, 0, -1):
                p.setPen(QPen(with_alpha(base, 0.05 * hv * (6 - i) / 5), i * 2.6))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, radius, radius)
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            g.setColorAt(0, top_c)
            g.setColorAt(1, bot_c)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawPath(path)
            p.save()
            p.setClipPath(path)
            gloss = QLinearGradient(0, r.top(), 0, r.center().y())
            gloss.setColorAt(0, QColor(255, 255, 255, 62))
            gloss.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(r.left(), r.top(), r.width(), r.height() / 2), QBrush(gloss))
            if hv > 0.01 and self._sweep < 1.0:
                x = r.left() - 60 + (r.width() + 120) * self._sweep
                band = QPolygonF([QPointF(x, r.top()), QPointF(x + 34, r.top()),
                                  QPointF(x + 14, r.bottom()), QPointF(x - 20, r.bottom())])
                p.setBrush(QColor(255, 255, 255, int(70 * hv * (1 - self._sweep))))
                p.drawPolygon(band)
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 60 + int(60 * hv)), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        elif self.kind == "ghost":
            p.setPen(QPen(QColor(255, 255, 255, int(70 + 110 * hv) if self.isEnabled() else 40), 1.2))
            p.setBrush(QColor(255, 255, 255, int(22 + 36 * hv) if self.isEnabled() else 10))
            p.drawPath(path)
        else:  # link
            text_color = with_alpha(QColor("white"), 0.75 + 0.25 * hv)
            if hv > 0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, int(28 * hv)))
                p.drawPath(path)
        p.setFont(self.font())
        p.setPen(text_color)
        p.drawText(r, Qt.AlignCenter, self.text())


class IconButton(QWidget):
    clicked = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind, self._hover, self.tall = kind, False, False
        self.setFixedSize(34, 28)
        if Theme.hover_cursor is not None:
            self.setCursor(Theme.hover_cursor)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        event.accept()  # bez tego zdarzenie trafia do paska tytułu, który startuje przeciąganie okna i połyka kliknięcie

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(232, 64, 82, 200) if self.kind == "close" else QColor(255, 255, 255, 40))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        p.setPen(QPen(QColor(255, 255, 255, 230), 1.6, Qt.SolidLine, Qt.RoundCap))
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.kind == "close":
            p.drawLine(c + QPointF(-4.5, -4.5), c + QPointF(4.5, 4.5))
            p.drawLine(c + QPointF(-4.5, 4.5), c + QPointF(4.5, -4.5))
        elif self.kind == "layout":   # ikona pokazuje układ, na który przełączysz
            w, h = (8, 13) if not self.tall else (14, 9)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - w / 2, c.y() - h / 2, w, h), 2, 2)
            p.drawLine(c + QPointF(-w / 2 + 1.5, -h / 2 + 3.2), c + QPointF(w / 2 - 1.5, -h / 2 + 3.2))
        else:
            p.drawLine(c + QPointF(-5, 3), c + QPointF(5, 3))


class TitleBar(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.setFixedHeight(40)
        self.btn_min, self.btn_close = IconButton("min", self), IconButton("close", self)
        self.btn_layout = IconButton("layout", self)
        self.btn_layout.setToolTip("Przełącz układ: poziomy / pionowy")
        self.btn_min.clicked.connect(lambda: self.window().showMinimized())

    def resizeEvent(self, event):
        self.btn_close.move(self.width() - 44, 6)
        self.btn_min.move(self.width() - 82, 6)
        self.btn_layout.move(self.width() - 120, 6)

    def mousePressEvent(self, event):
        handle = self.window().windowHandle()
        if event.button() == Qt.LeftButton and handle is not None:
            handle.startSystemMove()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        x = 16
        if Theme.icon is not None:
            p.drawPixmap(QRectF(x, 9, 22, 22), Theme.icon, QRectF(Theme.icon.rect()))
            x += 30
        if self.title:
            p.setFont(body_font(9.5, bold=True, spacing=1.0))
            p.setPen(QColor(8, 14, 40, 110))
            p.drawText(QPointF(x, 25.5), self.title)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(QPointF(x, 24.5), self.title)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, items: list, value: str, parent=None):
        super().__init__(parent)
        self.items = items
        self.index = [v for v, _ in items].index(value)
        self._x = float(self.index)
        self._hover = -1
        self.setMouseTracking(True)
        self.setFixedHeight(36)
        self.setFont(body_font(10.5, bold=True))
        fm = QFontMetrics(self.font())
        self.seg = max(fm.horizontalAdvance(t) for _, t in items) + 40
        self.setFixedWidth(self.seg * len(items) + 8)
        if Theme.hover_cursor is not None:
            self.setCursor(Theme.hover_cursor)
        self._anim = QVariantAnimation(self, duration=260)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.valueChanged.connect(self._set_x)

    def _set_x(self, v):
        self._x = float(v)
        self.update()

    @property
    def value(self) -> str:
        return self.items[self.index][0]

    def set_value(self, value: str, emit: bool = True) -> None:
        idx = [v for v, _ in self.items].index(value)
        if idx == self.index:
            return
        self.index = idx
        self._anim.stop()
        self._anim.setStartValue(self._x)
        self._anim.setEndValue(float(idx))
        self._anim.start()
        if emit:
            self.changed.emit(value)

    def _at(self, pos) -> int:
        return max(0, min(len(self.items) - 1, int((pos.x() - 4) // self.seg)))

    def mouseMoveEvent(self, event):
        self._hover = self._at(event.position())
        self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self.set_value(self.items[self._at(event.position())][0])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        on = self.isEnabled()
        track = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 50 if on else 25), 1.0))
        p.setBrush(QColor(0, 0, 0, 80 if on else 50))
        p.drawRoundedRect(track, 11, 11)
        pill = QRectF(4 + self._x * self.seg, 4, self.seg, self.height() - 8)
        base = Theme.color("accent") if on else QColor(96, 104, 128)
        g = QLinearGradient(0, pill.top(), 0, pill.bottom())
        g.setColorAt(0, base.lighter(118))
        g.setColorAt(1, base.darker(125))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.0))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(pill, 8, 8)
        p.setFont(self.font())
        for i, (_, text) in enumerate(self.items):
            r = QRectF(4 + i * self.seg, 4, self.seg, self.height() - 8)
            alpha = 255 if i == self.index else (225 if i == self._hover else 165)
            p.setPen(QColor(255, 255, 255, alpha if on else 110))
            p.drawText(r, Qt.AlignCenter, text)


class PathPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path: Optional[str] = None
        self.setFixedHeight(36)
        self.setFont(body_font(9.5))

    def set_path(self, path: Optional[str]) -> None:
        self.path = path
        self.setToolTip(path or "")
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.0))
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(r, 11, 11)
        # ikona folderu
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(Theme.color("accent2"), 0.95))
        fx, fy = r.left() + 14, r.center().y() - 6
        p.drawRoundedRect(QRectF(fx, fy + 2, 16, 11), 2.5, 2.5)
        p.drawRoundedRect(QRectF(fx, fy, 7, 4.5), 2, 2)
        text_rect = QRectF(r.left() + 40, r.top(), r.width() - 52, r.height())
        fm = QFontMetrics(self.font())
        text = self.path or "Nie odnaleziono gry – wskaż folder ręcznie"
        p.setPen(QColor(255, 255, 255, 235) if self.path else QColor(255, 140, 140, 235))
        p.setFont(self.font())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, fm.elidedText(text, Qt.ElideMiddle, int(text_rect.width())))


class StatusBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text, self.sub, self.color = "Sprawdzanie…", "", QColor("#9aa4c0")
        self.pulse = False
        self.t = 0.0
        self.setFixedHeight(54)

    def set_status(self, text: str, color: str, sub: str = "", pulse: bool = False) -> None:
        self.text, self.sub, self.color, self.pulse = text, sub, QColor(color), pulse
        self.update()

    def advance(self, dt: float) -> None:
        self.t += dt

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        c = QPointF(20, 20)
        pulse = 0.5 + 0.5 * math.sin(self.t * 3.2) if self.pulse else 0.0
        if self.pulse:
            p.setPen(Qt.NoPen)
            p.setBrush(with_alpha(self.color, 0.30 * (1 - pulse)))
            p.drawEllipse(c, 7 + 8 * pulse, 7 + 8 * pulse)
        p.setPen(QPen(with_alpha(self.color, 0.5), 3))
        p.setBrush(self.color)
        p.drawEllipse(c, 6, 6)
        p.setFont(body_font(13, bold=True, spacing=0.6))
        p.setPen(self.color.lighter(112))
        p.drawText(QPointF(42, 26), self.text)
        p.setFont(body_font(9.5))
        p.setPen(QColor(255, 255, 255, 170))
        p.drawText(QPointF(42, 46), self.sub)


class ProgressTrack(QWidget):
    """Pasek postępu z gładkim wypełnieniem. Bohater biega po jego górnej krawędzi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value, self.shown, self.t = 0.0, 0.0, 0.0
        self.busy = False
        self.setFixedHeight(26)

    def set_value(self, value: float) -> None:
        self.value = max(0.0, min(1.0, value))

    def displayed(self) -> float:
        return self.shown

    def advance(self, dt: float) -> None:
        self.t += dt
        if self.value < self.shown - 0.2:
            self.shown = self.value  # nowa operacja – bez cofania animacją
        self.shown += (self.value - self.shown) * min(1.0, dt * 7)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1.0))
        p.setBrush(QColor(4, 8, 22, 150))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        inner = r.adjusted(3, 3, -3, -3)
        width = inner.width() * self.shown
        if width > 1:
            fill = QRectF(inner.left(), inner.top(), max(width, inner.height()), inner.height())
            path = QPainterPath()
            path.addRoundedRect(fill, fill.height() / 2, fill.height() / 2)
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            g.setColorAt(0, Theme.color("accent").darker(120))
            g.setColorAt(1, Theme.color("accent2"))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawPath(path)
            p.save()
            p.setClipPath(path)
            speed = 1.6 if self.busy else 0.5
            for k in range(-1, int(fill.width() // 46) + 2):
                x = fill.left() + ((k * 46 + self.t * 40 * speed) % (fill.width() + 46)) - 6
                p.setBrush(QColor(255, 255, 255, 34))
                p.drawPolygon(QPolygonF([QPointF(x, fill.bottom()), QPointF(x + 14, fill.bottom()),
                                         QPointF(x + 28, fill.top()), QPointF(x + 14, fill.top())]))
            p.restore()
        p.setFont(body_font(8.5, bold=True))
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(r.adjusted(0, 0, -12, 0), Qt.AlignVCenter | Qt.AlignRight, f"{int(self.shown * 100)}%")


class MessageDialog(QDialog):
    """Okno komunikatu w stylu aplikacji (bez systemowej ramki)."""

    def __init__(self, parent, title: str, text: str, kind: str = "info",
                 extra: Optional[tuple] = None, ok_text: str = "OK"):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        if Theme.normal_cursor is not None:
            self.setCursor(Theme.normal_cursor)
        self.kind = kind
        self.setFixedWidth(470)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(12)
        head = QLabel(title)
        head.setFont(body_font(15, bold=True))
        head.setStyleSheet("color:white; background:transparent;")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setFont(body_font(10.5))
        body.setStyleSheet("color:rgba(255,255,255,215); background:transparent;")
        outer.addWidget(head)
        outer.addWidget(body)
        outer.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        if extra:
            extra_btn = GlowButton(extra[0], "ghost", height=42)
            extra_btn.clicked.connect(extra[1])
            row.addWidget(extra_btn)
        ok = GlowButton(ok_text, "primary", height=42)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        outer.addLayout(row)
        self.adjustSize()

    def showEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            geo = parent.window().frameGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        super().showEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        for i in range(6, 0, -1):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 14))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 18 + i, 18 + i)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(22, 30, 60, 250))
        g.setColorAt(1, QColor(10, 14, 32, 252))
        p.setBrush(QBrush(g))
        accent = {"error": QColor("#ff6b78"), "success": QColor("#ffd36b")}.get(self.kind, Theme.color("accent2"))
        p.setPen(QPen(with_alpha(accent, 0.55), 1.4))
        p.drawRoundedRect(r, 18, 18)
        p.setPen(QPen(accent, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(r.left() + 28, r.top() + 1.5), QPointF(r.left() + 78, r.top() + 1.5))


class IconTile(QWidget):
    """Kwadratowa ikonka-przycisk (poradnik, wsparcie, autorzy)."""
    clicked = Signal()
    hovered = Signal(bool)

    def __init__(self, kind: str, tip: str, parent=None, size: int = 44):
        super().__init__(parent)
        self.kind, self._hover = kind, 0.0
        self.setFixedSize(size, size)
        self.setToolTip(tip)
        if Theme.hover_cursor is not None:
            self.setCursor(Theme.hover_cursor)
        self._anim = QVariantAnimation(self, duration=170, startValue=0.0, endValue=1.0)
        self._anim.valueChanged.connect(self._set)

    def _set(self, v):
        self._hover = float(v)
        self.update()

    def enterEvent(self, event):
        self._anim.setDirection(QVariantAnimation.Forward)
        self._anim.start()
        self.hovered.emit(True)

    def leaveEvent(self, event):
        self._anim.setDirection(QVariantAnimation.Backward)
        self._anim.start()
        self.hovered.emit(False)

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        hv = self._hover
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        accent = Theme.color("accent")
        for i in range(4, 0, -1):
            p.setPen(QPen(with_alpha(accent, 0.07 * hv * (5 - i) / 4), i * 2.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(30, 40, 72, 215))
        g.setColorAt(1, QColor(12, 18, 40, 225))
        p.setPen(QPen(QColor(255, 255, 255, int(55 + 120 * hv)), 1.2))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 12, 12)
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(accent, 0.30 * hv))
        p.drawRoundedRect(r, 12, 12)
        c = r.center()
        ink = QColor(255, 255, 255, int(215 + 40 * hv))
        p.translate(c.x(), c.y() - 0.8 * hv)
        p.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.kind == "guide":      # otwarta książka
            for sx in (-1, 1):
                page = QPainterPath()
                page.moveTo(0, -5)
                page.cubicTo(sx * 4, -8, sx * 8, -8, sx * 10, -6.5)
                page.lineTo(sx * 10, 7)
                page.cubicTo(sx * 8, 5.5, sx * 4, 5.5, 0, 8)
                page.closeSubpath()
                p.drawPath(page)
        elif self.kind == "support":  # serce
            heart = QPainterPath()
            heart.moveTo(0, 8)
            heart.cubicTo(-14, -1, -8, -11, 0, -4)
            heart.cubicTo(8, -11, 14, -1, 0, 8)
            p.setBrush(with_alpha(QColor("#ff6f91"), 0.35 + 0.5 * hv))
            p.setPen(QPen(QColor("#ffd0dc"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(heart)
        else:                          # dwie osoby
            p.setBrush(with_alpha(ink, 0.25))
            for dx, s in ((5.5, 0.82), (-4.5, 1.0)):
                p.save()
                p.translate(dx, 0)
                p.scale(s, s)
                p.drawEllipse(QPointF(0, -5.5), 4.0, 4.0)
                body = QPainterPath()
                body.moveTo(-7, 9)
                body.cubicTo(-7, 0.5, 7, 0.5, 7, 9)
                p.drawPath(body)
                p.restore()


class AuthorsFlyout(QWidget):
    """Wysuwane menu z autorami: profil Steam (otwiera) i nick Discord (kopiuje do schowka)."""
    hovered = Signal(bool)
    chosen = Signal(str, str)   # (rodzaj: "steam" | "discord", wartość)

    W, HEAD, BLOCK, FOOT = 304, 36, 78, 30

    def __init__(self, authors, parent=None):
        super().__init__(parent)
        self.authors = list(authors)
        self.t, self._hover = 0.0, -1
        self.note = ""
        self.chips: list = []
        self.setMouseTracking(True)
        self.setFixedSize(self.W, self.HEAD + self.BLOCK * len(self.authors) + self.FOOT)
        if Theme.hover_cursor is not None:
            self.setCursor(Theme.hover_cursor)
        self._layout()
        self._anim = QVariantAnimation(self, duration=220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set)
        self._anim.finished.connect(lambda: self.hide() if self.t <= 0.001 else None)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(lambda: self._set_note(""))
        self.hide()

    def _layout(self) -> None:
        self.chips = []
        for i, (_name, steam, discord) in enumerate(self.authors):
            top = self.HEAD + i * self.BLOCK + 40
            self.chips.append((QRectF(62, top, 84, 26), "steam", steam, "Steam  ↗"))
            self.chips.append((QRectF(154, top, 138, 26), "discord", discord, f"Discord · {discord}"))

    def _set(self, v):
        self.t = float(v)
        self.update()

    def _set_note(self, text: str) -> None:
        self.note = text
        self.update()

    def flash(self, text: str) -> None:
        self._set_note(text)
        self._note_timer.start(2400)

    def open(self) -> None:
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.t)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def close_menu(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.t)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _chip_at(self, pos) -> int:
        for i, (rect, *_rest) in enumerate(self.chips):
            if rect.contains(pos):
                return i
        return -1

    def enterEvent(self, event):
        self.hovered.emit(True)

    def leaveEvent(self, event):
        self._hover = -1
        self.update()
        self.hovered.emit(False)

    def mouseMoveEvent(self, event):
        idx = self._chip_at(event.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mouseReleaseEvent(self, event):
        idx = self._chip_at(event.position())
        if event.button() == Qt.LeftButton and idx >= 0:
            _rect, kind, value, _label = self.chips[idx]
            self.chosen.emit(kind, value)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setOpacity(self.t)
        p.translate(0, (1 - self.t) * 10)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, QColor(22, 30, 62, 248))
        g.setColorAt(1, QColor(10, 14, 34, 250))
        p.setBrush(QBrush(g))
        p.setPen(QPen(with_alpha(Theme.color("accent2"), 0.55), 1.3))
        p.drawRoundedRect(r, 14, 14)
        p.setFont(body_font(8.5, bold=True, spacing=1.6))
        p.setPen(QColor(255, 255, 255, 150))
        p.drawText(QRectF(18, 10, self.W - 36, 20), Qt.AlignVCenter | Qt.AlignLeft, "AUTORZY SPOLSZCZENIA")
        for i, (name, _steam, _discord) in enumerate(self.authors):
            top = self.HEAD + i * self.BLOCK
            if i:
                p.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
                p.drawLine(QPointF(16, top - 4), QPointF(self.W - 16, top - 4))
            c = QPointF(36, top + 22)
            ag = QLinearGradient(c.x(), c.y() - 17, c.x(), c.y() + 17)
            ag.setColorAt(0, Theme.color("accent2"))
            ag.setColorAt(1, Theme.color("accent").darker(130))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1.0))
            p.setBrush(QBrush(ag))
            p.drawEllipse(c, 17, 17)
            p.setFont(body_font(12, bold=True))
            p.setPen(QColor(10, 16, 40))
            p.drawText(QRectF(c.x() - 17, c.y() - 17, 34, 34), Qt.AlignCenter, name[0])
            p.setFont(body_font(12, bold=True))
            p.setPen(QColor(255, 255, 255, 245))
            p.drawText(QPointF(62, top + 28), name)
        p.setFont(body_font(8.5, bold=True))
        for i, (rect, kind, _value, label) in enumerate(self.chips):
            hot = i == self._hover
            base = QColor("#5865F2") if kind == "discord" else Theme.color("accent")
            p.setPen(QPen(with_alpha(base, 0.9 if hot else 0.5), 1.1))
            p.setBrush(with_alpha(base, 0.45 if hot else 0.16))
            p.drawRoundedRect(rect, 9, 9)
            p.setPen(QColor(255, 255, 255, 255 if hot else 225))
            p.drawText(rect, Qt.AlignCenter, label)
        p.setFont(body_font(8.5))
        p.setPen(with_alpha(Theme.color("accent2"), 1.0) if self.note else QColor(255, 255, 255, 120))
        p.drawText(QRectF(16, self.height() - self.FOOT - 2, self.W - 32, self.FOOT), Qt.AlignVCenter | Qt.AlignLeft,
                   self.note or "Discord: kliknięcie kopiuje nick do schowka")
