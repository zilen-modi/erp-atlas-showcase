"""Suggested Compare flows for a topic ("transfer") or a program (LG.XFER.MAINT).

Two layers:
  * action_map -- from the code, no AI: every user action (a W4 GUI event handler,
    e.g. GUI.LG.XFER.MAINT.FRMXFR.BTNOK.CLICK) and the Pick files it writes, following
    GOSUB/GOTO inside the program and one hop of CALLs into other programs.
  * suggest -- Claude Code (the user's login, Atlas tools only) turns that map into named
    flows ("Create transfer", "Ship using serial numbers", ...) with steps, files and key
    patterns. Results are cached per topic/program.
"""

from __future__ import annotations

import json
import re
from typing import Any

from atlas.chat import run_structured
from atlas.config import Config
from atlas.parse.program import is_gui_callee
from atlas.query import usage_map
from atlas.store.db import Store, now

Result = dict[str, Any]
WRITE_OPS = ("WRITE", "WRITEU", "WRITEV", "WRITEVU", "MATWRITE", "MATWRITEU", "DELETE", "DELETEU")
_HANDLER = re.compile(r"^GUI\.([A-Z0-9.$%_]+?)\.([A-Z0-9_]+)\.([A-Z0-9_]+)\.([A-Z]+[0-9]*)$")


# Files that are plumbing, not business data: COMO/saved-list scratch files, mail queues,
# and names the parser splits oddly. Comparing them only adds noise.
NOISE_PREFIX = ("&",)
NOISE = frozenset({"SMAILS", "SUBSEND.LOG", "LINE-", "HITS-SIZE", "BLANKPROD", "SEARCH.ADD"})


def is_noise(pick_file: str) -> bool:
    return pick_file.startswith(NOISE_PREFIX) or pick_file in NOISE or pick_file.endswith("-")


def _blocks(store: Store, program: str) -> list[tuple[str, int, int]]:
    rows = store.db.execute("SELECT name, line FROM label WHERE provenance='git' AND program=? ORDER BY line",
                            (program,)).fetchall()
    total = store.db.execute("SELECT line_count FROM program WHERE provenance='git' AND name=?", (program,)).fetchone()
    end = total["line_count"] if total else 0
    out = []
    for i, r in enumerate(rows):
        stop = rows[i + 1]["line"] - 1 if i + 1 < len(rows) else end
        out.append((r["name"], r["line"], stop))
    return out


def _writes_between(store: Store, program: str, a: int, b: int) -> dict[str, int]:
    out: dict[str, int] = {}
    marks = ",".join("?" * len(WRITE_OPS))
    sql = (f"SELECT pick_file, MIN(line) line FROM io_op WHERE provenance='git' AND program=? "
           f"AND line BETWEEN ? AND ? AND pick_file IS NOT NULL AND op IN ({marks}) GROUP BY pick_file")
    for r in store.db.execute(sql, (program, a, b, *WRITE_OPS)):
        if not is_noise(r["pick_file"]):
            out[r["pick_file"]] = r["line"]
    return out


def _program_writes(store: Store, program: str) -> list[str]:
    marks = ",".join("?" * len(WRITE_OPS))
    return [r["pick_file"] for r in store.db.execute(
        f"SELECT DISTINCT pick_file FROM io_op WHERE provenance='git' AND program=? AND pick_file IS NOT NULL "
        f"AND op IN ({marks}) ORDER BY pick_file", (program, *WRITE_OPS)) if not is_noise(r["pick_file"])]


def action_map(store: Store, program: str, max_actions: int = 40, include_empty: bool = False) -> Result:
    """User actions in a program and the files each one ends up writing."""
    program = program.upper()
    blocks = _blocks(store, program)
    by_label = {name: (a, b) for name, a, b in blocks}
    edges = store.db.execute("SELECT kind, target, line FROM call_edge WHERE provenance='git' AND program=?",
                             (program,)).fetchall()
    callee_writes: dict[str, list[str]] = {}

    def reach(label: str, seen: set[str]) -> tuple[dict[str, str], set[str]]:
        """files -> how (line or callee), and callees, for a block and the blocks it jumps to."""
        files: dict[str, str] = {}
        calls: set[str] = set()
        stack = [label]
        while stack:
            lb = stack.pop()
            if lb in seen or lb not in by_label or len(seen) > 60:
                continue
            seen.add(lb)
            a, b = by_label[lb]
            for f, ln in _writes_between(store, program, a, b).items():
                files.setdefault(f, f"{program}:{ln}")
            for e in edges:
                if not a <= e["line"] <= b:
                    continue
                if e["kind"] in ("GOSUB", "GOTO"):
                    stack.append(e["target"])
                elif e["kind"] in ("CALL", "EXECUTE", "CHAIN") and not is_gui_callee(e["target"]):
                    calls.add(e["target"])
        for c in calls:
            if c not in callee_writes:
                callee_writes[c] = _program_writes(store, c)
            for f in callee_writes[c]:
                files.setdefault(f, f"via {c}")
        return files, calls

    actions = []
    for name, line, _end in blocks:
        m = _HANDLER.match(name)
        if not m:
            continue
        files, calls = reach(name, set())
        if not files and not include_empty:
            continue
        form, control, event = m.group(2), m.group(3), m.group(4)
        actions.append({"handler": name, "form": form, "control": control, "event": event, "line": line,
                        "writes": files, "calls": sorted(calls)[:12]})
    actions.sort(key=lambda x: -len(x["writes"]))  # type: ignore[arg-type]
    if not actions:                                 # not a W4 GUI program: the program as one action
        files, calls = {}, set()
        for name, _a, _b in blocks[:1] or [("(main)", 1, 1)]:
            files, calls = reach(name, set()) if blocks else ({}, set())
        for f in _program_writes(store, program):
            files.setdefault(f, program)
        if files:
            actions.append({"handler": "(whole program)", "form": "", "control": "", "event": "", "line": 1,
                            "writes": files, "calls": sorted(calls)[:12]})
    menus = [dict(r) for r in store.db.execute("SELECT code, used FROM menu WHERE program=? ORDER BY used DESC",
                                               (program,))]
    return {"program": program, "menus": menus, "actions": actions[:max_actions]}


