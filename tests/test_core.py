import unittest
import time
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from gamepad_app.core.config import _upgrade, default_config
from gamepad_app.core.runtime import _axis, _trigger, apply_mouse_motion, percent_from_analog, percent_from_raw
from gamepad_app.hid.protocol import (
    DEFAULT_PID, DEFAULT_VID, HIDReportDescriptor, classify_keyboard_protocol, get_raw_value,
)
from gamepad_app.hid.wooting_sdk import decode_analog_buffer
from gamepad_app.hid.providers import (AsyncKeyboardProvider, WootingSDKProvider, create_provider,
                                       discover_providers)
from gamepad_app.ui.terminal import TerminalApp


class RuntimeConversionTests(unittest.TestCase):
    def test_sdk_analog_values_are_clamped_and_use_profile_response(self):
        self.assertEqual(percent_from_analog(-1.0, 0, "linear", 0), 0)
        self.assertEqual(percent_from_analog(2.0, 0, "linear", 0), 100)
        self.assertEqual(percent_from_analog(0.02, 5, "linear", 0), 0)
        self.assertEqual(percent_from_analog(0.5, 0, "exponential", 0), 25)
        self.assertEqual(percent_from_analog(0.5, 0, "linear", 10), 55)

    def test_sdk_buffer_pairs_usages_and_clamps_normalized_values(self):
        self.assertEqual(decode_analog_buffer([4, 5, 6], [-0.5, 0.35, 1.5], 3),
                         {4: 0.0, 5: 0.35, 6: 1.0})
        self.assertEqual(decode_analog_buffer([4, 5], [0.5, 0.9], 1), {4: 0.5})

    def test_calibration_endpoints_and_deadzone(self):
        limits = [1000, 0]
        self.assertEqual(percent_from_raw(1000, limits, 0, "linear", 0), 0)
        self.assertEqual(percent_from_raw(0, limits, 0, "linear", 0), 100)
        self.assertEqual(percent_from_raw(970, limits, 4, "linear", 0), 0)

    def test_calibration_rejects_equal_limits(self):
        with self.assertRaises(ValueError):
            percent_from_raw(50, [50, 50], 0, "linear", 0)

    def test_curves_stay_inside_output_range(self):
        for curve in ("linear", "exponential", "logarithmic"):
            for raw in range(0, 1001, 25):
                result = percent_from_raw(raw, [1000, 0], 4, curve, 10)
                self.assertGreaterEqual(result, 0)
                self.assertLessEqual(result, 100)

    def test_xinput_boundaries(self):
        self.assertEqual(_axis(0), 0)
        self.assertEqual(_axis(100), 32767)
        self.assertEqual(_trigger(0), 0)
        self.assertEqual(_trigger(100), 255)

    def test_mouse_can_drive_each_stick_independently(self):
        values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP",
                                     "LS_RIGHT", "LS_LEFT", "LS_DOWN", "LS_UP")}
        apply_mouse_motion(values, 3, -2, 2.0, {"left": "keyboard", "right": "mouse"})
        self.assertEqual((values["RS_RIGHT"], values["RS_UP"]), (6, 4))
        self.assertEqual((values["LS_RIGHT"], values["LS_UP"]), (0, 0))
        apply_mouse_motion(values, -4, 5, 1.0, {"left": "mouse", "right": "keyboard"})
        self.assertEqual((values["LS_LEFT"], values["LS_DOWN"]), (4, 5))
        self.assertEqual((values["RS_LEFT"], values["RS_DOWN"]), (0, 0))

    def test_mouse_sensitivity_is_poll_interval_independent(self):
        outputs = []
        for dt, movement in ((1, 1), (8, 8), (20, 20)):
            values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP")}
            apply_mouse_motion(values, movement, 0, 1.0, {"right": "mouse"}, {}, dt, 100)
            outputs.append(values["RS_RIGHT"])
        self.assertEqual(outputs, [8, 8, 8])

    def test_mouse_axis_sensitivities_and_curves_are_independent(self):
        def convert(dx, dy, curve="linear", deadzone=0):
            values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP")}
            apply_mouse_motion(values, dx, dy, 1.0, {"right": "mouse"}, {}, 8, 100,
                               2.0, 1.0, curve, deadzone)
            return values
        linear = convert(20, 20)
        precise = convert(20, 20, "precision")
        accelerated = convert(20, 20, "accelerated")
        self.assertEqual((linear["RS_RIGHT"], linear["RS_DOWN"]), (40, 20))
        self.assertLess(precise["RS_RIGHT"], linear["RS_RIGHT"])
        self.assertGreater(accelerated["RS_RIGHT"], linear["RS_RIGHT"])
        self.assertEqual(convert(2, 2, deadzone=5)["RS_RIGHT"], 0)

    def test_mouse_smoothing_moves_toward_target_over_time(self):
        values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP")}
        state = {}
        apply_mouse_motion(values, 80, 0, 1.0, {"right": "mouse"}, state, 8, 100,
                           smoothing_ms=80)
        self.assertGreater(values["RS_RIGHT"], 0)
        self.assertLess(values["RS_RIGHT"], 80)

    def test_fast_diagonal_motion_is_limited_to_stick_magnitude(self):
        values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP")}
        apply_mouse_motion(values, 1000, 1000, 1.0, {"right": "mouse"})
        self.assertLessEqual((values["RS_RIGHT"] ** 2 + values["RS_DOWN"] ** 2) ** 0.5, 100)

    def test_mouse_stick_recenters_with_time_based_decay(self):
        states = []
        for dt in (1, 10):
            state = {}
            values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP")}
            apply_mouse_motion(values, 10, 0, 1.0, {"right": "mouse"}, state, 8, 100)
            for _ in range(100 // dt):
                apply_mouse_motion(values, 0, 0, 1.0, {"right": "mouse"}, state, dt, 100)
            states.append(state["RS_x"][0])
        self.assertAlmostEqual(states[0], states[1], places=6)
        self.assertLess(states[0], 10)
        self.assertGreater(states[0], 0)

    def test_mouse_axes_and_sticks_keep_independent_state(self):
        values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP",
                                     "LS_RIGHT", "LS_LEFT", "LS_DOWN", "LS_UP")}
        state = {}
        apply_mouse_motion(values, 5, 0, 1.0, {"left": "keyboard", "right": "mouse"}, state)
        self.assertEqual(values["LS_RIGHT"], 0)  # Keyboard-owned direction remains untouched.
        values = {key: 0 for key in ("RS_RIGHT", "RS_LEFT", "RS_DOWN", "RS_UP",
                                     "LS_RIGHT", "LS_LEFT", "LS_DOWN", "LS_UP")}
        apply_mouse_motion(values, 0, -3, 1.0, {"left": "mouse", "right": "keyboard"}, state)
        self.assertEqual((values["RS_RIGHT"], values["RS_UP"]), (0, 0))
        self.assertEqual((values["LS_RIGHT"], values["LS_UP"]), (0, 3))
        self.assertNotIn("RS_x", state)


