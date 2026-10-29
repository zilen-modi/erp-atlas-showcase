"""Plain-English summaries of the legacy code, written by Claude from git and kept with the program hash.

A program gets one summary: a title (what it does, not its name), a few sentences, the business words someone
would search with, and the lines that matter. A long program is first summarised section by section (split at
its labels), then as a whole from those. Small programs go several to one Claude call.

Summaries are orientation, not evidence: they say where to look, and answers still cite the code. When a
program changes in git its hash changes, its summaries show as stale, and the next run rewrites them. Most-used
programs (menu launches, one hop) come first, then the most-called subroutines.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from atlas import query
from atlas.chat import Person, run_structured
from atlas.config import Config
from atlas.parse.program import is_gui_callee
from atlas.store.db import Store, now

Result = dict[str, Any]
PROGRAM, SECTION = "program", "section"
BATCH_CHARS = 90_000          # source per Claude call (a few thousand lines)
BATCH_PROGRAMS = 8
SECTION_CHARS = 60_000        # a long program is cut into sections about this size, at labels
LINE_CHARS = 200

_ENTRY: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "What it does, in under 90 characters. Not its name."},
        "summary": {"type": "string", "description": "2-5 plain sentences: purpose, main steps, files and fields "
                                                     "it changes, notable business rules."},
        "terms": {"type": "array", "items": {"type": "string"},
                  "description": "5-12 business words and synonyms someone would search with "
                                 "(e.g. freight, ship via, backorder, transfer received), plus Pick file names."},
        "highlights": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "properties": {"line": {"type": "integer"}, "note": {"type": "string"}},
            "required": ["line", "note"]}},
    },
    "required": ["title", "summary", "terms", "highlights"],
}
_BATCH_SCHEMA = {"type": "object", "required": ["programs"], "properties": {"programs": {"type": "array", "items": {
    **_ENTRY, "properties": {"name": {"type": "string"}, **_ENTRY["properties"]},
    "required": ["name", *_ENTRY["required"]]}}}}
_ONE_SCHEMA = _ENTRY

_RULES = """Write for a developer who does not read Pick BASIC. Describe only what the code shown does; if it is too
thin to tell (a stub, a wrapper), say so. Name Pick files and fields as FILE<attr> with the DICT name where given.
Attribute assignments like XF<10> = ... change the record in memory; WRITE saves it. Highlights point at the
lines that matter most, using the line numbers shown. Plain English, no Markdown."""


# ------------------------------------------------------------------ reading back

def _row(r: Any, current: str | None) -> Result:
    return {"kind": r["kind"], "program": r["program"], "start": r["start_line"], "end": r["end_line"],
            "title": r["title"], "summary": r["summary"], "terms": json.loads(r["terms"]),
            "highlights": json.loads(r["highlights"]), "model": r["model"], "by": r["by"],
            "created_at": r["created_at"], "stale": current is not None and r["source_hash"] != current}


def get(store: Store, program: str) -> Result:
    """A program's summary and its section summaries, each marked stale if the code has changed since."""
    name = program.upper()
    p = store.db.execute("SELECT hash, line_count FROM program WHERE provenance='git' AND name=?", (name,)).fetchone()
    cur = p["hash"] if p else None
    rows = store.db.execute("SELECT * FROM summary WHERE program=? ORDER BY kind, start_line", (name,)).fetchall()
    whole = next((_row(r, cur) for r in rows if r["kind"] == PROGRAM), None)
    return {"program": name, "indexed": p is not None, "lines": p["line_count"] if p else None, "summary": whole,
            "sections": [_row(r, cur) for r in rows if r["kind"] == SECTION]}


def coverage(store: Store) -> Result:
    total = store.db.execute("SELECT COUNT(*) n FROM program WHERE provenance='git'").fetchone()["n"]
    r = store.db.execute(
        "SELECT COUNT(*) n, SUM(s.source_hash = p.hash) cur, COALESCE(SUM(s.cost_usd),0) cost FROM summary s "
        "JOIN program p ON p.provenance='git' AND p.name = s.program WHERE s.kind='program'").fetchone()
    sections = store.db.execute("SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) c FROM summary "
                                "WHERE kind='section'").fetchone()
    usage = query.usage_map(store)
    top = [n for n, _ in sorted(usage.items(), key=lambda kv: -kv[1])[:100]]
    done = {x["program"] for x in store.db.execute(
        "SELECT s.program FROM summary s JOIN program p ON p.provenance='git' AND p.name=s.program "
        "AND p.hash = s.source_hash WHERE s.kind='program'")}
    return {"programs": total, "summarised": r["cur"] or 0, "stale": (r["n"] or 0) - (r["cur"] or 0),
            "sections": sections["n"], "cost_usd": round((r["cost"] or 0) + (sections["c"] or 0), 2),
            "top_used": {"of": len(top), "done": sum(1 for n in top if n in done)}}


