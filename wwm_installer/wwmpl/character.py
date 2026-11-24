"""Oryginalny bohater 2D (wędrowny szermierz w słomianym kapeluszu) animowany proceduralnie.
Szkielet: biodra → tułów → głowa, nogi i ręce z dwoma segmentami. Animacje: bieg, stanie,
skok między „szynami" (napis tytułu ↔ pasek postępu), radość po zakończeniu.
Bohater nosi biało-czerwoną flagę: macha nią, kręci, kłania się, tnie mieczem (flaga na plecach)
i wbija ją w koniec paska po udanej instalacji."""
from __future__ import annotations

import math
import random
from typing import Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF


def pt(origin: QPointF, angle: float, length: float) -> QPointF:
    """Punkt w odległości `length` od `origin`; kąt liczony od pionu w dół, dodatni = do przodu (+x)."""
    return QPointF(origin.x() + math.sin(angle) * length, origin.y() + math.cos(angle) * length)


def with_alpha_c(color: QColor, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlphaF(max(0.0, min(1.0, alpha)) * color.alphaF())
    return out


def shade(color: QColor, factor: float) -> QColor:
    return QColor(min(255, int(color.red() * factor)), min(255, int(color.green() * factor)),
                  min(255, int(color.blue() * factor)), color.alpha())


class Hero:
    THIGH, SHIN, UPPER, FORE = 13.0, 13.0, 8.5, 8.5
    SKIN = QColor("#f1c9a5")
    PANTS = QColor("#27304a")
    STRAW = QColor("#dcb46f")
    METAL = QColor("#e8c765")
    FLAG_WHITE = QColor("#fbfbfb")
    FLAG_RED = QColor("#dc143c")
    POLE = QColor("#e4d2a6")
    ACTS = {"wave": 2.6, "bow": 1.7, "twirl": 1.9, "slash": 1.3}

    def __init__(self):
        self.x, self.y = 120.0, 120.0
        self.facing, self.face_vis = 1, 1.0
        self.phase, self.t = 0.0, 0.0
        self.mode = "patrol"          # patrol | bar | celebrate
        self.rails: dict = {}         # nazwa -> (x0, x1, y)
        self.rail = "title"
        self.sub, self.sub_time = "idle", 1.0
        self.hop_timer = random.uniform(2.5, 5.0)
        self.jump: Optional[dict] = None
        self.run_vis = 0.0
        self.progress = 0.0
        self.dust: list = []
        self.dust_timer = 0.0
        self.celebrate_timer = 0.0
        self.placed = False
        self.act: Optional[str] = None     # drobna scenka w trakcie postoju: wave | bow | twirl | slash
        self.act_t, self.act_dur, self.last_act = 0.0, 1.0, None
        self.act_fx = False
        self.tap = False               # niecierpliwe przytupywanie (pożegnanie)
        self.bubble_a = 0.0            # widoczność dymka „Do zobaczenia w grze!”
        self.fw_t = self.fw_t0 = None  # zegar pożegnania i chwila dotarcia na koniec paska
        self.fw_total = 10.0
        self.fw_strike = self.fw_cancel = None
        self.fw_jumped = False

    PLANT_TIME = 0.45

    # ------------------------------------------------------------------ sterowanie
    def set_rails(self, rails: dict) -> None:
        self.rails = rails
        if rails and not self.placed and "title" in rails:
            x0, x1, y = rails["title"]
            self.x, self.y, self.placed = x0 + (x1 - x0) * 0.25, y, True
        elif self.jump is None and self.rail in rails:
            self.y = rails[self.rail][2]

    def set_mode(self, mode: str) -> None:
        if mode != self.mode:
            self.mode = mode
            self.celebrate_timer = 0.0

    def set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))

    def bar_x(self) -> float:
        x0, x1, _ = self.rails["bar"]
        return x0 + (x1 - x0) * self.progress

    def _start_jump(self, end: tuple, dur: float, height: float) -> None:
        self.jump = {"start": (self.x, self.y), "end": end, "u": 0.0, "dur": dur, "h": height}
        dx = end[0] - self.x
        if abs(dx) > 4:
            self.facing = 1 if dx > 0 else -1

    def _puff(self, count: int, color=None) -> None:
        for _ in range(count):
            self.dust.append([self.x + random.uniform(-6, 6), self.y - 1, random.uniform(-26, 26),
                              random.uniform(-22, -4), random.uniform(0.35, 0.7), random.uniform(1.6, 3.4), color])

    def _begin_idle(self, duration: float) -> None:
        """Postój: często z drobną scenką (machanie flagą, ukłon, młynek, cięcie)."""
        self.sub, self.sub_time = "idle", duration
        self.act = None
        if self.mode == "patrol" and random.random() < 0.8:
            choices = [a for a in self.ACTS if a != self.last_act]
            self.act = self.last_act = random.choice(choices)
            self.act_t, self.act_dur, self.act_fx = 0.0, self.ACTS[self.act], False
            self.sub_time = self.act_dur + random.uniform(0.2, 0.7)

    def plant_progress(self) -> float:
        """0 = flaga w ręku, 1 = wbita w koniec paska (celebrate po dobiegnięciu; pożegnanie: wbija i zabiera)."""
        if self.mode == "farewell":
            if self.fw_t0 is None or self.fw_cancel is not None:
                return 0.0
            rel = self.fw_t - self.fw_t0
            if rel < self.PLANT_TIME:
                return rel / self.PLANT_TIME
            if rel < self.FW_UNPLANT:
                return 1.0
            return max(0.0, 1.0 - (rel - self.FW_UNPLANT) / 0.4)
        if self.mode != "celebrate" or self.celebrate_timer <= 0:
            return 0.0
        return min(1.0, self.celebrate_timer / self.PLANT_TIME)

    # ------------------------------------------------------------------ pożegnanie (zamykanie instalatora)
    FW_BOW = 0.5          # od dotarcia: ukłon
    FW_UNPLANT = 2.2      # wyciągnięcie flagi
    FW_JUMP = 2.65        # skok na napis

    def start_farewell(self, total: float = 10.0) -> None:
        self.mode = "farewell"
        self.fw_t, self.fw_t0, self.fw_total = 0.0, None, float(total)
        self.fw_strike = self.fw_cancel = None
        self.fw_jumped = False
        self.act, self.tap = None, False
        self.rail = "bar" if self.jump is None else self.rail

    def strike(self) -> None:
        """Zero na liczniku: skok w stronę krzyżyka z cięciem."""
        if self.mode == "farewell" and self.fw_cancel is None and self.fw_strike is None:
            self.fw_strike = 0.0

    def cancel_farewell(self) -> None:
        if self.mode == "farewell" and self.fw_strike is None:
            self.fw_cancel = 0.0

    def _advance_jump(self, dt: float) -> bool:
        j = self.jump
        if j is None:
            return False
        j["u"] = min(1.0, j["u"] + dt / j["dur"])
        u = j["u"]
        self.x = j["start"][0] + (j["end"][0] - j["start"][0]) * u
        self.y = j["start"][1] + (j["end"][1] - j["start"][1]) * u - j["h"] * 4 * u * (1 - u)
        if u >= 1.0:
            self.x, self.y = j["end"]
            self.jump = None
            self._puff(7)
        return True

    def _update_farewell(self, dt: float) -> bool:
        self.fw_t += dt
        running = self._advance_jump(dt)
        self.bubble_a = 0.0
        if self.fw_cancel is not None:               # „Nie zamykaj”: wzruszenie ramion i powrót do biegania
            self.fw_cancel += dt
            self.tap = False
            self.act, self.act_dur, self.act_t = "shrug", 1.1, self.fw_cancel
            if self.fw_cancel >= 1.1 and self.jump is None:
                self.act = None
                self.mode = "patrol"
                self.sub, self.sub_time = "idle", 0.6
            return running
        if self.fw_strike is not None:               # cięcie w skoku przez krzyżyk
            self.fw_strike += dt
            self.tap = False
            self.act, self.act_dur = "slash", 0.5
            self.act_t = self.act_dur * (0.25 + 0.75 * min(1.0, self.fw_strike / 0.45))
            if not self.fw_jumped and self.jump is None:
                self.fw_jumped = True
                cx, cy = self.rails.get("corner", (self.x + 40, self.y - 40))
                self.facing = 1 if cx >= self.x else -1
                self._start_jump((cx + 20 * self.facing, self.y), 0.55, max(20.0, self.y - cy + 8))
                self.rail = "corner"
            return True
        if self.fw_t0 is None:                       # najpierw dobiegnij na koniec paska
            self.y = self.rails["bar"][2] if self.jump is None else self.y
            dx = self.bar_x() - self.x
            if abs(dx) > 6 and self.jump is None:
                self.facing = 1 if dx > 0 else -1
                self.x += math.copysign(min(abs(dx), (140 + 3 * abs(dx)) * dt), dx)
                return True
            if self.jump is None:
                self.fw_t0 = self.fw_t
                self.facing = -1                     # przodem do okna, plecami do krawędzi
                self._puff(8, QColor("#f4e9d2"))
            return running
        rel = self.fw_t - self.fw_t0
        self.bubble_a = max(0.0, min(1.0, (rel - 0.3) / 0.25, (self.FW_JUMP - 0.05 - rel) / 0.3))
        if rel < self.FW_BOW:
            self.act = None
        elif rel < self.FW_UNPLANT:
            self.act, self.act_dur, self.act_t = "bow", self.FW_UNPLANT - self.FW_BOW, rel - self.FW_BOW
        elif rel < self.FW_JUMP:
            self.act = None
        elif self.rail == "bar" and self.jump is None:
            x0, x1, y = self.rails["title"]
            self._start_jump((x1 - 4, y), 0.85, 70)
            self.rail = "title"
        if self.jump is None and self.rail == "title":
            cx = self.rails.get("corner", (self.x + 50, 0))[0]
            self.facing = 1 if cx >= self.x else -1  # czeka zwrócony do krzyżyka
            if self.fw_t >= self.fw_total - 3.0:
                self.act, self.act_dur, self.act_t = "ready", 3.0, self.fw_t - (self.fw_total - 3.0)
                self.tap = False
            else:
                self.act, self.act_dur, self.act_t = "wave", 2.6, rel % 2.6
                self.tap = True
        return running

    # ------------------------------------------------------------------ aktualizacja
    def update(self, dt: float) -> None:
        self.t += dt
        self.face_vis += (self.facing - self.face_vis) * min(1.0, dt * 14)
        for d in self.dust:
            d[0] += d[2] * dt
            d[1] += d[3] * dt
            d[3] += 40 * dt
            d[4] -= dt
        self.dust = [d for d in self.dust if d[4] > 0]
        if "title" not in self.rails or "bar" not in self.rails:
            return
        if self.mode == "farewell":
            running = self._update_farewell(dt)
            self.run_vis += ((1.0 if running else 0.0) - self.run_vis) * min(1.0, dt * 9)
            if running:
                self.phase += dt * 12.0
            return
        self.tap = False
        self.bubble_a = 0.0
        want = "title" if self.mode == "patrol" else "bar"
        if self.mode != "patrol" or self.jump is not None:
            self.act = None
        running = False

        if self.jump is None and want != self.rail:
            target_x = self._clamp("title", self.x) if want == "title" else self.bar_x()
            self._start_jump((target_x, self.rails[want][2]), 0.8, 64)
            self.rail = want

        if self.jump is not None:
            j = self.jump
            j["u"] = min(1.0, j["u"] + dt / j["dur"])
            u = j["u"]
            self.x = j["start"][0] + (j["end"][0] - j["start"][0]) * u
            self.y = j["start"][1] + (j["end"][1] - j["start"][1]) * u - j["h"] * 4 * u * (1 - u)
            if u >= 1.0:
                self.x, self.y = j["end"]
                self.jump = None
                self._puff(7)
            running = True
        elif self.mode == "patrol":
            x0, x1, y = self.rails["title"]
            self.y = y
            if self.sub == "run":
                running = True
                self.x += self.facing * 92 * dt
                if self.x <= x0 + 4 or self.x >= x1 - 4:
                    self.x = max(x0 + 4, min(x1 - 4, self.x))
                    self.facing = -self.facing
                    self._begin_idle(random.uniform(0.8, 2.2))
                self.hop_timer -= dt
                if self.hop_timer <= 0 and x0 + 90 < self.x < x1 - 90:
                    self.hop_timer = random.uniform(3.0, 7.0)
                    self._start_jump((self.x + self.facing * 74, y), 0.55, 24)
                    self.rail = "title"
                self.sub_time -= dt
                if self.sub_time <= 0:
                    self._begin_idle(random.uniform(1.0, 2.6))
            else:
                if self.act:
                    self.act_t += dt
                    if self.act == "slash" and not self.act_fx and self.act_t / self.act_dur > 0.5:
                        self.act_fx = True
                        self._puff(9, QColor("#ffb7c9"))
                    if self.act_t >= self.act_dur:
                        self.act = None
                self.sub_time -= dt
                if self.sub_time <= 0 and not self.act:
                    self.sub, self.sub_time = "run", random.uniform(2.5, 6.0)
                    if random.random() < 0.35:
                        self.facing = -self.facing
        elif self.mode == "bar":
            x0, x1, y = self.rails["bar"]
            self.y = y
            dx = self.bar_x() - self.x
            if abs(dx) > 2:
                self.facing = 1 if dx > 0 else -1
                self.x += math.copysign(min(abs(dx), (60 + 5 * abs(dx)) * dt), dx)
            running = True  # bieg w miejscu = trwa praca
        else:  # celebrate: najpierw dobiegnij do końca paska, potem podskakuj z rękami w górze
            self.y = self.rails["bar"][2]
            dx = self.bar_x() - self.x
            if abs(dx) > 6:
                self.facing = 1 if dx > 0 else -1
                self.x += math.copysign(min(abs(dx), (140 + 3 * abs(dx)) * dt), dx)
                running = True
            else:
                before = self.celebrate_timer
                self.celebrate_timer += dt
                self.facing = 1
                if before < self.PLANT_TIME <= self.celebrate_timer:
                    self._puff(8, QColor("#f4e9d2"))                       # wbicie flagi w ziemię
                since = self.celebrate_timer - self.PLANT_TIME - 0.1
                if since > 0 and since % 0.95 < dt:
                    self._start_jump((self.x, self.y), 0.55, 26)
                    self.rail = "bar"
                    self._puff(5, QColor("#ffd978"))

        self.run_vis += ((1.0 if running else 0.0) - self.run_vis) * min(1.0, dt * 9)
        if running:
            self.phase += dt * (11.0 + (4 if self.mode == "bar" else 0))
            self.dust_timer -= dt
            if self.dust_timer <= 0 and self.jump is None:
                self.dust_timer = 0.11
                self._puff(1)

    def _clamp(self, rail: str, x: float) -> float:
        x0, x1, _ = self.rails[rail]
        return max(x0 + 4, min(x1 - 4, x))

    # ------------------------------------------------------------------ rysowanie
    def draw(self, p: QPainter, robe: QColor, scarf: QColor, winter: float = 0.0, summer: float = 0.0) -> None:
        """winter/summer 0..1 – płynne przejście na strój zimowy / letni (z palety sceny)."""
        for d in self.dust:
            c = QColor(d[6]) if d[6] else QColor(235, 235, 235)
            c.setAlphaF(max(0.0, min(0.5, d[4])))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(d[0], d[1]), d[5], d[5])

        air = self.jump is not None
        plant = self.plant_progress()
        arms_up = self.mode == "celebrate" and plant >= 1.0 and (air or self.run_vis < 0.5)
        act, act_u = self.act, (self.act_t / self.act_dur if self.act else 0.0)
        run, ph, t = self.run_vis, self.phase, self.t

        p.save()
        p.translate(self.x, self.y)
        height_in_air = 0.0
        if air:
            u = self.jump["u"]
            height_in_air = self.jump["h"] * 4 * u * (1 - u)
        # cień
        shadow = QColor(0, 0, 0, int(70 * (1 - min(1.0, height_in_air / 40))))
        p.setPen(Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(QPointF(0, 0.5), 11 * abs(self.face_vis) + 2, 2.4)

        p.scale(self.face_vis, 1.0)
        pen_cap = Qt.RoundCap

        bob = -abs(math.sin(ph)) * 2.6 * run if not air else 0.0
        breathe = math.sin(t * 2.2) * 0.5 * (1 - run)
        hip = QPointF(0, -25.0 + bob)
        lean = 0.20 * run + (0.12 if air else 0.0)
        if act == "bow":
            lean += 0.85 * math.sin(math.pi * min(1.0, act_u)) ** 0.7
        elif act == "wave":
            lean -= 0.06
        shoulder = QPointF(hip.x() + math.sin(lean) * 18, hip.y() - math.cos(lean) * 18 + breathe)
        head = QPointF(shoulder.x() + math.sin(lean) * 9, shoulder.y() - math.cos(lean) * 9)
        neck = QPointF(shoulder.x(), shoulder.y() - 1.5)

        def limb(a: QPointF, b: QPointF, c: QPointF, width: float, color: QColor) -> None:
            pen = QPen(color, width, Qt.SolidLine, pen_cap, Qt.RoundJoin)
            p.setPen(pen)
            p.drawLine(QLineF(a, b))
            p.drawLine(QLineF(b, c))

        def leg(offset: float):
            if self.tap and offset == 0 and not air:      # przytupywanie przednią stopą
                beat = max(0.0, math.sin(t * 9.0))
                return pt(hip, 0.12, self.THIGH), pt(pt(hip, 0.12, self.THIGH), 0.12 - 0.9 * beat, self.SHIN)
            if air:
                th, kn = (1.0, 1.5) if offset == 0 else (-0.6, 1.0)
            else:
                swing = math.sin(ph + offset)
                th = 0.95 * swing * run + (0.07 if offset == 0 else -0.07) * (1 - run)
                kn = (0.2 + 0.95 * max(0.0, math.sin(ph + offset - 1.2))) * run
            knee = pt(hip, th, self.THIGH)
            foot = pt(knee, th - kn, self.SHIN)
            return knee, foot

        def slash_angle(u: float) -> float:
            if u < 0.25:
                return 4.3 - 0.3 * (u / 0.25)
            if u < 0.5:
                s_ = (u - 0.25) / 0.25
                return 4.0 - 2.7 * (1 - (1 - s_) ** 2)
            if u < 0.8:
                return 1.3
            return 1.3 - 1.2 * ((u - 0.8) / 0.2)

        def arm(offset: float):
            front = offset != 0.0
            if act == "shrug":                          # wzruszenie ramion: ręce na boki, dłonie w górę
                k = math.sin(math.pi * min(1.0, act_u))
                side = 1 if front else -1
                ua = side * (0.25 + 1.0 * k)
                fa = ua + side * 1.5 * k
            elif front and act == "ready":              # miecz uniesiony do cięcia, lekkie drżenie
                ua = fa = 4.15 + math.sin(t * 28) * 0.035
            elif front and 0.0 < plant < 1.0 and self.mode in ("celebrate", "farewell"):
                ua, fa = 0.55 + 0.4 * plant, 0.35
            elif front and act == "wave":
                sw = math.sin(t * 8)
                ua = 2.45 + 0.12 * sw
                fa = ua + 0.35 * sw
            elif front and act == "twirl":
                ua, fa = 2.2, 2.5 + math.sin(t * 11) * 0.2
            elif front and act == "slash":
                ua = fa = slash_angle(act_u)
            elif arms_up:
                ua = math.pi - (0.95 if offset == 0 else -0.95) + math.sin(t * 9) * 0.12
                fa = ua + (0.15 if offset == 0 else -0.15)
            elif air:
                ua, fa = (-1.1, -0.2) if offset == 0 else (1.3, 2.2)
            else:
                ua = -0.95 * math.sin(ph + offset) * run + 0.05 * math.sin(t * 2.2 + offset) * (1 - run)
                fa = ua + 0.35 + 0.9 * run
            elbow = pt(shoulder, ua, self.UPPER)
            hand = pt(elbow, fa, self.FORE)
            return elbow, hand

        far_robe, far_pants, far_skin = shade(robe, 0.7), shade(self.PANTS, 0.7), shade(self.SKIN, 0.82)

        # szarfa (z tyłu)
        pen = QPen(scarf, 4.0, Qt.SolidLine, pen_cap, Qt.RoundJoin)
        prev = QPointF(neck)
        for i in range(1, 10):
            wave = math.sin(t * 9 - i * 0.8) * (1.0 + i * 0.55) * (0.35 + run)
            rise = -i * (1.0 if air else 0.0)
            cur = QPointF(neck.x() - i * (4.2 + 3.4 * run), neck.y() + wave + rise + i * 0.35)
            pen.setWidthF(max(1.0, 4.2 - i * 0.36))
            p.setPen(pen)
            p.drawLine(QLineF(prev, cur))
            prev = cur

        # flaga na plecach (gdy ręce są zajęte mieczem lub radością) — za tułowiem
        flag_on_back = (act in ("slash", "ready", "shrug") or arms_up) and plant <= 0.0
        if flag_on_back and plant < 1.0:
            self._flag(p, QPointF(hip.x() - 3, hip.y() + 3), math.pi + 0.78, -1, t, 2.4 + 2.0 * run, (4, 30))

        # miecz na plecach (podczas cięcia jest w dłoni)
        slashing = (act == "slash" and 0.12 < act_u < 0.92) or act == "ready"
        if not slashing:
            p.setPen(QPen(QColor("#3a2a22"), 2.8, Qt.SolidLine, pen_cap))
            sword_top = QPointF(shoulder.x() - 4, shoulder.y() - 7)
            sword_end = QPointF(hip.x() + 11, hip.y() + 14)
            p.drawLine(QLineF(sword_top, sword_end))
            p.setPen(Qt.NoPen)
            p.setBrush(self.METAL)
            p.drawEllipse(sword_top, 1.9, 1.9)
            p.setPen(QPen(scarf, 1.2, Qt.SolidLine, pen_cap))
            p.drawLine(QLineF(sword_top, QPointF(sword_top.x() - 4, sword_top.y() + 5 + math.sin(t * 6) * 1.2)))

        # tylna noga i ręka
        knee, foot = leg(math.pi)
        limb(hip, knee, foot, 4.6, far_pants)
        elbow, hand = arm(0.0)
        limb(shoulder, elbow, hand, 3.6, far_robe)
        fan_hand = hand if (summer > 0.05 and not air and not arms_up and act != "bow") else None
        p.setPen(Qt.NoPen)
        p.setBrush(far_skin)
        p.drawEllipse(hand, 1.9, 1.9)

        # poły szaty (łopoczą)
        tail = QPolygonF([
            QPointF(hip.x() - 3, hip.y() - 3), QPointF(hip.x() - 9 - 8 * run, hip.y() + 2 + math.sin(t * 10) * 1.6 * run),
            QPointF(hip.x() - 15 - 11 * run, hip.y() + 9 + math.sin(t * 10 + 1) * 2.2 * run),
            QPointF(hip.x() - 2, hip.y() + 13),
        ])
        p.setBrush(far_robe)
        p.drawPolygon(tail)

        if winter > 0.02:   # długi płaszcz z futrzanym obszyciem, łopocze przy biegu
            flap = math.sin(t * 7) * 2.0 * (0.3 + run)
            cloak = QPolygonF([
                QPointF(shoulder.x() - 5, shoulder.y() + 1), QPointF(shoulder.x() + 3, shoulder.y() + 1),
                QPointF(hip.x() + 4, hip.y() + 8),
                QPointF(hip.x() - 3 - 12 * run, hip.y() + 16 + flap),
                QPointF(hip.x() - 9 - 21 * run, hip.y() + 13 + flap * 1.4),
            ])
            p.setBrush(with_alpha_c(shade(robe, 0.62), winter))
            p.drawPolygon(cloak)
            p.setPen(QPen(with_alpha_c(QColor("#f4f1ea"), winter), 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(QPointF(hip.x() - 3 - 12 * run, hip.y() + 16 + flap),
                              QPointF(hip.x() - 9 - 21 * run, hip.y() + 13 + flap * 1.4)))
            p.setPen(Qt.NoPen)

        # tułów
        body = QPolygonF([
            QPointF(shoulder.x() - 5, shoulder.y()), QPointF(shoulder.x() + 5, shoulder.y()),
            QPointF(hip.x() + 7, hip.y() + 3), QPointF(hip.x() + 9, hip.y() + 14),
            QPointF(hip.x() - 9, hip.y() + 14), QPointF(hip.x() - 7, hip.y() + 3),
        ])
        p.setBrush(robe)
        p.drawPolygon(body)
        p.setBrush(scarf)  # pas i wykończenie rąbka
        p.drawRect(QRectF(hip.x() - 7.5, hip.y() + 1.5, 15, 3))
        p.setBrush(shade(robe, 1.25))
        p.drawRect(QRectF(hip.x() - 9, hip.y() + 12.5, 18, 1.6))

        if fan_hand is not None:   # wachlarz rysowany przed tułowiem, żeby był widoczny
            self._fan(p, QPointF(fan_hand.x() + 4, fan_hand.y() - 2), t, scarf, summer)
            p.setPen(Qt.NoPen)
            p.setBrush(far_skin)
            p.drawEllipse(QPointF(fan_hand.x() + 4, fan_hand.y() - 2), 1.9, 1.9)

        if winter > 0.02:
            fur = with_alpha_c(QColor("#f4f1ea"), winter)
            p.setBrush(fur)
            for k, (dx, dy, r) in enumerate(((-3.5, 1.0, 3.6), (0.0, 0.2, 3.9), (3.5, 1.0, 3.4))):
                p.drawEllipse(QPointF(neck.x() + dx, neck.y() + dy + 1.5), r, r * 0.8)

        # przednia noga
        knee, foot = leg(0.0)
        limb(hip, knee, foot, 4.8, self.PANTS)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161b2b"))
        p.drawEllipse(QPointF(foot.x() + 1.6, foot.y()), 3.4, 2.0)

        # przednia ręka
        elbow, hand = arm(math.pi)
        limb(shoulder, elbow, hand, 3.8, robe)
        holding = not (act in ("slash", "ready", "shrug") or arms_up or self.mode == "celebrate" or plant > 0)
        if act == "slash" and slashing:
            self._slash_fx(p, shoulder, hand, elbow, act_u, slash_angle(act_u))
        elif act == "ready":
            self._slash_fx(p, shoulder, hand, elbow, 0.1, 4.15)
        if holding:
            if act == "twirl":
                theta = t * 11.0
            elif act == "wave":
                theta = math.pi + math.sin(t * 8 + 0.8) * 0.55
            else:
                theta = math.pi + 0.22 + 0.10 * run + (0.2 if air else 0.0)
            self._flag(p, hand, theta, -1, t, 2.0 + 3.2 * run + (4.0 if act in ("wave", "twirl") else 0.0), (9, 41))
        p.setPen(Qt.NoPen)
        p.setBrush(self.SKIN)
        p.drawEllipse(hand, 2.0, 2.0)

        # głowa, kok, kapelusz
        p.setBrush(self.SKIN)
        p.drawEllipse(head, 5.6, 5.8)
        p.setPen(QPen(QColor("#2a2230"), 1.4, Qt.SolidLine, pen_cap))
        p.drawPoint(QPointF(head.x() + 2.6, head.y() + 0.8))
        p.setPen(Qt.NoPen)
        hat_y = head.y() - 3.0
        p.setBrush(shade(self.STRAW, 0.82))
        p.drawEllipse(QPointF(head.x(), hat_y + 1.2), 13.5, 3.4)
        cone = QPainterPath()
        cone.moveTo(head.x() - 11, hat_y + 0.6)
        cone.quadTo(head.x() - 4, hat_y - 3, head.x(), hat_y - 11)
        cone.quadTo(head.x() + 4, hat_y - 3, head.x() + 11, hat_y + 0.6)
        cone.closeSubpath()
        p.setBrush(self.STRAW)
        p.drawPath(cone)
        p.setPen(QPen(shade(self.STRAW, 0.7), 0.9))
        p.drawLine(QLineF(head.x() - 2, hat_y - 1, head.x() - 5, hat_y + 0.2))
        p.drawLine(QLineF(head.x() + 2, hat_y - 1, head.x() + 5, hat_y + 0.2))
        p.setPen(QPen(scarf, 1.1))
        p.drawLine(QLineF(head.x() - 5, hat_y + 3.0, head.x() - 5, hat_y + 8.5))  # tasiemka pod brodą
        if winter > 0.02:
            snow = with_alpha_c(QColor("#ffffff"), winter)
            p.setPen(Qt.NoPen)
            p.setBrush(snow)
            cap = QPainterPath()
            cap.moveTo(head.x() - 4.2, hat_y - 5.2)
            cap.quadTo(head.x(), hat_y - 13.5, head.x() + 4.2, hat_y - 5.2)
            cap.quadTo(head.x(), hat_y - 3.8, head.x() - 4.2, hat_y - 5.2)
            p.drawPath(cap)
            p.drawEllipse(QPointF(head.x() - 9.0, hat_y + 0.6), 2.6, 0.9)
            p.drawEllipse(QPointF(head.x() + 8.0, hat_y + 0.8), 2.0, 0.8)
            # para z ust w mroźnym powietrzu
            cycle = (t % 2.2) / 2.2
            if cycle < 0.55:
                u = cycle / 0.55
                for k in range(3):
                    uk = max(0.0, u - k * 0.15)
                    if uk <= 0:
                        continue
                    p.setBrush(QColor(255, 255, 255, int(150 * winter * (1 - uk))))
                    p.drawEllipse(QPointF(head.x() + 7 + uk * 9 + k * 2, head.y() + 2 - uk * 5), 1.4 + uk * 2.4,
                                  1.2 + uk * 2.0)
        if summer > 0.05:   # kwiat za opaską kapelusza
            fc = QPointF(head.x() - 7.5, hat_y - 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(with_alpha_c(QColor("#ff5d8f"), summer))
            for k in range(5):
                a = k * math.tau / 5 + t * 0.4
                p.drawEllipse(QPointF(fc.x() + math.cos(a) * 1.9, fc.y() + math.sin(a) * 1.9), 1.5, 1.5)
            p.setBrush(with_alpha_c(QColor("#ffd84d"), summer))
            p.drawEllipse(fc, 1.1, 1.1)
        p.restore()

        if self.bubble_a > 0.01:
            self._bubble(p, "Do zobaczenia w grze!", self.bubble_a)

        if plant > 0.0:
            gx, gy = self.x + 15, self.rails["bar"][2] if "bar" in self.rails else self.y
            e = 1 - (1 - plant) ** 2
            base = QPointF(self.x + 9 + (gx - self.x - 9) * e, gy - 32 * (1 - e))
            if plant >= 1.0:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 55))
                p.drawEllipse(QPointF(gx, gy + 0.5), 7, 2)
            self._flag(p, base, math.pi + 0.22 * (1 - e), 1, t, 3.6 if plant >= 1.0 else 2.0,
                       (9 * (1 - e), 31 + 12 * e), scale=1.0 + 0.45 * e)

    def _bubble(self, p: QPainter, text: str, alpha: float) -> None:
        """Dymek nad głową – po lewej stronie bohatera (stoi zwykle przy prawej krawędzi okna)."""
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        fm = QFontMetrics(font)
        w, h = fm.horizontalAdvance(text) + 18, 22
        lift = (1 - alpha) * 6
        x = self.x - w + 22
        y = self.y - 82 - h + lift
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 9, 9)
        tail = QPainterPath()
        tail.moveTo(x + w - 30, y + h - 1)
        tail.lineTo(x + w - 20, y + h + 8)
        tail.lineTo(x + w - 16, y + h - 1)
        path = path.united(tail)
        p.save()
        p.setOpacity(alpha)
        p.setPen(QPen(QColor(20, 30, 60, 120), 1.0))
        p.setBrush(QColor(255, 255, 255, 238))
        p.drawPath(path)
        p.setFont(font)
        p.setPen(QColor("#1b2550"))
        p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)
        p.restore()

    # ------------------------------------------------------------------ dodatki letnie
    def _fan(self, p: QPainter, hand: QPointF, t: float, scarf: QColor, summer: float) -> None:
        """Składany wachlarz – na postoju się nim wachluje, w biegu trzyma złożony."""
        p.save()
        p.translate(hand)
        idle = 1.0 - self.run_vis
        p.rotate(-35 + math.sin(t * 9) * 22 * idle)
        open_ang = 20 + 80 * idle
        fan = QPainterPath()
        fan.moveTo(0, 0)
        fan.arcTo(QRectF(-13, -13, 26, 26), 90 - open_ang / 2, open_ang)
        fan.closeSubpath()
        p.setPen(QPen(with_alpha_c(QColor("#7a4a26"), summer), 0.8))
        p.setBrush(with_alpha_c(QColor("#fff3d6"), summer))
        p.drawPath(fan)
        p.setPen(QPen(with_alpha_c(scarf, summer), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(-11, -11, 22, 22), int((90 - open_ang / 2) * 16), int(open_ang * 16))
        p.restore()

    # ------------------------------------------------------------------ flaga i efekty
    def _flag(self, p: QPainter, base: QPointF, theta: float, wind: int, t: float, amp: float,
              hold: tuple, scale: float = 1.0) -> None:
        """Tyczka od `base` w kierunku `theta` (jak w pt()) + falujące biało-czerwone płótno.
        wind = -1: płótno łopocze w lewo, +1: w prawo (lokalne współrzędne bohatera lub świat)."""
        d = QPointF(math.sin(theta), math.cos(theta))
        tail = QPointF(base.x() - d.x() * hold[0], base.y() - d.y() * hold[0])
        top = QPointF(base.x() + d.x() * hold[1], base.y() + d.y() * hold[1])
        p.setPen(QPen(self.POLE, 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(tail, top))
        p.setPen(Qt.NoPen)
        p.setBrush(self.METAL)
        p.drawEllipse(QPointF(top.x() + d.x() * 1.5, top.y() + d.y() * 1.5), 2.0, 2.0)
        width, height, cols = 21.0 * scale, 13.0 * scale, 7
        a_top = QPointF(top.x() - d.x() * 2.5, top.y() - d.y() * 2.5)
        a_bot = QPointF(a_top.x() - d.x() * height, a_top.y() - d.y() * height)
        tops, mids, bots = [], [], []
        for i in range(cols + 1):
            f = i / cols
            dx = wind * f * width
            wave = math.sin(t * 9.0 - f * 5.2) * amp * f
            droop = f * f * 2.5
            tops.append(QPointF(a_top.x() + dx, a_top.y() + wave + droop))
            bots.append(QPointF(a_bot.x() + dx * 0.97, a_bot.y() + wave * 0.9 + droop + f * 1.2))
            mids.append(QPointF((tops[-1].x() + bots[-1].x()) / 2, (tops[-1].y() + bots[-1].y()) / 2))
        edge = QPen(QColor(70, 0, 18, 110), 0.6)
        for upper, lower, colour in ((tops, mids, self.FLAG_WHITE), (mids, bots, self.FLAG_RED)):
            poly = QPolygonF(upper + lower[::-1])
            p.setPen(Qt.NoPen)
            p.setBrush(colour)
            p.drawPolygon(poly)
        for i in range(1, cols, 2):   # delikatne cieniowanie fałd
            quad = QPolygonF([tops[i], tops[i + 1], bots[i + 1], bots[i]])
            p.setBrush(QColor(0, 0, 0, 20))
            p.drawPolygon(quad)
        p.setPen(edge)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(tops + bots[::-1] + [tops[0]]))

    def _slash_fx(self, p: QPainter, shoulder: QPointF, hand: QPointF, elbow: QPointF, u: float, angle: float) -> None:
        """Ostrze w dłoni i półksiężycowy ślad cięcia."""
        tip = QPointF(hand.x() + math.sin(angle) * 17, hand.y() + math.cos(angle) * 17)
        p.setPen(QPen(QColor("#eef3ff"), 1.9, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(hand, tip))
        p.setPen(QPen(self.METAL, 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(hand, QPointF(hand.x() - math.sin(angle) * 3, hand.y() - math.cos(angle) * 3)))
        fade = 1.0 if u < 0.5 else max(0.0, 1.0 - (u - 0.5) / 0.3)
        if u < 0.28 or fade <= 0:
            return
        reach = 27.0
        steps = 12
        tail = min(angle + 1.5, 4.3)
        prev = None
        for i in range(steps + 1):
            a = tail + (angle - tail) * i / steps
            pnt = QPointF(shoulder.x() + math.sin(a) * reach, shoulder.y() + math.cos(a) * reach)
            if prev is not None:
                alpha = int(215 * fade * (i / steps) ** 1.4)
                p.setPen(QPen(QColor(255, 255, 255, alpha), 0.8 + 2.6 * i / steps, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QLineF(prev, pnt))
            prev = pnt
