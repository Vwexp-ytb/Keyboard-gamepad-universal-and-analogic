from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys

from gamepad_app.core.config import DATA_DIR, LOG_PATH, load_config

LOGGER = logging.getLogger("gamepad_app")
DEPENDENCIES = (
    ("hid", "hidapi>=0.14,<1"),
    ("vgamepad", "vgamepad>=0.1.0,<1"),
    ("keyboard", "keyboard>=0.13.5,<1"),
    ("mouse", "mouse>=0.7.1,<1"),
)


def configure_logging() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


def ensure_dependencies() -> None:
    if getattr(sys, "frozen", False):
        return
    missing = [(module, package) for module, package in DEPENDENCIES
               if importlib.util.find_spec(module) is None]
    for module, package in missing:
        LOGGER.warning("Installation automatique de la dépendance %s", package)
        subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
        if importlib.util.find_spec(module) is None:
            raise RuntimeError(f"L'installation de {package} n'a pas fourni le module {module}.")


def main() -> int:
    configure_logging()
    if os.name != "nt":
        LOGGER.error("Cette application nécessite Windows.")
        print("Cette application nécessite Windows.")
        return 1
    try:
        ensure_dependencies()
        from gamepad_app.ui.terminal import run_terminal
        run_terminal(load_config())
    except (ImportError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        LOGGER.exception("Erreur de démarrage")
        print(f"Démarrage impossible : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
