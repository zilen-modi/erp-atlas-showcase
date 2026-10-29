"""Keep the index current with erp (git mirror / working tree) and live TEST.

Everything is incremental: git sync re-parses only files that changed since the
last indexed commit; live sync re-fetches a bounded budget of programs and only
recomputes drift where a content hash moved.  Facts citing anything that
changed are re-verified and go stale when their line no longer matches.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from atlas.config import ROOT, Config
from atlas.drift.diff import compare
from atlas.memory import facts
from atlas.parse.proc import parse_proc, schedule_of, summary
from atlas.parse.program import is_gui_callee, parse_program
from atlas.parse.records import parse_dict_printout, parse_menu
from atlas.parse.template import parse_template
from atlas.sources.git_src import GitMirror, decode, parse_filename_map
from atlas.sources.live import LiveClient, LiveError
from atlas.store.db import Store, now, text_hash

Log = Callable[[str], None]

KIND_BY_DIR = {"src/BP": "BP", "src/MENU-ITEMS": "MENU", "src/DICT": "DICT", "src/TEMPLATES": "TEMPLATE",
               "src/PROK": "PROC",
               # BASIC outside BP: the AccuTerm GUI library, and the subroutines the ERP Next API calls
               "src/GUIBP": "BP", "src/next/api-helpers": "BP", "src/next/utilities": "BP"}
# where a program lives, for people: BP is the default and goes unsaid
FOLDER_LABEL = {"src/GUIBP": "AccuTerm GUI library", "src/next/api-helpers": "ERP Next API helper",
                "src/next/utilities": "ERP Next utility"}


@dataclass
class SyncReport:
    source: str
    from_sha: str | None = None
    to_sha: str | None = None
    parsed: int = 0
    deleted: int = 0
    unchanged: int = 0
    changed_programs: set[str] = field(default_factory=set)
    staled: list[tuple[str, list[str]]] = field(default_factory=list)
    drift_updated: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def line(self) -> str:
        span = f"{(self.from_sha or '∅')[:9]}→{(self.to_sha or '')[:9]}" if self.to_sha else ""
        return (f"{self.source} {span} parsed={self.parsed} deleted={self.deleted} "
                f"unchanged={self.unchanged} stale_facts={len(self.staled)} "
                f"drift_updated={len(self.drift_updated)} errors={len(self.errors)}")


def _kind_name(path: str, fmap: dict[str, str]) -> tuple[str, str] | None:
    for d, kind in KIND_BY_DIR.items():
        if path.startswith(d + "/"):
            base = path[len(d) + 1:]
            if "/" in base:
                return None
            if kind == "PROC":               # PROK names are percent-encoded on disk: %2AYEAREND = *YEAREND
                return kind, unquote(fmap.get(base, base))
            return kind, fmap.get(base, base)
    return None


def index_text(store: Store, provenance: str, kind: str, name: str, path: str, text: str,
               sha: str | None) -> None:
    h = store.put_source(provenance, kind, name, path, text, sha)
    lines = text.splitlines()
    if kind == "BP":
        store.put_program(provenance, parse_program(name.upper(), lines), h)
    elif kind == "MENU" and provenance == "git":
        m = parse_menu(name, lines)
        store.db.execute("INSERT OR REPLACE INTO menu VALUES (?,?,?,?,?)",
                         (m.code, m.exec, m.program, m.used, m.last_used))
    elif kind == "TEMPLATE" and provenance == "git":
        index_template(store, name, text)
    elif kind == "PROC" and provenance == "git":
        index_proc(store, name, text)
    elif kind == "DICT" and provenance == "git":
        store.db.execute("DELETE FROM dict_attr WHERE pick_file=?", (name,))
        store.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading, definition, "
                             "format, depth, assoc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             [(name, d.name, d.type, d.attr, d.conv, d.heading, d.definition, d.format,
                               d.depth, d.assoc) for d in parse_dict_printout(lines)])


def index_proc(store: Store, name: str, text: str) -> None:
    p = parse_proc(text, name)
    store.db.execute("INSERT OR REPLACE INTO proc VALUES (?,?,?,?,?,?,?)",
                     (name, p.kind, p.title[:200], p.description, schedule_of(p), p.lines, json.dumps(summary(p))))


def index_template(store: Store, name: str, text: str) -> None:
    t = parse_template(text, name)
    counts = {f.form: sum(1 for c in t.controls if c.form == f.form and c.kind != "form") for f in t.forms()}
    forms = [{"name": f.form, "title": f.prop(22), "width": f.width, "height": f.height,
              "controls": counts[f.form]} for f in t.forms()]
    store.db.execute("DELETE FROM screen_control WHERE project=?", (name,))
    store.db.execute("INSERT OR REPLACE INTO screen VALUES (?,?,?,?,?,?)",
                     (name, t.program.upper(), t.saved_at, len(forms), sum(counts.values()), json.dumps(forms)))
    store.db.executemany("INSERT INTO screen_control VALUES (?,?,?,?,?)",
                         [(name, c.form, c.name, c.kind, c.prop(0) or c.prop(22)) for c in t.controls
                          if c.kind not in ("form", "app")])


def reindex_dicts(store: Store) -> int:
    """Re-parse every stored DICT printout (after a parser change), without touching git."""
    rows = store.db.execute("SELECT s.name, b.text FROM source_file s JOIN blob b ON b.hash = s.hash "
                            "WHERE s.provenance='git' AND s.kind='DICT'").fetchall()
    for r in rows:
        store.db.execute("DELETE FROM dict_attr WHERE pick_file=?", (r["name"],))
        store.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading, definition, "
                             "format, depth, assoc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             [(r["name"], d.name, d.type, d.attr, d.conv, d.heading, d.definition, d.format,
                               d.depth, d.assoc) for d in parse_dict_printout(r["text"].splitlines())])
    store.commit()
    return len(rows)


def _unindex(store: Store, provenance: str, kind: str, name: str) -> None:
    store.delete_source(provenance, kind, name)
    if provenance == "git" and kind == "MENU":
        store.db.execute("DELETE FROM menu WHERE code=?", (name,))
    if provenance == "git" and kind == "DICT":
        store.db.execute("DELETE FROM dict_attr WHERE pick_file=?", (name,))
    if provenance == "git" and kind == "PROC":
        store.db.execute("DELETE FROM proc WHERE name=?", (name,))
    if provenance == "git" and kind == "TEMPLATE":
        store.db.execute("DELETE FROM screen WHERE project=?", (name,))
        store.db.execute("DELETE FROM screen_control WHERE project=?", (name,))


# ----------------------------------------------------------------------- git

def sync_git(store: Store, cfg: Config, fetch: bool = True, full: bool = False,
             log: Log = print) -> SyncReport:
    g = cfg.git
    mirror = GitMirror(g.mirror, g.origin, g.local_fallback, g.branch)
    how = mirror.ensure()
    if how != "existing":
        log(f"mirror created from {how}")
    head = mirror.fetch() if fetch else mirror.head()
    state = store.get_state("git:erp")
    last = state["last_sha"] if state else None
    rep = SyncReport("git:erp", last, head)
    try:
        fmap = parse_filename_map(decode(mirror.read(head, g.filename_map)))
    except Exception:
        fmap = {}

    _backfill(store, mirror, head, g.index_paths, fmap, rep, log)
    if last == head and not full:
        log(f"git: up to date at {head[:9]}")
        return rep

    if last is None or full or not mirror.is_ancestor(last, head):
        tree = mirror.ls_tree(head, g.index_paths)
        wanted = {p: b for p, b in tree.items() if _kind_name(p, fmap)}
        existing = {(r["kind"], r["name"]): r["hash"] for r in store.db.execute(
            "SELECT kind, name, hash FROM source_file WHERE provenance='git'")}
        log(f"git: full index of {len(wanted)} files at {head[:9]}")
        todo: list[tuple[str, str]] = list(wanted.items())
        seen = set()
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            blobs = mirror.read_blobs([b for _p, b in chunk])
            for path, blob in chunk:
                kn = _kind_name(path, fmap)
                assert kn
                seen.add(kn)
                text = decode(blobs[blob])
                if existing.get(kn) == text_hash(text):
                    rep.unchanged += 1
                    continue
                index_text(store, "git", kn[0], kn[1], path, text, head)
                rep.parsed += 1
                if kn[0] == "BP":
                    rep.changed_programs.add(kn[1].upper())
            store.commit()
            log(f"  {min(i + 500, len(todo))}/{len(todo)}")
        for kn in set(existing) - seen:
            _unindex(store, "git", *kn)
            rep.deleted += 1
            if kn[0] == "BP":
                rep.changed_programs.add(kn[1].upper())
    else:
        changes = mirror.diff(last, head, g.index_paths)
        log(f"git: {len(changes)} changed files {last[:9]}..{head[:9]}")
        tree = mirror.ls_tree(head, g.index_paths) if changes else {}
        for ch in changes:
            if ch.status in ("D", "R"):
                kn = _kind_name(ch.old_path or ch.path, fmap)
                if kn:
                    _unindex(store, "git", *kn)
                    rep.deleted += 1
                    if kn[0] == "BP":
                        rep.changed_programs.add(kn[1].upper())
            if ch.status in ("A", "M", "R"):
                kn = _kind_name(ch.path, fmap)
                if kn and ch.path in tree:
                    text = decode(mirror.read_blobs([tree[ch.path]])[tree[ch.path]])
                    index_text(store, "git", kn[0], kn[1], ch.path, text, head)
                    rep.parsed += 1
                    if kn[0] == "BP":
                        rep.changed_programs.add(kn[1].upper())
    store.set_state("git:erp", g.branch, head, f"mirror {g.mirror}")
    store.commit()
    if rep.parsed or rep.deleted:
        # Without statistics SQLite picks the by-target index for by-program lookups (15x slower).
        store.db.execute("ANALYZE")
        store.commit()
    _after_change(store, cfg, rep, "git", log)
    return rep


def _backfill(store: Store, mirror: GitMirror, head: str, index_paths: list[str], fmap: dict[str, str],
              rep: SyncReport, log: Log) -> None:
    """A directory added to index_paths after the first sync has nothing indexed yet, and the
    incremental diff only sees files that changed: index all of it once at HEAD."""
    for d in index_paths:
        kind = KIND_BY_DIR.get(d)
        if not kind or store.db.execute("SELECT 1 FROM source_file WHERE provenance='git' AND kind=? LIMIT 1",
                                        (kind,)).fetchone():
            continue
        tree = mirror.ls_tree(head, [d])
        todo = [(p, b) for p, b in tree.items() if _kind_name(p, fmap)]
        log(f"git: first index of {d}: {len(todo)} files")
        for i in range(0, len(todo), 500):
            chunk = todo[i:i + 500]
            blobs = mirror.read_blobs([b for _p, b in chunk])
            for path, blob in chunk:
                kn = _kind_name(path, fmap)
                assert kn
                index_text(store, "git", kn[0], kn[1], path, decode(blobs[blob]), head)
                rep.parsed += 1
            store.commit()


# ------------------------------------------------------------------ worktree

def sync_worktree(store: Store, cfg: Config, root: Path, log: Log = print) -> SyncReport:
    """Index a local checkout's files as-is (uncommitted edits included).  Read-only."""
    rep = SyncReport("worktree:erp")
    fmap_path = root / cfg.git.filename_map
    fmap = parse_filename_map(fmap_path.read_text(errors="replace")) if fmap_path.exists() else {}
    existing = {(r["kind"], r["name"]): r["hash"] for r in store.db.execute(
        "SELECT kind, name, hash FROM source_file WHERE provenance='worktree'")}
    seen = set()
    for d in cfg.git.index_paths:
        base = root / d
        if not base.is_dir():
            continue
        for entry in os.scandir(base):
            if not entry.is_file():
                continue
            rel = f"{d}/{entry.name}"
            kn = _kind_name(rel, fmap)
            if not kn:
                continue
            seen.add(kn)
            text = Path(entry.path).read_bytes().decode("latin-1")
            if existing.get(kn) == text_hash(text):
                rep.unchanged += 1
                continue
            index_text(store, "worktree", kn[0], kn[1], rel, text, None)
            rep.parsed += 1
            if kn[0] == "BP":
                rep.changed_programs.add(kn[1].upper())
    for kn in set(existing) - seen:
        _unindex(store, "worktree", *kn)
        rep.deleted += 1
    store.set_state("worktree:erp", str(root), None)
    store.commit()
    rep.staled = facts.check_stale(store, rep.changed_programs) if rep.changed_programs else []
    log(rep.line())
    return rep


