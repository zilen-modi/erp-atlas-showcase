"""Test Data Finder: find records on TEST that fit a scenario, instead of hunting for keys.

A scenario's criteria:
  query    -- a RetrieVe selection ("WITH MODE = \\"S\\" AND WITH DATE-ORD GE \\"09/01/2026\\"") run
              through the python layer's read-only /table/query, using DICT names;
  related  -- records that must (or must not) exist in other files, by key pattern
              ({"file": "TRANSFER-HIST", "key": "{key}-1", "exists": true} = "already shipped");
  columns  -- DICT names to show for each match.
Claude Code can write the criteria from a plain-English description, using the DICT, the
screen's combo items (MODE: O Order / S Ship / R Receive) and the data profile.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta
from typing import Any

from atlas import dictmodel, profile, screens
from atlas.chat import Person, run_structured
from atlas.config import Config
from atlas.sources.live import LiveClient, LiveError
from atlas.store.db import Store, now

Result = dict[str, Any]


class FinderError(ValueError):
    pass


class FinderUnreachable(FinderError):
    """TEST couldn't be reached (VPN, DNS, timeout): says nothing about the criteria."""


_SAFE = re.compile(r"""^WITH\s[A-Z0-9 .#$%&*/<>=\-_'"@,()\[\]]+$""", re.I)
_KEYWORDS = re.compile(r"\b(SELECT|SSELECT|LIST|SORT|DELETE|CLEAR|COPY|ED|CREATE|RUN|EXECUTE|SH|DOS)\b", re.I)


def check_query(q: str) -> str:
    """Only a selection clause: starts WITH, no statement separators, no verbs."""
    q = " ".join((q or "").split())
    if not q:
        return ""
    if len(q) > 600 or ";" in q or "\\" in q or not _SAFE.match(q) or _KEYWORDS.search(q.replace('"', " ")):
        raise FinderError('The query must be a selection like: WITH MODE = "S" AND WITH DATE-ORD GE "09/01/2026"')
    return q


def _dict_names(store: Store, table: str) -> set[str]:
    return {r["name"].upper() for r in store.db.execute("SELECT name FROM dict_attr WHERE pick_file=?", (table,))}


def normalise(store: Store, table: str, criteria: Result) -> Result:
    names = _dict_names(store, table)
    cols = [c.upper() for c in criteria.get("columns") or [] if c.upper() in names][:8]
    related = []
    for r in criteria.get("related") or []:
        f, k = str(r.get("file", "")).upper().strip(), str(r.get("key", "")).strip()
        if f and ("{key}" in k or "{num}" in k):
            related.append({"file": f, "key": k, "exists": bool(r.get("exists", True)), "why": r.get("why", "")})
    return {"query": check_query(criteria.get("query", "")), "columns": cols, "related": related[:4]}


