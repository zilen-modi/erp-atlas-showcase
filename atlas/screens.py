"""Screen Viewer: the W4 GUI forms in src/TEMPLATES, drawn and wired to the code.

For a project (one template file) Atlas gives each form's control tree (from the
template) and, from the program that drives it:
  * handlers  -- GUI.<PROG>.<FORM>.<CONTROL>.<EVENT> labels, with the Pick files each
                 ends up writing (GOSUBs followed, one hop of CALLs), as in suggested flows;
  * bindings  -- the field a control shows or edits, from ATGUIGETPROP/ATGUISETPROP(..GPVALUE..)
                 calls whose value is a record field (XF<16>) or a variable assigned to/from one;
  * orphans   -- handlers in the code whose control isn't in the template, and buttons with no handler.
Git copies of templates can differ from live (see CLAUDE.md): this is the git copy.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any

from atlas import suggest
from atlas.parse.template import form_tree, parse_template
from atlas.store.db import Store

Result = dict[str, Any]
_PROP = re.compile(
    r"ATGUI(GET|SET)PROP\s*\(\s*[^,]*,\s*['\"]([A-Z0-9_.$]+)['\"]\s*,\s*['\"]([A-Z0-9_.$]+)['\"]\s*,\s*GPVALUE\s*,"
    r"[^,]*,[^,]*,\s*([^,]+?)\s*,", re.I)
_FIELD = re.compile(r"^([A-Z0-9_.$]+)\s*(?:<\s*(\d+)[^>]*>|\(\s*(\d+)\s*\))$")
_HANDLER = re.compile(r"^GUI\.([A-Z0-9.$%_]+?)\.([A-Z0-9_]+)\.([A-Z0-9_]+)\.([A-Z]+[0-9]*)$")
_FORM_HANDLER = re.compile(r"^GUI\.([A-Z0-9.$%_]+?)\.([A-Z0-9_]+)\.([A-Z]+[0-9]*)$")


def list_screens(store: Store, q: str = "", limit: int = 200) -> Result:
    usage = {r["program"]: r["u"] for r in store.db.execute(
        "SELECT program, MAX(used) u FROM menu WHERE program IS NOT NULL GROUP BY program")}
    args: tuple[Any, ...] = ()
    where = ""
    if q.strip():
        like = f"%{q.strip().upper()}%"
        where = ("WHERE project LIKE ? OR program LIKE ? OR project IN (SELECT project FROM screen_control "
                 "WHERE UPPER(caption) LIKE ? OR control LIKE ?)")
        args = (like, like, like, like)
    rows = [dict(r) for r in store.db.execute(f"SELECT * FROM screen {where}", args)]
    for r in rows:
        r["launches"] = usage.get(r["program"]) or usage.get(r["project"])
        r["form_list"] = json.loads(r["form_list"] or "[]")
    rows.sort(key=lambda r: (-(r["launches"] or 0), r["project"]))
    return {"total": len(rows), "screens": rows[:limit]}


def _source(store: Store, kind: str, name: str) -> str | None:
    r = store.db.execute("SELECT b.text FROM source_file s JOIN blob b ON b.hash = s.hash "
                         "WHERE s.provenance='git' AND s.kind=? AND s.name=?", (kind, name)).fetchone()
    return r["text"] if r else None


def _program_for(store: Store, project: str, header_program: str) -> str:
    """The BP program driving a project: its own name if such a program exists, else the header's."""
    for cand in (project, header_program):
        if cand and store.db.execute("SELECT 1 FROM source_file WHERE provenance='git' AND kind='BP' AND name=?",
                                     (cand.upper(),)).fetchone():
            return cand.upper()
    return header_program.upper() or project.upper()


def _record_vars(store: Store, program: str) -> dict[str, str]:
    """Record variable -> the Pick file it is read from / written to in this program (most often)."""
    c: dict[str, Counter[str]] = defaultdict(Counter)
    for r in store.db.execute("SELECT record_var, pick_file FROM io_op WHERE provenance='git' AND program=? "
                              "AND record_var != '' AND pick_file != ''", (program,)):
        c[r["record_var"].upper()][r["pick_file"]] += 1
    return {v: cnt.most_common(1)[0][0] for v, cnt in c.items()}


