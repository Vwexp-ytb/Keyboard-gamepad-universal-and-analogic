from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
KEYCODE_HID = 0
MAX_KEYS = 128


class _DeviceInfo(ctypes.Structure):
    _fields_ = [
        ("vendor_id", ctypes.c_uint16),
        ("product_id", ctypes.c_uint16),
        ("manufacturer_name", ctypes.c_char_p),
        ("device_name", ctypes.c_char_p),
        ("device_id", ctypes.c_uint64),
        ("device_type", ctypes.c_int),
    ]


def _decode(value: bytes | None) -> str:
    return value.decode("utf-8", errors="replace") if value else ""


def decode_analog_buffer(codes: Any, values: Any, count: int) -> dict[int, float]:
    """Copy and clamp the SDK's paired HID usage/value buffers."""
    length = min(max(0, int(count)), len(codes), len(values), MAX_KEYS)
    return {int(codes[index]): max(0.0, min(1.0, float(values[index])))
            for index in range(length)}


class WootingAnalogSDK:
    """Optional adapter for the Wooting Analog SDK and installed SDK plugins."""

    def __init__(self, library_path: str, device_id: int | None = None) -> None:
        path = Path(library_path).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Bibliothèque du SDK analogique introuvable : {path}")
        self._dll_directory = None
        self._initialized = False
        try:
            if hasattr(os, "add_dll_directory"):
                self._dll_directory = os.add_dll_directory(str(path.parent))
            self._library = ctypes.CDLL(str(path))
        except OSError as exc:
            self.close()
            raise RuntimeError(f"Impossible de charger le SDK analogique : {exc}") from exc
        try:
            self._configure_functions()
            result = int(self._library.wooting_analog_initialise())
            if result < 0:
                raise RuntimeError(self._sdk_error(result))
            self._initialized = True
            if int(self._library.wooting_analog_set_keycode_mode(KEYCODE_HID)) < 0:
                raise RuntimeError("Le SDK analogique refuse le mode de touches HID.")
            devices = self._get_devices()
            matching = [entry for entry in devices if entry["device_type"] in (1, 2)]
            if device_id is not None:
                matching = [entry for entry in matching if entry["device_id"] == int(device_id)]
            if not matching:
                raise RuntimeError("Aucun clavier analogique correspondant n'est exposé par le SDK.")
            self.device_id = matching[0]["device_id"]
        except (AttributeError, OSError) as exc:
            self.close()
            raise RuntimeError(f"Bibliothèque SDK incompatible ou incomplète : {exc}") from exc
        except RuntimeError:
            self.close()
            raise

    def _configure_functions(self) -> None:
        lib = self._library
        lib.wooting_analog_initialise.restype = ctypes.c_int
        lib.wooting_analog_initialise.argtypes = []
        lib.wooting_analog_uninitialise.restype = ctypes.c_int
        lib.wooting_analog_uninitialise.argtypes = []
        lib.wooting_analog_set_keycode_mode.restype = ctypes.c_int
        lib.wooting_analog_set_keycode_mode.argtypes = [ctypes.c_int]
        lib.wooting_analog_get_connected_devices_info.restype = ctypes.c_int
        lib.wooting_analog_get_connected_devices_info.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32,
        ]
        lib.wooting_analog_read_full_buffer_device.restype = ctypes.c_int
        lib.wooting_analog_read_full_buffer_device.argtypes = [
            ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_float),
            ctypes.c_uint32, ctypes.c_uint64,
        ]

    @staticmethod
    def _sdk_error(code: int) -> str:
        names = {
            -2000: "SDK analogique non initialisé",
            -2001: "Aucun clavier analogique exposé par le SDK",
            -2002: "Clavier analogique déconnecté",
            -2003: "Échec du SDK analogique",
            -2005: "Aucun plugin analogique compatible n'est installé",
            -2006: "Fonction manquante dans la bibliothèque du SDK",
            -2009: "Version du SDK incompatible",
            -2010: "Bibliothèque système du SDK introuvable",
        }
        return f"{names.get(code, 'Erreur du SDK analogique')} ({code})."

    def _get_devices(self) -> list[dict[str, Any]]:
        pointers = (ctypes.c_void_p * 32)()
        count = int(self._library.wooting_analog_get_connected_devices_info(pointers, 32))
        if count < 0:
            raise RuntimeError(self._sdk_error(count))
        devices: list[dict[str, Any]] = []
        for pointer in pointers[:min(count, len(pointers))]:
            if not pointer:
                continue
            info = ctypes.cast(pointer, ctypes.POINTER(_DeviceInfo)).contents
            devices.append({
                "vendor_id": int(info.vendor_id), "product_id": int(info.product_id),
                "manufacturer": _decode(info.manufacturer_name),
                "name": _decode(info.device_name), "device_id": int(info.device_id),
                "device_type": int(info.device_type),
            })
        return devices

    @classmethod
    def list_devices(cls, library_path: str) -> list[dict[str, Any]]:
        sdk = cls.__new__(cls)
        path = Path(library_path).expanduser()
        if not path.is_file():
            raise RuntimeError(f"Bibliothèque du SDK analogique introuvable : {path}")
        sdk._initialized = False
        try:
            if hasattr(os, "add_dll_directory"):
                sdk._dll_directory = os.add_dll_directory(str(path.parent))
            else:
                sdk._dll_directory = None
            sdk._library = ctypes.CDLL(str(path))
        except OSError as exc:
            sdk.close()
            raise RuntimeError(f"Impossible de charger le SDK analogique : {exc}") from exc
        sdk._initialized = False
        try:
            sdk._configure_functions()
            result = int(sdk._library.wooting_analog_initialise())
            if result < 0:
                raise RuntimeError(sdk._sdk_error(result))
            sdk._initialized = True
            return [entry for entry in sdk._get_devices() if entry["device_type"] in (1, 2)]
        except AttributeError as exc:
            raise RuntimeError(f"Bibliothèque SDK incompatible ou incomplète : {exc}") from exc
        finally:
            sdk.close()

    def read_values(self) -> dict[int, float]:
        if not self._initialized:
            return {}
        codes = (ctypes.c_uint16 * MAX_KEYS)()
        values = (ctypes.c_float * MAX_KEYS)()
        count = int(self._library.wooting_analog_read_full_buffer_device(
            codes, values, MAX_KEYS, self.device_id,
        ))
        if count < 0:
            raise RuntimeError(self._sdk_error(count))
        return decode_analog_buffer(codes, values, count)

    def close(self) -> None:
        if self._initialized:
            try:
                self._library.wooting_analog_uninitialise()
            finally:
                self._initialized = False
        dll_directory = getattr(self, "_dll_directory", None)
        if dll_directory is not None:
            dll_directory.close()
            self._dll_directory = None
