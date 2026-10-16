from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

LOGGER = logging.getLogger(__name__)
REPORT_SIZE = 65
REPORT_HEADER_0 = 0xA0
REPORT_HEADER_1 = 0x10
REPORT_KEY_INDEX_OFFSET = 3
REPORT_ADC_HIGH_OFFSET = 16
REPORT_ADC_LOW_OFFSET = 17
HANDSHAKE_RESPONSE = 0xAA
DEFAULT_VID = 0x41E4
DEFAULT_PID = 0x2103
HID_KEYBOARD_USAGE_PAGE = 0x07


@dataclass(frozen=True)
class HIDValueField:
    report_id: int
    bit_offset: int
    bit_size: int
    usage_page: int
    usage: int
    logical_minimum: int
    logical_maximum: int


class HIDReportDescriptor:
    """Small parser for variable HID input fields used by analog keyboards."""

    def __init__(self, descriptor: bytes | list[int]) -> None:
        self.fields = self._parse(bytes(descriptor))
        self.analog_keyboard_fields = tuple(
            field for field in self.fields
            if field.usage_page == HID_KEYBOARD_USAGE_PAGE and field.logical_maximum > 1
        )

    @staticmethod
    def _parse(descriptor: bytes) -> list[HIDValueField]:
        globals_: dict[str, int] = {
            "usage_page": 0, "logical_minimum": 0, "logical_maximum": 0,
            "report_size": 0, "report_id": 0, "report_count": 0,
        }
        global_stack: list[dict[str, int]] = []
        local_usages: list[int] = []
        usage_minimum: int | None = None
        usage_maximum: int | None = None
        bit_offsets: dict[int, int] = {}
        fields: list[HIDValueField] = []
        offset = 0
        while offset < len(descriptor):
            prefix = descriptor[offset]
            offset += 1
            if prefix == 0xFE:
                if offset + 2 > len(descriptor):
                    break
                length = descriptor[offset]
                offset += 2 + length
                continue
            size_code = prefix & 0x03
            size = 4 if size_code == 3 else size_code
            item_type = (prefix >> 2) & 0x03
            tag = (prefix >> 4) & 0x0F
            payload = descriptor[offset:offset + size]
            if len(payload) != size:
                break
            unsigned = int.from_bytes(payload, "little", signed=False) if size else 0
            signed = int.from_bytes(payload, "little", signed=True) if size else 0
            offset += size
            if item_type == 1:  # Global item.
                if tag == 0:
                    globals_["usage_page"] = unsigned
                elif tag == 1:
                    globals_["logical_minimum"] = signed
                elif tag == 2:
                    globals_["logical_maximum"] = signed if globals_["logical_minimum"] < 0 else unsigned
                elif tag == 7:
                    globals_["report_size"] = unsigned
                elif tag == 8:
                    globals_["report_id"] = unsigned
                elif tag == 9:
                    globals_["report_count"] = unsigned
                elif tag == 10:
                    global_stack.append(globals_.copy())
                elif tag == 11 and global_stack:
                    globals_ = global_stack.pop()
            elif item_type == 2:  # Local item.
                if tag == 0:
                    local_usages.append(unsigned)
                elif tag == 1:
                    usage_minimum = unsigned
                elif tag == 2:
                    usage_maximum = unsigned
            elif item_type == 0 and tag == 8:  # Input main item.
                report_id = globals_["report_id"]
                bit_offset = bit_offsets.get(report_id, 0)
                report_size = globals_["report_size"]
                report_count = globals_["report_count"]
                is_constant = bool(unsigned & 0x01)
                is_variable = bool(unsigned & 0x02)
                if not is_constant and is_variable and 0 < report_size <= 32 and report_count <= 512:
                    usages = list(local_usages)
                    if usage_minimum is not None and usage_maximum is not None:
                        usages.extend(range(usage_minimum, min(usage_maximum, usage_minimum + report_count - 1) + 1))
                    for index in range(report_count):
                        if usages:
                            usage = usages[min(index, len(usages) - 1)]
                            fields.append(HIDValueField(report_id, bit_offset + index * report_size,
                                                        report_size, globals_["usage_page"], usage,
                                                        globals_["logical_minimum"], globals_["logical_maximum"]))
                bit_offsets[report_id] = bit_offset + report_size * report_count
                local_usages = []
                usage_minimum = None
                usage_maximum = None
        return fields

    def read_values(self, report: bytes | list[int]) -> dict[int, int]:
        data = bytes(report)
        values: dict[int, int] = {}
        for field in self.analog_keyboard_fields:
            start = 1 if field.report_id else 0
            if field.report_id and (not data or data[0] != field.report_id):
                continue
            bit_start = field.bit_offset
            first_byte = start + bit_start // 8
            bit_shift = bit_start % 8
            byte_count = (bit_shift + field.bit_size + 7) // 8
            if first_byte + byte_count > len(data):
                continue
            packed = int.from_bytes(data[first_byte:first_byte + byte_count], "little")
            raw = (packed >> bit_shift) & ((1 << field.bit_size) - 1)
            if field.logical_minimum < 0 and raw & (1 << (field.bit_size - 1)):
                raw -= 1 << field.bit_size
            values[field.usage] = raw
        return values


