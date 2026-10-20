#!/usr/bin/env python3
"""Dark, site-matched Windows companion for the Skua Dashboard."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from urllib.error import URLError
from urllib.request import urlopen

FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "SkuaDashboard"
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", HERE)) if FROZEN else HERE
URL = "http://localhost:8787/"
RELAY = HERE / ("SkuaRelay.exe" if FROZEN else "relay.py")
ICON = RESOURCE_DIR / "SkuaIcon.ico"

BG = "#0d0e12"
CARD = "#14161c"
INNER = "#1b1e26"
LINE = "#262a35"
FG = "#e8eaf0"
MUTED = "#8b93a5"
ACCENT = "#7c6cff"
GREEN = "#22c55e"
AMBER = "#e5a82a"
RED = "#e05555"


class DashboardApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Skua Manager")
        if ICON.is_file():
            try:
                self.iconbitmap(default=str(ICON))
            except tk.TclError:
                pass
        self.geometry("700x590")
        self.minsize(620, 520)
        self.configure(bg=BG)
        self.process: subprocess.Popen | None = None
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False

        self._build_ui()
        self.log_message("Ready. Settings and bot data are stored in your AppData folder.")
        self.after(250, self.drain_messages)
        self.after(500, self.check_status)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=22, pady=(20, 14))

        logo = tk.Label(header, text="V", bg=ACCENT, fg="#ffffff",
                        font=("Segoe UI", 12, "bold"), width=2, height=1)
        logo.pack(side="left", padx=(0, 10))
        title_area = tk.Frame(header, bg=BG)
        title_area.pack(side="left", fill="x", expand=True)
        tk.Label(title_area, text="Skua Manager", bg=BG, fg=FG,
                 font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(title_area, text="LOCAL DASHBOARD CONTROL", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(1, 0))
        tk.Label(header, text="●", bg=BG, fg=GREEN, font=("Segoe UI", 12)).pack(side="right", padx=(8, 0))
        tk.Label(header, text="LOCAL", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="right")

        self._separator()

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

        tk.Label(self, text="QUICK ACTIONS", bg=BG, fg=MUTED,
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
        tk.Label(log_header, text="ACTIVITY", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(log_header, text="Updates and relay messages", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="right")

        log_card = tk.Frame(self, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        log_card.pack(fill="both", expand=True, padx=22, pady=(0, 20))
        self.log = tk.Text(log_card, height=9, bg=CARD, fg=FG, insertbackground=FG,
                           selectbackground=ACCENT, relief="flat", wrap="word",
                           font=("Consolas", 9), padx=12, pady=11, state="disabled",
                           borderwidth=0)
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground=GREEN)
        self.log.tag_configure("error", foreground=RED)

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
            command = [str(RELAY)] if FROZEN else [sys.executable, str(RELAY)]
            self.process = subprocess.Popen(command, cwd=HERE, creationflags=flags)
            self.log_message("Started Skua relay.")
        except OSError as exc:
            messagebox.showerror("Could not start relay", str(exc))

    def stop_relay(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            self.process = None

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

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            if messagebox.askyesno("Exit", "Stop the relay and close the companion?"):
                self.stop_relay()
                self.destroy()
        else:
            self.destroy()


if __name__ == "__main__":
    app = DashboardApp()
    if not app.relay_responds():
        app.start_relay()
    app.mainloop()
