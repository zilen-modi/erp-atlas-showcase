"""MCP server exposing Atlas to Claude Code / Desktop (stdio).

Read tools plus exactly one write: `fact_propose`.  There is deliberately no
accept/retire tool -- a fact only becomes trusted when a named human runs
`atlas fact accept`.  Live access is not exposed by default either; the agent
reads what sync has already fetched, so it cannot generate load on TEST. The one
exception is `live_examples`, and only when the host opts in with
ATLAS_LIVE_EXAMPLES=<TEST reads per answer> (Ask Atlas sets 6): records looked up by key, or a few that match
a selection -- read-only, through the same throttled client as everything else.
"""

from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer

from atlas import config as cfgmod
from atlas import finder, process, query, sync, trace
from atlas.memory import facts

INSTRUCTIONS = """ERP Atlas indexes a legacy Pick/UniVerse ERP. Git main is the single source
of truth: explain behaviour from the git copy and cite it as PROGRAM:line. The `drift` tool only
tells you whether the TEST server runs a different version -- mention that in one short note, do
not cite TEST lines. Confirmed facts are reviewed knowledge; unconfirmed facts must be labelled so.
If you learn something non-obvious and can cite it, call fact_propose; a person confirms it later.
Attribute writes (X<n>=) change the in-memory record; persisted_by_write_at shows where it is saved."""

def _u(s: str) -> str:
    """Tool inputs sometimes arrive HTML-escaped (TRANSFER&lt;88&gt;); Pick text never contains entities."""
    return html.unescape(s) if s else s


server = MCPServer("erp-atlas", instructions=INSTRUCTIONS)
_store = None


def _st() -> Any:
    global _store
    if _store is None:
        from atlas.store.db import Store
        _store = Store(cfgmod.load().store)
    return _store


@server.tool()
def status() -> dict[str, Any]:
    """Index freshness (git sha, last sync, live fetch), counts, fact and drift totals."""
    return query.status(_st())


@server.tool()
def program_overview(name: str, provenance: str = "git") -> dict[str, Any]:
    """Signature, called programs, files opened, I/O by file, launching menus (with usage),
    callers, drift summary and known facts for one BP program. provenance: git | live | worktree."""
    return query.program_overview(_st(), name, provenance)


@server.tool()
def callers(name: str) -> dict[str, Any]:
    """Every CALL / RUN / CHAIN site that reaches this program, plus menus that launch it."""
    return query.callers(_st(), name)


@server.tool()
def who_writes(pick_file: str, attr: int) -> dict[str, Any]:
    """Programs assigning FILE<attr> (e.g. TRANSFER, 10), ordered by menu usage, with the lines
    where the record is persisted. Includes DICT names and facts scoped to FILE<attr>."""
    return query.attr_sites(_st(), pick_file, attr, "write")


@server.tool()
def who_reads(pick_file: str, attr: int) -> dict[str, Any]:
    """Programs reading FILE<attr>, ordered by menu usage."""
    return query.attr_sites(_st(), pick_file, attr, "read")


@server.tool()
def field_info(pick_file: str, attr: int) -> dict[str, Any]:
    """Summary of one attribute: DICT names, writer/reader counts, top programs, facts."""
    return query.field_info(_st(), pick_file, attr)


@server.tool()
def read_lines(name: str, start: int, end: int, provenance: str = "git") -> dict[str, Any]:
    """Exact source lines (max 400) from git, live or worktree."""
    return query.read_lines(_st(), name, start, end, provenance)


@server.tool()
def menu(code: str) -> dict[str, Any]:
    """A menu code (e.g. M4401): EXEC line, launch count, last used, and its program overview."""
    return query.menu(_st(), code)


@server.tool()
def drift(name: str, include_cosmetic: bool = False) -> dict[str, Any]:
    """Deployment check: does the TEST server run the same version as git? Returns which git
    commit TEST matches and the differences. Use it to add a one-line note, not as a source."""
    classes = None if not include_cosmetic else {"whitespace", "comment", "label", "logic",
                                                   "git-only", "live-only"}
    return query.drift(_st(), name, classes)


@server.tool()
def search_code(text: str, provenance: str = "git", limit: int = 50) -> dict[str, Any]:
    """Case-insensitive substring search over indexed BP source."""
    return query.search_code(_st(), _u(text), provenance, limit)


