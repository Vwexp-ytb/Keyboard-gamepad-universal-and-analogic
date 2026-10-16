from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import threading
import time
from typing import Any


@dataclass(frozen=True)
class LatencySnapshot:
    """Latency distribution in milliseconds for a bounded recent sample window."""

    samples: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


class LatencyMonitor:
    """Low-overhead, bounded latency sampler suitable for runtime diagnostics.

    Call record_ns() with a measured duration in nanoseconds. The monitor does
    not perform I/O, log, or allocate an unbounded history in the polling loop.
    """

    def __init__(self, capacity: int = 4096) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._samples: deque[int] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def record_ns(self, duration_ns: int) -> None:
        value = max(0, int(duration_ns))
        with self._lock:
            self._samples.append(value)

    def measure_start(self) -> int:
        return time.perf_counter_ns()

    def measure_end(self, started_ns: int) -> None:
        self.record_ns(time.perf_counter_ns() - started_ns)

    def snapshot(self) -> LatencySnapshot:
        with self._lock:
            values = sorted(self._samples)
        if not values:
            return LatencySnapshot(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        def percentile(p: float) -> float:
            # Nearest-rank percentile avoids interpolation and remains stable
            # for small sample windows.
            index = max(0, min(len(values) - 1, int((p / 100) * len(values) + 0.999999) - 1))
            return values[index] / 1_000_000

        return LatencySnapshot(
            samples=len(values),
            mean_ms=sum(values) / len(values) / 1_000_000,
            p50_ms=percentile(50),
            p95_ms=percentile(95),
            p99_ms=percentile(99),
            max_ms=values[-1] / 1_000_000,
        )

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


def benchmark_callable(function, iterations: int = 1000) -> dict[str, Any]:
    """Benchmark a pure callable; intended for diagnostics, never auto-run in gameplay."""
    if iterations < 1 or iterations > 10_000_000:
        raise ValueError("iterations must be between 1 and 10,000,000")
    monitor = LatencyMonitor(capacity=min(iterations, 100_000))
    for _ in range(iterations):
        started = time.perf_counter_ns()
        function()
        monitor.record_ns(time.perf_counter_ns() - started)
    result = monitor.snapshot().to_dict()
    result["iterations"] = iterations
    return result