def programs_for(store: Store, topic: str, limit: int = 3) -> list[str]:
    """Most-used W4/BP programs matching a topic word, by name or by what their menus run."""
    t = topic.strip().upper()
    if not t:
        return []
    exact = store.db.execute("SELECT name FROM program WHERE provenance='git' AND name=?", (t,)).fetchone()
    if exact:
        return [exact["name"]]
    usage = usage_map(store)
    words = [w for w in re.split(r"[^A-Z0-9]+", t) if len(w) >= 2]
    # common abbreviations used in program names
    alias = {"TRANSFER": ["XFR", "XFER", "TRANSFER"], "ORDER": ["ORD", "ORDER"], "INVOICE": ["INV", "INVOICE"],
             "PURCHASE": ["PO", "PURCH"], "RECEIVE": ["RCV", "REC", "RECEIV"], "PRODUCT": ["PRD", "PROD", "PRODUCT"],
             "CUSTOMER": ["CUS", "CUST"], "SHIP": ["SHIP"], "PAYMENT": ["PAY", "PMT"], "QUOTE": ["QUOTE", "QTE"]}
    needles = set()
    for w in words:
        needles |= set(alias.get(w, [w])) | set(alias.get(w.rstrip("S"), []))
    cands = {r["name"] for n in needles for r in store.db.execute(
        "SELECT name FROM program WHERE provenance='git' AND name LIKE ?", (f"%{n}%",))}
    cands |= {r["program"] for n in needles for r in store.db.execute(
        "SELECT program FROM menu WHERE program IS NOT NULL AND (exec LIKE ? OR code LIKE ?)", (f"%{n}%", f"%{n}%"))}
    ranked = sorted((c for c in cands if c and not is_gui_callee(c)), key=lambda p: -(usage.get(p) or 0))
    top = [p for p in ranked if usage.get(p)][:10]
    # a busy caller lends usage to every helper it calls, so among the busiest candidates prefer the
    # programs with the most real user actions -- the maintenance screens, not the helpers
    top.sort(key=lambda p: -len(action_map(store, p)["actions"]))
    return top[:limit]


# ------------------------------------------------------------------ AI naming

SCHEMA = {
    "type": "object",
    "properties": {
        "flows": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "program": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "files": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"pick_file": {"type": "string"}, "key_template": {"type": "string"},
                                   "why": {"type": "string"}},
                    "required": ["pick_file", "key_template", "why"]}},
                "evidence": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "description", "program", "steps", "files", "evidence"]}},
    },
    "required": ["flows"],
}

PROMPT = """A developer is testing that ERP Next writes the same Pick records as the legacy UniVerse ERP.
They do the same business action in both systems, then compare every file the action touches at each
checkpoint. Propose the Compare flows worth setting up for: {topic}.

Below is an action map extracted from the git source: each user action (W4 GUI event handler) and the
files it writes (directly, through GOSUBs, or via a called program, one hop). Use the erp-atlas tools
(read_lines, flow, program_overview, who_writes, file_detail, search) to understand what the actions
really do -- modes like order/ship/receive, serial numbers, kits, cancel/delete -- before naming them.

Return 3-8 flows. For each:
- name: a business action a tester would recognise ("Create transfer", "Ship transfer using serial numbers").
- description: one sentence on what is tested.
- program: the main BP program.
- steps: the checkpoints in order, each starting with "After", e.g. ["After create", "After ship"].
- files: every Pick file the flow writes that should be compared. key_template must be a literal pattern
  whose placeholders are {{key}} (the main document number as the user types it) or {{num}} (the same
  number without a letter prefix, T11027 -> 11027), e.g. "{{key}}", "{{key}}-1", "{{num}}", "T{{num}}".
  If one file has several records per document, list it once per pattern. If the record is keyed by
  something else (a part number, branch, user), set key_template to "" and say in why how the key is built.
  why: a short reason.
- evidence: 2-5 citations as PROGRAM:line from the git copy.
Only use files that appear in the map or that you confirmed in the code. Skip pure navigation/print actions.

ACTION MAP:
{map}"""