def run(store: Store, client: LiveClient, table: str, criteria: Result, limit: int = 20, log: Any = None) -> Result:
    """Matches on TEST, newest keys first where the key is numeric, with the related checks applied."""
    say = log or (lambda _m: None)
    table = table.upper()
    c = normalise(store, table, criteria)
    # related checks filter afterwards: select plenty so enough survive
    fetch = min(max(limit * 20, 200), 400) if c["related"] else min(limit, 400)
    cols = c["columns"] or []
    say(f"Selecting {table} {c['query'] or '(all)'}…")
    # the key is always asked for; asking twice (an @ID column) is a 422 from the python layer
    attrs = ["@ID", *[x for x in cols if x.upper() not in ("@ID", "ID")]]
    try:
        rows = client.query(table, c["query"], fetch, attrs)
    except LiveError as e:
        msg = str(e)
        if "not found" in msg.lower():
            rows = []
        elif "live call failed" in msg.lower():
            raise FinderUnreachable(f"TEST couldn't be reached: {msg[:300]}") from e
        else:
            raise FinderError(f"TEST rejected the query: {msg[:300]}") from e
    keys = [str(r.get("ID")) for r in rows if r.get("ID")]
    say(f"{len(keys)} record{'s' if len(keys) != 1 else ''} match the selection")
    by_key = {str(r.get("ID")): r for r in rows}
    checks: dict[str, dict[str, bool]] = {k: {} for k in keys}
    for rel in c["related"]:
        rkeys = {k: screens_key(rel["key"], k) for k in keys}
        want = list(dict.fromkeys(rkeys.values()))
        got: dict[str, list[str]] = {}
        for i in range(0, len(want), 200):
            got.update(client.read_block(rel["file"], want[i:i + 200]))
        for k, rk in rkeys.items():
            checks[k][f"{rel['file']} {rel['key']}"] = bool(got.get(rk))
        say(f"Checked {rel['file']} {rel['key']} for {len(keys)} records")
    out: list[Result] = []
    for k in keys:
        ok = all(checks[k].get(f"{r['file']} {r['key']}") == r["exists"] for r in c["related"])
        if not ok:
            continue
        r = by_key[k]
        out.append({"key": k, "values": {col: _flat(_cell(r, k, col)) for col in cols},
                    "lists": {col: _values(_cell(r, k, col)) for col in cols},
                    "related": checks[k]})
    def order(x: Result) -> tuple[bool, int, str]:
        k = str(x["key"])
        return (not k.isdigit(), -int(k) if k.isdigit() else 0, k)
    out.sort(key=order)
    return {"table": table, "criteria": c, "selected": len(keys), "matches": out[:limit],
            "total_matches": len(out), "capped": len(keys) >= fetch}


def screens_key(template: str, key: str) -> str:
    from atlas.compare import resolve_key
    return resolve_key(template, key)


def _cell(row: Result, key: str, col: str) -> Any:
    """A column of a selected row; the key columns are the key itself."""
    return key if col.upper() in ("@ID", "ID") else row.get(col.lower(), row.get(col, ""))


def _values(v: Any) -> list[str]:
    """A column's values as a list: one per value of a multivalued field (subvalues joined)."""
    if isinstance(v, list):
        return [x for x in (_flat(y) for y in v) if x != ""]
    return [] if v in (None, "") else [str(v)]


def _flat(v: Any) -> str:
    if isinstance(v, list):
        return " ] ".join(_flat(x) for x in v if _flat(x) != "")
    return "" if v is None else str(v)


# ------------------------------------------------------------------ fields, values and one record

PICK_EPOCH = date(1967, 12, 31)
VM, SVM = "\xfd", "\xfc"


def show(conv: str, raw: str) -> str:
    """A stored value as a person reads it: D conversions are day numbers, MDn/MRn are scaled integers."""
    c = (conv or "").strip().upper()
    if raw == "" or not c:
        return raw
    try:
        if c.startswith("D"):
            return (PICK_EPOCH + timedelta(days=int(raw))).isoformat()
        m = re.match(r"M[DR](\d)", c)
        if m:
            n = int(m.group(1))
            return f"{int(raw) / 10 ** n:.{n}f}" if n else str(int(raw))
    except (ValueError, OverflowError):
        return raw
    return raw


def _kind(conv: str, prof: Result | None) -> str:
    c = (conv or "").upper()
    if c.startswith("D"):
        return "date"
    if c.startswith(("MD", "MR")):
        return "number"
    return str(prof["kind"]) if prof and prof.get("kind") else "text"