def open_generic_device(vid: int, pid: int) -> tuple[Any, HIDReportDescriptor]:
    """Open a HID-compliant keyboard that exposes analog keys as variable values."""
    try:
        import hid
    except ImportError as exc:
        raise RuntimeError("Dépendance hidapi manquante.") from exc
    candidates = hid.enumerate(vid, pid)
    for info in candidates:
        dev = hid.device()
        try:
            dev.open_path(info["path"])
            descriptor = HIDReportDescriptor(dev.get_report_descriptor())
            if descriptor.analog_keyboard_fields:
                dev.set_nonblocking(True)
                LOGGER.info("Interface HID générique ouverte: interface=%s", info.get("interface_number"))
                return dev, descriptor
            dev.close()
        except (OSError, IOError, AttributeError, ValueError, hid.HIDException) as exc:
            LOGGER.debug("Interface HID non compatible ignorée (%s): %s", info.get("interface_number"), exc)
            try:
                dev.close()
            except (OSError, hid.HIDException):
                LOGGER.debug("Fermeture d'une interface HID ignorée impossible", exc_info=True)
    raise RuntimeError("Aucun rapport HID standard avec des touches analogiques n'a été détecté.")


def classify_keyboard_protocol(vid: int, pid: int, descriptor: bytes | list[int] | None) -> str:
    """Classify the currently supported transports without guessing vendor protocols."""
    if (vid, pid) == (DEFAULT_VID, DEFAULT_PID):
        return "ace60"
    if descriptor:
        try:
            if HIDReportDescriptor(descriptor).analog_keyboard_fields:
                return "generic"
        except (TypeError, ValueError):
            pass
    return "unsupported"


def probe_keyboard_interface(info: dict[str, Any]) -> str:
    """Inspect one enumerated HID interface and return its supported protocol, if any."""
    vid, pid = int(info.get("vendor_id", 0)), int(info.get("product_id", 0))
    if (vid, pid) == (DEFAULT_VID, DEFAULT_PID):
        return "ace60"
    try:
        import hid
    except ImportError:
        return "unsupported"
    try:
        dev = hid.device()
        try:
            dev.open_path(info["path"])
            descriptor = dev.get_report_descriptor()
        finally:
            dev.close()
    except (KeyError, OSError, AttributeError, ValueError, hid.HIDException):
        LOGGER.debug("Impossible d'inspecter l'interface HID %s", info.get("interface_number"), exc_info=True)
        return "unsupported"
    return classify_keyboard_protocol(vid, pid, descriptor)