@server.tool()
def search_meaning(description: str, limit: int = 8) -> dict[str, Any]:
    """Find programs, sections of long programs, and facts by what they DO, from a plain description
    ("where is freight calculated", "release a depot backorder"). Use this when the question names behaviour
    rather than programs or fields. Results are machine-written summaries: use them to know where to look,
    then read_lines and cite the code. A stale summary describes an older version of the program."""
    from atlas import semantic
    return semantic.search(_st(), description, max(1, min(limit, 15)))


@server.tool()
def search(q: str) -> dict[str, Any]:
    """Find anything by name: programs (ranked by menu launches), menus, FILE<attr> fields,
    DICT names (e.g. DATEREQD -> TRANSFER<10>) and facts. Start here when unsure what a name is."""
    return query.search(_st(), _u(q))


@server.tool()
def flow(name: str, depth: int = 2) -> dict[str, Any]:
    """Call tree from a menu code (M4401) or program, 1-3 levels deep, with the Pick files each
    program reads and writes. Use this to explain an end-to-end flow before drilling into code."""
    return query.flow(_st(), name, max(1, min(depth, 3)))


@server.tool()
def file_detail(pick_file: str) -> dict[str, Any]:
    """Data dictionary for one Pick file: every attribute used in code or named in DICT, with
    writer/reader program counts, which attributes DICT does not name, and the programs opening it."""
    return query.file_detail(_st(), pick_file)


@server.tool()
def fact_lookup(query_text: str = "", scope: str = "", status: str = "") -> list[dict[str, Any]]:
    """Search learned facts (accepted first). scope like 'TRANSFER<88>' or a program name."""
    return facts.search(_st(), _u(query_text), status or None, _u(scope) or None)


@server.tool()
def fact_propose(text: str, cites: list[str], proposed_by: str, kind: str = "rule",
                 scope: str = "", rationale: str = "") -> dict[str, Any]:
    """Propose a fact for human review. cites: ['git:LG.XFER.MAINT:2036', 'doc:path', 'parity:run'].
    kind: rule|meaning|trap|glossary|mapping. It stays 'proposed' (unconfirmed) until a person
    accepts it with the CLI."""
    parsed = []
    text, scope, rationale = _u(text), _u(scope), _u(rationale)
    for c in cites:
        parts = _u(c).split(":")
        if len(parts) >= 3 and parts[0] in facts.CODE_SOURCES:
            parsed.append(facts.Cite(parts[0], parts[1], int(parts[2])))
        else:
            parsed.append(facts.Cite(parts[0], ":".join(parts[1:])))
    # When a host (e.g. Ask Atlas) sets ATLAS_PROPOSER, authorship comes from the host, never
    # from the model -- a model will happily fill in whatever identity it has seen.
    proposer = os.environ.get("ATLAS_PROPOSER") or proposed_by
    try:
        fid = facts.propose(_st(), text, kind, parsed, proposer, rationale, scope)
    except facts.FactError as e:
        return {"error": str(e)}
    return {"id": fid, "status": "proposed", "next": f"a reviewer runs: atlas fact accept {fid} --by <name>"}


# ------------------------------------------------------------------ journeys, processes, test data

def _field_ref(f: dict[str, Any]) -> str:
    return f"{f['file']}<{f['attr']}>"


def _screen(x: dict[str, Any]) -> str | None:
    return f"{x['screen']['form']}.{x['screen']['control']}" if x.get("screen") else None


def _first_menu(menus: list[dict[str, Any]]) -> str | None:
    return f"{menus[0]['menu']} via {' > '.join(menus[0]['path'])}" if menus else None


def _value(v: dict[str, Any]) -> str:
    return v["value"] + (f" = {v['label']}" if v["label"] else "") + (f" ({v['count']})" if v["count"] else "")


