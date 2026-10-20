#!/usr/bin/env python3
"""Small Windows GUI for starting and maintaining the Skua Dashboard."""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
URL = "http://localhost:8787/"
RELAY = HERE / "relay.py"


class DashboardApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Skua Dashboard Companion")
        self.geometry("560x430")
        self.minsize(500, 380)
        self.configure(bg="#0d0e12")
        self.process: subprocess.Popen | None = None
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#0d0e12")
        style.configure("TLabel", background="#0d0e12", foreground="#e8eaf0", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Sub.TLabel", foreground="#8b93a5")
        style.configure("TButton", font=("Segoe UI", 10), padding=(10, 8))
        style.configure("Accent.TButton", background="#7c6cff", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#9588ff")])

        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Skua Dashboard", style="Title.TLabel").pack(anchor="w")
        ttk.Label(root, text="Quick controls for your local dashboard and Git updates.", style="Sub.TLabel").pack(anchor="w", pady=(2, 14))

        status_row = ttk.Frame(root)
        status_row.pack(fill="x", pady=(0, 12))
        self.status_dot = tk.Label(status_row, text="●", fg="#e5a82a", bg="#0d0e12", font=("Segoe UI", 12))
        self.status_dot.pack(side="left")
        self.status = ttk.Label(status_row, text="Checking local relay…")
        self.status.pack(side="left", padx=(7, 0))
        self.url_label = ttk.Label(status_row, text=URL, style="Sub.TLabel")
        self.url_label.pack(side="right")

        actions = ttk.Frame(root)
        actions.pack(fill="x")
        for column in range(2):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="Open / Reload Dashboard", style="Accent.TButton", command=self.open_dashboard).grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=5)
        ttk.Button(actions, text="Restart Relay", command=self.restart_relay).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=5)
        ttk.Button(actions, text="Fetch Latest Git Updates", command=self.pull_updates).grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=5)
        ttk.Button(actions, text="Open Repository Folder", command=self.open_folder).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=5)

        ttk.Label(root, text="Activity", style="Sub.TLabel").pack(anchor="w", pady=(14, 5))
        self.log = tk.Text(root, height=10, bg="#14161c", fg="#e8eaf0", insertbackground="#e8eaf0",
                           relief="flat", wrap="word", font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log_message("Ready. Git updates use a safe fast-forward-only pull.")
        self.after(250, self.drain_messages)
        self.after(1000, self.check_status)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def log_message(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def worker(self, title: str, action) -> None:
        def run() -> None:
            try:
                result = action()
                self.messages.put(("log", f"{title}: {result}"))
            except Exception as exc:
                self.messages.put(("error", f"{title} failed: {exc}"))
        threading.Thread(target=run, daemon=True).start()

    def drain_messages(self) -> None:
        try:
            while True:
                kind, message = self.messages.get_nowait()
                self.log_message(message)
                if kind == "error":
                    self.status.configure(text=message)
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
        self.status_dot.configure(fg="#22c55e" if alive else "#e5a82a")
        self.status.configure(text="Relay online" if alive else "Relay not responding")
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
            messagebox.showerror("Missing file", f"Could not find relay.py at:\n{RELAY}")
            return
        executable = sys.executable
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.process = subprocess.Popen([executable, str(RELAY)], cwd=HERE, creationflags=flags)
            self.log_message("Started relay.py.")
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
        if not (HERE / ".git").exists():
            messagebox.showerror("Git repository not found", "This folder is not a Git checkout. Clone the dashboard repository first.")
            return
        if not messagebox.askyesno("Fetch latest updates", "Run git pull --ff-only for the dashboard repository?\n\nLocal edits that conflict with upstream changes may prevent the update."):
            return

        def pull() -> str:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=HERE,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode != 0:
                raise RuntimeError(output or f"git exited with code {result.returncode}")
            changed = "Already up to date" not in output and "Already up-to-date" not in output
            self.messages.put(("log", output or "Git pull completed."))
            if changed:
                self.messages.put(("log", "Updates were pulled; restarting relay to load them."))
                self.stop_relay()
                self.start_relay()
            return "updates pulled" if changed else "already up to date"

        self.worker("Git update", pull)

    def open_folder(self) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(HERE)])
            else:
                webbrowser.open(HERE.as_uri())
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