class ProviderConfigurationTests(unittest.TestCase):
    def test_legacy_profile_gets_optional_sdk_provider_settings(self):
        upgraded = _upgrade({"keyboard": {"mode": "ace60"}, "bindings": {}})
        providers = upgraded["profiles"]["Course"]["sdk_providers"]
        self.assertTrue(providers["wooting"])
        self.assertFalse(providers["razer_chroma"])
        self.assertFalse(providers["corsair_icue"])
        self.assertFalse(providers["logitech_g"])

    def test_sdk_provider_settings_are_sanitized_and_preserved(self):
        upgraded = _upgrade({"profiles": {"Test": {
            "sdk_providers": {"wooting": False, "plugin:extra": True, "bad": "yes"},
        }}, "active_profile": "Test"})
        providers = upgraded["profiles"]["Test"]["sdk_providers"]
        self.assertFalse(providers["wooting"])
        self.assertTrue(providers["plugin:extra"])
        self.assertNotIn("bad", providers)

    def test_provider_discovery_does_not_activate_lighting_sdk_as_key_reader(self):
        with patch("gamepad_app.hid.providers._find_dll", return_value=None), \
                patch("gamepad_app.hid.providers._snapshot_processes", return_value={"iCUE.exe"}), \
                patch("gamepad_app.hid.providers._snapshot_services", return_value={}):
            statuses = {item.provider_id: item for item in discover_providers({"corsair_icue": True})}
        self.assertTrue(statuses["corsair_icue"].installed)
        self.assertFalse(statuses["corsair_icue"].input_capable)
        self.assertIn("sans lecture", statuses["corsair_icue"].details)
        self.assertEqual(statuses["wooting"].details, "désactivé dans le profil")

    def test_provider_factory_exposes_common_contract(self):
        provider = create_provider("wooting")
        self.assertIsInstance(provider, WootingSDKProvider)
        self.assertIn("analog_travel", provider.capabilities)


