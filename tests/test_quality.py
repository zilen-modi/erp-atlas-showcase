import json

import pytest

from atlas import ask_eval, citecheck
from atlas.parse.program import parse_program
from atlas.store.db import Store

SRC = ["      SUBROUTINE W4FRT(OINV)", "* freight codes", '      MISFRT="88123"', '      MISEXPD="S3237208"',
       "      FOR X=1 TO 3", "         TFR=TFR+OINV<39,X>", "      NEXT X", "      RETURN"]


@pytest.fixture
def st(tmp_path):
    s = Store(tmp_path / "atlas.db")
    s.put_program("git", parse_program("W4FRT", SRC), s.put_source("git", "BP", "W4FRT", "p", "\n".join(SRC)))
    s.commit()
    return s


def test_real_citations_and_quotes_pass(st):
    a = ('Freight codes are set at the top:\n```\nMISFRT="88123"        misc freight\nMISEXPD="S3237208"  ; SPN\n```\n'
         "(W4FRT:3-4) and summed in the loop (W4FRT:5-7). HTTP:1 and TRANSFER:10 aren't programs.")
    r = citecheck.check(st, a)
    assert r == {"cites": 2, "ok": 2, "problems": []}


def test_made_up_lines_and_misquotes_are_caught(st):
    r = citecheck.check(st, "It writes the record (W4FRT:120). Also see W4NOPE:5.")
    assert r["cites"] == 1 and [p["why"] for p in r["problems"]] == ["W4FRT has only 8 lines"]
    r = citecheck.check(st, '```\nCALL IORELEASE("WRITE",PN,"",PRDFILE,GUIAPP,PRD,"2422")\n```\n(W4FRT:5)')
    assert r["problems"] and r["problems"][0]["why"].startswith("quoted code doesn't match")


def test_diagrams_and_descriptions_are_not_treated_as_quotes(st):
    a = ("```\nW4FRT (freight)\n  └─ CALL W4OTHER   W4FRT:5\n```\n(W4FRT:5)\n"
         "```\nOINV<39,n> = quantity shipped\n```\n(W4FRT:6)")
    assert citecheck.check(st, a)["problems"] == []


def test_scoring_caps_a_contradicted_answer(st):
    case = {"id": "T-1", "q": "q", "must_cite": ["W4FRT", "W4OTHER"]}
    good = ask_eval.score(st, case, "See W4FRT:3.", {"score": 1.0, "missing": [], "contradicted": []})
    assert good["checks"] == {"cited": 0.5, "checked": 1.0, "expected": 1.0} and good["missing_cites"] == ["W4OTHER"]
    wrong = ask_eval.score(st, case, "See W4FRT:3.", {"score": 0.9, "missing": [], "contradicted": ["x"]})
    assert wrong["score"] == 0.3


def test_run_asks_each_case_and_keeps_receipts(st, tmp_path, monkeypatch):
    cases = tmp_path / "golden.json"
    cases.write_text(json.dumps({"version": 1, "cases": [
        {"id": "T-1", "status": "verified", "q": "Where is freight summed?", "expected": "In the loop",
         "must_cite": ["W4FRT"]},
        {"id": "T-2", "status": "draft", "q": "Unanswerable", "expected": "", "must_cite": []}]}))
    monkeypatch.setattr(ask_eval, "CASES", cases)

    def fake_ask(store, cfg, q, chat_id=None, person=None):
        yield {"type": "chat", "chat_id": "c1"}
        if q.startswith("Where"):
            yield {"type": "text", "text": "In the loop at W4FRT:5-7."}
            yield {"type": "done", "cost_usd": 0.5}
        else:
            yield {"type": "error", "message": "boom"}
    monkeypatch.setattr(ask_eval.chat, "ask", fake_ask)
    monkeypatch.setattr(ask_eval.chat, "delete_chat", lambda store, cid: None)
    monkeypatch.setattr(ask_eval, "judge",
                        lambda *a: {"score": 1.0, "missing": [], "contradicted": [], "cost_usd": 0.1})
    from types import SimpleNamespace
    r = ask_eval.run(st, SimpleNamespace(chat=SimpleNamespace(model="m")), None)
    assert r["verified"] == {"n": 1, "score": 1.0} and r["draft"] == {"n": 1, "score": 0.0}
    assert r["cost_usd"] == 0.6
    h = ask_eval.history(st)
    assert h[0]["run"] == r["run"] and {x["id"] for x in h[0]["results"]} == {"T-1", "T-2"}


def test_cases_are_added_as_drafts_and_verified_by_a_person(tmp_path, monkeypatch):
    cases = tmp_path / "golden.json"
    cases.write_text(json.dumps({"version": 1, "cases": []}))
    monkeypatch.setattr(ask_eval, "CASES", cases)
    c = ask_eval.add_case("Is MIS an SPN?", "", ["lg.spn.create"], "answer a1", "Max")
    assert c["id"] == "AA-01" and c["status"] == "draft" and c["must_cite"] == ["LG.SPN.CREATE"]
    with pytest.raises(ValueError, match="expected answer"):
        ask_eval.verify("AA-01", "Ada")
    v = ask_eval.verify("AA-01", "Ada <ada@x>", "Yes: ALT-PN MIS points to S1000001.")
    assert v["status"] == "verified" and v["reviewed_by"] == "Ada <ada@x>"