@server.tool()
def trace_field(pick_file: str, attr: int) -> dict[str, Any]:
    """A field's whole journey: the menus users start from, each program that sets it and where the value
    comes from (a screen field, another file's field, today's date, cleared, computed), where it's saved,
    who reads it, and which other fields it's copied into. Use it for 'where does X come from / go'."""
    j = trace.field_journey(_st(), _u(pick_file), attr)
    src = sorted(j["sources"], key=lambda s: -(s["launches"] or 0))
    rd = sorted(j["readers"], key=lambda r: (-(len(r["copies"]) + len(r["shown"])), -(r["launches"] or 0)))
    return {
        "field": j["field"], "counts": j["counts"],
        "set_by": [{"program": s["program"], "launches": s["launches"],
                    "menu": _first_menu(s["menus"]),
                    "sets": [{"line": x["line"], "kind": x["kind"], "screen": _screen(x),
                              "from": _field_ref(x["from"]) if x.get("from") else None,
                              "code": (x.get("code") or x.get("text") or "")[:120]} for x in s["sets"][:4]],
                    "saved_at": s["saved"][:3]} for s in src[:10]],
        "read_by": [{"program": r["program"], "launches": r["launches"], "lines": r["lines"][:3],
                     "copies_into": [f"{_field_ref(c['to'])} (line {c['line']})" for c in r["copies"]],
                     "shown_on": [f"{x['form']}.{x['control']} (line {x['line']})" for x in r["shown"]]}
                    for r in rd[:12]],
        "page": f"/trace?file={quote(j['field']['file'])}&attr={attr}",
    }


@server.tool()
def process_flow(process_key: str = "transfer") -> dict[str, Any]:
    """A business process read off the code, as the life of one record through its status field
    (e.g. 'transfer': TRANSFER<2> O ordered, B depot backorder, S shipped, R received): who moves a record
    into each state (program, line, menu, from which state, saved to the live file or a history file),
    which screen sets it freely, and who archives and deletes records. process_key: see the 'processes' list."""
    if process_key not in process.PROCESSES:
        return {"error": f"no process {process_key}", "processes": [p["key"] for p in process.catalog()]}
    j = process.process_flow(_st(), process_key)
    progs = j["programs"]
    states = []
    for st in j["states"]:
        steps = sorted((x for x in j["steps"] if x["to"] == st["code"]),
                       key=lambda x: -(progs[x["program"]]["launches"] or 0))
        states.append({"code": st["code"], "label": st["label"], "set_by": [
            {"program": x["program"], "line": x["line"], "from": x["from"], "saved_to": x["saved_to"],
             "launches": progs[x["program"]]["launches"],
             "menu": progs[x["program"]]["menus"][0]["menu"] if progs[x["program"]]["menus"] else None}
            for x in steps[:6]], "programs": len({x["program"] for x in steps})})
    return {"process": j["process"], "states": states,
            "set_on_screen": [{"program": c["program"], "line": c["line"], "screen": _screen(c)} for c in j["chosen"]],
            "leaves": [{"program": x["program"], "line": x["line"], "archives_to": x["archives_to"]}
                       for x in j["leave"][:6]],
            "page": f"/process?p={process_key}"}


@server.tool()
def processes() -> list[dict[str, Any]]:
    """The business processes Atlas can lay out with process_flow (key, title, file, status field, states)."""
    return process.catalog()


@server.tool()
def test_data_fields(pick_file: str, names: list[str] | None = None) -> dict[str, Any]:
    """A file's DICT fields for building a Test data search: attribute, kind (date, number, code, text),
    how often it's filled, and the values it's known to take (process states, screen dropdowns, the data
    profile), e.g. MODE: O Ordered, S Shipped, R Received. Pass names to narrow it down."""
    fs = finder.fields(_st(), _u(pick_file))
    want = {n.upper() for n in names or []}
    pick = [f for f in fs if (not want or f["name"] in want) and (want or f["values"] or (f["filled_pct"] or 0) >= 50)]
    return {"file": pick_file.upper(), "fields": [
        {"name": f["name"], "attr": f["attr"], "kind": f["kind"], "filled_pct": f["filled_pct"],
         "values": [_value(v) for v in f["values"][:12]]} for f in pick[:60]]}


@server.tool()
def test_data_link(pick_file: str, query_text: str, columns: list[str] | None = None) -> dict[str, Any]:
    """Check a RetrieVe selection and turn it into a Test data link the reader clicks to run it on TEST
    themselves, e.g. query_text 'WITH MODE = "R" AND WITH VIA = "UPS"'. Use the url it returns verbatim
    as a Markdown link; it does not touch TEST."""
    table = _u(pick_file).upper()
    try:
        crit = finder.normalise(_st(), table, {"query": _u(query_text), "columns": columns or []})
    except finder.FinderError as e:
        return {"error": str(e)}
    url = f"/test-data?file={quote(table)}&q={quote(crit['query'])}" + \
        (f"&cols={quote(','.join(crit['columns']))}" if crit["columns"] else "") + "&run=1"
    return {"url": url, "query": crit["query"], "columns": crit["columns"]}


