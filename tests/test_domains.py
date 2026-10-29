from atlas import domains
from atlas.parse.program import parse_program
from atlas.store.db import Store


def put(st: Store, name: str, *calls: str) -> None:
    lines = [f"      SUBROUTINE {name}"] + [f"      CALL {c}" for c in calls] + ["      RETURN"]
    h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


def test_domains_from_menus_calls_and_callers(tmp_path, monkeypatch):
    monkeypatch.setattr(domains, "UTILITY", 3)         # PRODDESC has 5 callers: a utility here
    st = Store(tmp_path / "atlas.db")
    put(st, "ORDENTRY", "PRICESUB", "COMMONSUB")       # M1 entry
    put(st, "STOCKRCV", "COMMONSUB", "RCVSUB")         # M4 entry
    put(st, "CUSTMAINT", "COMMONSUB")                  # M7 entry
    put(st, "PRICESUB")
    put(st, "RCVSUB")
    put(st, "COMMONSUB")
    put(st, "NIGHTLY", "RCVSUB")                       # no menu, calls receiving code
    put(st, "PRODDESC")
    for i in range(4):
        put(st, f"FIX{i}", "PRODDESC")                 # only calls everybody's lookup
    put(st, "ORDENTRY2", "PRODDESC")
    put(st, "LONELY")
    for code, prog, used in [("M1112", "ORDENTRY", 1000), ("M1113", "ORDENTRY2", 5), ("M4830", "STOCKRCV", 500),
                             ("M7001", "CUSTMAINT", 50)]:
        st.db.execute("INSERT INTO menu VALUES (?, ?, ?, ?, NULL)", (code, f"RUN BP {prog}", prog, used))
    st.commit()
    d = domains.build(st)
    assert (d["ORDENTRY"], d["STOCKRCV"], d["CUSTMAINT"]) == ("1", "4", "7")
    assert d["PRICESUB"] == "1" and d["RCVSUB"] == "4"          # a subroutine joins the domain that calls it
    assert d["COMMONSUB"] == domains.SHARED                      # reached from three domains
    assert d["NIGHTLY"] == "4"                                   # batch code that calls receiving
    assert d["FIX0"] == domains.OFF and d["LONELY"] == domains.OFF
