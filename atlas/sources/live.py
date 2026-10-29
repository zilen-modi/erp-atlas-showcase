"""Read-only client for the UniVerse python-layer endpoints.

Only three endpoints may ever be called -- the allowlist below is the safety
boundary and is deliberately not configurable.  `/routine/call` executes
arbitrary subroutines and `/w5/readu` takes record locks; Atlas must never be
able to reach either, whatever the config says.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:          # not on Windows: per-process pacing only
    fcntl = None  # type: ignore[assignment]
import httpx

ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/table"), ("POST", "/table/query"), ("POST", "/table/block")}
)


def to_attr(x: Any) -> str:
    """The python layer sends a multivalued attribute as a JSON array (values), with nested
    arrays for subvalues. Rebuild the Pick string with raw value/subvalue marks."""
    if x is None:
        return ""
    if isinstance(x, list):
        return "\xfd".join("\xfc".join("" if y is None else str(y) for y in v) if isinstance(v, list)
                           else to_attr(v) for v in x)
    return str(x)


class LiveError(RuntimeError):
    pass


class NotAllowed(LiveError):
    pass


def content_hash(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8", "surrogatepass")).hexdigest()


@dataclass
class LiveRecord:
    table: str
    record_id: str
    lines: list[str]
    hash: str
    fetched_at: str
    from_cache: bool


class LiveClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 120,
        min_interval_s: float = 1.0,
        cache_dir: Path | None = None,
        deny_tables: list[str] | None = None,
        transport: httpx.BaseTransport | None = None,
        parallel: int = 1,
        lock_dir: Path | None = None,
        max_parallel: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = min_interval_s
        # at most `parallel` calls in flight; call starts are spaced min_interval_s / parallel apart,
        # so the rate never exceeds `parallel` calls per min_interval_s
        self.parallel = max(1, int(parallel))
        self._slots = threading.Semaphore(self.parallel)
        self._pace = threading.Lock()
        self.cache_dir = cache_dir
        self.deny = {t.upper() for t in (deny_tables or [])}
        self._last = 0.0
        self._http = httpx.Client(timeout=timeout_s, transport=transport)
        # Every Atlas process (the API, each Ask Atlas chat's tools, the CLI) shares one budget for TEST through
        # lock files here: at most `max_parallel` calls in flight on this machine, starts paced machine-wide.
        self.lock_dir = lock_dir
        self.max_parallel = max(1, int(max_parallel or self.parallel))
        self.timeout_s = timeout_s
        if lock_dir is not None:
            lock_dir.mkdir(parents=True, exist_ok=True)

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        if (method.upper(), path) not in ALLOWED:
            raise NotAllowed(f"{method} {path} is not on the read-only allowlist")
        with self._slots, self._machine_slot():
            return self._send(method, path, **kw)

    @contextmanager
    def _machine_slot(self) -> Iterator[None]:
        """Hold one of the machine-wide call slots (a free lock file) for the length of a call."""
        if self.lock_dir is None or fcntl is None:
            yield
            return
        deadline = time.monotonic() + self.timeout_s
        while True:
            for i in range(self.max_parallel):
                f = (self.lock_dir / f"slot-{i}.lock").open("a")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    f.close()
                    continue
                try:
                    yield
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
                    f.close()
                return
            if time.monotonic() > deadline:
                raise LiveError("TEST is busy with other Atlas calls; try again in a minute")
            time.sleep(0.05)

    def _wait_turn(self) -> None:
        with self._pace:
            if self.lock_dir is not None and fcntl is not None:
                # machine-wide pacing: the last call start on this machine is kept in a shared file
                gap = self.min_interval_s / self.max_parallel
                with (self.lock_dir / "pace.lock").open("a+") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.seek(0)
                    try:
                        last = float(f.read().strip() or 0)
                    except ValueError:
                        last = 0.0
                    wait = gap - (time.time() - last)
                    if wait > 0:
                        time.sleep(wait)
                    f.seek(0)
                    f.truncate()
                    f.write(repr(time.time()))
                    f.flush()
                    fcntl.flock(f, fcntl.LOCK_UN)
                return
            gap = self.min_interval_s / self.parallel
            wait = gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _send(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        err: Exception | None = None
        for _attempt in range(2):
            self._wait_turn()
            try:
                resp = self._http.request(method, self.base_url + path, **kw)
                if resp.status_code >= 500:
                    err = LiveError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                    continue
                if resp.status_code >= 400:
                    raise LiveError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                body: dict[str, Any] = resp.json()
                return body
            except httpx.TransportError as e:
                err = e
        raise LiveError(f"live call failed ({err}); is the VPN connected?")

    def _check_table(self, table: str) -> None:
        base = table.upper().removeprefix("DICT ").strip()
        if base in self.deny:
            raise NotAllowed(f"table {table} is on the sensitive-data denylist")

    # -- cache -------------------------------------------------------------

    def _cache_path(self, table: str, record_id: str) -> Path | None:
        if self.cache_dir is None:
            return None
        safe = lambda s: s.replace("/", "%2F").replace("\\", "%5C")  # noqa: E731
        return self.cache_dir / safe(table) / f"{safe(record_id)}.json"

    def _from_cache(self, table: str, record_id: str, max_age_s: float | None) -> LiveRecord | None:
        p = self._cache_path(table, record_id)
        if p is None or not p.exists():
            return None
        d = json.loads(p.read_text())
        if max_age_s is not None:
            age = (datetime.now(UTC) - datetime.fromisoformat(d["fetched_at"])).total_seconds()
            if age > max_age_s:
                return None
        return LiveRecord(table, record_id, d["lines"], d["hash"], d["fetched_at"], True)

    def _to_cache(self, rec: LiveRecord) -> None:
        p = self._cache_path(rec.table, rec.record_id)
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"table": rec.table, "id": rec.record_id, "lines": rec.lines,
                                 "hash": rec.hash, "fetched_at": rec.fetched_at}))

    # -- API ---------------------------------------------------------------

    def read_record(self, table: str, record_id: str, max_age_s: float | None = None,
                    refresh: bool = False) -> LiveRecord:
        """One record as a list of attributes (for BP: source lines)."""
        self._check_table(table)
        if not refresh:
            cached = self._from_cache(table, record_id, max_age_s)
            if cached:
                return cached
        body = self._request("GET", "/table", params={"table_name": table, "record_id": record_id})
        if body.get("error") or not body.get("success", True):
            raise LiveError(f"{table} {record_id}: {body.get('error') or body.get('detail')}")
        data = body.get("data") or []
        lines = [to_attr(x) for x in data] if isinstance(data, list) else str(data).split("\n")
        rec = LiveRecord(table, record_id, lines, content_hash(lines),
                         datetime.now(UTC).isoformat(timespec="seconds"), False)
        self._to_cache(rec)
        return rec

    def query(self, table: str, query: str = "", limit: int | None = None,
              attributes: list[str] | None = None) -> list[Any]:
        self._check_table(table)
        payload: dict[str, Any] = {"table_name": table, "query": query, "attributes": attributes or ["@ID"]}
        if limit is not None:
            payload["limit"] = limit
        body = self._request("POST", "/table/query", json=payload)
        return list(body.get("data") or [])

    def list_ids(self, table: str, limit: int, query: str = "") -> list[str]:
        """Record keys in file order (the python layer's query needs one attribute; @ID is cheapest)."""
        return [str(r.get("ID")) for r in self.query(table, query, limit) if r.get("ID") not in (None, "")]

    def read_block(self, table: str, record_ids: list[str]) -> dict[str, list[str]]:
        """Many records in one call. Missing records come back as [] (HTTP 206)."""
        self._check_table(table)
        try:
            body = self._request("POST", "/table/block", json={"table_name": table, "record_ids": record_ids})
        except LiveError as e:
            if "not found" in str(e).lower():          # 404 when none of the records exist
                return {rid: [] for rid in record_ids}
            raise
        out: dict[str, list[str]] = {}
        for item in body.get("data") or []:
            for rid, data in (item or {}).items():
                out[str(rid)] = [to_attr(x) for x in data] if isinstance(data, list) else []
        return out

    def close(self) -> None:
        self._http.close()
