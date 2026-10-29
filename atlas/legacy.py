"""Background Jobs Map and Reports Catalogue: the legacy work nobody sees on a screen.

Jobs   -- PROC scripts (src/PROK): when they run (nightly / daily / weekly / month-end / year-end /
          on demand, from their names, text and SLEEP), who launches them (menus, other procs), what
          they run (programs, procs, RetrieVe reports), what those programs write, which CONTROL
          counters they bump (XF#, PO#...), and any destructive commands (CLEAR-FILE, DELETE).
Reports -- everything that produces a report: PROC RetrieVe reports (SORT/LIST ... HEADING/LPTR, with
          their columns) and BP programs launched from a menu or proc that export to Excel
          (LG.EXCEL.DOWNLOAD / LG.SUB.DC) or print (HEADING, PRINTER ON).
Both carry a migration status (parity table): todo, built, standard, scheduled, not needed.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from atlas import suggest
from atlas.query import usage_map
from atlas.store.db import Store, now

Result = dict[str, Any]
SCHEDULES = ["nightly", "daily", "weekly", "month-end", "year-end", "on demand"]
STATUSES = {"job": ["todo", "scheduled", "built", "not needed"],
            "report": ["todo", "built", "standard", "not needed"]}
EXCEL = {"LG.EXCEL.DOWNLOAD", "LG.SUB.DC", "LG.INV.EXCEL"}
_REPORTISH = re.compile(r"(RPT|REPORT|REG|JRL|JOURNAL|LIST|LISTING|SUMM|ANAL|STAT|AUDIT|AGING|AGED)", re.I)
_CACHE: dict[str, Any] = {}


def _sha(store: Store) -> str:
    s = store.get_state("git:erp")
    return (s["last_sha"] if s else "") or ""


def _procs(store: Store) -> dict[str, Result]:
    rows = store.db.execute("SELECT * FROM proc")
    return {r["name"]: {**dict(r), "data": json.loads(r["data"] or "{}")} for r in rows}


def _bp_names(store: Store) -> set[str]:
    return {r["name"] for r in store.db.execute("SELECT name FROM program WHERE provenance='git'")}


def _menu_launch(store: Store, procs: set[str]) -> tuple[dict[str, list[Result]], dict[str, list[Result]]]:
    """Menus launching each proc (EXEC/DO/PROK X, or bare X) and each program (RUN BP X)."""
    to_proc: dict[str, list[Result]] = defaultdict(list)
    to_prog: dict[str, list[Result]] = defaultdict(list)
    for m in store.db.execute("SELECT code, exec, program, used FROM menu"):
        ex = (m["exec"] or "").strip().upper()
        w = ex.split()
        item = {"code": m["code"], "used": m["used"] or 0}
        if m["program"]:
            to_prog[m["program"]].append(item)
        elif len(w) >= 2 and w[0] in ("EXEC", "DO", "PROK") and w[1] in procs:
            to_proc[w[1]].append(item)
        elif w and w[0] in procs:
            to_proc[w[0]].append(item)
    return to_proc, to_prog


def _graph(store: Store) -> Result:
    key = "graph:" + _sha(store)
    if key in _CACHE:
        return _CACHE[key]  # type: ignore[no-any-return]
    procs = _procs(store)
    bp = _bp_names(store)
    names = set(procs)
    to_proc, to_prog = _menu_launch(store, names)
    calls: dict[str, set[str]] = defaultdict(set)
    runs: dict[str, set[str]] = defaultdict(set)
    for n, p in procs.items():
        for c in p["data"].get("commands", []):
            t = (c.get("target") or "").upper()
            if c["kind"] == "proc" and t in names and t != n:
                calls[n].add(t)
            elif c["kind"] in ("run", "call") and t in bp:
                runs[n].add(t)
            elif c["kind"] == "call" and t in names and t != n:
                calls[n].add(t)
        for it in p["data"].get("menu_items", []):
            w = (it.get("command") or "").upper().split()
            if w and w[0] == "RUN" and len(w) >= 3 and w[2] in bp:
                runs[n].add(w[2])
            elif w and w[0] in names:
                calls[n].add(w[0])
            elif w and w[0] in bp:
                runs[n].add(w[0])
    called_by: dict[str, set[str]] = defaultdict(set)
    for a, bs in calls.items():
        for b in bs:
            called_by[b].add(a)
    g = {"procs": procs, "bp": bp, "calls": calls, "runs": runs, "called_by": called_by,
         "menus_proc": to_proc, "menus_prog": to_prog}
    if key != "graph:":                  # no git commit recorded: don't share a cache between databases
        _CACHE.clear()
        _CACHE[key] = g
    return g


def _parity(store: Store, kind: str) -> dict[str, Result]:
    return {r["name"]: dict(r) for r in store.db.execute("SELECT * FROM parity WHERE kind=?", (kind,))}


def set_parity(store: Store, kind: str, name: str, status: str, target: str = "", note: str = "",
               by: str = "") -> Result:
    if kind not in STATUSES or status not in STATUSES[kind]:
        raise ValueError(f"status must be one of {', '.join(STATUSES.get(kind, []))}")
    store.db.execute("INSERT OR REPLACE INTO parity VALUES (?,?,?,?,?,?,?)",
                     (kind, name, status, target.strip(), note.strip(), by, now()))
    store.commit()
    return _parity(store, kind)[name]


# ------------------------------------------------------------------ jobs

def _counters(store: Store, programs: set[str]) -> list[str]:
    if not programs:
        return []
    marks = ",".join("?" * len(programs))
    rows = store.db.execute(f"SELECT DISTINCT key_expr FROM io_op WHERE provenance='git' AND pick_file='CONTROL' AND "
                            f"op LIKE 'WRITE%' AND program IN ({marks})", tuple(programs))
    out = []
    for r in rows:
        k = (r["key_expr"] or "").strip()
        if len(k) > 2 and k[0] in "\"'" and k[-1] == k[0] and not k.upper().endswith(".ERRORS\""):
            out.append(k[1:-1])
    return sorted(set(out))


def _launches(g: Result, name: str) -> int:
    return sum(m["used"] for m in g["menus_proc"].get(name, []))


def list_jobs(store: Store, schedule: str = "", q: str = "", only_jobs: bool = True) -> Result:
    """Procs that do work (run programs, print reports, change data), grouped by schedule."""
    g = _graph(store)
    par = _parity(store, "job")
    rows = []
    for n, p in g["procs"].items():
        cmds = p["data"].get("commands", [])
        does = g["runs"].get(n) or any(c["kind"] in ("report", "destructive") for c in cmds) or g["calls"].get(n)
        if only_jobs and not does:
            continue
        if schedule and p["schedule"] != schedule:
            continue
        if q:
            hay = f"{n} {p['title']} {p['description']}".upper()
            if q.upper() not in hay:
                continue
        rows.append({
            "name": n, "kind": p["kind"], "title": p["title"], "schedule": p["schedule"],
            "programs": len(g["runs"].get(n, ())), "procs": len(g["calls"].get(n, ())),
            "reports": sum(1 for c in cmds if c["kind"] == "report"),
            "destructive": sum(1 for c in cmds if c["kind"] == "destructive"),
            "menus": [m["code"] for m in g["menus_proc"].get(n, [])][:3], "launches": _launches(g, n),
            "called_by": len(g["called_by"].get(n, ())), "status": par.get(n, {}).get("status", "todo"),
        })
    order = {s: i for i, s in enumerate(SCHEDULES)}
    rows.sort(key=lambda r: (order.get(r["schedule"], 9), -r["launches"], -r["programs"], r["name"]))
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["schedule"]] += 1
    return {"total": len(rows), "by_schedule": {s: counts.get(s, 0) for s in SCHEDULES}, "jobs": rows}


def job(store: Store, name: str) -> Result:
    g = _graph(store)
    name = name.upper()
    p = g["procs"].get(name) or next((v for k, v in g["procs"].items() if k.upper() == name), None)
    if p is None:
        raise ValueError(f"no proc {name} in src/PROK")
    name = p["name"]
    programs = sorted(g["runs"].get(name, ()))
    usage = usage_map(store)
    prog_rows = []
    for pr in programs:
        writes = sorted(suggest._program_writes(store, pr))
        prog_rows.append({"name": pr, "writes": writes, "counters": _counters(store, {pr}),
                          "launches": usage.get(pr)})
    reports = [c for c in p["data"].get("commands", []) if c["kind"] == "report"]
    destructive = [c for c in p["data"].get("commands", []) if c["kind"] == "destructive"]
    par = _parity(store, "job").get(name)
    return {
        "name": name, "kind": p["kind"], "title": p["title"], "description": p["description"],
        "schedule": p["schedule"], "lines": p["lines"],
        "menus": g["menus_proc"].get(name, []), "called_by": sorted(g["called_by"].get(name, ())),
        "calls": sorted(g["calls"].get(name, ())), "programs": prog_rows,
        "writes": sorted({w for x in prog_rows for w in x["writes"]}),
        "counters": sorted({c for x in prog_rows for c in x["counters"]}),
        "reports": reports, "destructive": destructive, "commands": p["data"].get("commands", []),
        "menu_items": p["data"].get("menu_items", []),
        "parity": par or {"status": "todo", "target": "", "note": ""}, "statuses": STATUSES["job"],
    }


def jobs_writing(store: Store, pick_file: str) -> list[Result]:
    """Background jobs whose programs write this file (for the file page and search)."""
    g = _graph(store)
    out = []
    for n, progs in g["runs"].items():
        hits = [pr for pr in progs if pick_file.upper() in suggest._program_writes(store, pr)]
        if hits:
            out.append({"name": n, "schedule": g["procs"][n]["schedule"], "via": hits[:3]})
    return sorted(out, key=lambda r: (SCHEDULES.index(r["schedule"]) if r["schedule"] in SCHEDULES else 9, r["name"]))


# ------------------------------------------------------------------ reports catalogue

def _source(store: Store, name: str) -> str:
    r = store.db.execute("SELECT b.text FROM source_file s JOIN blob b ON b.hash = s.hash WHERE s.provenance='git' "
                         "AND s.kind='BP' AND s.name=?", (name,)).fetchone()
    return r["text"] if r else ""


def _screen_title(store: Store, program: str) -> str:
    r = store.db.execute("SELECT form_list FROM screen WHERE project=? OR program=? ORDER BY project != ? LIMIT 1",
                         (program, program, program)).fetchone()
    if not r:
        return ""
    forms = json.loads(r["form_list"] or "[]")
    t = forms[0]["title"] if forms else ""
    t = re.sub(r"^\s*M\d+\s*[-:]?\s*", "", t)                        # M1810 -
    t = re.sub(r"^\s*\[[^\]]*\]\s*[-:]?\s*", "", t)                   # [LG.DAY.SALES] -
    t = re.sub(rf"^\s*{re.escape(program)}\s*[-:]\s*", "", t, flags=re.I)  # LG.ORDLOG.RPT -
    return t.strip()


def catalogue(store: Store) -> list[Result]:
    key = "cat:" + _sha(store)
    if key in _CACHE:
        return _CACHE[key]  # type: ignore[no-any-return]
    g = _graph(store)
    usage = usage_map(store)
    out: list[Result] = []
    # PROC RetrieVe reports
    for n, p in g["procs"].items():
        reps = [c for c in p["data"].get("commands", []) if c["kind"] == "report"]
        if not reps:
            continue
        main = max(reps, key=lambda c: (bool(c.get("heading")), len(c.get("columns", []))))
        out.append({
            "kind": "proc", "type": "report", "name": n, "title": main.get("heading") or p["title"] or n,
            "output": "printer" if any(c.get("printed") for c in reps) else "screen",
            "files": sorted({c["target"] for c in reps if c.get("target")}),
            "columns": main.get("columns", [])[:20], "criteria": main.get("criteria", ""),
            "reports_in_proc": len(reps), "schedule": p["schedule"],
            "menus": [m["code"] for m in g["menus_proc"].get(n, [])][:3], "launches": _launches(g, n),
        })
    # BP programs launched by a menu or a proc
    launched: dict[str, int] = defaultdict(int)
    for prog, ms in g["menus_prog"].items():
        launched[prog] += sum(m["used"] for m in ms)
    for _n, progs in g["runs"].items():
        for pr in progs:
            launched.setdefault(pr, 0)
    excel_callers = defaultdict(set)
    for r in store.db.execute("SELECT DISTINCT program, target FROM call_edge WHERE provenance='git' AND target IN "
                              "(" + ",".join("?" * len(EXCEL)) + ")", tuple(EXCEL)):
        excel_callers[r["program"]].add(r["target"])
    # a menu program often reaches its Excel/print subroutine one hop down
    sub_excel = {r["program"]: r["target"] for r in store.db.execute(
        "SELECT DISTINCT program, target FROM call_edge WHERE provenance='git' AND kind='CALL'")
        if r["target"] in excel_callers}
    for prog in launched:
        if prog not in g["bp"]:
            continue
        text = _source(store, prog)
        up = text.upper()
        heads = re.findall(r'^\s*HEADING\s+"([^"]{3,120})"', text, re.M | re.I)
        excel = bool(excel_callers.get(prog)) or prog in sub_excel
        printed = bool(heads) or ("PRINTER ON" in up and bool(_REPORTISH.search(prog)))
        if not (excel or printed):
            continue
        files = [r["pick_file"] for r in store.db.execute(
            "SELECT pick_file, COUNT(*) n FROM io_op WHERE provenance='git' AND program=? AND op LIKE 'READ%' "
            "AND pick_file != '' GROUP BY pick_file ORDER BY n DESC LIMIT 8", (prog,))]
        title = _screen_title(store, prog) or (re.sub(r"'[A-Z]*'", " ", heads[0]).strip() if heads else "")
        # an inquiry/entry screen with an "export to Excel" button is not a report
        is_report = bool(heads) or bool(_REPORTISH.search(prog)) or bool(_REPORTISH.search(title)) \
            or not store.db.execute("SELECT 1 FROM screen WHERE project=? OR program=?", (prog, prog)).fetchone()
        out.append({
            "kind": "program", "type": "report" if is_report else "screen export", "name": prog,
            "title": title or prog,
            "output": " + ".join(x for x in ("Excel" if excel else "", "printer" if printed else "") if x),
            "files": files, "columns": [], "criteria": "", "schedule": "",
            "menus": [m["code"] for m in g["menus_prog"].get(prog, [])][:3],
            "launches": usage.get(prog) or launched[prog] or 0,
            "via": sorted(excel_callers.get(prog, set()) | ({sub_excel[prog]} if prog in sub_excel else set())),
        })
    out.sort(key=lambda r: (-(r["launches"] or 0), r["name"]))
    if key != "cat:":
        _CACHE[key] = out
    return out


def list_reports(store: Store, q: str = "", kind: str = "", status: str = "", limit: int = 500,
                 include_screens: bool = False) -> Result:
    par = _parity(store, "report")
    rows = []
    screen_exports = 0
    for r in catalogue(store):
        if r["type"] == "screen export":
            screen_exports += 1
            if not include_screens:
                continue
        st = par.get(r["name"], {}).get("status", "todo")
        if (kind and r["kind"] != kind) or (status and st != status):
            continue
        if q and q.upper() not in f"{r['name']} {r['title']} {' '.join(r['files'])}".upper():
            continue
        rows.append({**r, "status": st, "target": par.get(r["name"], {}).get("target", "")})
    done = sum(1 for r in rows if r["status"] != "todo")
    weight = sum(r["launches"] or 0 for r in rows) or 1
    done_w = sum(r["launches"] or 0 for r in rows if r["status"] != "todo")
    return {"total": len(rows), "decided": done, "decided_by_use_pct": round(100 * done_w / weight, 1),
            "screen_exports": screen_exports,
            "reports": rows[:limit], "statuses": STATUSES["report"]}


def report(store: Store, name: str) -> Result:
    r = next((x for x in catalogue(store) if x["name"].upper() == name.upper()), None)
    if r is None:
        raise ValueError(f"{name} is not in the reports catalogue")
    par = _parity(store, "report").get(r["name"])
    extra: Result = {}
    if r["kind"] == "proc":
        extra["job"] = job(store, r["name"])
    return {**r, **extra, "parity": par or {"status": "todo", "target": "", "note": ""},
            "statuses": STATUSES["report"]}
