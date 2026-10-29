"""Data Profiler: what a Pick file really holds on TEST, attribute by attribute.

Samples records through the read-only python layer (query for keys, block reads for
records), then for every attribute measures fill rate, multivalue use, lengths, value
kinds and top values, and checks them against the DICT (S/M, conversion) and against
the files the code looks its values up in (`READ X FROM BRANCHFILE, XF<3>` means
TRANSFER<3> holds BRANCH keys). Only aggregates are stored, never whole records.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from atlas import dictmodel
from atlas.sources.live import LiveClient, LiveError, NotAllowed
from atlas.store.db import Store, now

Result = dict[str, Any]
VM, SM = "\xfd", "\xfc"
BLOCK = 200                       # records per block read
DISTINCT_CAP = 5000               # distinct values tracked per attribute
DATE_LO, DATE_HI = 4384, 25568    # Pick day numbers for 1980-01-01 .. 2037-12-31
_INT = re.compile(r"^-?\d+$")
_DEC = re.compile(r"^-?\d*\.\d+$")
_REF_KEY = re.compile(r"^\s*([A-Z0-9.$_]+)\s*<\s*(\d+)\s*(?:,[^>]*)?>\s*$")
_READS = ("READ", "READU", "READV", "READVU", "MATREAD", "MATREADU")
_WORKFILE = re.compile(r"(^&|WK$|WORK$|TEMP$|TMP$|SCRATCH|^SORT)")


def _norm(v: str) -> str:
    for a, b in (("", VM), ("", SM), ("ý", VM), ("ü", SM)):
        v = v.replace(a, b)
    return v


def _shape(key: str) -> str:
    """22043738 -> 9{8}; C11027-2 -> A9{5}-9."""
    s = re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", key))
    return re.sub(r"(9{2,}|A{2,})", lambda m: f"{m.group(0)[0]}{{{len(m.group(0))}}}", s)


# ------------------------------------------------------------------ what the code says

def key_references(store: Store, table: str) -> dict[int, list[Result]]:
    """attr -> files the code reads using that attribute as the key, with how many programs do it."""
    recvars: dict[str, set[str]] = defaultdict(set)
    for r in store.db.execute("SELECT program, record_var FROM io_op WHERE provenance='git' AND pick_file=? "
                              "AND op IN ('READ','READU','MATREAD','MATREADU') AND record_var != ''", (table,)):
        recvars[r["program"]].add(r["record_var"].upper())
    progs: dict[tuple[int, str], set[str]] = defaultdict(set)
    marks = ",".join("?" * len(_READS))
    for r in store.db.execute(f"SELECT program, pick_file, key_expr FROM io_op WHERE provenance='git' AND op IN "
                              f"({marks}) AND pick_file != ?", (*_READS, table)):
        vs = recvars.get(r["program"])
        m = _REF_KEY.match((r["key_expr"] or "").upper()) if vs else None
        if m and vs and m.group(1) in vs and not _WORKFILE.search(r["pick_file"]):
            progs[(int(m.group(2)), r["pick_file"])].add(r["program"])
    out: dict[int, list[Result]] = defaultdict(list)
    for (attr, f), ps in progs.items():
        out[attr].append({"file": f, "programs": len(ps), "examples": sorted(ps)[:3]})
    for v in out.values():
        v.sort(key=lambda x: -x["programs"])
    return out


def writers(store: Store, table: str) -> dict[int, int]:
    return {r["attr"]: r["n"] for r in store.db.execute(
        "SELECT attr, COUNT(DISTINCT program) n FROM attr_ref WHERE provenance='git' AND pick_file=? "
        "AND access='write' GROUP BY attr", (table,))}


# ------------------------------------------------------------------ sampling

def sample(client: LiveClient, table: str, size: int, log: Any) -> tuple[dict[str, list[str]], int]:
    """Up to `size` records. Keys come from the file's first 4x`size` in file order, then a random
    pick among them, so one hash group doesn't dominate. Returns (records, keys seen)."""
    ids = client.list_ids(table, min(max(size * 4, size), 20000))
    log(f"Listed {len(ids):,} record keys from {table}")
    pick = ids if len(ids) <= size else random.Random(42).sample(ids, size)
    batches = [pick[i:i + BLOCK] for i in range(0, len(pick), BLOCK)]
    recs: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, getattr(client, "parallel", 1))) as pool:
        for i, got in enumerate(pool.map(lambda b: client.read_block(table, b), batches), 1):
            recs.update({k: v for k, v in got.items() if v})
            log(f"[{i}/{len(batches)}] read {len(recs):,} of {len(pick):,} records")
    return recs, len(ids)


