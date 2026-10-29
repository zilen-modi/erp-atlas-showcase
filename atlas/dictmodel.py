"""Dictionary export for the new system: one JSON document per Pick file, e.g.

    {"table_name": "SERIAL-LOG", "description": "...",
     "fields": [{"pos": 1, "uv": "VEND/CUST", "model": "vendorCustomerId", "sm": "M", "format": "string"}, ...]}

`uv`, `sm` (S single / M multivalued) and `format` come from the DICT printout in git.
`model` (the camelCase field name in the new model) is suggested: instantly from the
dictionary name and heading (rules below), or by Claude Code, which also reads how the
code uses each attribute. Names the user edits are kept and win over suggestions.
"""

from __future__ import annotations

import json
import re
from typing import Any

from atlas.chat import Person, run_structured
from atlas.config import Config
from atlas.store.db import Store, now

Result = dict[str, Any]
FORMATS = ("string", "date", "time", "number", "decimal")

ABBR = {
    "ACCT": "account", "ADDR": "address", "ADJ": "adjustment", "ALT": "alternate", "AMT": "amount",
    "AVG": "average", "BAL": "balance", "BO": "backorder", "BR": "branch", "CD": "code", "CDE": "code",
    "CHG": "change", "CNT": "count", "CO": "company", "COMM": "commission", "CR": "credit", "CT": "count",
    "CUR": "current", "CUST": "customer", "DEPT": "department", "DESC": "description", "DIST": "distribution",
    "DOC": "document", "DR": "debit", "DT": "date", "EMP": "employee", "EXT": "extended", "FRT": "freight",
    "GRP": "group", "HIST": "history", "ID": "id", "INV": "invoice", "LN": "line", "LOC": "location",
    "MAX": "maximum", "MFG": "manufacturer", "MIN": "minimum", "MSG": "message", "NO": "number",
    "NUM": "number", "ORD": "order", "ORIG": "original", "PCT": "percent", "PH": "phone", "PREV": "previous",
    "PROD": "product", "PN": "partNumber", "QTY": "quantity", "RCV": "received", "REC": "record", "REF": "reference",
    "REQ": "request", "SEQ": "sequence", "SHP": "shipped", "SLS": "sales", "SLSM": "salesman", "STAT": "status",
    "STS": "status", "TEL": "telephone", "TERR": "territory", "TOT": "total", "TRAN": "transaction",
    "TRANS": "transaction", "TYP": "type", "UM": "unitOfMeasure", "UOM": "unitOfMeasure", "UPD": "updated",
    "USR": "user", "VEND": "vendor", "WGHT": "weight", "WHSE": "warehouse", "WT": "weight", "XF": "transfer",
    "XFR": "transfer", "YR": "year",
}
# a field holding one of these is a reference to it: PRODUCT -> productId
ENTITIES = {"product", "customer", "vendor", "writer", "salesman", "employee", "user"}
# too generic on their own: the column heading usually says more (DATE + "TRANS DATE" -> transactionDate)
GENERIC = {"date", "time", "name", "description", "code", "type", "status", "amount", "number", "quantity"}


def _words(text: str) -> list[str]:
    text = text.replace("#", " NO ").replace("&", " AND ")
    out: list[str] = []
    for w in re.split(r"[^A-Za-z0-9]+", text):
        if not w:
            continue
        out.extend(re.findall(r"[A-Z]+[a-z0-9]*|[a-z0-9]+", ABBR.get(w.upper(), w.lower())))
    return [w.lower() for w in out]


def _camel(words: list[str]) -> str:
    s = words[0] + "".join(w[:1].upper() + w[1:] for w in words[1:]) if words else ""
    return re.sub(r"^(\d)", r"f\1", s)


def suggest_name(uv: str, heading: str = "", table: str = "") -> str:
    """Rule-based model name for one dictionary field."""
    if uv.upper() == "@ID":
        return _camel(_words(table) + ["id"])
    words = _words(uv)
    head = _words(heading)
    if words and set(words) <= GENERIC and head and len(head) > len(words) and words[-1] in head:
        words = head
    if words and words[-1] in ENTITIES:
        words = words + ["id"]
    return _camel(words) or "field"


def format_of(conv: str) -> str:
    c = (conv or "").upper()
    if c.startswith("D"):
        return "date"
    if c.startswith("MT"):
        return "time"
    m = re.match(r"M[DR](\d)", c)
    if m:
        return "decimal" if m.group(1) != "0" else "number"
    return "string"


def describe(table: str) -> str:
    words = _words(table)
    return " ".join(words).capitalize() if words else table