# ---------------------------------------------------------------------- live

def live_client(cfg: Config, parallel: bool = False) -> LiveClient:
    """parallel=True for many small record reads (capture); program source syncs stay one at a time."""
    lv = cfg.live
    return LiveClient(lv.base_url, lv.timeout_s, lv.min_interval_s, lv.cache_dir, lv.deny_tables,
                      parallel=lv.parallel if parallel else 1,
                      # one budget for TEST across every Atlas process on this machine
                      lock_dir=ROOT / ".data" / "live-locks", max_parallel=lv.parallel)


def fetch_live_programs(store: Store, cfg: Config, programs: Iterable[str], refresh: bool = True,
                        client: LiveClient | None = None, log: Log = print) -> SyncReport:
    rep = SyncReport(f"live:{cfg.environment}")
    cl = client or live_client(cfg)
    for name in programs:
        name = name.upper()
        try:
            rec = cl.read_record("BP", name, refresh=refresh)
        except LiveError as e:
            rep.errors.append(f"{name}: {e}")
            log(f"  live {name}: {e}")
            continue
        text = "\n".join(rec.lines)
        prev = store.source("live", "BP", name)
        if prev is not None and prev["hash"] == text_hash(text):
            rep.unchanged += 1
            store.db.execute("UPDATE source_file SET fetched_at=? WHERE provenance='live' AND kind='BP' "
                             "AND name=?", (rec.fetched_at, name))
        else:
            h = store.put_source("live", "BP", name, "BP", text, None, rec.fetched_at)
            store.put_program("live", parse_program(name, rec.lines), h)
            rep.parsed += 1
            rep.changed_programs.add(name)
        log(f"  live {name}: {len(rec.lines)} lines{' (cache)' if rec.from_cache else ''}")
    store.set_state(f"live:{cfg.environment}", cfg.live.base_url, None)
    store.commit()
    _after_change(store, cfg, rep, "live", log)
    return rep


