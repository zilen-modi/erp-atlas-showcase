"""How good are Ask Atlas's answers? The golden set (eval/golden-set.json) is questions with SME-checked answers.
A run asks each one (a fresh chat, the same tools and prompt people get) and scores:

  cited     share of the case's must_cite programs the answer cites as PROGRAM:line
  checked   share of the answer's citations that check out against git (atlas.citecheck)
  expected  how fully and correctly the answer states the expected answer, judged by Claude with no tools
            (only for cases that have one); anything it contradicts caps the case at 0.3

A case's score is the mean of the checks that apply. Only verified cases count toward the headline score; drafts
are reported beside it. A draft becomes verified when a named person confirms its expected answer. Every run is
kept as receipts (kind 'ask-eval'), tied to the git sha, so a change to the prompt, tools or model that makes
answers worse shows up as a lower score.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from atlas import chat, citecheck
from atlas.config import ROOT, Config
from atlas.store.db import Store, now

Result = dict[str, Any]
CASES = ROOT / "eval" / "golden-set.json"

_JUDGE = {
    "type": "object",
    "properties": {
        "score": {"type": "number",
                  "description": "0 to 1: how fully and correctly the answer states the expected answer"},
        "missing": {"type": "array", "items": {"type": "string"}, "description": "expected points it leaves out"},
        "contradicted": {"type": "array", "items": {"type": "string"},
                         "description": "expected points it gets wrong or contradicts"},
    },
    "required": ["score", "missing", "contradicted"],
}


def load() -> Result:
    return dict(json.loads(CASES.read_text()))


def save(data: Result) -> None:
    CASES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def cases() -> list[Result]:
    return list(load()["cases"])


def add_case(question: str, expected: str, must_cite: list[str], source: str, by: str) -> Result:
    """A new draft case (e.g. from a corrected thumbs-down); it counts once someone verifies it."""
    data = load()
    n = 1 + max((int(c["id"].split("-")[-1]) for c in data["cases"] if c["id"].startswith("AA-")), default=0)
    case = {"id": f"AA-{n:02d}", "status": "draft", "q": question.strip(), "expected": expected.strip(),
            "must_cite": [m.upper() for m in must_cite], "source": source, "added_by": by}
    data["cases"].append(case)
    save(data)
    return case


def verify(case_id: str, by: str, expected: str | None = None) -> Result:
    """A named person confirms a case's expected answer: it now counts toward the headline score."""
    data = load()
    for c in data["cases"]:
        if c["id"] == case_id:
            if expected is not None:
                c["expected"] = expected.strip()
            if not c.get("expected"):
                raise ValueError("Write the expected answer before verifying the case")
            c["status"], c["reviewed_by"] = "verified", by
            save(data)
            return dict(c)
    raise ValueError(f"No case {case_id}")


def judge(cfg: Config, question: str, expected: str, answer: str, person: chat.Person | None) -> Result:
    prompt = (f"A reviewer checked this answer about a legacy ERP against an expected answer written by an expert.\n"
              f"Question: {question}\n\nExpected answer (correct):\n{expected}\n\nAnswer to grade:\n{answer}\n\n"
              "Score how fully and correctly the answer states the expected answer's points (extra correct detail "
              "is fine). List expected points it leaves out, and any it gets wrong or contradicts.")
    r = chat.run_structured(cfg, prompt, _JUDGE, effort="low", timeout_s=300, person=person, tools=False)
    out = r["output"] or {}
    return {"score": max(0.0, min(1.0, float(out.get("score") or 0))), "missing": out.get("missing") or [],
            "contradicted": out.get("contradicted") or [], "cost_usd": float(r.get("cost_usd") or 0)}


def score(store: Store, case: Result, answer: str, verdict: Result | None) -> Result:
    checks: dict[str, float | None] = {"cited": None, "checked": None, "expected": None}
    cited = {c["program"] for c in citecheck.cites(answer)}
    must = [m.upper() for m in case.get("must_cite") or []]
    if must:
        checks["cited"] = sum(m in cited for m in must) / len(must)
    cc = citecheck.check(store, answer)
    if cc["cites"]:
        checks["checked"] = 1 - len(cc["problems"]) / max(cc["cites"], len(cc["problems"]))
    if verdict is not None:
        checks["expected"] = verdict["score"]
    applied = [v for v in checks.values() if v is not None]
    s = sum(applied) / len(applied) if applied else 0.0
    if verdict and verdict["contradicted"]:
        s = min(s, 0.3)                       # a wrong answer that cites well is still wrong
    return {"score": round(s, 3), "checks": checks, "citations": cc,
            "missing_cites": [m for m in must if m not in cited]}


