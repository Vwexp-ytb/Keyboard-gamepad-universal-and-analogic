from __future__ import annotations

import json
import logging
import math
import os
import sys
import shutil
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RESOURCE_DIR
LEGACY_CONFIG_PATH = APP_DIR / "gamepad_config.json"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ACE60Gamepad"
CONFIG_PATH = DATA_DIR / "gamepad_config.json"
LOG_PATH = DATA_DIR / "app.log"
LAYOUTS_PATH = RESOURCE_DIR / "config" / "layouts.json"
ACTION_LABELS_PATH = RESOURCE_DIR / "config" / "actions.json"
ACTION_IDS = (
    "RT", "LT", "LS_LEFT", "LS_RIGHT", "LS_UP", "LS_DOWN",
    "RS_LEFT", "RS_RIGHT", "RS_UP", "RS_DOWN", "A", "B", "X", "Y",
    "LB", "RB", "L3", "R3", "START", "BACK", "GUIDE",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)


def default_config() -> dict[str, Any]:
    course = {
        "keyboard": {"mode": None, "vid": 0x41E4, "pid": 0x2103, "protocol": "ace60",
                     "sdk_provider": "wooting", "sdk_library": "", "sdk_device_id": None},
        "sdk_providers": {"wooting": True, "razer_chroma": False,
                          "corsair_icue": False, "logitech_g": False},
        "bindings": {}, "calibration": {}, "shift_scan": None,
        "mouse_joystick_enabled": False,
        "mouse_x": False, "mouse_y": False,
        "stick_sources": {"left": "keyboard", "right": "keyboard"},
        "mouse_sensitivity": 1.0, "mouse_sensitivity_x": 1.0,
        "mouse_sensitivity_y": 1.0, "mouse_return_ms": 100,
        "mouse_aim_curve": "linear", "mouse_deadzone": 0, "mouse_smoothing_ms": 0,
        "deadzone": 4, "button_on": 50, "anti_deadzone": 0,
        "curve": "linear", "poll_interval_ms": 1,
        "dks": {}, "macros": [], "socd": {"mode": "last_input", "pairs": [["LS_LEFT", "LS_RIGHT"]]},
        "processes": [], "layout": "QWERTY ANSI", "language": "fr",
    }
    fps = json.loads(json.dumps(course))
    fps.update(curve="exponential", deadzone=1, button_on=35, poll_interval_ms=1,
               mouse_joystick_enabled=True,
               stick_sources={"left": "keyboard", "right": "mouse"},
               socd={"mode": "last_input", "pairs": [["LS_LEFT", "LS_RIGHT"]]},
               processes=["FortniteClient-Win64-Shipping.exe"])
    racing = json.loads(json.dumps(course))
    racing.update(curve="linear", deadzone=2, poll_interval_ms=2,
                  mouse_aim_curve="precision", mouse_smoothing_ms=12,
                  processes=["acs.exe", "assettocorsa.exe", "acc.exe"])
    adventure = json.loads(json.dumps(course))
    return {
        "version": 2,
        "active_profile": "Aventure / Polyvalent",
        "profiles": {
            "FPS Compétitif": fps,
            "Sim Racing": racing,
            "Aventure / Polyvalent": adventure,
            "Course": json.loads(json.dumps(course)),
        },
    }