def live_priority(store: Store, cfg: Config, budget: int) -> list[str]:
    """Most-used programs first (menu launches reaching them), never-checked before re-checks."""
    from atlas.query import usage_map
    usage = usage_map(store)
    fetched = {r["name"]: r["fetched_at"] for r in store.db.execute(
        "SELECT name, fetched_at FROM source_file WHERE provenance='live' AND kind='BP'")}
    known = {r["name"] for r in store.db.execute("SELECT name FROM program WHERE provenance='git'")}
    candidates = [p for p in usage if p in known and not is_gui_callee(p)]
    order = sorted(candidates, key=lambda p: (p in fetched, fetched.get(p, ""), -usage[p]))
    return order[:budget]


def sync_live(store: Store, cfg: Config, budget: int | None = None, log: Log = print) -> SyncReport:
    progs = live_priority(store, cfg, budget or cfg.live_budget)
    log(f"live: refreshing {len(progs)} programs from {cfg.environment}")
    return fetch_live_programs(store, cfg, progs, refresh=True, log=log)


# --------------------------------------------------------------------- drift

def compute_drift(store: Store, cfg: Config, program: str, blame: bool = True) -> dict[str, Any] | None:
    program = program.upper()
    g = store.source("git", "BP", program)
    v = store.source("live", "BP", program)
    if g is None or v is None:
        return None
    targets = {}
    for prov in ("git", "live"):
        targets[prov] = {r["target"] for r in store.db.execute(
            "SELECT target FROM call_edge WHERE provenance=? AND program=? AND kind IN ('GOSUB','GOTO')",
            (prov, program))}
    hunks = compare(str(g["text"]).splitlines(), str(v["text"]).splitlines(), targets["git"], targets["live"])
    commits: dict[int, list[dict[str, str]]] = {}
    if blame and g["sha"]:
        mirror = GitMirror(cfg.git.mirror, cfg.git.origin, cfg.git.local_fallback, cfg.git.branch)
        git_set = {x.strip() for x in str(g["text"]).splitlines()}
        for h in hunks:
            try:
                if h.git_start and h.cls in ("logic", "git-only"):
                    seen: dict[str, dict[str, str]] = {}
                    for c in mirror.blame_lines(g["sha"], g["path"], h.git_start, h.git_end):
                        seen.setdefault(c["sha"], c)
                    commits[h.index] = list(seen.values())
                elif h.cls == "live-only":
                    # most distinctive line: code absent from today's git copy, longest first
                    code = [x.strip() for x in h.live_lines if x.strip() and not x.strip().startswith("*")]
                    rare = [x for x in code if x not in git_set]
                    probe = max(rare or code, key=len, default="")
                    if len(probe) >= 8:
                        removed = mirror.last_touching(g["sha"], g["path"], probe)
                        if removed:
                            commits[h.index] = [{**removed, "role": "removed-in-git"}]
            except Exception:
                pass
    closest = closest_commit(cfg, g, str(v["text"]).splitlines()) if blame and hunks else None
    store.db.execute("DELETE FROM drift WHERE program=?", (program,))
    store.db.execute("DELETE FROM drift_version WHERE program=?", (program,))
    if closest:
        store.db.execute("INSERT INTO drift_version VALUES (?,?,?,?,?,?,?)",
                         (program, closest["sha"], closest["date"], closest["author"], closest["summary"],
                          closest["real_hunks"], closest["behind"]))
    ts = now()
    store.db.executemany(
        "INSERT INTO drift VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(program, h.index, h.cls, h.git_start, h.git_end, h.live_start, h.live_end,
          "\n".join(h.git_lines), "\n".join(h.live_lines), json.dumps(commits.get(h.index, [])),
          g["hash"], v["hash"], ts) for h in hunks])
    store.commit()
    return {"program": program, "hunks": hunks, "commits": commits, "closest": closest,
            "git_sha": g["sha"], "live_fetched_at": v["fetched_at"]}


