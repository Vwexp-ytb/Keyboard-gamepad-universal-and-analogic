from __future__ import annotations

import copy
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from gamepad_app.core.config import (
    ACTION_IDS, ACTION_LABELS_PATH, LAYOUTS_PATH, load_config, load_json, save_config,
)
from gamepad_app.core.runtime import ESCAPE_SCAN, EXIT_SCAN, MOUSE_TOGGLE_SCAN, GamepadRuntime
from gamepad_app.hid.protocol import (
    DEFAULT_PID, DEFAULT_VID, HIDReportDescriptor, enable_debug, get_raw_value,
    open_device, open_generic_device, read_report, restore_config,
    probe_keyboard_interface,
)
from gamepad_app.hid.wooting_sdk import WootingAnalogSDK
from gamepad_app.hid.providers import available_provider_ids

LOGGER = logging.getLogger(__name__)
DIAGNOSTIC_SECONDS = 8.0
COLORS = {
    "window": "#F3F5F7", "surface": "#FFFFFF", "text": "#17212B",
    "muted": "#647180", "border": "#D9E0E7", "accent": "#285F9E",
    "accent_hover": "#1E4E84", "selected": "#E7EFF8", "success": "#287A55",
}


class GamepadGUI:
    """Tkinter front end for profile setup, HID checks, and the shared runtime."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ACE60 Gamepad — Clavier vers manette")
        self.root.geometry("1080x780")
        self.root.minsize(900, 700)
        self.config = load_config()
        self.profile_name = self.config["active_profile"]
        self.actions = load_json(ACTION_LABELS_PATH)["sections"]
        self.layouts = load_json(LAYOUTS_PATH)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.runtime: GamepadRuntime | None = None
        self.worker: threading.Thread | None = None
        self.cancel_worker = threading.Event()
        self.device_choices: dict[str, dict[str, Any]] = {}
        self.action_labels = {action: fr for section in self.actions
                              for action, fr, _ in section["actions"]}
        self._configure_style()
        self._build()
        self._load_profile()
        self.root.after(100, self._poll_events)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background=COLORS["window"])
        self.root.option_add("*Font", ("Segoe UI", 9))
        style.configure("TFrame", background=COLORS["window"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["window"], foreground=COLORS["text"])
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["window"], foreground=COLORS["muted"])
        style.configure("Title.TLabel", background=COLORS["window"], foreground=COLORS["text"],
                        font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background=COLORS["window"], foreground=COLORS["muted"],
                        font=("Segoe UI", 9))
        style.configure("TLabelframe", background=COLORS["window"], bordercolor=COLORS["border"],
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=COLORS["window"], foreground=COLORS["text"],
                        font=("Segoe UI Semibold", 9))
        style.configure("TNotebook", background=COLORS["window"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 9), background=COLORS["window"],
                        foreground=COLORS["muted"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface"])],
                  foreground=[("selected", COLORS["accent"])])
        style.configure("TButton", padding=(11, 7), background="#E8EDF2", foreground=COLORS["text"],
                        bordercolor=COLORS["border"])
        style.map("TButton", background=[("active", "#DDE4EB"), ("disabled", "#F0F2F4")])
        style.configure("Accent.TButton", padding=(13, 8), background=COLORS["accent"],
                        foreground="#FFFFFF", bordercolor=COLORS["accent"])
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"])],
                  foreground=[("disabled", "#E7ECF1")])
        style.configure("TEntry", padding=6, fieldbackground=COLORS["surface"],
                        bordercolor=COLORS["border"])
        style.configure("TSpinbox", padding=5, fieldbackground=COLORS["surface"],
                        bordercolor=COLORS["border"])
        style.configure("TCombobox", padding=5, fieldbackground=COLORS["surface"],
                        bordercolor=COLORS["border"])
        style.configure("Treeview", rowheight=29, background=COLORS["surface"],
                        fieldbackground=COLORS["surface"], foreground=COLORS["text"],
                        bordercolor=COLORS["border"], borderwidth=1)
        style.configure("Treeview.Heading", padding=(8, 8), background="#EEF2F5",
                        foreground=COLORS["muted"], font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", COLORS["selected"])],
                  foreground=[("selected", COLORS["text"])])

    @property
    def profile(self) -> dict[str, Any]:
        return self.config["profiles"][self.profile_name]

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, padding=(24, 18, 24, 12))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="ACE60 Gamepad", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(header, text="Configuration et contrôle de la manette",
                  style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(header, textvariable=self.profile_var, state="readonly", width=24,
                                          values=list(self.config["profiles"]))
        self.profile_combo.grid(row=0, column=1, rowspan=2, sticky="e", padx=(8, 6))
        self.profile_combo.bind("<<ComboboxSelected>>", self._select_profile)
        ttk.Button(header, text="Nouveau profil", command=self._new_profile).grid(
            row=0, column=2, rowspan=2, padx=(4, 0))
        self.status_var = tk.StringVar(value="Prêt. Sélectionne ton clavier, puis configure les touches.")
        footer = ttk.Frame(self.root, padding=(24, 9, 24, 12))
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Separator(footer).pack(fill="x", pady=(0, 9))
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel", anchor="w").pack(fill="x")

        self.tabs = ttk.Notebook(self.root)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 4))
        self.setup_tab = ttk.Frame(self.tabs, padding=16)
        self.action_tab = ttk.Frame(self.tabs, padding=16)
        self.run_tab = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(self.setup_tab, text="1 · Clavier et visée")
        self.tabs.add(self.action_tab, text="2 · Affectations")
        self.tabs.add(self.run_tab, text="3 · Démarrer")
        self._build_setup_tab()
        self._build_actions_tab()
        self._build_run_tab()

    def _build_setup_tab(self) -> None:
        tab = self.setup_tab
        tab.columnconfigure(0, weight=1)
        device = ttk.LabelFrame(tab, text="1 · Clavier analogique", padding=12)
        device.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        device.columnconfigure(1, weight=1)
        ttk.Label(device, text="Appareil").grid(row=0, column=0, sticky="w", padx=4, pady=6)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(device, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.device_combo.bind("<<ComboboxSelected>>", self._choose_detected_device)
        ttk.Button(device, text="Détecter les claviers", command=self._scan_devices).grid(
            row=0, column=2, padx=4)
        self.device_support_var = tk.StringVar(value="Branche le clavier puis lance la détection automatique.")
        ttk.Label(device, textvariable=self.device_support_var, style="Muted.TLabel", wraplength=780).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 8))
        self.advanced_device_button = ttk.Button(device, text="Options manuelles", command=self._toggle_device_advanced)
        self.advanced_device_button.grid(row=2, column=0, sticky="w", padx=4, pady=(2, 4))
        self.advanced_device_frame = ttk.Frame(device)
        self.advanced_device_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4, pady=(6, 0))
        self.advanced_device_frame.grid_remove()
        advanced = self.advanced_device_frame
        advanced.columnconfigure(1, weight=1)
        ttk.Label(advanced, text="Mode").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.mode_var = tk.StringVar()
        ttk.Combobox(advanced, textvariable=self.mode_var, state="readonly", width=22,
                     values=("MCHOSE ACE60", "Clavier standard", "Autre clavier HID")).grid(
                         row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(advanced, text="VID / PID").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ids = ttk.Frame(advanced)
        ids.grid(row=1, column=1, sticky="w")
        self.vid_var, self.pid_var = tk.StringVar(), tk.StringVar()
        ttk.Entry(ids, textvariable=self.vid_var, width=12).pack(side="left", padx=(4, 6))
        ttk.Entry(ids, textvariable=self.pid_var, width=12).pack(side="left", padx=4)
        ttk.Label(advanced, text="Protocole de lecture").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.protocol_var = tk.StringVar()
        ttk.Combobox(advanced, textvariable=self.protocol_var, state="readonly", width=34,
                     values=("HID standard (détection automatique)", "ACE60 / protocole MCHOSE",
                             "SDK analogique + plugins compatibles")).grid(
                         row=2, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(advanced, text="À utiliser uniquement avec le protocole documenté du fabricant.",
                  style="Muted.TLabel", wraplength=740).grid(row=3, column=0, columnspan=3,
                                                              sticky="w", padx=4, pady=4)
        ttk.Label(advanced, text="Bibliothèque Wooting SDK (optionnelle)").grid(
            row=4, column=0, sticky="w", padx=4, pady=4)
        self.sdk_library_var = tk.StringVar()
        sdk_path_frame = ttk.Frame(advanced)
        sdk_path_frame.grid(row=4, column=1, columnspan=2, sticky="ew")
        sdk_path_frame.columnconfigure(0, weight=1)
        ttk.Entry(sdk_path_frame, textvariable=self.sdk_library_var).grid(
            row=0, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(sdk_path_frame, text="Parcourir…", command=self._browse_sdk_library).grid(
            row=0, column=1, padx=4, pady=4)
        ttk.Label(advanced, text=("Avec Universal Analog Plugin : Wooting, certains Razer Huntsman, "
                                  "DrunkDeer, NuPhy et modèles Keychron HE. Les plugins/firmwares "
                                  "requis restent à installer."),
                  style="Muted.TLabel", wraplength=760).grid(
            row=5, column=0, columnspan=3, sticky="w", padx=4, pady=4)
        provider_frame = ttk.LabelFrame(advanced, text="Détection des SDK fabricants", padding=6)
        provider_frame.grid(row=6, column=0, columnspan=3, sticky="ew", padx=4, pady=6)
        provider_names = (("wooting", "Wooting Analog SDK"),
                          ("razer_chroma", "Razer Chroma"),
                          ("corsair_icue", "Corsair iCUE"),
                          ("logitech_g", "Logitech G"))
        self.sdk_provider_vars = {}
        for index, (provider_id, label) in enumerate(provider_names):
            variable = tk.BooleanVar(value=provider_id == "wooting")
            self.sdk_provider_vars[provider_id] = variable
            ttk.Checkbutton(provider_frame, text=label, variable=variable).grid(
                row=0, column=index, sticky="w", padx=4)
        ttk.Label(provider_frame,
                  text="La détection ne garantit pas un accès aux touches : Chroma/iCUE servent surtout à l’éclairage. "
                       "Wooting (ou un plugin analogique) fournit des valeurs de touches.",
                  style="Muted.TLabel", wraplength=740).grid(row=1, column=0, columnspan=4,
                                                               sticky="w", padx=4, pady=(4, 0))
        ttk.Label(advanced, text="Provider SDK actif").grid(row=7, column=0, sticky="w", padx=4, pady=4)
        self.sdk_provider_var = tk.StringVar(value="wooting")
        ttk.Combobox(advanced, textvariable=self.sdk_provider_var, state="readonly", width=34,
                     values=available_provider_ids()).grid(row=7, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(advanced, text="Les extensions tierces s’ajoutent via le point d’entrée Python documenté.",
                  style="Muted.TLabel").grid(row=7, column=2, sticky="w", padx=4, pady=4)

        sticks = ttk.LabelFrame(tab, text="Entrées des sticks", padding=10)
        sticks.grid(row=1, column=0, sticky="ew", pady=6)
        for column in range(5):
            sticks.columnconfigure(column, weight=1)
        self.left_source_var, self.right_source_var = tk.StringVar(), tk.StringVar()
        ttk.Label(sticks, text="Stick gauche").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(sticks, textvariable=self.left_source_var, state="readonly",
                     values=("Clavier", "Souris")).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(sticks, text="Stick droit").grid(row=0, column=2, sticky="w", padx=4)
        ttk.Combobox(sticks, textvariable=self.right_source_var, state="readonly",
                     values=("Clavier", "Souris")).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Label(sticks, text="Sensibilité X / Y").grid(row=1, column=0, sticky="w", padx=4, pady=8)
        self.sensitivity_x_var, self.sensitivity_y_var = tk.StringVar(), tk.StringVar()
        sens_frame = ttk.Frame(sticks)
        sens_frame.grid(row=1, column=1, sticky="w", padx=4, pady=8)
        ttk.Spinbox(sens_frame, from_=0.1, to=20.0, increment=0.1,
                    textvariable=self.sensitivity_x_var, width=7).pack(side="left")
        ttk.Label(sens_frame, text=" /").pack(side="left")
        ttk.Spinbox(sens_frame, from_=0.1, to=20.0, increment=0.1,
                    textvariable=self.sensitivity_y_var, width=7).pack(side="left")
        ttk.Label(sticks, text="Disposition du clavier").grid(row=1, column=2, sticky="w", padx=4, pady=8)
        self.layout_var = tk.StringVar()
        layout_combo = ttk.Combobox(sticks, textvariable=self.layout_var, state="readonly",
                                    values=tuple(self.layouts))
        layout_combo.grid(row=1, column=3, sticky="ew", padx=4, pady=8)
        layout_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_bindings())
        ttk.Label(sticks, text="Retour au centre (ms)").grid(row=2, column=0, sticky="w", padx=4, pady=6)
        self.mouse_return_var = tk.StringVar()
        ttk.Spinbox(sticks, from_=20, to=1000, increment=10, textvariable=self.mouse_return_var,
                    width=10).grid(row=2, column=1, sticky="w", padx=4, pady=6)
        ttk.Label(sticks, text="Durée de l’amortissement après le mouvement (20–1000 ms).")\
            .grid(row=2, column=2, columnspan=2, sticky="w", padx=4, pady=6)

        ttk.Label(sticks, text="Courbe / zone morte %").grid(row=3, column=0, sticky="w", padx=4, pady=6)
        self.mouse_curve_var, self.mouse_deadzone_var = tk.StringVar(), tk.StringVar()
        ttk.Combobox(sticks, textvariable=self.mouse_curve_var, state="readonly", width=16,
                     values=("Linéaire", "Précision", "Accélérée")).grid(
                         row=3, column=1, sticky="w", padx=4, pady=6)
        ttk.Spinbox(sticks, from_=0, to=50, textvariable=self.mouse_deadzone_var,
                    width=7).grid(row=3, column=2, sticky="w", padx=4, pady=6)
        ttk.Label(sticks, text="Lissage (ms)").grid(row=3, column=3, sticky="w", padx=4, pady=6)
        self.mouse_smoothing_var = tk.StringVar()
        ttk.Spinbox(sticks, from_=0, to=200, increment=5, textvariable=self.mouse_smoothing_var,
                    width=7).grid(row=3, column=4, sticky="w", padx=4, pady=6)

        ttk.Label(sticks, text="Préréglage visée").grid(row=4, column=0, sticky="w", padx=4, pady=6)
        self.aim_preset_var = tk.StringVar(value="Personnalisé")
        ttk.Combobox(sticks, textvariable=self.aim_preset_var, state="readonly", width=16,
                     values=("Précision", "Équilibré", "Rapide", "Personnalisé")).grid(
                         row=4, column=1, sticky="w", padx=4, pady=6)
        ttk.Button(sticks, text="Appliquer", command=self._apply_aim_preset).grid(
            row=4, column=2, sticky="w", padx=4, pady=6)

        settings = ttk.LabelFrame(tab, text="Réponse analogique", padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=6)
        for column in range(6):
            settings.columnconfigure(column, weight=1)
        self.curve_var = tk.StringVar()
        self.deadzone_var = tk.StringVar()
        self.anti_deadzone_var = tk.StringVar()
        self.threshold_var = tk.StringVar()
        self.poll_var = tk.StringVar()
        ttk.Label(settings, text="Courbe").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Combobox(settings, textvariable=self.curve_var, state="readonly",
                     values=("Linéaire", "Exponentielle", "Logarithmique")).grid(row=1, column=0, sticky="ew", padx=4)
        for column, (label, variable, high) in enumerate((
            ("Zone morte %", self.deadzone_var, 50), ("Anti-deadzone %", self.anti_deadzone_var, 50),
            ("Seuil bouton %", self.threshold_var, 100), ("Polling ms", self.poll_var, 20),
        ), 1):
            ttk.Label(settings, text=label).grid(row=0, column=column, sticky="w", padx=4)
            ttk.Spinbox(settings, from_=1 if label == "Seuil bouton %" else 0, to=high,
                        textvariable=variable, width=9).grid(row=1, column=column, sticky="ew", padx=4)
        ttk.Button(tab, text="Enregistrer la configuration", style="Accent.TButton",
                   command=self._save_profile).grid(row=3, column=0, sticky="e", pady=(12, 0))

    def _build_actions_tab(self) -> None:
        tab = self.action_tab
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.binding_tree = ttk.Treeview(tab, columns=("key", "type"), show="tree headings", selectmode="browse")
        self.binding_tree.heading("#0", text="ACTION MANETTE")
        self.binding_tree.heading("key", text="TOUCHE AFFECTÉE")
        self.binding_tree.heading("type", text="SOURCE")
        self.binding_tree.column("#0", width=420, minwidth=260)
        self.binding_tree.column("key", width=260, minwidth=180)
        self.binding_tree.column("type", width=180, minwidth=120)
        self.binding_tree.grid(row=0, column=0, sticky="nsew")
        self.binding_tree.tag_configure("stripe", background="#F8FAFC")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.binding_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.binding_tree.configure(yscrollcommand=scroll.set)
        controls = ttk.Frame(tab)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Button(controls, text="Affecter une touche", command=self._capture_binding).pack(side="left", padx=4)
        ttk.Button(controls, text="Effacer l’affectation", command=self._clear_binding).pack(side="left", padx=4)
        ttk.Label(controls, text="La touche reste bloquée pendant le jeu pour éviter une double action.").pack(
            side="right", padx=4)

    def _build_run_tab(self) -> None:
        tab = self.run_tab
        tab.columnconfigure(0, weight=1)
        ttk.Label(tab, text="Démarrage", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w", pady=8)
        ttk.Label(tab, text="En mode analogique, calibre les touches avant de jouer. Le test HID vérifie les rapports pendant que tu bouges les touches sélectionnées.",
                  wraplength=850).grid(row=1, column=0, sticky="w", pady=6)
        ttk.Label(tab, text="Pendant le jeu, la souris est capturée; appuie sur Échap pour la libérer. Le statut indique si elle est capturée ou libérée.",
                  wraplength=850).grid(row=2, column=0, sticky="w", pady=6)
        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="w", pady=12)
        self.start_button = ttk.Button(buttons, text="Démarrer la manette", style="Accent.TButton",
                                       command=self._start_runtime)
        self.start_button.pack(side="left", padx=4)
        self.stop_button = ttk.Button(buttons, text="Arrêter", command=self._stop_runtime, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        self.calibrate_button = ttk.Button(buttons, text="Calibrer les touches analogiques", command=self._start_calibration)
        self.calibrate_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Test HID automatique", command=self._start_diagnostic).pack(side="left", padx=4)
        ttk.Button(buttons, text="Annuler test/calibration", command=self.cancel_worker.set).pack(side="left", padx=4)
        ttk.Label(tab, text="Le test dure 8 secondes. Appuie et relâche les touches assignées; le programme indique pour chacune si sa valeur évolue réellement.",
                  wraplength=850).grid(row=4, column=0, sticky="w", pady=8)
        self.results = tk.Text(tab, height=16, wrap="word", state="disabled")
        self.results.grid(row=5, column=0, sticky="nsew", pady=8)
        tab.rowconfigure(5, weight=1)

    def _load_profile(self) -> None:
        profile = self.profile
        self.profile_var.set(self.profile_name)
        keyboard = profile["keyboard"]
        self.mode_var.set({"ace60": "MCHOSE ACE60", "standard": "Clavier standard",
                           "custom": "Autre clavier HID"}.get(keyboard.get("mode"), "MCHOSE ACE60"))
        self.vid_var.set(f"0x{int(keyboard.get('vid', DEFAULT_VID)):04X}")
        self.pid_var.set(f"0x{int(keyboard.get('pid', DEFAULT_PID)):04X}")
        self.protocol_var.set({"ace60": "ACE60 / protocole MCHOSE",
                               "wooting_sdk": "SDK analogique + plugins compatibles",
                               "sdk_provider": "SDK analogique + plugins compatibles"}.get(
                                   keyboard.get("protocol", "ace60"),
                                   "HID standard (détection automatique)"))
        self.sdk_library_var.set(str(keyboard.get("sdk_library", "")))
        self.sdk_provider_var.set(str(keyboard.get("sdk_provider", "wooting")))
        configured_providers = profile.get("sdk_providers", {})
        for provider_id, variable in self.sdk_provider_vars.items():
            variable.set(bool(configured_providers.get(provider_id, provider_id == "wooting")))
        sources = profile.get("stick_sources", {"left": "keyboard", "right": "keyboard"})
        self.left_source_var.set("Souris" if sources.get("left") == "mouse" else "Clavier")
        self.right_source_var.set("Souris" if sources.get("right") == "mouse" else "Clavier")
        self.sensitivity_x_var.set(str(profile.get("mouse_sensitivity_x", profile.get("mouse_sensitivity", 1.0))))
        self.sensitivity_y_var.set(str(profile.get("mouse_sensitivity_y", profile.get("mouse_sensitivity", 1.0))))
        self.mouse_return_var.set(str(profile.get("mouse_return_ms", 100)))
        self.mouse_curve_var.set({"linear": "Linéaire", "precision": "Précision",
                                  "accelerated": "Accélérée"}.get(profile.get("mouse_aim_curve"), "Linéaire"))
        self.mouse_deadzone_var.set(str(profile.get("mouse_deadzone", 0)))
        self.mouse_smoothing_var.set(str(profile.get("mouse_smoothing_ms", 0)))
        self.aim_preset_var.set("Personnalisé")
        self.layout_var.set(profile.get("layout", "QWERTY ANSI"))
        self.curve_var.set({"linear": "Linéaire", "exponential": "Exponentielle",
                            "logarithmic": "Logarithmique"}.get(profile.get("curve"), "Linéaire"))
        self.deadzone_var.set(str(profile.get("deadzone", 4)))
        self.anti_deadzone_var.set(str(profile.get("anti_deadzone", 0)))
        self.threshold_var.set(str(profile.get("button_on", 50)))
        self.poll_var.set(str(profile.get("poll_interval_ms", 1)))
        self._refresh_bindings()

    def _apply_aim_preset(self) -> None:
        presets = {
            "Précision": (0.6, 0.6, "Précision", 3, 70, 35),
            "Équilibré": (1.0, 1.0, "Linéaire", 0, 100, 0),
            "Rapide": (1.5, 1.5, "Accélérée", 0, 140, 0),
        }
        preset = presets.get(self.aim_preset_var.get())
        if preset is None:
            return
        sx, sy, curve, deadzone, return_ms, smoothing = preset
        self.sensitivity_x_var.set(str(sx))
        self.sensitivity_y_var.set(str(sy))
        self.mouse_curve_var.set(curve)
        self.mouse_deadzone_var.set(str(deadzone))
        self.mouse_return_var.set(str(return_ms))
        self.mouse_smoothing_var.set(str(smoothing))

    def _toggle_device_advanced(self) -> None:
        if self.advanced_device_frame.winfo_manager():
            self.advanced_device_frame.grid_remove()
            self.advanced_device_button.configure(text="Options manuelles")
        else:
            self.advanced_device_frame.grid()
            self.advanced_device_button.configure(text="Masquer les options manuelles")

    def _select_profile(self, _event: Any = None) -> None:
        selected = self.profile_var.get()
        if selected in self.config["profiles"]:
            self._save_profile(show_message=False)
            self.profile_name = selected
            self.config["active_profile"] = selected
            self._load_profile()

    def _new_profile(self) -> None:
        name = simpledialog.askstring("Nouveau profil", "Nom du profil :", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name or name in self.config["profiles"]:
            messagebox.showerror("Profil", "Nom vide ou déjà utilisé.", parent=self.root)
            return
        self._save_profile(show_message=False)
        self.config["profiles"][name] = copy.deepcopy(self.profile)
        self.profile_name = name
        self.config["active_profile"] = name
        self.profile_combo.configure(values=list(self.config["profiles"]))
        self._load_profile()
        self._save_profile(show_message=False)

    def _collect_fields(self) -> bool:
        profile = self.profile
        keyboard = profile["keyboard"]
        old_device_identity = (keyboard.get("mode"), keyboard.get("vid"), keyboard.get("pid"),
                               keyboard.get("protocol", "ace60"))
        old_layout = profile.get("layout")
        mode = self.mode_var.get()
        keyboard["mode"] = {"MCHOSE ACE60": "ace60", "Clavier standard": "standard",
                            "Autre clavier HID": "custom"}.get(mode, "ace60")
        try:
            keyboard["vid"] = int(self.vid_var.get().strip(), 0)
            keyboard["pid"] = int(self.pid_var.get().strip(), 0)
            sensitivity_x = float(self.sensitivity_x_var.get().replace(",", "."))
            sensitivity_y = float(self.sensitivity_y_var.get().replace(",", "."))
            mouse_return = int(self.mouse_return_var.get())
            mouse_deadzone = int(self.mouse_deadzone_var.get())
            mouse_smoothing = int(self.mouse_smoothing_var.get())
            deadzone = int(self.deadzone_var.get())
            anti_deadzone = int(self.anti_deadzone_var.get())
            button_on = int(self.threshold_var.get())
            poll = int(self.poll_var.get())
        except ValueError:
            messagebox.showerror("Réglages invalides", "Vérifie VID/PID et les réglages numériques.", parent=self.root)
            return False
        if not (0 <= keyboard["vid"] <= 0xFFFF and 0 <= keyboard["pid"] <= 0xFFFF
                and 0.1 <= sensitivity_x <= 20.0 and 0.1 <= sensitivity_y <= 20.0
                and 20 <= mouse_return <= 1000 and 0 <= mouse_deadzone <= 50
                and 0 <= mouse_smoothing <= 200 and 0 <= deadzone <= 50
                and 0 <= anti_deadzone <= 50 and 1 <= button_on <= 100 and 1 <= poll <= 20):
            messagebox.showerror("Réglages invalides", "Une valeur est hors de ses limites autorisées.", parent=self.root)
            return False
        protocol_labels = {"ACE60 / protocole MCHOSE": "ace60",
                           "SDK analogique + plugins compatibles": "wooting_sdk",
                           "HID standard (détection automatique)": "generic"}
        keyboard["protocol"] = protocol_labels.get(self.protocol_var.get(), "generic")
        keyboard["sdk_provider"] = self.sdk_provider_var.get().strip() or "wooting"
        keyboard["sdk_library"] = self.sdk_library_var.get().strip()
        profile["sdk_providers"] = {provider_id: bool(variable.get())
                                     for provider_id, variable in self.sdk_provider_vars.items()}
        if keyboard["protocol"] == "wooting_sdk" and keyboard["sdk_provider"] != "wooting":
            keyboard["protocol"] = "sdk_provider"
        if keyboard["protocol"] == "wooting_sdk" and not keyboard["sdk_library"]:
            messagebox.showerror("SDK analogique requis",
                                 "Sélectionne la bibliothèque Wooting Analog SDK avant d’enregistrer ce protocole.",
                                 parent=self.root)
            return False
        if keyboard["protocol"] == "sdk_provider":
            profile["sdk_providers"].setdefault(keyboard["sdk_provider"], True)
        new_device_identity = (keyboard["mode"], keyboard["vid"], keyboard["pid"], keyboard["protocol"])
        if new_device_identity != old_device_identity or self.layout_var.get() != old_layout:
            profile["calibration"].clear()
        profile["stick_sources"] = {"left": "mouse" if self.left_source_var.get() == "Souris" else "keyboard",
                                    "right": "mouse" if self.right_source_var.get() == "Souris" else "keyboard"}
        profile["mouse_joystick_enabled"] = profile["stick_sources"]["right"] == "mouse"
        profile["mouse_sensitivity_x"], profile["mouse_sensitivity_y"] = sensitivity_x, sensitivity_y
        profile["mouse_sensitivity"] = (sensitivity_x + sensitivity_y) / 2
        profile["mouse_return_ms"] = mouse_return
        profile["mouse_deadzone"], profile["mouse_smoothing_ms"] = mouse_deadzone, mouse_smoothing
        profile["mouse_aim_curve"] = {"Linéaire": "linear", "Précision": "precision",
                                      "Accélérée": "accelerated"}.get(self.mouse_curve_var.get(), "linear")
        profile["layout"] = self.layout_var.get()
        profile["curve"] = {"Linéaire": "linear", "Exponentielle": "exponential",
                            "Logarithmique": "logarithmic"}.get(self.curve_var.get(), "linear")
        profile["deadzone"], profile["anti_deadzone"] = deadzone, anti_deadzone
        profile["button_on"], profile["poll_interval_ms"] = button_on, poll
        return True

    def _browse_sdk_library(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Sélectionner la bibliothèque Wooting Analog SDK",
                                          filetypes=(("Bibliothèque Windows", "*.dll"), ("Tous les fichiers", "*.*")))
        if path:
            self.sdk_library_var.set(path)

    def _save_profile(self, show_message: bool = True) -> None:
        if not self._collect_fields():
            return
        self.config["active_profile"] = self.profile_name
        try:
            save_config(self.config)
            if show_message:
                self.status_var.set("Configuration enregistrée.")
        except OSError as exc:
            messagebox.showerror("Enregistrement impossible", str(exc), parent=self.root)

    def _refresh_bindings(self) -> None:
        for item in self.binding_tree.get_children():
            self.binding_tree.delete(item)
        bindings = self.profile.get("bindings", {})
        for index, action in enumerate(ACTION_IDS):
            binding = bindings.get(action)
            key = binding.get("name", "—") if binding else "—"
            scan = int(binding.get("scan", 0)) if binding else 0
            layout = self.layouts.get(self.layout_var.get(), {}).get("scan_to_hid", {})
            kind = "Analogique HID" if self.mode_var.get() != "Clavier standard" and str(scan) in layout else (
                "Numérique" if binding else "—")
            self.binding_tree.insert("", "end", iid=action, text=self.action_labels.get(action, action),
                                     values=(key, kind), tags=("stripe",) if index % 2 else ())

    def _scan_devices(self) -> None:
        try:
            import hid
            devices = hid.enumerate()
        except (ImportError, OSError) as exc:
            messagebox.showerror("Détection HID", str(exc), parent=self.root)
            return
        self.device_choices.clear()
        detected: list[tuple[bool, str, dict[str, Any]]] = []
        for item in devices:
            vid, pid = int(item.get("vendor_id", 0)), int(item.get("product_id", 0))
            if not vid or not pid:
                continue
            name = " ".join(filter(None, (item.get("manufacturer_string"), item.get("product_string"))))
            protocol = probe_keyboard_interface(item)
            support = {"ace60": "ACE60 pris en charge", "generic": "HID analogique standard pris en charge"}.get(
                protocol, "Aucune entrée analogique standard détectée")
            label = f"{name or 'Périphérique HID'} — {support} — {vid:04X}:{pid:04X}"
            if label in self.device_choices:
                continue
            item["_analog_protocol"] = protocol
            self.device_choices[label] = item
            detected.append((protocol in ("ace60", "generic"), label, item))
        sdk_error = None
        sdk_path = self.sdk_library_var.get().strip()
        if sdk_path:
            try:
                for sdk_device in WootingAnalogSDK.list_devices(sdk_path):
                    item = {"vendor_id": sdk_device["vendor_id"], "product_id": sdk_device["product_id"],
                            "manufacturer_string": sdk_device["manufacturer"],
                            "product_string": sdk_device["name"], "_analog_protocol": "wooting_sdk",
                            "_sdk_device_id": sdk_device["device_id"]}
                    label = (f"{sdk_device['manufacturer']} {sdk_device['name']} — SDK/plugin analogique "
                             f"— {item['vendor_id']:04X}:{item['product_id']:04X}")
                    self.device_choices[label] = item
                    detected.append((True, label, item))
            except (OSError, RuntimeError) as exc:
                sdk_error = str(exc)
        detected.sort(key=lambda record: (not record[0], record[1].casefold()))
        labels = [label for _supported, label, _item in detected]
        self.device_combo.configure(values=labels)
        supported = [record for record in detected if record[0]]
        if supported:
            self.device_var.set(supported[0][1])
            self._choose_detected_device()
            unsupported_count = len(detected) - len(supported)
            self.status_var.set(f"{len(supported)} clavier(s) analogique(s) compatible(s) détecté(s).")
            if sdk_error:
                self.device_support_var.set(f"Détection HID terminée. SDK/plugin : {sdk_error}")
            elif not sdk_path:
                self.device_support_var.set(
                    "Détection HID terminée. Pour Wooting, Razer Huntsman analogiques, DrunkDeer, "
                    "NuPhy ou certains Keychron HE, sélectionne la DLL SDK et installe le plugin compatible.")
            if unsupported_count:
                self.device_support_var.set(
                    f"{len(supported)} compatible(s). Les autres appareils demandent un protocole ou SDK fabricant.")
        elif labels:
            self.device_var.set(labels[0])
            self._choose_detected_device()
            self.status_var.set("Aucun clavier analogique pris en charge détecté.")
        else:
            self.device_var.set("")
            self.device_support_var.set("Aucun périphérique HID détecté. Vérifie le branchement puis réessaie.")
            self.status_var.set("Aucun périphérique HID détecté.")

    def _choose_detected_device(self, _event: Any = None) -> None:
        item = self.device_choices.get(self.device_var.get())
        if item:
            self.vid_var.set(f"0x{int(item['vendor_id']):04X}")
            self.pid_var.set(f"0x{int(item['product_id']):04X}")
            protocol = item.get("_analog_protocol", "unsupported")
            if protocol == "ace60":
                self.mode_var.set("MCHOSE ACE60")
                self.protocol_var.set("ACE60 / protocole MCHOSE")
                self.device_support_var.set("Compatible : protocole analogique ACE60 détecté automatiquement.")
            elif protocol == "generic":
                self.mode_var.set("Autre clavier HID")
                self.protocol_var.set("HID standard (détection automatique)")
                self.device_support_var.set(
                    "Compatible : le descripteur USB expose des valeurs analogiques HID standards.")
            elif protocol == "wooting_sdk":
                self.mode_var.set("Autre clavier HID")
                self.protocol_var.set("SDK analogique + plugins compatibles")
                self.sdk_provider_var.set("wooting")
                self.profile["keyboard"]["sdk_device_id"] = int(item["_sdk_device_id"])
                self.device_support_var.set(
                    "Compatible via le SDK/plugin analogique. La prise en charge réelle dépend du modèle, "
                    "du firmware et des logiciels fabricant requis.")
            else:
                self.mode_var.set("Autre clavier HID")
                self.protocol_var.set("HID standard (détection automatique)")
                self.device_support_var.set(
                    "Non pris en charge automatiquement. Il faut un adaptateur ou SDK documenté par la marque.")
            if protocol == "wooting_sdk":
                self.sdk_library_var.set(self.profile["keyboard"].get("sdk_library", ""))
            self._refresh_bindings()

    def _capture_binding(self) -> None:
        selected = self.binding_tree.selection()
        if not selected:
            messagebox.showinfo("Affecter une touche", "Sélectionne d’abord une action.", parent=self.root)
            return
        action = selected[0]
        self.status_var.set(f"Appuie puis relâche la touche à affecter à « {self.action_labels[action]} »…")
        self.cancel_worker.clear()
        self.worker = threading.Thread(target=self._capture_key_worker, args=(action,), daemon=True)
        self.worker.start()

    def _capture_key_worker(self, action: str) -> None:
        try:
            import keyboard
            pressed = threading.Event()
            selected: list[Any] = []
            def callback(event: Any) -> None:
                if event.event_type == "down" and not pressed.is_set():
                    if int(event.scan_code) == ESCAPE_SCAN:
                        selected.append(None)
                    elif int(event.scan_code) in (EXIT_SCAN, MOUSE_TOGGLE_SCAN):
                        self.events.put(("status", "F9 et F12 sont réservées aux commandes de l'application."))
                        return
                    else:
                        selected.append((int(event.scan_code), str(event.name or "touche")))
                    pressed.set()
            remove = keyboard.hook(callback, suppress=False)
            try:
                if not pressed.wait(20.0):
                    self.events.put(("status", "Délai dépassé; affectation annulée."))
                elif selected[0] is not None:
                    self.events.put(("binding", (action, *selected[0])))
                else:
                    self.events.put(("status", "Affectation annulée avec Échap."))
            finally:
                remove()
        except (ImportError, OSError) as exc:
            self.events.put(("error", f"Capture clavier impossible : {exc}"))

    def _clear_binding(self) -> None:
        selected = self.binding_tree.selection()
        if not selected:
            return
        self.profile["bindings"].pop(selected[0], None)
        self.profile["calibration"].clear()
        self._refresh_bindings()
        self._save_profile(show_message=False)

    def _scan_mapping(self) -> dict[int, int]:
        return {int(scan): int(usage) for scan, usage in
                self.layouts[self.profile["layout"]]["scan_to_hid"].items()}

    def _analog_scans(self) -> list[int]:
        mapping = self._scan_mapping()
        scans = {int(binding["scan"]) for binding in self.profile["bindings"].values()}
        scans.update(int(binding["alternate"]["scan"]) for binding in self.profile["bindings"].values()
                     if binding.get("alternate"))
        return sorted(scans.intersection(mapping))

    def _start_runtime(self) -> None:
        if self.runtime is not None and self.runtime.thread.is_alive():
            return
        if self._selected_device_is_unsupported():
            messagebox.showinfo(
                "Clavier non pris en charge",
                "Aucun flux analogique compatible n’a été détecté pour cet appareil. "
                "Il faut un adaptateur officiel ou un SDK de son fabricant.",
                parent=self.root,
            )
            return
        self._save_profile(show_message=False)
        if not self.profile["bindings"]:
            messagebox.showwarning("Touches manquantes", "Affecte au moins une touche de manette.", parent=self.root)
            return
        keyboard = self.profile["keyboard"]
        if keyboard.get("mode") is None:
            messagebox.showwarning("Clavier manquant", "Choisis un mode de clavier.", parent=self.root)
            return
        missing = [scan for scan in self._analog_scans() if str(scan) not in self.profile["calibration"]]
        if (keyboard.get("mode") in ("ace60", "custom") and
                keyboard.get("protocol") not in ("wooting_sdk", "sdk_provider") and missing):
            if messagebox.askyesno("Calibration nécessaire", "Certaines touches analogiques ne sont pas calibrées. Les calibrer maintenant ?",
                                   parent=self.root):
                self._start_calibration(then_start=True)
                return
        self._launch_runtime()

    def _launch_runtime(self) -> None:
        def status(text: str) -> None:
            self.events.put(("status", text))
        self.runtime = GamepadRuntime(self.profile, self._scan_mapping(), status, self.profile_name)
        self.runtime.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("Démarrage du runtime…")

    def _stop_runtime(self) -> None:
        if self.runtime:
            self.runtime.stop()
            self.status_var.set("Arrêt demandé…")

    def _start_calibration(self, then_start: bool = False) -> None:
        if self._selected_device_is_unsupported():
            messagebox.showinfo(
                "Clavier non pris en charge",
                "La calibration est impossible tant qu’un flux analogique compatible n’est pas détecté.",
                parent=self.root,
            )
            return
        self._save_profile(show_message=False)
        if self.runtime is not None and self.runtime.thread.is_alive():
            messagebox.showinfo("Calibration", "Arrête la manette avant de calibrer le clavier HID.", parent=self.root)
            return
        if self.profile["keyboard"].get("mode") not in ("ace60", "custom"):
            messagebox.showinfo("Calibration", "La calibration nécessite un clavier analogique.", parent=self.root)
            return
        if self.profile["keyboard"].get("protocol") in ("wooting_sdk", "sdk_provider"):
            self.status_var.set("Le SDK fournit déjà les valeurs normalisées; aucune calibration n’est nécessaire.")
            if then_start:
                self._launch_runtime()
            return
        scans = self._analog_scans()
        if not scans:
            messagebox.showinfo("Calibration", "Aucune touche analogique affectée pour cette disposition.", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            return
        self.cancel_worker.clear()
        self.calibrate_button.configure(state="disabled")
        self.status_var.set("Calibration : déplace chaque touche sur toute sa course, puis laisse-la se stabiliser.")
        self.worker = threading.Thread(target=self._calibration_worker, args=(scans, then_start), daemon=True)
        self.worker.start()

    def _calibration_worker(self, scans: list[int], then_start: bool) -> None:
        device = None
        original = None
        changed = False
        try:
            kb = self.profile["keyboard"]
            if kb.get("protocol", "ace60") == "generic":
                device, descriptor = open_generic_device(int(kb["vid"]), int(kb["pid"]))
            else:
                device = open_device(int(kb["vid"]), int(kb["pid"]))
                original, changed = enable_debug(device)
                descriptor = None
            mapping = self._scan_mapping()
            for scan in scans:
                if self.cancel_worker.is_set():
                    break
                label = next((binding["name"] for binding in self.profile["bindings"].values()
                              if int(binding["scan"]) == scan), f"scan {scan}")
                self.events.put(("status", f"Calibration de {label} — bouge la touche sur toute sa course…"))
                low, high, initial, last = 65535, 0, None, None
                stable_since = time.monotonic()
                deadline = time.monotonic() + 30.0
                count = 0
                while time.monotonic() < deadline and not self.cancel_worker.is_set():
                    report = read_report(device, timeout_ms=25)
                    if not report:
                        continue
                    raw = descriptor.read_values(report).get(mapping[scan]) if descriptor else get_raw_value(report)[1]
                    if raw is None:
                        continue
                    count += 1
                    initial = raw if initial is None else initial
                    low, high = min(low, raw), max(high, raw)
                    now = time.monotonic()
                    if last is None or abs(raw - last) >= 8:
                        stable_since, last = now, raw
                    if high - low >= 100 and now - stable_since >= 1.2:
                        break
                if count >= 3 and high - low >= 100:
                    if descriptor is not None and initial is not None:
                        released, pressed = ((low, high) if abs(initial - low) <= abs(initial - high)
                                             else (high, low))
                    else:
                        released, pressed = high, low
                    self.profile["calibration"][str(scan)] = [released, pressed]
                    self.events.put(("status", f"{label} calibrée — repos {released}, enfoncée {pressed}."))
                else:
                    self.events.put(("status", f"Plage trop faible pour {label} ({high-low}); touche ignorée."))
            self.events.put(("calibration_done", then_start))
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            LOGGER.exception("Calibration graphique échouée")
            self.events.put(("error", f"Calibration impossible : {exc}"))
        finally:
            if device is not None:
                try:
                    restore_config(device, original, changed)
                except (OSError, RuntimeError):
                    LOGGER.exception("Restauration HID après calibration graphique échouée")
                try:
                    device.close()
                except (OSError, RuntimeError):
                    LOGGER.warning("Fermeture HID après calibration graphique échouée", exc_info=True)

    def _start_diagnostic(self) -> None:
        if self._selected_device_is_unsupported():
            messagebox.showinfo(
                "Clavier non pris en charge",
                "Le test analogique ne peut pas lire cet appareil sans adaptateur ou SDK fabricant.",
                parent=self.root,
            )
            return
        self._save_profile(show_message=False)
        if self.runtime is not None and self.runtime.thread.is_alive():
            messagebox.showinfo("Test HID", "Arrête la manette avant de tester le clavier HID.", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            return
        kb = self.profile["keyboard"]
        if kb.get("mode") not in ("ace60", "custom"):
            messagebox.showinfo("Test HID", "Choisis un clavier analogique avant le test.", parent=self.root)
            return
        self.cancel_worker.clear()
        self.worker = threading.Thread(target=self._diagnostic_worker, daemon=True)
        self.worker.start()
        self.status_var.set("Test HID en cours. Appuie et relâche les touches assignées pendant 8 secondes…")

    def _selected_device_is_unsupported(self) -> bool:
        item = self.device_choices.get(self.device_var.get())
        return bool(item and item.get("_analog_protocol") == "unsupported")

    def _diagnostic_worker(self) -> None:
        device = None
        original = None
        changed = False
        try:
            kb = self.profile["keyboard"]
            sdk_mode = kb.get("protocol") == "wooting_sdk"
            if kb.get("protocol") == "sdk_provider":
                self.events.put(("error", "Le test HID intégré n’interroge que le Wooting SDK; "
                                           "le provider sélectionné peut être testé par son plugin."))
                return
            generic = kb.get("protocol", "ace60") == "generic"
            if sdk_mode:
                device = WootingAnalogSDK(str(kb.get("sdk_library", "")), kb.get("sdk_device_id"))
                descriptor = None
            elif generic:
                device, descriptor = open_generic_device(int(kb["vid"]), int(kb["pid"]))
            else:
                device = open_device(int(kb["vid"]), int(kb["pid"]))
                original, changed = enable_debug(device)
                descriptor = None
            mapping = self._scan_mapping()
            scans = self._analog_scans()
            observed: dict[int, list[int]] = {scan: [] for scan in scans}
            deadline = time.monotonic() + DIAGNOSTIC_SECONDS
            reports = 0
            while time.monotonic() < deadline and not self.cancel_worker.is_set():
                if sdk_mode:
                    by_usage = {usage: round(value * 65535) for usage, value in device.read_values().items()}
                    reports += 1
                else:
                    report = read_report(device, timeout_ms=50)
                    if not report:
                        continue
                    reports += 1
                    if descriptor:
                        by_usage = descriptor.read_values(report)
                    else:
                        index, raw = get_raw_value(report)
                        by_usage = {index: raw} if index is not None and raw is not None else {}
                for scan in scans:
                    raw = by_usage.get(mapping[scan])
                    if raw is not None:
                        observed[scan].append(raw)
            lines = [f"Rapports reçus : {reports}"]
            for scan in scans:
                samples = observed[scan]
                label = next((binding["name"] for binding in self.profile["bindings"].values()
                              if int(binding["scan"]) == scan), f"scan {scan}")
                if samples:
                    span = max(samples) - min(samples)
                    result = "variation analogique détectée" if span >= 8 else "rapport reçu, mais valeur presque fixe"
                    lines.append(f"{label} : {result} (plage {span}; {len(samples)} mesures)")
                else:
                    lines.append(f"{label} : aucun rapport correspondant")
            self.events.put(("diagnostic", "\n".join(lines)))
        except (ImportError, RuntimeError, OSError, ValueError) as exc:
            LOGGER.exception("Diagnostic HID graphique échoué")
            self.events.put(("error", f"Test HID impossible : {exc}"))
        finally:
            if device is not None:
                try:
                    if kb.get("protocol") not in ("wooting_sdk", "sdk_provider"):
                        restore_config(device, original, changed)
                except (OSError, RuntimeError):
                    LOGGER.exception("Restauration HID après diagnostic échouée")
                try:
                    device.close()
                except (OSError, RuntimeError):
                    LOGGER.warning("Fermeture HID après diagnostic échouée", exc_info=True)

    def _append_results(self, text: str) -> None:
        self.results.configure(state="normal")
        self.results.delete("1.0", "end")
        self.results.insert("end", text)
        self.results.configure(state="disabled")

    def _poll_events(self) -> None:
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status_var.set(value)
            elif kind == "binding":
                action, scan, name = value
                self.profile["bindings"][action] = {"scan": scan, "name": name}
                self.profile["calibration"].pop(str(scan), None)
                self._refresh_bindings()
                self._save_profile(show_message=False)
                self.status_var.set(f"Touche « {name} » affectée à {self.action_labels[action]}.")
            elif kind == "calibration_done":
                self._save_profile(show_message=False)
                self.calibrate_button.configure(state="normal")
                if value:
                    self._launch_runtime()
            elif kind == "diagnostic":
                self._append_results(value)
                self.status_var.set("Test HID terminé.")
            elif kind == "error":
                self.status_var.set(value)
                self.calibrate_button.configure(state="normal")
                messagebox.showerror("Erreur", value, parent=self.root)
        if self.runtime and not self.runtime.thread.is_alive():
            self.runtime = None
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        self.root.after(100, self._poll_events)


def run_gui() -> None:
    root = tk.Tk()
    GamepadGUI(root)
    root.mainloop()