def bindings(store: Store, program: str) -> dict[tuple[str, str], list[Result]]:
    """(FORM, CONTROL) -> fields its value comes from / goes to."""
    text = _source(store, "BP", program)
    if not text:
        return {}
    lines = text.splitlines()
    recs = _record_vars(store, program)
    upper = [ln.upper() for ln in lines]
    out: dict[tuple[str, str], dict[tuple[str, int], Result]] = defaultdict(dict)

    def field_of(expr: str) -> tuple[str, int] | None:
        m = _FIELD.match(expr.strip().upper())
        if m and m.group(1) in recs:
            return recs[m.group(1)], int(m.group(2) or m.group(3))
        return None

    # variables used as a record key: `READ XF FROM XFFILE, XFN` -> XFN is TRANSFER's @ID
    key_of: dict[str, Counter[str]] = defaultdict(Counter)
    for r in store.db.execute("SELECT key_expr, pick_file FROM io_op WHERE provenance='git' AND program=? "
                              "AND pick_file != ''", (program,)):
        k = (r["key_expr"] or "").strip().upper()
        if re.fullmatch(r"[A-Z][A-Z0-9_.$]*", k):
            key_of[k][r["pick_file"]] += 1
    assign_cache: dict[str, Counter[tuple[str, int]]] = {}

    def via(var: str) -> Counter[tuple[str, int]]:
        """Fields a plain variable is assigned from or saved into anywhere in the program."""
        if var in assign_cache:
            return assign_cache[var]
        found: Counter[tuple[str, int]] = Counter()
        v = re.escape(var)
        from_rec = re.compile(rf"(?:^|[\s;]){v}\s*=\s*([A-Z0-9_.$]+)\s*(?:<\s*(\d+)[^>]*>|\(\s*(\d+)\s*\))")
        into_rec = re.compile(rf"([A-Z0-9_.$]+)\s*(?:<\s*(\d+)[^>]*>|\(\s*(\d+)\s*\))\s*=\s*{v}\s*(?:$|;|\*)")
        for ln in upper:
            if var not in ln:
                continue
            for rx in (from_rec, into_rec):
                for m in rx.finditer(ln):
                    if m.group(1) in recs:
                        found[(recs[m.group(1)], int(m.group(2) or m.group(3)))] += 1
        assign_cache[var] = found
        return found

    for i, ln in enumerate(upper, 1):
        if "GPVALUE" not in ln:
            continue
        for m in _PROP.finditer(ln):
            direction, form, ctl, expr = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            key = (form, ctl)
            f = field_of(expr)
            if f:
                cur = out[key].setdefault(f, {"file": f[0], "attr": f[1], "how": "direct", "lines": []})
                cur["lines"].append(i)
                continue
            if re.fullmatch(r"[A-Z][A-Z0-9_.$]*", expr) and expr not in ("GUIERRORS", "GUISTATE"):
                if expr in key_of:
                    # the key of every file the program reads with it (XFN: TRANSFER and TRANSFER-LOG)
                    for pf, _n in key_of[expr].most_common(3):
                        cur = out[key].setdefault((pf, 0), {"file": pf, "attr": 0, "how": f"record key via {expr}",
                                                           "lines": []})
                        cur["lines"].append(i)
                    continue
                for (pf, attr), n in via(expr).most_common(2):
                    cur = out[key].setdefault((pf, attr), {"file": pf, "attr": attr, "how": f"via {expr}",
                                                           "lines": [], "weight": 0})
                    cur["lines"].append(i)
                    cur["weight"] = cur.get("weight", 0) + n
            _ = direction
    res: dict[tuple[str, str], list[Result]] = {}
    for key, d in out.items():
        items = sorted(d.values(), key=lambda x: (not x["how"].startswith(("direct", "record key")),
                                                  -len(x["lines"])))
        for x in items:
            x["lines"] = sorted(set(x["lines"]))[:5]
            x.pop("weight", None)
        res[key] = items[:3]
    return res


_HANDLER_CACHE: dict[tuple[str, str], Result] = {}


def _handler_data(store: Store, program: str, sha: str) -> Result:
    """The program's GUI handler labels and what each writes; cached per git commit (sha)."""
    key = (sha, program)
    if sha and key in _HANDLER_CACHE:
        return _HANDLER_CACHE[key]
    am = suggest.action_map(store, program, max_actions=5000, include_empty=True)
    rows = [{"label": r["name"], "line": r["line"]} for r in store.db.execute(
        "SELECT name, line FROM label WHERE provenance='git' AND program=? AND name LIKE 'GUI.%'", (program,))]
    data = {"actions": am["actions"], "labels": rows}
    if sha:
        if len(_HANDLER_CACHE) > 64:
            _HANDLER_CACHE.clear()
        _HANDLER_CACHE[key] = data
    return data


