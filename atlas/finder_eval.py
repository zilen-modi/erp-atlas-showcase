"""How accurate is Test data's 'Describe the record you need'? Each case in eval/finder-set.json is a tester's
description and what the criteria must contain. A run asks Claude for criteria (the same call the page makes),
runs them on TEST, and scores:

  valid    TEST accepted the selection                  (skipped when TEST can't be reached)
  found    it found at least one record                 (skipped likewise)
  fields   share of the expected conditions present, on the right attribute (DICT synonyms count) and value
  related  share of the expected related-record checks present
  keys     share of the case's known-good records the criteria find (when the case lists any)

A case's score is the mean of the checks that apply. Only verified cases count toward the headline score;
drafts are reported beside it. Every run is kept as receipts (kind 'finder-eval'), tied to the git sha.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from atlas import finder
from atlas.config import ROOT, Config
from atlas.sources.live import LiveClient
from atlas.store.db import Store, now

Result = dict[str, Any]
CASES = ROOT / "eval" / "finder-set.json"
_COND = re.compile(r'WITH\s+(\S+)\s+(=|#|EQ|NE|GE|LE|GT|LT|LIKE)\s+"([^"]*)"', re.I)


def load() -> list[Result]:
    return list(json.loads(CASES.read_text())["cases"])


def conditions(store: Store, table: str, query: str) -> list[Result]:
    """The selection's conditions as (attribute, op, value): DICT names resolved to attribute numbers."""
    attrs = {r["name"].upper(): r["attr"] for r in store.db.execute(
        "SELECT name, attr FROM dict_attr WHERE pick_file=?", (table,))}
    out = []
    for name, op, value in _COND.findall(query or ""):
        op = {"EQ": "=", "NE": "#"}.get(op.upper(), op.upper())
        kind = ("filled" if op == "#" and value == "" else "empty" if op == "=" and value == ""
                else "range" if op in ("GE", "LE", "GT", "LT") else "like" if op == "LIKE" else op)
        out.append({"name": name.upper(), "attr": attrs.get(name.upper()), "op": kind, "value": value})
    return out


def _meets(want: Result, got: list[Result]) -> bool:
    on = [g for g in got if g["attr"] == want["attr"]]
    vals = {str(v).upper() for v in want.get("values") or []}
    op = want.get("op", "any")
    if op == "any":
        return bool(on)
    if op == "filled":       # "has a value": # "", or a range that implies one (QOH GT "0")
        return any(g["op"] in ("filled", "range") or (g["op"] == "#" and g["value"] == "") for g in on)
    if op == "range":
        return any(g["op"] == "range" for g in on)
    return any(g["op"] == op and (not vals or g["value"].upper() in vals) for g in on)


def score(store: Store, case: Result, criteria: Result, ran: Result | None, error: str | None,
          key_hits: list[bool] | None = None) -> Result:
    table = case["file"].upper()
    got = conditions(store, table, criteria.get("query", ""))
    exp = case.get("expect", {})
    checks: dict[str, float | None] = {"valid": None, "found": None, "fields": None, "related": None, "keys": None}
    if error is not None:
        checks["valid"], checks["found"] = 0.0, 0.0
    elif ran is not None:
        checks["valid"], checks["found"] = 1.0, 1.0 if ran["total_matches"] > 0 else 0.0
    want = exp.get("conditions") or []
    met = [_meets(w, got) for w in want]
    if want:
        checks["fields"] = sum(met) / len(want)
    rel_want = exp.get("related") or []
    rel_got = {(r["file"].upper(), r["key"], bool(r["exists"])) for r in criteria.get("related") or []}
    rel_met = [(r["file"].upper(), r["key"], bool(r["exists"])) in rel_got for r in rel_want]
    if rel_want:
        checks["related"] = sum(rel_met) / len(rel_want)
    if key_hits:
        checks["keys"] = sum(key_hits) / len(key_hits)
    applied = [v for v in checks.values() if v is not None]
    return {"id": case["id"], "status": case.get("status", "draft"), "file": table, "description": case["description"],
            "score": round(sum(applied) / len(applied), 3) if applied else 0.0, "checks": checks,
            "query": criteria.get("query", ""), "related": criteria.get("related") or [], "used": got,
            "missing": [w for w, ok in zip(want, met, strict=True) if not ok]
            + [r for r, ok in zip(rel_want, rel_met, strict=True) if not ok],
            "matches": ran["total_matches"] if ran else None, "error": error}


