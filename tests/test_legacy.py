import pytest

from atlas import legacy
from atlas.parse.proc import parse_proc, schedule_of
from atlas.parse.program import parse_program
from atlas.store.db import Store
from atlas.sync import index_proc

GOODNIGHT = "\n".join([
    "PQN", "HSLEEP 24:00", "P",
    "HSSELECT PRODUCT BY WHSE", "H BY LINE", "STON", "HRUN BP LG.PURCH.GEN (P)", "P",
    "HSORT PRODUCT BY WHSE", 'H AND WITH AV-FOR-BO > "0"', "H ID-SUPP DESCRIPTION ON-HAND",
    """H HEADING "BACKORDERS REPORT AS OF 'TL'PAGE 'PL'" """, "H LPTR", "P",
    "[PROK CLEANUP]", "X",
])
CLEANUP = "\n".join(["PQ", "HCLEAR-FILE DATA WORKFILE", "P", "X"])


def test_parse_proc_commands():
    p = parse_proc(GOODNIGHT, "GOODNIGHT")
    kinds = [(c.kind, c.target) for c in p.commands]
    assert ("sleep", "") in kinds and ("run", "LG.PURCH.GEN") in kinds and ("proc", "CLEANUP") in kinds
    rep = next(c for c in p.commands if c.kind == "report")
    assert rep.target == "PRODUCT" and rep.printed and rep.heading == "BACKORDERS REPORT AS OF"
    assert rep.columns == ["WHSE", "DESCRIPTION", "ON-HAND"] and rep.criteria.startswith("WITH AV-FOR-BO")
    assert schedule_of(p) == "nightly"
    c = parse_proc(CLEANUP, "EOM-CLEANUP")
    assert c.commands[0].kind == "destructive" and schedule_of(c) == "month-end"


def test_jobs_graph_and_parity():
    st = Store(":memory:")
    lines = ["      PROGRAM LG.PURCH.GEN", "      CALL *OPEN.FILE('SUGG-PO',SF)", "      WRITE R ON SF, K",
             "      CALL *OPEN.FILE('CONTROL',CF)", '      WRITE N ON CF, "PO#"', "      END"]
    h = st.put_source("git", "BP", "LG.PURCH.GEN", "src/BP/LG.PURCH.GEN", "\n".join(lines))
    st.put_program("git", parse_program("LG.PURCH.GEN", lines), h)
    index_proc(st, "GOODNIGHT", GOODNIGHT)
    index_proc(st, "CLEANUP", CLEANUP)
    st.db.execute("INSERT INTO menu VALUES ('M9','EXEC GOODNIGHT',NULL,12,'2026-04-09')")
    st.commit()
    j = legacy.job(st, "goodnight")
    assert j["schedule"] == "nightly" and j["calls"] == ["CLEANUP"] and j["menus"][0]["code"] == "M9"
    assert j["programs"][0]["name"] == "LG.PURCH.GEN" and "SUGG-PO" in j["writes"] and j["counters"] == ["PO#"]
    assert legacy.job(st, "CLEANUP")["called_by"] == ["GOODNIGHT"]
    cat = {r["name"]: r for r in legacy.catalogue(st)}
    assert cat["GOODNIGHT"]["output"] == "printer" and cat["GOODNIGHT"]["files"] == ["PRODUCT"]
    legacy.set_parity(st, "report", "GOODNIGHT", "standard", "Stock Projected Qty")
    assert legacy.list_reports(st)["decided"] == 1
    with pytest.raises(ValueError):
        legacy.set_parity(st, "report", "GOODNIGHT", "scheduled")