class SDKProviderTests(unittest.TestCase):
    class FakeProvider:
        provider_id = "fake"
        capabilities = frozenset({"analog_travel"})

        def __init__(self, fail=False):
            self.fail = fail
            self.closed = False

        def initialize(self, _settings):
            return None

        def read_keys(self):
            if self.fail:
                raise OSError("SDK disconnected")
            return {4: 0.7, 5: -1.0, 6: 4.0}

        def close(self):
            self.closed = True

    def test_async_provider_clamps_snapshots_and_closes(self):
        native = self.FakeProvider()
        provider = AsyncKeyboardProvider(native, interval_ms=1)
        provider.initialize({})
        deadline = time.monotonic() + 0.2
        snapshot = {}
        while time.monotonic() < deadline and not snapshot:
            snapshot = provider.read_keys()
            time.sleep(0.002)
        self.assertEqual(snapshot, {4: 0.7, 6: 1.0})
        provider.close()
        self.assertTrue(native.closed)

    def test_async_provider_surfaces_worker_failure_as_runtime_error(self):
        provider = AsyncKeyboardProvider(self.FakeProvider(fail=True), interval_ms=1)
        with self.assertLogs("gamepad_app.hid.providers", level="ERROR"):
            provider.initialize({})
            deadline = time.monotonic() + 0.2
            while time.monotonic() < deadline and provider._error is None:
                time.sleep(0.002)
        with self.assertRaisesRegex(RuntimeError, "SDK disconnected"):
            provider.read_keys()
        provider.close()


class ConfigUpgradeTests(unittest.TestCase):
    def test_default_profile_has_independent_stick_sources(self):
        profile = default_config()["profiles"]["Course"]
        self.assertEqual(profile["stick_sources"], {"left": "keyboard", "right": "keyboard"})
        self.assertEqual(profile["mouse_return_ms"], 100)
        self.assertEqual(profile["keyboard"]["sdk_library"], "")
        self.assertIsNone(profile["keyboard"]["sdk_device_id"])

    def test_sdk_keyboard_settings_survive_profile_upgrade(self):
        config = default_config()
        keyboard = config["profiles"]["Course"]["keyboard"]
        keyboard.update(protocol="wooting_sdk", sdk_library="C:/sdk/analog.dll", sdk_device_id="1234")
        upgraded = _upgrade(config)["profiles"]["Course"]["keyboard"]
        self.assertEqual(upgraded["protocol"], "wooting_sdk")
        self.assertEqual(upgraded["sdk_library"], "C:/sdk/analog.dll")
        self.assertEqual(upgraded["sdk_device_id"], 1234)

    def test_legacy_keyboard_settings_gain_safe_sdk_defaults(self):
        upgraded = _upgrade({"profiles": {"Course": {"keyboard": {"vid": 1, "pid": 2}}}})
        keyboard = upgraded["profiles"]["Course"]["keyboard"]
        self.assertEqual(keyboard["sdk_library"], "")
        self.assertIsNone(keyboard["sdk_device_id"])

    def test_legacy_profiles_get_default_mouse_return(self):
        upgraded = _upgrade({"profiles": {"Course": {"mouse_sensitivity": 2.0}}})
        self.assertEqual(upgraded["profiles"]["Course"]["mouse_return_ms"], 100)
        self.assertEqual(upgraded["profiles"]["Course"]["mouse_sensitivity_x"], 2.0)
        self.assertEqual(upgraded["profiles"]["Course"]["mouse_sensitivity_y"], 2.0)

    def test_new_mouse_profile_values_are_sanitized(self):
        config = default_config()
        profile = config["profiles"]["Course"]
        profile.update(mouse_sensitivity_x=99, mouse_sensitivity_y=float("nan"),
                       mouse_aim_curve="unknown", mouse_deadzone=90, mouse_smoothing_ms=-1)
        profile = _upgrade(config)["profiles"]["Course"]
        self.assertEqual(profile["mouse_sensitivity_x"], 1.0)
        self.assertEqual(profile["mouse_sensitivity_y"], 1.0)
        self.assertEqual(profile["mouse_aim_curve"], "linear")
        self.assertEqual(profile["mouse_deadzone"], 0)
        self.assertEqual(profile["mouse_smoothing_ms"], 0)

    def test_legacy_mouse_settings_migrate_to_right_stick_source(self):
        upgraded = _upgrade({"mouse_x": True})
        profile = upgraded["profiles"]["Course"]
        self.assertEqual(profile["stick_sources"]["right"], "mouse")
        self.assertEqual(profile["stick_sources"]["left"], "keyboard")

    def test_invalid_source_values_fall_back_to_keyboard(self):
        config = default_config()
        config["profiles"]["Course"]["stick_sources"] = {"left": "invalid", "right": "mouse"}
        profile = _upgrade(config)["profiles"]["Course"]
        self.assertEqual(profile["stick_sources"], {"left": "keyboard", "right": "mouse"})

    def test_stick_source_menu_persists_selection_in_profile(self):
        app = TerminalApp(default_config())
        app.save = lambda: None
        with patch("builtins.input", return_value="2"), redirect_stdout(StringIO()):
            app._change_setting("stick_left")
        self.assertEqual(app.profile["stick_sources"]["left"], "mouse")

    def test_invalid_nested_profile_values_are_sanitized(self):
        config = default_config()
        profile = config["profiles"]["Course"]
        profile["keyboard"] = "broken"
        profile["bindings"] = {"A": {"scan": "not-a-number"}, "B": {"scan": 22, "name": "B"}}
        profile["calibration"] = {"22": [1, 1], "23": [500, 10]}
        profile["mouse_sensitivity"] = float("nan")
        cleaned = _upgrade(config)["profiles"]["Course"]
        self.assertIsNone(cleaned["keyboard"]["mode"])
        self.assertEqual(set(cleaned["bindings"]), {"B"})
        self.assertEqual(cleaned["calibration"], {"23": [500, 10]})
        self.assertEqual(cleaned["mouse_sensitivity"], 1.0)

    def test_configuration_display_renders_both_languages(self):
        for language in ("fr", "en"):
            config = default_config()
            config["profiles"]["Course"]["language"] = language
            app = TerminalApp(config)
            with redirect_stdout(StringIO()):
                app.show_config()
                app._print_setting_summary()


