"""Trace: a field's journey through the legacy ERP, from where users start to where the value ends up.

For FILE<attr> it answers, with a PROGRAM:line for every step:

  how users get there   the menus whose programs lead (through CALLs) to each program that sets the field,
                        or "no menu" for batch code
  where the value comes from   each assignment `REC<attr> = ...`: a screen field (ATGUIGETPROP), another
                        file's field (`OTHER<n>`), cleared (""), today's date, or a computed expression
  where it is saved     the WRITE that puts the record back
  who reads it          every program that reads it, by domain and usage, and where a reader copies it on
                        into another file's field (`DEST<m> = ...REC<attr>...`) or shows it on a screen

Assignment parsing is a line-level reading of Pick BASIC: good for the common forms, and every hop it reports
carries the line so a person can check it. A copy into another field is labelled "possibly", since the
value may be transformed on the way.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from atlas import domains as doms
from atlas.query import attr_sites, freshness, usage_map
from atlas.store.db import Store

Result = dict[str, Any]

MENU_HOPS = 4          # how far up the CALL graph to look for the menus that lead to a program
SCREEN_LOOKBACK = 120  # lines before an assignment searched for the screen read that fed it
MAX_READERS = 60

_GET = re.compile(r"ATGUIGETPROP\s*\(\s*[\w.]+\s*,\s*'([^']+)'\s*,\s*'([^']+)'(.*)", re.I)
_SET = re.compile(r"ATGUISETPROP\s*\(\s*[\w.]+\s*,\s*'([^']+)'\s*,\s*'([^']+)'(.*)", re.I)
_FIELD = re.compile(r"\b([A-Z][\w.$]*)<\s*(\d+)\s*(?:,[^>]*)?>", re.I)


def _rhs(line: str, var: str, attr: int) -> str | None:
    """The right-hand side of `VAR<attr> = ...` on this line, if it assigns it."""
    m = re.search(rf"\b{re.escape(var)}<\s*{attr}\s*(?:,[^>]*)?>\s*=(?!=)\s*(.+)", line, re.I)
    if not m:
        return None
    rhs = re.split(r";|\bELSE\b|\bEND\b", m.group(1), maxsplit=1)[0].strip()
    return rhs


def _var_files(store: Store, program: str) -> dict[str, str]:
    """Which file each record variable in a program belongs to (its most-used binding)."""
    seen: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in store.db.execute("SELECT var, pick_file, COUNT(*) n FROM attr_ref WHERE provenance='git' AND program=? "
                              "GROUP BY var, pick_file", (program,)):
        if r["var"] and r["pick_file"]:
            seen[r["var"].upper()][r["pick_file"]] += r["n"]
    return {v: max(fs, key=lambda f: fs[f]) for v, fs in seen.items()}


def _origin(src: list[str], line: int, rhs: str, files: dict[str, str]) -> Result:
    """Where an assigned value comes from."""
    plain = rhs.strip()
    if plain in ('""', "''"):
        return {"kind": "clear", "text": "cleared"}
    if re.fullmatch(r"DATE\(\)", plain, re.I):
        return {"kind": "system", "text": "today's date"}
    other = _FIELD.search(plain)
    if other and other.group(1).upper() in files:
        var = other.group(1).upper()
        src_field = {"file": files[var], "attr": int(other.group(2)), "var": var}
        return {"kind": "copy", "text": plain[:120], "from": src_field}
    # a variable (maybe converted, ICONV(REQDT,"D2/")): look back for the screen read that filled it
    names = {v.upper() for v in re.findall(r"\b([A-Z][\w.$]*)\b(?!\s*\()", plain, re.I)} - {"D2/", "MD2"}
    for n in range(line - 1, max(0, line - SCREEN_LOOKBACK), -1):
        g = _GET.search(src[n - 1])
        if g and any(re.search(rf"\b{re.escape(v)}\b", g.group(3), re.I) for v in names):
            return {"kind": "screen", "text": plain[:120], "converted": plain.upper() not in names,
                    "screen": {"form": g.group(1), "control": g.group(2), "line": n}}
    return {"kind": "computed", "text": plain[:120]}


def _menu_paths(store: Store, program: str, callers: dict[str, set[str]], menus: dict[str, tuple[str, int]],
                limit: int = 3) -> list[Result]:
    """The busiest menus that lead to `program`, each with the CALL path down to it."""
    if program in menus:
        code, used = menus[program]
        return [{"menu": code, "used": used, "path": [program]}]
    prev: dict[str, str] = {program: ""}
    q = deque([(program, 0)])
    found: list[str] = []
    while q:
        p, d = q.popleft()
        if d >= MENU_HOPS:
            continue
        for c in callers.get(p, ()):
            if c in prev:
                continue
            prev[c] = p
            if c in menus:
                found.append(c)
            else:
                q.append((c, d + 1))
    found.sort(key=lambda c: -menus[c][1])
    out = []
    for c in found[:limit]:
        path, p = [c], c
        while prev[p]:
            p = prev[p]
            path.append(p)
        out.append({"menu": menus[c][0], "used": menus[c][1], "path": path})
    return out


def field_journey(store: Store, pick_file: str, attr: int) -> Result:
    f = pick_file.upper()
    writes = attr_sites(store, f, attr, "write")
    reads = attr_sites(store, f, attr, "read")
    domains = doms.domain_map(store)
    usage = usage_map(store)
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

    sources = []
    for p in writes["programs"]:
        name = p["program"]
        src = store.source_lines("git", name) or []
        files = _var_files(store, name)
        sets = []
        for s in p["sites"]:
            text = src[s["line"] - 1] if 0 < s["line"] <= len(src) else ""
            if s.get("op"):                       # WRITEV straight to the file
                sets.append({"line": s["line"], "kind": "direct", "text": text.strip()[:140]})
                continue
            rhs = _rhs(text, s["var"] or "", attr)
            o = (_origin(src, s["line"], rhs, files) if rhs is not None
                 else {"kind": "computed", "text": text.strip()[:120]})
            sets.append({"line": s["line"], "code": text.strip()[:160], **o})
        paths = _menu_paths(store, name, callers, menus)
        sources.append({"program": name, "launches": p["reached_launches"], "domain": domains.get(name),
                        "menus": paths, "no_menu": not paths, "sets": sets,
                        "saved": p.get("persisted_by_write_at", [])})

    readers = []
    for p in reads["programs"][:MAX_READERS]:
        name = p["program"]
        src = store.source_lines("git", name) or []
        files = _var_files(store, name)
        copies: list[Result] = []
        shown: list[Result] = []
        for s in p["sites"]:
            text = src[s["line"] - 1] if 0 < s["line"] <= len(src) else ""
            var = (s.get("var") or "").upper()
            g = _SET.search(text)
            if g and var and re.search(rf"\b{re.escape(var)}<\s*{attr}\b", g.group(3), re.I):
                shown.append({"line": s["line"], "form": g.group(1), "control": g.group(2)})
                continue
            m = _FIELD.search(text)
            if m and var and m.group(1).upper() != var and m.group(1).upper() in files:
                rhs = _rhs(text, m.group(1), int(m.group(2)))
                to = {"file": files[m.group(1).upper()], "attr": int(m.group(2)), "var": m.group(1).upper()}
                if rhs and re.search(rf"\b{re.escape(var)}<\s*{attr}\b", rhs, re.I) \
                        and not any(c["line"] == s["line"] and c["to"] == to for c in copies):
                    copies.append({"line": s["line"], "code": text.strip()[:160], "to": to})
        readers.append({"program": name, "launches": p["reached_launches"], "domain": domains.get(name),
                        "lines": [s["line"] for s in p["sites"]], "copies": copies, "shown": shown})

    return {
        "field": {"file": f, "attr": attr, "names": writes["dict_names"], "facts": writes["facts"]},
        "sources": sources, "readers": readers,
        "counts": {"writers": len(writes["programs"]), "readers": len(reads["programs"]),
                   "readers_shown": len(readers)},
        "domains": doms.NAMES,
        "launches": {"top_reader": max((usage.get(p["program"]) or 0 for p in reads["programs"]), default=0)},
        "freshness": freshness(store),
    }
