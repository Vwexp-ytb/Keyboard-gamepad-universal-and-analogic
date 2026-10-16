from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class DKSAction:
    """A depth crossing mapped to a controller action."""

    threshold: int
    action: str
    direction: str = "press"


class DKSEngine:
    """Evaluate up to four configurable press/release depth crossings per key."""

    def __init__(self, definitions: dict[str, Any] | None = None) -> None:
        self._rules: dict[int, tuple[DKSAction, ...]] = {}
        self._depths: dict[int, int] = {}
        self._active: set[str] = set()
        self._release_deadlines: dict[tuple[int, str], float] = {}
        self.configure(definitions or {})

    def configure(self, definitions: dict[str, Any]) -> None:
        rules: dict[int, tuple[DKSAction, ...]] = {}
        for raw_scan, entries in definitions.items():
            scan = int(raw_scan)
            if not 0 <= scan <= 255 or not isinstance(entries, list) or len(entries) > 4:
                continue
            cleaned = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    threshold = int(entry.get("threshold", 50))
                    action = str(entry["action"])
                except (KeyError, TypeError, ValueError):
                    continue
                direction = str(entry.get("direction", "press"))
                if 1 <= threshold <= 100 and action and len(action) <= 32 and direction in ("press", "release"):
                    cleaned.append(DKSAction(threshold, action, direction))
            if cleaned:
                rules[scan] = tuple(cleaned)
        self._rules = rules
        self._depths.clear()
        self._active.clear()
        self._release_deadlines.clear()

    def update(self, depths: dict[int, int]) -> set[str]:
        """Return actions held by configured thresholds, supporting keyboard and analog depth."""
        active: set[str] = set()
        now = time.monotonic()
        for scan, rules in self._rules.items():
            depth = max(0, min(100, int(depths.get(scan, 0))))
            previous = self._depths.get(scan, 0)
            self._depths[scan] = depth
            for rule in rules:
                if rule.direction == "press" and depth >= rule.threshold:
                    active.add(rule.action)
                elif (rule.direction == "release" and previous >= rule.threshold > depth):
                    self._release_deadlines[(scan, rule.action)] = now + 0.05
                if rule.direction == "release" and now < self._release_deadlines.get((scan, rule.action), 0):
                    active.add(rule.action)
        self._active = active
        return set(active)