_LIVE_CALLS = {"n": 0}


DAILY_TEST_READS = 150          # per person per day through Ask Atlas (ATLAS_LIVE_DAILY overrides)


def _live_gate(table: str, what: str) -> dict[str, Any] | None:
    """Every TEST read in an answer goes through here: on for this host, within the answer's and the person's
    daily budget, never a sensitive table. Each read is logged under the person who asked."""
    budget = int(os.environ.get("ATLAS_LIVE_EXAMPLES") or 0)
    if budget <= 0:
        return {"error": "TEST reads are off for this host; give a test_data_link instead"}
    if _LIVE_CALLS["n"] >= budget:
        return {"error": f"TEST read budget used ({budget} per answer); answer from what you have and give a "
                         "test_data_link for more"}
    if table in cfgmod.load().live.deny_tables:
        return {"error": f"{table} holds sensitive data and is never read by Atlas"}
    uid = os.environ.get("ATLAS_USER_ID") or None
    if uid:
        from atlas import auth
        daily = int(os.environ.get("ATLAS_LIVE_DAILY") or DAILY_TEST_READS)
        if auth.test_reads_today(_st(), uid, "ask-atlas") >= daily:
            return {"error": f"This person's daily TEST read limit ({daily}) is used up; answer from the code and "
                             "give a test_data_link"}
        auth.audit(_st(), uid, "test.read", {"via": "ask-atlas", "file": table, "what": what[:200]})
    _LIVE_CALLS["n"] += 1
    return None


@server.tool()
def live_record(pick_file: str, key: str) -> dict[str, Any]:
    """Read ONE record from the TEST server by its key (read-only), every attribute under its DICT names.
    Use it to check a specific code, product, transfer or setting the reader names ("is MIS an SPN?", "what's on
    transfer 1234567?"). If a code isn't a key of the file you expect, it may be an alias: product codes people
    type are usually keys in ALT-PN, whose record points at the PRODUCT key. Values come from TEST as of now; say
    so, and explain what they mean from the git code."""
    table = _u(pick_file).upper()
    if (stop := _live_gate(table, f"record {key}")) is not None:
        return stop
    try:
        r = finder.record(_st(), sync.live_client(cfgmod.load()), table, _u(key).strip())
    except finder.FinderError as e:
        msg = str(e)
        if "not found" in msg.lower() or "404" in msg:
            return {"file": table, "key": key, "found": False}
        return {"error": msg}
    # only filled attributes, compactly: <n>, its DICT names, its (multi)values as displayed
    fields = [{"attr": f["attr"], "names": f["names"][:3], "values": f["values"][:12]}
              for f in r["fields"] if f["raw"] != ""]
    return {"file": table, "key": r["key"], "found": True, "read_at": r["fetched_at"], "source": "TEST",
            "fields": fields[:150], "more": test_data_link(table, f'WITH @ID = "{r["key"]}"').get("url")}


@server.tool()
def live_examples(pick_file: str, query_text: str, columns: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    """Read up to 5 real records from the TEST server that match a RetrieVe selection, and how many match
    (read-only). Use it when the answer depends on what the data actually holds ("are there MIS products with
    S keys?", "show me a real one"). Show the records as a small table and say they were just read from TEST."""
    table = _u(pick_file).upper()
    if (stop := _live_gate(table, _u(query_text))) is not None:
        return stop
    cfg = cfgmod.load()
    q = _u(query_text)
    try:
        crit: dict[str, Any] = {"query": q, "columns": columns or []}
        r = finder.run(_st(), sync.live_client(cfg), table, crit, max(1, min(limit, 5)))
    except finder.FinderError as e:
        return {"error": str(e)}
    link = test_data_link(table, q, columns)
    return {"file": table, "query": r["criteria"]["query"], "columns": r["criteria"]["columns"],
            "records": [{"key": m["key"], **m["values"]} for m in r["matches"]],
            "matched": r["total_matches"], "more": link.get("url")}


def main() -> None:
    server.run()
