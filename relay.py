#!/usr/bin/env python3
"""Local relay for the Skua dashboard. Standard library only."""
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
import urllib.request
from collections import deque
from typing import Any
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
CFG_PATH, DATA_PATH = HERE / "config.json", HERE / "bots.json"
DEFAULTS = {"port": 8787, "push_key": "", "discord_webhook": "", "allowed_origins": ["https://wtffidy.github.io"]}


def load_config() -> dict[str, Any]:
    cfg = {**DEFAULTS, **(json.loads(CFG_PATH.read_text()) if CFG_PATH.exists() else {})}
    cfg["push_key"] = cfg["push_key"] or secrets.token_hex(12)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


CFG = load_config()
LOCK = threading.Lock()
RAW: deque[dict[str, Any]] = deque(maxlen=20)
BOTS: dict[str, dict[str, Any]] = {}
_PROCESS_SAMPLES: dict[int, tuple[int, int]] = {}
_USAGE_LOCK = threading.Lock()
WS_LOCK = threading.Lock()
WS_CLIENTS: set[socket.socket] = set()
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


def number(value: object) -> int | None:
    match = NUMBER.search(str(value or ""))
    if not match:
        return None
    try:
        return int(match.group().replace(",", ""))
    except ValueError:
        return None


def parse_pair(value: object) -> dict[str, int] | None:
    nums = NUMBER.findall(str(value or ""))
    if len(nums) < 2:
        return None
    try:
        return {"cur": int(nums[0].replace(",", "")), "max": int(nums[1].replace(",", ""))}
    except ValueError:
        return None


