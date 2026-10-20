#!/usr/bin/env python3
"""Local relay for the Skua dashboard. Standard library only."""
import json
import re
import secrets
import threading
import time
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
CFG_PATH, DATA_PATH = HERE / "config.json", HERE / "bots.json"
DEFAULTS = {"port": 8787, "push_key": "", "discord_webhook": "", "allowed_origins": ["https://wtffidy.github.io"]}


def load_config() -> dict:
    cfg = {**DEFAULTS, **(json.loads(CFG_PATH.read_text()) if CFG_PATH.exists() else {})}
    cfg["push_key"] = cfg["push_key"] or secrets.token_hex(12)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


CFG = load_config()
LOCK = threading.Lock()
RAW = deque(maxlen=20)
BOTS = {}
if DATA_PATH.exists():
    try:
        loaded = json.loads(DATA_PATH.read_text())
        if isinstance(loaded, dict):
            BOTS = {k: v for k, v in loaded.items()
                    if isinstance(v, dict) and time.time() * 1000 - v.get("updated", 0) < 86_400_000}
    except (ValueError, OSError, AttributeError):
        BOTS = {}

BOLD = re.compile(r"\*\*(.+?)\*\*")
NUMBER = re.compile(r"-?\d[\d,]*")
STATUS = (("start", "Running script"), ("conclud", "Stopped"), ("stop", "Stopped"),
          ("crash", "Crashed"), ("relog", "Relogging"))
ALIASES = {
    "map": "map", "location": "map", "room": "room", "level": "level",
    "class": "class", "character class": "class", "gold": "gold", "ac": "ac",
    "adventurecoins": "ac", "adventure coins": "ac", "script": "script",
    "quest": "quest", "current quest": "quest", "weapon": "weapon", "equipment": "weapon",
    "kills": "kills", "kill": "kills", "drops": "drops", "quests": "quests",
    "deaths": "deaths", "relogins": "relogins", "relogs": "relogins",
    "skua memory": "skuaMem", "skua mem": "skuaMem", "game memory": "gameMem", "game mem": "gameMem",
}


def clean_label(value) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(value or "").lower()).strip()


def number(value):
    match = NUMBER.search(str(value or ""))
    if not match:
        return None
    try:
        return int(match.group().replace(",", ""))
    except ValueError:
        return None


def parse_pair(value):
    nums = NUMBER.findall(str(value or ""))
    if len(nums) < 2:
        return None
    try:
        return {"cur": int(nums[0].replace(",", "")), "max": int(nums[1].replace(",", ""))}
    except ValueError:
        return None


def extract_stats(body: dict, embed: dict) -> tuple[dict, list]:
    """Normalize custom stats and common Discord embed fields into dashboard properties."""
    raw_stats = body.get("stats")
    stats = dict(raw_stats) if isinstance(raw_stats, dict) else {}
    fields = embed.get("fields") or []
    visible_fields = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        label, value = str(field.get("name") or "").strip(), str(field.get("value") or "").strip()
        if not label:
            continue
        visible_fields.append({"name": label, "value": value})
        key = clean_label(label)
        if key in ("hp", "health", "health points"):
            pair = parse_pair(value)
            if pair:
                stats["hp"] = pair
            continue
        if key in ("mp", "mana", "mana points"):
            pair = parse_pair(value)
            if pair:
                stats["mp"] = pair
            continue
        if key in ("inventory", "inv", "inventory slots"):
            pair = parse_pair(value)
            if pair:
                stats["inv"] = {"used": pair["cur"], "total": pair["max"]}
            continue
        target = ALIASES.get(key)
        if target and value:
            if target in ("gold", "ac", "level", "kills", "drops", "quests", "deaths", "relogins", "skuaMem", "gameMem"):
                parsed = number(value)
                if parsed is not None:
                    stats[target] = parsed
            else:
                stats[target] = re.sub(r"\*", "", value).strip()
    return stats, visible_fields