def _answer(store: Store, cfg: Config, question: str, person: chat.Person | None) -> Result:
    """Ask in a fresh chat, exactly as a person would; the chat is removed afterwards (the run keeps the answer)."""
    text, err, cost, chat_id = "", None, 0.0, None
    for ev in chat.ask(store, cfg, question, None, person):
        if ev["type"] == "chat":
            chat_id = ev["chat_id"]
        elif ev["type"] == "text":
            text += ev["text"]
        elif ev["type"] == "done":
            cost = float(ev.get("cost_usd") or 0)
        elif ev["type"] == "error":
            err = ev["message"]
    if chat_id:
        chat.delete_chat(store, chat_id)
    return {"answer": text.strip(), "error": err, "cost_usd": cost}


def run(store: Store, cfg: Config, person: chat.Person | None = None, ids: list[str] | None = None,
        log: Callable[[str], None] | None = None) -> Result:
    say = log or (lambda _m: None)
    todo = [c for c in cases() if not ids or c["id"] in ids]
    sha = (store.db.execute("SELECT last_sha FROM index_state WHERE source='git:erp'").fetchone() or [None])[0]
    run_id, results, cost = uuid.uuid4().hex[:10], [], 0.0
    for n, case in enumerate(todo, 1):
        say(f"[{n}/{len(todo)}] {case['id']}: {case['q']}")
        a = _answer(store, cfg, case["q"], person)
        cost += a["cost_usd"]
        if a["error"] and not a["answer"]:
            r = {"id": case["id"], "status": case.get("status", "draft"), "q": case["q"], "score": 0.0,
                 "checks": {}, "error": a["error"], "answer": ""}
        else:
            verdict = None
            if case.get("expected"):
                try:
                    verdict = judge(cfg, case["q"], case["expected"], a["answer"], person)
                    cost += verdict["cost_usd"]
                except RuntimeError as e:
                    say(f"  couldn't grade against the expected answer: {str(e)[:120]}")
            s = score(store, case, a["answer"], verdict)
            r = {"id": case["id"], "status": case.get("status", "draft"), "q": case["q"], **s,
                 "verdict": verdict, "answer": a["answer"], "error": a["error"]}
        say(f"  score {r['score']:.2f}" + (f" · {len(r.get('citations', {}).get('problems', []))} citation problems"
                                          if r.get("citations") else ""))
        results.append(r)
        store.db.execute("INSERT INTO receipt VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex[:12], "ask-eval",
                         case["id"], r["score"], json.dumps({"run": run_id, **r}, default=str), sha, now()))
        store.commit()
    ver = [r["score"] for r in results if r["status"] == "verified"]
    dra = [r["score"] for r in results if r["status"] != "verified"]
    summary = {"run": run_id, "at": now(), "sha": sha, "cases": len(results), "cost_usd": round(cost, 4),
               "model": (person.model if person else "") or cfg.chat.model,
               "verified": {"n": len(ver), "score": round(sum(ver) / len(ver), 3) if ver else None},
               "draft": {"n": len(dra), "score": round(sum(dra) / len(dra), 3) if dra else None}}
    store.db.execute("INSERT INTO receipt VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex[:12], "ask-eval-run", run_id,
                     summary["verified"]["score"] if ver else summary["draft"]["score"], json.dumps(summary), sha,
                     summary["at"]))
    store.commit()
    say(f"Done: {len(results)} cases · verified {summary['verified']} · draft {summary['draft']} · ${cost:.2f}")
    return {**summary, "results": results}


def history(store: Store, limit: int = 10) -> list[Result]:
    """Recent runs, newest first, each with its per-case results."""
    runs = [json.loads(r["detail"]) for r in store.db.execute(
        "SELECT detail FROM receipt WHERE kind='ask-eval-run' ORDER BY created_at DESC LIMIT ?", (limit,))]
    for run_ in runs[:1]:
        run_["results"] = [json.loads(r["detail"]) for r in store.db.execute(
            "SELECT detail FROM receipt WHERE kind='ask-eval' AND detail LIKE ? ORDER BY subject",
            (f'{{"run": "{run_["run"]}"%',))]
    return runs