def _key_hits(store: Store, client: LiveClient, table: str, criteria: Result, keys: list[str]) -> list[bool] | None:
    """Do the criteria find each known-good record? Asked per key (selection AND @ID); not for OR selections."""
    q = criteria.get("query", "")
    if not keys or re.search(r"\bOR\b", q, re.I):
        return None
    hits = []
    for k in keys:
        one = {**criteria, "query": (f"{q} AND " if q else "") + f'WITH @ID = "{k}"'}
        try:
            hits.append(any(m["key"] == k for m in finder.run(store, client, table, one, 5)["matches"]))
        except finder.FinderError:
            hits.append(False)
    return hits


def run(store: Store, cfg: Config, client: LiveClient | None, ids: list[str] | None = None,
        log: Callable[[str], None] | None = None) -> Result:
    say = log or (lambda _m: None)
    cases = [c for c in load() if not ids or c["id"] in ids]
    sha = (store.db.execute("SELECT last_sha FROM index_state WHERE source='git:erp'").fetchone() or [None])[0]
    run_id, results, cost = uuid.uuid4().hex[:10], [], 0.0
    for n, case in enumerate(cases, 1):
        say(f"[{n}/{len(cases)}] {case['id']} {case['file']}: “{case['description']}”")
        try:
            s = finder.suggest(store, cfg, case["file"], case["description"], say)
        except Exception as e:                      # a failed suggestion is a failed case, not a failed run
            results.append({**score(store, case, {}, None, f"no criteria: {e}"), "explanation": ""})
            continue
        cost += float(s.get("cost_usd") or 0)
        crit, ran, error, hits = s["criteria"], None, None, None
        if client is not None:
            try:
                ran = finder.run(store, client, case["file"], crit, 25)
                hits = _key_hits(store, client, case["file"], crit, case.get("keys") or [])
            except finder.FinderUnreachable as e:  # the VPN dropped: not the criteria's fault, so don't score it
                say(f"  {str(e)[:100]}: scoring the criteria only from here on")
                client = None
            except finder.FinderError as e:
                error = str(e)[:300]
        r = {**score(store, case, crit, ran, error, hits), "explanation": s.get("explanation", "")}
        say(f"  score {r['score']:.2f}  {r['query'] or '(no selection)'}")
        results.append(r)
        detail = json.dumps({"run": run_id, **r})
        store.db.execute("INSERT INTO receipt VALUES (?,?,?,?,?,?,?)",
                         (uuid.uuid4().hex[:12], "finder-eval", case["id"], r["score"], detail, sha, now()))
    verified = [r["score"] for r in results if r["status"] == "verified"]
    drafts = [r["score"] for r in results if r["status"] != "verified"]
    summary = {"run": run_id, "at": now(), "sha": sha, "cases": len(results), "cost_usd": round(cost, 4),
               "verified": {"n": len(verified), "score": round(sum(verified) / len(verified), 3) if verified else None},
               "draft": {"n": len(drafts), "score": round(sum(drafts) / len(drafts), 3) if drafts else None},
               "live": client is not None}
    store.db.execute("INSERT INTO receipt VALUES (?,?,?,?,?,?,?)",
                     (uuid.uuid4().hex[:12], "finder-eval-run", run_id,
                      summary["verified"]["score"] if verified else summary["draft"]["score"],
                      json.dumps(summary), sha, summary["at"]))
    store.commit()
    say(f"Done: {len(results)} cases, verified {summary['verified']}, draft {summary['draft']}, ${cost:.2f}")
    return {**summary, "results": results}

