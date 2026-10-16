from __future__ import annotations

import time
from typing import Any


class MacroEngine:
    """Schedule bounded, sequential controller-action macros on depth crossings."""

    def __init__(self, definitions: list[dict[str, Any]] | None = None) -> None:
        self.definitions = definitions or []
        self.previous: dict[int, int] = {}
        self.events: list[tuple[float, float, str]] = []

    def update(self, depths: dict[int, int], now: float | None = None) -> set[str]:
        now = time.monotonic() if now is None else now
        active: set[str] = set()
        for macro in self.definitions:
            scan, threshold = macro["scan"], macro["threshold"]
            depth = depths.get(scan, 0)
            if self.previous.get(scan, 0) < threshold <= depth:
                cursor = now
                for step in macro["steps"]:
                    cursor += step["delay_ms"] / 1000
                    end = cursor + step["duration_ms"] / 1000
                    self.events.append((cursor, end, step["action"]))
                    cursor = end
        for macro in self.definitions:
            self.previous[macro["scan"]] = depths.get(macro["scan"], 0)
        self.events = [event for event in self.events if event[1] > now]
        active.update(action for start, end, action in self.events if start <= now < end)
        return active