def _upgrade(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade the original single-profile JSON format in memory."""
    if isinstance(data.get("profiles"), dict):
        result = default_config()
        result.update({k: v for k, v in data.items() if k != "profiles"})
        result["profiles"] = data["profiles"] or result["profiles"]
        result["active_profile"] = data.get("active_profile", next(iter(result["profiles"])))
    else:
        profile = default_config()["profiles"]["Course"]
        profile["keyboard"] = data.get("keyboard", profile["keyboard"])
        profile["bindings"] = data.get("bindings", {})
        profile["calibration"] = data.get("calibration", {})
        profile["mouse_sensitivity"] = data.get("mouse_sensitivity", profile["mouse_sensitivity"])
        profile["mouse_return_ms"] = data.get("mouse_return_ms", profile["mouse_return_ms"])
        profile["mouse_x"] = data.get("mouse_x", profile["mouse_x"])
        profile["mouse_y"] = data.get("mouse_y", profile["mouse_y"])
        if profile["mouse_x"] or profile["mouse_y"]:
            profile["stick_sources"]["right"] = "mouse"
        result = {"version": 2, "active_profile": "Course", "profiles": {"Course": profile}}
    for name, profile in result["profiles"].items():
        if not isinstance(profile, dict):
            result["profiles"][name] = profile = default_config()["profiles"]["Course"].copy()
        legacy_sensitivity = profile.get("mouse_sensitivity", 1.0)
        profile.setdefault("mouse_sensitivity_x", legacy_sensitivity)
        profile.setdefault("mouse_sensitivity_y", legacy_sensitivity)
        had_stick_sources = isinstance(profile.get("stick_sources"), dict)
        defaults = default_config()["profiles"]["Course"]
        for key, value in defaults.items():
            if key == "mouse_joystick_enabled" and key not in profile:
                # Preserve existing mouse-stick profiles when migrating old configs.
                sources = profile.get("stick_sources", {})
                profile[key] = bool((isinstance(sources, dict) and sources.get("right") == "mouse") or
                                    profile.get("mouse_x") or profile.get("mouse_y"))
                continue
            profile.setdefault(key, value.copy() if isinstance(value, dict) else value)
        sources = profile.get("stick_sources")
        if not isinstance(sources, dict):
            sources = {}
            profile["stick_sources"] = sources
        if not had_stick_sources and (profile.get("mouse_x") or profile.get("mouse_y")):
            sources["right"] = "mouse"
        for stick in ("left", "right"):
            if sources.get(stick) not in ("keyboard", "mouse"):
                sources[stick] = "keyboard"
        keyboard = profile.get("keyboard")
        if not isinstance(keyboard, dict):
            profile["keyboard"] = keyboard = defaults["keyboard"].copy()
        sdk_providers = profile.get("sdk_providers")
        if not isinstance(sdk_providers, dict):
            sdk_providers = {}
        profile["sdk_providers"] = {
            str(provider_id): enabled
            for provider_id, enabled in sdk_providers.items()
            if isinstance(provider_id, str) and provider_id and len(provider_id) <= 80
            and isinstance(enabled, bool)
        }
        for provider_id, enabled in defaults["sdk_providers"].items():
            profile["sdk_providers"].setdefault(provider_id, enabled)
        if keyboard.get("mode") not in (None, "ace60", "standard", "custom"):
            keyboard["mode"] = None
        if keyboard.get("protocol") not in ("ace60", "generic", "wooting_sdk", "sdk_provider"):
            keyboard["protocol"] = "ace60"
        provider_id = keyboard.get("sdk_provider", "wooting")
        keyboard["sdk_provider"] = (str(provider_id)[:80] if isinstance(provider_id, str) and provider_id
                                     else "wooting")
        keyboard["sdk_library"] = str(keyboard.get("sdk_library") or "")
        try:
            sdk_device_id = keyboard.get("sdk_device_id")
            keyboard["sdk_device_id"] = int(sdk_device_id) if sdk_device_id is not None else None
        except (TypeError, ValueError):
            keyboard["sdk_device_id"] = None
        for identity in ("vid", "pid"):
            try:
                value = int(keyboard.get(identity, defaults["keyboard"][identity]))
            except (TypeError, ValueError):
                value = defaults["keyboard"][identity]
            keyboard[identity] = value if 0 <= value <= 0xFFFF else defaults["keyboard"][identity]
        bindings = profile.get("bindings")
        if not isinstance(bindings, dict):
            bindings = {}
        clean_bindings: dict[str, Any] = {}
        for action, binding in bindings.items():
            if action not in ACTION_IDS or not isinstance(binding, dict):
                continue
            try:
                scan = int(binding["scan"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= scan <= 255:
                continue
            clean: dict[str, Any] = {"scan": scan, "name": str(binding.get("name", f"scan {scan}"))}
            alternate = binding.get("alternate")
            if isinstance(alternate, dict):
                try:
                    alternate_scan = int(alternate["scan"])
                except (KeyError, TypeError, ValueError):
                    alternate_scan = -1
                if 0 <= alternate_scan <= 255:
                    clean["alternate"] = {
                        "scan": alternate_scan,
                        "name": str(alternate.get("name", f"scan {alternate_scan}")),
                    }
            clean_bindings[action] = clean
        profile["bindings"] = clean_bindings
        dks = profile.get("dks")
        clean_dks: dict[str, list[dict[str, Any]]] = {}
        if isinstance(dks, dict):
            for raw_scan, entries in dks.items():
                try:
                    scan = int(raw_scan)
                except (TypeError, ValueError):
                    continue
                if not 0 <= scan <= 255 or not isinstance(entries, list):
                    continue
                actions = []
                for entry in entries[:4]:
                    if not isinstance(entry, dict) or entry.get("action") not in ACTION_IDS:
                        continue
                    try:
                        threshold = int(entry.get("threshold", 50))
                    except (TypeError, ValueError):
                        continue
                    direction = entry.get("direction", "press")
                    if 1 <= threshold <= 100 and direction in ("press", "release"):
                        actions.append({"threshold": threshold, "action": entry["action"],
                                        "direction": direction})
                if actions:
                    clean_dks[str(scan)] = actions
        profile["dks"] = clean_dks
        macros = profile.get("macros")
        clean_macros = []
        if isinstance(macros, list):
            for macro in macros[:32]:
                if not isinstance(macro, dict) or not isinstance(macro.get("steps"), list):
                    continue
                try:
                    scan = int(macro["scan"])
                    threshold = int(macro.get("threshold", 50))
                except (KeyError, TypeError, ValueError):
                    continue
                if not 0 <= scan <= 255 or not 1 <= threshold <= 100:
                    continue
                steps = []
                for step in macro["steps"][:16]:
                    if not isinstance(step, dict) or step.get("action") not in ACTION_IDS:
                        continue
                    try:
                        duration = int(step.get("duration_ms", 50))
                        delay = int(step.get("delay_ms", 0))
                    except (TypeError, ValueError):
                        continue
                    if 1 <= duration <= 5000 and 0 <= delay <= 5000:
                        steps.append({"action": step["action"], "duration_ms": duration, "delay_ms": delay})
                if steps:
                    clean_macros.append({"scan": scan, "threshold": threshold, "steps": steps})
        profile["macros"] = clean_macros
        socd = profile.get("socd")
        pairs = socd.get("pairs", []) if isinstance(socd, dict) else []
        clean_pairs = [[a, b] for pair in pairs if isinstance(pair, list) and len(pair) == 2
                       for a, b in [pair] if a in ACTION_IDS and b in ACTION_IDS and a != b][:8]
        profile["socd"] = {"mode": socd.get("mode", "off") if isinstance(socd, dict) and
                            socd.get("mode") in ("off", "last_input", "first_input", "neutral", "up_priority")
                            else "off", "pairs": clean_pairs}
        processes = profile.get("processes", [])
        profile["processes"] = [str(name)[:128] for name in processes[:20]
                                 if isinstance(name, str) and name.lower().endswith(".exe")]
        calibration = profile.get("calibration")
        if not isinstance(calibration, dict):
            calibration = {}
        clean_calibration: dict[str, list[int]] = {}
        for scan, limits in calibration.items():
            try:
                released, pressed = (int(value) for value in limits)
            except (TypeError, ValueError):
                continue
            if 0 <= pressed <= 0xFFFF and 0 <= released <= 0xFFFF and released != pressed:
                clean_calibration[str(scan)] = [released, pressed]
        profile["calibration"] = clean_calibration
        if profile.get("layout") not in ("QWERTY ANSI", "QWERTY ISO", "AZERTY ANSI", "AZERTY ISO"):
            profile["layout"] = defaults["layout"]
        if profile.get("language") not in ("fr", "en"):
            profile["language"] = defaults["language"]
        if profile.get("curve") not in ("linear", "exponential", "logarithmic"):
            profile["curve"] = defaults["curve"]
        if profile.get("mouse_aim_curve") not in ("linear", "precision", "accelerated"):
            profile["mouse_aim_curve"] = defaults["mouse_aim_curve"]
        profile["mouse_x"] = bool(profile.get("mouse_x"))
        profile["mouse_y"] = bool(profile.get("mouse_y"))
        for key, low, high in (("deadzone", 0, 50), ("button_on", 1, 100),
                               ("anti_deadzone", 0, 50), ("poll_interval_ms", 1, 20),
                               ("mouse_return_ms", 20, 1000), ("mouse_deadzone", 0, 50),
                               ("mouse_smoothing_ms", 0, 200)):
            try:
                value = int(profile[key])
            except (TypeError, ValueError):
                value = defaults[key]
            profile[key] = value if low <= value <= high else defaults[key]
        try:
            sensitivity = float(profile["mouse_sensitivity"])
        except (TypeError, ValueError):
            sensitivity = defaults["mouse_sensitivity"]
        profile["mouse_sensitivity"] = (sensitivity if math.isfinite(sensitivity) and 0.1 <= sensitivity <= 20.0
                                         else defaults["mouse_sensitivity"])
        for axis in ("x", "y"):
            key = f"mouse_sensitivity_{axis}"
            try:
                axis_sensitivity = float(profile[key])
            except (TypeError, ValueError):
                axis_sensitivity = profile["mouse_sensitivity"]
            profile[key] = (axis_sensitivity if math.isfinite(axis_sensitivity) and
                            0.1 <= axis_sensitivity <= 20.0 else profile["mouse_sensitivity"])
        shift_scan = profile.get("shift_scan")
        try:
            shift_scan = int(shift_scan) if shift_scan is not None else None
        except (TypeError, ValueError):
            shift_scan = None
        profile["shift_scan"] = shift_scan if shift_scan is None or 0 <= shift_scan <= 255 else None
    if result["active_profile"] not in result["profiles"]:
        result["active_profile"] = next(iter(result["profiles"]))
    result["version"] = 3
    return result


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        if path == CONFIG_PATH and not path.exists() and LEGACY_CONFIG_PATH.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LEGACY_CONFIG_PATH, path)
        with path.open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
        if not isinstance(raw, dict):
            raise ValueError("La racine de configuration doit être un objet JSON.")
        return _upgrade(raw)
    except FileNotFoundError:
        return default_config()
    except (OSError, ValueError, TypeError) as exc:
        LOGGER.exception("Configuration illisible; utilisation des valeurs par défaut: %s", exc)
        if path.exists():
            try:
                backup = path.with_suffix(path.suffix + ".corrupt")
                if not backup.exists():
                    shutil.copy2(path, backup)
            except OSError:
                LOGGER.warning("Impossible de sauvegarder la configuration illisible.", exc_info=True)
        return default_config()


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except OSError:
        LOGGER.exception("Échec de sauvegarde de %s", path)
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Impossible de supprimer le fichier temporaire %s", temp)
        raise


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} doit contenir un objet JSON.")
    return value
