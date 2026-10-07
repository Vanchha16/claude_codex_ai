"""Cross-process ownership guard for the scanner + Telegram sender.

Only ONE process may run the live scanner and outbox sender. The owner holds an OS-level exclusive lock on
.tmp/gold-signals/owner.lock for its whole lifetime (msvcrt on Windows, fcntl elsewhere). The OS releases the
lock automatically when the owning process exits or is killed, so recovery after a crash needs no cleanup.
A second launcher/web-worker process that cannot take the lock must not start a scanner or sender.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import UTC


class OwnerLock:
    def __init__(self, path: Path):
        self.path = path
        self.info_path = path.with_suffix(".json")
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def acquire(self) -> bool:
        if self._fh is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        tmp = self.info_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "since": datetime.now(UTC).isoformat()}), encoding="utf-8")
        os.replace(tmp, self.info_path)
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None

    def holder(self) -> Optional[dict]:
        """Last recorded owner (informational only; the lock itself is the source of truth)."""
        try:
            return json.loads(self.info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
