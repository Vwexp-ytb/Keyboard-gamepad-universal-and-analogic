"""Common, optional keyboard SDK provider interface and discovery helpers.

Providers are loaded on the runtime worker, never on the UI thread. Vendor SDKs
must be optional: failure to load one leaves the regular keyboard/HID paths in
charge. Third-party plugins can register an entry point in the
``ace60_gamepad.keyboard_providers`` group and implement the protocol below.
"""
from __future__ import annotations

import importlib.metadata
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from gamepad_app.hid.wooting_sdk import WootingAnalogSDK

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class IKeyboardSDKProvider(Protocol):
    """Contract for keyboard input providers.

    ``read_keys`` returns USB HID usage -> normalized 0..1 travel values.
    Implementations must make reads non-blocking or document a bounded timeout;
    the runtime invokes methods on a dedicated worker thread.
    """

    provider_id: str
    capabilities: frozenset[str]

    def initialize(self, settings: dict[str, Any]) -> None: ...
    def read_keys(self) -> dict[int, float]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ProviderStatus:
    provider_id: str
    installed: bool
    running: bool
    input_capable: bool
    details: str


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    processes: tuple[str, ...]
    services: tuple[str, ...]
    dll_candidates: tuple[str, ...]
    input_capable: bool = False


_SPECS = (
    ProviderSpec("wooting", "Wooting Analog SDK", ("Wootility.exe",), (),
                 ("wooting_analog_sdk_dist.dll", "wooting_analog_sdk.dll"), True),
    # These vendor SDKs are detected for diagnostics, but their published APIs
    # are for lighting/device control rather than arbitrary keyboard key state.
    ProviderSpec("razer_chroma", "Razer Chroma", ("Razer Synapse 3.exe", "RazerAppEngine.exe"),
                 ("Razer Chroma SDK Server",),
                 ("RzChromaSDK.dll", "RzChromaSDK64.dll")),
    ProviderSpec("corsair_icue", "Corsair iCUE", ("iCUE.exe", "Corsair.Service.exe"),
                 ("CorsairService", "CorsairLLAccessService"),
                 ("CUESDK.x64_2019.dll", "CUESDK.x64_2024.dll")),
    ProviderSpec("logitech_g", "Logitech G SDK", ("lghub.exe", "lghub_agent.exe"),
                 ("LGHUBUpdaterService",),
                 ("LogitechGSDK.dll", "LogitechLed.dll")),
)


def _program_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        value = os.environ.get(env_name)
        if value:
            roots.append(Path(value))
    return tuple(roots)


def _find_dll(names: tuple[str, ...]) -> Path | None:
    roots = _program_roots()
    # Keep lookup bounded: do not recursively scan disks. SDK consumers can set
    # ACE60_<PROVIDER>_SDK_DLL or pass a library path in their profile.
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate
        try:
            for child in root.iterdir():
                if child.is_dir():
                    for name in names:
                        candidate = child / name
                        if candidate.is_file():
                            return candidate
        except OSError:
            continue
    return None


def _snapshot_processes() -> set[str]:
    names = tuple(name for spec in _SPECS for name in spec.processes)
    if os.name != "nt" or not names:
        return set()
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
            timeout=0.75, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = result.stdout.casefold()
        return {name for name in names if name.casefold() in output}
    except (OSError, subprocess.SubprocessError):
        LOGGER.debug("Impossible de vérifier les processus SDK.", exc_info=True)
        return set()


