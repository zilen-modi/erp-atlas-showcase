"""Compare: old-system vs new-system records, field by field, at each step of a flow.

A *flow* is a named list of *steps* (After create, After ship, ...) and the Pick
*files* it touches, each with a key template ({key}, {num}, {key}-1, T{num}, ...).
{key} is the run's key as typed; {num} is the same key without its letter prefix
(T11027 -> 11027), because files of one flow often key the same document differently.  A *run* is
one test of a flow: an old-system key and a new-system key.  At each step the
user captures both sides from TEST; Atlas diffs them attribute by attribute and
also shows what each step changed on each side.  Notes on a field are kept on
the flow, so they show again on every later run.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from atlas.sources.live import LiveClient, LiveError
from atlas.store.db import Store, now

SIDES = ("legacy", "new")
VERDICTS = ("expected", "bug", "question", "fixed")
VM, SM = "\xfd", "\xfc"
# MultiValue marks can arrive raw, as their PUA code points, or (after a lossy hop) as the
# latin-1 characters of the raw byte -- normalise all of them to the raw marks.
_MARKS = {"": VM, "": SM, "": "\xfb", "ý": VM, "ü": SM}
PICK_EPOCH = date(1967, 12, 31)

Result = dict[str, Any]


class CompareError(ValueError):
    pass


def _id() -> str:
    return uuid.uuid4().hex[:10]


def normalise(value: str) -> str:
    for a, b in _MARKS.items():
        value = value.replace(a, b)
    return value


def split_values(value: str) -> list[list[str]]:
    """Attribute -> values -> subvalues."""
    return [v.split(SM) for v in normalise(value).split(VM)]


def display(value: str) -> str:
    return normalise(value).replace(VM, " ] ").replace(SM, " \\ ")


def _pick_date(v: str) -> str | None:
    try:
        n = int(v)
    except ValueError:
        return None
    if not 0 < n < 40000:
        return None
    return (PICK_EPOCH + timedelta(days=n)).isoformat()


# ------------------------------------------------------------------ flows

def list_flows(store: Store) -> list[Result]:
    def count(table: str, flow_id: str) -> int:
        return int(store.db.execute(f"SELECT COUNT(*) c FROM {table} WHERE flow_id=?", (flow_id,)).fetchone()["c"])

    rows = []
    for f in store.db.execute("SELECT * FROM cmp_flow ORDER BY updated_at DESC").fetchall():
        fid = f["id"]
        last = store.db.execute("SELECT MAX(updated_at) m FROM cmp_run WHERE flow_id=?", (fid,)).fetchone()["m"]
        rows.append({**dict(f), "steps": count("cmp_step", fid), "files": count("cmp_file", fid),
                     "runs": count("cmp_run", fid), "last_run": last})
    return rows


def get_flow(store: Store, flow_id: str) -> Result:
    f = store.db.execute("SELECT * FROM cmp_flow WHERE id=?", (flow_id,)).fetchone()
    if f is None:
        raise CompareError(f"no flow {flow_id}")
    steps = [dict(r) for r in store.db.execute("SELECT * FROM cmp_step WHERE flow_id=? ORDER BY seq", (flow_id,))]
    files = [dict(r) for r in store.db.execute("SELECT * FROM cmp_file WHERE flow_id=? ORDER BY seq", (flow_id,))]
    runs = [dict(r) for r in store.db.execute("SELECT * FROM cmp_run WHERE flow_id=? ORDER BY created_at DESC",
                                              (flow_id,))]
    notes = store.db.execute("SELECT COUNT(*) c FROM cmp_note WHERE flow_id=?", (flow_id,)).fetchone()["c"]
    return {**dict(f), "steps": steps, "files": files, "runs": runs, "notes": notes}


def save_flow(store: Store, body: Result, flow_id: str | None = None) -> str:
    """Create or replace a flow definition. Steps/files keep their ids when passed back,
    so captures and notes stay attached across edits."""
    name = str(body.get("name") or "").strip()
    if not name:
        raise CompareError("a flow needs a name")
    steps = [s for s in body.get("steps") or [] if str(s.get("name") or "").strip()]
    files = [f for f in body.get("files") or [] if str(f.get("pick_file") or "").strip()]
    if not steps:
        raise CompareError("add at least one step, e.g. 'After create'")
    if not files:
        raise CompareError("add at least one file the flow touches")
    ts = now()
    if flow_id is None:
        flow_id = _id()
        store.db.execute("INSERT INTO cmp_flow VALUES (?,?,?,?,?)",
                         (flow_id, name, body.get("description", ""), ts, ts))
    else:
        get_flow(store, flow_id)
        store.db.execute("UPDATE cmp_flow SET name=?, description=?, updated_at=? WHERE id=?",
                         (name, body.get("description", ""), ts, flow_id))
    keep_steps, keep_files = [], []
    for i, s in enumerate(steps):
        sid = s.get("id") or _id()
        keep_steps.append(sid)
        store.db.execute("INSERT OR REPLACE INTO cmp_step VALUES (?,?,?,?)", (sid, flow_id, i, s["name"].strip()))
    for i, f in enumerate(files):
        fid = f.get("id") or _id()
        keep_files.append(fid)
        tpl = str(f.get("key_template") or "{key}").strip() or "{key}"
        store.db.execute("INSERT OR REPLACE INTO cmp_file VALUES (?,?,?,?,?,?)",
                         (fid, flow_id, i, f["pick_file"].strip().upper(), tpl, f.get("note", "")))
    for table, keep in (("cmp_step", keep_steps), ("cmp_file", keep_files)):
        marks = ",".join("?" * len(keep))
        store.db.execute(f"DELETE FROM {table} WHERE flow_id=? AND id NOT IN ({marks})", (flow_id, *keep))
    store.commit()
    return flow_id


def delete_flow(store: Store, flow_id: str) -> None:
    runs = [r["id"] for r in store.db.execute("SELECT id FROM cmp_run WHERE flow_id=?", (flow_id,))]
    for r in runs:
        delete_run(store, r, commit=False)
    for t in ("cmp_step", "cmp_file", "cmp_note"):
        store.db.execute(f"DELETE FROM {t} WHERE flow_id=?", (flow_id,))
    store.db.execute("DELETE FROM cmp_flow WHERE id=?", (flow_id,))
    store.commit()


# ------------------------------------------------------------------ runs

def create_run(store: Store, flow_id: str, legacy_key: str, new_key: str, name: str = "") -> str:
    get_flow(store, flow_id)
    if not legacy_key.strip() and not new_key.strip():
        raise CompareError("enter the old-system key, the new-system key, or both")
    rid, ts = _id(), now()
    store.db.execute("INSERT INTO cmp_run VALUES (?,?,?,?,?,?,?)",
                     (rid, flow_id, name.strip() or f"{legacy_key.strip() or '—'} vs {new_key.strip() or '—'}",
                      legacy_key.strip(), new_key.strip(), ts, ts))
    store.commit()
    return rid


def update_run(store: Store, run_id: str, body: Result) -> None:
    run = _run(store, run_id)
    store.db.execute("UPDATE cmp_run SET name=?, legacy_key=?, new_key=?, updated_at=? WHERE id=?",
                     (body.get("name", run["name"]), body.get("legacy_key", run["legacy_key"]).strip(),
                      body.get("new_key", run["new_key"]).strip(), now(), run_id))
    for o in body.get("overrides") or []:
        if o.get("key", "").strip():
            store.db.execute("INSERT OR REPLACE INTO cmp_run_key VALUES (?,?,?,?)",
                             (run_id, o["file_id"], o["side"], o["key"].strip()))
        else:
            store.db.execute("DELETE FROM cmp_run_key WHERE run_id=? AND file_id=? AND side=?",
                             (run_id, o["file_id"], o["side"]))
    store.commit()


def delete_run(store: Store, run_id: str, commit: bool = True) -> None:
    for t in ("cmp_snapshot", "cmp_run_key"):
        store.db.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
    store.db.execute("DELETE FROM cmp_note WHERE run_id=?", (run_id,))
    store.db.execute("DELETE FROM cmp_run WHERE id=?", (run_id,))
    if commit:
        store.commit()


def _run(store: Store, run_id: str) -> Any:
    r = store.db.execute("SELECT * FROM cmp_run WHERE id=?", (run_id,)).fetchone()
    if r is None:
        raise CompareError(f"no run {run_id}")
    return r


_PREFIXED = re.compile(r"^([A-Za-z]+)(\d.*)$")


def split_key(key: str) -> tuple[str, str]:
    """T11027 -> ("T", "11027"); 11027 -> ("", "11027")."""
    m = _PREFIXED.match(key)
    return (m.group(1), m.group(2)) if m else ("", key)


def resolve_key(template: str, key: str) -> str:
    if not key:
        return ""
    return template.replace("{key}", key).replace("{num}", split_key(key)[1])


def template_variants(template: str, prefixes: set[str]) -> list[str]:
    """Other patterns to try when a record isn't under the flow's pattern: the key
    without its prefix, and with each letter prefix seen elsewhere in the run/flow."""
    if "{key}" not in template and "{num}" not in template:
        return []
    bare = template.replace("{key}", "{num}")
    found = re.match(r"^(.*?)\{num\}", bare)
    lead = re.sub(r"[A-Za-z]+$", "", found.group(1)) if found else ""
    rest = bare[found.end():] if found else ""
    out = [f"{lead}{{num}}{rest}"] + [f"{lead}{p}{{num}}{rest}" for p in sorted(prefixes)]
    return [t for t in dict.fromkeys(out) if t != template]


def find_record(client: LiveClient, pick_file: str, template: str, key: str,
                prefixes: set[str]) -> tuple[str, str, list[str], str | None]:
    """Read pick_file under the pattern, falling back to key variants.
    Returns (template used, record key, lines, error). Connection errors propagate."""
    tried: set[str] = set()
    for tpl in [template, *template_variants(template, prefixes)]:
        rk = resolve_key(tpl, key)
        if not rk or rk in tried:
            continue
        tried.add(rk)
        try:
            rec = client.read_record(pick_file, rk, refresh=True)
        except LiveError as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                continue
            raise
        if any(x != "" for x in rec.lines):
            return tpl, rk, rec.lines, None
    return template, resolve_key(template, key), [], "record not found"


def key_prefixes(store: Store, run_id: str) -> set[str]:
    """Letter prefixes worth trying: from the run's keys and the flow's literal patterns."""
    run = _run(store, run_id)
    out = {split_key(run[f"{s}_key"] or "")[0].upper() for s in SIDES}
    for f in store.db.execute("SELECT key_template FROM cmp_file WHERE flow_id=?", (run["flow_id"],)):
        m = re.search(r"([A-Za-z]+)\{(?:key|num)\}", f["key_template"])
        if m:
            out.add(m.group(1).upper())
    return {p for p in out if p}


def keys_for(store: Store, run_id: str) -> dict[str, dict[str, str]]:
    """file_id -> side -> record key (template applied, then per-run override)."""
    run = _run(store, run_id)
    over = {(r["file_id"], r["side"]): r["key"] for r in store.db.execute(
        "SELECT * FROM cmp_run_key WHERE run_id=?", (run_id,))}
    out: dict[str, dict[str, str]] = {}
    for f in store.db.execute("SELECT * FROM cmp_file WHERE flow_id=?", (run["flow_id"],)):
        out[f["id"]] = {
            side: over.get((f["id"], side)) or resolve_key(f["key_template"], run[f"{side}_key"] or "")
            for side in SIDES}
    return out


def get_run(store: Store, run_id: str) -> Result:
    run = dict(_run(store, run_id))
    flow = get_flow(store, run["flow_id"])
    keys = keys_for(store, run_id)
    over = {(r["file_id"], r["side"]) for r in store.db.execute("SELECT * FROM cmp_run_key WHERE run_id=?", (run_id,))}
    caps: dict[str, dict[str, Any]] = {}
    for r in store.db.execute("SELECT step_id, side, MAX(fetched_at) at, SUM(found) found, COUNT(*) n "
                              "FROM cmp_snapshot WHERE run_id=? GROUP BY step_id, side", (run_id,)):
        caps.setdefault(r["step_id"], {})[r["side"]] = {"at": r["at"], "found": r["found"], "files": r["n"]}
    return {**run, "flow": {k: flow[k] for k in ("id", "name", "description")},
            "steps": [{**s, "captured": caps.get(s["id"], {})} for s in flow["steps"]],
            "files": [{**f, "keys": keys.get(f["id"], {}),
                       "overridden": [s for s in SIDES if (f["id"], s) in over]} for f in flow["files"]]}


# ------------------------------------------------------------------ capture

def capture(store: Store, client: LiveClient, run_id: str, step_id: str,
            sides: tuple[str, ...] = SIDES, log: Any = print) -> Result:
    run = _run(store, run_id)
    step = store.db.execute("SELECT 1 FROM cmp_step WHERE id=? AND flow_id=?", (step_id, run["flow_id"])).fetchone()
    if step is None:
        raise CompareError("that step is not part of this run's flow")
    keys = keys_for(store, run_id)
    rows = list(store.db.execute("SELECT * FROM cmp_file WHERE flow_id=? ORDER BY seq", (run["flow_id"],)))
    files = {f["id"]: f["pick_file"] for f in rows}
    templates = {f["id"]: f["key_template"] for f in rows}
    over = {(r["file_id"], r["side"]) for r in store.db.execute(
        "SELECT file_id, side FROM cmp_run_key WHERE run_id=?", (run_id,))}
    prefixes = key_prefixes(store, run_id)
    tasks = [(side, fid) for side in sides for fid in files if keys[fid][side]]
    total, done = len(tasks), 0

    def read(side: str, fid: str) -> tuple[str, str, list[str], str | None]:
        if (fid, side) in over:
            # the user typed this exact key: read it as is
            return find_record(client, files[fid], "{key}", keys[fid][side], set())
        return find_record(client, files[fid], templates[fid], run[f"{side}_key"], prefixes)

    # reads run in parallel (the client caps calls in flight); DB writes and logging stay on this thread
    pool = ThreadPoolExecutor(max_workers=max(1, getattr(client, "parallel", 1)))
    try:
        futures = {pool.submit(read, side, fid): (side, fid) for side, fid in tasks}
        for fut in as_completed(futures):
            side, fid = futures[fut]
            pick_file, who = files[fid], ("old" if side == "legacy" else "new")
            tpl, rk, lines, err = fut.result()          # a connection error propagates and stops the capture
            if err is None and (fid, side) not in over and tpl != templates[fid]:
                # this file keys the document differently: remember it on the flow for every run
                store.db.execute("UPDATE cmp_file SET key_template=? WHERE id=?", (tpl, fid))
                log(f"{pick_file}: nothing under {keys[fid][side]}, found {rk}. Pattern for {pick_file} is now {tpl}.")
                templates[fid] = tpl
            found = 0 if err else 1
            h = hashlib.sha256(json.dumps(lines).encode("utf-8", "surrogatepass")).hexdigest()[:16]
            store.db.execute("INSERT OR REPLACE INTO cmp_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (run_id, step_id, side, fid, rk, found, json.dumps(lines), h, err, now()))
            store.commit()
            done += 1
            log(f"[{done}/{total}] {who} {pick_file} {rk}: {f'{len(lines)} attributes' if found else err}")
    finally:
        pool.shutdown(wait=True, cancel_futures=True)   # on cancel/error: drop queued reads, let in-flight ones end
    store.db.execute("UPDATE cmp_run SET updated_at=? WHERE id=?", (now(), run_id))
    store.commit()
    # the first file of a flow is its main record: say so plainly when a side doesn't have it
    first = rows[0]["id"] if rows else None
    for side in sides:
        if first:
            snap = store.db.execute("SELECT found, record_key FROM cmp_snapshot WHERE run_id=? AND step_id=? "
                                    "AND side=? AND file_id=?", (run_id, step_id, side, first)).fetchone()
            if snap and not snap["found"]:
                who = "old" if side == "legacy" else "new"
                log(f"WARNING: {who} system has no {files[first]} {snap['record_key']} on TEST. "
                    f"Check the key under Keys.")
    return {"captured": done}


# ------------------------------------------------------------------ diff

def _snap(store: Store, run_id: str, step_id: str, side: str, file_id: str) -> Any:
    return store.db.execute("SELECT * FROM cmp_snapshot WHERE run_id=? AND step_id=? AND side=? AND file_id=?",
                            (run_id, step_id, side, file_id)).fetchone()


def _dict(store: Store, pick_file: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for r in store.db.execute("SELECT attr, name, conv FROM dict_attr WHERE pick_file=? AND type IN ('A','D') "
                              "ORDER BY attr", (pick_file,)):
        d = out.setdefault(r["attr"], {"names": [], "date": False})
        if r["name"] not in d["names"]:
            d["names"].append(r["name"])
        if str(r["conv"] or "").upper().startswith("D"):
            d["date"] = True
    return out


def _notes(store: Store, flow_id: str, run_id: str, pick_file: str) -> dict[int, list[Result]]:
    out: dict[int, list[Result]] = {}
    for r in store.db.execute("SELECT * FROM cmp_note WHERE flow_id=? AND pick_file=? AND (run_id IS NULL OR run_id=?) "
                              "ORDER BY created_at", (flow_id, pick_file, run_id)):
        out.setdefault(r["attr"], []).append({**dict(r), "scope": "flow" if r["run_id"] is None else "run"})
    return out


def _cell(value: str, is_date: bool) -> Result:
    vals = split_values(value)
    shown = display(value)
    hint = None
    if is_date and value and VM not in normalise(value):
        hint = _pick_date(value)
    return {"raw": value, "display": shown, "values": len(vals) if value else 0, "date": hint,
            "list": vals if value else []}


def _status(a: str, b: str) -> str:
    a, b = normalise(a), normalise(b)
    if a == b:
        return "same"
    if not a:
        return "new-only"
    if not b:
        return "old-only"
    return "different"


def _files(store: Store, flow_id: str) -> list[Result]:
    return [dict(f) for f in store.db.execute("SELECT * FROM cmp_file WHERE flow_id=? ORDER BY seq", (flow_id,))]


def diff(store: Store, run_id: str, step_id: str) -> Result:
    run = _run(store, run_id)
    files = _files(store, run["flow_id"])
    out = []
    for f in files:
        a_s, b_s = _snap(store, run_id, step_id, "legacy", f["id"]), _snap(store, run_id, step_id, "new", f["id"])
        a = json.loads(a_s["lines"]) if a_s and a_s["found"] else []
        b = json.loads(b_s["lines"]) if b_s and b_s["found"] else []
        dic = _dict(store, f["pick_file"])
        notes = _notes(store, run["flow_id"], run_id, f["pick_file"])
        rows = []
        width = max(len(a), len(b))
        for i in range(width):
            va = a[i] if i < len(a) else ""
            vb = b[i] if i < len(b) else ""
            st = _status(va, vb)
            n = notes.get(i + 1, [])
            if st == "same" and not va and not n:
                continue                      # empty on both sides: nothing to show
            d = dic.get(i + 1, {"names": [], "date": False})
            rows.append({"attr": i + 1, "names": d["names"], "status": st, "old": _cell(va, d["date"]),
                         "new": _cell(vb, d["date"]), "notes": n})
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        explained = sum(1 for r in rows if r["status"] != "same" and any(x["verdict"] in ("expected", "fixed")
                                                                          for x in r["notes"]))
        out.append({"file_id": f["id"], "pick_file": f["pick_file"], "note": f["note"],
                    "old": _snapinfo(a_s), "new": _snapinfo(b_s), "rows": rows, "counts": counts,
                    "differences": sum(v for k, v in counts.items() if k != "same"), "explained": explained})
    return {"run_id": run_id, "step_id": step_id, "files": out}


def _snapinfo(s: Any) -> Result | None:
    if s is None:
        return None
    return {"key": s["record_key"], "found": bool(s["found"]), "error": s["error"], "at": s["fetched_at"]}


def _at(snaps: dict[tuple[str, str], list[str] | None], side: str, step: str, i: int) -> str:
    v = snaps[(side, step)]
    return v[i] if v and i < len(v) else ""


def changes(store: Store, run_id: str, from_step: str, to_step: str) -> Result:
    """What each side changed between two steps, attribute by attribute."""
    run = _run(store, run_id)
    files = _files(store, run["flow_id"])
    out = []
    for f in files:
        snaps: dict[tuple[str, str], list[str] | None] = {}
        for side in SIDES:
            for step in (from_step, to_step):
                s = _snap(store, run_id, step, side, f["id"])
                snaps[(side, step)] = json.loads(s["lines"]) if s and s["found"] else None
        dic = _dict(store, f["pick_file"])
        rows = []
        width = max(len(v or []) for v in snaps.values()) if snaps else 0
        for i in range(width):
            ob, oa = _at(snaps, "legacy", from_step, i), _at(snaps, "legacy", to_step, i)
            nb, na = _at(snaps, "new", from_step, i), _at(snaps, "new", to_step, i)
            oc, nc = normalise(ob) != normalise(oa), normalise(nb) != normalise(na)
            if not (oc or nc):
                continue
            if oc and nc:
                verdict = "both" if normalise(oa) == normalise(na) else "both-differently"
            else:
                verdict = "old-only" if oc else "new-only"
            d = dic.get(i + 1, {"names": [], "date": False})
            rows.append({"attr": i + 1, "names": d["names"], "change": verdict,
                         "old_before": _cell(ob, d["date"]), "old_after": _cell(oa, d["date"]),
                         "new_before": _cell(nb, d["date"]), "new_after": _cell(na, d["date"])})
        captured = {f"{side}_{'from' if step == from_step else 'to'}": snaps[(side, step)] is not None
                    for side in SIDES for step in (from_step, to_step)}
        out.append({"file_id": f["id"], "pick_file": f["pick_file"], "rows": rows, "captured": captured})
    return {"run_id": run_id, "from": from_step, "to": to_step, "files": out}


def quick(client: LiveClient, store: Store, pick_file: str, key_a: str, key_b: str) -> Result:
    pick_file = pick_file.strip().upper()
    recs: dict[str, tuple[list[str], str | None]] = {}
    used = {"legacy": key_a.strip(), "new": key_b.strip()}
    prefixes = {split_key(k)[0].upper() for k in used.values()} - {""}

    def one(side: str) -> None:
        key = used[side]
        if not key:
            recs[side] = ([], "no key")
            return
        try:
            _, rk, lines, err = find_record(client, pick_file, "{key}", key, prefixes)
            recs[side] = (lines, err)
            used[side] = rk
        except LiveError as e:
            recs[side] = ([], str(e))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, SIDES))
    dic = _dict(store, pick_file)
    a, b = recs["legacy"][0], recs["new"][0]
    rows = []
    for i in range(max(len(a), len(b))):
        va, vb = (a[i] if i < len(a) else ""), (b[i] if i < len(b) else "")
        st = _status(va, vb)
        if st == "same" and not va:
            continue
        d = dic.get(i + 1, {"names": [], "date": False})
        rows.append({"attr": i + 1, "names": d["names"], "status": st, "old": _cell(va, d["date"]),
                     "new": _cell(vb, d["date"]), "notes": []})
    return {"pick_file": pick_file, "old": {"key": used["legacy"], "typed": key_a.strip(), "error": recs["legacy"][1]},
            "new": {"key": used["new"], "typed": key_b.strip(), "error": recs["new"][1]}, "rows": rows,
            "differences": sum(1 for r in rows if r["status"] != "same")}


# ------------------------------------------------------------------ notes

def add_note(store: Store, run_id: str, pick_file: str, attr: int, verdict: str, text: str, author: str,
             remember: bool = True) -> str:
    run = _run(store, run_id)
    if verdict not in VERDICTS:
        raise CompareError(f"verdict must be one of {', '.join(VERDICTS)}")
    if not text.strip():
        raise CompareError("write what you noticed")
    nid, ts = _id(), now()
    store.db.execute("INSERT INTO cmp_note VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (nid, run["flow_id"], None if remember else run_id, pick_file.upper(), int(attr), verdict,
                      text.strip(), author.strip() or "anonymous", ts, ts))
    store.commit()
    return nid


def update_note(store: Store, note_id: str, verdict: str | None, text: str | None) -> None:
    n = store.db.execute("SELECT * FROM cmp_note WHERE id=?", (note_id,)).fetchone()
    if n is None:
        raise CompareError("no such note")
    if verdict is not None and verdict not in VERDICTS:
        raise CompareError(f"verdict must be one of {', '.join(VERDICTS)}")
    store.db.execute("UPDATE cmp_note SET verdict=?, text=?, updated_at=? WHERE id=?",
                     (verdict or n["verdict"], (text if text is not None else n["text"]).strip(), now(), note_id))
    store.commit()


def delete_note(store: Store, note_id: str) -> None:
    store.db.execute("DELETE FROM cmp_note WHERE id=?", (note_id,))
    store.commit()


def flow_notes(store: Store, flow_id: str) -> list[Result]:
    return [dict(r) for r in store.db.execute(
        "SELECT * FROM cmp_note WHERE flow_id=? ORDER BY pick_file, attr, created_at", (flow_id,))]


def _md(cell: Result) -> str:
    return str(cell["display"] or "—").replace("|", "\\|")[:80]


def report_markdown(store: Store, run_id: str) -> str:
    """Every step's differences with their notes, ready to paste into a ticket."""
    run = get_run(store, run_id)
    out = [f"## {run['flow']['name']}: {run['name']}", "",
           f"Old system key `{run['legacy_key'] or '—'}` · new system key `{run['new_key'] or '—'}`", ""]
    for step in run["steps"]:
        if not step["captured"]:
            out += [f"### {step['name']}", "_not captured yet_", ""]
            continue
        d = diff(store, run_id, step["id"])
        total = sum(f["differences"] for f in d["files"])
        out.append(f"### {step['name']} — {total} difference{'s' if total != 1 else ''}")
        for f in d["files"]:
            rows = [r for r in f["rows"] if r["status"] != "same"]
            if not rows:
                continue
            out += ["", f"**{f['pick_file']}**", "", "| Attr | Name | Old | New | Note |", "|---|---|---|---|---|"]
            for r in rows:
                note = "; ".join(f"{n['verdict']}: {n['text']}" for n in r["notes"]) or ""
                names = ", ".join(r["names"][:2])
                out.append(f"| <{r['attr']}> | {names} | {_md(r['old'])} | {_md(r['new'])} | {note} |")
        out.append("")
    return "\n".join(out)