# ------------------------------------------------------------------ profiling

class _Attr:
    def __init__(self) -> None:
        self.filled = self.multi = self.sub = 0
        self.nvals: list[int] = []
        self.lens: list[int] = []
        self.values: Counter[str] = Counter()
        self.overflow = False
        self.kinds: Counter[str] = Counter()
        self.bad_date: list[str] = []
        self.bad_time: list[str] = []
        self.flags: Counter[str] = Counter()

    def add(self, raw: str) -> None:
        v = _norm(raw)
        if v.replace(VM, "").replace(SM, "") == "":
            return
        self.filled += 1
        parts = v.split(VM)
        if len(parts) > 1:
            self.multi += 1
        if SM in v:
            self.sub += 1
        self.nvals.append(len(parts))
        self.lens.append(len(v))
        if "�" in v:
            self.flags["fffd"] += 1
        for p in parts:
            for x in p.split(SM):
                if x == "":
                    continue
                if x != x.strip() and " " not in x.strip():
                    self.flags["spaces"] += 1        # a code/number with stray spaces; free text is fine
                if any(ord(c) < 32 for c in x):
                    self.flags["control"] += 1
                if _INT.match(x):
                    self.kinds["int"] += 1
                elif _DEC.match(x):
                    self.kinds["dec"] += 1
                else:
                    self.kinds["text"] += 1
                if x in self.values or len(self.values) < DISTINCT_CAP:
                    self.values[x] += 1
                else:
                    self.overflow = True