def record(body: dict) -> dict:
    """Store bot state and return the webhook body for optional Discord forwarding."""
    RAW.append(dict(body))
    stats = body.get("stats") if isinstance(body.get("stats"), dict) else {}
    embeds = [e for e in (body.get("embeds") or []) if isinstance(e, dict)] or [{}]
    embed = embeds[0]
    desc = "\n".join(str(e.get("description") or "") for e in embeds)
    bold = BOLD.findall(desc)
    name = (body.get("username") or (embed.get("author") or {}).get("name") or
            (bold[0] if bold else None) or (embed.get("footer") or {}).get("text") or "unknown")
    title = " ".join(str(e.get("title") or "") for e in embeds).lower()
    normalized = dict(stats)
    fields = []
    # Data may be split across multiple Discord embeds by the client.
    for current_embed in embeds:
        embed_stats, embed_fields = extract_stats({"stats": normalized}, current_embed)
        normalized.update(embed_stats)
        fields.extend(embed_fields)
        description = str(current_embed.get("description") or "")
        # Accept common "Quest: ..." / "Equipment: ..." lines in descriptions too.
        for line in description.splitlines():
            match = re.match(r"\s*\**([^:*]{1,40})\**\s*:\s*(.+?)\s*\**$", line)
            if not match:
                continue
            label, value = match.group(1).strip(), match.group(2).strip()
            key = clean_label(label)
            target = ALIASES.get(key)
            if key in ("quest", "current quest", "quest name", "active quest"):
                normalized["quest"] = value
            elif key in ("equipment", "equip", "weapon", "equipped weapon", "equipped items", "gear"):
                normalized["weapon"] = value
            elif target and value:
                if target in ("gold", "ac", "level", "kills", "drops", "quests", "deaths", "relogins", "skuaMem", "gameMem"):
                    parsed = number(value)
                    if parsed is not None:
                        normalized[target] = parsed
                else:
                    normalized[target] = re.sub(r"\*", "", value).strip()
            fields.append({"name": label, "value": value})
    now = int(time.time() * 1000)
    with LOCK:
        prev = BOTS.get(name, {})
        status = next((label for key, label in STATUS if key in title), None) or embed.get("title") or prev.get("status")
        script = bold[1] if len(bold) > 1 else normalized.get("script", prev.get("script"))
        # Every webhook proves the client is alive; only state-bearing payloads update stateUpdated.
        # Keep prior game values when a health ping or notification contains no snapshot.
        has_state = bool(normalized)
        updated = now
        state_updated = now if has_state else prev.get("stateUpdated", prev.get("updated", 0))
        merged = {**prev, **normalized}
        BOTS[name] = {
            **merged, "status": status, "script": script, "name": name,
            "updated": updated, "stateUpdated": state_updated,
            "last": body.get("content") or desc.replace("**", "") or embed.get("title") or prev.get("last"),
            "fields": fields or prev.get("fields", []),
        }
        DATA_PATH.write_text(json.dumps(BOTS, ensure_ascii=False))
    print(time.strftime("%H:%M:%S"), name, "|", json.dumps(RAW[-1], ensure_ascii=False)[:300])
    return body



def forward(body: dict) -> None:
    url = CFG["discord_webhook"]
    if not url:
        return
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "SkuaRelay/1.0"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as ex:
        print("Discord forward failed:", ex)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in CFG["allowed_origins"] or origin.startswith(("http://localhost", "http://127.0.0.1")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code: int, body=b"", ctype: str = "application/json") -> None:
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if code != 204 and data:
            self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = HERE / "index.html"
            self._send(200, page.read_bytes(), "text/html; charset=utf-8") if page.exists() else self._send(404, b"index.html not found next to relay.py")
        elif path == "/bots":
            with LOCK:
                self._send(200, list(BOTS.values()))
        elif path == "/raw":
            with LOCK:
                self._send(200, list(RAW))
        else:
            self._send(404, b"not found")

    def do_DELETE(self):
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if len(parts) != 2 or parts[0] != "bots":
            return self._send(404, b"not found")
        with LOCK:
            found = BOTS.pop(parts[1], None) is not None
            DATA_PATH.write_text(json.dumps(BOTS, ensure_ascii=False))
        self._send(200 if found else 404, b"ok" if found else b"no such bot")

    def do_POST(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if not (u.path == "/hook" or parts[:2] == ["api", "webhooks"]):
            return self._send(404, b"not found")
        key = (parse_qs(u.query).get("key") or [parts[3] if len(parts) > 3 else ""])[0]
        if not secrets.compare_digest(key, CFG["push_key"]):
            return self._send(401, b"no")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except (ValueError, TypeError):
            return self._send(400, b"bad json")
        if not isinstance(body, dict):
            return self._send(400, b"expected JSON object")
        forwarded = record(body)
        threading.Thread(target=forward, args=(forwarded,), daemon=True).start()
        self._send(204)

if __name__ == "__main__":
    port = CFG["port"]
    print(f"Skua relay running. Dashboard: http://localhost:{port}/\nPut this in the client's Discord Webhook URL field:\n  http://localhost:{port}/api/webhooks/1/{CFG['push_key']}")
    if not CFG["discord_webhook"]:
        print("(No Discord webhook set in config.json, so nothing is forwarded to Discord.)")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except OSError as ex:
        print(f"Could not start on port {port}: {ex}")
