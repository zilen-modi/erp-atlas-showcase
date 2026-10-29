"""Knowledge memory: facts that Atlas learns, with a human-gated lifecycle.

Rules (ported in spirit from the parity registry, /Office/parity/src/registry.ts):

  * Anyone -- including the agent -- may PROPOSE a fact.  Nothing proposed ever
    changes an answer on its own; it is shown as "unconfirmed".
  * Only a named human may ACCEPT, and only when every citation still matches
    the source it was taken from.  The MCP server has no accept tool.
  * A fact needs at least one citation.  A git/live/worktree citation pins the
    exact line text, so the fact can be checked against the code forever after.
  * A rationale that is only a frequency ("seen twice") is rejected: how often
    something happened is not why it happens.
  * When a cited line changes, the fact goes STALE and must be re-reviewed.  A
    line that merely moved (same text nearby) is re-pointed, not staled.
  * RETIRE keeps the record; history is append-only in fact_event.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from atlas.store.db import Store, line_hash, now

KINDS = {"rule", "meaning", "trap", "glossary", "mapping"}
CODE_SOURCES = {"git", "live", "worktree"}
SOURCES = CODE_SOURCES | {"doc", "parity"}
NOT_HUMAN = {"agent", "atlas", "claude", "ai", "bot", "llm", "assistant", "system", ""}
MOVE_WINDOW = 200

_FREQ_ONLY = re.compile(
    r"^\s*(it\s+)?(was\s+)?(seen|observed|found|happened|occurs?|occurred)\s+"
    r"(once|twice|\d+\s+times|many\s+times|often|several\s+times)\W*$", re.IGNORECASE)


class FactError(ValueError):
    pass


@dataclass
class Cite:
    src: str
    ref: str
    line: int | None = None
    note: str = ""


def _source_line(store: Store, src: str, program: str, line: int) -> str | None:
    lines = store.source_lines(src, program)
    if lines is None or not (1 <= line <= len(lines)):
        return None
    return lines[line - 1]


def _next_id(store: Store) -> str:
    row = store.db.execute("SELECT id FROM fact ORDER BY id DESC LIMIT 1").fetchone()
    n = int(row["id"].split("-")[1]) + 1 if row else 1
    return f"F-{n:04d}"


def _event(store: Store, fact_id: str, actor: str, action: str, detail: str = "") -> None:
    store.db.execute("INSERT INTO fact_event VALUES (?,?,?,?,?)", (fact_id, now(), actor, action, detail))


def propose(store: Store, text: str, kind: str, cites: list[Cite], proposed_by: str,
            rationale: str = "", scope: str = "", supersedes: str | None = None) -> str:
    text, scope, rationale = html.unescape(text), html.unescape(scope), html.unescape(rationale)
    if not text.strip():
        raise FactError("fact text is empty")
    if kind not in KINDS:
        raise FactError(f"kind must be one of {sorted(KINDS)}")
    if not cites:
        raise FactError("a fact needs at least one citation")
    if rationale and _FREQ_ONLY.match(rationale):
        raise FactError("a frequency is not a rationale -- say why it happens, not how often")
    resolved = []
    for c in cites:
        if c.src not in SOURCES:
            raise FactError(f"cite src must be one of {sorted(SOURCES)}")
        text_at = None
        if c.src in CODE_SOURCES:
            if c.line is None:
                raise FactError(f"code citation {c.ref} needs a line number")
            text_at = _source_line(store, c.src, c.ref.upper(), c.line)
            if text_at is None:
                raise FactError(f"{c.src}:{c.ref}:{c.line} is not in the index (run atlas sync)")
        resolved.append((c, text_at))
    fid = _next_id(store)
    ts = now()
    store.db.execute("INSERT INTO fact VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (fid, text.strip(), kind, scope, "proposed", rationale, proposed_by,
                      None, None, None, supersedes, ts, ts))
    for c, text_at in resolved:
        store.db.execute("INSERT INTO fact_cite VALUES (?,?,?,?,?,?,?)",
                         (fid, c.src, c.ref.upper() if c.src in CODE_SOURCES else c.ref, c.line,
                          text_at, line_hash(text_at) if text_at is not None else None, c.note))
    _event(store, fid, proposed_by, "propose")
    store.commit()
    return fid


def get(store: Store, fid: str) -> dict[str, object]:
    row = store.db.execute("SELECT * FROM fact WHERE id=?", (fid,)).fetchone()
    if row is None:
        raise FactError(f"no fact {fid}")
    cites = [dict(r) for r in store.db.execute("SELECT * FROM fact_cite WHERE fact_id=?", (fid,))]
    return {**dict(row), "cites": cites}


def _cite_problems(store: Store, fid: str, repoint: bool) -> list[str]:
    """Re-check every code citation.  Moved lines are re-pointed when `repoint`."""
    problems = []
    for c in store.db.execute("SELECT rowid, * FROM fact_cite WHERE fact_id=?", (fid,)).fetchall():
        if c["src"] not in CODE_SOURCES:
            continue
        lines = store.source_lines(c["src"], c["ref"])
        if lines is None:
            problems.append(f"{c['src']}:{c['ref']} no longer exists")
            continue
        ln = c["line"]
        if 1 <= ln <= len(lines) and line_hash(lines[ln - 1]) == c["line_hash"]:
            continue
        lo, hi = max(1, ln - MOVE_WINDOW), min(len(lines), ln + MOVE_WINDOW)
        moved = [i for i in range(lo, hi + 1) if line_hash(lines[i - 1]) == c["line_hash"]]
        if moved:
            new = min(moved, key=lambda i: abs(i - ln))
            if repoint:
                store.db.execute("UPDATE fact_cite SET line=? WHERE rowid=?", (new, c["rowid"]))
                _event(store, fid, "atlas", "repoint", f"{c['ref']}:{ln} -> {new}")
            continue
        problems.append(f"{c['src']}:{c['ref']}:{ln} changed (was: {str(c['line_text']).strip()[:80]})")
    return problems


def accept(store: Store, fid: str, by: str) -> None:
    who = (by or "").strip()
    if who.lower() in NOT_HUMAN:
        raise FactError("acceptance needs a named human reviewer (--by <name>)")
    f = get(store, fid)
    if f["status"] not in ("proposed", "stale"):
        raise FactError(f"{fid} is {f['status']}; only proposed or stale facts can be accepted")
    problems = _cite_problems(store, fid, repoint=True)
    if problems:
        raise FactError("citations no longer match the source; re-cite before accepting: "
                        + "; ".join(problems))
    ts = now()
    store.db.execute("UPDATE fact SET status='accepted', accepted_by=?, accepted_at=?, stale_reason=NULL, "
                     "updated_at=? WHERE id=?", (who, ts, ts, fid))
    if f.get("supersedes"):
        store.db.execute("UPDATE fact SET status='retired', updated_at=? WHERE id=?", (ts, f["supersedes"]))
        _event(store, str(f["supersedes"]), who, "retire", f"superseded by {fid}")
    _event(store, fid, who, "accept")
    store.commit()


def retire(store: Store, fid: str, by: str, reason: str) -> None:
    get(store, fid)
    store.db.execute("UPDATE fact SET status='retired', updated_at=? WHERE id=?", (now(), fid))
    _event(store, fid, by, "retire", reason)
    store.commit()


def recite(store: Store, fid: str, by: str) -> None:
    """Refresh a stale fact's citations to the current text of the cited lines
    and send it back to review.  Only use after reading what changed."""
    get(store, fid)
    for c in store.db.execute("SELECT rowid, * FROM fact_cite WHERE fact_id=?", (fid,)).fetchall():
        if c["src"] in CODE_SOURCES:
            t = _source_line(store, c["src"], c["ref"], c["line"])
            if t is not None:
                store.db.execute("UPDATE fact_cite SET line_text=?, line_hash=? WHERE rowid=?",
                                 (t, line_hash(t), c["rowid"]))
    store.db.execute("UPDATE fact SET status='proposed', updated_at=? WHERE id=?", (now(), fid))
    _event(store, fid, by, "recite")
    store.commit()


def check_stale(store: Store, programs: set[str] | None = None) -> list[tuple[str, list[str]]]:
    """Re-verify live facts (proposed/accepted).  Returns facts newly marked stale."""
    q = "SELECT DISTINCT f.id FROM fact f JOIN fact_cite c ON c.fact_id=f.id " \
        "WHERE f.status IN ('proposed','accepted')"
    ids = [r["id"] for r in store.db.execute(q)]
    if programs is not None:
        wanted = {p.upper() for p in programs}
        ids = [i for i in ids if any(r["ref"] in wanted for r in
                                     store.db.execute("SELECT ref FROM fact_cite WHERE fact_id=?", (i,)))]
    staled = []
    for fid in ids:
        problems = _cite_problems(store, fid, repoint=True)
        if problems:
            store.db.execute("UPDATE fact SET status='stale', stale_reason=?, updated_at=? WHERE id=?",
                             ("; ".join(problems), now(), fid))
            _event(store, fid, "atlas", "stale", "; ".join(problems))
            staled.append((fid, problems))
    store.commit()
    return staled


def search(store: Store, query: str = "", status: str | None = None, scope: str | None = None,
           limit: int = 50) -> list[dict[str, object]]:
    sql = "SELECT * FROM fact WHERE 1=1"
    args: list[object] = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if scope:
        sql += " AND scope LIKE ?"
        args.append(f"%{scope}%")
    for word in query.split():
        sql += " AND (text LIKE ? OR scope LIKE ? OR id IN (SELECT fact_id FROM fact_cite WHERE ref LIKE ?))"
        args += [f"%{word}%"] * 3
    sql += " ORDER BY CASE status WHEN 'accepted' THEN 0 WHEN 'proposed' THEN 1 WHEN 'stale' THEN 2 ELSE 3 END," \
           " id LIMIT ?"
    args.append(limit)
    return [get(store, r["id"]) for r in store.db.execute(sql, args)]
