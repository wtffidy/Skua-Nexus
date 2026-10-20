#!/usr/bin/env python3
"""Dark, site-matched Windows companion for the Skua Dashboard."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser

try:
    import pystray
except ImportError:
    pystray = None
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None
from urllib.error import URLError
from urllib.request import urlopen

FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "SkuaDashboard"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", HERE)) if FROZEN else HERE
URL = "http://127.0.0.1:8787/"
RELAY = HERE / ("SkuaRelay.exe" if FROZEN else "relay.py")
ICON = RESOURCE_DIR / "SkuaIcon.ico"

BG = "#080D16"
CARD = "#101A29"
INNER = "#142237"
LINE = "#263B53"
FG = "#E6F2FF"
MUTED = "#8297B2"
ACCENT = "#55E7FF"
GREEN = "#3CE6A0"
AMBER = "#FFCA67"
RED = "#FF5478"


class DashboardApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Skua Nexus | Manager")
        if ICON.is_file():
            try:
                self.iconbitmap(default=str(ICON))
            except tk.TclError:
                pass
        self.geometry("760x640")
        self.minsize(660, 560)
        self.configure(bg=BG)
        self.process: subprocess.Popen | None = None
        self.relay_log_handle = None
        self.relay_log_path = APP_DATA / "relay.log"
        self.ui_settings_path = APP_DATA / "ui-settings.json"
        self.ui_settings = self._load_ui_settings()
        self._background_original = None
        self._background_photo = None
        self._background_label = None
        self._background_path = str(self.ui_settings.get("background_image", ""))
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.tray_icon = None
        self.tray_thread = None

        self._build_ui()
        self._apply_opacity()
        self.attributes("-topmost", bool(self.ui_settings.get("always_on_top", False)))
        self._load_background_image()
        self.bind("<Configure>", self._on_window_resize, add="+")
        self.log_message("Ready. Settings and bot data are stored in your AppData folder.")
        self.after(250, self.drain_messages)
        self.after(500, self.check_status)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Unmap>", self._on_window_unmap, add="+")

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=(20, 14))

        logo = tk.Label(header, text="V", bg=ACCENT, fg="#07121B",
                        font=("Segoe UI", 14, "bold"), width=2, height=1,
                        highlightthickness=1, highlightbackground="#8AF2FF")
        logo.pack(side="left", padx=(0, 10))
        title_area = tk.Frame(header, bg=BG)
        title_area.pack(side="left", fill="x", expand=True)
        tk.Label(title_area, text="SKUA NEXUS", bg=BG, fg=FG,
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(title_area, text="OPERATIONS CONTROL  /  LOCAL NODE", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(2, 0))
        tk.Label(header, text="●", bg=BG, fg=GREEN, font=("Segoe UI", 12)).pack(side="right", padx=(8, 0))
        tk.Label(header, text="LOCAL NODE", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="right")

        self._separator()

        appearance_row = tk.Frame(self, bg=BG)
        appearance_row.pack(fill="x", padx=22, pady=(8, 0))
        tk.Label(appearance_row, text="PERSONALIZE YOUR NODE", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        self._button(appearance_row, "Appearance", self.open_appearance_settings).pack(side="right")

        status_card = tk.Frame(self, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        status_card.pack(fill="x", padx=22, pady=(16, 12))
        status_inner = tk.Frame(status_card, bg=CARD)
        status_inner.pack(fill="x", padx=15, pady=13)
        self.status_dot = tk.Label(status_inner, text="●", bg=CARD, fg=AMBER, font=("Segoe UI", 13))
        self.status_dot.pack(side="left", padx=(0, 9))
        status_text = tk.Frame(status_inner, bg=CARD)
        status_text.pack(side="left", fill="x", expand=True)
        tk.Label(status_text, text="Relay status", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w")
        self.status = tk.Label(status_text, text="Checking local relay…", bg=CARD, fg=FG,
                               font=("Segoe UI", 11, "bold"))
        self.status.pack(anchor="w", pady=(2, 0))
        tk.Label(status_inner, text=URL, bg=CARD, fg=MUTED,
                 font=("Consolas", 9)).pack(side="right")

        tk.Label(self, text="CONTROL DECK  /  QUICK ACTIONS", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(8, 7))
        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=22)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self._button(actions, "Open / Reload Dashboard", self.open_dashboard, primary=True).grid(
            row=0, column=0, sticky="ew", padx=(0, 6), pady=5)
        self._button(actions, "Restart Relay", self.restart_relay).grid(
            row=0, column=1, sticky="ew", padx=(6, 0), pady=5)
        self._button(actions, "Check for Updates" if FROZEN else "Fetch Latest Git Updates", self.pull_updates, primary=True).grid(
            row=1, column=0, sticky="ew", padx=(0, 6), pady=5)
        self._button(actions, "Open Repository Folder", self.open_folder).grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=5)

        log_header = tk.Frame(self, bg=BG)
        log_header.pack(fill="x", padx=24, pady=(16, 7))
        tk.Label(log_header, text="SYSTEM TELEMETRY", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        log_actions = tk.Frame(log_header, bg=BG)
        log_actions.pack(side="right")
        self._button(log_actions, "Open Relay Log", self.open_relay_log).pack(side="right", padx=(6, 0))
        self._button(log_actions, "Clear", self.clear_log).pack(side="right")

        log_card = tk.Frame(self, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        log_card.pack(fill="both", expand=True, padx=22, pady=(0, 20))
        self.log = tk.Text(log_card, height=9, bg=CARD, fg=FG, insertbackground=FG,
                           selectbackground=ACCENT, relief="flat", wrap="word",
                           font=("Consolas", 9), padx=12, pady=11, state="disabled",
                           borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("error", foreground=RED)

    def _load_ui_settings(self) -> dict[str, object]:
        try:
            if self.ui_settings_path.is_file():
                data = json.loads(self.ui_settings_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"opacity": 100, "background_image": ""}

    def _save_ui_settings(self) -> None:
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            self.ui_settings_path.write_text(json.dumps(self.ui_settings, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log_message(f"Could not save appearance settings: {exc}")

    def _apply_opacity(self) -> None:
        try:
            opacity = max(60, min(100, int(self.ui_settings.get("opacity", 100))))
            self.attributes("-alpha", opacity / 100)
        except (tk.TclError, TypeError, ValueError):
            pass

    def _load_background_image(self) -> None:
        if not self._background_path:
            return
        if Image is None or ImageTk is None:
            self.log_message("Custom backgrounds require Pillow. Rebuild with the updated build script or install Pillow.")
            return
        try:
            with Image.open(self._background_path) as source:
                self._background_original = source.convert("RGB")
            if self._background_label is None:
                self._background_label = tk.Label(self, bd=0, highlightthickness=0)
                self._background_label.place(x=0, y=0, relwidth=1, relheight=1)
                self._background_label.lower()
            self._render_background_image()
        except (OSError, ValueError) as exc:
            self.log_message(f"Could not load background image: {exc}")

    def _render_background_image(self) -> None:
        if self._background_original is None or self._background_label is None:
            return
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        resized = self._background_original.resize((width, height), Image.Resampling.LANCZOS)
        self._background_photo = ImageTk.PhotoImage(resized)
        self._background_label.configure(image=self._background_photo)
        self._background_label.lower()

    def _on_window_resize(self, event: tk.Event) -> None:
        if event.widget is self and self._background_original is not None:
            self._render_background_image()

    def open_appearance_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Skua Nexus | Appearance")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("470x370")
        tk.Label(dialog, text="APPEARANCE SETTINGS", bg=BG, fg=ACCENT, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(dialog, text="Choose a custom background image and adjust window opacity.", bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=420, justify="left").pack(anchor="w", padx=20, pady=(0, 12))
        image_row = tk.Frame(dialog, bg=BG)
        image_row.pack(fill="x", padx=20)
        tk.Label(image_row, text="Background image", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.background_path_label = tk.Label(image_row, text=Path(self._background_path).name if self._background_path else "None selected", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="e")
        self.background_path_label.pack(side="right", fill="x", expand=True, padx=(8, 0))
        image_buttons = tk.Frame(dialog, bg=BG)
        image_buttons.pack(fill="x", padx=20, pady=(8, 14))
        self._button(image_buttons, "Choose Image...", lambda: self._choose_background(dialog), primary=True).pack(side="left")
        self._button(image_buttons, "Remove Image", lambda: self._clear_background(dialog)).pack(side="left", padx=(8, 0))
        opacity_row = tk.Frame(dialog, bg=BG)
        opacity_row.pack(fill="x", padx=20)
        tk.Label(opacity_row, text="Window opacity", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).pack(side="left")
        opacity_value = tk.Label(opacity_row, text=f"{int(self.ui_settings.get("opacity", 100))}%", bg=BG, fg=ACCENT, font=("Segoe UI", 9, "bold"))
        opacity_value.pack(side="right")
        opacity_var = tk.IntVar(value=int(self.ui_settings.get("opacity", 100)))
        def update_opacity(value: str) -> None:
            opacity = max(60, min(100, int(float(value))))
            opacity_value.configure(text=f"{opacity}%")
            self.ui_settings["opacity"] = opacity
            self._apply_opacity()
        tk.Scale(dialog, from_=60, to=100, orient="horizontal", resolution=1, variable=opacity_var, command=update_opacity, showvalue=False, bg=BG, fg=FG, troughcolor=INNER, activebackground=ACCENT, highlightthickness=0, bd=0, length=420).pack(fill="x", padx=20, pady=(0, 10))
        always_on_top_var = tk.BooleanVar(value=bool(self.ui_settings.get("always_on_top", False)))
        tk.Checkbutton(dialog, text="Keep manager above other windows", variable=always_on_top_var, command=lambda: self._set_always_on_top(always_on_top_var.get()), bg=BG, fg=FG, selectcolor=INNER, activebackground=BG, activeforeground=FG, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 4))
        minimize_to_tray_var = tk.BooleanVar(value=bool(self.ui_settings.get("minimize_to_tray", False)))
        tk.Checkbutton(dialog, text="Minimize to system tray", variable=minimize_to_tray_var, bg=BG, fg=FG, selectcolor=INNER, activebackground=BG, activeforeground=FG, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 4))
        self._appearance_tray_var = minimize_to_tray_var
        open_dashboard_var = tk.BooleanVar(value=bool(self.ui_settings.get("open_dashboard_on_startup", False)))
        tk.Checkbutton(dialog, text="Open dashboard in browser when manager starts", variable=open_dashboard_var, command=lambda: self.ui_settings.__setitem__("open_dashboard_on_startup", open_dashboard_var.get()), bg=BG, fg=FG, selectcolor=INNER, activebackground=BG, activeforeground=FG, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 8))
        self._appearance_topmost_var = always_on_top_var
        self._appearance_dashboard_var = open_dashboard_var
        footer = tk.Frame(dialog, bg=BG)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        self._button(footer, "Save", lambda: self._save_appearance(dialog), primary=True).pack(side="right")
        self._button(footer, "Close", lambda: self._cancel_appearance(dialog)).pack(side="right", padx=(0, 8))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._cancel_appearance(dialog))

    def _choose_background(self, dialog: tk.Toplevel) -> None:
        if Image is None or ImageTk is None:
            messagebox.showerror("Image support unavailable", "Custom backgrounds need Pillow. Install it with python -m pip install Pillow, then restart the manager.", parent=dialog)
            return
        path = filedialog.askopenfilename(parent=dialog, title="Choose a background image", filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")])
        if not path:
            return
        self._background_path = path
        self.ui_settings["background_image"] = path
        self.background_path_label.configure(text=Path(path).name)
        self._background_original = None
        self._load_background_image()

    def _clear_background(self, dialog: tk.Toplevel) -> None:
        self._background_path = ""
        self.ui_settings["background_image"] = ""
        self._background_original = None
        self._background_photo = None
        if self._background_label is not None:
            self._background_label.configure(image="")
            self._background_label.lower()
        self.background_path_label.configure(text="None selected")

    def _set_always_on_top(self, enabled: bool) -> None:
        self.ui_settings["always_on_top"] = enabled
        self.attributes("-topmost", enabled)

    def _save_appearance(self, dialog: tk.Toplevel) -> None:
        self.ui_settings["always_on_top"] = self._appearance_topmost_var.get()
        self.ui_settings["open_dashboard_on_startup"] = self._appearance_dashboard_var.get()
        self.ui_settings["minimize_to_tray"] = self._appearance_tray_var.get()
        self._save_ui_settings()
        self.log_message("Appearance settings saved.")
        dialog.grab_release()
        dialog.destroy()

    def _cancel_appearance(self, dialog: tk.Toplevel) -> None:
        self.ui_settings["always_on_top"] = self._appearance_topmost_var.get()
        self.ui_settings["open_dashboard_on_startup"] = self._appearance_dashboard_var.get()
        self.ui_settings["minimize_to_tray"] = self._appearance_tray_var.get()
        self._save_ui_settings()
        dialog.grab_release()
        dialog.destroy()

    def _separator(self) -> None:
        tk.Frame(self, bg=LINE, height=1).pack(fill="x")

    def _button(self, parent: tk.Widget, text: str, command, primary: bool = False) -> tk.Button:
        background = ACCENT if primary else INNER
        active = "#9588ff" if primary else "#292d38"
        button = tk.Button(
            parent, text=text, command=command, bg=background, fg="#ffffff" if primary else FG,
            activebackground=active, activeforeground="#ffffff", relief="flat",
            highlightthickness=1, highlightbackground=ACCENT if primary else LINE,
            highlightcolor=ACCENT, bd=0, padx=12, pady=11,
            font=("Segoe UI", 10, "bold" if primary else "normal"), cursor="hand2"
        )
        return button

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log_message("Log view cleared. The relay log file was not deleted.")

    def open_relay_log(self) -> None:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        if not self.relay_log_path.exists():
            self.relay_log_path.touch()
        try:
            if sys.platform == "win32":
                os.startfile(str(self.relay_log_path))
            else:
                webbrowser.open(self.relay_log_path.as_uri())
            self.log_message(f"Opened relay log: {self.relay_log_path}")
        except OSError as exc:
            messagebox.showerror("Could not open relay log", str(exc))
    def log_message(self, message: str) -> None:
        self.log.configure(state="normal")
        tag = "error" if "failed" in message.lower() or "error" in message.lower() else (
            "ok" if "online" in message.lower() or "started" in message.lower() else "")
        self.log.insert("end", message.rstrip() + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def worker(self, title: str, action) -> None:
        if self.busy:
            self.log_message("Please wait for the current operation to finish.")
            return
        self.busy = True

        def run() -> None:
            try:
                result = action()
                self.messages.put(("log", f"{title}: {result}"))
            except Exception as exc:
                self.messages.put(("error", f"{title} failed: {exc}"))
            finally:
                self.messages.put(("busy", ""))
        threading.Thread(target=run, daemon=True).start()

    def drain_messages(self) -> None:
        try:
            while True:
                kind, message = self.messages.get_nowait()
                if kind == "busy":
                    self.busy = False
                elif kind == "restart_after_update":
                    self.stop_relay()
                    self.start_relay()
                else:
                    self.log_message(message)
                    if kind == "error":
                        self.status.configure(text="Action failed", fg=RED)
        except queue.Empty:
            pass
        self.after(250, self.drain_messages)

    def relay_responds(self) -> bool:
        try:
            with urlopen(URL, timeout=1.5) as response:
                return response.status == 200
        except (URLError, TimeoutError, OSError):
            return False

    def check_status(self) -> None:
        alive = self.relay_responds()
        self.status_dot.configure(fg=GREEN if alive else AMBER)
        self.status.configure(text="Relay online" if alive else "Relay not responding", fg=GREEN if alive else AMBER)
        self.after(5000, self.check_status)

    def open_dashboard_when_ready(self, attempt: int = 0) -> None:
        if self.relay_responds():
            webbrowser.open(URL, new=0, autoraise=True)
            self.log_message("Opened dashboard automatically after relay became available.")
            return
        if attempt >= 30:
            self.log_message("Dashboard auto-open skipped because the relay did not become ready in 15 seconds.")
            return
        self.after(500, lambda: self.open_dashboard_when_ready(attempt + 1))
    def open_dashboard(self) -> None:
        if not self.relay_responds():
            if not messagebox.askyesno("Relay is offline", "The local relay is not responding. Start it now?"):
                return
            self.start_relay()
        webbrowser.open(URL, new=0, autoraise=True)
        self.log_message("Opened dashboard in your default browser.")

    def start_relay(self) -> None:
        if self.process and self.process.poll() is None:
            self.log_message("Relay process is already running.")
            return
        if not RELAY.exists():
            messagebox.showerror("Missing file", f"Could not find the relay at:\n{RELAY}")
            return
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            APP_DATA.mkdir(parents=True, exist_ok=True)
            self.relay_log_handle = self.relay_log_path.open("a", encoding="utf-8", errors="replace")
            self.relay_log_handle.write(f"\n--- Relay launch {__import__('datetime').datetime.now().isoformat(timespec='seconds')} ---\n")
            self.relay_log_handle.flush()
            command = [str(RELAY)] if FROZEN else [sys.executable, str(RELAY)]
            self.process = subprocess.Popen(
                command, cwd=HERE, creationflags=flags,
                stdout=self.relay_log_handle, stderr=subprocess.STDOUT,
            )
            self.log_message(f"Started Skua relay; startup output: {self.relay_log_path}")
            self.after(1000, self.check_relay_startup)
        except OSError as exc:
            if self.relay_log_handle:
                self.relay_log_handle.close()
                self.relay_log_handle = None
            messagebox.showerror("Could not start relay", str(exc))

    def check_relay_startup(self) -> None:
        if self.process is None:
            return
        exit_code = self.process.poll()
        if exit_code is not None:
            self.log_message(f"Relay exited immediately with code {exit_code}. See {self.relay_log_path}")
            self.status.configure(text="Relay failed to start — see relay.log", fg=RED)
            if self.relay_log_handle:
                self.relay_log_handle.close()
                self.relay_log_handle = None

    def stop_relay(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None
        if self.relay_log_handle:
            self.relay_log_handle.close()
            self.relay_log_handle = None

    def restart_relay(self) -> None:
        self.log_message("Restarting relay…")
        self.stop_relay()
        self.start_relay()

    def pull_updates(self) -> None:
        if FROZEN:
            webbrowser.open("https://github.com/wtffidy/skua-dashboard/releases/latest")
            self.log_message("Opened the latest release page. Install the new MSI to update.")
            return
        if not (HERE / ".git").exists():
            messagebox.showerror("Git repository not found", "This folder is not a Git checkout. Clone the dashboard repository first.")
            return
        if not messagebox.askyesno("Fetch latest updates", "Run git pull --ff-only for the dashboard repository?\n\nLocal edits that conflict with upstream changes may prevent the update."):
            return

        def pull() -> str:
            result = subprocess.run(
                ["git", "pull", "--ff-only"], cwd=HERE, capture_output=True,
                text=True, timeout=120, check=False,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                raise RuntimeError(output or f"git exited with code {result.returncode}")
            changed = "Already up to date" not in output and "Already up-to-date" not in output
            self.messages.put(("log", output or "Git pull completed."))
            if changed:
                self.messages.put(("log", "Updates were pulled; restarting relay to load them."))
                self.messages.put(("restart_after_update", ""))
            return "updates pulled" if changed else "already up to date"

        self.worker("Git update", pull)

    def open_folder(self) -> None:
        folder = APP_DATA if FROZEN else HERE
        folder.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(folder)])
            else:
                webbrowser.open(folder.as_uri())
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _on_window_unmap(self, event: tk.Event) -> None:
        if event.widget is self and self.state() == "iconic" and bool(self.ui_settings.get("minimize_to_tray", False)):
            self.after_idle(self.minimize_to_tray)

    def minimize_to_tray(self) -> None:
        if not bool(self.ui_settings.get("minimize_to_tray", False)):
            return
        if pystray is None or Image is None:
            self.log_message("System tray support is unavailable. Rebuild with the updated dependencies.")
            return
        if self.tray_icon is not None:
            self.withdraw()
            return
        try:
            if ICON.is_file():
                with Image.open(ICON) as source:
                    tray_image = source.convert("RGBA")
            else:
                tray_image = Image.new("RGBA", (64, 64), (8, 13, 22, 255))
            menu = pystray.Menu(
                pystray.MenuItem("Show Skua Nexus", lambda icon, item: self.after(0, self.restore_from_tray), default=True),
                pystray.MenuItem("Exit", lambda icon, item: self.after(0, self.close)),
            )
            self.tray_icon = pystray.Icon("SkuaNexusManager", tray_image, "Skua Nexus | Manager", menu)
            self.withdraw()
            self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self.tray_thread.start()
            self.log_message("Manager minimized to the system tray.")
        except Exception as exc:
            self.tray_icon = None
            self.deiconify()
            self.log_message(f"Could not minimize to system tray: {exc}")

    def restore_from_tray(self) -> None:
        icon = self.tray_icon
        self.tray_icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()
        self.log_message("Manager restored from the system tray.")

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Exit", "Stop the relay and close the companion?"):
                return
            self.stop_relay()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.destroy()


if __name__ == "__main__":
    # Velopack starts the main executable with lifecycle arguments during install,
    # update, and uninstall. Do not launch the interactive GUI for these hooks.
    velopack_hook_args = {
        "--veloapp-install",
        "--veloapp-obsolete",
        "--veloapp-updated",
        "--veloapp-uninstall",
    }
    if any(argument in velopack_hook_args for argument in sys.argv[1:]):
        raise SystemExit(0)

    app = DashboardApp()
    if not app.relay_responds():
        app.start_relay()
    if bool(app.ui_settings.get("open_dashboard_on_startup", False)):
        app.after(750, app.open_dashboard_when_ready)
    app.mainloop()
