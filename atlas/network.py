"""Branch network: the branches and the transfers moving between them, read from TEST.

Branches come from BRANCH (city, state from the tax jurisdiction, mother = regional hub);
the Central Distribution branches from CONTROL "CD.IDS" (branch 1 when it isn't set). Transfers
come from TRANSFER: mode S = shipped and not yet received ("in transit"), mode O = ordered
and not yet shipped ("open", the last N days). Lanes aggregate transfers by from -> to.
A transfer's journey adds its TRANSFER-LOG events (date, time, user, reason, program).
Read-only, through the same throttled python-layer client as everything else.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from atlas.config import ROOT
from atlas.sources.live import LiveClient, LiveError

SAVED = ROOT / ".data" / "network.json"

Result = dict[str, Any]
_CACHE: dict[str, Any] = {"at": 0.0, "key": None, "value": None}
_LOCK = threading.Lock()
TTL_S = 300
PICK_EPOCH = date(1967, 12, 31)
VM = "\xfd"


def _d(s: str) -> date | None:
    """MM/DD/YY (python layer output conversion) -> date."""
    s = (s or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _title(city: str) -> str:
    return " ".join(w.capitalize() for w in city.split()) if city else ""


def branches(client: LiveClient) -> list[Result]:
    rows = client.query("BRANCH", "", 1000, ["@ID", "CITY", "TAX-JUR", "MOTHER.BR"])
    try:
        cds = [x for x in client.read_record("CONTROL", "CD.IDS", refresh=True).lines[0].split(VM) if x]
    except (LiveError, IndexError):
        cds = []
    cds = cds or ["1"]
    out: list[Result] = []
    for r in rows:
        bid = str(r.get("ID", "")).strip()
        if not re.fullmatch(r"\d+", bid):          # "1.SALES" and similar are not physical branches
            continue
        state = re.sub(r"[^A-Z]", "", str(r.get("tax-jur") or "").upper())[:2]
        out.append({"id": bid, "city": _title(str(r.get("city") or "")), "state": state,
                    "mother": str(r.get("mother.br") or "").strip() or bid, "cd": bid in cds})
    # a hub is a branch other branches report to (being your own mother doesn't count)
    children: dict[str, int] = defaultdict(int)
    for b in out:
        if b["mother"] != b["id"]:
            children[str(b["mother"])] += 1
    for b in out:
        b["children"] = children.get(str(b["id"]), 0)
        b["hub"] = b["children"] > 0 and not b["cd"]
    return sorted(out, key=lambda b: int(b["id"]))


def _transfers(client: LiveClient, query: str, limit: int) -> list[Result]:
    rows = client.query("TRANSFER", query, limit, ["@ID", "FROM", "TO", "MODE", "DATE-ORD", "REQUIRED", "DATE-SHIP",
                                                   "VIA-DESC", "TOT-WGHT", "WRITER"])
    today = date.today()
    out = []
    for r in rows:
        req = _d(str(r.get("required", "")))
        ordered = _d(str(r.get("date-ord", "")))
        out.append({
            "id": str(r.get("ID")), "from": str(r.get("from") or "").strip(), "to": str(r.get("to") or "").strip(),
            "mode": str(r.get("mode") or "").strip(), "ordered": _iso(ordered), "required": _iso(req),
            "shipped": _iso(_d(str(r.get("date-ship", "")))), "via": str(r.get("via-desc") or "").strip(),
            "weight": str(r.get("tot-wght") or "").strip(), "writer": str(r.get("writer") or "").strip(),
            "overdue": bool(req and req < today), "age": (today - ordered).days if ordered else None,
        })
    return out


def snapshot(client: LiveClient, days: int = 30, refresh: bool = False, log: Any = None) -> Result:
    """Everything the network view draws, cached for a few minutes (a refresh is ~15 s of TEST reads)."""
    say = log or (lambda _m: None)
    key = (client.base_url, days)
    with _LOCK:
        if not refresh and _CACHE["key"] == key and time.monotonic() - _CACHE["at"] < TTL_S:
            return _CACHE["value"]  # type: ignore[no-any-return]
    t0 = time.monotonic()
    say("Reading branches…")
    br = branches(client)
    since = (date.today() - timedelta(days=days)).strftime("%m/%d/%Y")
    say("Reading transfers in transit…")
    transit = _transfers(client, 'WITH MODE = "S"', 2000)
    say(f"Reading open transfers ordered since {since}…")
    open_ = _transfers(client, f'WITH MODE = "O" AND WITH DATE-ORD GE "{since}"', 6000)
    ids = {b["id"] for b in br}
    stats: dict[str, Result] = {b["id"]: {"out_open": 0, "in_open": 0, "out_transit": 0, "in_transit": 0,
                                          "overdue_in": 0, "overdue_out": 0} for b in br}
    lanes: dict[tuple[str, str], Result] = {}
    for t in [*transit, *open_]:
        f, to = t["from"], t["to"]
        kind = "transit" if t["mode"] == "S" else "open"
        if f in stats:
            stats[f][f"out_{kind}"] += 1
            stats[f]["overdue_out"] += t["overdue"]
        if to in stats:
            stats[to][f"in_{kind}"] += 1
            stats[to]["overdue_in"] += t["overdue"]
        if f in ids and to in ids and f != to:
            ln = lanes.setdefault((f, to), {"from": f, "to": to, "open": 0, "transit": 0, "overdue": 0,
                                            "vias": defaultdict(int)})
            ln[kind] += 1
            ln["overdue"] += t["overdue"]
            if t["via"]:
                ln["vias"][t["via"]] += 1
    lane_list = []
    for ln in lanes.values():
        ln["vias"] = sorted(ln["vias"], key=lambda v: -ln["vias"][v])[:3]
        lane_list.append(ln)
    lane_list.sort(key=lambda x: -(x["open"] + x["transit"]))
    for b in br:
        b.update(stats[b["id"]])
    today = date.today().isoformat()
    value = {
        "at": datetime.now().isoformat(timespec="seconds"), "days": days, "source": client.base_url,
        "branches": br, "lanes": lane_list,
        "transit": sorted(transit, key=lambda t: (not t["overdue"], t["required"] or "")),
        "open_count": len(open_), "open_capped": len(open_) >= 6000,
        "kpis": {
            "branches": len(br), "hubs": sum(b["hub"] for b in br), "cds": sum(b["cd"] for b in br),
            "in_transit": len(transit), "open": len(open_),
            "overdue": sum(t["overdue"] for t in [*transit, *open_]),
            "ordered_today": sum(1 for t in open_ if t["ordered"] == today),
            "lanes": len(lane_list),
        },
        "seconds": round(time.monotonic() - t0, 1),
    }
    with _LOCK:
        _CACHE.update(at=time.monotonic(), key=key, value=value)
    try:
        SAVED.write_text(json.dumps(value))
    except OSError:
        pass
    return value


def cached(client: LiveClient, days: int = 30) -> Result | None:
    """The last snapshot without touching TEST: memory first, then the saved copy."""
    with _LOCK:
        if _CACHE["key"] == (client.base_url, days) and _CACHE["value"]:
            return _CACHE["value"]  # type: ignore[no-any-return]
    try:
        v = json.loads(SAVED.read_text())
    except (OSError, ValueError):
        return None
    if v.get("days") != days or v.get("source") != client.base_url:
        return None
    with _LOCK:
        _CACHE.update(at=0.0, key=(client.base_url, days), value=v)    # stale: next refresh re-reads
    return v  # type: ignore[no-any-return]


def branch_detail(client: LiveClient, branch: str, days: int = 30) -> Result:
    snap = cached(client, days) or snapshot(client, days)
    b = next((x for x in snap["branches"] if x["id"] == branch), None)
    if b is None:
        raise ValueError(f"no branch {branch}")
    since = (date.today() - timedelta(days=days)).strftime("%m/%d/%Y")
    out_open = _transfers(client, f'WITH MODE = "O" AND WITH FROM = "{branch}" AND WITH DATE-ORD GE "{since}"', 300)
    in_open = _transfers(client, f'WITH MODE = "O" AND WITH TO = "{branch}" AND WITH DATE-ORD GE "{since}"', 300)
    transit_in = [t for t in snap["transit"] if t["to"] == branch]
    transit_out = [t for t in snap["transit"] if t["from"] == branch]
    names = {x["id"]: x for x in snap["branches"]}
    family = [x for x in snap["branches"] if x["mother"] == b["mother"] and x["id"] != b["id"]]
    return {**b, "mother_branch": names.get(b["mother"]), "family": family[:20],
            "inbound": {"transit": transit_in, "open": sorted(in_open, key=lambda t: t["required"] or "")[:100]},
            "outbound": {"transit": transit_out, "open": sorted(out_open, key=lambda t: t["required"] or "")[:100]},
            "lanes": [ln for ln in snap["lanes"] if branch in (ln["from"], ln["to"])][:12]}


def journey(client: LiveClient, xfn: str) -> Result:
    """One transfer: header, lines count, and its TRANSFER-LOG events in order."""
    rec = client.read_record("TRANSFER", xfn, refresh=True)
    if not any(rec.lines):
        raise ValueError(f"no transfer {xfn} on TEST (it may have been received and moved to history)")
    a = rec.lines

    def at(n: int) -> str:
        return a[n - 1] if len(a) >= n else ""

    def pdate(v: str) -> str | None:
        v = v.split(VM)[0].strip()
        return (PICK_EPOCH + timedelta(days=int(v))).isoformat() if v.isdigit() else None
    products = [x for x in at(27).split(VM) if x]
    events: list[Result] = []
    try:
        log = client.read_record("TRANSFER-LOG", xfn, refresh=True).lines
    except LiveError:
        log = []
    if log and any(log):
        cols = {k: (log[k - 1].split(VM) if len(log) >= k else []) for k in (1, 2, 3, 8, 9, 17)}
        for i, dv in enumerate(cols[1]):
            def g(k: int, i: int = i) -> str:
                return cols[k][i] if i < len(cols[k]) else ""
            secs = g(2)
            events.append({"date": pdate(dv), "time": f"{int(secs) // 3600:02d}:{int(secs) % 3600 // 60:02d}"
                           if secs.isdigit() else "", "user": g(3), "reason": g(8), "mode": g(9), "program": g(17)})
    return {"id": xfn, "from": at(1), "mode": at(2), "to": at(3), "ordered": pdate(at(9)), "required": pdate(at(10)),
            "shipped": pdate(at(11)), "received": pdate(at(12)), "via": at(16), "writer": at(13),
            "lines": len(products), "events": events}