def _fields(store: Store, table: str) -> list[Result]:
    """One row per stored position, from the first A/D dictionary item naming it."""
    by_pos: dict[int, Result] = {}
    for r in store.db.execute("SELECT rowid, * FROM dict_attr WHERE pick_file=? AND type IN ('A','D') "
                              "ORDER BY attr, rowid", (table,)):
        pos = int(r["attr"])
        if pos in by_pos:
            if pos == 0 and r["name"].upper() == "@ID":       # the key: always listed as @ID
                by_pos[0]["aliases"].append(by_pos[0]["uv"])
                by_pos[0].update(uv="@ID", heading=r["heading"] or "")
            else:
                by_pos[pos]["aliases"].append(r["name"])
            continue
        by_pos[pos] = {"pos": pos, "uv": r["name"], "heading": r["heading"] or "", "conv": r["conv"] or "",
                       "sm": "S" if pos == 0 else (r["depth"] or "S"), "aliases": []}
    return [by_pos[k] for k in sorted(by_pos)]


def _unique(fields: list[Result]) -> None:
    seen: dict[str, int] = {}
    for f in fields:
        n = seen.get(f["model"], 0)
        seen[f["model"]] = n + 1
        if n:
            f["model"] = f"{f['model']}{f['pos']}"


def get(store: Store, table: str) -> Result:
    table = table.upper()
    fields = _fields(store, table)
    if not fields:
        raise ValueError(f"no dictionary for {table} in git")
    saved = {r["pos"]: r for r in store.db.execute("SELECT * FROM dict_model WHERE pick_file=?", (table,))}
    meta = store.db.execute("SELECT * FROM dict_model_file WHERE pick_file=?", (table,)).fetchone()
    for f in fields:
        s = saved.get(f["pos"])
        f["model"] = s["model"] if s else suggest_name("@ID" if f["pos"] == 0 else f["uv"], f["heading"], table)
        f["format"] = s["format"] if s and s["format"] else format_of(f["conv"])
        f["sm"] = s["sm"] if s and s["sm"] else f["sm"]
        f["source"] = s["source"] if s else "rules"
    _unique(fields)
    from atlas.profile import model_hints  # late import: profile imports this module
    hints = model_hints(store, table)
    for f in fields:
        if f["pos"] in hints:
            f["data"] = hints[f["pos"]]
    return {"table_name": table, "description": meta["description"] if meta else describe(table),
            "description_source": meta["source"] if meta else "rules", "fields": fields}


def export(store: Store, table: str) -> Result:
    """The JSON document exactly as handed to the new system."""
    d = get(store, table)
    return {"table_name": d["table_name"], "description": d["description"],
            "fields": [{"pos": f["pos"], "uv": f["uv"], "model": f["model"], "sm": f["sm"], "format": f["format"]}
                       for f in d["fields"]]}


def save(store: Store, table: str, body: Result, source: str = "user") -> Result:
    table = table.upper()
    known = {f["pos"] for f in _fields(store, table)}
    ts = now()
    if "description" in body:
        store.db.execute("INSERT OR REPLACE INTO dict_model_file VALUES (?,?,?,?)",
                         (table, str(body["description"]).strip(), source, ts))
    for f in body.get("fields") or []:
        pos = int(f["pos"])
        if pos not in known:
            continue
        model = re.sub(r"[^A-Za-z0-9_]", "", str(f.get("model") or ""))
        fmt = f.get("format") if f.get("format") in FORMATS else None
        sm = f.get("sm") if f.get("sm") in ("S", "M") else None
        if not model:
            store.db.execute("DELETE FROM dict_model WHERE pick_file=? AND pos=?", (table, pos))
            continue
        store.db.execute("INSERT OR REPLACE INTO dict_model VALUES (?,?,?,?,?,?,?)",
                         (table, pos, model, fmt, sm, f.get("source") or source, ts))
    store.commit()
    return get(store, table)


def reset(store: Store, table: str) -> Result:
    table = table.upper()
    store.db.execute("DELETE FROM dict_model WHERE pick_file=?", (table,))
    store.db.execute("DELETE FROM dict_model_file WHERE pick_file=?", (table,))
    store.commit()
    return get(store, table)


# ------------------------------------------------------------------ AI names

SCHEMA = {
    "type": "object", "required": ["description", "fields"],
    "properties": {
        "description": {"type": "string"},
        "fields": {"type": "array", "items": {
            "type": "object", "required": ["pos", "model", "format"],
            "properties": {"pos": {"type": "integer"}, "model": {"type": "string"},
                           "format": {"type": "string", "enum": list(FORMATS)}}}},
    },
}

