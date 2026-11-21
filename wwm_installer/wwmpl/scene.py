"""Animowana scena 2D: niebo, góry z paralaksą, mgła, bambusy, cząsteczki (płatki, świetliki,
gwiazdy), trzy nastroje (dzień / noc / świt) z płynnym przejściem, bohater i efekty kursora."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QCursor, QGuiApplication, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from .character import Hero


def C(h: str) -> list:
    h = h.lstrip("#")
    return [float(int(h[i:i + 2], 16)) for i in (0, 2, 4)]


PALETTES = {
    "day": dict(
        sky_top=C("#4fa3e6"), sky_bottom=C("#fde8cc"), glow=C("#fff0c2"), far=C("#a7bfd8"), mid=C("#7da0b6"),
        near=C("#4a7a70"), mist=C("#f7f1e8"), bamboo_far=C("#6bac84"), bamboo_near=C("#1b5843"),
        ground=C("#12402f"), petal=C("#ffb7c9"), robe=C("#2b9a8f"), scarf=C("#e0445a"),
        accent=C("#3b9be0"), accent2=C("#9fe3d2"),
        sun=1.0, sun_y=0.25, moon=0.0, moon_y=0.80, stars=0.0, fireflies=0.0, petals=1.0, clouds=0.9, fog=0.35),
    "night": dict(
        sky_top=C("#060a26"), sky_bottom=C("#2b3b7c"), glow=C("#6c86d8"), far=C("#33468a"), mid=C("#1e2c60"),
        near=C("#111a3e"), mist=C("#7183c8"), bamboo_far=C("#193060"), bamboo_near=C("#050a1c"),
        ground=C("#040818"), petal=C("#bcd3ff"), robe=C("#7080ea"), scarf=C("#ff7a8a"),
        accent=C("#7d8cff"), accent2=C("#c2caff"),
        sun=0.0, sun_y=0.80, moon=1.0, moon_y=0.22, stars=1.0, fireflies=1.0, petals=0.35, clouds=0.2, fog=0.55),
    "dawn": dict(
        sky_top=C("#4a4192"), sky_bottom=C("#ffb98f"), glow=C("#ffd37a"), far=C("#c68fb0"), mid=C("#94638f"),
        near=C("#523f6b"), mist=C("#ffdcc4"), bamboo_far=C("#735f8e"), bamboo_near=C("#2b2349"),
        ground=C("#1d1535"), petal=C("#ffc2d4"), robe=C("#e0566c"), scarf=C("#ffd36b"),
        accent=C("#ff9a62"), accent2=C("#ffe0b0"),
        sun=1.0, sun_y=0.50, moon=0.0, moon_y=0.80, stars=0.12, fireflies=0.35, petals=1.8, clouds=1.0, fog=0.45),
}


class Mood:
    """Aktualna paleta płynnie dąży do palety docelowej."""

    def __init__(self, name: str):
        self.name = name
        self.cur = {k: (list(v) if isinstance(v, list) else v) for k, v in PALETTES[name].items()}

    def set(self, name: str) -> None:
        self.name = name

    def update(self, dt: float) -> None:
        k = 1 - math.exp(-dt * 1.9)
        for key, target in PALETTES[self.name].items():
            cur = self.cur[key]
            if isinstance(target, list):
                for i in range(3):
                    cur[i] += (target[i] - cur[i]) * k
            else:
                self.cur[key] += (target - cur) * k

    def color(self, key: str, alpha: float = 1.0) -> QColor:
        r, g, b = self.cur[key]
        return QColor(int(r), int(g), int(b), int(max(0.0, min(1.0, alpha)) * 255))

    def mix(self, a: str, b: str, u: float) -> QColor:
        ca, cb = self.cur[a], self.cur[b]
        return QColor(*(int(ca[i] + (cb[i] - ca[i]) * u) for i in range(3)))

    def __getitem__(self, key):
        return self.cur[key]


class Ridge:
    """Pasmo górskie jako suma sinusów o całkowitych częstotliwościach – kafelkuje się bez szwu."""

    def __init__(self, seed: int, period: int, sharp: float = 1.35):
        rnd = random.Random(seed)
        ks, amps = (1, 2, 3, 5, 8, 13, 21), (1.0, 0.75, 0.5, 0.32, 0.2, 0.12, 0.07)
        self.terms = [(k, a, rnd.uniform(0, math.tau)) for k, a in zip(ks, amps)]
        self.norm = sum(amps)
        self.period, self.sharp = period, sharp

    def h(self, x: float) -> float:
        v = sum(a * math.sin(math.tau * k * x / self.period + ph) for k, a, ph in self.terms) / self.norm
        return ((v + 1) / 2) ** self.sharp

    def path(self, base: float, amp: float, bottom: float) -> QPainterPath:
        path = QPainterPath(QPointF(0, bottom))
        for x in range(0, self.period + 1, 8):
            path.lineTo(x, base - amp * self.h(x))
        path.lineTo(self.period, bottom)
        path.closeSubpath()
        return path


class Stalk:
    def __init__(self, rnd: random.Random, x: float, top: float, layer: str):
        self.x, self.top, self.layer = x, top, layer
        self.phase = rnd.uniform(0, math.tau)
        self.lean = rnd.uniform(-0.04, 0.04)
        self.leaf_seed = rnd.random()


class Petal:
    def __init__(self, rnd: random.Random, w: float, h: float, spread=True):
        self.reset(rnd, w, h, spread)

    def reset(self, rnd, w, h, spread=False):
        self.x = rnd.uniform(-40, w + 40)
        self.y = rnd.uniform(-20, h) if spread else rnd.uniform(-60, -10)
        self.vy = rnd.uniform(20, 46)
        self.vx = rnd.uniform(8, 30)
        self.rot = rnd.uniform(0, 360)
        self.vrot = rnd.uniform(-120, 120)
        self.size = rnd.uniform(3.6, 6.4)
        self.phase = rnd.uniform(0, math.tau)
        self.rank = rnd.random()


class SceneWidget(QWidget):
    PERIOD = 1500

    def __init__(self, parent=None, mood: str = "day"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)
        self.mood = Mood(mood)
        self.t = 0.0
        self.px = 0.0
        self._last = time.perf_counter()
        self.hero = Hero()
        self.rnd = random.Random(7)
        self.ridges = [Ridge(11, self.PERIOD, 1.5), Ridge(23, self.PERIOD, 1.25), Ridge(5, self.PERIOD, 1.0)]
        self.paths: list = []
        self.stalks: list = []
        self.petals: list = []
        self.fireflies = [(self.rnd.random(), self.rnd.random(), self.rnd.uniform(0.2, 0.6),
                           self.rnd.uniform(0.2, 0.6), self.rnd.uniform(0, math.tau)) for _ in range(18)]
        self.stars = [(self.rnd.random(), self.rnd.random() * 0.55, self.rnd.uniform(0.8, 2.0), self.rnd.randrange(4))
                      for _ in range(90)]
        self.clouds = [(self.rnd.random(), self.rnd.uniform(0.06, 0.34), self.rnd.uniform(0.6, 1.3),
                        self.rnd.uniform(5, 14)) for _ in range(6)]
        self.sprites: dict = {}
        self.overlay = None
        self.progress_source = None   # wywołanie zwracające aktualny postęp 0..1
        self.hooks: list = []         # wywołania co klatkę: hook(dt)
        self._build_geometry()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    # ------------------------------------------------------------------ geometria
    def _build_geometry(self) -> None:
        w, h = max(self.width(), 100), max(self.height(), 100)
        specs = ((0.60, 0.24), (0.71, 0.17), (0.86, 0.11))
        self.paths = [r.path(h * b, h * a, h + 4) for r, (b, a) in zip(self.ridges, specs)]
        self.specs = [(h * b, h * a) for b, a in specs]
        rnd = random.Random(3)
        self.stalks = []
        for i in range(11):
            self.stalks.append(Stalk(rnd, w * (0.04 + 0.92 * (i + rnd.random() * 0.6) / 11), h * rnd.uniform(0.30, 0.55), "far"))
        for x in (0.006, 0.03, 0.056, 0.944, 0.97, 0.994):
            self.stalks.append(Stalk(rnd, w * x, h * rnd.uniform(0.05, 0.22), "near"))
        self.petals = [Petal(self.rnd, w, h) for _ in range(46)]

    def resizeEvent(self, event):
        self._build_geometry()
        super().resizeEvent(event)

    def _ensure_sprites(self) -> None:
        if self.sprites:
            return
        cloud = QPixmap(320, 120)
        cloud.fill(Qt.transparent)
        p = QPainter(cloud)
        p.setRenderHint(QPainter.Antialiasing)
        for cx, cy, r in ((70, 70, 46), (125, 52, 56), (185, 62, 52), (240, 74, 42), (150, 84, 50)):
            g = QRadialGradient(cx, cy, r)
            g.setColorAt(0, QColor(255, 255, 255, 190))
            g.setColorAt(0.6, QColor(255, 255, 255, 90))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), r, r * 0.62)
        p.end()
        fog = QPixmap(640, 150)
        fog.fill(Qt.transparent)
        p = QPainter(fog)
        g = QRadialGradient(320, 75, 320)
        g.setColorAt(0, QColor(255, 255, 255, 140))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(g))
        p.setPen(Qt.NoPen)
        p.save()
        p.translate(320, 75)
        p.scale(1, 0.23)
        p.drawEllipse(QPointF(0, 0), 320, 320)
        p.restore()
        p.end()
        fly = QPixmap(40, 40)
        fly.fill(Qt.transparent)
        p = QPainter(fly)
        g = QRadialGradient(20, 20, 20)
        g.setColorAt(0, QColor(255, 250, 190, 255))
        g.setColorAt(0.25, QColor(210, 255, 150, 150))
        g.setColorAt(1, QColor(150, 255, 120, 0))
        p.setBrush(QBrush(g))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(20, 20), 20, 20)
        p.end()
        self.sprites = {"cloud": cloud, "fog": fog, "fly": fly}

    # ------------------------------------------------------------------ sterowanie
    def set_mood(self, name: str) -> None:
        self.mood.set(name)

    def tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        self.t += dt
        self.mood.update(dt)
        # paralaksa za kursorem
        target = 0.0
        pos = self.mapFromGlobal(QCursor.pos())
        if self.width() > 0 and self.rect().contains(pos):
            target = (pos.x() / self.width() - 0.5) * 2
        self.px += (target - self.px) * min(1.0, dt * 3.0)
        w, h = self.width(), self.height()
        amount = self.mood["petals"]
        for petal in self.petals:
            petal.x += (petal.vx + math.sin(self.t * 1.3 + petal.phase) * 18) * dt
            petal.y += petal.vy * dt
            petal.rot += petal.vrot * dt
            if petal.y > h + 20 or petal.x > w + 60:
                petal.reset(self.rnd, w, h)
        if self.progress_source is not None:
            self.hero.set_progress(self.progress_source())
        for hook in self.hooks:
            hook(dt)
        self.hero.update(dt)
        self.update()
        if self.overlay is not None:
            self.overlay.step(dt)

    # ------------------------------------------------------------------ rysowanie
    def paintEvent(self, event):
        self._ensure_sprites()
        w, h = self.width(), self.height()
        m, t = self.mood, self.t
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 14, 14)
        p.setClipPath(clip)

        sky = QLinearGradient(0, 0, 0, h * 0.85)
        sky.setColorAt(0, m.color("sky_top"))
        sky.setColorAt(1, m.color("sky_bottom"))
        p.fillRect(self.rect(), QBrush(sky))

        # gwiazdy
        if m["stars"] > 0.01:
            p.setPen(Qt.NoPen)
            groups = ([], [], [], [])
            for sx, sy, size, grp in self.stars:
                groups[grp].append((sx * w, sy * h, size))
            for grp, items in enumerate(groups):
                alpha = m["stars"] * (0.45 + 0.55 * math.sin(t * (0.8 + grp * 0.45) + grp * 1.7)) ** 2
                p.setBrush(QColor(255, 255, 255, int(255 * max(0.0, min(1.0, alpha)))))
                for x, y, size in items:
                    p.drawEllipse(QPointF(x, y), size * 0.6, size * 0.6)

        # słońce i księżyc
        sx, sy = w * 0.73 + self.px * -6, h * m["sun_y"]
        if m["sun"] > 0.01:
            g = QRadialGradient(sx, sy, 260)
            g.setColorAt(0, m.color("glow", 0.75 * m["sun"]))
            g.setColorAt(1, m.color("glow", 0.0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(sx, sy), 260, 260)
            p.setBrush(QColor(255, 246, 214, int(255 * m["sun"])))
            p.drawEllipse(QPointF(sx, sy), 34, 34)
        mx, my = w * 0.24 + self.px * -5, h * m["moon_y"]
        if m["moon"] > 0.01:
            g = QRadialGradient(mx, my, 190)
            g.setColorAt(0, QColor(170, 195, 255, int(120 * m["moon"])))
            g.setColorAt(1, QColor(170, 195, 255, 0))
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(mx, my), 190, 190)
            p.setBrush(QColor(246, 243, 224, int(255 * m["moon"])))
            p.drawEllipse(QPointF(mx, my), 31, 31)
            p.setBrush(QColor(205, 205, 190, int(120 * m["moon"])))
            for dx, dy, r in ((-9, -6, 6), (8, 7, 4.5), (3, -13, 3.2)):
                p.drawEllipse(QPointF(mx + dx, my + dy), r, r)

        # chmury
        if m["clouds"] > 0.02:
            p.setOpacity(min(1.0, m["clouds"]) * 0.85)
            cloud = self.sprites["cloud"]
            for cx, cy, scale, speed in self.clouds:
                x = ((cx * (w + 400) + t * speed + self.px * -10) % (w + 400)) - 300
                p.drawPixmap(QRectF(x, cy * h, cloud.width() * scale, cloud.height() * scale), cloud, QRectF(cloud.rect()))
            p.setOpacity(1.0)

        # góry, mgła, bambusy
        for i, (path, (base, amp)) in enumerate(zip(self.paths, self.specs)):
            key = ("far", "mid", "near")[i]
            speed, par = ((5, 8), (9, 16), (0, 26))[i]
            offset = (t * speed + self.px * par) % self.PERIOD
            top = m.color(key)
            bottom = m.mix(key, "mist", 0.65 if i < 2 else 0.25)
            g = QLinearGradient(0, base - amp, 0, base + 30)
            g.setColorAt(0, top)
            g.setColorAt(1, bottom)
            p.setBrush(QBrush(g))
            p.setPen(Qt.NoPen)
            for k in range(-1, int(w // self.PERIOD) + 2):
                p.save()
                p.translate(k * self.PERIOD - offset, 0)
                p.drawPath(path)
                p.restore()
            if i < 2:
                band = QLinearGradient(0, base - amp * 0.15, 0, base + amp * 0.5)
                band.setColorAt(0, m.color("mist", 0.0))
                band.setColorAt(0.5, m.color("mist", 0.55 * m["fog"] + 0.1))
                band.setColorAt(1, m.color("mist", 0.0))
                p.fillRect(QRectF(0, base - amp * 0.15, w, amp * 0.65), QBrush(band))
            if i == 0:
                self._draw_fog(p, w, h, base)
            if i == 1:
                self._draw_bamboo(p, "far", w, h)
        p.fillRect(QRectF(0, h * 0.93, w, h * 0.07 + 2), m.color("ground"))
        self._draw_bamboo(p, "near", w, h)

        # świetliki i płatki
        self._draw_particles(p, w, h)

        # winieta
        v = QRadialGradient(w / 2, h * 0.5, max(w, h) * 0.75)
        v.setColorAt(0.0, QColor(0, 0, 0, 0))
        v.setColorAt(0.62, QColor(0, 0, 0, 0))
        v.setColorAt(1.0, QColor(0, 0, 0, 120))
        p.fillRect(self.rect(), QBrush(v))
        p.end()

    def _draw_fog(self, p, w, h, base) -> None:
        fog = self.sprites["fog"]
        p.setOpacity(min(1.0, self.mood["fog"] * 1.3))
        for i in range(4):
            x = ((i * 380 + self.t * (7 + i * 3) + self.px * -14) % (w + 700)) - 650
            p.drawPixmap(QRectF(x, base - 30 + (i % 2) * 40, 640, 150), fog, QRectF(fog.rect()))
        p.setOpacity(1.0)

    def _draw_bamboo(self, p, layer: str, w: float, h: float) -> None:
        m, t = self.mood, self.t
        near = layer == "near"
        color = m.color("bamboo_near" if near else "bamboo_far")
        base_y = h + 6
        stalks, nodes, leaves = [], [], []
        par = 38 if near else 16
        for s in self.stalks:
            if s.layer != layer:
                continue
            sway = math.sin(t * 0.9 + s.phase) * (7 if near else 4)
            x0 = s.x + self.px * par
            top = s.top
            prev = QPointF(x0, base_y)
            segs = 9
            for i in range(1, segs + 1):
                u = i / segs
                y = base_y + (top - base_y) * u
                x = x0 + s.lean * (base_y - y) + sway * u * u
                cur = QPointF(x, y)
                stalks.append(QLineF(prev, cur))
                if i % 2 == 0:
                    nodes.append(QLineF(x - (4 if near else 2.2), y, x + (4 if near else 2.2), y))
                if u > 0.55 and i % 1 == 0:
                    for side in (-1, 1):
                        ang = side * (0.75 + 0.35 * math.sin(t * 1.6 + s.phase + i)) + 0.5
                        ln = (22 if near else 12) * (1.15 - u * 0.4)
                        leaves.append(QLineF(x, y, x + math.sin(ang) * ln * side * -1 + side * ln * 0.2, y + abs(math.cos(ang)) * ln * 0.55))
                prev = cur
        p.setPen(QPen(color, 9 if near else 3.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLines(stalks)
        p.setPen(QPen(m.mix("bamboo_near" if near else "bamboo_far", "mist", 0.18), 2.0 if near else 1.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLines(nodes)
        p.setPen(QPen(color, 5 if near else 2.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLines(leaves)

    def _draw_particles(self, p, w: float, h: float) -> None:
        m, t = self.mood, self.t
        if m["fireflies"] > 0.02:
            fly = self.sprites["fly"]
            for fx, fy, ax, ay, ph in self.fireflies:
                x = (fx * w + math.sin(t * ax + ph) * 60 + self.px * 12) % w
                y = h * (0.45 + 0.4 * fy) + math.sin(t * ay * 1.7 + ph) * 28
                p.setOpacity(m["fireflies"] * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.9 + ph * 3))))
                p.drawPixmap(QPointF(x - 20, y - 20), fly)
            p.setOpacity(1.0)
        amount = m["petals"]
        p.setPen(Qt.NoPen)
        petal_color = m.color("petal", 0.9)
        shine = m.mix("petal", "mist", 0.6)
        limit = int(len(self.petals) * min(1.0, amount / 1.0)) if amount < 1 else len(self.petals)
        for petal in self.petals[:max(0, limit)]:
            p.save()
            p.translate(petal.x + self.px * 10, petal.y)
            p.rotate(petal.rot)
            squash = 0.45 + 0.55 * abs(math.sin(math.radians(petal.rot) * 0.5 + petal.phase))
            p.scale(1.0, squash)
            p.setBrush(petal_color)
            p.drawEllipse(QPointF(0, 0), petal.size, petal.size * 0.62)
            p.setBrush(shine)
            p.drawEllipse(QPointF(-petal.size * 0.25, 0), petal.size * 0.35, petal.size * 0.2)
            p.restore()


class FxOverlay(QWidget):
    """Przezroczysta warstwa na wierzchu: bohater, iskry za kursorem i fale po kliknięciu."""

    def __init__(self, scene: SceneWidget, parent=None):
        super().__init__(parent)
        self.scene = scene
        scene.overlay = self
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.sparks: list = []
        self.ripples: list = []
        self.last_pos = None
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self.isVisible():
            try:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
            except AttributeError:
                return False
            if self.rect().contains(pos):
                self.ripples.append([pos.x(), pos.y(), 0.0])
        return False

    def step(self, dt: float) -> None:
        pos = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(pos):
            if self.last_pos is not None:
                dx, dy = pos.x() - self.last_pos.x(), pos.y() - self.last_pos.y()
                dist = math.hypot(dx, dy)
                if dist > 2 and len(self.sparks) < 90:
                    for _ in range(min(3, 1 + int(dist / 14))):
                        self.sparks.append([pos.x() + random.uniform(-3, 3), pos.y() + random.uniform(-3, 3),
                                            random.uniform(-14, 14), random.uniform(-6, 22),
                                            random.uniform(0.45, 0.9), random.uniform(1.0, 2.6)])
            self.last_pos = pos
        else:
            self.last_pos = None
        for s in self.sparks:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[4] -= dt
        self.sparks = [s for s in self.sparks if s[4] > 0]
        for r in self.ripples:
            r[2] += dt
        self.ripples = [r for r in self.ripples if r[2] < 0.55]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self.scene.mood
        self.scene.hero.draw(p, m.color("robe"), m.color("scarf"))
        p.setPen(Qt.NoPen)
        for x, y, vx, vy, life, size in self.sparks:
            c = m.color("accent2", min(1.0, life * 1.3))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), size, size)
        for x, y, age in self.ripples:
            u = age / 0.55
            c = m.color("accent2", (1 - u) * 0.8)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(c, 2.0 * (1 - u) + 0.5))
            p.drawEllipse(QPointF(x, y), 4 + 26 * u, 4 + 26 * u)
        p.end()


# ---------------------------------------------------------------- kursor i ikona

def make_cursor(hover: bool = False) -> QCursor:
    size = 36
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    blade = QPolygonF([QPointF(3, 2.5), QPointF(23, 12.5), QPointF(14.5, 15), QPointF(11, 24.5)])
    g = QLinearGradient(3, 3, 22, 22)
    g.setColorAt(0, QColor("#ffffff"))
    g.setColorAt(1, QColor("#7fd6ff") if not hover else QColor("#ffd66b"))
    p.setPen(QPen(QColor(10, 18, 45, 230), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QBrush(g))
    p.drawPolygon(blade)
    p.setPen(QPen(QColor(10, 18, 45, 140), 1.0))
    p.drawLine(QLineF(4.5, 4.5, 14.5, 15))
    if hover:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 214, 107, 220), 1.6))
        p.drawEllipse(QPointF(5, 5), 4.2, 4.2)
    p.end()
    return QCursor(pix, 3, 3)


def make_icon(size: int = 256) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    p.scale(s, s)
    bg = QLinearGradient(0, 0, 0, 256)
    bg.setColorAt(0, QColor("#2b4a99"))
    bg.setColorAt(1, QColor("#0b1030"))
    p.setBrush(QBrush(bg))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    glow = QRadialGradient(170, 88, 90)
    glow.setColorAt(0, QColor(255, 244, 214, 230))
    glow.setColorAt(1, QColor(255, 244, 214, 0))
    p.setBrush(QBrush(glow))
    p.drawEllipse(QPointF(170, 88), 90, 90)
    p.setBrush(QColor("#fff6dc"))
    p.drawEllipse(QPointF(170, 88), 34, 34)
    p.setBrush(Qt.NoBrush)
    for i, (y, width) in enumerate(((120, 11), (150, 9), (180, 7))):
        path = QPainterPath(QPointF(34, y + 20))
        path.cubicTo(90, y - 28, 130, y + 52, 214 - i * 12, y - 6 + i * 4)
        pen = QPen(QColor(255, 255, 255, 235 - i * 40), width, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#d8364b"))
    p.drawRoundedRect(QRectF(172, 176, 54, 54), 9, 9)
    p.setPen(QColor("#fff4ee"))
    font = p.font()
    font.setPixelSize(30)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(172, 176, 54, 54), Qt.AlignCenter, "PL")
    p.end()
    return pix
