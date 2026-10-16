from __future__ import annotations

from collections.abc import Iterable


class SOCDResolver:
    """Resolve opposing digital/analog inputs with deterministic SOCD policies.

    Supported modes: last_input, first_input, neutral, and up_priority.
    Values are modified in place to avoid allocating in the polling loop.
    """

    MODES = frozenset({"last_input", "first_input", "neutral", "up_priority"})

    def __init__(self, pairs: Iterable[Iterable[str]] | None = None, mode: str = "last_input") -> None:
        normalized: list[tuple[str, str]] = []
        for pair in pairs or ():
            values = tuple(pair)
            if len(values) == 2 and values[0] != values[1]:
                normalized.append((str(values[0]), str(values[1])))
        self.pairs = tuple(normalized)
        self.mode = mode if mode in self.MODES else "last_input"
        self._sequence: dict[str, int] = {}
        self._clock = 0
        self._previous: set[str] = set()

    def reset(self) -> None:
        """Clear edge history when profiles or devices change."""
        self._sequence.clear()
        self._clock = 0
        self._previous.clear()

    def resolve(self, values: dict[str, int]) -> None:
        pressed = {name for name, value in values.items() if value > 0}
        for name in pressed - self._previous:
            self._clock += 1
            self._sequence[name] = self._clock
        self._previous = pressed
        for pair in self.pairs:
            left, right = pair
            if left not in pressed or right not in pressed:
                continue
            if self.mode == "neutral":
                values[left] = values[right] = 0
            elif self.mode == "up_priority":
                # Up wins only for the conventional vertical pair; all other
                # pairs use neutral to avoid guessing a directional policy.
                if "UP" in left:
                    values[right] = 0
                elif "UP" in right:
                    values[left] = 0
                else:
                    values[left] = values[right] = 0
            elif self.mode == "first_input":
                if self._sequence.get(left, 0) <= self._sequence.get(right, 0):
                    values[right] = 0
                else:
                    values[left] = 0
            elif self._sequence.get(left, 0) > self._sequence.get(right, 0):
                values[right] = 0
            else:
                values[left] = 0
