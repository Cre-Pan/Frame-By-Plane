# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame By Plane — tutorial motion

A tiny, dependency-free tween clock for the Live Tutorial card.

The card is drawn by a viewport ``POST_PIXEL`` handler, so it only moves when
the viewport is redrawn. :class:`Motion` keeps every running animation in one
place and answers a single question for the operator: "is anything still
moving?". While it is, the operator redraws the viewport at frame rate; as
soon as it is not, the frame timer is removed and an idle card costs nothing.

Two kinds of animation are available:

* **values** (:meth:`Motion.value`) glide towards a target and can be
  retargeted mid-flight: the progress bar, hover highlights, card height;
* **events** (:meth:`Motion.trigger` / :meth:`Motion.phase`) play once from 0
  to 1: the card appearing, a step sliding in, a completed dot popping.
"""

from __future__ import annotations

import math
import time
from typing import Callable

Ease = Callable[[float], float]


def clamp01(value: float) -> float:
    return 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else value


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 * 0.5


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Ease out with a small overshoot: the "pop" of a confirmed step."""
    t = clamp01(t)
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


def bump(t: float) -> float:
    """0 → 1 → 0 over the phase, smooth at both ends."""
    return math.sin(math.pi * clamp01(t))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class Motion:
    """Named tweens and one-shot events sharing one clock."""

    __slots__ = ("clock", "_values", "_events", "_awake_until")

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        # key -> (start value, target, start time, duration, ease)
        self._values: dict[str, tuple[float, float, float, float, Ease]] = {}
        # key -> (start time, duration)
        self._events: dict[str, tuple[float, float]] = {}
        self._awake_until = 0.0

    # -- values ---------------------------------------------------------
    def value(self, key: str, target: float, duration: float, ease: Ease = ease_out_cubic) -> float:
        """Current value of ``key`` gliding towards ``target``.

        The first call snaps to the target so nothing animates on load. A new
        target restarts the glide from wherever the value is right now.
        """
        target = float(target)
        entry = self._values.get(key)
        if entry is None:
            self._values[key] = (target, target, 0.0, 0.0, ease)
            return target
        now = self.clock()
        current = self._sample(entry, now)
        if entry[1] != target:
            if duration <= 0.0:
                self._values[key] = (target, target, 0.0, 0.0, ease)
                return target
            self._values[key] = (current, target, now, duration, ease)
            return current
        return current

    def snap(self, key: str, target: float) -> None:
        self._values[key] = (float(target), float(target), 0.0, 0.0, ease_out_cubic)

    @staticmethod
    def _sample(entry: tuple[float, float, float, float, Ease], now: float) -> float:
        start_value, target, start, duration, ease = entry
        if duration <= 0.0 or now >= start + duration:
            return target
        return lerp(start_value, target, ease((now - start) / duration))

    # -- events ---------------------------------------------------------
    def trigger(self, key: str, duration: float, delay: float = 0.0) -> None:
        self._events[key] = (self.clock() + max(0.0, delay), max(1e-6, duration))

    def phase(self, key: str) -> float | None:
        """Linear 0..1 progress of a running event, ``None`` when idle."""
        entry = self._events.get(key)
        if entry is None:
            return None
        start, duration = entry
        t = (self.clock() - start) / duration
        if t >= 1.0:
            del self._events[key]
            return None
        return max(0.0, t)

    def running(self, key: str) -> bool:
        return self.phase(key) is not None

    def cancel(self, key: str) -> None:
        self._events.pop(key, None)

    # -- frame scheduling -----------------------------------------------
    def wake(self, seconds: float = 0.15) -> None:
        """Keep frames coming briefly so the next draw can start animations."""
        self._awake_until = max(self._awake_until, self.clock() + seconds)

    def busy(self) -> bool:
        now = self.clock()
        if now < self._awake_until:
            return True
        if any(now < start + duration for start, duration in self._events.values()):
            return True
        return any(
            entry[3] > 0.0 and now < entry[2] + entry[3] for entry in self._values.values()
        )
