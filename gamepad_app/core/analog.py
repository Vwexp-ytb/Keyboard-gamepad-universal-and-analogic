from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalogCalibration:
    """Per-key raw sensor calibration; values may increase or decrease on press."""

    released: int
    pressed: int

    def __post_init__(self) -> None:
        if self.released == self.pressed:
            raise ValueError("released and pressed calibration values must differ")

    def normalize(self, raw: int) -> float:
        ratio = (int(raw) - self.released) / (self.pressed - self.released)
        return max(0.0, min(1.0, ratio))


class AnalogHysteresis:
    """Small stateful threshold filter to prevent noisy repeated press/release edges."""

    def __init__(self, press_threshold: int = 50, release_threshold: int = 45) -> None:
        if not 1 <= release_threshold < press_threshold <= 100:
            raise ValueError("thresholds must satisfy 1 <= release < press <= 100")
        self.press_threshold = press_threshold
        self.release_threshold = release_threshold
        self.pressed = False

    def update(self, depth: int) -> bool:
        depth = max(0, min(100, int(depth)))
        if self.pressed:
            if depth <= self.release_threshold:
                self.pressed = False
        elif depth >= self.press_threshold:
            self.pressed = True
        return self.pressed

    def reset(self) -> None:
        self.pressed = False