def field_values(store: Store, table: str) -> dict[int, list[Result]]:
    """Known values per attribute: a process's named states, a screen dropdown's items, the profile's most common."""
    from atlas import process
    out: dict[int, dict[str, Result]] = {}

    def add(attr: int, value: str, label: str | None = None, count: int | None = None, source: str = "") -> None:
        v = out.setdefault(attr, {}).setdefault(value, {"value": value, "label": None, "count": None, "source": source})
        v["label"] = v["label"] or label
        v["count"] = v["count"] if v["count"] is not None else count

    for p in process.PROCESSES.values():
        if p["file"] == table:
            for code, label in p["states"].items():
                add(p["attr"], code, label, source="process")
    for r in store.db.execute("SELECT project FROM screen WHERE project IN (SELECT DISTINCT program FROM io_op "
                              "WHERE provenance='git' AND pick_file=?) LIMIT 5", (table,)):
        try:
            sc = screens.screen(store, r["project"])
            for f in sc["forms"][:3]:
                d = screens.form(store, r["project"], f["name"])
                for ctl, w in d["wiring"].items():
                    b = next((x for x in w["bindings"] if x["file"] == table and x["attr"]), None)
                    if not b:
                        continue
                    for i in (_node(d["form"]["controls"], ctl) or {}).get("items") or []:
                        add(int(b["attr"]), str(i["value"]), str(i["label"]), source="screen")
        except ValueError:
            continue
    prof = profile.latest(store, table)
    for a in (prof or {}).get("attributes", []):
        if a["kind"] == "code":
            for v, c in a["top"][:12]:
                add(int(a["pos"]), str(v), count=int(c), source="profile")
    return {k: list(v.values()) for k, v in out.items()}


def fields(store: Store, table: str) -> list[Result]:
    """The DICT of a file as query-builder fields: name, attribute, kind, how often it's filled, known values."""
    table = table.upper()
    prof = {int(a["pos"]): a for a in (profile.latest(store, table) or {}).get("attributes", [])}
    values = field_values(store, table)
    rows = store.db.execute("SELECT name, attr, conv, depth FROM dict_attr WHERE pick_file=? AND type IN ('A','D') "
                            "ORDER BY attr, name", (table,)).fetchall()
    out = []
    for r in rows:
        a, pr = r["attr"], prof.get(r["attr"])
        out.append({"name": r["name"], "attr": a, "conv": r["conv"] or "", "multi": (r["depth"] or "") == "M",
                    "kind": "key" if a == 0 else _kind(r["conv"], pr), "filled_pct": pr["filled_pct"] if pr else None,
                    "values": values.get(a, [])})
    return out


def _named(store: Store, table: str, lines: list[str]) -> list[Result]:
    names: dict[int, list[tuple[str, str]]] = {}
    for r in store.db.execute("SELECT name, attr, conv FROM dict_attr WHERE pick_file=? AND type IN ('A','D') "
                              "AND attr > 0 ORDER BY name", (table,)):
        names.setdefault(r["attr"], []).append((r["name"], r["conv"] or ""))
    out = []
    for i, raw in enumerate(lines, start=1):
        conv = next((c for _, c in names.get(i, []) if c), "")
        vals = [[show(conv, sv) for sv in v.split(SVM)] for v in raw.split(VM)] if raw != "" else []
        out.append({"attr": i, "names": [n for n, _ in names.get(i, [])], "conv": conv, "raw": raw,
                    "values": [" · ".join(x for x in v if x != "") for v in vals]})
    return out


def record(store: Store, client: LiveClient, table: str, key: str, related: list[Result] | None = None) -> Result:
    """One TEST record, every attribute under its DICT names and converted, with the scenario's related records."""
    table = table.upper()
    try:
        rec = client.read_record(table, key, max_age_s=60)
    except LiveError as e:
        raise FinderError(f"Couldn't read {table} {key}: {str(e)[:200]}") from e
    rel = []
    for r in (related or [])[:4]:
        f, k = str(r.get("file", "")).upper(), screens_key(str(r.get("key", "")), key)
        if not f or not k:
            continue
        try:
            lines = client.read_record(f, k, max_age_s=60).lines
            rel.append({"file": f, "key": k, "exists": True, "fields": _named(store, f, lines)})
        except LiveError:
            rel.append({"file": f, "key": k, "exists": False, "fields": []})
    return {"table": table, "key": key, "fetched_at": rec.fetched_at, "fields": _named(store, table, rec.lines),
            "related": rel}