def handlers(store: Store, program: str, sha: str) -> dict[tuple[str, str], list[Result]]:
    """(FORM, CONTROL or '') -> event handlers with the files they write."""
    data = _handler_data(store, program, sha)
    writes = {a["handler"]: a for a in data["actions"]}
    out: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for lb in data["labels"]:
        name = lb["label"].upper()
        m = _HANDLER.match(name)
        if m:
            form, ctl, event = m.group(2), m.group(3), m.group(4)
        else:
            m2 = _FORM_HANDLER.match(name)
            if not m2:
                continue
            form, ctl, event = m2.group(2), "", m2.group(3)
        a = writes.get(name, {})
        out[(form, ctl)].append({"event": event, "label": name, "line": lb["line"],
                                 "writes": sorted((a.get("writes") or {}).keys()), "calls": a.get("calls", [])})
    for v in out.values():
        v.sort(key=lambda h: h["line"])
    return out


def screen(store: Store, project: str) -> Result:
    row = store.db.execute("SELECT * FROM screen WHERE project=?", (project,)).fetchone()
    if row is None:
        row = store.db.execute("SELECT * FROM screen WHERE UPPER(project)=?", (project.upper(),)).fetchone()
    if row is None:
        raise ValueError(f"no screen template {project} in git")
    usage = {r["program"]: r["u"] for r in store.db.execute(
        "SELECT program, MAX(used) u FROM menu WHERE program IS NOT NULL GROUP BY program")}
    program = _program_for(store, row["project"], row["program"])
    menus = [dict(r) for r in store.db.execute(
        "SELECT code, used FROM menu WHERE program=? ORDER BY used DESC LIMIT 5", (program,))]
    return {"project": row["project"], "program": program, "header_program": row["program"],
            "saved_at": row["saved_at"], "forms": json.loads(row["form_list"] or "[]"),
            "controls": row["controls"], "launches": usage.get(program), "menus": menus}


def form(store: Store, project: str, form_name: str, sha: str = "") -> Result:
    s = screen(store, project)
    text = _source(store, "TEMPLATE", s["project"])
    if text is None:
        raise ValueError(f"no screen template {project} in git")
    t = parse_template(text, s["project"])
    form_name = form_name.upper() or (t.forms()[0].form if t.forms() else "")
    tree = form_tree(t, form_name)
    if tree is None:
        raise ValueError(f"{project} has no form {form_name}")
    hs = handlers(store, s["program"], sha)
    bs = bindings(store, s["program"])
    names = {c.name for c in t.controls if c.form == form_name}
    wiring: dict[str, Result] = {}
    for c in t.controls:
        if c.form != form_name or c.kind == "form":
            continue
        h, b = hs.get((form_name, c.name), []), bs.get((form_name, c.name), [])
        if h or b:
            wiring[c.name] = {"handlers": h, "bindings": b}
    # a control shown by record key (XFN) could be the key of several files; the one most other
    # controls on this form are bound to is the form's document (TRANSFER, not TRANSFER-LOG)
    fcount = Counter(b["file"] for v in wiring.values() for b in v["bindings"] if b["attr"])
    for v in wiring.values():
        v["bindings"].sort(key=lambda b: (not b["how"].startswith(("direct", "record key")),
                                          -fcount.get(b["file"], 0) if b["attr"] == 0 else 0))
    orphans = sorted({ctl for (f, ctl) in hs if f == form_name and ctl and ctl not in names})
    no_handler = sorted(c.name for c in t.controls if c.form == form_name and c.kind == "button"
                        and not hs.get((form_name, c.name)))
    form_events = hs.get((form_name, ""), [])
    writes = sorted({w for v in wiring.values() for h in v["handlers"] for w in h["writes"]})
    return {**s, "form": tree, "wiring": wiring, "form_events": form_events,
            "orphan_handlers": [{"control": o, "handlers": hs[(form_name, o)]} for o in orphans],
            "buttons_without_handler": no_handler, "writes": writes}