REAL = ("logic", "git-only", "live-only")


def closest_commit(cfg: Config, g: Any, live: list[str], limit: int = 15) -> dict[str, Any] | None:
    """Which recent git version of the file is live TEST actually running?
    Compares live against the file's last `limit` commits; fewest real hunks wins."""
    mirror = GitMirror(cfg.git.mirror, cfg.git.origin, cfg.git.local_fallback, cfg.git.branch)
    try:
        hist = mirror.file_history(g["sha"], g["path"], limit)
    except Exception:
        return None
    best: dict[str, Any] | None = None
    for i, c in enumerate(hist):
        try:
            text = decode(mirror.read(c["sha"], g["path"]))
        except Exception:
            continue
        n = sum(1 for h in compare(text.splitlines(), live) if h.cls in REAL)
        if best is None or n < best["real_hunks"]:
            best = {**c, "real_hunks": n, "behind": i}
        if n == 0:
            break
    return best


def _after_change(store: Store, cfg: Config, rep: SyncReport, provenance: str, log: Log) -> None:
    if not rep.changed_programs:
        log(rep.line())
        return
    rep.staled = facts.check_stale(store, rep.changed_programs)
    live_names = {r["name"] for r in store.db.execute(
        "SELECT name FROM source_file WHERE provenance='live' AND kind='BP'")}
    for p in sorted(rep.changed_programs & live_names):
        if compute_drift(store, cfg, p) is not None:
            rep.drift_updated.append(p)
    for fid, why in rep.staled:
        log(f"  fact {fid} is now STALE: {'; '.join(why)}")
    log(rep.line())


# --------------------------------------------------------------------- slices

def slice_programs(store: Store, seeds: list[str], menus: list[str], hops: int) -> list[str]:
    frontier = [s.upper() for s in seeds]
    for m in menus:
        row = store.db.execute("SELECT program FROM menu WHERE code=?", (m,)).fetchone()
        if row and row["program"]:
            frontier.insert(0, row["program"])
    known = {r["name"] for r in store.db.execute("SELECT name FROM program WHERE provenance='git'")}
    out = list(dict.fromkeys(p for p in frontier if p in known))
    for _ in range(hops):
        nxt = []
        for p in list(out):
            for r in store.db.execute("SELECT DISTINCT target FROM call_edge WHERE provenance='git' "
                                      "AND program=? AND kind IN ('CALL','EXECUTE','CHAIN','ENTER')", (p,)):
                t = r["target"]
                if t in known and not is_gui_callee(t) and t not in out and t not in nxt:
                    nxt.append(t)
        out += nxt
    return out
