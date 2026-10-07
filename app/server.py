"""Run the dashboard server on 127.0.0.1 (foreground). Use `gold.cmd start` for a hidden background process."""
from __future__ import annotations

import argparse
import json
import os
import socket
from datetime import datetime

import uvicorn

from . import APP_ID
from .config import STATE_DIR, load_settings
from .models import UTC
from .web import create_app

STATE_FILE = STATE_DIR / "server.json"


def bind_loopback(preferred: int, attempts: int = 20) -> socket.socket:
    last = None
    for port in range(preferred, preferred + attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(64)
            return s
        except OSError as exc:
            last = exc
            s.close()
    raise SystemExit(f"no free loopback port in {preferred}-{preferred + attempts - 1}: {last}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    settings = load_settings()
    sock = bind_loopback(args.port or settings.port)
    port = sock.getsockname()[1]
    settings.port = port
    app = create_app(settings)
    url = f"http://127.0.0.1:{port}/"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"app": APP_ID, "url": url, "port": port, "pid": os.getpid(),
                               "token": app.state.token, "started_at": datetime.now(UTC).isoformat()}, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)
    print(f"[{datetime.now(UTC).isoformat()}] VC Signal at {url} (pid {os.getpid()})", flush=True)
    config = uvicorn.Config(app, log_level="info", access_log=False)
    uvicorn.Server(config).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