PROMPT = """You are naming fields for the new system's data model of the legacy Pick file {table}.
For every attribute below, give `model`: a clear camelCase English name a developer would expect
(e.g. VEND/CUST -> vendorCustomerId, DOC# -> documentNumber, DATE with heading TRANS DATE ->
transactionDate). Rules:
- Expand abbreviations. A field holding another record's key (product, customer, vendor, writer,
  salesman, branch...) ends in "Id". Position 0 (@ID) is the record key: name it after the file + "Id".
- The dictionary name is authoritative when it is a clear word (PRODUCT -> productId, WRITER -> writerId).
  Use the code lines only to decode vague or abbreviated names (TO3, SUFF, DATERECD). Code lines come
  from several programs; if one program stores something odd, don't rename the field after it.
- Names must be unique within the file. Do not invent meaning you can't see; keep it plain.
- `format`: one of string, date, time, number, decimal. The dictionary conversion (D... date, MT...
  time, MD/MR n>0 decimal, n=0 number) wins; otherwise infer from the code, default string.
Also give `description`: a short phrase of at most 8 words saying what the file holds
(e.g. "Serial number transaction log").
You may use the Atlas tools (field_info, who_writes, read_lines) if the lines below are not enough,
but keep it quick.

File: {table}
Attributes (JSON): {fields}
"""


def _code_samples(store: Store, table: str, per_attr: int = 3) -> dict[int, list[str]]:
    """Up to `per_attr` code lines per attribute, each from a different program, most-used
    programs first -- so one odd program can't dominate what a field seems to hold."""
    from atlas.query import usage_map
    usage = usage_map(store)
    cache: dict[str, list[str]] = {}
    seen: dict[int, set[str]] = {}
    out: dict[int, list[str]] = {}
    rows = store.db.execute("SELECT program, line, attr, access FROM attr_ref WHERE provenance='git' AND "
                            "pick_file=?", (table,)).fetchall()
    rows.sort(key=lambda r: (r["access"] != "write", -(usage.get(r["program"]) or 0), r["program"], r["line"]))
    for r in rows:
        lst, progs = out.setdefault(r["attr"], []), seen.setdefault(r["attr"], set())
        prog = r["program"]
        if len(lst) >= per_attr or prog in progs:
            continue
        if prog not in cache:
            src = store.db.execute("SELECT b.text FROM source_file s JOIN blob b ON b.hash=s.hash WHERE "
                                   "s.provenance='git' AND s.kind='BP' AND s.name=?", (prog,)).fetchone()
            cache[prog] = src["text"].splitlines() if src else []
        lines = cache[prog]
        if 0 < r["line"] <= len(lines):
            progs.add(prog)
            lst.append(f"{prog}:{r['line']} {lines[r['line'] - 1].strip()[:160]}")
    return out


def suggest_ai(store: Store, cfg: Config, table: str, log: Any = None, person: Person | None = None) -> Result:
    """Claude Code names every field (user-edited names are kept) and describes the file."""
    say = log or (lambda _m: None)
    d = get(store, table)
    say(f"Read the DICT: {len(d['fields'])} fields")
    samples = _code_samples(store, d["table_name"])
    n_lines = sum(len(v) for v in samples.values())
    progs = {x.split(":", 1)[0] for v in samples.values() for x in v}
    say(f"Collected {n_lines} code lines from {len(progs)} programs showing how the fields are used")
    compact = [{"pos": f["pos"], "uv": f["uv"], "aliases": f["aliases"][:3], "heading": f["heading"],
                "conv": f["conv"], "sm": f["sm"], "code": samples.get(f["pos"], [])} for f in d["fields"]]
    say("Asking Claude Code to name the fields…")
    res = run_structured(cfg, PROMPT.format(table=d["table_name"], fields=json.dumps(compact)[:50000]), SCHEMA,
                         log=say, person=person)
    out = res["output"]
    user = {f["pos"] for f in d["fields"] if f["source"] == "user"}
    fields = [{"pos": f["pos"], "model": f["model"], "format": f.get("format"), "source": "ai"}
              for f in out.get("fields", []) if isinstance(f.get("pos"), int) and f["pos"] not in user]
    body: Result = {"fields": fields}
    if d["description_source"] != "user" and out.get("description"):
        body["description"] = out["description"]
    kept = len(user)
    say(f"Saving {len(fields)} names" + (f" (kept {kept} you edited)" if kept else ""))
    got = save(store, d["table_name"], body, source="ai")
    got["cost_usd"] = res["cost_usd"]
    return got