def open_device(vid: int, pid: int) -> Any:
    try:
        import hid
    except ImportError as exc:
        raise RuntimeError("Dépendance hidapi manquante.") from exc
    candidates = hid.enumerate(vid, pid)
    if not candidates:
        raise RuntimeError(f"Aucun périphérique HID VID={vid:#06x}, PID={pid:#06x}.")
    candidates.sort(key=lambda item: item.get("interface_number") != 2)
    for info in candidates:
        dev = hid.device()
        try:
            dev.open_path(info["path"])
            dev.set_nonblocking(False)
            dev.write([0x00, 0x55, 0x03, 0x00, 0x20, 0x20] + [0] * 59)
            response = dev.read(REPORT_SIZE, timeout_ms=500)
            if response and response[0] == HANDSHAKE_RESPONSE:
                dev.set_nonblocking(True)
                LOGGER.info("Interface HID ouverte: interface=%s usage=%s", info.get("interface_number"), info.get("usage"))
                return dev
            dev.close()
        except (OSError, IOError, hid.HIDException) as exc:
            LOGGER.warning("Interface HID ignorée (%s): %s", info.get("interface_number"), exc)
            try:
                dev.close()
            except (OSError, hid.HIDException):
                LOGGER.debug("Fermeture d'une interface HID ignorée impossible", exc_info=True)
    raise RuntimeError("Aucune interface HID n'a répondu au handshake.")


def send_recv(dev: Any, data: list[int], timeout_ms: int = 500) -> bytes | None:
    packet = [0x00, *data]
    packet += [0] * max(0, REPORT_SIZE - len(packet))
    dev.write(packet[:REPORT_SIZE])
    time.sleep(0.02)
    response = dev.read(REPORT_SIZE, timeout_ms=timeout_ms)
    return bytes(response) if response else None


def read_report(dev: Any, timeout_ms: int = 20) -> bytes | None:
    data = dev.read(REPORT_SIZE, timeout_ms=timeout_ms)
    return bytes(data) if data else None


def get_raw_value(report: bytes) -> tuple[int | None, int | None]:
    if len(report) >= REPORT_ADC_LOW_OFFSET + 1 and report[:2] == bytes((REPORT_HEADER_0, REPORT_HEADER_1)):
        raw = (report[REPORT_ADC_HIGH_OFFSET] << 8) | report[REPORT_ADC_LOW_OFFSET]
        return report[REPORT_KEY_INDEX_OFFSET], raw
    return None, None


def read_func_config(dev: Any) -> list[int]:
    response = send_recv(dev, [0x55, 0x05, 0x00, 0x38, 0x38])
    if not response or response[0] != HANDSHAKE_RESPONSE:
        raise RuntimeError("Pas de réponse à GetFuncConfig.")
    config = list(response[8:64])
    if len(config) != 56:
        raise RuntimeError(f"Réponse de configuration incorrecte ({len(config)} octets).")
    return config


def write_func_config(dev: Any, config: list[int]) -> bool:
    checksum = (len(config) + sum(config)) & 0xFF
    response = send_recv(dev, [0x55, 0x06, 0x00, checksum, len(config), 0, 0, 0, *config])
    return bool(response and response[0] == HANDSHAKE_RESPONSE)


def enable_debug(dev: Any) -> tuple[list[int], bool]:
    original = read_func_config(dev)
    modified = list(original)
    modified[7] |= 0x08
    if modified == original:
        return original, False
    if not write_func_config(dev, modified):
        try:
            write_func_config(dev, original)
        except (OSError, RuntimeError):
            LOGGER.exception("Échec de restauration après activation debug")
        raise RuntimeError("Échec de l'activation du mode debug.")
    LOGGER.info("Mode debug analogique activé.")
    return original, True


def restore_config(dev: Any, original: list[int] | None, changed: bool) -> None:
    if original is None or not changed:
        return
    if not write_func_config(dev, original):
        LOGGER.error("Restauration HID non confirmée; débranchez/rebranchez le clavier.")
    else:
        LOGGER.info("Configuration HID d'origine restaurée.")
