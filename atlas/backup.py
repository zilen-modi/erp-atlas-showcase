"""Backups of what Atlas can't rebuild from git: accounts, accepted facts, summaries Claude wrote, saved
scenarios, compare notes and chats (all in the SQLite store), plus the key that decrypts saved Claude tokens and
the settings.

Each backup is a folder in .data/backups named by time, made with SQLite's online backup (safe while Atlas runs)
and gzipped (about a fifth of the size). To restore: stop Atlas, `gunzip -c atlas.db.gz > .data/atlas.db`, and
copy secret.key and settings.json back into .data.
The newest KEEP are kept. The API makes one a day by itself; `atlas backup` makes one now. They sit on the same
disk as Atlas: copy .data/backups somewhere else (a share, cloud storage) to survive losing this machine.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas.config import ROOT

DIR = ROOT / ".data" / "backups"
KEEP = 14
EVERY_S = 24 * 3600
EXTRAS = (ROOT / ".data" / "secret.key", ROOT / ".data" / "settings.json")


def backup(db: Path, dest: Path = DIR, keep: int = KEEP) -> dict[str, Any]:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = dest / stamp
    out.mkdir(parents=True, exist_ok=True)
    raw = out / db.name
    src = sqlite3.connect(str(db))
    try:
        dst = sqlite3.connect(str(raw))
        src.backup(dst)
        dst.close()
    finally:
        src.close()
    with raw.open("rb") as fi, gzip.open(out / (db.name + ".gz"), "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo, 1 << 20)
    raw.unlink()
    for f in EXTRAS:
        if f.exists():
            shutil.copy2(f, out / f.name)
    if (out / "secret.key").exists():
        (out / "secret.key").chmod(0o600)          # it decrypts saved Claude tokens
    old = sorted(p for p in dest.iterdir() if p.is_dir())[:-keep] if keep > 0 else []
    for p in old:
        shutil.rmtree(p, ignore_errors=True)
    size = sum(f.stat().st_size for f in out.iterdir())
    return {"path": str(out), "bytes": size, "removed": len(old)}


def latest(dest: Path = DIR) -> dict[str, Any] | None:
    dirs = sorted(p for p in dest.iterdir() if p.is_dir()) if dest.exists() else []
    if not dirs:
        return None
    d = dirs[-1]
    return {"path": str(d), "at": datetime.strptime(d.name, "%Y%m%d-%H%M%S").replace(tzinfo=UTC).isoformat(),
            "count": len(dirs), "bytes": sum(f.stat().st_size for f in d.iterdir())}


def start_daily(db: Path) -> None:
    """Back up now if the newest backup is a day old (or missing), then check hourly. Runs in the API process."""
    def loop() -> None:
        while True:
            try:
                last = latest()
                age = time.time() - datetime.fromisoformat(last["at"]).timestamp() if last else None
                if age is None or age >= EVERY_S:
                    backup(db)
            except Exception as e:  # a failed backup must never take the API down; try again next hour
                print(f"backup failed: {e}", flush=True)
            time.sleep(3600)
    threading.Thread(target=loop, daemon=True, name="atlas-backup").start()