# ------------------------------------------------------------------ what to write next

def queue(store: Store, limit: int, only: list[str] | None = None) -> list[str]:
    """Programs without a current summary: those menus launch directly (most launches first), then those they
    call (by the launches reaching them), then the most-called; GUI and I/O plumbing last."""
    if only:                                    # asked for by name: (re)write them even if current
        known = {r["name"] for r in store.db.execute("SELECT name FROM program WHERE provenance='git'")}
        return [n.upper() for n in only if n.upper() in known][:limit]
    rows = store.db.execute(
        "SELECT p.name FROM program p LEFT JOIN summary s ON s.kind='program' AND s.program=p.name "
        "AND s.source_hash = p.hash WHERE p.provenance='git' AND s.program IS NULL").fetchall()
    todo = {r["name"] for r in rows}
    own = {r["program"]: r["u"] or 0 for r in store.db.execute(
        "SELECT program, MAX(used) u FROM menu WHERE program IS NOT NULL GROUP BY program")}
    usage = query.usage_map(store)
    called = {r["target"]: r["n"] for r in store.db.execute(
        "SELECT target, COUNT(DISTINCT program) n FROM call_edge WHERE provenance='git' "
        "AND kind IN ('CALL','EXECUTE','CHAIN','ENTER') GROUP BY target")}
    return sorted(todo, key=lambda n: (is_gui_callee(n), -own.get(n, 0), -usage.get(n, 0), -called.get(n, 0),
                                       n))[:limit]


# ------------------------------------------------------------------ prompts

def _context(store: Store, name: str) -> str:
    """What the index already knows about a program: files, fields with DICT names, calls, menus."""
    o = query.program_overview(store, name)
    io = ", ".join(f"{r['op']} {r['pick_file']}" for r in o.get("io", [])[:20] if r["pick_file"])
    fields = store.db.execute(
        "SELECT a.pick_file, a.attr, MAX(a.access) acc, (SELECT name FROM dict_attr d WHERE d.pick_file=a.pick_file "
        "AND d.attr=a.attr ORDER BY length(name) LIMIT 1) dn FROM attr_ref a WHERE a.provenance='git' AND "
        "a.program=? AND a.pick_file IS NOT NULL GROUP BY a.pick_file, a.attr ORDER BY COUNT(*) DESC LIMIT 25",
        (name,)).fetchall()
    fl = ", ".join(f"{f['pick_file']}<{f['attr']}>{' ' + f['dn'] if f['dn'] else ''} ({f['acc']})" for f in fields)
    calls = ", ".join(k.split(" ", 1)[1] for k in list(o.get("calls", {}))[:20])
    menus = ", ".join(f"{m['code']} ({m['used']} launches)" for m in o.get("menus", [])[:5])
    params = f", params {', '.join(o['params'])}" if o.get("params") else ""
    return "\n".join(x for x in [
        f"Kind: {o.get('kind')}, {o.get('lines')} lines{params}",
        f"File I/O: {io}" if io else "", f"Fields: {fl}" if fl else "", f"Calls: {calls}" if calls else "",
        f"Launched from menus: {menus}" if menus else "",
        f"Called by: {', '.join(o['callers'][:12])}" if o.get("callers") else ""] if x)


def _numbered(lines: list[str], start: int, end: int) -> str:
    """Source lines with their numbers; blank lines dropped, very long lines cut."""
    return "\n".join(f"{i}: {lines[i - 1].rstrip()[:LINE_CHARS]}" for i in range(start, end + 1)
                     if lines[i - 1].strip())


