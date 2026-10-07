"""Project-local launcher:  gold.cmd start | stop | status | restart | replay [...] | symbols [pattern] | build-ui | test"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import APP_ID
from .config import PROJECT_ROOT, STATE_DIR

STATE_FILE = STATE_DIR / "server.json"
LOG_FILE = STATE_DIR / "server.log"


def _read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _health(state: dict) -> dict | None:
    try:
        with urllib.request.urlopen(state["url"] + "api/health", timeout=2) as r:
            data = json.loads(r.read().decode())
        return data if data.get("app") == APP_ID and data.get("pid") == state.get("pid") else None
    except Exception:
        return None


def _started_after(state: dict, t: float) -> bool:
    from datetime import datetime
    try:
        return datetime.fromisoformat(state["started_at"]).timestamp() >= t - 1
    except (KeyError, ValueError):
        return False


def status() -> int:
    st = _read_state()
    h = _health(st) if st else None
    if h:
        print(f"Running: {st['url']} (PID {st['pid']}, mode {h['mode']}, scanner {'on' if h['scanner_running'] else 'off'})")
        print(f"Log: {LOG_FILE}")
        return 0
    print("Not running." + (f" (stale record for PID {st['pid']})" if st else ""))
    return 1


def start() -> int:
    st = _read_state()
    if st and _health(st):
        print(f"Already running: {st['url']} (PID {st['pid']})")
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = str(pyw if pyw.exists() else py)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    launched = time.time()
    with open(LOG_FILE, "ab") as log:
        kwargs = dict(cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
        try:
            proc = subprocess.Popen([exe, "-m", "app.server"], creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), **kwargs)
        except OSError:
            proc = subprocess.Popen([exe, "-m", "app.server"], creationflags=flags, **kwargs)
    for _ in range(60):
        time.sleep(0.5)
        st = _read_state()
        # the venv's python(w).exe is a redirector stub, so the server PID differs from proc.pid: match by start time
        if st and _started_after(st, launched) and _health(st):
            print(f"VC Signal running in the background: {st['url']} (PID {st['pid']})")
            print(f"Log: {LOG_FILE}\nStop with: gold.cmd stop")
            return 0
        if proc.poll() is not None:
            break
    print(f"The server did not start (exit code {proc.poll()}). See {LOG_FILE}.")
    return 1


def stop() -> int:
    st = _read_state()
    if not st or not _health(st):
        print("No running VC Signal server is recorded; nothing was stopped.")
        return 0
    req = urllib.request.Request(st["url"] + "api/admin/shutdown", data=b"{}", method="POST",
                                 headers={"X-Session-Token": st["token"], "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    for _ in range(20):
        time.sleep(0.5)
        if not _health(st):
            print(f"Stopped VC Signal at {st['url']} (PID {st['pid']}).")
            return 0
    try:
        os.kill(st["pid"], 15)
        print(f"Force-stopped PID {st['pid']}.")
    except OSError as exc:
        print(f"Could not stop PID {st['pid']}: {exc}")
        return 1
    return 0


def symbols(pattern: str = "*XAU*") -> int:
    from .config import load_settings
    from .data.mt5 import MT5Feed
    s = load_settings()
    feed = MT5Feed("", s.mt5_terminal_path, s.mt5_server_utc_offset_hours)
    st = feed.connect()
    if st.state in ("disconnected", "error"):
        print(st.message)
        return 2
    try:
        rows = feed.list_symbols(pattern)
    finally:
        feed.shutdown()
    if not rows:
        print(f"No symbols match {pattern!r}. Try `gold.cmd symbols *GOLD*` or `gold.cmd symbols *`.")
        return 1
    print(f"Symbols matching {pattern!r} in your terminal (set the exact name as GOLD_SYMBOL in .env):")
    for r in rows:
        print(f"  {r['name']:<16} digits={r['digits']} tick={r['tick_size']} visible={r['visible']}  {r['description']}  [{r['path']}]")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "status"
    if cmd == "start":
        return start()
    if cmd == "stop":
        return stop()
    if cmd == "restart":
        stop()
        return start()
    if cmd == "status":
        return status()
    if cmd == "replay":
        from .replay import main as replay_main
        return replay_main(argv)
    if cmd == "symbols":
        return symbols(argv[0] if argv else "*XAU*")
    if cmd == "build-ui":
        # Rebuild the TailAdmin-based dashboard assets (app/static/index.html + app/static/dist) from frontend/.
        frontend = PROJECT_ROOT / "frontend"
        npm = "npm.cmd" if os.name == "nt" else "npm"
        if not (frontend / "node_modules").exists():
            rc = subprocess.call([npm, "ci", "--cache", str(PROJECT_ROOT / ".tmp" / "npm-cache"), "--no-audit", "--no-fund"], cwd=str(frontend))
            if rc:
                return rc
        return subprocess.call([npm, "run", "build"], cwd=str(frontend))
    if cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", *argv], cwd=str(PROJECT_ROOT))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
