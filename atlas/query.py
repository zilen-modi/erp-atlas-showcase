"""Read-side queries shared by the CLI and the MCP server.

Every result is plain data plus a `freshness` header so a reader always knows
which source (git sha / live fetch time) a claim came from.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from atlas.memory import facts
from atlas.parse.program import is_gui_callee
from atlas.store.db import Store

Result = dict[str, Any]


def freshness(store: Store) -> Result:
    out: Result = {}
    for r in store.db.execute("SELECT * FROM index_state"):
        out[r["source"]] = {"sha": (r["last_sha"] or "")[:9] or None, "synced_at": r["synced_at"]}
    return out


def status(store: Store) -> Result:
    counts = {r["provenance"]: r["n"] for r in store.db.execute(
        "SELECT provenance, COUNT(*) n FROM program GROUP BY provenance")}
    fstat = {r["status"]: r["n"] for r in store.db.execute("SELECT status, COUNT(*) n FROM fact GROUP BY status")}
    drift = {r["class"]: r["n"] for r in store.db.execute("SELECT class, COUNT(*) n FROM drift GROUP BY class")}
    drift_progs = store.db.execute("SELECT COUNT(DISTINCT program) n FROM drift WHERE class IN "
                                   "('logic','git-only','live-only')").fetchone()["n"]
    answers = store.db.execute("SELECT COUNT(*) n FROM answer").fetchone()["n"]
    return {"freshness": freshness(store), "programs": counts, "answers": answers,
            "menus": store.db.execute("SELECT COUNT(*) n FROM menu").fetchone()["n"],
            "facts": fstat, "drift_hunks": drift, "programs_with_real_drift": drift_progs}


def _prog(store: Store, name: str, provenance: str) -> Any:
    return store.db.execute("SELECT * FROM program WHERE provenance=? AND name=?",
                            (provenance, name.upper())).fetchone()


def program_overview(store: Store, name: str, provenance: str = "git") -> Result:
    name = name.upper()
    p = _prog(store, name, provenance)
    if p is None:
        return {"error": f"{name} not indexed under {provenance}", "freshness": freshness(store)}
    edges = store.db.execute("SELECT kind, target, line, nargs FROM call_edge WHERE provenance=? AND program=?",
                             (provenance, name)).fetchall()
    calls: dict[str, list[int]] = defaultdict(list)
    for e in edges:
        if e["kind"] in ("CALL", "EXECUTE", "CHAIN", "ENTER") and not is_gui_callee(e["target"]):
            calls[f"{e['kind']} {e['target']}"].append(e["line"])
    handles = store.db.execute("SELECT var, pick_file, line FROM file_handle WHERE provenance=? AND program=?",
                               (provenance, name)).fetchall()
    io = store.db.execute("SELECT op, pick_file, COUNT(*) n, MIN(line) first FROM io_op WHERE provenance=? "
                          "AND program=? GROUP BY op, pick_file ORDER BY pick_file", (provenance, name)).fetchall()
    menus = [dict(r) for r in store.db.execute("SELECT code, used, last_used FROM menu WHERE program=? "
                                               "ORDER BY used DESC", (name,))]
    callers = sorted({r["program"] for r in store.db.execute(
        "SELECT program FROM call_edge WHERE provenance=? AND target=? AND kind IN ('CALL','EXECUTE','CHAIN',"
        "'ENTER')", (provenance, name))})
    drift = {r["class"]: r["n"] for r in store.db.execute(
        "SELECT class, COUNT(*) n FROM drift WHERE program=? GROUP BY class", (name,))}
    live = store.source("live", "BP", name)
    deployment = deployment_status(store, name)
    screens = [r["project"] for r in store.db.execute(
        "SELECT project FROM screen WHERE project=? OR program=? ORDER BY project != ?", (name, name, name))] \
        if store.db.execute("SELECT name FROM sqlite_master WHERE name='screen'").fetchone() else []
    summary = store.db.execute("SELECT title, summary, source_hash FROM summary WHERE kind='program' "
                               "AND program=?", (name,)).fetchone() if provenance == "git" else None
    path = store.db.execute("SELECT path FROM source_file WHERE provenance=? AND kind='BP' AND name=?",
                            (provenance, name)).fetchone()
    from atlas.sync import FOLDER_LABEL
    folder = next((label for d, label in FOLDER_LABEL.items() if path and str(path["path"]).startswith(d + "/")), None)
    return {
        "program": name, "provenance": provenance, "kind": p["kind"], "params": json.loads(p["params"]),
        "folder": folder,
        "summary": {"title": summary["title"], "text": summary["summary"], "machine_written": True,
                    "stale": summary["source_hash"] != p["hash"]} if summary else None,
        "screens": screens,
        "lines": p["line_count"],
        "labels": store.db.execute("SELECT COUNT(*) n FROM label WHERE provenance=? AND program=?",
                                   (provenance, name)).fetchone()["n"],
        "gosub_calls": sum(1 for e in edges if e["kind"] == "GOSUB"),
        "calls": {k: v for k, v in sorted(calls.items())},
        "gui_calls": sum(1 for e in edges if e["kind"] == "CALL" and is_gui_callee(e["target"])),
        "files_opened": sorted({h["pick_file"] for h in handles}),
        "io": [dict(r) for r in io],
        "menus": menus, "callers": callers,
        "drift": drift or ("not fetched live yet" if live is None else "identical"),
        "deployment": deployment,
        "facts": [{"id": f["id"], "status": f["status"], "text": f["text"]}
                  for f in facts.search(store, name, limit=20)],
        "freshness": freshness(store),
    }


def deployment_status(store: Store, name: str) -> Result:
    """Git is the source of truth; this only says whether TEST runs the same version.
    state: same | different | unchecked."""
    name = name.upper()
    live = store.source("live", "BP", name)
    if live is None:
        return {"state": "unchecked"}
    real = store.db.execute("SELECT COUNT(*) n FROM drift WHERE program=? AND class IN "
                            "('logic','git-only','live-only')", (name,)).fetchone()["n"]
    if not real:
        return {"state": "same", "checked_at": live["fetched_at"]}
    v = store.db.execute("SELECT * FROM drift_version WHERE program=?", (name,)).fetchone()
    return {"state": "different", "checked_at": live["fetched_at"], "differences": real,
            "test_commit": dict(v) if v else None}


def fact_home(f: Result) -> str:
    """The page a fact belongs on: its field, else the program it cites, else a search."""
    scope = str(f.get("scope") or "")
    m = re.match(r"^([A-Z0-9][A-Z0-9.\-/]*)<(\d+)>$", scope.upper())
    if m:
        return f"/field/{m.group(1)}/{m.group(2)}"
    for c in f.get("cites") or []:
        if c.get("src") in ("git", "live", "worktree"):
            return f"/program/{c['ref']}"
    return f"/search?q={scope or f.get('id')}"


def callers(store: Store, name: str, provenance: str = "git") -> Result:
    rows = store.db.execute("SELECT program, kind, line, nargs FROM call_edge WHERE provenance=? AND target=? "
                            "AND kind IN ('CALL','EXECUTE','CHAIN','ENTER') ORDER BY program, line",
                            (provenance, name.upper())).fetchall()
    menus = [dict(r) for r in store.db.execute("SELECT code, used FROM menu WHERE program=?", (name.upper(),))]
    return {"target": name.upper(), "sites": [dict(r) for r in rows],
            "programs": len({r["program"] for r in rows}), "menus": menus, "freshness": freshness(store)}


def usage_map(store: Store) -> dict[str, int]:
    """Menu launches reaching each program: its own menus, else its direct callers' menus.
    One hop only -- past depth 1 the CALL graph saturates and attribution means nothing."""
    own = {r["program"]: r["u"] or 0 for r in store.db.execute(
        "SELECT program, MAX(used) u FROM menu WHERE program IS NOT NULL GROUP BY program")}
    reach = dict(own)
    for r in store.db.execute("SELECT DISTINCT program, target FROM call_edge WHERE provenance='git' "
                              "AND kind IN ('CALL','EXECUTE','CHAIN','ENTER')"):
        u = own.get(r["program"])
        if u and r["target"] not in own and u > reach.get(r["target"], 0):
            reach[r["target"]] = u
    return reach


def _dict_names(store: Store, pick_file: str, attr: int) -> list[str]:
    return [r["name"] for r in store.db.execute(
        "SELECT name FROM dict_attr WHERE pick_file=? AND attr=? AND type IN ('A','D')", (pick_file, attr))]


def attr_sites(store: Store, pick_file: str, attr: int, access: str, provenance: str = "git") -> Result:
    """Where TRANSFER<attr> is written (or read).  Assignments are to the in-memory
    record; `persisted_by` lists where that record variable is written back."""
    f = pick_file.upper()
    rows = store.db.execute(
        "SELECT program, line, var, value_pos FROM attr_ref WHERE provenance=? AND pick_file=? AND attr=? "
        "AND access=? ORDER BY program, line", (provenance, f, attr, access)).fetchall()
    ops = ("WRITEV", "WRITEVU") if access == "write" else ("READV", "READVU", "READVL")
    direct = store.db.execute(
        f"SELECT program, line, op, key_expr FROM io_op WHERE provenance=? AND pick_file=? AND attr=? "
        f"AND op IN ({','.join('?' * len(ops))}) ORDER BY program, line", (provenance, f, attr, *ops)).fetchall()
    by_prog: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_prog[r["program"]].append({"line": r["line"], "var": r["var"], "value": r["value_pos"]})
    for r in direct:
        by_prog[r["program"]].append({"line": r["line"], "op": r["op"], "key": r["key_expr"]})
    persisted: dict[str, list[int]] = {}
    if access == "write":
        for prog in by_prog:
            persisted[prog] = [r["line"] for r in store.db.execute(
                "SELECT line FROM io_op WHERE provenance=? AND program=? AND pick_file=? AND op LIKE '%WRITE%'",
                (provenance, prog, f))]
    usage = usage_map(store)
    order = sorted(by_prog, key=lambda p: (-(usage.get(p) or 0), p))
    return {
        "file": f, "attr": attr, "access": access, "dict_names": _dict_names(store, f, attr),
        "programs": [{"program": p, "reached_launches": usage.get(p), "sites": by_prog[p],
                      **({"persisted_by_write_at": persisted[p]} if access == "write" else {})} for p in order],
        "note": "record variables are bound to a file by READ/WRITE in the same program; "
                "a variable read from several files is listed under each",
        "facts": [{"id": x["id"], "status": x["status"], "text": x["text"]}
                  for x in facts.search(store, scope=f"{f}<{attr}>")],
        "freshness": freshness(store),
    }


def field_info(store: Store, pick_file: str, attr: int) -> Result:
    w = attr_sites(store, pick_file, attr, "write")
    r = attr_sites(store, pick_file, attr, "read")
    return {"file": pick_file.upper(), "attr": attr, "dict_names": w["dict_names"],
            "writer_programs": len(w["programs"]), "reader_programs": len(r["programs"]),
            "top_writers": [p["program"] for p in w["programs"][:10]],
            "top_readers": [p["program"] for p in r["programs"][:10]],
            "facts": w["facts"], "freshness": w["freshness"]}


def read_lines(store: Store, name: str, start: int, end: int, provenance: str = "git") -> Result:
    lines = store.source_lines(provenance, name.upper())
    if lines is None:
        return {"error": f"{name} not indexed under {provenance}"}
    start = max(1, start)
    end = min(len(lines), max(start, end), start + 400)
    return {"program": name.upper(), "provenance": provenance, "start": start, "end": end,
            "lines": [f"{i}: {lines[i - 1]}" for i in range(start, end + 1)], "freshness": freshness(store)}


def menu(store: Store, code: str) -> Result:
    row = store.db.execute("SELECT * FROM menu WHERE code=?", (code.upper(),)).fetchone()
    if row is None:
        return {"error": f"menu {code} not indexed"}
    out: Result = dict(row)
    if row["program"]:
        out["program_overview"] = program_overview(store, row["program"])
    return out


def drift(store: Store, name: str, classes: set[str] | None = None) -> Result:
    classes = classes or {"logic", "git-only", "live-only"}
    rows = store.db.execute("SELECT * FROM drift WHERE program=? ORDER BY hunk", (name.upper(),)).fetchall()
    if not rows:
        live = store.source("live", "BP", name.upper())
        return {"program": name.upper(),
                "drift": "not fetched live yet" if live is None else "identical to git",
                "freshness": freshness(store)}
    ver = store.db.execute("SELECT * FROM drift_version WHERE program=?", (name.upper(),)).fetchone()
    return {"program": name.upper(),
            "summary": dict(Counter(r["class"] for r in rows)),
            "live_matches_git_version": dict(ver) if ver else None,
            "computed_at": rows[0]["computed_at"],
            "hunks": [{"hunk": r["hunk"], "class": r["class"],
                       "git": [r["git_start"], r["git_end"]], "live": [r["live_start"], r["live_end"]],
                       "git_text": r["git_text"], "live_text": r["live_text"],
                       "git_commits": json.loads(r["git_commits"] or "[]")}
                      for r in rows if r["class"] in classes],
            "freshness": freshness(store)}


def search_code(store: Store, text: str, provenance: str = "git", limit: int = 50) -> Result:
    """Plain substring search across indexed source (case-insensitive)."""
    needle = text.upper()
    hits = []
    for r in store.db.execute("SELECT s.name, b.text FROM source_file s JOIN blob b ON b.hash=s.hash "
                              "WHERE s.provenance=? AND s.kind='BP' AND instr(upper(b.text), ?) > 0",
                              (provenance, needle)):
        for i, ln in enumerate(str(r["text"]).splitlines(), 1):
            if needle in ln.upper():
                hits.append({"program": r["name"], "line": i, "text": ln.strip()[:200]})
                if len(hits) >= limit:
                    return {"query": text, "hits": hits, "truncated": True, "freshness": freshness(store)}
    return {"query": text, "hits": hits, "truncated": False, "freshness": freshness(store)}


# ------------------------------------------------------------------ UI helpers

_FIELD_Q = re.compile(r"^\s*([A-Z0-9][A-Z0-9.\-/]*)\s*[< ]\s*(\d+)\s*>?\s*$", re.IGNORECASE)


def search(store: Store, q: str, limit: int = 20) -> Result:
    """One box for everything: programs, menus, FILE<attr> fields, DICT names, facts."""
    q = q.strip()
    if not q:
        return {"query": q, "screens": [], "programs": [], "menus": [], "fields": [], "dict_names": [], "facts": []}
    up = q.upper()
    usage = usage_map(store)
    progs = [r["name"] for r in store.db.execute(
        "SELECT name FROM program WHERE provenance='git' AND name LIKE ? LIMIT 400", (f"%{up}%",))]
    progs.sort(key=lambda p: (p != up, not p.startswith(up), -(usage.get(p) or 0), p))
    menus = [dict(r) for r in store.db.execute(
        "SELECT code, exec, program, used FROM menu WHERE code LIKE ? OR program LIKE ? "
        "ORDER BY (code = ?) DESC, used DESC LIMIT ?", (f"{up}%", f"%{up}%", up, limit))]
    fields: list[Result] = []
    m = _FIELD_Q.match(q)
    if m:
        f, a = m.group(1).upper(), int(m.group(2))
        fields.append({"file": f, "attr": a, "dict_names": _dict_names(store, f, a)})
    dict_names = [dict(r) for r in store.db.execute(
        "SELECT pick_file, attr, name FROM dict_attr WHERE name LIKE ? AND type IN ('A','D') "
        "ORDER BY (name = ?) DESC, pick_file LIMIT ?", (f"%{up}%", up, limit))]
    screens = [dict(r) for r in store.db.execute(
        "SELECT project, program, forms FROM screen WHERE project LIKE ? OR program LIKE ? "
        "ORDER BY (project = ?) DESC, project LIMIT ?", (f"%{up}%", f"%{up}%", up, min(limit, 8)))] \
        if store.db.execute("SELECT name FROM sqlite_master WHERE name='screen'").fetchone() else []
    return {
        "query": q,
        "screens": screens,
        "programs": [{"name": p, "reached_launches": usage.get(p)} for p in progs[:limit]],
        "menus": menus, "fields": fields, "dict_names": dict_names,
        "facts": [{"id": x["id"], "status": x["status"], "scope": x["scope"], "text": x["text"]}
                  for x in facts.search(store, q, limit=min(limit, 10))],
    }


def blocks(store: Store, name: str, provenance: str = "git") -> Result:
    rows = store.db.execute("SELECT name, line FROM label WHERE provenance=? AND program=? ORDER BY line",
                            (provenance, name.upper())).fetchall()
    p = _prog(store, name, provenance)
    return {"program": name.upper(), "provenance": provenance,
            "lines": p["line_count"] if p else 0,
            "blocks": [{"label": r["name"], "line": r["line"]} for r in rows]}


def drift_overview(store: Store) -> Result:
    live = {r["name"]: r["fetched_at"] for r in store.db.execute(
        "SELECT name, fetched_at FROM source_file WHERE provenance='live' AND kind='BP'")}
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for r in store.db.execute("SELECT program, class, COUNT(*) n FROM drift GROUP BY program, class"):
        counts[r["program"]][r["class"]] = r["n"]
    versions = {r["program"]: dict(r) for r in store.db.execute("SELECT * FROM drift_version")}
    usage = usage_map(store)
    rows = []
    for name, fetched in live.items():
        c = counts.get(name, {})
        real = sum(v for k, v in c.items() if k in ("logic", "git-only", "live-only"))
        rows.append({"program": name, "live_fetched_at": fetched, "classes": c, "real_hunks": real,
                     "state": "drift" if real else ("cosmetic" if c else "identical"),
                     "test_version": versions.get(name), "reached_launches": usage.get(name)})
    rows.sort(key=lambda r: (-r["real_hunks"], -(r["reached_launches"] or 0), r["program"]))
    return {"programs": rows,
            "totals": dict(Counter(r["state"] for r in rows)), "freshness": freshness(store)}


# ------------------------------------------------------------------ browse sections

def programs_list(store: Store, q: str = "", sort: str = "usage", limit: int = 100, offset: int = 0) -> Result:
    usage = usage_map(store)
    live = {r["name"] for r in store.db.execute("SELECT name FROM source_file WHERE provenance='live' AND kind='BP'")}
    real = {r["program"] for r in store.db.execute(
        "SELECT DISTINCT program FROM drift WHERE class IN ('logic','git-only','live-only')")}
    rows = [dict(r) for r in store.db.execute(
        "SELECT name, kind, line_count FROM program WHERE provenance='git' AND name LIKE ?", (f"%{q.upper()}%",))]
    for r in rows:
        r["reached_launches"] = usage.get(r["name"])
        r["live"] = "drift" if r["name"] in real else ("fetched" if r["name"] in live else None)
    own = {r["program"] for r in store.db.execute("SELECT DISTINCT program FROM menu WHERE program IS NOT NULL")}
    key = {"usage": lambda r: (-(r["reached_launches"] or 0), r["name"] not in own, r["name"]),
           "lines": lambda r: (-(r["line_count"] or 0), r["name"]),
           "name": lambda r: r["name"]}.get(sort, lambda r: r["name"])
    rows.sort(key=key)
    return {"total": len(rows), "offset": offset, "programs": rows[offset:offset + limit]}


def menus_list(store: Store, q: str = "", limit: int = 200, offset: int = 0) -> Result:
    like = f"%{q.upper()}%"
    rows = [dict(r) for r in store.db.execute(
        "SELECT code, exec, program, used, last_used FROM menu WHERE code LIKE ? OR exec LIKE ? "
        "ORDER BY used DESC", (like, like))]
    total = sum(r["used"] or 0 for r in rows)
    return {"total": len(rows), "launches": total, "offset": offset, "menus": rows[offset:offset + limit]}


def files_list(store: Store, q: str = "") -> Result:
    dict_n = {r["pick_file"]: r["n"] for r in store.db.execute(
        "SELECT pick_file, COUNT(DISTINCT attr) n FROM dict_attr WHERE type IN ('A','D') GROUP BY pick_file")}
    opened = {r["pick_file"]: r["n"] for r in store.db.execute(
        "SELECT pick_file, COUNT(DISTINCT program) n FROM file_handle WHERE provenance='git' GROUP BY pick_file")}
    writers = {r["pick_file"]: r["n"] for r in store.db.execute(
        "SELECT pick_file, COUNT(DISTINCT program) n FROM io_op WHERE provenance='git' AND op LIKE '%WRITE%' "
        "AND pick_file IS NOT NULL GROUP BY pick_file")}
    names = sorted({*dict_n, *opened})
    rows = [{"file": f, "dict_attrs": dict_n.get(f, 0), "programs_opening": opened.get(f, 0),
             "programs_writing": writers.get(f, 0)} for f in names if q.upper() in f]
    rows.sort(key=lambda r: (-r["programs_opening"], r["file"]))
    return {"total": len(rows), "files": rows}


def file_detail(store: Store, pick_file: str) -> Result:
    f = pick_file.upper()
    attrs: dict[int, Result] = {}
    for r in store.db.execute("SELECT attr, name, type, conv FROM dict_attr WHERE pick_file=? AND attr > 0 "
                              "ORDER BY attr", (f,)):
        a = attrs.setdefault(r["attr"], {"attr": r["attr"], "dict_names": [], "writers": 0, "readers": 0})
        if r["type"] in ("A", "D") and r["name"] not in a["dict_names"]:
            a["dict_names"].append(r["name"])
    for r in store.db.execute("SELECT attr, access, COUNT(DISTINCT program) n FROM attr_ref WHERE provenance='git' "
                              "AND pick_file=? GROUP BY attr, access", (f,)):
        a = attrs.setdefault(r["attr"], {"attr": r["attr"], "dict_names": [], "writers": 0, "readers": 0})
        a["writers" if r["access"] == "write" else "readers"] = r["n"]
    usage = usage_map(store)
    progs = sorted({r["program"] for r in store.db.execute(
        "SELECT DISTINCT program FROM file_handle WHERE provenance='git' AND pick_file=?", (f,))},
        key=lambda p: (-(usage.get(p) or 0), p))
    ops: dict[str, set[str]] = {}
    for r in store.db.execute("SELECT program, op FROM io_op WHERE provenance='git' AND pick_file=?", (f,)):
        ops.setdefault(r["program"], set()).add("write" if "WRITE" in r["op"] or r["op"].startswith("DELETE")
                                                else "read")
    return {"file": f, "attributes": [attrs[k] for k in sorted(attrs)],
            "undocumented": [k for k in sorted(attrs) if not attrs[k]["dict_names"]],
            "programs": [{"program": p, "reached_launches": usage.get(p), "access": sorted(ops.get(p, set()))}
                         for p in progs[:300]],
            "program_count": len(progs), "freshness": freshness(store)}


def flow(store: Store, name: str, depth: int = 2, max_children: int = 40) -> Result:
    """Call tree from a program (or a menu code) with the data each node touches.
    Depth is kept small on purpose: past 1-2 hops the call graph saturates."""
    root = name.upper()
    menu_row = store.db.execute("SELECT * FROM menu WHERE code=?", (root,)).fetchone()
    if menu_row and menu_row["program"]:
        root = menu_row["program"]
    known = {r["name"] for r in store.db.execute("SELECT name FROM program WHERE provenance='git'")}
    usage = usage_map(store)
    seen: set[str] = set()

    def node(p: str, level: int) -> Result:
        seen.add(p)
        io: dict[str, set[str]] = {}
        for r in store.db.execute("SELECT op, pick_file FROM io_op WHERE provenance='git' AND program=? "
                                  "AND pick_file IS NOT NULL", (p,)):
            io.setdefault(r["pick_file"], set()).add("W" if "WRITE" in r["op"] or r["op"].startswith("DELETE")
                                                      else "R")
        n: Result = {"program": p, "known": p in known, "reached_launches": usage.get(p),
                     "reads": sorted(k for k, v in io.items() if v == {"R"}),
                     "writes": sorted(k for k, v in io.items() if "W" in v), "children": []}
        if level >= depth or p not in known:
            return n
        targets: dict[str, int] = {}
        for r in store.db.execute("SELECT target, MIN(line) line FROM call_edge WHERE provenance='git' AND program=? "
                                  "AND kind IN ('CALL','EXECUTE','CHAIN','ENTER') GROUP BY target ORDER BY line", (p,)):
            if not is_gui_callee(r["target"]):
                targets[r["target"]] = r["line"]
        for t, line in list(targets.items())[:max_children]:
            if t in seen:
                n["children"].append({"program": t, "line": line, "repeat": True, "children": []})
            else:
                child = node(t, level + 1)
                child["line"] = line
                n["children"].append(child)
        n["more"] = max(0, len(targets) - max_children)
        return n

    return {"root": root, "menu": dict(menu_row) if menu_row else None, "depth": depth,
            "tree": node(root, 0), "freshness": freshness(store)}
