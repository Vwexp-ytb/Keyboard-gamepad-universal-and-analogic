from __future__ import annotations

import copy
import json
import logging
import queue
import threading
import time
from typing import Any

from gamepad_app.core.config import ACTION_LABELS_PATH, LAYOUTS_PATH, RESOURCE_DIR, load_json, save_config
from gamepad_app.core.runtime import ESCAPE_SCAN, EXIT_SCAN, MOUSE_TOGGLE_SCAN, GamepadRuntime, is_admin
from gamepad_app.hid.protocol import (
    DEFAULT_PID, DEFAULT_VID, HIDReportDescriptor, enable_debug, get_raw_value,
    open_device, open_generic_device, read_report, restore_config,
)

LOGGER = logging.getLogger(__name__)
CAPTURE_TIMEOUT_SECONDS = 30.0
CALIBRATION_TIMEOUT_SECONDS = 30.0
CALIBRATION_STABLE_SECONDS = 1.2
CALIBRATION_MOVEMENT_THRESHOLD = 8
CALIBRATION_MINIMUM_SPAN = 100
COURSE_BINDINGS = {
    "RT": (17, "W"), "LT": (31, "S"),
    "LS_LEFT": (30, "A"), "LS_RIGHT": (32, "D"),
}
FPS_BINDINGS = {
    "LS_UP": (17, "W"), "LS_DOWN": (31, "S"),
    "LS_LEFT": (30, "A"), "LS_RIGHT": (32, "D"),
    "RS_LEFT": (0, "Mouse X"), "RS_RIGHT": (0, "Mouse X"),
    "RS_UP": (0, "Mouse Y"), "RS_DOWN": (0, "Mouse Y"),
}