def extract_stats(body: dict[str, Any], embed: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Normalize custom stats and common Discord embed fields into dashboard properties."""
    raw_stats = body.get("stats")
    stats = dict(raw_stats) if isinstance(raw_stats, dict) else {}
    fields = embed.get("fields") or []
    visible_fields: list[dict[str, str]] = []
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
            else:
                count = number(value)
                if count is not None:
                    stats["invCount"] = count
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


def record(body: dict[str, Any]) -> dict[str, Any]:
    """Store bot state and return the webhook body for optional Discord forwarding."""
    RAW.append(dict(body))
    raw_stats = body.get("stats")
    stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
    embeds = [e for e in (body.get("embeds") or []) if isinstance(e, dict)] or [{}]
    embed = embeds[0]
    desc = "\n".join(str(e.get("description") or "") for e in embeds)
    bold = BOLD.findall(desc)
    name = (body.get("username") or (embed.get("author") or {}).get("name") or
            (bold[0] if bold else None) or (embed.get("footer") or {}).get("text") or "unknown")
    title = " ".join(str(e.get("title") or "") for e in embeds).lower()
    normalized: dict[str, Any] = dict(stats)
    fields: list[dict[str, str]] = []
    # Data may be split across multiple Discord embeds by the client.
    for current_embed in embeds:
        embed_stats, embed_fields = extract_stats({"stats": normalized}, current_embed)
        normalized.update(embed_stats)
        fields.extend(embed_fields)
        description = str(current_embed.get("description") or "")
        # Accept common "Quest: ..." / "Equipment: ..." lines in descriptions too.
        for line in description.splitlines():
            match = re.match(r"\s*\*{0,2}([^:*]{1,40})\*{0,2}\s*:\s*(.+?)\s*\*{0,2}$", line)
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
    print(time.strftime("%H:%M:%S"), name, "|", json.dumps(RAW[-1], ensure_ascii=False))
    return body



def process_usage() -> dict[str, Any]:
    """Return CPU, RAM, and uptime for the running Windows Skua/VibeSkua process(es)."""
    if os.name != "nt":
        return {"available": False, "reason": "Windows process metrics are only available on Windows."}
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        PROCESS_MEMORY_COUNTERS_CLASS = 0

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
            ]

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        version_api = ctypes.WinDLL("version", use_last_error=True)
        version_api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        version_api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version_api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        version_api.GetFileVersionInfoW.restype = wintypes.BOOL
        version_api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        version_api.VerQueryValueW.restype = wintypes.BOOL

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [("dwSignature", wintypes.DWORD), ("dwStrucVersion", wintypes.DWORD),
                        ("dwFileVersionMS", wintypes.DWORD), ("dwFileVersionLS", wintypes.DWORD),
                        ("dwProductVersionMS", wintypes.DWORD), ("dwProductVersionLS", wintypes.DWORD),
                        ("dwFileFlagsMask", wintypes.DWORD), ("dwFileFlags", wintypes.DWORD),
                        ("dwFileOS", wintypes.DWORD), ("dwFileType", wintypes.DWORD),
                        ("dwFileSubtype", wintypes.DWORD), ("dwFileDateMS", wintypes.DWORD),
                        ("dwFileDateLS", wintypes.DWORD)]

        def read_product_version(file_path: str) -> str | None:
            ignored = wintypes.DWORD(0)
            size = version_api.GetFileVersionInfoSizeW(file_path, ctypes.byref(ignored))
            if not size:
                return None
            buffer = ctypes.create_string_buffer(size)
            if not version_api.GetFileVersionInfoW(file_path, 0, size, buffer):
                return None
            pointer, length = ctypes.c_void_p(), wintypes.UINT(0)
            if not version_api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or not pointer.value:
                return None
            info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
            major, minor = info.dwProductVersionMS >> 16, info.dwProductVersionMS & 0xFFFF
            build, revision = info.dwProductVersionLS >> 16, info.dwProductVersionLS & 0xFFFF
            return f"{major}.{minor}.{build}" + (f".{revision}" if revision else "")

        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return {"available": False, "reason": "Could not enumerate Windows processes."}

        now = time.monotonic()
        total_cpu_100ns = 0
        total_memory = 0
        oldest_creation = None
        product_version = None
        found = 0
        current_samples: dict[int, tuple[int, int]] = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                exe_name = entry.szExeFile.lower()
                if exe_name in ("skua.exe", "vibeskua.exe") or (exe_name.startswith("vibeskua") and exe_name.endswith(".exe")):
                    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, entry.th32ProcessID)
                    if handle:
                        try:
                            path_buffer = ctypes.create_unicode_buffer(32768)
                            path_length = wintypes.DWORD(len(path_buffer))
                            if kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(path_length)) and product_version is None:
                                product_version = read_product_version(path_buffer.value)
                            created, exited, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
                            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
                                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
                                continue
                            to_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
                            creation = to_int(created)
                            cpu_ticks = to_int(kernel_time) + to_int(user_time)
                            current_samples[entry.th32ProcessID] = (cpu_ticks, int(now * 1_000_000_000))
                            previous = _PROCESS_SAMPLES.get(entry.th32ProcessID)
                            if previous:
                                elapsed_100ns = max(1, int((now * 1_000_000_000 - previous[1]) / 100))
                                cpu_delta = max(0, cpu_ticks - previous[0])
                                total_cpu_100ns += int(cpu_delta / max(1, os.cpu_count() or 1))
                                # CPU percentage is calculated below from elapsed wall time.
                                current_samples[entry.th32ProcessID] = (cpu_ticks, int(now * 1_000_000_000))
                            counters = PROCESS_MEMORY_COUNTERS()
                            counters.cb = ctypes.sizeof(counters)
                            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                                total_memory += counters.WorkingSetSize
                            oldest_creation = creation if oldest_creation is None else min(oldest_creation, creation)
                            found += 1
                        finally:
                            kernel32.CloseHandle(handle)
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        cpu_percent = None
        with _USAGE_LOCK:
            prior_samples = dict(_PROCESS_SAMPLES)
            _PROCESS_SAMPLES.clear()
            _PROCESS_SAMPLES.update(current_samples)
        if prior_samples and found:
            cpu_delta = 0
            elapsed_ns = 0
            for pid, (ticks, stamp) in current_samples.items():
                old = prior_samples.get(pid)
                if old:
                    cpu_delta += max(0, ticks - old[0])
                    elapsed_ns = max(elapsed_ns, stamp - old[1])
            if elapsed_ns > 0:
                cpu_percent = round(min(100.0, cpu_delta / (elapsed_ns / 100) / max(1, os.cpu_count() or 1) * 100), 1)

        uptime_seconds = None
        if oldest_creation is not None:
            current_filetime = int((time.time() + 11644473600) * 10_000_000)
            uptime_seconds = max(0, int((current_filetime - oldest_creation) / 10_000_000))
        return {
            "available": found > 0,
            "processes": found,
            "cpuPercent": cpu_percent,
            "memoryBytes": total_memory,
            "uptimeSeconds": uptime_seconds,
            "processName": "VibeSkua",
            "version": product_version,
        }
    except Exception as exc:
        return {"available": False, "reason": f"Process metrics unavailable: {type(exc).__name__}"}


def websocket_frame(payload: bytes, opcode: int = 1) -> bytes:
    """Build an unmasked server-to-client WebSocket frame."""
    length = len(payload)
    head = bytes([0x80 | opcode])
    if length < 126:
        return head + bytes([length]) + payload
    if length < 65536:
        return head + bytes([126]) + struct.pack("!H", length) + payload
    return head + bytes([127]) + struct.pack("!Q", length) + payload


def broadcast_snapshot() -> None:
    """Push the current dashboard state to every connected WebSocket browser."""
    with LOCK:
        bots = list(BOTS.values())
    payload = json.dumps({"type": "snapshot", "bots": bots, "usage": process_usage()}, ensure_ascii=False).encode("utf-8")
    frame = websocket_frame(payload)
    dead: list[socket.socket] = []
    with WS_LOCK:
        for client in WS_CLIENTS:
            try:
                client.sendall(frame)
            except (OSError, ConnectionError):
                dead.append(client)
        for client in dead:
            WS_CLIENTS.discard(client)
            try:
                client.close()
            except OSError:
                pass


def usage_broadcast_loop() -> None:
    """Refresh process telemetry for connected browsers even between bot heartbeats."""
    while True:
        time.sleep(2)
        with WS_LOCK:
            connected = bool(WS_CLIENTS)
        if connected:
            broadcast_snapshot()


def read_websocket_frame(client: socket.socket) -> tuple[int, bytes] | None:
    """Read one client WebSocket frame, including its required masking."""
    def read_exact(count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = client.recv(count - len(data))
            if not chunk:
                raise ConnectionError("WebSocket client disconnected")
            data.extend(chunk)
        return bytes(data)

    first, second = read_exact(2)
    opcode, length = first & 0x0F, second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(8))[0]
    masked = bool(second & 0x80)
    mask = read_exact(4) if masked else b""
    payload = read_exact(length) if length else b""
    if masked:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return opcode, payload


def forward(body: dict[str, Any]) -> None:
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
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in CFG["allowed_origins"] or origin.startswith(("http://localhost", "http://127.0.0.1")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send(self, code: int, body: Any = b"", ctype: str = "application/json") -> None:
        data: bytes = json.dumps(body).encode() if isinstance(body, (dict, list)) else body if isinstance(body, bytes) else str(body).encode()
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
        elif path == "/usage":
            self._send(200, process_usage())
        elif path == "/ws":
            key = (parse_qs(urlparse(self.path).query).get("key") or [""])[0]
            if CFG["allowed_origins"] and self.headers.get("Origin", "") not in CFG["allowed_origins"] and not self.headers.get("Origin", "").startswith(("http://localhost", "http://127.0.0.1")):
                return self._send(403, b"origin not allowed")
            if CFG["push_key"] and not secrets.compare_digest(key, CFG["push_key"]):
                return self._send(401, b"no")
            ws_key = self.headers.get("Sec-WebSocket-Key")
            if self.headers.get("Upgrade", "").lower() != "websocket" or not ws_key:
                return self._send(400, b"websocket upgrade required")
            accept = base64.b64encode(hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            client = self.connection
            client.settimeout(45)
            with WS_LOCK:
                WS_CLIENTS.add(client)
            try:
                with LOCK:
                    initial_bots = list(BOTS.values())
                initial = json.dumps({"type": "snapshot", "bots": initial_bots, "usage": process_usage()}, ensure_ascii=False).encode("utf-8")
                client.sendall(websocket_frame(initial))
                while True:
                    frame = read_websocket_frame(client)
                    if frame is None:
                        break
                    opcode, payload = frame
                    if opcode == 8:
                        try:
                            client.sendall(websocket_frame(payload, 8))
                        except OSError:
                            pass
                        break
                    if opcode == 9:
                        client.sendall(websocket_frame(payload, 10))
            except (OSError, ConnectionError, socket.timeout):
                pass
            finally:
                with WS_LOCK:
                    WS_CLIENTS.discard(client)
                try:
                    client.close()
                except OSError:
                    pass
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
        if found:
            threading.Thread(target=broadcast_snapshot, daemon=True).start()

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
        threading.Thread(target=broadcast_snapshot, daemon=True).start()
        threading.Thread(target=forward, args=(forwarded,), daemon=True).start()
        self._send(204)

if __name__ == "__main__":
    port = CFG["port"]
    print(f"Skua relay running. Dashboard: http://localhost:{port}/\nPut this in the client's Discord Webhook URL field:\n  http://localhost:{port}/api/webhooks/1/{CFG['push_key']}")
    if not CFG["discord_webhook"]:
        print("(No Discord webhook set in config.json, so nothing is forwarded to Discord.)")
    threading.Thread(target=usage_broadcast_loop, daemon=True).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except OSError as ex:
        print(f"Could not start on port {port}: {ex}")
