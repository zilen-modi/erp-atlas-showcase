import numpy as np
import pytest

from atlas import knowledge, semantic
from atlas.parse.program import parse_program
from atlas.store.db import Store

FREIGHT = ["      SUBROUTINE W4FREIGHT(ORD)", "* work out the freight charge from the ship-via",
           "      CALL *OPEN.FILE('ORDER',OF)", "      READ OR FROM OF, ORD ELSE RETURN",
           "      OR<12> = OR<11> * 0.05", "      WRITE OR ON OF, ORD", "      RETURN"]
STUB = ["      SUBROUTINE W4STUB", "      RETURN"]


def put(st, name, lines):
    h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


@pytest.fixture
def st(tmp_path):
    s = Store(tmp_path / "atlas.db")
    put(s, "W4FREIGHT", FREIGHT)
    put(s, "W4STUB", STUB)
    s.db.execute("INSERT INTO menu VALUES ('M1','RUN BP W4FREIGHT','W4FREIGHT',500,'2026-01-01')")
    s.commit()
    return s


def fake_claude(calls):
    def run(cfg, prompt, schema, **kw):
        calls.append(prompt)
        assert kw.get("tools") is False
        names = [ln.split()[-1] for ln in prompt.splitlines() if ln.startswith("=== PROGRAM")]
        entry = lambda n: {"name": n, "title": f"{n} does a thing", "summary": "It works out freight.",  # noqa: E731
                           "terms": ["freight", "ship via"], "highlights": [{"line": 5, "note": "the charge"},
                                                                            {"line": 999, "note": "made up"}]}
        out = {"programs": [entry(n) for n in names]} if names else entry("x")
        return {"output": out, "cost_usd": 0.02, "model": "claude-sonnet-5-5"}
    return run


def test_queue_puts_most_used_first_and_skips_current(st, monkeypatch):
    assert knowledge.queue(st, 10) == ["W4FREIGHT", "W4STUB"]
    calls = []
    monkeypatch.setattr(knowledge, "run_structured", fake_claude(calls))
    monkeypatch.setattr(semantic, "index", lambda st, log=None: {})
    r = knowledge.summarize(st, None, 10)
    assert r["programs"] == 2 and len(calls) == 1          # both small: one call
    assert "W4FREIGHT" in calls[0] and "ORDER" in calls[0]   # source and context go in the prompt
    assert knowledge.queue(st, 10) == []


def test_summary_goes_stale_when_code_changes(st, monkeypatch):
    monkeypatch.setattr(knowledge, "run_structured", fake_claude([]))
    monkeypatch.setattr(semantic, "index", lambda st, log=None: {})
    knowledge.summarize(st, None, 10)
    s = knowledge.get(st, "W4FREIGHT")["summary"]
    assert not s["stale"] and [h["line"] for h in s["highlights"]] == [5]   # out-of-range line dropped
    put(st, "W4FREIGHT", FREIGHT + ["* changed"])
    assert knowledge.get(st, "W4FREIGHT")["summary"]["stale"]
    assert knowledge.queue(st, 10) == ["W4FREIGHT"]
    assert knowledge.coverage(st)["stale"] == 1


def test_long_program_is_cut_at_labels(st, monkeypatch):
    monkeypatch.setattr(knowledge, "SECTION_CHARS", 400)
    body = ["      SUBROUTINE W4BIG"]
    for n in range(6):
        body += [f"{100 + n}:"] + [f"      X = {n} * {i} ;* step {i} of part {n}" for i in range(12)]
    lines = body + ["      RETURN"]
    put(st, "W4BIG", lines)
    secs = knowledge._sections(st, "W4BIG", lines)
    assert len(secs) > 1 and secs[0][0] == 1 and secs[-1][1] == len(lines)
    assert all(a[1] + 1 == b[0] for a, b in zip(secs, secs[1:], strict=False))   # no gaps, no overlap
    assert all(lines[s - 1].rstrip().endswith(":") for s, _, _ in secs[1:])      # each starts at a label


class FakeEmbedder:
    """Words to vectors by vocabulary, so 'freight' finds the freight program without the real model."""
    VOCAB = ["freight", "charge", "ship", "transfer", "stub", "thin"]

    def _v(self, text):
        t = text.lower()
        return np.array([t.count(w) for w in self.VOCAB] + [0.01], dtype=np.float32)

    def passage_embed(self, texts):
        return [self._v(t) for t in texts]

    def query_embed(self, texts):
        return [self._v(t) for t in texts]


def test_search_by_meaning(st, monkeypatch):
    monkeypatch.setattr(semantic, "_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(semantic, "available", lambda: True)
    monkeypatch.setattr(semantic, "_matrix", None)
    for name, title, summary in [("W4FREIGHT", "Works out the freight charge", "Freight from ship via."),
                                 ("W4STUB", "An empty stub", "Too thin to tell.")]:
        knowledge._save(st, "program", name, 0, 0, knowledge._hash(st, name),
                        {"title": title, "summary": summary, "terms": [], "highlights": []}, "m", 0, "t", 10)
    st.commit()
    assert semantic.index(st)["updated"] == 2
    assert semantic.index(st)["updated"] == 0              # unchanged text isn't re-embedded
    r = semantic.search(st, "where is the freight charge", 5)
    assert r["results"][0]["program"] == "W4FREIGHT"
    assert all(x["program"] != "W4STUB" for x in r["results"])   # unrelated: below the threshold


def test_search_says_when_index_is_empty(st, monkeypatch):
    monkeypatch.setattr(semantic, "available", lambda: True)
    r = semantic.search(st, "freight")
    assert r["ready"] is False and "Admin" in r["note"]
