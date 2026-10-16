from __future__ import annotations

import ctypes
import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from gamepad_app.core.mouse_capture import MouseCapture
from gamepad_app.hid.protocol import (
    HIDReportDescriptor, enable_debug, get_raw_value, open_device, open_generic_device,
    read_report, restore_config,
)
from gamepad_app.hid.providers import AsyncKeyboardProvider, create_provider, discover_providers
from gamepad_app.features.dks import DKSEngine
from gamepad_app.features.socd import SOCDResolver
from gamepad_app.features.macros import MacroEngine
from gamepad_app.core.config import CONFIG_PATH, load_config
from gamepad_app.core.diagnostics import LatencyMonitor
from gamepad_app.profiles.manager import ConfigReloader, ProcessProfileWatcher

LOGGER = logging.getLogger(__name__)
EXIT_SCAN = 88
ESCAPE_SCAN = 1
MOUSE_TOGGLE_SCAN = 67  # F9 toggles mouse input for the right stick.
XUSB_BUTTONS = {
    "A": "XUSB_GAMEPAD_A", "B": "XUSB_GAMEPAD_B", "X": "XUSB_GAMEPAD_X", "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER", "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "L3": "XUSB_GAMEPAD_LEFT_THUMB", "R3": "XUSB_GAMEPAD_RIGHT_THUMB",
    "START": "XUSB_GAMEPAD_START", "BACK": "XUSB_GAMEPAD_BACK", "GUIDE": "XUSB_GAMEPAD_GUIDE",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP", "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT", "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def percent_from_raw(raw: int, limits: list[int] | tuple[int, int], deadzone: int, curve: str,
                     anti_deadzone: int) -> int:
    released, pressed = limits
    span = released - pressed
    if span == 0:
        raise ValueError("Les limites de calibration sont identiques.")
    value = max(0.0, min(1.0, (released - raw) / span))
    if value * 100 < deadzone:
        return 0
    if deadzone < 100:
        value = max(0.0, (value - deadzone / 100) / (1 - deadzone / 100))
    if curve == "exponential":
        value = value * value
    elif curve == "logarithmic":
        value = math.log1p(9 * value) / math.log(10)
    value = (anti_deadzone / 100) + value * (1 - anti_deadzone / 100) if value else 0.0
    return max(0, min(100, round(value * 100)))


def percent_from_analog(value: float, deadzone: int, curve: str, anti_deadzone: int) -> int:
    """Convert an SDK-normalized analog value to the profile's 0..100 range."""
    value = max(0.0, min(1.0, float(value)))
    if value * 100 < deadzone:
        return 0
    if deadzone < 100:
        value = max(0.0, (value - deadzone / 100) / (1 - deadzone / 100))
    if curve == "exponential":
        value *= value
    elif curve == "logarithmic":
        value = math.log1p(9 * value) / math.log(10)
    if value:
        value = anti_deadzone / 100 + value * (1 - anti_deadzone / 100)
    return max(0, min(100, round(value * 100)))


def _axis(pct: int) -> int:
    return max(-32768, min(32767, round(pct * 327.67)))


def _trigger(pct: int) -> int:
    return max(0, min(255, round(pct * 255 / 100)))


def apply_mouse_motion(vals: dict[str, int], dx: float, dy: float, sensitivity: float,
                       sources: dict[str, str], state: dict[str, list[float]] | None = None,
                       dt_ms: float = 8.0, return_ms: float = 100.0,
                       sensitivity_x: float | None = None, sensitivity_y: float | None = None,
                       curve: str = "linear", deadzone: float = 0.0,
                       smoothing_ms: float = 0.0) -> None:
    """Apply relative movement as a rate-normalized stick deflection with smooth return.

    Sensitivity is expressed in percent per mouse count at an 8 ms reference
    interval, so changing the polling interval does not change the feel.
    """
    if state is None:
        state = {}
    dt_ms = max(0.1, float(dt_ms))
    return_ms = max(1.0, float(return_ms))
    for stick, prefix in (("left", "LS"), ("right", "RS")):
        x_key, y_key = f"{prefix}_x", f"{prefix}_y"
        if sources.get(stick) != "mouse":
            state.pop(x_key, None)
            state.pop(y_key, None)
            continue
        x = state.get(x_key, [0.0])[0]
        y = state.get(y_key, [0.0])[0]
        sx = float(sensitivity if sensitivity_x is None else sensitivity_x)
        sy = float(sensitivity if sensitivity_y is None else sensitivity_y)
        tx, ty = dx * sx * 8.0 / dt_ms, dy * sy * 8.0 / dt_ms
        def shape(value: float) -> float:
            magnitude = abs(value)
            if magnitude <= deadzone:
                return 0.0
            magnitude = min(100.0, (magnitude - deadzone) * 100.0 / max(1.0, 100.0 - deadzone))
            normalized = magnitude / 100.0
            if curve == "precision":
                normalized = normalized ** 1.6
            elif curve == "accelerated":
                normalized = math.sqrt(normalized)
            return math.copysign(normalized * 100.0, value)
        tx, ty = shape(tx), shape(ty)
        # A poll's delta represents mouse speed over that interval. Replace the
        # active axis target; only idle axes decay, avoiding displacement buildup.
        # Exponential decay depends on elapsed time, not number of poll cycles.
        decay = math.exp(-dt_ms / return_ms)
        if smoothing_ms > 0 and (dx or dy):
            blend = 1.0 - math.exp(-dt_ms / smoothing_ms)
            x += (tx - x) * blend
            y += (ty - y) * blend
        else:
            x = tx if dx else x * decay
            y = ty if dy else y * decay
        magnitude = math.hypot(x, y)
        if magnitude > 100.0:
            x, y = x * 100.0 / magnitude, y * 100.0 / magnitude
        if abs(x) < 0.5:
            x = 0.0
        if abs(y) < 0.5:
            y = 0.0
        state[x_key], state[y_key] = [x], [y]
        out_x = math.copysign(max(1, round(abs(x))), x) if x else 0
        out_y = math.copysign(max(1, round(abs(y))), y) if y else 0
        out_magnitude = math.hypot(out_x, out_y)
        if out_magnitude > 100:
            out_x, out_y = out_x * 100 / out_magnitude, out_y * 100 / out_magnitude
        vals[f"{prefix}_RIGHT"] = max(0, math.floor(out_x))
        vals[f"{prefix}_LEFT"] = max(0, math.floor(-out_x))
        vals[f"{prefix}_DOWN"] = max(0, math.floor(out_y))
        vals[f"{prefix}_UP"] = max(0, math.floor(-out_y))


class GamepadRuntime:
    def __init__(self, profile: dict[str, Any], scan_to_hid: dict[int, int],
                 status: Callable[[str], None], profile_name: str | None = None) -> None:
        self.profile = profile
        self.profile_name = profile_name
        self._reload_lock = threading.Lock()
        self._pending_profile: dict[str, Any] | None = None
        self.scan_to_hid = scan_to_hid
        self.status = status
        self.stop_event = threading.Event()
        self.latency_monitor = LatencyMonitor(capacity=4096)
        self.thread = threading.Thread(target=self._run, name="gamepad-runtime", daemon=True)
        self.mouse_lock = threading.Lock()
        self.mouse_delta = [0.0, 0.0]
        sources = profile.get("stick_sources", {})
        self._mouse_joystick_enabled = bool(profile.get(
            "mouse_joystick_enabled", isinstance(sources, dict) and sources.get("right") == "mouse"))
        self._mouse_toggle_down = False
        self._mouse_stick_state: dict[str, list[float]] = {}
        self.mouse_capture = MouseCapture()
        self._mouse_module: Any = None
        self._keyboard_module: Any = None
        self._hooks: list[Callable[[], None]] = []

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        self.thread.join(timeout)

    def _run(self) -> None:
        device: Any = None
        original: list[int] | None = None
        changed = False
        generic_descriptor: HIDReportDescriptor | None = None
        gamepad: Any = None
        terminal_status: str | None = None
        config_reloader: ConfigReloader | None = None
        profile_watcher: ProcessProfileWatcher | None = None
        try:
            import hid
            import keyboard
            import vgamepad as vg
            try:
                ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), 2)
            except (AttributeError, OSError):
                LOGGER.warning("Impossible d'élever la priorité du thread de polling.")
            self._keyboard_module = keyboard
            self._mouse_module = self._import_mouse_if_needed()
            try:
                provider_statuses = discover_providers()
            except Exception:
                LOGGER.exception("Détection SDK fabricants échouée; démarrage sans découverte automatique.")
                provider_statuses = []
            detected_sdk_names = [status.provider_id for status in provider_statuses if status.installed]
            for provider_status in provider_statuses:
                LOGGER.info("SDK clavier %s: %s", provider_status.provider_id, provider_status.details)
            self._digital: dict[int, bool] = {}
            config_reloader = ConfigReloader(CONFIG_PATH, self._queue_profile_reload)
            config_reloader.start()
            profile_watcher = ProcessProfileWatcher(CONFIG_PATH, self._queue_process_profile)
            profile_watcher.start()
            dks_engine = DKSEngine(self.profile.get("dks", {}))
            macro_engine = MacroEngine(self.profile.get("macros", []))
            socd_config = self.profile.get("socd", {})
            socd_resolver = SOCDResolver(socd_config.get("pairs", []), socd_config.get("mode", "last_input")) if socd_config.get("mode") in SOCDResolver.MODES else None
            self._install_hooks(keyboard)
            gamepad = vg.VX360Gamepad()
            button_map = {key: getattr(vg.XUSB_BUTTON, val) for key, val in XUSB_BUTTONS.items()}
            self._install_mouse()
            try:
                self.mouse_capture.capture()
                self.status("Mouse captured — press Esc to release it." if self.profile.get("language") == "en"
                            else "Souris capturée — appuie sur Échap pour la libérer.")
            except OSError:
                LOGGER.exception("Impossible de capturer la souris")
            detected_text = (" — logiciels/SDK détectés : " + ", ".join(detected_sdk_names)) if detected_sdk_names else ""
            self.status(("Controller active — F9 toggles the mouse joystick, F12 stops, Esc releases the mouse." +
                         (" — detected vendor software/SDKs: " + ", ".join(detected_sdk_names)
                          if detected_sdk_names else "")
                         if self.profile.get("language") == "en" else
                         "Manette active — F9 active/désactive le joystick souris, F12 arrête, Échap libère la souris." + detected_text))
            kb = self.profile["keyboard"]
            analog_mode = kb.get("mode") in ("ace60", "custom")
            mapped_scans = {int(binding["scan"]) for binding in self.profile["bindings"].values()}
            mapped_scans.update(int(binding["alternate"]["scan"]) for binding in self.profile["bindings"].values()
                                if binding.get("alternate"))
            mapped_scans.update(int(scan) for scan in self.profile.get("dks", {}))
            mapped_scans.update(int(macro["scan"]) for macro in self.profile.get("macros", []))
            analog_scans = {scan for scan in mapped_scans if analog_mode and scan in self.scan_to_hid}
            scan_to_index = {scan: self.scan_to_hid[scan] for scan in analog_scans if scan in self.scan_to_hid}
            index_to_scan = {index: scan for scan, index in scan_to_index.items()}
            latest = {scan: 0 for scan in scan_to_index}
            digital = self._digital
            last_retry = 0.0
            last_presence_check = 0.0
            last_state: tuple[int, ...] | None = None
            last_mouse_update = time.monotonic()
            while not self.stop_event.is_set():
                cycle_started_ns = time.perf_counter_ns()
                with self._reload_lock:
                    pending_profile, self._pending_profile = self._pending_profile, None
                if pending_profile is not None:
                    live_keys = ("deadzone", "button_on", "anti_deadzone", "curve", "poll_interval_ms",
                                 "mouse_sensitivity", "mouse_sensitivity_x", "mouse_sensitivity_y",
                                 "mouse_return_ms", "mouse_aim_curve", "mouse_deadzone", "mouse_smoothing_ms",
                                 "stick_sources", "mouse_joystick_enabled")
                    self.profile.update({key: pending_profile[key] for key in live_keys if key in pending_profile})
                    if "mouse_joystick_enabled" in pending_profile:
                        self._mouse_joystick_enabled = bool(pending_profile["mouse_joystick_enabled"])
                    LOGGER.info("Réglages de profil rechargés à chaud.")
                now = time.monotonic()
                sdk_mode = kb.get("protocol") in ("wooting_sdk", "sdk_provider")
                if device is not None and not sdk_mode and now - last_presence_check >= 1.0:
                    last_presence_check = now
                    try:
                        present = bool(hid.enumerate(int(kb["vid"]), int(kb["pid"])))
                    except (OSError, hid.HIDException):
                        LOGGER.warning("Vérification de présence HID échouée", exc_info=True)
                        present = False
                    if not present:
                        LOGGER.warning("Clavier analogique retiré; reconnexion surveillée.")
                        try:
                            if not sdk_mode:
                                restore_config(device, original, changed)
                        except (OSError, RuntimeError, hid.HIDException):
                            LOGGER.warning("Restauration HID après retrait échouée", exc_info=True)
                        try:
                            device.close()
                        except (OSError, RuntimeError, hid.HIDException):
                            LOGGER.debug("Fermeture après retrait échouée", exc_info=True)
                        device = None
                        original, changed = None, False
                        generic_descriptor = None
                        latest = {scan: 0 for scan in latest}
                        last_retry = now
                if analog_scans and device is None and time.monotonic() - last_retry >= 1.0:
                    last_retry = time.monotonic()
                    candidate: Any = None
                    try:
                        if sdk_mode:
                            provider_id = ("wooting" if kb.get("protocol") == "wooting_sdk"
                                           else str(kb.get("sdk_provider", "wooting")))
                            provider_settings = {
                                "library": str(kb.get("sdk_library", "")),
                                "device_id": kb.get("sdk_device_id"),
                                "keyboard": kb,
                                "profile": self.profile,
                            }
                            if not self.profile.get("sdk_providers", {}).get(provider_id, True):
                                raise RuntimeError(f"Le provider {provider_id} est désactivé dans ce profil.")
                            candidate = AsyncKeyboardProvider(create_provider(provider_id))
                            candidate.initialize(provider_settings)
                            generic_descriptor = None
                        elif kb.get("protocol", "ace60") == "generic":
                            candidate, generic_descriptor = open_generic_device(int(kb["vid"]), int(kb["pid"]))
                        else:
                            candidate = open_device(int(kb["vid"]), int(kb["pid"]))
                            connected_original, connected_changed = enable_debug(candidate)
                            if original is None:
                                original, changed = connected_original, connected_changed
                        device = candidate
                        self.status("Analog keyboard connected." if self.profile.get("language") == "en"
                                    else "Clavier analogique connecté.")
                    except (RuntimeError, OSError, hid.HIDException) as exc:
                        if candidate is not None:
                            try:
                                candidate.close()
                            except (OSError, RuntimeError, hid.HIDException):
                                LOGGER.debug("Fermeture du périphérique refusé échouée", exc_info=True)
                            del candidate
                        LOGGER.info("Clavier analogique indisponible: %s", exc)
                if device is not None:
                    try:
                        if sdk_mode:
                            # SDK full-buffer reads omit idle keys; clear the previous
                            # snapshot before applying this poll to prevent stale values.
                            latest = {scan: 0 for scan in scan_to_index}
                            for usage, value in device.read_keys().items():
                                scan = index_to_scan.get(usage)
                                if scan is not None:
                                    latest[scan] = percent_from_analog(value,
                                        int(self.profile["deadzone"]), str(self.profile["curve"]),
                                        int(self.profile["anti_deadzone"]))
                        else:
                            report = read_report(device, timeout_ms=0)
                            reads = 0
                            while report is not None and reads < 128:
                                raw_values = (generic_descriptor.read_values(report).items()
                                              if generic_descriptor is not None
                                              else (get_raw_value(report),))
                                for index, raw in raw_values:
                                    scan = index_to_scan.get(index)
                                    if scan is not None and raw is not None:
                                        calibration = self.profile.get("calibration", {}).get(str(scan))
                                        if calibration:
                                            latest[scan] = percent_from_raw(raw, calibration,
                                                int(self.profile["deadzone"]), str(self.profile["curve"]),
                                                int(self.profile["anti_deadzone"]))
                                report = read_report(device, timeout_ms=0)
                                reads += 1
                    except (OSError, RuntimeError, hid.HIDException) as exc:
                        LOGGER.warning("Clavier HID déconnecté; reconnexion automatique: %s", exc)
                        try:
                            if not sdk_mode:
                                restore_config(device, original, changed)
                        except (OSError, RuntimeError, hid.HIDException):
                            LOGGER.warning("Restauration HID après déconnexion échouée", exc_info=True)
                        try:
                            device.close()
                        except (OSError, RuntimeError, hid.HIDException):
                            LOGGER.debug("Fermeture du périphérique HID échouée", exc_info=True)
                        device = None
                        original, changed = None, False
                        generic_descriptor = None
                        latest = {scan: 0 for scan in latest}
                vals = {action: 0 for action in XUSB_BUTTONS}
                vals.update({key: 0 for key in ("RT", "LT", "LS_LEFT", "LS_RIGHT", "LS_UP", "LS_DOWN",
                                                "RS_LEFT", "RS_RIGHT", "RS_UP", "RS_DOWN")})
                shift_scan = self.profile.get("shift_scan")
                shift_pressed = bool(digital.get(int(shift_scan), False)) if shift_scan is not None else False
                for action, binding in self.profile["bindings"].items():
                    chosen = binding.get("alternate") if shift_pressed and binding.get("alternate") else binding
                    scan = int(chosen["scan"])
                    if scan in latest:
                        vals[action] = latest[scan]
                    else:
                        vals[action] = 100 if digital.get(scan, False) else 0
                depths = {scan: latest.get(scan, 100 if digital.get(scan, False) else 0)
                          for scan in mapped_scans}
                for action in dks_engine.update(depths):
                    if action in vals:
                        vals[action] = max(vals[action], 100)
                for action in macro_engine.update(depths):
                    if action in vals:
                        vals[action] = max(vals[action], 100)
                with self.mouse_lock:
                    dx, dy = self.mouse_delta
                    self.mouse_delta = [0.0, 0.0]
                sensitivity = float(self.profile["mouse_sensitivity"])
                sources = self.profile.get("stick_sources", {})
                if not sources:
                    # Support direct runtime users that still pass pre-profile configs.
                    sources = {"right": "mouse" if self.profile.get("mouse_x") or self.profile.get("mouse_y") else "keyboard"}
                sources = dict(sources)
                if self._mouse_joystick_enabled:
                    sources["right"] = "mouse"
                elif sources.get("right") == "mouse":
                    sources["right"] = "keyboard"
                mouse_update_time = time.monotonic()
                interval_ms = max(0.1, (mouse_update_time - last_mouse_update) * 1000.0)
                last_mouse_update = mouse_update_time
                apply_mouse_motion(vals, dx, dy, sensitivity, sources, self._mouse_stick_state,
                                   interval_ms, float(self.profile.get("mouse_return_ms", 100)),
                                   float(self.profile.get("mouse_sensitivity_x", sensitivity)),
                                   float(self.profile.get("mouse_sensitivity_y", sensitivity)),
                                   str(self.profile.get("mouse_aim_curve", "linear")),
                                   float(self.profile.get("mouse_deadzone", 0)),
                                   float(self.profile.get("mouse_smoothing_ms", 0)))
                if socd_resolver is not None:
                    socd_resolver.resolve(vals)
                state = tuple(vals.values())
                if state != last_state:
                    self._update_gamepad(gamepad, button_map, vals, int(self.profile["button_on"]))
                    last_state = state
                # Measures processing cost, excluding the configured sleep interval.
                self.latency_monitor.measure_end(cycle_started_ns)
                interval = max(0.001, min(0.020, float(self.profile["poll_interval_ms"]) / 1000.0))
                self.stop_event.wait(interval)
        except ImportError as exc:
            LOGGER.exception("Dépendance runtime indisponible")
            terminal_status = (f"Runtime dependency error: {exc}" if self.profile.get("language") == "en"
                               else f"Dépendance runtime indisponible: {exc}")
        except (RuntimeError, OSError, ValueError, KeyError, TypeError, hid.HIDException) as exc:
            LOGGER.exception("Le runtime manette s'est arrêté sur une erreur")
            terminal_status = (f"Runtime error: {exc}" if self.profile.get("language") == "en"
                               else f"Erreur runtime: {exc}")
        finally:
            if config_reloader is not None:
                config_reloader.stop()
            if profile_watcher is not None:
                profile_watcher.stop()
            for remove in reversed(self._hooks):
                try:
                    remove()
                except (RuntimeError, OSError):
                    LOGGER.warning("Échec de retrait d'un hook", exc_info=True)
            try:
                self.mouse_capture.release()
            except OSError:
                LOGGER.exception("La capture souris n'a pas pu être relâchée proprement")
            if gamepad is not None:
                try:
                    attached = getattr(gamepad, "is_attached", True)
                    attached = attached() if callable(attached) else bool(attached)
                    if attached:
                        gamepad.reset()
                        gamepad.update()
                    else:
                        LOGGER.info("Périphérique ViGEmBus déjà détaché.")
                except (RuntimeError, OSError):
                    LOGGER.exception("Réinitialisation ViGEmBus échouée")
                finally:
                    gamepad = None
            if device is not None:
                try:
                    if kb.get("protocol") not in ("wooting_sdk", "sdk_provider"):
                        restore_config(device, original, changed)
                except (RuntimeError, OSError, hid.HIDException):
                    LOGGER.exception("Restauration de configuration HID échouée")
                try:
                    device.close()
                except (RuntimeError, OSError, hid.HIDException):
                    LOGGER.warning("Fermeture du périphérique HID échouée", exc_info=True)
            self.status(terminal_status or (
                "Controller stopped; keys released." if self.profile.get("language") == "en"
                else "Manette arrêtée; touches libérées."))

    def _queue_profile_reload(self) -> None:
        config = load_config(CONFIG_PATH)
        name = self.profile_name or config.get("active_profile")
        profile = config.get("profiles", {}).get(name)
        if isinstance(profile, dict):
            with self._reload_lock:
                self._pending_profile = profile.copy()

    def _queue_process_profile(self, name: str, profile: dict[str, Any]) -> None:
        if not isinstance(profile, dict):
            return
        # Changing the HID device or hook map mid-session could leave keys captured.
        if profile.get("keyboard") != self.profile.get("keyboard") or profile.get("bindings") != self.profile.get("bindings"):
            LOGGER.info("Profil %s ignoré: périphérique ou assignations différents; arrêt/reprise requis.", name)
            return
        with self._reload_lock:
            self._pending_profile = profile.copy()
            self.profile_name = name

    def _import_mouse_if_needed(self) -> Any:
        try:
            import mouse
        except ImportError as exc:
            raise RuntimeError("Dépendance Python mouse manquante pour la capture souris.") from exc
        return mouse

    def _install_hooks(self, keyboard: Any) -> None:
        scans = {int(b["scan"]) for b in self.profile["bindings"].values()}
        scans.update(int(scan) for scan in self.profile.get("dks", {}))
        scans.update(int(macro["scan"]) for macro in self.profile.get("macros", []))
        for b in self.profile["bindings"].values():
            if b.get("alternate"):
                scans.add(int(b["alternate"]["scan"]))
        shift = self.profile.get("shift_scan")
        if shift is not None:
            scans.add(int(shift))
        scans.difference_update((EXIT_SCAN, ESCAPE_SCAN, MOUSE_TOGGLE_SCAN))
        digital: dict[int, bool] = getattr(self, "_digital", {})
        self._digital = digital
        for scan in scans:
            def callback(event: Any, code: int = scan) -> bool:
                digital[code] = event.event_type == "down"
                return False
            self._hooks.append(keyboard.hook_key(scan, callback, suppress=True))
        def stop_callback(event: Any) -> None:
            if event.event_type == "down":
                self.stop_event.set()
        self._hooks.append(keyboard.hook_key(EXIT_SCAN, stop_callback, suppress=False))
        def toggle_mouse_joystick(event: Any) -> None:
            if event.event_type == "up":
                self._mouse_toggle_down = False
                return
            if event.event_type != "down" or self._mouse_toggle_down:
                return
            self._mouse_toggle_down = True
            self._mouse_joystick_enabled = not self._mouse_joystick_enabled
            enabled = self._mouse_joystick_enabled
            message = (("Mouse joystick enabled." if enabled else "Mouse joystick disabled.")
                       if self.profile.get("language") == "en" else
                       ("Joystick souris activé." if enabled else "Joystick souris désactivé."))
            LOGGER.info(message)
            self.status(message)
        self._hooks.append(keyboard.hook_key(MOUSE_TOGGLE_SCAN, toggle_mouse_joystick, suppress=False))
        def release_mouse(event: Any) -> None:
            if event.event_type == "down":
                self.mouse_capture.release()
                self.status("Mouse released — runtime still active." if self.profile.get("language") == "en"
                            else "Souris libérée — runtime toujours actif.")
        self._hooks.append(keyboard.hook_key(ESCAPE_SCAN, release_mouse, suppress=False))

    def _install_mouse(self) -> None:
        def on_event(event: Any) -> None:
            if getattr(event, "event_type", None) != "move":
                return
            x, y = float(event.x), float(event.y)
            previous = getattr(self, "_last_mouse_position", None)
            self._last_mouse_position = (x, y)
            if previous is not None:
                with self.mouse_lock:
                    self.mouse_delta[0] += x - previous[0]
                    self.mouse_delta[1] += y - previous[1]
        self._mouse_module.hook(on_event)
        self._hooks.append(lambda callback=on_event: self._mouse_module.unhook(callback))

    @staticmethod
    def _update_gamepad(gamepad: Any, button_map: dict[str, Any], vals: dict[str, int], button_on: int) -> None:
        gamepad.right_trigger(value=_trigger(vals["RT"]))
        gamepad.left_trigger(value=_trigger(vals["LT"]))
        gamepad.left_joystick(x_value=_axis(vals["LS_RIGHT"] - vals["LS_LEFT"]),
                              y_value=_axis(vals["LS_UP"] - vals["LS_DOWN"]))
        gamepad.right_joystick(x_value=_axis(vals["RS_RIGHT"] - vals["RS_LEFT"]),
                               y_value=_axis(vals["RS_UP"] - vals["RS_DOWN"]))
        for action, button in button_map.items():
            if vals[action] >= button_on:
                gamepad.press_button(button=button)
            else:
                gamepad.release_button(button=button)
        gamepad.update()
