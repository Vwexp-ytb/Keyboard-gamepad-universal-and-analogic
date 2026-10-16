from __future__ import annotations

import unittest

from gamepad_app.core.analog import AnalogCalibration, AnalogHysteresis
from gamepad_app.core.diagnostics import LatencyMonitor, benchmark_callable
from gamepad_app.features.socd import SOCDResolver


class AnalogCalibrationTests(unittest.TestCase):
    def test_normalizes_both_sensor_directions(self) -> None:
        descending = AnalogCalibration(released=1000, pressed=100)
        self.assertEqual(descending.normalize(1000), 0.0)
        self.assertEqual(descending.normalize(550), 0.5)
        self.assertEqual(descending.normalize(100), 1.0)
        ascending = AnalogCalibration(released=0, pressed=200)
        self.assertEqual(ascending.normalize(100), 0.5)

    def test_clamps_out_of_range_and_rejects_degenerate_calibration(self) -> None:
        calibration = AnalogCalibration(100, 0)
        self.assertEqual(calibration.normalize(500), 0.0)
        self.assertEqual(calibration.normalize(-100), 1.0)
        with self.assertRaises(ValueError):
            AnalogCalibration(42, 42)

    def test_hysteresis_prevents_threshold_chatter(self) -> None:
        filter_ = AnalogHysteresis(press_threshold=60, release_threshold=45)
        self.assertFalse(filter_.update(59))
        self.assertTrue(filter_.update(60))
        self.assertTrue(filter_.update(50))
        self.assertFalse(filter_.update(45))


class LatencyMonitorTests(unittest.TestCase):
    def test_snapshot_reports_distribution_and_bounded_window(self) -> None:
        monitor = LatencyMonitor(capacity=3)
        for duration in (1_000_000, 2_000_000, 3_000_000, 4_000_000):
            monitor.record_ns(duration)
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot.samples, 3)
        self.assertEqual(snapshot.p50_ms, 3.0)
        self.assertEqual(snapshot.p95_ms, 4.0)
        self.assertEqual(snapshot.max_ms, 4.0)

    def test_empty_snapshot_and_benchmark_validation(self) -> None:
        self.assertEqual(LatencyMonitor().snapshot().samples, 0)
        with self.assertRaises(ValueError):
            benchmark_callable(lambda: None, iterations=0)
        self.assertEqual(benchmark_callable(lambda: None, iterations=3)["iterations"], 3)


class AdditionalSOCDTests(unittest.TestCase):
    def test_neutral_mode_clears_both_directions(self) -> None:
        values = {"LS_LEFT": 100, "LS_RIGHT": 70}
        SOCDResolver([["LS_LEFT", "LS_RIGHT"]], mode="neutral").resolve(values)
        self.assertEqual(values, {"LS_LEFT": 0, "LS_RIGHT": 0})

    def test_first_input_mode_preserves_first_direction(self) -> None:
        resolver = SOCDResolver([["LS_LEFT", "LS_RIGHT"]], mode="first_input")
        resolver.resolve({"LS_LEFT": 100, "LS_RIGHT": 0})
        values = {"LS_LEFT": 100, "LS_RIGHT": 100}
        resolver.resolve(values)
        self.assertEqual(values["LS_LEFT"], 100)
        self.assertEqual(values["LS_RIGHT"], 0)

    def test_up_priority_is_only_applied_to_vertical_pair(self) -> None:
        resolver = SOCDResolver([["LS_UP", "LS_DOWN"], ["LS_LEFT", "LS_RIGHT"]], mode="up_priority")
        values = {"LS_UP": 100, "LS_DOWN": 100, "LS_LEFT": 100, "LS_RIGHT": 100}
        resolver.resolve(values)
        self.assertEqual(values["LS_UP"], 100)
        self.assertEqual(values["LS_DOWN"], 0)
        self.assertEqual(values["LS_LEFT"], 0)
        self.assertEqual(values["LS_RIGHT"], 0)


if __name__ == "__main__":
    unittest.main()
