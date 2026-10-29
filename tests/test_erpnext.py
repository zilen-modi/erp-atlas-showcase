from atlas import erpnext
from atlas.parse.program import parse_program
from atlas.store.db import Store


def put(st, name, lines, path):
    h = st.put_source("git", "BP", name, path, "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


def test_what_the_new_system_still_needs(tmp_path):
    st = Store(tmp_path / "atlas.db")
    put(st, "NX_COST", ["      SUBROUTINE NX_COST(P)", "      CALL LG.GETCOST(P)", "      CALL IOREADU(A,B)",
                           "      CALL NX_ENCRYPT(P)", "      RETURN"], "src/next/api-helpers/NX_COST")
    put(st, "NX_ENCRYPT", ["      SUBROUTINE NX_ENCRYPT(P)", "      RETURN"], "src/next/utilities/NX_ENCRYPT")
    put(st, "LG.GETCOST", [
        "      SUBROUTINE LG.GETCOST(P)", "      CALL LG.NET.CALC(P)", "      RETURN"], "src/BP/LG.GETCOST")
    put(st, "LG.NET.CALC", ["      SUBROUTINE LG.NET.CALC(P)", "      RETURN"], "src/BP/LG.NET.CALC")
    put(st, "W4OTHER", ["      SUBROUTINE W4OTHER", "      RETURN"], "src/BP/W4OTHER")
    st.commit()
    r = erpnext.overview(st)
    assert [h["program"] for h in r["helpers"]] == ["NX_COST", "NX_ENCRYPT"]
    cost = r["helpers"][0]
    assert cost["folder"] == "ERP Next API helper" and cost["calls"] == ["LG.GETCOST"]   # IOREADU is plumbing
    assert cost["uses_helpers"] == ["NX_ENCRYPT"]
    deps = {d["program"]: d for d in r["depends_on"]}
    assert deps["LG.GETCOST"]["depth"] == 1 and deps["LG.NET.CALC"]["depth"] == 2           # reached through LG.GETCOST
    assert deps["LG.NET.CALC"]["via"] == ["NX_COST"] and "W4OTHER" not in deps
    assert "IOREADU" not in deps and "NX_ENCRYPT" not in deps                     # neither plumbing nor helpers
    assert r["totals"] == {"helpers": 2, "old_programs": 2, "direct": 1, "files": 0, "summarised": 0}