def _problem(level: str, code: str, text: str) -> Result:
    return {"level": level, "code": code, "text": text}


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def analyse(table: str, recs: dict[str, list[str]], dict_fields: list[Result],
            refs: dict[int, list[Result]], wr: dict[int, int]) -> Result:
    n = len(recs)
    width = max([len(v) for v in recs.values()] + [f["pos"] for f in dict_fields] + [0])
    attrs = [_Attr() for _ in range(width + 1)]
    for lines in recs.values():
        for i, raw in enumerate(lines, 1):
            attrs[i].add(raw)
    by_pos = {f["pos"]: f for f in dict_fields}
    shapes = Counter(_shape(k) for k in recs)
    out_attrs = []
    for pos in range(1, width + 1):
        a, d = attrs[pos], by_pos.get(pos)
        if not a.filled and not d:
            continue
        vals = sum(a.kinds.values())
        numeric = a.kinds["int"] + a.kinds["dec"]
        distinct = len(a.values)
        dfmt = (d or {}).get("format", "")
        # what the values look like
        if not a.filled:
            kind = "empty"
        elif dfmt == "date" or (vals and a.kinds["int"] == vals and d and "DATE" in d["uv"].upper()):
            kind = "date"
        elif dfmt == "time":
            kind = "time"
        elif vals and numeric >= 0.98 * vals:
            kind = "decimal" if a.kinds["dec"] else "integer"
        elif distinct <= 30 and a.lens and sum(a.lens) / len(a.lens) <= 8 and a.filled >= 20:
            kind = "code"
        else:
            kind = "text"
        if kind == "date":
            for x in a.values:
                if not (_INT.match(x) and DATE_LO <= int(x) <= DATE_HI):
                    a.bad_date.append(x)
        if kind == "time":
            for x in a.values:
                if not (_INT.match(x) and 0 <= int(x) <= 86400):
                    a.bad_time.append(x)
        p: list[Result] = []
        names = [d["uv"], *d.get("aliases", [])] if d else []
        if not d and a.filled:
            by = f"; written by {wr[pos]} program{'s' if wr[pos] != 1 else ''}" if wr.get(pos) else ""
            p.append(_problem("warn", "undocumented",
                              f"Not in the DICT but filled in {_pct(a.filled, n)}% of records{by}"))
        if d and not a.filled:
            p.append(_problem("info", "unused", "In the DICT but empty in every sampled record"))
        if d and d["sm"] == "S" and a.multi:
            p.append(_problem("warn", "sm", f"DICT says single-valued, but {_pct(a.multi, a.filled)}% of filled "
                              f"records hold several values (up to {max(a.nvals)})"))
        if a.bad_date:
            bad = sum(a.values[x] for x in a.bad_date)
            p.append(_problem("error" if dfmt == "date" else "warn", "date",
                              f"{bad} value{'s' if bad != 1 else ''} aren't dates between 1980 and 2037, e.g. "
                              + ", ".join(repr(x) for x in a.bad_date[:3])))
        if a.bad_time:
            bad = sum(a.values[x] for x in a.bad_time)
            p.append(_problem("warn", "time", f"{bad} values aren't times of day (0-86400 seconds), e.g. "
                              + ", ".join(repr(x) for x in a.bad_time[:3])))
        if dfmt in ("number", "decimal") and vals and numeric < vals:
            odd = [x for x in a.values if not (_INT.match(x) or _DEC.match(x))][:3]
            p.append(_problem("error", "number", f"{vals - numeric} values aren't numbers, e.g. "
                              + ", ".join(repr(x) for x in odd)))
        if a.flags["fffd"]:
            p.append(_problem("error", "fffd", f"{a.flags['fffd']} records hold U+FFFD: value marks destroyed by a bad "
                              "character conversion; not recoverable from the data"))
        if a.flags["control"]:
            p.append(_problem("warn", "control", f"{a.flags['control']} values contain control characters"))
        if a.flags["spaces"]:
            p.append(_problem("warn", "spaces", f"{a.flags['spaces']} single-word values have leading or trailing "
                              "spaces (a lookup by this value would miss)"))
        if kind == "code":
            lower = defaultdict(set)
            for x in a.values:
                lower[x.upper()].add(x)
            clash = [sorted(v) for v in lower.values() if len(v) > 1]
            if clash:
                p.append(_problem("warn", "case", "Same code in different case: "
                                  + "; ".join("/".join(c) for c in clash[:3])))
        if a.lens and max(a.lens) > 250:
            p.append(_problem("info", "long", f"Longest value is {max(a.lens)} characters"))
        if a.filled and a.filled >= 0.995 * n and n >= 50:
            p.append(_problem("info", "required", "Filled in every sampled record: likely required"))
        top = a.values.most_common(8)
        out_attrs.append({
            "pos": pos, "names": names, "dict": {k: d[k] for k in ("sm", "format", "conv")} if d else None,
            "filled": a.filled, "filled_pct": _pct(a.filled, n),
            "multi_pct": _pct(a.multi, a.filled), "max_values": max(a.nvals) if a.nvals else 0,
            "avg_values": round(sum(a.nvals) / len(a.nvals), 2) if a.nvals else 0,
            "sub_pct": _pct(a.sub, a.filled),
            "len_min": min(a.lens) if a.lens else 0, "len_max": max(a.lens) if a.lens else 0,
            "len_avg": round(sum(a.lens) / len(a.lens), 1) if a.lens else 0,
            "distinct": distinct, "distinct_capped": a.overflow, "kind": kind,
            "top": [[v[:80], c] for v, c in top] if distinct <= max(40, n // 10) else [],
            "writers": wr.get(pos, 0), "refs": [dict(r) for r in refs.get(pos, [])][:4],
            "problems": p,
        })
    return {"records": n, "width": width, "key_shapes": shapes.most_common(6), "attributes": out_attrs}


def check_references(client: LiveClient, table: str, recs: dict[str, list[str]], result: Result,
                     log: Any, per_ref: int = 200, max_refs: int = 8) -> None:
    """For the strongest code-derived references, read the distinct sampled values from the target
    file and count the ones that aren't keys there."""
    todo = []
    for a in result["attributes"]:
        for r in a["refs"]:
            if r["programs"] >= 2 or len(a["refs"]) == 1:
                todo.append((r["programs"], a, r))
    todo.sort(key=lambda t: -t[0])
    for _, a, ref in todo[:max_refs]:
        pos = a["pos"]
        vals: Counter[str] = Counter()
        for lines in recs.values():
            if pos <= len(lines):
                for v in _norm(lines[pos - 1]).split(VM):
                    v = v.split(SM)[0].strip()
                    if v:
                        vals[v] += 1
        keys = [v for v, _ in vals.most_common(per_ref)]
        if not keys:
            continue
        try:
            got = client.read_block(ref["file"], keys)
        except NotAllowed:
            ref["skipped"] = "sensitive file: not read"
            continue
        except LiveError as e:
            ref["skipped"] = str(e)[:120]
            continue
        missing = [k for k in keys if not got.get(k)]
        ref.update(checked=len(keys), missing=len(missing), missing_examples=missing[:5],
                   missing_records=sum(vals[k] for k in missing))
        log(f"Checked <{pos}> against {ref['file']}: {len(missing)} of {len(keys)} values not found")
    # judge each attribute's references together: code often reads several files with the same field
    # (a from-branch that is sometimes a customer); the file the values mostly match is the real one
    for a in result["attributes"]:
        checked = [r for r in a["refs"] if "checked" in r]
        if not checked:
            continue
        best = min(checked, key=lambda r: r["missing"] / r["checked"])
        for r in checked:
            if not r["missing"]:
                continue
            share = _pct(r["missing"], r["checked"])
            eg = ", ".join(repr(x) for x in r["missing_examples"][:3])
            if r is not best and best["missing"] / best["checked"] < 0.05:
                a["problems"].append(_problem("info", "ref-other", f"Mostly holds {best['file']} keys; "
                                              f"{r['missing']} of {r['checked']} values aren't in {r['file']} "
                                              f"(some programs read {r['file']} with it), e.g. {eg}"))
                continue
            level = "error" if share >= 5 and r["programs"] >= 2 else "warn"
            who = f"{r['programs']} program{'s look' if r['programs'] != 1 else ' looks'}"
            a["problems"].append(_problem(level, "ref", f"{r['missing']} of {r['checked']} distinct values aren't "
                                          f"keys in {r['file']} ({who} it up by this field), e.g. {eg}"))


def run(store: Store, client: LiveClient, table: str, size: int = 1000, log: Any = print,
        env: str = "TEST", sha: str = "") -> Result:
    table = table.strip().upper()
    size = max(50, min(int(size), 5000))
    started = now()
    try:
        dfields = dictmodel.get(store, table)["fields"]
    except ValueError:
        dfields = []
    log(f"DICT: {len(dfields)} attributes described" if dfields else f"{table} has no DICT in git: profiling data only")
    refs = key_references(store, table)
    log(f"Code: {sum(len(v) for v in refs.values())} lookups use {table} fields as keys of other files")
    recs, seen = sample(client, table, size, log)
    if not recs:
        raise ValueError(f"no records read from {table} on {env}")
    log(f"Profiling {len(recs):,} records…")
    res = analyse(table, recs, dfields, refs, writers(store, table))
    check_references(client, table, recs, res, log)
    res["keys_seen"] = seen
    errors = sum(1 for a in res["attributes"] for p in a["problems"] if p["level"] == "error")
    warnings = sum(1 for a in res["attributes"] for p in a["problems"] if p["level"] == "warn")
    rid = uuid.uuid4().hex[:10]
    store.db.execute("INSERT INTO profile_run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (rid, table, size, len(recs), started, now(), client.base_url, env, sha, errors, warnings,
                      json.dumps(res)))
    store.commit()
    log(f"Done: {errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}")
    return get(store, rid)


