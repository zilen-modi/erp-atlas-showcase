"""Process flow: a business process read off the code, as the life of one record.

A process is a file and its status field (TRANSFER<2> MODE: O ordered, S shipped, R received ...). Every
`REC<status> = "X"` in the code is a step into state X. For each step this finds:

  who            the program and line, its usage, and the menus that lead to it
  from where     the state it moves from, when the condition is on the line or just above
                 (`IF REC<2> = "S" THEN REC<2> = "R"`)
  saved to       the file the record is next written to: the process file itself, or a history file
  what else      the other fields of the same record it sets around that line, and the other files it writes

plus how records leave the process (DELETE from the file) and where they are archived. Labels for the
states come from a small curated list (PROCESSES); a status field without one shows its raw codes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from atlas import domains as doms
from atlas.query import freshness, usage_map
from atlas.store.db import Store
from atlas.trace import _menu_paths, _origin, _var_files

Result = dict[str, Any]

# Processes worth naming. `order` is the usual life of a record; `states` are read from the code around the
# lines cited in `why` (the MODE codes, and B: LG.DEPOT.PRINT:974 moves B to O when the depot prints it).
PROCESSES: dict[str, Result] = {
    "transfer": {
        "title": "Branch transfer", "file": "TRANSFER", "attr": 2,
        "blurb": "Stock moved between branches: ordered, (held at the depot), shipped, received, then archived.",
        "states": {"O": "Ordered", "B": "Depot backorder", "S": "Shipped", "R": "Received"},
        "order": ["O", "B", "S", "R"],
    },
}

NEARBY = 40          # lines either side of a status change searched for the other fields set with it
GUARD_LOOKBACK = 15  # lines above a status change searched for the state it moves from
_COND = re.compile(r"\b(IF|CASE|AND|OR|WHILE|UNTIL)\b", re.I)


def _changes(line: str, var: str, attr: int) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """On one line: the literal states VAR<attr> is set to, the (op, literal) conditions on it, and any
    non-literal values it is set to (`XF<2> = MODE`: whatever the user picked)."""
    sets: list[str] = []
    conds: list[tuple[str, str]] = []
    other: list[str] = []
    pat = re.compile(rf"\b{re.escape(var)}<\s*{attr}\s*>\s*(=|EQ|#|NE|<>)\s*(\"[^\"]*\"|'[^']*'|[^;\s]+)", re.I)
    for m in pat.finditer(line):
        before = line[:m.start()]
        lit = m.group(2)[1:-1] if m.group(2)[:1] in "\"'" else None
        # a condition when an IF/CASE/... comes before it on the line with no THEN in between
        last_then = before.upper().rfind("THEN")
        is_cond = m.group(1).upper() != "=" or bool(_COND.search(before[last_then + 4 if last_then >= 0 else 0:]))
        if is_cond:
            if lit is not None:
                conds.append(("is" if m.group(1).upper() in ("=", "EQ") else "not", lit))
        elif lit is not None:
            sets.append(lit)
        else:
            other.append(m.group(2))
    return sets, conds, other


def process_flow(store: Store, key: str | None = None, pick_file: str | None = None, attr: int | None = None) -> Result:
    meta = PROCESSES.get(key or "", {})
    f = (pick_file or meta.get("file") or "").upper()
    a = attr or meta.get("attr")
    if not f or not a:
        return {"error": "name a process, or a file and its status field"}
    usage = usage_map(store)
    domain = doms.domain_map(store)
    menus: dict[str, tuple[str, int]] = {}
    for r in store.db.execute("SELECT code, program, used FROM menu WHERE program IS NOT NULL AND program <> ''"):
        p = r["program"].upper()
        if p not in menus or (r["used"] or 0) > menus[p][1]:
            menus[p] = (r["code"], r["used"] or 0)
    callers: dict[str, set[str]] = defaultdict(set)
    for r in store.db.execute("SELECT DISTINCT program, target FROM call_edge WHERE provenance='git' "
                              "AND kind IN ('CALL','EXECUTE','CHAIN','ENTER')"):
        if r["program"] != r["target"]:
            callers[r["target"]].add(r["program"])

    steps: list[Result] = []
    chosen: list[Result] = []     # set to a variable, not a fixed state: usually what the user picked on a screen
    by_prog: dict[str, list[Any]] = defaultdict(list)
    for r in store.db.execute("SELECT program, line, var FROM attr_ref WHERE provenance='git' AND pick_file=? "
                              "AND attr=? AND access='write' ORDER BY program, line", (f, a)):
        by_prog[r["program"]].append(r)
    for prog, refs in by_prog.items():
        src = store.source_lines("git", prog) or []
        writes = store.db.execute("SELECT line, pick_file, record_var FROM io_op WHERE provenance='git' AND program=? "
                                  "AND op LIKE '%WRITE%' ORDER BY line", (prog,)).fetchall()
        reads = store.db.execute("SELECT line, record_var, pick_file FROM io_op WHERE provenance='git' AND program=? "
                                 "AND op LIKE 'READ%' AND record_var IS NOT NULL ORDER BY line", (prog,)).fetchall()
        files = _var_files(store, prog)
        for r in refs:
            var, ln = (r["var"] or "").upper(), r["line"]
            text = src[ln - 1] if 0 < ln <= len(src) else ""
            sets, conds, other = _changes(text, var, a)
            if not sets and not other:
                continue
            # the file this record is written to next: if it isn't this process's file (or its history), the
            # variable belongs to another file here (TEST<2> on ORDER in LG.ORDER.MAINT) and it isn't a step at all
            nxt = next((w for w in writes if w["line"] >= ln and (w["record_var"] or "").upper() == var), None)
            saved = nxt["pick_file"] if nxt else None
            if saved and saved != f and not saved.startswith(f) and files.get(var) != f:
                continue
            # the record in this variable here is whatever it was last read from (TEST is reused for 30 files)
            last = next((x for x in reversed(reads) if x["line"] <= ln and x["record_var"].upper() == var), None)
            if last and not (last["pick_file"] or "").startswith(f):
                continue
            if not conds:
                for n in range(ln - 1, max(0, ln - GUARD_LOOKBACK), -1):
                    _, c, _ = _changes(src[n - 1], var, a)
                    if c:
                        conds = c
                        break
            frm = next((v for op, v in conds if op == "is"), None) or None    # "" is a new, blank record
            # the other fields of this record set around here, and what else this program writes
            near = store.db.execute(
                "SELECT DISTINCT attr FROM attr_ref WHERE provenance='git' AND program=? AND pick_file=? "
                "AND access='write' AND attr <> ? AND line BETWEEN ? AND ? ORDER BY attr",
                (prog, f, a, ln - NEARBY, ln + NEARBY)).fetchall()
            for value in other:
                chosen.append({"program": prog, "line": ln, "code": text.strip()[:160], "from": frm,
                               "saved_to": saved, **_origin(src, ln, value, files)})
            for state in sets:
                steps.append({"program": prog, "line": ln, "to": state, "from": frm, "code": text.strip()[:160],
                              "saved_to": saved, "saved_at": nxt["line"] if nxt else None,
                              "also_sets": [x["attr"] for x in near][:12]})

    names = {r["attr"]: r["name"] for r in store.db.execute(
        "SELECT attr, name FROM dict_attr WHERE pick_file=? AND type IN ('A','D') ORDER BY attr", (f,))}
    progs = sorted({s["program"] for s in steps} | {c["program"] for c in chosen})
    info: dict[str, Result] = {}
    for p in progs:
        outs = [r["pick_file"] for r in store.db.execute(
            "SELECT pick_file, COUNT(*) n FROM io_op WHERE provenance='git' AND program=? AND op LIKE '%WRITE%' "
            "AND pick_file IS NOT NULL AND pick_file <> ? GROUP BY pick_file ORDER BY n DESC LIMIT 8", (p, f))]
        ins = [r["pick_file"] for r in store.db.execute(
            "SELECT pick_file, COUNT(*) n FROM io_op WHERE provenance='git' AND program=? AND op LIKE 'READ%' "
            "AND pick_file IS NOT NULL AND pick_file <> ? GROUP BY pick_file ORDER BY n DESC LIMIT 8", (p, f))]
        info[p] = {"program": p, "launches": usage.get(p), "domain": domain.get(p),
                   "menus": _menu_paths(store, p, callers, menus, limit=2), "writes": outs, "reads": ins}

    # leaving the process: who deletes records from the file, and where they keep a copy
    leave = []
    for r in store.db.execute("SELECT program, MIN(line) line FROM io_op WHERE provenance='git' AND pick_file=? "
                              "AND op LIKE 'DELETE%' GROUP BY program", (f,)):
        hist = [x["pick_file"] for x in store.db.execute(
            "SELECT DISTINCT pick_file FROM io_op WHERE provenance='git' AND program=? AND op LIKE '%WRITE%' "
            "AND pick_file <> ? AND (pick_file LIKE ? OR pick_file LIKE '%HIST%' OR pick_file LIKE '%LOG%')",
            (r["program"], f, f"{f}%"))]
        leave.append({"program": r["program"], "line": r["line"], "launches": usage.get(r["program"]),
                      "domain": domain.get(r["program"]), "archives_to": hist})
    leave.sort(key=lambda x: -(x["launches"] or 0))

    found = sorted({s["to"] for s in steps} | {s["from"] for s in steps if s["from"]})
    order = [s for s in meta.get("order", []) if s in found] + [s for s in found if s not in meta.get("order", [])]
    return {
        "process": {"key": key, "title": meta.get("title") or f"{f}<{a}>", "blurb": meta.get("blurb"),
                    "file": f, "attr": a, "field": names.get(a)},
        "states": [{"code": s, "label": meta.get("states", {}).get(s)} for s in order],
        "steps": steps, "chosen": chosen, "programs": info, "leave": leave,
        "fields": {str(k): v for k, v in names.items()},
        "domains": doms.NAMES, "freshness": freshness(store),
    }


def catalog() -> list[Result]:
    return [{"key": k, "title": v["title"], "file": v["file"], "attr": v["attr"], "blurb": v["blurb"],
             "states": v["states"]} for k, v in PROCESSES.items()]
