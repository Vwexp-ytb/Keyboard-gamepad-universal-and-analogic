from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class ProfileManager:
    """Load validated JSON presets and optionally select them by process name."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load_all(self) -> dict[str, dict[str, Any]]:
        profiles: dict[str, dict[str, Any]] = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Le profil doit être un objet JSON.")
                profiles[path.stem] = data
            except (OSError, ValueError, json.JSONDecodeError):
                LOGGER.exception("Profil ignoré: %s", path)
        return profiles

    def matching_profile(self, profile_rules: dict[str, list[str]]) -> str | None:
        """Return first process-matched profile; Windows tasklist is queried sparingly."""
        if not profile_rules:
            return None
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                timeout=1.5, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            running = result.stdout.casefold()
        except (OSError, subprocess.SubprocessError):
            LOGGER.debug("Détection des processus indisponible", exc_info=True)
            return None
        for profile, executables in profile_rules.items():
            if any(Path(name).name.casefold() in running for name in executables if isinstance(name, str)):
                return profile
        return None


class ConfigReloader:
    """Poll a config file timestamp without blocking the gamepad polling thread."""

    def __init__(self, path: Path, callback, interval: float = 1.0) -> None:
        self.path, self.interval, self.callback_fn = path, max(0.25, interval), callback
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="config-reloader", daemon=True)
        self._mtime = self._stat()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _stat(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            mtime = self._stat()
            if mtime is not None and mtime != self._mtime:
                self._mtime = mtime
                try:
                    self.on_change()
                except Exception:
                    LOGGER.exception("Rechargement à chaud de la configuration échoué")

    def on_change(self) -> None:
        """Override callback target to keep invocation off the polling thread."""
        self.callback_fn()


class ProcessProfileWatcher:
    """Monitor configured executable names and notify when a profile matches."""

    def __init__(self, config_path: Path, callback, interval: float = 3.0) -> None:
        self.config_path = config_path
        self.callback = callback
        self.interval = max(1.0, interval)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="profile-autoswitch", daemon=True)
        self._last_profile: str | None = None

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _run(self) -> None:
        from gamepad_app.core.config import load_config

        while not self.stop_event.is_set():
            config = load_config(self.config_path)
            profiles = config.get("profiles", {})
            rules = {name: profile.get("processes", []) for name, profile in profiles.items()
                     if isinstance(profile, dict) and profile.get("processes")}
            selected = ProfileManager(self.config_path.parent / "profiles").matching_profile(rules)
            selected = selected or config.get("active_profile")
            if selected and selected != self._last_profile:
                self._last_profile = selected
                try:
                    self.callback(selected, profiles.get(selected, {}))
                except Exception:
                    LOGGER.exception("Basculement automatique de profil échoué")
            self.stop_event.wait(self.interval)
