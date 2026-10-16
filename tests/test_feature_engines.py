from __future__ import annotations

import unittest

from gamepad_app.features.dks import DKSEngine
from gamepad_app.features.macros import MacroEngine
from gamepad_app.features.socd import SOCDResolver


class DKSEngineTests(unittest.TestCase):
    def test_press_threshold_tracks_analog_depth(self) -> None:
        engine = DKSEngine({"30": [{"threshold": 50, "action": "RT", "direction": "press"}]})
        self.assertEqual(engine.update({30: 49}), set())
        self.assertEqual(engine.update({30: 50}), {"RT"})
        self.assertEqual(engine.update({30: 100}), {"RT"})
        self.assertEqual(engine.update({30: 0}), set())

    def test_release_threshold_emits_short_action(self) -> None:
        engine = DKSEngine({"30": [{"threshold": 75, "action": "A", "direction": "release"}]})
        self.assertEqual(engine.update({30: 80}), set())
        self.assertEqual(engine.update({30: 70}), {"A"})
        self.assertEqual(engine.update({30: 0}), {"A"})

    def test_invalid_rule_is_ignored(self) -> None:
        engine = DKSEngine({"999": [{"threshold": 20, "action": "A"}],
                            "30": [{"threshold": 0, "action": "B"}]})
        self.assertEqual(engine.update({30: 100}), set())


class SOCDResolverTests(unittest.TestCase):
    def test_last_pressed_direction_wins(self) -> None:
        resolver = SOCDResolver([["LS_LEFT", "LS_RIGHT"]])
        first = {"LS_LEFT": 100, "LS_RIGHT": 0}
        resolver.resolve(first)
        self.assertEqual(first["LS_LEFT"], 100)
        second = {"LS_LEFT": 100, "LS_RIGHT": 100}
        resolver.resolve(second)
        self.assertEqual(second["LS_LEFT"], 0)
        self.assertEqual(second["LS_RIGHT"], 100)

    def test_disabled_conflict_pair_is_unmodified(self) -> None:
        resolver = SOCDResolver([])
        values = {"LS_LEFT": 100, "LS_RIGHT": 100}
        resolver.resolve(values)
        self.assertEqual(values, {"LS_LEFT": 100, "LS_RIGHT": 100})


class MacroEngineTests(unittest.TestCase):
    def test_macro_is_scheduled_on_threshold_crossing(self) -> None:
        engine = MacroEngine([{
            "scan": 30,
            "threshold": 60,
            "steps": [{"action": "A", "duration_ms": 100, "delay_ms": 0}],
        }])
        self.assertEqual(engine.update({30: 50}, now=1.0), set())
        self.assertEqual(engine.update({30: 60}, now=1.0), {"A"})
        self.assertEqual(engine.update({30: 60}, now=1.05), {"A"})
        self.assertEqual(engine.update({30: 0}, now=1.11), set())

    def test_macro_does_not_trigger_without_crossing(self) -> None:
        engine = MacroEngine([{
            "scan": 30,
            "threshold": 60,
            "steps": [{"action": "B", "duration_ms": 50, "delay_ms": 0}],
        }])
        self.assertEqual(engine.update({30: 80}, now=1.0), {"B"})


if __name__ == "__main__":
    unittest.main()
