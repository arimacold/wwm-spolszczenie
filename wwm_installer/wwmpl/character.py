"""Oryginalny bohater 2D (wędrowny szermierz w słomianym kapeluszu) animowany proceduralnie.

Jak to działa:
* Poza (pose) = słownik kątów i przesunięć szkieletu: biodra → tułów → głowa, ręce i nogi z dwoma segmentami.
* Scenki są klipami z klatkami kluczowymi (keyframes) i krzywymi wygładzania; między dowolnymi dwiema pozami
  (bieg ↔ scenka ↔ skok) zawsze jest płynne przenikanie, więc ruchy nigdy się nie „przeskakują” ani nie nakładają.
* Nogi na ziemi liczone są odwrotną kinematyką (IK) – stopy stoją w miejscu, gdy bohater się kłania lub robi wypad.
* Rekwizyty mają jeden stan naraz: flaga (w ręce / na plecach jak sashimono / wbita w ziemię), miecz (w pochwie / w
  dłoni), tykwa (u pasa / w dłoni). Zmieniają się wyłącznie w zdarzeniach klipów, dokładnie w chwili, gdy ręka
  jest przy nich – dzięki temu nic się nie dubluje.
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF

PI, TAU = math.pi, math.tau


# ------------------------------------------------------------------------------ narzędzia
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


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def smooth(x: float) -> float:
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in(x: float) -> float:
    x = clamp01(x)
    return x * x * x


def ease_back(x: float) -> float:
    """Lekkie przestrzelenie i powrót – „sprężyste” wejście w pozę."""
    x = clamp01(x)
    c = 1.5
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def ease_snap(x: float) -> float:
    """Bardzo szybki start, miękkie wyhamowanie – cięcia mieczem i kopnięcia."""
    x = clamp01(x)
    return 1 - (1 - x) ** 5


EASE = {"io": smooth, "out": ease_out, "in": ease_in, "back": ease_back, "snap": ease_snap, "lin": clamp01}


def envelope(u: float, a: float = 0.15, b: float = 0.15) -> float:
    return smooth(u / a) * smooth((1 - u) / b)


# ------------------------------------------------------------------------------ pozy
ANGLE_FIELDS = ("flag", "sword", "rot")
FLAG_UP = PI + 0.22          # drzewce pionowo w górę, lekko do tyłu
SHOULDER_REST = -2.55        # drzewce oparte o bark
STAND = {
    "hip_dx": 0.0, "hip_dy": 0.0, "lean": 0.02, "head": 0.0, "look": 1.0, "eyes": 1.0,
    "fx": 3.5, "bx": -3.0, "ikf": 1.0, "ikb": 1.0,          # stopy na ziemi (IK) i ich pozycje
    "lt": 0.07, "lk": 0.0, "bt": -0.07, "bk": 0.0,          # nogi bez IK: udo, zgięcie kolana
    "fu": 0.05, "ff": 0.45, "bu": -0.05, "bf": 0.3,          # ręce: ramię i przedramię (przednia / tylna)
    "flag": FLAG_UP, "amp": 2.0, "grip": 0.0, "sword": 4.5, "rot": 0.0, "squash": 1.0,
}
FIELDS = tuple(STAND)


def lerp_angle(a: float, b: float, w: float) -> float:
    d = (b - a + PI) % TAU - PI
    return a + d * w


def mix(a: dict, b: dict, w: float) -> dict:
    """Interpolacja dwóch póz; w może lekko wyjść poza 0..1 (krzywe ze sprężynowaniem)."""
    out = {}
    for k in FIELDS:
        if k in ANGLE_FIELDS:
            out[k] = lerp_angle(a[k], b[k], w)
        else:
            out[k] = a[k] + (b[k] - a[k]) * w
    return out


class Clip:
    """Animacja z klatek kluczowych. keys: (u, {pole: wartość}, krzywa) – brakujące pola przechodzą z poprzedniej
    klatki. events: (u, nazwa). hold = po końcu zostaje w ostatniej pozie (aż coś ją zastąpi)."""

    def __init__(self, name: str, dur: float, keys: list, events=(), hold=False, extra=None, blend=0.22):
        self.name, self.dur, self.hold, self.extra, self.blend = name, dur, hold, extra, blend
        self.events = sorted(events)
        frames, prev = [], dict(STAND)
        for entry in keys:
            cur = dict(prev)
            cur.update(entry[1])
            frames.append((entry[0], cur, EASE[entry[2]] if len(entry) > 2 else smooth))
            prev = cur
        self.frames = frames

    def sample(self, u: float) -> dict:
        fr = self.frames
        if u <= fr[0][0]:
            return dict(fr[0][1])
        for i in range(1, len(fr)):
            u1, p1, ease = fr[i]
            if u <= u1:
                u0, p0, _ = fr[i - 1]
                return mix(p0, p1, ease((u - u0) / (u1 - u0)) if u1 > u0 else 1.0)
        return dict(fr[-1][1])


# Wspólne fragmenty póz
LIFT = {"fu": 0.4, "ff": 1.2, "flag": PI, "hip_dy": -0.5}
STAB_BACK = {"fu": -0.9, "ff": -0.6, "flag": PI, "hip_dy": 5.5, "lean": 0.2, "fx": 6.5, "bx": -4.5,
             "bu": 0.3, "bf": 0.9}
UPRIGHT = {"hip_dy": 0.0, "hip_dx": 0.0, "lean": 0.02, "fx": 3.5, "bx": -3.0, "bu": -0.05, "bf": 0.3}
WAVE_UP = {"fu": 2.55, "ff": 2.85, "flag": PI - 0.1, "lean": -0.06, "bu": -0.55, "bf": 0.95, "amp": 6.0,
           "fx": 4.5, "bx": -3.5}
WAVE_LOW = dict(WAVE_UP, fu=1.95, ff=2.35, flag=PI - 0.55)   # pożegnanie przy górnej krawędzi okna
TWIRL_UP = {"fu": 2.85, "ff": 3.05, "grip": 1.0, "amp": 7.0, "lean": -0.05, "bu": -0.55, "bf": 0.95}
SIT = {"hip_dy": 17.0, "ikf": 0.0, "ikb": 0.0, "lt": 1.45, "lk": 2.7, "bt": 1.3, "bk": 2.55, "lean": 0.04,
       "head": 0.1, "fu": 0.75, "ff": 1.45, "bu": 0.6, "bf": 1.35, "eyes": 0.0}
CHEER_UP = {"fu": 2.8, "ff": 3.0, "bu": 2.4, "bf": 2.7, "lean": -0.07, "head": -0.1, "fx": 4.5, "bx": -3.5}
CROUCH = {"hip_dy": 5.0, "lean": 0.3, "squash": 0.93, "fx": 5.0, "bx": -4.0, "ikf": 1.0, "ikb": 1.0}
CROUCH_ARMS = {"fu": -0.35, "ff": 0.3, "bu": -0.9, "bf": -0.4}
LAND = {"hip_dy": 4.0, "lean": 0.18, "squash": 0.92, "fx": 4.5, "bx": -3.5, "ikf": 1.0, "ikb": 1.0}


def _wave_osc(h, q: dict, e: float) -> None:
    o = math.sin(h.t * 7.5)
    q["flag"] += 0.8 * o * e
    q["fu"] += 0.16 * o * e
    q["ff"] += 0.4 * math.sin(h.t * 7.5 - 0.7) * e
    q["hip_dy"] -= 0.8 * abs(o) * e
    q["head"] += 0.05 * o * e


def _x_wave(h, u, q):
    _wave_osc(h, q, envelope(u, 0.14, 0.14))


def _x_twirl(h, u, q):
    s = smooth((u - 0.14) / 0.72)
    q["flag"] += TAU * 3 * s
    q["ff"] += 0.12 * math.sin(TAU * 3 * s) * envelope(u, 0.14, 0.14)


def _x_drink(h, u, q):
    if 0.42 < u < 0.62:
        q["head"] += 0.05 * math.sin(h.t * 14)


def _x_meditate(h, u, q):
    e = smooth((u - 0.2) / 0.06) * smooth((0.82 - u) / 0.06)
    q["hip_dy"] -= e * (2.5 + 1.5 * math.sin(h.t * 1.6))
    q["lean"] += 0.02 * math.sin(h.t * 1.2) * e


def _x_stretch(h, u, q):
    e = smooth((u - 0.18) / 0.05) * smooth((0.47 - u) / 0.05)
    q["fu"] += 0.03 * math.sin(h.t * 31) * e
    q["bu"] += 0.03 * math.sin(h.t * 29) * e


def _x_shiver(h, u, q):
    e = envelope(u)
    q["hip_dx"] += 0.55 * math.sin(h.t * 47) * e
    q["bf"] += 0.28 * math.sin(h.t * 13) * e
    q["head"] += 0.03 * math.sin(h.t * 41) * e


def _x_fan(h, u, q):
    q["bf"] += 0.35 * math.sin(h.t * 12) * envelope(u)


def _x_ready(h, u, q):
    e = smooth((u - 0.26) / 0.05)
    q["fu"] += 0.02 * math.sin(h.t * 28) * e
    q["hip_dy"] += 0.35 * math.sin(h.t * 3.1) * e


def _x_flip(h, u, q):
    q["rot"] = -TAU * smooth((u - 0.1) / 0.75)


def _x_cheer(h, u, q):
    q["fu"] += 0.15 * math.sin(h.t * 12)
    q["bu"] -= 0.12 * math.sin(h.t * 12)


def _x_cheer_flip(h, u, q):
    _x_flip(h, u, q)


def build_clips() -> dict:
    clips = [
        # --- scenki podczas patrolu
        Clip("wave", 2.6, [(0, {}), (0.14, WAVE_UP, "back"), (0.86, {}), (1.0, STAND)], extra=_x_wave),
        Clip("bow", 2.2, [
            (0, {}),
            (0.18, {"fu": 0.0, "ff": 0.12, "bu": 0.0, "bf": 0.1, "flag": PI, "fx": 1.5, "bx": -1.5}),
            (0.30, {}),
            (0.55, {"lean": 0.88, "head": 0.28, "fu": 0.6, "ff": 0.62, "bu": 0.5, "bf": 0.55, "flag": PI - 0.5,
                    "hip_dx": -2.5, "hip_dy": 1.0}),
            (0.72, {}),
            (0.94, {"lean": 0.02, "head": 0.0, "fu": 0.0, "ff": 0.12, "bu": 0.0, "bf": 0.1, "flag": PI,
                    "hip_dx": 0.0, "hip_dy": 0.0}),
            (1.0, STAND)]),
        Clip("twirl", 2.4, [(0, {}), (0.14, TWIRL_UP, "back"), (0.86, {}), (1.0, STAND)], extra=_x_twirl),
        Clip("kata", 3.9, [
            (0, {}), (0.05, LIFT), (0.11, STAB_BACK, "snap"),
            (0.17, dict(UPRIGHT, fu=2.6, ff=3.2)),
            (0.23, {"fu": 3.75, "ff": 3.55, "sword": 4.4}),
            (0.31, {"fu": 3.3, "ff": 3.35, "sword": 3.45, "hip_dy": 3.5, "fx": 7.0, "bx": -7.0, "lean": 0.05,
                    "bu": 1.3, "bf": 2.0}),
            (0.36, {}),
            (0.42, {"fu": 1.2, "ff": 0.95, "sword": 1.0, "lean": 0.38, "hip_dx": 4.0, "hip_dy": 5.0, "fx": 12.0,
                    "bx": -6.0, "bu": -0.6, "bf": 0.0}, "snap"),
            (0.47, {}),
            (0.54, {"fu": 2.35, "ff": 2.5, "sword": 2.65, "lean": -0.05, "hip_dx": 2.0, "hip_dy": 2.0,
                    "bu": -1.0, "bf": -0.5}, "snap"),
            (0.59, {}),
            (0.63, {"fu": 0.7, "ff": 1.4, "sword": 1.57, "lean": 0.1, "hip_dx": 0.0, "hip_dy": 3.0,
                    "bu": 0.8, "bf": 1.5}),
            (0.69, {"fu": 1.55, "ff": 1.57, "sword": 1.57, "lean": 0.42, "hip_dx": 7.0, "hip_dy": 4.5,
                    "fx": 15.0, "bx": -6.0, "bu": -1.2, "bf": -0.9}, "snap"),
            (0.74, {}),
            (0.79, {"fu": 0.45, "ff": 0.55, "sword": 0.75, "lean": 0.15, "hip_dx": 3.0, "hip_dy": 3.0,
                    "fx": 8.0, "bx": -5.0, "bu": 0.0, "bf": 0.4}, "snap"),
            (0.81, {}),
            (0.87, dict(UPRIGHT, fu=3.65, ff=3.5, sword=4.5)),
            (0.93, dict(STAB_BACK, hip_dy=4.0)),
            (1.0, STAND)],
            events=[(0.11, "plant"), (0.23, "draw"), (0.87, "sheathe"), (0.93, "unplant")]),
        Clip("look", 3.0, [
            (0, {}),
            (0.12, {"flag": SHOULDER_REST, "fu": 0.85, "ff": 2.2, "grip": 0.35, "amp": 2.5}),
            (0.22, {"look": -1.0, "head": -0.04, "lean": -0.04, "hip_dx": -0.8}),
            (0.40, {}),
            (0.50, {"look": 1.0, "head": 0.0, "lean": 0.02, "hip_dx": 0.0}),
            (0.60, {"head": -0.38, "lean": -0.07}),
            (0.78, {}),
            (0.88, {"head": 0.0, "lean": 0.02}),
            (1.0, STAND)]),
        Clip("drink", 3.4, [
            (0, {}), (0.05, LIFT), (0.10, STAB_BACK, "snap"),
            (0.17, dict(UPRIGHT, fu=0.25, ff=0.25, lean=0.04, bu=-0.55, bf=0.95)),
            (0.22, {}),
            (0.32, {"fu": 1.25, "ff": 3.3, "head": -0.1}),
            (0.40, {"fu": 1.5, "ff": 3.7, "head": -0.5, "lean": -0.12}),
            (0.62, {}),
            (0.70, {"fu": 1.0, "ff": 2.4, "head": 0.0, "lean": 0.02}),
            (0.76, {"fu": 0.25, "ff": 0.25}),
            (0.80, {}),
            (0.88, dict(STAB_BACK, hip_dy=4.0, bu=-0.05, bf=0.3)),
            (1.0, STAND)],
            events=[(0.10, "plant"), (0.20, "take_gourd"), (0.77, "gourd_back"), (0.89, "unplant")],
            extra=_x_drink),
        Clip("meditate", 7.5, [
            (0, {}), (0.03, LIFT), (0.06, STAB_BACK, "snap"),
            (0.11, {"hip_dy": 6.0, "lean": 0.1, "fu": 0.3, "ff": 0.8, "bu": 0.2, "bf": 0.7, "fx": 5.0, "bx": -4.0}),
            (0.17, SIT),
            (0.84, {}),
            (0.90, {"hip_dy": 5.0, "ikf": 1.0, "ikb": 1.0, "lean": 0.12, "eyes": 1.0, "head": 0.0, "fu": 0.3,
                    "ff": 0.8, "bu": 0.2, "bf": 0.7, "fx": 5.0, "bx": -4.0}),
            (0.94, dict(STAB_BACK, hip_dy=4.5)),
            (1.0, STAND)],
            events=[(0.06, "plant"), (0.945, "unplant")], extra=_x_meditate),
        Clip("stretch", 2.6, [
            (0, {}),
            (0.22, {"fu": 2.95, "ff": 3.1, "bu": 2.7, "bf": 2.95, "lean": -0.16, "head": -0.3, "hip_dy": -1.5,
                    "flag": PI + 0.05, "amp": 3.5, "fx": 2.5, "bx": -2.5}),
            (0.32, {"eyes": 0.0}),
            (0.45, {"lean": -0.22, "head": -0.38}),
            (0.60, {"fu": 1.65, "ff": 2.0, "bu": -1.45, "bf": -1.1, "lean": 0.04, "head": 0.05, "hip_dy": 0.0,
                    "eyes": 1.0}),
            (0.76, {"fu": 0.2, "ff": 0.6, "bu": 0.1, "bf": 0.4, "lean": 0.32, "head": 0.25, "hip_dx": -1.5,
                    "hip_dy": 1.0}),
            (0.86, {}),
            (1.0, STAND)], extra=_x_stretch),
        Clip("kick", 1.5, [
            (0, {}),
            (0.10, {"head": 0.25, "lean": 0.08}),
            (0.22, {"ikf": 0.0, "lt": -0.45, "lk": 1.35, "lean": -0.04, "head": 0.18, "bu": 0.5, "bf": 1.0,
                    "hip_dy": 0.8}),
            (0.40, {"lt": 1.3, "lk": 0.05, "lean": -0.22, "bu": -0.7, "bf": -0.3, "hip_dy": -0.5, "head": 0.0},
             "snap"),
            (0.52, {"lt": 1.0, "lk": 0.4}),
            (0.68, {"ikf": 1.0, "lt": 0.07, "lk": 0.0, "lean": 0.02, "head": -0.18, "bu": -0.05, "bf": 0.3,
                    "hip_dy": 0.0}),
            (0.88, {}),
            (1.0, STAND)],
            events=[(0.0, "pebble"), (0.40, "kick")]),
        Clip("shiver", 2.6, [
            (0, {}),
            (0.15, {"flag": SHOULDER_REST, "fu": 0.95, "ff": 2.35, "grip": 0.35, "bu": 1.0, "bf": 2.15,
                    "lean": 0.14, "head": 0.18, "hip_dy": 1.5, "fx": 2.0, "bx": -2.0}),
            (0.85, {}), (1.0, STAND)], extra=_x_shiver),
        Clip("fan", 2.8, [
            (0, {}), (0.15, {"bu": 1.05, "bf": 2.65, "head": -0.12, "lean": -0.04}), (0.85, {}), (1.0, STAND)],
            extra=_x_fan),

        # --- finał instalacji i pożegnanie
        Clip("plant_big", 0.45, [
            (0, {}),
            (0.35, {"fu": 2.6, "ff": 2.9, "flag": PI, "hip_dy": -1.5, "lean": -0.05}),
            (0.70, {"fu": 0.8, "ff": 0.55, "flag": PI, "hip_dy": 5.5, "lean": 0.3, "fx": 7.0, "bx": -5.0}, "snap"),
            (1.0, {"fu": 0.35, "ff": 0.7, "hip_dy": 2.0, "lean": 0.1, "fx": 4.5, "bx": -3.5})],
            events=[(0.7, "plant_big")], blend=0.12),
        Clip("pickup", 0.45, [
            (0, {}),
            (0.5, {"fu": 0.8, "ff": 0.6, "flag": PI, "hip_dy": 4.0, "lean": 0.28, "fx": 7.0, "bx": -5.0}),
            (1.0, STAND)], events=[(0.5, "unplant")], blend=0.12),
        Clip("fw_bow", 1.7, [
            (0, {"fu": 0.0, "ff": 0.12, "bu": 0.0, "bf": 0.1, "fx": 1.5, "bx": -1.5}),
            (0.30, {"lean": 0.9, "head": 0.3, "fu": 0.62, "ff": 0.65, "bu": 0.55, "bf": 0.6, "hip_dx": -2.5,
                    "hip_dy": 1.0}),
            (0.65, {}),
            (0.95, {"lean": 0.02, "head": 0.0, "fu": 0.0, "ff": 0.12, "bu": 0.0, "bf": 0.1, "hip_dx": 0.0,
                    "hip_dy": 0.0}),
            (1.0, {})]),
        Clip("ready", 3.0, [
            (0, {}),
            (0.12, {"fu": 3.4, "ff": 3.15, "flag": PI + 0.35, "lean": 0.0}),
            (0.26, {"fu": 3.65, "ff": 3.45, "hip_dy": 4.5, "lean": 0.3, "fx": 9.0, "bx": -7.0, "bu": 1.0,
                    "bf": 1.55, "head": -0.06, "eyes": 0.5}),
            (1.0, {})], events=[(0.12, "stow")], hold=True, extra=_x_ready),
        Clip("shrug", 1.1, [
            (0, {}),
            (0.3, {"fu": 0.35, "ff": 1.95, "bu": -0.35, "bf": -1.95, "head": 0.18, "hip_dy": -1.0, "lean": -0.03}),
            (0.72, {}), (1.0, STAND)]),
        Clip("sheathe_quick", 0.45, [(0, {}), (0.6, {"fu": 3.65, "ff": 3.5, "sword": 4.5}), (1.0, STAND)],
             events=[(0.6, "sheathe")], blend=0.1),
        Clip("unstow", 0.5, [(0, {}), (0.5, {"fu": 3.4, "ff": 3.15, "flag": PI + 0.35}), (1.0, STAND)],
             events=[(0.5, "unstow")], blend=0.1),

        # --- fazy skoku (u = postęp lotu)
        Clip("hop", 1.0, [
            (0.0, {"ikf": 0.0, "ikb": 0.0, "lt": -0.25, "lk": 0.25, "bt": -0.65, "bk": 0.55, "lean": 0.16,
                   "fu": 0.9, "ff": 2.0, "bu": 1.3, "bf": 1.9, "squash": 1.07, "flag": PI + 0.42, "amp": 5.0}),
            (0.32, {"lt": 1.25, "lk": 1.95, "bt": 0.45, "bk": 1.6, "lean": 0.12, "fu": 1.1, "ff": 2.1, "bu": -1.0,
                    "bf": -0.4, "squash": 1.0}),
            (0.68, {}),
            (1.0, {"lt": 0.5, "lk": 0.4, "bt": -0.2, "bk": 0.55, "lean": 0.05, "fu": 0.7, "ff": 1.5, "bu": -0.6,
                   "bf": -0.1})]),
        Clip("flip", 1.0, [
            (0.0, {"ikf": 0.0, "ikb": 0.0, "lt": -0.25, "lk": 0.25, "bt": -0.65, "bk": 0.55, "lean": 0.1,
                   "fu": 1.6, "ff": 2.6, "bu": 2.0, "bf": 2.6, "squash": 1.08, "flag": PI + 0.42, "amp": 5.0}),
            (0.28, {"lt": 1.75, "lk": 2.7, "bt": 1.55, "bk": 2.6, "fu": 1.3, "ff": 2.4, "bu": 1.1, "bf": 2.2,
                    "squash": 1.0, "lean": 0.25}),
            (0.75, {}),
            (1.0, {"lt": 0.5, "lk": 0.4, "bt": -0.2, "bk": 0.55, "lean": 0.05, "fu": 0.7, "ff": 1.5, "bu": -0.6,
                   "bf": -0.1})], extra=_x_flip),
        Clip("cheer", 1.0, [
            (0.0, dict(CHEER_UP, ikf=0.0, ikb=0.0, lt=-0.2, lk=0.3, bt=-0.5, bk=0.5, squash=1.06)),
            (0.35, {"lt": 1.0, "lk": 1.7, "bt": 0.3, "bk": 1.4, "squash": 1.0}),
            (0.7, {}),
            (1.0, {"lt": 0.4, "lk": 0.4, "bt": -0.2, "bk": 0.5})], extra=_x_cheer),
        Clip("cheer_flip", 1.0, [
            (0.0, dict(CHEER_UP, ikf=0.0, ikb=0.0, lt=-0.2, lk=0.3, bt=-0.5, bk=0.5, squash=1.08)),
            (0.28, {"lt": 1.75, "lk": 2.7, "bt": 1.55, "bk": 2.6, "fu": 1.3, "ff": 2.4, "bu": 1.1, "bf": 2.2,
                    "squash": 1.0, "lean": 0.25}),
            (0.75, {}),
            (1.0, dict(CHEER_UP, lt=0.4, lk=0.4, bt=-0.2, bk=0.5, lean=0.0))], extra=_x_cheer_flip),
        Clip("strike", 1.0, [
            (0.0, {"ikf": 0.0, "ikb": 0.0, "sword": 4.3, "fu": 3.7, "ff": 3.6, "lean": 0.2, "lt": 0.6, "lk": 1.2,
                   "bt": -0.4, "bk": 0.8, "bu": 1.0, "bf": 1.5, "eyes": 0.5}),
            (0.35, {"sword": 1.1, "fu": 1.3, "ff": 1.2, "lean": 0.5, "lt": 1.1, "lk": 0.3, "bt": -1.0, "bk": 0.5,
                    "bu": -1.3, "bf": -1.0}, "snap"),
            (1.0, {"sword": 0.9, "fu": 1.0, "ff": 0.9, "lean": 0.35, "lt": 0.5, "lk": 0.4, "bt": -0.3, "bk": 0.6})]),
    ]
    return {c.name: c for c in clips}


CLIPS = build_clips()
JUMP_CLIPS = {"hop": "hop", "big": "hop", "flip": "flip", "cheer": "cheer", "cheer_flip": "cheer_flip",
              "strike": "strike"}
# Pula scenek podczas patrolu: nazwa -> waga (zimą dochodzi drżenie z zimna, latem wachlarz).
PATROL_ACTS = {"wave": 3.0, "bow": 2.0, "twirl": 3.0, "kata": 3.0, "look": 2.0, "drink": 2.0, "meditate": 1.2,
               "stretch": 2.0, "kick": 2.0}
SEASON_ACTS = ("shiver", "fan")
TRAIL_LIFE = 0.16


class Hero:
    THIGH, SHIN, UPPER, FORE = 13.0, 13.0, 8.5, 8.5
    SKIN = QColor("#f1c9a5")
    PANTS = QColor("#27304a")
    STRAW = QColor("#dcb46f")
    METAL = QColor("#e8c765")
    STEEL = QColor("#e4ebf7")
    LACQUER = QColor("#2b1d1a")
    GOURD = QColor("#c98b3e")
    FLAG_WHITE = QColor("#fbfbfb")
    FLAG_RED = QColor("#dc143c")
    POLE = QColor("#e4d2a6")
    ACTS = {name: CLIPS[name].dur for name in list(PATROL_ACTS) + list(SEASON_ACTS)}

    RUN_SPEED = 92.0
    ACCEL_PATROL = 520.0
    ACCEL_FAST = 1500.0
    PLANT_TIME = 0.45
    FW_BOW = 0.5          # od dotarcia na koniec paska: ukłon
    FW_UNPLANT = 2.2      # wyciągnięcie flagi
    FW_JUMP = 2.65        # skok na napis

    def __init__(self):
        self.x, self.y = 120.0, 120.0
        self.vx = 0.0
        self.facing, self.face_vis = 1, 1.0
        self.phase, self.t = 0.0, 0.0
        self.mode = "patrol"          # patrol | bar | celebrate | farewell
        self.rails: dict = {}         # nazwa -> (x0, x1, y); „corner” -> (x, y) krzyżyka
        self.rail = "title"
        self.placed = False
        self.progress = 0.0
        self.season = (0.0, 0.0)      # (zima, lato) z palety sceny
        # sterowanie ruchem
        self.goal: Optional[float] = None
        self.cruise = 0.0
        self.treadmill = False
        self.run_w = 0.0
        self.jump: Optional[dict] = None
        self.land_t, self.land_dur = 0.0, 0.2
        # patrol
        self.p_state, self.idle_left, self.run_left = "idle", 1.0, 3.0
        self.hop_timer = random.uniform(3.0, 6.0)
        self.recent = deque(maxlen=3)
        # scenki i rekwizyty
        self.action: Optional[Clip] = None
        self.action_t, self.action_id, self.fired = 0.0, 0, set()
        self.act: Optional[str] = None
        self.act_t, self.act_dur = 0.0, 1.0
        self.queue: list = []
        self.stance: Optional[str] = None
        self.tap = False
        self.flag_slot = "hand"       # hand | back | ground
        self.flag_ground: Optional[dict] = None
        self.wobble, self.wobble_v = 0.0, 0.0
        self.sword_slot = "back"      # back | hand
        self.gourd_slot = "hip"       # hip | hand
        self.fan_w = 0.0
        # świętowanie
        self.c_planted, self.c_timer, self.c_next, self.c_count = False, 0.0, 0.35, 0
        # pożegnanie
        self.bubble_a = 0.0
        self.fw_t = self.fw_t0 = None
        self.fw_total = 10.0
        self.fw_strike = self.fw_cancel = None
        self.fw_jumped = False
        self.fw_stages: set = set()
        # efekty
        self.dust: list = []          # [x, y, vx, vy, życie, rozmiar, kolor, grawitacja]
        self.dust_timer = 0.0
        self.mote_timer = 0.0
        self.pebbles: list = []
        self.trail: list = []         # [hx, hy, tx, ty, wiek] – smuga ostrza
        self.blink_in, self.blink_t = random.uniform(1.5, 4.0), 0.0
        # poza
        self.pose = dict(STAND)
        self.pose_key = "loco:"
        self.blend_from = dict(STAND)
        self.blend_t, self.blend_dur = 1.0, 0.2
        self.skel: dict = self._skeleton(self.pose)

    # ================================================================== sterowanie z zewnątrz
    def set_rails(self, rails: dict) -> None:
        self.rails = rails
        if rails and not self.placed and "title" in rails:
            x0, x1, y = rails["title"]
            self.x, self.y, self.placed = x0 + (x1 - x0) * 0.25, y, True
            self.vx = 0.0
            self._reset_props()
        elif self.jump is None and self.rail in rails and len(rails[self.rail]) == 3:
            self.y = rails[self.rail][2]

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        self.stance, self.tap, self.bubble_a = None, False, 0.0
        self.c_planted, self.c_timer, self.c_next, self.c_count = False, 0.0, 0.35, 0
        self._abort_action(cleanup=True)
        if mode == "patrol":
            self.p_state, self.idle_left = "idle", 0.5

    def set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, value))

    def bar_x(self) -> float:
        x0, x1, _ = self.rails["bar"]
        return x0 + (x1 - x0) * self.progress

    def plant_progress(self) -> float:
        """0 = flaga w ręku, 1 = wbita w koniec paska (świętowanie i pożegnanie)."""
        if self.mode not in ("celebrate", "farewell"):
            return 0.0
        if self.flag_slot == "ground" and self.flag_ground and self.flag_ground["big"]:
            return 1.0
        if self.action is not None and self.action.name == "plant_big":
            return min(1.0, self.action_t / self.PLANT_TIME)
        return 0.0

    def start_farewell(self, total: float = 10.0) -> None:
        self.mode = "farewell"
        self.fw_t, self.fw_t0, self.fw_total = 0.0, None, float(total)
        self.fw_strike = self.fw_cancel = None
        self.fw_jumped = False
        self.fw_stages = set()
        self.stance, self.tap = None, False
        self._abort_action(cleanup=True)
        if self.flag_ground and self.flag_ground["big"] and self.flag_ground["rail"] == "bar":
            self.queue = [item for item in self.queue if item != "fetch"]   # flaga już stoi na końcu paska

    def strike(self) -> None:
        """Zero na liczniku: skok w stronę krzyżyka z cięciem iai."""
        if self.mode == "farewell" and self.fw_cancel is None and self.fw_strike is None:
            self.fw_strike = 0.0

    def cancel_farewell(self) -> None:
        if self.mode == "farewell" and self.fw_strike is None and self.fw_cancel is None:
            self.fw_cancel = 0.0
            self.stance, self.tap = None, False
            self._abort_action(cleanup=False)
            self._start_action("shrug")

    # ================================================================== scenki i rekwizyty
    def _start_action(self, name: str) -> None:
        clip = CLIPS[name]
        self.action, self.action_t = clip, 0.0
        self.action_id += 1
        self.fired = set()
        self.act, self.act_t, self.act_dur = name, 0.0, clip.dur

    def _abort_action(self, cleanup: bool) -> None:
        self.action = None
        self.act = None
        self.queue = []
        self.pebbles = [pb for pb in self.pebbles if not pb["rest"]]
        if self.gourd_slot == "hand":
            self.gourd_slot = "hip"
        if cleanup:
            if self.sword_slot == "hand":
                self.queue.append("sheathe_quick")
            if self.flag_slot == "ground":
                self.queue.append("fetch")
            elif self.flag_slot == "back":
                self.queue.append("unstow")

    def _reset_props(self) -> None:
        self.action, self.act, self.queue, self.jump = None, None, [], None
        self.flag_slot, self.flag_ground = "hand", None
        self.sword_slot, self.gourd_slot = "back", "hip"
        self.trail, self.pebbles = [], []

    def _run_queue(self) -> bool:
        """Sprzątanie rekwizytów (schowaj miecz, podnieś flagę) przed zmianą zajęcia. True = jeszcze trwa."""
        if self.jump is not None or self.action is not None:
            return True
        while self.queue:
            item = self.queue[0]
            if item == "fetch":
                if self.flag_slot != "ground" or not self.flag_ground:
                    self.queue.pop(0)
                    continue
                if self.flag_ground["rail"] != self.rail:
                    self.flag_slot, self.flag_ground = "hand", None   # flaga na innej szynie – nie biegamy po nią
                    self.queue.pop(0)
                    continue
                gx = self._flag_world()[0]
                dx = gx - self.x
                if abs(dx) > 16:
                    self.goal = gx - math.copysign(12.0, dx)
                    if abs(self.goal - self.x) > 1.5 or abs(self.vx) > 10:
                        return True
                self.goal = None
                self.vx = 0.0
                if abs(dx) > 0.5:
                    self.facing = 1 if dx > 0 else -1
                self.queue.pop(0)
                self._start_action("pickup")
                return True
            self.queue.pop(0)
            if item == "sheathe_quick" and self.sword_slot == "hand":
                self._start_action(item)
                return True
            if item == "unstow" and self.flag_slot == "back":
                self._start_action(item)
                return True
        return False

    def _event(self, name: str) -> None:
        if name in ("plant", "plant_big"):
            self._plant(big=name == "plant_big")
        elif name in ("unplant", "unstow"):
            self.flag_slot, self.flag_ground = "hand", None
        elif name == "stow":
            self.flag_slot = "back"
        elif name == "draw":
            self.sword_slot = "hand"
            hx, hy = self._world(self.skel["fh"])
            self._puff_at(hx, hy, 3, QColor("#f3f7ff"), spread=8, grav=-10)
        elif name == "sheathe":
            self.sword_slot = "back"
            sx, sy = self._world(QPointF(self.skel["shoulder"].x() - 3.0, self.skel["shoulder"].y() - 4.0))
            self._puff_at(sx, sy, 5, QColor("#ffe58a"), spread=10, grav=-20)   # „klik” tsuby
        elif name == "take_gourd":
            self.gourd_slot = "hand"
        elif name == "gourd_back":
            self.gourd_slot = "hip"
        elif name == "pebble":
            fx = self.x + self.facing * (self.pose["fx"] + 7.0)
            self.pebbles.append({"x": fx, "y": self.y - 1.6, "vx": 0.0, "vy": 0.0, "life": 9.0, "rest": True,
                                 "bounces": 0, "spin": 0.0})
        elif name == "kick":
            for pb in self.pebbles:
                if pb["rest"]:
                    pb.update(rest=False, vx=self.facing * random.uniform(120, 160), vy=-random.uniform(95, 135),
                              life=2.2, spin=random.uniform(8, 14) * self.facing)
            self._puff_at(self.x + self.facing * 9, self.y, 3)

    def _plant(self, big: bool) -> None:
        """Flaga trafia w ziemię dokładnie tam, gdzie jest dłoń – bez przeskoku."""
        if self.rail not in ("title", "bar"):
            return
        hx, hy = self._world(self.skel["fh"])
        x0, _, gy = self.rails[self.rail]
        theta = self.pose["flag"]
        top_y = hy + math.cos(theta) * (41 - 15 * self.pose["grip"])
        length0 = max(30.0, gy - top_y)
        self.flag_ground = {"rail": self.rail, "off": hx - x0, "L0": length0,
                            "L1": 62.0 if big else max(44.0, length0 - 10.0), "s0": 1.0, "s1": 1.45 if big else 1.0,
                            "sink": 0.0, "wind": -self.facing, "big": big}
        self.flag_slot = "ground"
        self.wobble, self.wobble_v = 0.0, -2.6 * self.facing
        self._puff_at(hx, gy, 8, QColor("#f4e9d2"), spread=7)

    def _flag_world(self) -> tuple:
        g = self.flag_ground
        rail = self.rails.get(g["rail"])
        if not rail or len(rail) != 3:
            return self.x, self.y
        return rail[0] + g["off"], rail[2]

    # ================================================================== aktualizacja
    def update(self, dt: float) -> None:
        dt = min(dt, 0.05)
        self.t += dt
        self.face_vis += (self.facing - self.face_vis) * min(1.0, dt * 16)
        self._step_effects(dt)
        if "title" not in self.rails or "bar" not in self.rails:
            self._update_pose(dt)
            return
        self.goal, self.cruise, self.treadmill = None, 0.0, False
        if self.mode == "farewell":
            self._brain_farewell(dt)
        else:
            self._brain(dt)
        self._step_action(dt)
        airborne = self._step_jump(dt)
        if not airborne:
            self._locomote(dt)
        self._update_pose(dt)
        self._sample_trail()

    # ---------------------------------------------------------------- mózg: patrol / pasek / radość
    def _brain(self, dt: float) -> None:
        self.bubble_a = 0.0
        if self.mode != "celebrate":
            self.stance = None
        if self._run_queue():
            return
        want = "title" if self.mode == "patrol" else "bar"
        if self.rail != want:
            if self.action is not None:
                self._abort_action(cleanup=True)
                if self._run_queue():
                    return
            target = self._clamp("title", self.x) if want == "title" else self.bar_x()
            self.vx = 0.0
            self._start_jump((target, self.rails[want][2]), 0.8, 64, "big")
            self.rail = want
            return
        if self.jump is not None:
            return
        self.y = self.rails[self.rail][2]
        if self.mode == "patrol":
            self._patrol(dt)
        elif self.mode == "bar":
            self.goal = self.bar_x()
            self.treadmill = True
            if abs(self.goal - self.x) < 2:
                self.facing = 1
        else:
            self._celebrate(dt)

    def _patrol(self, dt: float) -> None:
        if self.action is not None:
            return
        x0, x1, y = self.rails["title"]
        if self.p_state == "run":
            edge = (x1 - 6) if self.facing > 0 else (x0 + 6)
            dist = (edge - self.x) * self.facing
            stop = self.vx * self.vx / (2 * self.ACCEL_PATROL) + 2.0
            self.run_left -= dt
            if dist <= stop or self.run_left <= 0:
                self.cruise = 0.0
                if abs(self.vx) < 6:
                    self.vx = 0.0
                    if dist < 30:
                        self.facing = -self.facing
                    self._begin_idle()
                return
            self.cruise = self.facing * self.RUN_SPEED
            self.hop_timer -= dt
            if self.hop_timer <= 0 and abs(self.vx) > 70:
                flip = random.random() < 0.3
                dur = 0.78 if flip else 0.6
                reach = abs(self.vx) * dur
                if dist - reach > 50:
                    self.hop_timer = random.uniform(3.5, 7.5)
                    self._start_jump((self.x + self.facing * reach, y), dur, 40 if flip else 24,
                                     "flip" if flip else "hop")
        else:
            self.idle_left -= dt
            if self.idle_left <= 0:
                self.p_state, self.run_left = "run", random.uniform(2.5, 6.0)
                if random.random() < 0.35:
                    self.facing = -self.facing

    def _begin_idle(self) -> None:
        self.p_state, self.idle_left = "idle", random.uniform(0.5, 1.3)
        if random.random() < 0.85:
            self._start_action(self._choose_act())

    def _choose_act(self) -> str:
        winter, summer = self.season
        weights = dict(PATROL_ACTS)
        weights["shiver"] = 4.0 * winter
        weights["fan"] = 4.0 * summer
        for name in self.recent:
            weights.pop(name, None)
        names = [n for n, w in weights.items() if w > 0]
        pick = random.choices(names, [weights[n] for n in names])[0]
        self.recent.append(pick)
        return pick

    def _celebrate(self, dt: float) -> None:
        y = self.rails["bar"][2]
        if not self.c_planted:
            if self.action is not None or self.flag_slot != "hand":
                return
            self.goal = self.bar_x()
            if abs(self.goal - self.x) < 1.5 and abs(self.vx) < 12:
                self.goal, self.vx, self.facing = None, 0.0, 1
                self.c_planted = True
                self._start_action("plant_big")
            return
        if self.action is not None:
            return
        self.stance = "cheer"
        self.c_timer += dt
        if self.c_timer >= self.c_next:
            self.c_count += 1
            flip = self.c_count % 3 == 0
            self._start_jump((self.x, y), 0.78 if flip else 0.55, 36 if flip else 26, "cheer_flip" if flip else "cheer")
            self.c_next = self.c_timer + (1.3 if flip else 0.95)
            self._puff(5, QColor("#ffd978"))

    # ---------------------------------------------------------------- mózg: pożegnanie
    def _brain_farewell(self, dt: float) -> None:
        self.fw_t += dt
        self.bubble_a = 0.0
        if self.fw_cancel is not None:               # „Nie zamykaj”: wzruszenie ramion i powrót do biegania
            self.fw_cancel += dt
            if self.fw_cancel >= 1.1 and self.action is None and self.jump is None:
                self.set_mode("patrol")
                self.p_state, self.idle_left = "idle", 0.6
            return
        if self.fw_strike is not None:               # cięcie iai w skoku przez krzyżyk
            self.fw_strike += dt
            self.stance, self.tap = None, False
            if not self.fw_jumped and self.jump is None:
                self.fw_jumped = True
                self.action, self.act, self.queue = None, None, []
                if self.flag_slot == "hand":
                    self.flag_slot = "back"
                self.sword_slot = "hand"
                cx, cy = self.rails.get("corner", (self.x + 40, self.y - 40))
                self.facing = 1 if cx >= self.x else -1
                self._start_jump((cx + 20 * self.facing, self.y), 0.55, max(20.0, self.y - cy + 8), "strike", pre=0.04)
                self.rail = "corner"
            return
        if self._run_queue():
            return
        if self.fw_t0 is None:                       # najpierw dobiegnij na koniec paska
            if self.jump is not None or self.action is not None:
                return
            if self.rail != "bar":
                self.vx = 0.0
                self._start_jump((self.bar_x(), self.rails["bar"][2]), 0.8, 64, "big")
                self.rail = "bar"
                return
            self.y = self.rails["bar"][2]
            self.goal = self.bar_x()
            if self.flag_slot == "ground":
                self.goal = self.x                   # stoi przy wbitej fladze
            if abs(self.goal - self.x) < 1.5 and abs(self.vx) < 12:
                self.goal, self.vx = None, 0.0
                self.facing = 1
                if self.flag_slot == "hand":
                    self.fw_t0 = self.fw_t
                    self._start_action("plant_big")
                else:
                    self.fw_t0 = self.fw_t - self.PLANT_TIME      # flaga już wbita – od razu do ukłonu
            return
        rel = self.fw_t - self.fw_t0
        self.bubble_a = max(0.0, min(1.0, (rel - 0.3) / 0.25, (self.FW_JUMP - 0.05 - rel) / 0.3))
        stages = self.fw_stages
        if rel < self.FW_JUMP:
            if rel >= self.PLANT_TIME and "turn" not in stages:
                stages.add("turn")
                self.facing = -1                     # przodem do okna – ukłon dla gracza
            if rel >= self.FW_BOW and "bow" not in stages:
                stages.add("bow")
                self._start_action("fw_bow")
            if rel >= self.FW_UNPLANT and "pick" not in stages:
                stages.add("pick")
                self.facing = 1
                if self.flag_slot == "ground":
                    self._start_action("pickup")
            return
        if self.rail == "bar":
            if self.jump is None and self.action is None:
                if self.flag_slot == "ground":       # na wszelki wypadek – flaga nigdy nie zostaje
                    self.flag_slot, self.flag_ground = "hand", None
                x0, x1, y = self.rails["title"]
                self._start_jump((x1 - 4, y), 0.85, 70, "big")
                self.rail = "title"
            return
        if self.jump is not None:
            return
        self.y = self.rails["title"][2]
        cx = self.rails.get("corner", (self.x + 50, 0))[0]
        self.facing = 1 if cx >= self.x else -1     # czeka zwrócony do krzyżyka
        if self.fw_t >= self.fw_total - 3.0:
            if "ready" not in stages:
                stages.add("ready")
                self.stance, self.tap = None, False
                self._start_action("ready")
        elif self.action is None:
            self.stance = "wave" if self.flag_slot == "hand" else None
            self.tap = True

    # ---------------------------------------------------------------- ruch
    def _step_action(self, dt: float) -> None:
        clip = self.action
        if clip is None:
            self.act = None
            return
        self.action_t += dt
        u = self.action_t / clip.dur
        for index, (eu, name) in enumerate(clip.events):
            if eu <= u and index not in self.fired:
                self.fired.add(index)
                self._event(name)
        self.act_t = self.action_t
        if clip.name == "meditate" and 0.22 < u < 0.86:
            self.mote_timer -= dt
            if self.mote_timer <= 0:
                self.mote_timer = 0.16
                self.dust.append([self.x + random.uniform(-15, 15), self.y - random.uniform(4, 30),
                                  random.uniform(-4, 4), random.uniform(-16, -8), random.uniform(1.0, 1.6),
                                  random.uniform(1.0, 1.9), QColor("#ffe08a"), -4.0])
        if u >= 1.0 and not clip.hold:
            self.action, self.act = None, None
            if self.mode == "patrol":
                self.idle_left = max(self.idle_left, random.uniform(0.35, 0.9))

    def _start_jump(self, end: tuple, dur: float, height: float, kind: str = "hop", pre: float = 0.09) -> None:
        self.jump = {"start": (self.x, self.y), "end": end, "u": 0.0, "dur": dur, "h": height, "kind": kind,
                     "pre": pre, "id": self.action_id + random.random()}
        dx = end[0] - self.x
        if abs(dx) > 4:
            self.facing = 1 if dx > 0 else -1

    def _step_jump(self, dt: float) -> bool:
        j = self.jump
        if j is None:
            return False
        if j["pre"] > 0:
            j["pre"] -= dt
            return True
        j["u"] = min(1.0, j["u"] + dt / j["dur"])
        u = j["u"]
        self.x = j["start"][0] + (j["end"][0] - j["start"][0]) * u
        self.y = j["start"][1] + (j["end"][1] - j["start"][1]) * u - j["h"] * 4 * u * (1 - u)
        if u >= 1.0:
            self.x, self.y = j["end"]
            self.jump = None
            self.land_dur = 0.26 if j["h"] > 45 else 0.18
            self.land_t = self.land_dur
            self._puff(7)
        return True

    def _locomote(self, dt: float) -> None:
        fast = self.mode != "patrol" or bool(self.queue)
        accel = self.ACCEL_FAST if fast else self.ACCEL_PATROL
        if self.action is not None:
            target = 0.0
        elif self.goal is not None:
            dx = self.goal - self.x
            vmax = min(520.0, (70 + 5 * abs(dx)) if self.mode == "bar" else (130 + 3 * abs(dx)))
            target = math.copysign(min(vmax, math.sqrt(2 * accel * abs(dx)) * 0.92), dx) if abs(dx) > 0.4 else 0.0
        else:
            target = self.cruise
        step = accel * dt
        self.vx += max(-step, min(step, target - self.vx))
        self.x += self.vx * dt
        if self.goal is not None and abs(self.goal - self.x) < 0.6 and abs(self.vx) < 8:
            self.x, self.vx = self.goal, 0.0
        if self.action is None and abs(self.vx) > 4:
            self.facing = 1 if self.vx > 0 else -1
        speed = abs(self.vx)
        want = min(1.0, speed / 90.0)
        if self.treadmill:
            want = max(want, 0.85)
        self.run_w += (want - self.run_w) * min(1.0, dt * 10)
        self.phase += dt * (max(speed * 0.125, 14.0 if self.treadmill else 0.0))
        if self.run_w > 0.55:
            self.dust_timer -= dt
            if self.dust_timer <= 0:
                self.dust_timer = 0.11
                self._puff(1)

    def _clamp(self, rail: str, x: float) -> float:
        x0, x1, _ = self.rails[rail]
        return max(x0 + 4, min(x1 - 4, x))

    # ---------------------------------------------------------------- efekty
    def _puff(self, count: int, color=None) -> None:
        self._puff_at(self.x, self.y - 1, count, color)

    def _puff_at(self, x: float, y: float, count: int, color=None, spread: float = 6.0, grav: float = 40.0) -> None:
        for _ in range(count):
            self.dust.append([x + random.uniform(-spread, spread), y, random.uniform(-26, 26),
                              random.uniform(-22, -4), random.uniform(0.35, 0.7), random.uniform(1.6, 3.4), color,
                              grav])

    def _step_effects(self, dt: float) -> None:
        for d in self.dust:
            d[0] += d[2] * dt
            d[1] += d[3] * dt
            d[3] += d[7] * dt
            d[4] -= dt
        self.dust = [d for d in self.dust if d[4] > 0]
        for pb in self.pebbles:
            if pb["rest"]:
                continue
            pb["vy"] += 380 * dt
            pb["x"] += pb["vx"] * dt
            pb["y"] += pb["vy"] * dt
            pb["life"] -= dt
            rail = self.rails.get(self.rail)
            floor = rail[2] - 1.6 if rail and len(rail) == 3 and rail[0] <= pb["x"] <= rail[1] else 1e9
            if pb["y"] >= floor and pb["vy"] > 0:
                pb["y"] = floor
                pb["bounces"] += 1
                pb["vy"] *= -0.38
                pb["vx"] *= 0.55
                if pb["bounces"] == 1:
                    self._puff_at(pb["x"], floor, 2)
                if abs(pb["vy"]) < 18:
                    pb["vy"] = 0.0
                    pb["vx"] *= 0.8
        self.pebbles = [pb for pb in self.pebbles if pb["life"] > 0]
        if self.flag_ground is not None:
            self.flag_ground["sink"] = min(1.0, self.flag_ground["sink"] + dt / 0.14)
        self.wobble_v += (-95 * self.wobble - 6.5 * self.wobble_v) * dt
        self.wobble += self.wobble_v * dt
        for tr in self.trail:
            tr[4] += dt
        self.trail = [tr for tr in self.trail if tr[4] < TRAIL_LIFE]
        if self.land_t > 0:
            self.land_t = max(0.0, self.land_t - dt)
        self.blink_in -= dt
        if self.blink_in <= 0:
            self.blink_t, self.blink_in = 0.13, random.uniform(2.0, 5.0)
        self.blink_t = max(0.0, self.blink_t - dt)
        summer = self.season[1]
        fan_on = (self.act == "fan") or (self.act is None and self.mode == "patrol" and self.stance is None
                                          and self.jump is None and self.run_w < 0.3 and summer > 0.3)
        self.fan_w += ((1.0 if fan_on else 0.0) - self.fan_w) * min(1.0, dt * 6)

    def _sample_trail(self) -> None:
        if self.sword_slot != "hand":
            return
        hand = self.skel["fh"]
        a = self.pose["sword"]
        inner = self._world(pt(hand, a, 6.0))
        tip = self._world(pt(hand, a, 19.0))
        if self.trail and math.hypot(tip[0] - self.trail[-1][2], tip[1] - self.trail[-1][3]) < 1.2:
            return
        self.trail.append([inner[0], inner[1], tip[0], tip[1], 0.0])

    # ================================================================== poza
    def _idle_pose(self) -> dict:
        t = self.t
        b = math.sin(t * 2.1)
        q = dict(STAND)
        q["hip_dy"] = 0.35 * (1 + b) * 0.5
        q["lean"] += 0.015 * b
        q["fu"] += 0.03 * b
        q["bu"] += 0.05 * math.sin(t * 2.1 + 0.8)
        q["flag"] += 0.035 * math.sin(t * 1.4)
        q["hip_dx"] = 0.6 * math.sin(t * 0.45)
        return q

    def _run_pose(self) -> dict:
        ph = self.phase
        q = dict(STAND)
        q.update(ikf=0.0, ikb=0.0, lean=0.22, head=-0.12, amp=5.5)
        q["hip_dy"] = -abs(math.sin(ph)) * 2.6 + 0.8
        for leg, off in (("l", 0.0), ("b", PI)):
            q[leg + "t"] = 0.95 * math.sin(ph + off)
            q[leg + "k"] = 0.25 + 1.05 * max(0.0, math.sin(ph + off - 1.2))
        q["bu"] = 0.9 * math.sin(ph)                 # tylna ręka idzie razem z przednią nogą
        q["bf"] = q["bu"] + 1.25
        if self.flag_slot == "hand":                 # z flagą przednia ręka trzyma ją przed piersią
            q["fu"] = 0.55 - 0.25 * math.sin(ph)
            q["ff"] = q["fu"] + 1.25
            q["flag"] = PI + 0.38 + 0.08 * math.sin(ph)
        else:
            q["fu"] = -0.9 * math.sin(ph)
            q["ff"] = q["fu"] + 1.25
        return q

    def _stance_pose(self, base: dict) -> dict:
        q = dict(base)
        if self.stance == "cheer":
            q.update(CHEER_UP)
            _x_cheer(self, 0.0, q)
            q["hip_dy"] -= abs(math.sin(self.t * 4.5)) * 1.4
        elif self.stance == "wave":
            q.update(WAVE_LOW)
            _wave_osc(self, q, 0.75)
        return q

    def _target_pose(self) -> tuple:
        j = self.jump
        if j is not None:
            if j["pre"] > 0:
                q = self._stance_pose(self._idle_pose()) if self.stance else self._idle_pose()
                q.update(CROUCH)
                if j["kind"] not in ("cheer", "cheer_flip", "strike"):
                    q.update(CROUCH_ARMS)
                return f"crouch:{j['id']}", q
            clip = CLIPS[JUMP_CLIPS[j["kind"]]]
            q = clip.sample(j["u"])
            if clip.extra:
                clip.extra(self, j["u"], q)
            return f"jump:{j['id']}", q
        if self.action is not None:
            clip = self.action
            u = min(1.0, self.action_t / clip.dur)
            q = clip.sample(u)
            if clip.extra:
                clip.extra(self, u, q)
            return f"act:{self.action_id}", q
        q = mix(self._idle_pose(), self._run_pose(), smooth(self.run_w))
        if self.stance:
            q = self._stance_pose(q)
        return f"loco:{self.stance or ''}", q

    def _update_pose(self, dt: float) -> None:
        key, target = self._target_pose()
        if key != self.pose_key:
            old = self.pose_key.split(":")[0]
            new = key.split(":")[0]
            if new in ("jump", "crouch"):
                dur = 0.07
            elif old == "jump":
                dur = 0.1
            elif new == "act":
                dur = self.action.blend if self.action is not None else 0.2
            else:
                dur = 0.28
            self.blend_from, self.blend_t, self.blend_dur = dict(self.pose), 0.0, dur
            self.pose_key = key
        self.blend_t += dt
        w = smooth(self.blend_t / self.blend_dur) if self.blend_dur > 0 else 1.0
        q = mix(self.blend_from, target, w) if w < 1.0 else target
        if self.land_t > 0 and self.jump is None:
            k = (self.land_t / self.land_dur) ** 1.3 * 0.85
            landed = dict(q)
            landed.update(LAND)
            q = mix(q, landed, k)
        if self.tap and self.jump is None and self.action is None:
            beat = max(0.0, math.sin(self.t * 9.0))
            q["ikf"] = 0.0
            q["lt"] = 0.15 + 0.2 * beat
            q["lk"] = 0.12 + 0.45 * beat
        self.pose = q
        self.skel = self._skeleton(q)

    # ---------------------------------------------------------------- szkielet i IK
    def _solve_leg(self, hip: QPointF, foot: QPointF) -> tuple:
        dx, dy = foot.x() - hip.x(), foot.y() - hip.y()
        d = min(max(math.hypot(dx, dy), 4.0), self.THIGH + self.SHIN - 0.05)
        a = math.atan2(dx, dy)
        alpha = math.acos(max(-1.0, min(1.0, (self.THIGH ** 2 + d * d - self.SHIN ** 2) / (2 * self.THIGH * d))))
        return a + alpha, 2 * alpha

    def _leg(self, hip: QPointF, q: dict, front: bool) -> tuple:
        ik, th, kn, fx = (q["ikf"], q["lt"], q["lk"], q["fx"]) if front else (q["ikb"], q["bt"], q["bk"], q["bx"])
        ik = clamp01(ik)
        if ik > 0.001:
            ith, ikn = self._solve_leg(hip, QPointF(fx, 0.0))
            th += (ith - th) * ik
            kn += (ikn - kn) * ik
        knee = pt(hip, th, self.THIGH)
        return knee, pt(knee, th - kn, self.SHIN)

    def _skeleton(self, q: dict) -> dict:
        hip = QPointF(q["hip_dx"], -25.0 + q["hip_dy"])
        lean = q["lean"]
        shoulder = QPointF(hip.x() + math.sin(lean) * 18, hip.y() - math.cos(lean) * 18)
        tilt = lean + q["head"]
        head = QPointF(shoulder.x() + math.sin(tilt) * 9, shoulder.y() - math.cos(tilt) * 9)
        fk, ffoot = self._leg(hip, q, True)
        bk, bfoot = self._leg(hip, q, False)
        fe = pt(shoulder, q["fu"], self.UPPER)
        be = pt(shoulder, q["bu"], self.UPPER)
        return {"hip": hip, "shoulder": shoulder, "head": head, "neck": QPointF(shoulder.x(), shoulder.y() - 1.5),
                "fk": fk, "ffoot": ffoot, "bk": bk, "bfoot": bfoot, "fe": fe, "fh": pt(fe, q["ff"], self.FORE),
                "be": be, "bh": pt(be, q["bf"], self.FORE)}

    def _world(self, p_local: QPointF) -> tuple:
        """Lokalny punkt szkieletu -> współrzędne okna (z obrotem salta, ściśnięciem i kierunkiem)."""
        q = self.pose
        x, y = p_local.x(), p_local.y()
        r = q["rot"]
        if abs(r) > 1e-4:
            dy = y + 22.0
            c, s = math.cos(r), math.sin(r)
            x, y = x * c - dy * s, x * s + dy * c - 22.0
        sq = q["squash"]
        x *= 1 + (1 - sq) * 0.6
        y *= sq
        return self.x + x * self.face_vis, self.y + y

    def _ground_y(self) -> float:
        j = self.jump
        if j is None or j["pre"] > 0:
            return self.y
        return j["start"][1] + (j["end"][1] - j["start"][1]) * j["u"]

    # ================================================================== rysowanie
    def draw(self, p: QPainter, robe: QColor, scarf: QColor, winter: float = 0.0, summer: float = 0.0) -> None:
        """winter/summer 0..1 – płynne przejście na strój zimowy / letni (z palety sceny)."""
        self.season = (winter, summer)
        p.setPen(Qt.NoPen)
        for d in self.dust:
            c = QColor(d[6]) if d[6] else QColor(235, 235, 235)
            c.setAlphaF(max(0.0, min(0.8 if d[7] < 0 else 0.5, d[4])))
            p.setBrush(c)
            p.drawEllipse(QPointF(d[0], d[1]), d[5], d[5])
        for pb in self.pebbles:
            p.setBrush(QColor("#8b8f9c"))
            p.save()
            p.translate(pb["x"], pb["y"])
            p.rotate(pb["spin"] * (2.2 - pb["life"]) * 40)
            p.drawEllipse(QPointF(0, 0), 2.1, 1.6)
            p.setBrush(QColor("#c4c8d3"))
            p.drawEllipse(QPointF(-0.6, -0.5), 0.8, 0.6)
            p.restore()
        if self.flag_slot == "ground" and self.flag_ground is not None:
            self._draw_ground_flag(p)
        if not self.skel:
            return
        q, s = self.pose, self.skel
        t, run = self.t, self.run_w
        air = self.jump is not None and self.jump["pre"] <= 0

        gy = self._ground_y()
        lift = max(0.0, gy - self.y)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(70 * (1 - min(1.0, lift / 45)))))
        p.drawEllipse(QPointF(self.x, gy + 0.5), (11 * abs(self.face_vis) + 2) * (1 - 0.35 * min(1.0, lift / 45)), 2.4)

        p.save()
        p.translate(self.x, self.y)
        p.scale(self.face_vis, 1.0)
        sq = q["squash"]
        p.scale(1 + (1 - sq) * 0.6, sq)
        if abs(q["rot"]) > 1e-4:
            p.translate(0, -22)
            p.rotate(math.degrees(q["rot"]))
            p.translate(0, 22)

        hip, shoulder, head, neck = s["hip"], s["shoulder"], s["head"], s["neck"]
        cap = Qt.RoundCap
        far_robe, far_pants, far_skin = shade(robe, 0.7), shade(self.PANTS, 0.7), shade(self.SKIN, 0.82)

        def limb(a: QPointF, b: QPointF, c: QPointF, width: float, color: QColor) -> None:
            p.setPen(QPen(color, width, Qt.SolidLine, cap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF([a, b, c]))

        # szarfa (z tyłu) – łopocze mocniej w biegu i unosi się w locie
        pen = QPen(scarf, 4.0, Qt.SolidLine, cap, Qt.RoundJoin)
        prev = QPointF(neck)
        for i in range(1, 10):
            wave = math.sin(t * 9 - i * 0.8) * (1.0 + i * 0.55) * (0.35 + run)
            rise = -i * (1.0 if air else 0.0)
            cur = QPointF(neck.x() - i * (4.2 + 3.4 * run), neck.y() + wave + rise + i * 0.35)
            pen.setWidthF(max(1.0, 4.2 - i * 0.36))
            p.setPen(pen)
            p.drawLine(QLineF(prev, cur))
            prev = cur

        # sashimono – flaga zatknięta na plecach
        if self.flag_slot == "back":
            self._flag(p, QPointF(hip.x() - 4, hip.y() + 3), PI + q["lean"] - 0.12, -1, t, 2.4 + 2.5 * run,
                       (0, 54), scale=0.85)
        self._scabbard(p, shoulder, hip, scarf, t)

        # tylna noga i ręka
        limb(hip, s["bk"], s["bfoot"], 4.6, far_pants)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#11141f"))
        p.drawEllipse(QPointF(s["bfoot"].x() + 1.4, s["bfoot"].y()), 3.1, 1.8)
        limb(shoulder, s["be"], s["bh"], 3.6, far_robe)
        p.setPen(Qt.NoPen)
        p.setBrush(far_skin)
        p.drawEllipse(s["bh"], 1.9, 1.9)

        # poły szaty i zimowy płaszcz
        tail = QPolygonF([
            QPointF(hip.x() - 3, hip.y() - 3),
            QPointF(hip.x() - 9 - 8 * run, hip.y() + 2 + math.sin(t * 10) * 1.6 * run),
            QPointF(hip.x() - 15 - 11 * run, hip.y() + 9 + math.sin(t * 10 + 1) * 2.2 * run),
            QPointF(hip.x() - 2, hip.y() + 13),
        ])
        p.setBrush(far_robe)
        p.drawPolygon(tail)
        if winter > 0.02:
            flap = math.sin(t * 7) * 2.0 * (0.3 + run)
            cloak = QPolygonF([
                QPointF(shoulder.x() - 5, shoulder.y() + 1), QPointF(shoulder.x() + 3, shoulder.y() + 1),
                QPointF(hip.x() + 4, hip.y() + 8),
                QPointF(hip.x() - 3 - 12 * run, hip.y() + 16 + flap),
                QPointF(hip.x() - 9 - 21 * run, hip.y() + 13 + flap * 1.4),
            ])
            p.setBrush(with_alpha_c(shade(robe, 0.62), winter))
            p.drawPolygon(cloak)
            p.setPen(QPen(with_alpha_c(QColor("#f4f1ea"), winter), 2.4, Qt.SolidLine, cap))
            p.drawLine(QLineF(QPointF(hip.x() - 3 - 12 * run, hip.y() + 16 + flap),
                              QPointF(hip.x() - 9 - 21 * run, hip.y() + 13 + flap * 1.4)))
            p.setPen(Qt.NoPen)

        # tułów (przy siadzie rąbek szaty się skraca, żeby nie wchodził w litery)
        skirt = 14.0 - 0.55 * max(0.0, q["hip_dy"] - 6.0)
        body = QPolygonF([
            QPointF(shoulder.x() - 5, shoulder.y()), QPointF(shoulder.x() + 5, shoulder.y()),
            QPointF(hip.x() + 7, hip.y() + 3), QPointF(hip.x() + 9, hip.y() + skirt),
            QPointF(hip.x() - 9, hip.y() + skirt), QPointF(hip.x() - 7, hip.y() + 3),
        ])
        p.setBrush(robe)
        p.drawPolygon(body)
        p.setBrush(QColor(255, 255, 255, 26))       # połysk na przodzie szaty
        p.drawPolygon(QPolygonF([QPointF(shoulder.x() + 1.5, shoulder.y() + 1), QPointF(shoulder.x() + 5, shoulder.y()),
                                 QPointF(hip.x() + 7, hip.y() + 3), QPointF(hip.x() + 3, hip.y() + 3)]))
        p.setBrush(scarf)
        p.drawRect(QRectF(hip.x() - 7.5, hip.y() + 1.5, 15, 3))
        p.setBrush(shade(robe, 1.25))
        p.drawRect(QRectF(hip.x() - 9, hip.y() + skirt - 1.5, 18, 1.6))
        if self.gourd_slot == "hip":
            self._gourd(p, QPointF(hip.x() + 5.0, hip.y() + 6.5), 0.0, hanging=True)

        if self.fan_w > 0.02 and summer > 0.05:      # wachlarz w tylnej dłoni – przed tułowiem
            self._fan(p, QPointF(s["bh"].x() + 3, s["bh"].y() - 2), t, scarf, summer * self.fan_w)
            p.setPen(Qt.NoPen)
            p.setBrush(far_skin)
            p.drawEllipse(QPointF(s["bh"].x() + 3, s["bh"].y() - 2), 1.9, 1.9)

        if winter > 0.02:
            p.setBrush(with_alpha_c(QColor("#f4f1ea"), winter))
            for dx, dy, r in ((-3.5, 1.0, 3.6), (0.0, 0.2, 3.9), (3.5, 1.0, 3.4)):
                p.drawEllipse(QPointF(neck.x() + dx, neck.y() + dy + 1.5), r, r * 0.8)

        # przednia noga
        limb(hip, s["fk"], s["ffoot"], 4.8, self.PANTS)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#161b2b"))
        p.drawEllipse(QPointF(s["ffoot"].x() + 1.6, s["ffoot"].y()), 3.4, 2.0)

        # przednia ręka z tym, co trzyma
        hand = s["fh"]
        if self.flag_slot == "hand":
            g = clamp01(q["grip"])
            self._flag(p, hand, q["flag"], -1, t, q["amp"] + 3.0 * run, (9 + 15 * g, 41 - 15 * g))
        limb(shoulder, s["fe"], hand, 3.8, robe)
        if self.sword_slot == "hand":
            self._sword(p, hand, q["sword"])
        if self.gourd_slot == "hand":
            self._gourd(p, hand, PI - q["ff"])
        p.setPen(Qt.NoPen)
        p.setBrush(self.SKIN)
        p.drawEllipse(hand, 2.0, 2.0)

        self._head(p, head, q, scarf, winter, summer)
        p.restore()

        if self.trail:
            self._draw_trail(p)
        if self.bubble_a > 0.01:
            self._bubble(p, "Do zobaczenia w grze!", self.bubble_a)

    # ---------------------------------------------------------------- części ciała i rekwizyty
    def _head(self, p: QPainter, head: QPointF, q: dict, scarf: QColor, winter: float, summer: float) -> None:
        t = self.t
        p.save()
        p.translate(head)
        p.rotate(math.degrees((q["lean"] + q["head"]) * 0.75))
        look = max(-1.0, min(1.0, q["look"]))
        p.setPen(Qt.NoPen)
        p.setBrush(self.SKIN)
        p.drawEllipse(QPointF(0, 0), 5.6, 5.8)
        if abs(look) > 0.3:                          # nos podpowiada, w którą stronę patrzy
            p.setBrush(shade(self.SKIN, 0.94))
            p.drawEllipse(QPointF(5.0 * look, 1.4), 1.0, 1.0)
        ex = 2.6 * look
        if q["eyes"] < 0.75 or self.blink_t > 0:
            width = 1.2 if q["eyes"] >= 0.25 else 1.4
            p.setPen(QPen(QColor("#2a2230"), 0.9, Qt.SolidLine, Qt.RoundCap))
            if q["eyes"] < 0.25:                     # zamknięte – medytacja / ziewnięcie
                path = QPainterPath()
                path.moveTo(ex - width, 0.6)
                path.quadTo(ex, 1.6, ex + width, 0.6)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            else:
                p.drawLine(QLineF(ex - width, 0.9, ex + width, 0.9))
        else:
            p.setPen(QPen(QColor("#2a2230"), 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawPoint(QPointF(ex, 0.8))
        p.setPen(Qt.NoPen)
        hat_y = -3.0
        p.setBrush(shade(self.STRAW, 0.82))
        p.drawEllipse(QPointF(0, hat_y + 1.2), 13.5, 3.4)
        cone = QPainterPath()
        cone.moveTo(-11, hat_y + 0.6)
        cone.quadTo(-4, hat_y - 3, 0, hat_y - 11)
        cone.quadTo(4, hat_y - 3, 11, hat_y + 0.6)
        cone.closeSubpath()
        p.setBrush(self.STRAW)
        p.drawPath(cone)
        p.setPen(QPen(shade(self.STRAW, 0.7), 0.9))
        p.drawLine(QLineF(-2, hat_y - 1, -5, hat_y + 0.2))
        p.drawLine(QLineF(2, hat_y - 1, 5, hat_y + 0.2))
        p.setPen(QPen(scarf, 1.1))
        p.drawLine(QLineF(-5, hat_y + 3.0, -5, hat_y + 8.5))     # tasiemka pod brodą
        if winter > 0.02:
            snow = with_alpha_c(QColor("#ffffff"), winter)
            p.setPen(Qt.NoPen)
            p.setBrush(snow)
            capp = QPainterPath()
            capp.moveTo(-4.2, hat_y - 5.2)
            capp.quadTo(0, hat_y - 13.5, 4.2, hat_y - 5.2)
            capp.quadTo(0, hat_y - 3.8, -4.2, hat_y - 5.2)
            p.drawPath(capp)
            p.drawEllipse(QPointF(-9.0, hat_y + 0.6), 2.6, 0.9)
            p.drawEllipse(QPointF(8.0, hat_y + 0.8), 2.0, 0.8)
            cycle = (t % 2.2) / 2.2                  # para z ust w mroźnym powietrzu
            if cycle < 0.55:
                u = cycle / 0.55
                side = 1.0 if look >= 0 else -1.0
                for k in range(3):
                    uk = max(0.0, u - k * 0.15)
                    if uk <= 0:
                        continue
                    p.setBrush(QColor(255, 255, 255, int(150 * winter * (1 - uk))))
                    p.drawEllipse(QPointF(side * (7 + uk * 9 + k * 2), 2 - uk * 5), 1.4 + uk * 2.4, 1.2 + uk * 2.0)
        if summer > 0.05:                            # kwiat za opaską kapelusza
            fc = QPointF(-7.5, hat_y - 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(with_alpha_c(QColor("#ff5d8f"), summer))
            for k in range(5):
                a = k * TAU / 5 + t * 0.4
                p.drawEllipse(QPointF(fc.x() + math.cos(a) * 1.9, fc.y() + math.sin(a) * 1.9), 1.5, 1.5)
            p.setBrush(with_alpha_c(QColor("#ffd84d"), summer))
            p.drawEllipse(fc, 1.1, 1.1)
        p.restore()

    def _scabbard(self, p: QPainter, shoulder: QPointF, hip: QPointF, scarf: QColor, t: float) -> None:
        """Pochwa na plecach zostaje zawsze; rękojeść widać tylko, gdy miecz jest schowany."""
        mouth = QPointF(shoulder.x() - 2.6, shoulder.y() - 3.2)
        end = QPointF(hip.x() + 11, hip.y() + 14)
        p.setPen(QPen(self.LACQUER, 2.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(mouth, end))
        p.setPen(QPen(self.METAL, 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(end, QPointF(end.x() - 1.3, end.y() - 1.6)))
        if self.sword_slot == "back":
            top = QPointF(shoulder.x() - 5.2, shoulder.y() - 8.0)
            p.setPen(QPen(QColor("#3a2a22"), 2.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(mouth, top))
            p.setPen(QPen(self.METAL, 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(QPointF(mouth.x() - 1.6, mouth.y() + 1.0), QPointF(mouth.x() + 1.6, mouth.y() - 1.0)))
            p.setPen(Qt.NoPen)
            p.setBrush(self.METAL)
            p.drawEllipse(top, 1.5, 1.5)
            p.setPen(QPen(scarf, 1.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(top, QPointF(top.x() - 4, top.y() + 5 + math.sin(t * 6) * 1.2)))
        else:
            p.setPen(QPen(self.METAL, 1.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(QPointF(mouth.x() - 1.4, mouth.y() + 0.9), QPointF(mouth.x() + 1.4, mouth.y() - 0.9)))

    def _sword(self, p: QPainter, hand: QPointF, angle: float) -> None:
        d = QPointF(math.sin(angle), math.cos(angle))
        perp = QPointF(-d.y(), d.x())
        tip = QPointF(hand.x() + d.x() * 19, hand.y() + d.y() * 19)
        p.setPen(QPen(QColor("#3a2a22"), 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(hand, QPointF(hand.x() - d.x() * 4.5, hand.y() - d.y() * 4.5)))
        p.setPen(QPen(self.STEEL, 2.0, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(QPointF(hand.x() + d.x() * 2, hand.y() + d.y() * 2), tip))
        p.setPen(QPen(QColor(255, 255, 255, 210), 0.7, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(QPointF(hand.x() + d.x() * 3 + perp.x() * 0.6, hand.y() + d.y() * 3 + perp.y() * 0.6),
                          QPointF(tip.x() + perp.x() * 0.3, tip.y() + perp.y() * 0.3)))
        p.setPen(QPen(self.METAL, 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QLineF(QPointF(hand.x() + perp.x() * 2.2 + d.x() * 1.4, hand.y() + perp.y() * 2.2 + d.y() * 1.4),
                          QPointF(hand.x() - perp.x() * 2.2 + d.x() * 1.4, hand.y() - perp.y() * 2.2 + d.y() * 1.4)))

    def _gourd(self, p: QPainter, c: QPointF, rotation: float, hanging: bool = False) -> None:
        p.save()
        p.translate(c)
        if hanging:
            p.rotate(math.sin(self.t * 3 + 1) * 6 * (0.3 + self.run_w))
        else:
            p.rotate(math.degrees(rotation))
            p.translate(0, -1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(shade(self.GOURD, 0.85))
        p.drawEllipse(QPointF(0, 1.9), 2.5, 2.4)
        p.setBrush(self.GOURD)
        p.drawEllipse(QPointF(0, -1.5), 1.7, 1.6)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(QPointF(-0.8, 1.2), 0.8, 1.0)
        p.setBrush(QColor("#b2302c"))
        p.drawEllipse(QPointF(0, -3.3), 0.8, 0.7)
        p.restore()

    def _draw_trail(self, p: QPainter) -> None:
        """Smuga ostrza z poprzednich klatek – półksiężyc powstaje sam z prawdziwego toru miecza."""
        tr = self.trail
        p.setPen(Qt.NoPen)
        n = len(tr)
        for i in range(1, n):
            a, b = tr[i - 1], tr[i]
            fade = (1 - b[4] / TRAIL_LIFE) * (i / n)
            if fade <= 0.02:
                continue
            poly = QPolygonF([QPointF(a[0], a[1]), QPointF(a[2], a[3]), QPointF(b[2], b[3]), QPointF(b[0], b[1])])
            p.setBrush(QColor(255, 255, 255, int(150 * fade)))
            p.drawPolygon(poly)
            p.setPen(QPen(QColor(220, 235, 255, int(230 * fade)), 1.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QLineF(QPointF(a[2], a[3]), QPointF(b[2], b[3])))
            p.setPen(Qt.NoPen)

    def _draw_ground_flag(self, p: QPainter) -> None:
        g = self.flag_ground
        gx, gy = self._flag_world()
        s = ease_out(g["sink"])
        length = g["L0"] + (g["L1"] - g["L0"]) * s
        scale = g["s0"] + (g["s1"] - g["s0"]) * s
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QPointF(gx, gy + 0.5), 6 * scale, 1.8)
        theta = PI + self.wobble + 0.025 * math.sin(self.t * 1.7)
        self._flag(p, QPointF(gx, gy), theta, g["wind"], self.t, 3.4 if g["big"] else 2.4, (0, length), scale=scale)

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

    def _fan(self, p: QPainter, hand: QPointF, t: float, scarf: QColor, alpha: float) -> None:
        """Składany wachlarz – przy twarzy wachluje szybko, przy biodrze leniwie."""
        p.save()
        p.translate(hand)
        fast = 1.0 if self.act == "fan" else 0.0
        p.rotate(-35 + math.sin(t * (9 + 5 * fast)) * (16 + 10 * fast))
        open_ang = 100.0
        fan = QPainterPath()
        fan.moveTo(0, 0)
        fan.arcTo(QRectF(-13, -13, 26, 26), 90 - open_ang / 2, open_ang)
        fan.closeSubpath()
        p.setPen(QPen(with_alpha_c(QColor("#7a4a26"), alpha), 0.8))
        p.setBrush(with_alpha_c(QColor("#fff3d6"), alpha))
        p.drawPath(fan)
        p.setPen(QPen(with_alpha_c(scarf, alpha), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(-11, -11, 22, 22), int((90 - open_ang / 2) * 16), int(open_ang * 16))
        p.restore()

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
        for upper, lower, colour in ((tops, mids, self.FLAG_WHITE), (mids, bots, self.FLAG_RED)):
            p.setPen(Qt.NoPen)
            p.setBrush(colour)
            p.drawPolygon(QPolygonF(upper + lower[::-1]))
        for i in range(1, cols, 2):                  # delikatne cieniowanie fałd
            p.setBrush(QColor(0, 0, 0, 20))
            p.drawPolygon(QPolygonF([tops[i], tops[i + 1], bots[i + 1], bots[i]]))
        p.setPen(QPen(QColor(70, 0, 18, 110), 0.6))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(tops + bots[::-1] + [tops[0]]))