class TerminalApp:
    """Terminal interface for configuring and running the virtual gamepad."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.profile_name = str(config["active_profile"])
        self.actions = load_json(ACTION_LABELS_PATH)["sections"]
        self.layouts: dict[str, dict[str, Any]] = load_json(LAYOUTS_PATH)
        self.strings: dict[str, Any] = {}
        self._load_strings()

    @property
    def profile(self) -> dict[str, Any]:
        return self.config["profiles"][self.profile_name]

    @property
    def language(self) -> str:
        return str(self.profile.get("language", "fr"))

    def _load_strings(self) -> None:
        path = RESOURCE_DIR / "locales" / f"terminal_{self.language}.json"
        with path.open("r", encoding="utf-8") as stream:
            self.strings = json.load(stream)

    def t(self, key: str, **values: Any) -> str:
        return str(self.strings[key]).format(**values)

    def run(self) -> None:
        if not is_admin():
            print(self.t("admin_warning"))
        if self.profile["keyboard"].get("mode") is None:
            print(self.t("first_use"))
            self.select_keyboard()
            if self.profile["keyboard"].get("mode") is not None:
                self.configure_bindings()
        while True:
            self._load_strings()
            print(f"\n=== {self.t('title')} ===")
            print(self.t("menu_summary", keyboard=self.keyboard_label(), profile=self.profile_name,
                         bindings=len(self.profile["bindings"])))
            options = ("keyboard", "bindings", "run", "show", "profiles", "settings", "calibrate", "preset", "language", "quit")
            for index, key in enumerate(options, 1):
                print(f"  {index}) {self.t('menu_' + key)}")
            choice = input(self.t("menu_prompt")).strip()
            try:
                if choice == "1":
                    self.select_keyboard()
                elif choice == "2":
                    self.configure_bindings()
                elif choice == "3":
                    self.run_gamepad()
                elif choice == "4":
                    self.show_config()
                elif choice == "5":
                    self.manage_profiles()
                elif choice == "6":
                    self.configure_settings()
                elif choice == "7":
                    self.calibrate()
                elif choice == "8":
                    self.choose_preset()
                elif choice == "9":
                    self.change_language()
                elif choice == "10":
                    self.save()
                    return
                else:
                    print(self.t("invalid_choice"))
            except KeyboardInterrupt:
                self.save()
                print("\n" + self.t("menu_interrupted"))
                return
            except (ValueError, RuntimeError, OSError) as exc:
                LOGGER.exception("Action du menu terminal échouée")
                print(self.t("operation_failed", error=exc))

    def keyboard_label(self) -> str:
        keyboard = self.profile["keyboard"]
        mode = keyboard.get("mode")
        if mode == "ace60":
            return self.t("device_ace60")
        if mode == "standard":
            return self.t("device_standard")
        if mode == "custom":
            return self.t("device_custom_label", vid=int(keyboard["vid"]), pid=int(keyboard["pid"]))
        return self.t("device_none")

    def select_keyboard(self) -> None:
        keyboard = self.profile["keyboard"]
        before = (keyboard.get("mode"), keyboard.get("vid"), keyboard.get("pid"), keyboard.get("protocol"))
        print("\n" + self.t("keyboard_menu", current=self.keyboard_label()))
        print("  1) " + self.t("device_ace60"))
        print("  2) " + self.t("device_standard"))
        print("  3) " + self.t("device_custom"))
        choice = input(self.t("keyboard_prompt")).strip()
        if choice == "1":
            keyboard.update(mode="ace60", vid=DEFAULT_VID, pid=DEFAULT_PID)
        elif choice == "2":
            keyboard.update(mode="standard")
        elif choice == "3":
            self._list_hid_devices()
            try:
                vid = int(input(self.t("vid_prompt")).strip(), 16)
                pid = int(input(self.t("pid_prompt")).strip(), 16)
                if not 0 <= vid <= 0xFFFF or not 0 <= pid <= 0xFFFF:
                    raise ValueError
            except ValueError:
                print(self.t("invalid_vid_pid"))
                return
            protocol_choice = input(self.t("protocol_prompt")).strip()
            if protocol_choice not in ("1", "2", "3", ""):
                print(self.t("invalid_choice"))
                return
            if protocol_choice == "3":
                library = input("Chemin vers la DLL Wooting Analog SDK : ").strip().strip('"')
                try:
                    from gamepad_app.hid.wooting_sdk import WootingAnalogSDK
                    devices = WootingAnalogSDK.list_devices(library)
                except (OSError, RuntimeError) as exc:
                    print(f"SDK analogique indisponible : {exc}")
                    return
                if not devices:
                    print("Aucun clavier analogique exposé par le SDK ou ses plugins.")
                    return
                for index, device in enumerate(devices, 1):
                    print(f"  {index}) {device['manufacturer']} {device['name']} "
                          f"({device['vendor_id']:04X}:{device['product_id']:04X})")
                try:
                    sdk_device = devices[int(input("Clavier [1] : ").strip() or "1") - 1]
                except (ValueError, IndexError):
                    print(self.t("invalid_choice"))
                    return
                keyboard.update(mode="custom", vid=sdk_device["vendor_id"], pid=sdk_device["product_id"],
                                protocol="wooting_sdk", sdk_provider="wooting", sdk_library=library,
                                sdk_device_id=sdk_device["device_id"])
            else:
                protocol = "ace60" if protocol_choice == "1" else "generic"
                keyboard.update(mode="custom", vid=vid, pid=pid, protocol=protocol)
        elif choice:
            print(self.t("invalid_choice"))
            return
        after = (keyboard.get("mode"), keyboard.get("vid"), keyboard.get("pid"), keyboard.get("protocol"))
        if before != after:
            self.profile["calibration"] = {}
        self.save()
        print(self.t("keyboard_selected", keyboard=self.keyboard_label()))

    def _list_hid_devices(self) -> None:
        try:
            import hid
        except ImportError:
            print(self.t("hid_module_missing"))
            return
        print(self.t("hid_devices"))
        found: set[tuple[int, int]] = set()
        for item in hid.enumerate():
            identity = (int(item["vendor_id"]), int(item["product_id"]))
            if identity in found:
                continue
            found.add(identity)
            name = f"{item.get('manufacturer_string') or ''} {item.get('product_string') or ''}".strip()
            print(self.t("hid_device", vid=identity[0], pid=identity[1], name=name))

    def _capture_key(self, prompt: str) -> tuple[int, str] | None:
        import keyboard

        events: queue.Queue[Any] = queue.Queue()
        remover = keyboard.hook(events.put, suppress=False)
        deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
        try:
            print(prompt, end="", flush=True)
            selected: Any = None
            while selected is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self.t("capture_timeout"))
                try:
                    event = events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError(self.t("capture_timeout")) from exc
                if event.event_type != "down":
                    continue
                if int(event.scan_code) == ESCAPE_SCAN:
                    return None
                if int(event.scan_code) in (EXIT_SCAN, MOUSE_TOGGLE_SCAN):
                    print(self.t("reserved_shortcut"))
                    continue
                selected = event
            scan = int(selected.scan_code)
            name = str(selected.name or f"scan {scan}")
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(self.t("capture_timeout"))
                try:
                    event = events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError(self.t("capture_timeout")) from exc
                if event.event_type == "up" and int(event.scan_code) == scan:
                    return scan, name
        finally:
            remover()

    def configure_bindings(self) -> None:
        if self.profile["keyboard"].get("mode") is None:
            print(self.t("choose_keyboard_first"))
            self.select_keyboard()
            if self.profile["keyboard"].get("mode") is None:
                return
        if self._yes("load_course_preset", default=False):
            self._apply_preset(COURSE_BINDINGS)
        print("\n" + self.t("mapping_instructions"))
        for section in self.actions:
            print(f"\n--- {section['fr' if self.language == 'fr' else 'en']} ---")
            if not self._yes("configure_section", default=True):
                continue
            for action, fr, en in section["actions"]:
                label = fr if self.language == "fr" else en
                binding = self.profile["bindings"].get(action, {})
                current = str(binding.get("name", self.t("none")))
                captured = self._capture_key(self.t("capture_action", label=label, current=current))
                if captured is None:
                    self.profile["bindings"].pop(action, None)
                    print(self.t("binding_cleared"))
                    continue
                scan, name = captured
                new_binding: dict[str, Any] = {"scan": scan, "name": name}
                if binding.get("alternate"):
                    new_binding["alternate"] = binding["alternate"]
                self.profile["bindings"][action] = new_binding
                print(self.t("binding_saved", name=name, kind=self._key_kind(scan)))
                if self._yes("configure_alternate", default=bool(new_binding.get("alternate"))):
                    alternate = self._capture_key(self.t("capture_alternate", label=label))
                    if alternate is None:
                        new_binding.pop("alternate", None)
                    else:
                        alt_scan, alt_name = alternate
                        new_binding["alternate"] = {"scan": alt_scan, "name": alt_name}
                        print(self.t("alternate_saved", name=alt_name))
                self.profile["bindings"][action] = new_binding
        if self._yes("configure_shift", default=self.profile.get("shift_scan") is not None):
            shift = self._capture_key(self.t("capture_shift"))
            self.profile["shift_scan"] = shift[0] if shift else None
            if shift:
                print(self.t("shift_saved", name=shift[1]))
        mapped_scans = {int(binding["scan"]) for binding in self.profile["bindings"].values()}
        mapped_scans.update(int(binding["alternate"]["scan"]) for binding in self.profile["bindings"].values()
                            if binding.get("alternate"))
        self.profile["calibration"] = {key: value for key, value in self.profile["calibration"].items()
                                        if int(key) in mapped_scans}
        if self._yes("configure_stick_sources", default=False):
            for stick, label_key in (("left", "setting_stick_left"), ("right", "setting_stick_right")):
                print(self.t(label_key))
                for index, source in enumerate(("keyboard", "mouse"), 1):
                    print(f"  {index}) {self.t('source_' + source)}")
                try:
                    choice = int(input(self.t("source_prompt")))
                    self.profile["stick_sources"][stick] = ("keyboard", "mouse")[choice - 1]
                    if stick == "right":
                        self.profile["mouse_joystick_enabled"] = self.profile["stick_sources"][stick] == "mouse"
                except (ValueError, IndexError):
                    print(self.t("invalid_choice"))
            if "mouse" in self.profile["stick_sources"].values():
                try:
                    sensitivity = float(input(self.t("sensitivity_prompt")).replace(",", "."))
                    if not 0.1 <= sensitivity <= 20.0:
                        raise ValueError
                    self.profile["mouse_sensitivity"] = sensitivity
                except ValueError:
                    print(self.t("invalid_sensitivity"))
        self.save()

    def _key_kind(self, scan: int) -> str:
        mode = self.profile["keyboard"].get("mode")
        mapping = self.layouts.get(self.profile.get("layout", "QWERTY ANSI"), {}).get("scan_to_hid", {})
        analog = mode in ("ace60", "custom") and str(scan) in mapping
        return self.t("analog_key" if analog else "digital_key")

    def _yes(self, key: str, default: bool = False, **values: Any) -> bool:
        suffix = self.t("yes_no_default") if default else self.t("no_yes_default")
        answer = input(self.t(key, **values) + " " + suffix + " ").strip().lower()
        if not answer:
            return default
        return answer.startswith(("o", "y"))

    def _apply_preset(self, bindings: dict[str, tuple[int, str]]) -> None:
        self.profile["bindings"].clear()
        for action, (scan, name) in bindings.items():
            if scan == 0:
                continue
            self.profile["bindings"][action] = {"scan": scan, "name": name}
        mouse_enabled = bindings is FPS_BINDINGS
        self.profile["mouse_x"] = mouse_enabled
        self.profile["mouse_y"] = mouse_enabled
        self.profile.setdefault("stick_sources", {"left": "keyboard", "right": "keyboard"})
        self.profile["stick_sources"]["left"] = "keyboard"
        self.profile["stick_sources"]["right"] = "mouse" if mouse_enabled else "keyboard"
        self.profile["mouse_joystick_enabled"] = mouse_enabled
        self.save()

    def choose_preset(self) -> None:
        print("  1) " + self.t("preset_course"))
        print("  2) " + self.t("preset_fps"))
        choice = input(self.t("preset_prompt")).strip()
        if choice == "1":
            self._apply_preset(COURSE_BINDINGS)
        elif choice == "2":
            self._apply_preset(FPS_BINDINGS)
        else:
            print(self.t("invalid_choice"))
            return
        print(self.t("preset_loaded"))

    def show_config(self) -> None:
        print(self.t("config_header", profile=self.profile_name, keyboard=self.keyboard_label()))
        print(self.t("config_settings", layout=self.profile.get("layout"), curve=self.t(str(self.profile.get("curve"))),
                     deadzone=self.profile.get("deadzone"), button_on=self.profile.get("button_on"),
                     anti_deadzone=self.profile.get("anti_deadzone"), poll=self.profile.get("poll_interval_ms"),
                     left_source=self.t("source_" + self.profile.get("stick_sources", {}).get("left", "keyboard")),
                     right_source=self.t("source_" + self.profile.get("stick_sources", {}).get("right", "keyboard")),
                     mouse_enabled=self._on_off(bool(self.profile.get("mouse_joystick_enabled"))),
                     sensitivity=self.profile.get("mouse_sensitivity")))
        if self.profile.get("shift_scan") is not None:
            print(self.t("config_shift", scan=self.profile["shift_scan"]))
        for section in self.actions:
            for action, fr, en in section["actions"]:
                binding = self.profile["bindings"].get(action)
                if not binding:
                    continue
                label = fr if self.language == "fr" else en
                primary = f"{binding['name']} ({self._key_kind(int(binding['scan']))})"
                alternate = binding.get("alternate")
                if alternate:
                    primary += self.t("config_alternate_suffix", name=alternate["name"])
                print(f"  {label:<38} ← {primary}")
        if not self.profile["bindings"]:
            print(self.t("no_bindings"))

    def configure_settings(self) -> None:
        keys = ("layout", "curve", "deadzone", "button_on", "anti_deadzone", "poll_interval_ms",
                "mouse_sensitivity", "mouse_joystick_enabled", "stick_left", "stick_right")
        while True:
            print("\n" + self.t("settings_header"))
            self._print_setting_summary()
            for index, key in enumerate(keys, 1):
                print(f"  {index}) {self.t('setting_' + key)}")
            print(f"  {len(keys) + 1}) " + self.t("settings_save_return"))
            choice = input(self.t("settings_prompt")).strip()
            if choice == str(len(keys) + 1) or not choice:
                self.save()
                return
            try:
                selected = keys[int(choice) - 1]
            except (ValueError, IndexError):
                print(self.t("invalid_choice"))
                continue
            self._change_setting(selected)

    def _print_setting_summary(self) -> None:
        profile = self.profile
        print(self.t("settings_summary", layout=profile["layout"], curve=self.t(str(profile["curve"])),
                     deadzone=profile["deadzone"], button_on=profile["button_on"],
                     anti_deadzone=profile["anti_deadzone"], poll=profile["poll_interval_ms"],
                     sensitivity=profile["mouse_sensitivity"],
                     mouse_enabled=self._on_off(bool(profile.get("mouse_joystick_enabled"))),
                     left_source=self.t("source_" + profile["stick_sources"]["left"]),
                     right_source=self.t("source_" + profile["stick_sources"]["right"])))

    def _change_setting(self, key: str) -> None:
        profile = self.profile
        if key == "layout":
            previous = str(profile["layout"])
            names = list(self.layouts)
            for index, name in enumerate(names, 1):
                print(f"  {index}) {name}")
            try:
                selected = int(input(self.t("layout_prompt"))) - 1
                profile[key] = names[selected]
                if profile[key] != previous:
                    profile["calibration"] = {}
            except (ValueError, IndexError):
                print(self.t("invalid_choice"))
        elif key == "curve":
            values = ("linear", "exponential", "logarithmic")
            for index, value in enumerate(values, 1):
                print(f"  {index}) {self.t(value)}")
            try:
                profile[key] = values[int(input(self.t("curve_prompt"))) - 1]
            except (ValueError, IndexError):
                print(self.t("invalid_choice"))
        elif key in ("deadzone", "button_on", "anti_deadzone", "poll_interval_ms"):
            limits = {"deadzone": (0, 50), "button_on": (1, 100), "anti_deadzone": (0, 50),
                      "poll_interval_ms": (1, 20)}
            low, high = limits[key]
            try:
                value = int(input(self.t("integer_setting_prompt", name=self.t("setting_" + key),
                                         low=low, high=high)))
                if not low <= value <= high:
                    raise ValueError
                profile[key] = value
            except ValueError:
                print(self.t("invalid_number"))
        elif key == "mouse_sensitivity":
            try:
                value = float(input(self.t("sensitivity_prompt")).replace(",", "."))
                if not 0.1 <= value <= 20.0:
                    raise ValueError
                profile[key] = value
            except ValueError:
                print(self.t("invalid_sensitivity"))
        elif key == "mouse_joystick_enabled":
            profile[key] = not bool(profile.get(key, False))
            print(self.t("setting_toggled", name=self.t("setting_" + key),
                         value=self._on_off(profile[key])))
        elif key in ("stick_left", "stick_right"):
            stick = "left" if key == "stick_left" else "right"
            options = ("keyboard", "mouse")
            for index, source in enumerate(options, 1):
                print(f"  {index}) {self.t('source_' + source)}")
            try:
                choice = int(input(self.t("source_prompt")))
                profile["stick_sources"][stick] = options[choice - 1]
            except (ValueError, IndexError):
                print(self.t("invalid_choice"))
        self.save()

    def _on_off(self, value: bool) -> str:
        return self.t("on" if value else "off")

    def manage_profiles(self) -> None:
        print("\n" + self.t("profiles_header", active=self.profile_name))
        names = list(self.config["profiles"])
        for index, name in enumerate(names, 1):
            print(f"  {index}) {name}")
        print("  n) " + self.t("profile_new"))
        choice = input(self.t("profile_prompt")).strip()
        if choice.lower() == "n":
            name = input(self.t("profile_name_prompt")).strip()
            if not name or name in self.config["profiles"]:
                print(self.t("invalid_profile"))
                return
            self.config["profiles"][name] = copy.deepcopy(self.profile)
            self.profile_name = name
            self.config["active_profile"] = name
            self.save()
            print(self.t("profile_created", name=name))
            return
        try:
            selected = names[int(choice) - 1]
        except (ValueError, IndexError):
            print(self.t("invalid_choice"))
            return
        self.profile_name = selected
        self.config["active_profile"] = selected
        self._load_strings()
        self.save()
        print(self.t("profile_selected", name=selected))

    def change_language(self) -> None:
        print(f"  1) {self.t('language_french')}\n  2) {self.t('language_english')}")
        choice = input(self.t("language_prompt")).strip()
        if choice in ("1", "fr", "FR"):
            self.profile["language"] = "fr"
        elif choice in ("2", "en", "EN"):
            self.profile["language"] = "en"
        else:
            print(self.t("invalid_choice"))
            return
        self._load_strings()
        self.save()
        print(self.t("language_changed"))

    def calibrate(self) -> None:
        if self.profile["keyboard"].get("protocol") in ("wooting_sdk", "sdk_provider"):
            print("Le provider SDK fournit les valeurs : aucune calibration HID manuelle n’est requise.")
            return
        keyboard_cfg = self.profile["keyboard"]
        if keyboard_cfg.get("mode") not in ("ace60", "custom"):
            print(self.t("calibration_requires_analog"))
            return
        key_map = {int(scan): int(hid_code) for scan, hid_code in
                   self.layouts[self.profile["layout"]]["scan_to_hid"].items()}
        scans = {int(binding["scan"]) for binding in self.profile["bindings"].values()}
        scans.update(int(binding["alternate"]["scan"]) for binding in self.profile["bindings"].values()
                     if binding.get("alternate"))
        scans = sorted(scans.intersection(key_map))
        if not scans:
            print(self.t("calibration_no_keys"))
            return
        try:
            import keyboard
            import hid
        except ImportError as exc:
            print(self.t("operation_failed", error=exc))
            return
        device: Any = None
        original: list[int] | None = None
        changed = False
        descriptor: HIDReportDescriptor | None = None
        remover: Any = None
        stop = threading.Event()
        try:
            if keyboard_cfg.get("protocol", "ace60") == "generic":
                device, descriptor = open_generic_device(int(keyboard_cfg["vid"]), int(keyboard_cfg["pid"]))
            else:
                device = open_device(int(keyboard_cfg["vid"]), int(keyboard_cfg["pid"]))
                original, changed = enable_debug(device)
            for _ in range(100):
                if read_report(device, 5) is None:
                    break
            remover = keyboard.hook_key(ESCAPE_SCAN,
                                        lambda event: stop.set() if event.event_type == "down" else None)
            for scan in scans:
                label = self._name_for_scan(scan)
                if str(scan) in self.profile["calibration"] and not self._yes("calibrate_again", label=label):
                    continue
                print(self.t("calibration_start", label=label))
                values: list[int] = []
                low, high = 65535, 0
                initial: int | None = None
                last: int | None = None
                stable_since = time.monotonic()
                deadline = time.monotonic() + CALIBRATION_TIMEOUT_SECONDS
                while time.monotonic() < deadline and not stop.is_set():
                    report = read_report(device, 25)
                    if not report:
                        continue
                    raw = (descriptor.read_values(report).get(key_map[scan])
                           if descriptor is not None else get_raw_value(report)[1])
                    if raw is None:
                        continue
                    values.append(raw)
                    if initial is None:
                        initial = raw
                    low, high = min(low, raw), max(high, raw)
                    now = time.monotonic()
                    if last is None or abs(raw - last) >= CALIBRATION_MOVEMENT_THRESHOLD:
                        stable_since = now
                        last = raw
                    if high - low >= CALIBRATION_MINIMUM_SPAN and now - stable_since >= CALIBRATION_STABLE_SECONDS:
                        break
                if stop.is_set():
                    print(self.t("calibration_interrupted"))
                    break
                if len(values) >= 3 and high - low >= CALIBRATION_MINIMUM_SPAN:
                    if descriptor is not None and initial is not None:
                        released, pressed = ((low, high) if abs(initial - low) <= abs(initial - high)
                                             else (high, low))
                    else:
                        released, pressed = high, low
                    self.profile["calibration"][str(scan)] = [released, pressed]
                    self.save()
                    print(self.t("calibration_value", label=label, released=released,
                                 pressed=pressed, count=len(values)))
                else:
                    print(self.t("calibration_insufficient", label=label, span=high - low))
        except (RuntimeError, OSError, hid.HIDException) as exc:
            LOGGER.exception("Calibration HID échouée")
            print(self.t("operation_failed", error=exc))
        finally:
            if remover is not None:
                try:
                    remover()
                except (RuntimeError, OSError):
                    LOGGER.warning("Retrait du hook de calibration échoué", exc_info=True)
            if device is not None:
                try:
                    restore_config(device, original, changed)
                except (RuntimeError, OSError, hid.HIDException):
                    LOGGER.exception("Restauration HID après calibration échouée")
                try:
                    device.close()
                except (RuntimeError, OSError, hid.HIDException):
                    LOGGER.warning("Fermeture HID après calibration échouée", exc_info=True)

    def _name_for_scan(self, scan: int) -> str:
        for binding in self.profile["bindings"].values():
            if int(binding["scan"]) == scan:
                return str(binding["name"])
            alternate = binding.get("alternate")
            if alternate and int(alternate["scan"]) == scan:
                return str(alternate["name"])
        return f"scan {scan}"

    def run_gamepad(self) -> None:
        if self.profile["keyboard"].get("mode") is None:
            print(self.t("choose_keyboard_first"))
            return
        if not self.profile["bindings"]:
            print(self.t("no_bindings_configure"))
            return
        if (self.profile["keyboard"].get("mode") in ("ace60", "custom") and
                self.profile["keyboard"].get("protocol") not in ("wooting_sdk", "sdk_provider")):
            scans = {int(binding["scan"]) for binding in self.profile["bindings"].values()}
            scans.update(int(binding["alternate"]["scan"]) for binding in self.profile["bindings"].values()
                         if binding.get("alternate"))
            analog_scans = [scan for scan in scans if str(scan) in
                            self.layouts[self.profile["layout"]]["scan_to_hid"]]
            missing = [scan for scan in analog_scans if str(scan) not in self.profile["calibration"]]
            if missing and self._yes("calibrate_before_run", default=True):
                self.calibrate()
        print(self.t("runtime_started"))

        def status(text: str) -> None:
            print(f"\n{text}", flush=True)

        mapping = {int(scan): int(hid_code) for scan, hid_code in
                   self.layouts[self.profile["layout"]]["scan_to_hid"].items()}
        runtime = GamepadRuntime(self.profile, mapping, status, self.profile_name)
        runtime.start()
        try:
            while runtime.thread.is_alive():
                runtime.join(0.25)
        except KeyboardInterrupt:
            print("\n" + self.t("runtime_stopping"))
            runtime.stop()
            runtime.join(2.0)

    def save(self) -> None:
        self.config["active_profile"] = self.profile_name
        save_config(self.config)


def run_terminal(config: dict[str, Any]) -> None:
    TerminalApp(config).run()


