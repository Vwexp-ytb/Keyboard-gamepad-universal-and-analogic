from __future__ import annotations

import logging
import os
import subprocess
import tkinter as tk
from tkinter import messagebox

from main import configure_logging, ensure_dependencies

LOGGER = logging.getLogger("gamepad_app.gui")


def main() -> int:
    configure_logging()
    if os.name != "nt":
        print("Cette application nécessite Windows.")
        return 1
    try:
        ensure_dependencies()
        from gamepad_app.ui.gui import run_gui
        run_gui()
    except (ImportError, OSError, RuntimeError, subprocess.CalledProcessError, tk.TclError) as exc:
        LOGGER.exception("Démarrage de l'interface graphique impossible")
        try:
            messagebox.showerror(
                "ACE60 Gamepad — démarrage impossible",
                f"L’application n’a pas pu démarrer.\n\n{exc}\n\nConsulte le journal dans %LOCALAPPDATA%\\ACE60Gamepad.",
            )
        except tk.TclError:
            print(f"Démarrage impossible : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