def _sections(store: Store, name: str, lines: list[str]) -> list[tuple[int, int, list[str]]]:
    """Cut a long program at labels into pieces of about SECTION_CHARS: (start, end, labels inside)."""
    labels = [(r["line"], r["name"]) for r in store.db.execute(
        "SELECT line, name FROM label WHERE provenance='git' AND program=? ORDER BY line", (name,))]
    out: list[tuple[int, int, list[str]]] = []
    start, size = 1, 0
    inside: list[str] = []
    cuts = {ln for ln, _ in labels}
    names = dict(labels)
    for i, text in enumerate(lines, 1):
        if i in cuts and size >= SECTION_CHARS * 0.6 and i > start:
            out.append((start, i - 1, inside))
            start, size, inside = i, 0, []
        if i in names:
            inside.append(names[i])
        size += min(len(text), LINE_CHARS) + 8
        if size >= SECTION_CHARS * 1.4:          # no label for a long way: cut anyway
            out.append((start, i, inside))
            start, size, inside = i + 1, 0, []
    if start <= len(lines):
        out.append((start, len(lines), inside))
    return out


# ------------------------------------------------------------------ writing

@dataclass
class Unit:
    """One Claude call: several small programs, or one section of a long program, or a long program's roll-up."""
    kind: str                       # batch | section | rollup
    programs: list[str]
    start: int = 0
    end: int = 0
    labels: tuple[str, ...] = ()


def _save(store: Store, kind: str, program: str, start: int, end: int, src_hash: str, e: Result, model: str,
          cost: float, by: str, max_line: int) -> None:
    hl = [{"line": int(h["line"]), "note": str(h["note"])[:200]} for h in e.get("highlights", [])
          if isinstance(h.get("line"), int) and 1 <= h["line"] <= max_line][:6]
    store.db.execute("INSERT OR REPLACE INTO summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (kind, program, start, end, src_hash, str(e["title"])[:140], str(e["summary"])[:2000],
                      json.dumps([str(t)[:60] for t in e.get("terms", [])][:16]), json.dumps(hl), model,
                      round(cost, 5), by, now()))


def plan(store: Store, names: list[str]) -> Iterator[Unit]:
    """Group programs into Claude calls: small ones packed together, long ones section by section."""
    batch: list[str] = []
    size = 0
    for name in names:
        lines = store.source_lines("git", name) or []
        chars = sum(min(len(x), LINE_CHARS) + 8 for x in lines if x.strip())
        if chars > BATCH_CHARS:
            if batch:
                yield Unit("batch", batch)
                batch, size = [], 0
            for s, e, labels in _sections(store, name, lines):
                yield Unit("section", [name], s, e, tuple(labels))
            yield Unit("rollup", [name])
            continue
        if batch and (size + chars > BATCH_CHARS or len(batch) >= BATCH_PROGRAMS):
            yield Unit("batch", batch)
            batch, size = [], 0
        batch.append(name)
        size += chars
    if batch:
        yield Unit("batch", batch)


def _hash(store: Store, name: str) -> str:
    return str(store.db.execute("SELECT hash FROM program WHERE provenance='git' AND name=?", (name,)).fetchone()[0])