# ------------------------------------------------------------------ scenarios

def save(store: Store, body: Result, sid: str | None = None, user_id: str | None = None) -> Result:
    table = str(body.get("pick_file", "")).upper().strip()
    name = str(body.get("name", "")).strip()
    if not table or not name:
        raise FinderError("a scenario needs a file and a name")
    crit = normalise(store, table, body.get("criteria") or {})
    ts = now()
    if sid is None:
        sid = uuid.uuid4().hex[:10]
        store.db.execute("INSERT INTO finder_scenario (id, flow_id, pick_file, name, description, criteria, "
                         "created_at, updated_at, user_id, shared) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (sid, body.get("flow_id"), table, name, body.get("description", ""), json.dumps(crit),
                          ts, ts, user_id, 1 if body.get("shared") else 0))
    else:
        store.db.execute("UPDATE finder_scenario SET name=?, description=?, criteria=?, pick_file=?, updated_at=?, "
                         "shared=COALESCE(?, shared) WHERE id=?",
                         (name, body.get("description", ""), json.dumps(crit), table, ts,
                          None if body.get("shared") is None else int(bool(body["shared"])), sid))
    store.commit()
    return get(store, sid)


_SCENARIO = "SELECT s.*, u.name owner FROM finder_scenario s LEFT JOIN app_user u ON u.id = s.user_id"


def _scenario(r: Any) -> Result:
    return {**dict(r), "shared": bool(r["shared"]), "criteria": json.loads(r["criteria"])}


def get(store: Store, sid: str) -> Result:
    r = store.db.execute(_SCENARIO + " WHERE s.id=?", (sid,)).fetchone()
    if r is None:
        raise FinderError(f"no scenario {sid}")
    return _scenario(r)


def visible(s: Result, user_id: str | None) -> bool:
    """Your own saved searches, the ones shared with the team, and those from before sign-in (no owner)."""
    return user_id is None or s["user_id"] in (None, user_id) or bool(s["shared"])


def list_all(store: Store, flow_id: str | None = None, table: str | None = None,
             user_id: str | None = None) -> list[Result]:
    q, args = _SCENARIO, []
    conds = []
    if user_id:
        conds.append("(s.user_id=? OR s.user_id IS NULL OR s.shared=1)")
        args.append(user_id)
    if flow_id:
        conds.append("(s.flow_id=? OR s.flow_id IS NULL)")
        args.append(flow_id)
    if table:
        conds.append("s.pick_file=?")
        args.append(table.upper())
    if conds:
        q += " WHERE " + " AND ".join(conds)
    return [_scenario(r) for r in store.db.execute(q + " ORDER BY s.updated_at DESC", args)]


def delete(store: Store, sid: str) -> None:
    store.db.execute("DELETE FROM finder_scenario WHERE id=?", (sid,))
    store.commit()


def mark_run(store: Store, sid: str, count: int) -> None:
    store.db.execute("UPDATE finder_scenario SET last_run=?, last_count=? WHERE id=?", (now(), count, sid))
    store.commit()


# ------------------------------------------------------------------ AI: description -> criteria

SCHEMA = {
    "type": "object", "required": ["query", "columns", "related", "explanation"],
    "properties": {
        "query": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "related": {"type": "array", "items": {"type": "object", "required": ["file", "key", "exists"],
                                               "properties": {"file": {"type": "string"}, "key": {"type": "string"},
                                                              "exists": {"type": "boolean"},
                                                              "why": {"type": "string"}}}},
        "explanation": {"type": "string"},
        "name": {"type": "string"},
    },
}

