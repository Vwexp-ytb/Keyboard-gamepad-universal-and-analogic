from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gamepad_app.profiles.manager import ProfileManager


class ProfileManagerTests(unittest.TestCase):
    def test_save_is_loadable_and_preserves_previous_version_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = ProfileManager(Path(temp))
            target = manager.save_profile("FPS", {"version": 1, "bindings": {}})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["version"], 1)
            manager.save_profile("FPS", {"version": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["version"], 2)
            self.assertEqual(json.loads(target.with_suffix(".json.bak").read_text(encoding="utf-8"))["version"], 1)

    def test_invalid_names_and_non_json_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manager = ProfileManager(Path(temp))
            for name in ("../escape", "nested/name", "bad:name", ""):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    manager.save_profile(name, {"version": 1})
            with self.assertRaises(ValueError):
                manager.save_profile("broken", {"value": float("nan")})


if __name__ == "__main__":
    unittest.main()
