from __future__ import annotations


class SOCDResolver:
    """Resolve configured opposing pairs using last-input priority."""

    def __init__(self, pairs: list[list[str]] | None = None) -> None:
        self.pairs = tuple(tuple(pair[:2]) for pair in (pairs or []) if len(pair) == 2)
        self._sequence: dict[str, int] = {}
        self._clock = 0
        self._previous: set[str] = set()

    def resolve(self, values: dict[str, int]) -> None:
        pressed = {name for name, value in values.items() if value > 0}
        for name in pressed - self._previous:
            self._clock += 1
            self._sequence[name] = self._clock
        self._previous = pressed
        for pair in self.pairs:
            left, right = pair
            if left in pressed and right in pressed:
                if self._sequence.get(left, 0) > self._sequence.get(right, 0):
                    values[right] = 0
                else:
                    values[left] = 0