PROMPT = """Turn a tester's description into criteria for finding {table} records on the TEST server.

Description: {desc}
Today is {today}.

Return:
- query: a UniVerse RetrieVe selection clause using ONLY the DICT names below, e.g.
  WITH MODE = "S" AND WITH DATE-ORD GE "09/01/2026". Rules: every condition starts with WITH; values in
  double quotes; dates as "MM/DD/YYYY" (the DICT conversion applies them); use # for not-equal, "" for empty,
  GE/LE/GT/LT for ranges, AND/OR between conditions. Leave it "" if nothing can be expressed this way.
- related: other records that must exist (exists=true) or must not exist (exists=false), by key pattern with
  {{key}} = the {table} record's key, e.g. {{"file": "TRANSFER-HIST", "key": "{{key}}-1", "exists": true}} for
  "already shipped". Only use files and patterns you can justify from the code (use the Atlas tools to check how
  the program writes them). Usually 0-2 entries.
- columns: 3-6 DICT names that let a tester recognise a good match (dates, status/mode, branch, counts).
- name: a short scenario name (e.g. "Shipped transfer with serial numbers").
- explanation: one or two sentences on how the criteria express the description, and anything you could NOT
  express (so the tester can check it by hand).

DICT of {table} (name, attribute, conversion, S/M):
{dict}

Known values (from the screen's dropdowns and the data profile):
{values}
"""


def _known_values(store: Store, table: str) -> list[str]:
    out: list[str] = []
    for r in store.db.execute("SELECT project FROM screen WHERE project IN (SELECT DISTINCT program FROM io_op "
                              "WHERE provenance='git' AND pick_file=?) LIMIT 5", (table,)):
        try:
            s = screens.screen(store, r["project"])
            for f in s["forms"][:3]:
                d = screens.form(store, r["project"], f["name"])
                for ctl, w in d["wiring"].items():
                    b = next((x for x in w["bindings"] if x["file"] == table and x["attr"]), None)
                    if not b:
                        continue
                    node = _node(d["form"]["controls"], ctl)
                    if node and node.get("items"):
                        items = ", ".join(f"{i['value']}={i['label']}" for i in node["items"][:12])
                        out.append(f"{table}<{b['attr']}> ({ctl} on {r['project']}): {items}")
        except ValueError:
            continue
    prof = profile.latest(store, table)
    if prof:
        for a in prof["attributes"]:
            if a["kind"] == "code" and a["top"]:
                out.append(f"{table}<{a['pos']}> {a['names'][:1]}: " + ", ".join(f"{v} ({c})" for v, c in a["top"][:8]))
    return out[:40]


def _node(nodes: list[Result], name: str) -> Result | None:
    for n in nodes:
        if n["name"] == name:
            return n
        k = _node(n.get("children", []), name)
        if k:
            return k
    return None


def suggest(store: Store, cfg: Config, table: str, description: str, log: Any = None,
            person: Person | None = None) -> Result:
    say = log or (lambda _m: None)
    table = table.upper()
    try:
        fields = dictmodel.get(store, table)["fields"]
    except ValueError as e:
        raise FinderError(str(e)) from e
    rows = store.db.execute("SELECT name, attr, conv, depth FROM dict_attr WHERE pick_file=? AND type IN ('A','D') "
                            "ORDER BY attr", (table,)).fetchall()
    dict_text = "\n".join(f"{r['name']} <{r['attr']}> {r['conv'] or ''} {r['depth'] or ''}".strip() for r in rows)
    say(f"Read the DICT: {len(fields)} attributes")
    values = _known_values(store, table)
    say(f"Collected {len(values)} lists of known values from screens and the data profile")
    say("Asking Claude Code to write the criteria…")
    res = run_structured(cfg, PROMPT.format(table=table, desc=description, today=date.today().isoformat(),
                                            dict=dict_text[:20000], values="\n".join(values) or "(none)"),
                         SCHEMA, log=say, person=person)
    out = res["output"]
    crit = normalise(store, table, out)
    explanation = str(out.get("explanation", "")).replace('\\"', '"')
    return {"criteria": crit, "name": out.get("name") or description[:60], "explanation": explanation,
            "cost_usd": res["cost_usd"]}