def run_unit(store: Store, cfg: Config, u: Unit, person: Person | None, log: Callable[[str], None]) -> float:
    """Write the summaries for one unit and save them. Returns what the call cost."""
    by = person.name if person and person.name else "Atlas"
    if u.kind == "batch":
        parts = []
        for n in u.programs:
            lines = store.source_lines("git", n) or []
            parts.append(f"=== PROGRAM {n}\n{_context(store, n)}\n--- source\n{_numbered(lines, 1, len(lines))}")
        prompt = (f"Summarise each of these {len(u.programs)} programs from a legacy Pick ERP. Return one entry per "
                  f"program, with `name` exactly as given.\n{_RULES}\n\n" + "\n\n".join(parts))
        r = run_structured(cfg, prompt, _BATCH_SCHEMA, effort="low", timeout_s=600, person=person, tools=False)
        got = {str(e.get("name", "")).upper(): e for e in r["output"].get("programs", [])}
        cost = float(r.get("cost_usd") or 0)
        for n in u.programs:
            if n in got:
                _save(store, PROGRAM, n, 0, 0, _hash(store, n), got[n], r.get("model", ""), cost / len(u.programs),
                      by, len(store.source_lines("git", n) or []))
            else:
                log(f"  {n}: no summary came back; it stays in the queue")
        store.commit()
        return cost
    name = u.programs[0]
    lines = store.source_lines("git", name) or []
    src = _hash(store, name)
    if u.kind == "section":
        have = store.db.execute("SELECT 1 FROM summary WHERE kind='section' AND program=? AND start_line=? AND "
                                "end_line=? AND source_hash=?", (name, u.start, u.end, src)).fetchone()
        if have:                                     # written by an earlier, interrupted run
            return 0.0
        prompt = (f"Summarise lines {u.start}-{u.end} of {name}, a {len(lines)}-line program in a legacy Pick ERP"
                  + (f" (labels in this part: {', '.join(u.labels[:30])})" if u.labels else "")
                  + f".\nAbout the whole program:\n{_context(store, name)}\n{_RULES}\n\n"
                  + _numbered(lines, u.start, u.end))
        r = run_structured(cfg, prompt, _ONE_SCHEMA, effort="low", timeout_s=600, person=person, tools=False)
        cost = float(r.get("cost_usd") or 0)
        _save(store, SECTION, name, u.start, u.end, src, r["output"], r.get("model", ""), cost, by, len(lines))
        store.commit()
        return cost
    secs = store.db.execute("SELECT * FROM summary WHERE kind='section' AND program=? AND source_hash=? "
                            "ORDER BY start_line", (name, src)).fetchall()
    store.db.execute("DELETE FROM summary WHERE kind='section' AND program=? AND source_hash != ?", (name, src))
    outline = "\n".join(f"Lines {s['start_line']}-{s['end_line']}: {s['title']}. {s['summary']}" for s in secs)
    prompt = (f"{name} is a {len(lines)}-line program in a legacy Pick ERP. Below are summaries of its sections. "
              f"Summarise the whole program; highlights may reuse the sections' line numbers.\n"
              f"{_context(store, name)}\n{_RULES}\n\n{outline}")
    r = run_structured(cfg, prompt, _ONE_SCHEMA, effort="low", timeout_s=600, person=person, tools=False)
    cost = float(r.get("cost_usd") or 0)
    _save(store, PROGRAM, name, 0, 0, src, r["output"], r.get("model", ""), cost, by, len(lines))
    store.commit()
    return cost


def estimate(store: Store, limit: int) -> Result:
    """What the next run would cover, before spending anything: programs, Claude calls, the biggest ones."""
    names = queue(store, limit)
    units = list(plan(store, names))
    sizes = {r["name"]: r["line_count"] for r in store.db.execute(
        "SELECT name, line_count FROM program WHERE provenance='git'")}
    return {"programs": len(names), "calls": len(units), "lines": sum(sizes.get(n, 0) for n in names),
            "first": [{"name": n, "lines": sizes.get(n, 0)} for n in names[:6]]}


def summarize(store: Store, cfg: Config, limit: int, person: Person | None = None,
              log: Callable[[str], None] | None = None, only: list[str] | None = None) -> Result:
    """Write summaries for the next `limit` programs in the queue (or just `only`), then refresh the search index."""
    say = log or (lambda _m: None)
    names = queue(store, limit, only)
    if not names:
        say("Every program in scope already has a current summary.")
        return {"programs": 0, "cost_usd": 0.0}
    say(f"Summarising {len(names)} program{'s' if len(names) != 1 else ''}: {', '.join(names[:8])}"
        + (" …" if len(names) > 8 else ""))
    cost, done, failed = 0.0, 0, 0
    for u in plan(store, names):
        what = (", ".join(u.programs) if u.kind == "batch" else
                f"{u.programs[0]} lines {u.start}-{u.end}" if u.kind == "section" else f"{u.programs[0]} (whole)")
        say(f"{'Reading' if u.kind != 'rollup' else 'Pulling together'} {what}")
        try:
            cost += run_unit(store, cfg, u, person, say)
        except RuntimeError as e:                 # one bad call shouldn't lose the rest of the run
            failed += 1
            say(f"  failed: {str(e)[:200]}")
            continue
        if u.kind != "section":
            done += len(u.programs)
        say(f"  {done}/{len(names)} done · ${cost:.2f} so far")
    from atlas import semantic
    semantic.index(store, say)
    say(f"Done: {done} summarised, {failed} call{'s' if failed != 1 else ''} failed, ${cost:.2f}")
    return {"programs": done, "failed": failed, "cost_usd": round(cost, 4)}