_PATTERN = re.compile(r"[A-Za-z0-9.\-*#]*\{(?:key|num)\}[A-Za-z0-9.\-*#]*")


def sanitize_files(files: list[Result]) -> list[Result]:
    """Make every key_template something capture can use: only {key} placeholders, one pattern per entry.
    Records keyed by something else fall back to {key} with the hint kept, to override per run."""
    out: list[Result] = []
    seen: set[tuple[str, str]] = set()
    for f in files:
        pf = str(f.get("pick_file", "")).strip().upper()
        raw = str(f.get("key_template") or "").strip()
        why = str(f.get("why") or "").strip()
        pats = _PATTERN.findall(raw)
        extra = re.sub(r"\{(?:key|num)\}", "", raw)
        if raw and not pats or "{" in extra:
            # keyed by something other than the document number: keep the recipe as a hint
            hint = f"Key: {raw}. Set this record's key under Keys on the run."
            why = f"{why} {hint}".strip() if raw else why
            pats = ["{key}"]
        for p in pats or ["{key}"]:
            if (pf, p) in seen:
                continue
            seen.add((pf, p))
            out.append({"pick_file": pf, "key_template": p, "why": why})
    return out


def _cache_key(topic: str, program: str | None) -> str:
    return (program or topic).strip().upper()


def cached(store: Store, topic: str = "", program: str | None = None) -> Result | None:
    _ensure(store)
    r = store.db.execute("SELECT * FROM cmp_suggestion WHERE key=?", (_cache_key(topic, program),)).fetchone()
    if not r:
        return None
    payload = json.loads(r["payload"])
    for f in payload.get("flows", []):
        f["files"] = sanitize_files(f.get("files", []))
    return {**payload, "created_at": r["created_at"]}


def _ensure(store: Store) -> None:
    store.db.execute("CREATE TABLE IF NOT EXISTS cmp_suggestion (key TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")


def quick(store: Store, topic: str = "", program: str | None = None) -> Result:
    """Instant, code-only suggestions: one flow per program covering every file its actions write."""
    progs = [program.upper()] if program else programs_for(store, topic)
    out = []
    maps = []
    for p in progs:
        am = action_map(store, p)
        maps.append(am)
        files: dict[str, str] = {}
        for a in am["actions"]:
            for f, how in a["writes"].items():
                files.setdefault(f, how)
        if files:
            out.append({"name": f"Everything {p} writes", "description": f"All files written by {p}'s user actions.",
                        "program": p, "steps": ["After create"],
                        "files": [{"pick_file": f, "key_template": "{key}", "why": f"written at {how}"}
                                  for f, how in sorted(files.items())],
                        "evidence": [a["handler"] for a in am["actions"][:3]], "source": "code"})
    return {"topic": topic, "programs": progs, "flows": out, "actions": maps}


def suggest(store: Store, cfg: Config, topic: str = "", program: str | None = None, log: Any = print) -> Result:
    """Ask Claude Code to name flows from the action map; cache the result."""
    _ensure(store)
    base = quick(store, topic, program)
    if not base["programs"]:
        raise ValueError(f"no programs found for “{topic}”")
    compact = []
    for am in base["actions"]:
        compact.append({"program": am["program"], "menus": am["menus"][:3], "actions": [
            {"handler": a["handler"], "line": a["line"], "writes": a["writes"], "calls": a["calls"]}
            for a in am["actions"][:25]]})
    what = program.upper() if program else f"“{topic}” (programs {', '.join(base['programs'])})"
    prompt = PROMPT.format(topic=what, map=json.dumps(compact)[:60000])
    log(f"asking Claude Code to name flows for {what}…")
    res = run_structured(cfg, prompt, SCHEMA, effort="medium", log=log)   # naming flows doesn't need full effort
    flows = res["output"].get("flows") or []
    known = {r["pick_file"] for r in store.db.execute(
        "SELECT DISTINCT pick_file FROM file_handle WHERE provenance='git'")}
    for f in flows:
        f["source"] = "ai"
        f["files"] = sanitize_files([x for x in f.get("files", []) if x.get("pick_file", "").upper() in known])
        f["steps"] = [s for s in f.get("steps", []) if s.strip()] or ["After create"]
    payload = {"topic": topic, "program": program, "programs": base["programs"],
               "flows": [f for f in flows if f["files"]], "cost_usd": res["cost_usd"]}
    store.db.execute("INSERT OR REPLACE INTO cmp_suggestion VALUES (?,?,?)",
                     (_cache_key(topic, program), json.dumps(payload), now()))
    store.commit()
    log(f"{len(payload['flows'])} flows suggested")
    return payload