def _snapshot_services() -> dict[str, tuple[bool, bool]]:
    names = tuple(name for spec in _SPECS for name in spec.services)
    if os.name != "nt":
        return {}
    states: dict[str, tuple[bool, bool]] = {}
    for name in names:
        try:
            result = subprocess.run(
                ["sc", "query", name], capture_output=True, text=True, timeout=0.35,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = result.stdout.upper()
            states[name] = (result.returncode == 0,
                            result.returncode == 0 and "RUNNING" in output)
        except (OSError, subprocess.SubprocessError):
            LOGGER.debug("Impossible de vérifier le service %s.", name, exc_info=True)
    return states


def discover_providers(enabled: dict[str, bool] | None = None) -> list[ProviderStatus]:
    """Inspect known SDK files/processes once; this never loads a vendor DLL."""
    statuses = []
    process_snapshot = _snapshot_processes()
    service_snapshot = _snapshot_services()
    for spec in _SPECS:
        if enabled is not None and not enabled.get(spec.provider_id, False):
            statuses.append(ProviderStatus(spec.provider_id, False, False, spec.input_capable,
                                           "désactivé dans le profil"))
            continue
        env_key = f"ACE60_{spec.provider_id.upper()}_SDK_DLL"
        explicit = Path(os.environ[env_key]).expanduser() if os.environ.get(env_key) else None
        dll_path = explicit if explicit and explicit.is_file() else _find_dll(spec.dll_candidates)
        running_processes = set(spec.processes).intersection(process_snapshot)
        running_services = {name for name in spec.services if service_snapshot.get(name, (False, False))[1]}
        running = bool(running_processes or running_services)
        installed = dll_path is not None or running or any(
            service_snapshot.get(name, (False, False))[0] for name in spec.services)
        if not installed:
            details = "SDK/logiciel non détecté"
        elif spec.input_capable:
            details = (f"bibliothèque SDK localisée ({dll_path})" if dll_path else
                       "logiciel Wootility détecté; chemin de la DLL à configurer")
        else:
            details = "logiciel détecté; API publique repérée sans lecture générique des touches"
        statuses.append(ProviderStatus(spec.provider_id, installed, running,
                                       spec.input_capable, details))

    try:
        eps = importlib.metadata.entry_points()
        plugins = eps.select(group="ace60_gamepad.keyboard_providers")
        if enabled is not None:
            plugins = [entry for entry in plugins if enabled.get(f"plugin:{entry.name}", False)]
        statuses.extend(ProviderStatus(f"plugin:{entry.name}", True, True, True,
                                       f"provider Python installé ({entry.value})") for entry in plugins)
    except Exception:
        LOGGER.debug("Découverte des plugins SDK indisponible.", exc_info=True)
    return statuses


def available_provider_ids() -> tuple[str, ...]:
    """Return built-in and installed third-party provider identifiers."""
    try:
        eps = importlib.metadata.entry_points().select(group="ace60_gamepad.keyboard_providers")
        return ("wooting", *(f"plugin:{entry.name}" for entry in eps))
    except Exception:
        LOGGER.debug("Liste des providers tiers indisponible.", exc_info=True)
        return ("wooting",)


class WootingSDKProvider:
    provider_id = "wooting"
    capabilities = frozenset({"digital_keys", "analog_travel", "device_selection"})

    def __init__(self) -> None:
        self._sdk: WootingAnalogSDK | None = None

    def initialize(self, settings: dict[str, Any]) -> None:
        library = str(settings.get("library", ""))
        device_id = settings.get("device_id")
        self._sdk = WootingAnalogSDK(library, device_id)

    def read_keys(self) -> dict[int, float]:
        return self._sdk.read_values() if self._sdk else {}

    def close(self) -> None:
        sdk, self._sdk = self._sdk, None
        if sdk is not None:
            sdk.close()


class AsyncKeyboardProvider:
    """Move potentially blocking native SDK reads off the gamepad loop."""

    provider_id = "async"
    capabilities = frozenset({"digital_keys", "analog_travel"})

    def __init__(self, provider: IKeyboardSDKProvider, interval_ms: float = 1.0) -> None:
        self._provider = provider
        self._interval = max(0.0005, float(interval_ms) / 1000.0)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot: dict[int, float] = {}
        self._error: Exception | None = None
        self._thread: threading.Thread | None = None
        self._provider_closed = False

    def initialize(self, settings: dict[str, Any]) -> None:
        try:
            self._provider.initialize(settings)
        except Exception as exc:
            self._close_native()
            raise RuntimeError(f"Initialisation SDK {self._provider.provider_id} échouée : {exc}") from exc
        self._thread = threading.Thread(target=self._poll, name=f"sdk-{self._provider.provider_id}",
                                       daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        active: dict[int, float] = {}
        try:
            while not self._stop.is_set():
                values = self._provider.read_keys()
                for usage, value in values.items():
                    usage, value = int(usage), max(0.0, min(1.0, float(value)))
                    if value <= 0.0:
                        active.pop(usage, None)
                    else:
                        active[usage] = value
                with self._lock:
                    self._snapshot = active.copy()
                self._stop.wait(self._interval)
        except Exception as exc:
            self._error = exc
            LOGGER.exception("Lecture asynchrone SDK interrompue (%s)", self._provider.provider_id)
        finally:
            self._close_native()

    def _close_native(self) -> None:
        if self._provider_closed:
            return
        self._provider_closed = True
        try:
            self._provider.close()
        except Exception:
            LOGGER.exception("Déchargement du provider SDK échoué (%s)", self._provider.provider_id)

    def read_keys(self) -> dict[int, float]:
        if self._error is not None:
            raise RuntimeError(f"Lecture du SDK {self._provider.provider_id} interrompue: {self._error}")
        with self._lock:
            return self._snapshot.copy()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is None:
            self._close_native()
        else:
            # Release native resources on the polling worker, never while it is
            # inside a DLL call. A stuck native call remains isolated in a daemon.
            thread.join(timeout=0.25)
            if thread.is_alive():
                LOGGER.error("Le SDK %s ne répond pas; son worker reste isolé.", self._provider.provider_id)


def create_provider(provider_id: str) -> IKeyboardSDKProvider:
    if provider_id == "wooting":
        return WootingSDKProvider()
    try:
        entry_points = importlib.metadata.entry_points()
        name = provider_id.removeprefix("plugin:")
        selected = entry_points.select(group="ace60_gamepad.keyboard_providers", name=name)
        entry = next(iter(selected), None)
        if entry is None:
            raise LookupError(f"Provider SDK non enregistré : {provider_id}")
        provider_type = entry.load()
        provider = provider_type()
        if not isinstance(provider, IKeyboardSDKProvider):
            raise TypeError(f"Le provider {provider_id} ne respecte pas IKeyboardSDKProvider")
        return provider
    except Exception as exc:
        LOGGER.exception("Chargement du provider %s impossible", provider_id)
        raise RuntimeError(f"Chargement du provider SDK {provider_id} impossible : {exc}") from exc