class HIDProtocolTests(unittest.TestCase):
    def test_keyboard_protocol_detection_does_not_guess_unknown_vendor_protocols(self):
        self.assertEqual(classify_keyboard_protocol(DEFAULT_VID, DEFAULT_PID, None), "ace60")
        self.assertEqual(classify_keyboard_protocol(0x1234, 0x5678, None), "unsupported")

    def test_keyboard_protocol_detection_recognizes_analog_hid_fields(self):
        descriptor = bytes((0x05, 0x07, 0x09, 0x04, 0x15, 0x00,
                            0x26, 0xFF, 0x03, 0x75, 0x10, 0x95, 0x01, 0x81, 0x02))
        self.assertEqual(classify_keyboard_protocol(0x1234, 0x5678, descriptor), "generic")

    def test_generic_descriptor_decodes_analog_keyboard_usage(self):
        descriptor = bytes((0x05, 0x07, 0x09, 0x04, 0x15, 0x00,
                            0x26, 0xFF, 0x03, 0x75, 0x10, 0x95, 0x01, 0x81, 0x02))
        parser = HIDReportDescriptor(descriptor)
        self.assertEqual(parser.read_values(bytes((0x34, 0x12))), {0x04: 0x1234})

    def test_generic_descriptor_honors_report_id(self):
        descriptor = bytes((0x05, 0x07, 0x09, 0x04, 0x15, 0x00, 0x25, 0xFF,
                            0x85, 0x01, 0x75, 0x08, 0x95, 0x01, 0x81, 0x02))
        parser = HIDReportDescriptor(descriptor)
        self.assertEqual(parser.read_values(bytes((1, 99))), {0x04: 99})
        self.assertEqual(parser.read_values(bytes((2, 99))), {})

    def test_mchose_decoder_rejects_nonmatching_reports(self):
        self.assertEqual(get_raw_value(bytes(65)), (None, None))

    def test_mchose_decoder_reads_known_report_fields(self):
        report = bytearray(65)
        report[0:2] = bytes((0xA0, 0x10))
        report[3] = 0x04
        report[16:18] = bytes((0x12, 0x34))
        self.assertEqual(get_raw_value(bytes(report)), (0x04, 0x1234))


if __name__ == "__main__":
    unittest.main()