def get(store: Store, rid: str) -> Result:
    r = store.db.execute("SELECT * FROM profile_run WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise ValueError(f"no profile {rid}")
    return {**{k: r[k] for k in r.keys() if k != "result"}, **json.loads(r["result"])}


def latest(store: Store, table: str) -> Result | None:
    r = store.db.execute("SELECT id FROM profile_run WHERE pick_file=? ORDER BY finished_at DESC LIMIT 1",
                         (table.upper(),)).fetchone()
    return get(store, r["id"]) if r else None


def history(store: Store, table: str | None = None, limit: int = 50) -> list[Result]:
    q = "SELECT id, pick_file, sample, records, finished_at, errors, warnings, environment FROM profile_run"
    args: tuple[Any, ...] = ()
    if table:
        q += " WHERE pick_file=?"
        args = (table.upper(),)
    rows = store.db.execute(q + " ORDER BY finished_at DESC LIMIT ?", (*args, limit))
    return [dict(r) for r in rows]


def overview(store: Store) -> list[Result]:
    """Latest profile per file, worst first (for the dashboard / list page)."""
    rows = store.db.execute(
        "SELECT p.id, p.pick_file, p.records, p.finished_at, p.errors, p.warnings FROM profile_run p JOIN "
        "(SELECT pick_file, MAX(finished_at) m FROM profile_run GROUP BY pick_file) l "
        "ON l.pick_file = p.pick_file AND l.m = p.finished_at ORDER BY p.errors DESC, p.warnings DESC")
    return [dict(r) for r in rows]


def model_hints(store: Store, table: str) -> dict[int, Result]:
    """What the data says the model export should be, where it disagrees with the DICT."""
    prof = latest(store, table)
    if not prof:
        return {}
    out: dict[int, Result] = {}
    for a in prof["attributes"]:
        h: Result = {}
        if a["dict"] and a["dict"]["sm"] == "S" and a["multi_pct"] > 0:
            h["sm"] = "M"
        if a["dict"] and a["dict"]["format"] == "string" and a["kind"] in ("date", "integer", "decimal") \
                and a["filled"] >= 20:
            h["format"] = {"integer": "number"}.get(a["kind"], a["kind"])
        if a["filled_pct"] >= 99.5 and prof["records"] >= 50:
            h["required"] = True
        if h:
            out[a["pos"]] = h
    return out
