#!/usr/bin/env python3
"""Local relay for the Skua dashboard. Standard library only, so there is nothing to install.

Client webhook  ->  this script (localhost)  ->  Discord (optional, forwarded unchanged)
GitHub Pages dashboard  ->  GET http://localhost:8787/bots
"""
import json
import secrets
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
CFG_PATH, DATA_PATH = HERE / "config.json", HERE / "bots.json"
DEFAULTS = {"port": 8787, "push_key": "", "discord_webhook": "", "allowed_origins": ["https://wtffidy.github.io"]}


def load_config() -> dict:
    cfg = {**DEFAULTS, **(json.loads(CFG_PATH.read_text()) if CFG_PATH.exists() else {})}
    cfg["push_key"] = cfg["push_key"] or secrets.token_hex(12)  # generated once, then saved
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


CFG = load_config()
LOCK = threading.Lock()
RAW = deque(maxlen=20)  # last payloads, handy for seeing what the client really sends
BOTS = {}
if DATA_PATH.exists():  # keep recent bots across restarts, drop anything older than a day
    try:
        BOTS = {k: v for k, v in json.loads(DATA_PATH.read_text()).items() if time.time() * 1000 - v.get("updated", 0) < 86_400_000}
    except (ValueError, OSError):
        BOTS = {}


def record(body: dict) -> dict:
    """Store the bot's latest state; returns the body to forward (without our private 'stats' key)."""
    RAW.append(dict(body))
    stats = body.pop("stats", None) or {}
    e = (body.get("embeds") or [{}])[0] or {}
    name = body.get("username") or (e.get("author") or {}).get("name") or (e.get("footer") or {}).get("text") or "unknown"
    with LOCK:
        prev = BOTS.get(name, {})
        # Merge so earlier stats survive a plain text alert
        BOTS[name] = {**prev, **stats, "name": name, "updated": int(time.time() * 1000),
                      "last": body.get("content") or e.get("title") or prev.get("last"),
                      "fields": e.get("fields") or prev.get("fields")}
        DATA_PATH.write_text(json.dumps(BOTS))
    print(time.strftime("%H:%M:%S"), name, "|", json.dumps(RAW[-1])[:300])
    return body


def forward(body: dict) -> None:
    url = CFG["discord_webhook"]
    if not url:
        return
    # Discord rejects Python's default User-Agent, so send our own
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "SkuaRelay/1.0"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as ex:
        print("Discord forward failed:", ex)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence the default per-request logging
        pass

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in CFG["allowed_origins"] or origin.startswith(("http://localhost", "http://127.0.0.1")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")  # lets an https page reach localhost

    def _send(self, code: int, body=b"") -> None:
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/bots":
            with LOCK:
                self._send(200, list(BOTS.values()))
        elif path == "/raw":
            self._send(200, list(RAW))
        else:
            self._send(404, b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        # Accepts /hook?key=KEY or a Discord-lookalike /api/webhooks/<id>/KEY
        if not (u.path == "/hook" or parts[:2] == ["api", "webhooks"]):
            return self._send(404, b"not found")
        key = (parse_qs(u.query).get("key") or [parts[3] if len(parts) > 3 else ""])[0]
        if not secrets.compare_digest(key, CFG["push_key"]):
            return self._send(401, b"no")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._send(400, b"bad json")
        threading.Thread(target=forward, args=(record(body),), daemon=True).start()
        self._send(204)  # same reply Discord gives, so the client sees success


if __name__ == "__main__":
    port = CFG["port"]
    print(f"Skua relay running. Put this in the client's Discord Webhook URL field:\n  http://localhost:{port}/api/webhooks/1/{CFG['push_key']}")
    if not CFG["discord_webhook"]:
        print("(No Discord webhook set in config.json, so nothing is forwarded to Discord.)")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()  # 127.0.0.1 = this PC only
    except OSError as ex:
        print(f"Could not start on port {port}: {ex}")
