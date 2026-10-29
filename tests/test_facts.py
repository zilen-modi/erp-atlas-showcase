import pytest

from atlas.memory import facts
from atlas.memory.facts import Cite, FactError
from atlas.parse.program import parse_program
from atlas.store.db import Store

PROG = ["      SUBROUTINE W4DEMO(A)", "      X = 1", "      IF XF<3> = 142 THEN GOSUB 10", "      RETURN"]


def store_with(lines, prov="git"):
    st = Store(":memory:")
    put(st, lines, prov)
    return st


def put(st, lines, prov="git"):
    text = "\n".join(lines)
    h = st.put_source(prov, "BP", "W4DEMO", "src/BP/W4DEMO", text)
    st.put_program(prov, parse_program("W4DEMO", lines), h)
    st.commit()


def propose(st, **kw):
    args = dict(text="ANTF branch 142 check uses XF<3> (to-branch)", kind="rule",
                cites=[Cite("git", "W4DEMO", 3)], proposed_by="zilen", rationale="")
    args.update(kw)
    return facts.propose(st, **args)


def test_propose_requires_citation_and_valid_line():
    st = store_with(PROG)
    with pytest.raises(FactError):
        propose(st, cites=[])
    with pytest.raises(FactError):
        propose(st, cites=[Cite("git", "W4DEMO", 99)])
    with pytest.raises(FactError):
        propose(st, cites=[Cite("git", "W4DEMO")])


def test_frequency_rationale_rejected():
    st = store_with(PROG)
    with pytest.raises(FactError):
        propose(st, rationale="seen twice")
    assert propose(st, rationale="XF<3> holds the destination branch per DICT TRANSFER")


def test_only_named_human_can_accept():
    st = store_with(PROG)
    fid = propose(st)
    for bot in ("", "agent", "Claude", "atlas"):
        with pytest.raises(FactError):
            facts.accept(st, fid, bot)
    facts.accept(st, fid, "Ben")
    f = facts.get(st, fid)
    assert f["status"] == "accepted" and f["accepted_by"] == "Ben"


def test_changed_line_goes_stale_moved_line_repoints():
    st = store_with(PROG)
    fid = propose(st)
    facts.accept(st, fid, "Ben")
    moved = PROG[:1] + ["      * inserted comment"] + PROG[1:]
    put(st, moved)
    assert facts.check_stale(st) == []
    assert facts.get(st, fid)["cites"][0]["line"] == 4          # re-pointed, still accepted
    changed = [ln.replace("XF<3>", "XF<1>") for ln in moved]
    put(st, changed)
    staled = facts.check_stale(st, {"W4DEMO"})
    assert [s[0] for s in staled] == [fid]
    assert facts.get(st, fid)["status"] == "stale"
    with pytest.raises(FactError):
        facts.accept(st, fid, "Ben")                            # must re-cite first
    facts.recite(st, fid, "Ben")
    facts.accept(st, fid, "Ben")
    assert facts.get(st, fid)["status"] == "accepted"


def test_supersede_and_retire_and_history():
    st = store_with(PROG)
    old = propose(st)
    facts.accept(st, old, "Ben")
    new = propose(st, text="refined", supersedes=old)
    facts.accept(st, new, "Ben")
    assert facts.get(st, old)["status"] == "retired"
    facts.retire(st, new, "Ben", "rule removed in 1218ab83a")
    actions = [r["action"] for r in st.db.execute("SELECT action FROM fact_event WHERE fact_id=?", (new,))]
    assert actions == ["propose", "accept", "retire"]


def test_search_orders_accepted_first():
    st = store_with(PROG)
    a = propose(st, text="ANTF alpha")
    b = propose(st, text="ANTF beta", scope="TRANSFER<3>")
    facts.accept(st, b, "Ben")
    assert [f["id"] for f in facts.search(st, "ANTF")] == [b, a]
    assert [f["id"] for f in facts.search(st, scope="TRANSFER<3>")] == [b]
