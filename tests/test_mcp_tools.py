from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from atlas import domains, finder
from atlas.mcp import server
from atlas.parse.program import parse_program
from atlas.store.db import Store


def put(st: Store, name: str, lines: list[str]) -> None:
    h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


@pytest.fixture
def st(tmp_path, monkeypatch):
    s = Store(tmp_path / "atlas.db")
    put(s, "XFRRECV", [
        "      SUBROUTINE XFRRECV(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      READ XF FROM XFFILE, K ELSE RETURN",
        "      CALL ATGUIGETPROP(GUIAPP, 'FRMXFR', 'TXTDTREQ', GPVALUE, 0, 0, REQDT, GUIERRORS, GUISTATE)",
        "      IF XF<2> = 'S' THEN XF<2> = 'R'",
        "      XF<10> = REQDT",
        "      WRITE XF ON XFFILE, K",
        "      RETURN"])
    s.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr) VALUES ('TRANSFER',?,?,?)",
                     [("MODE", "A", 2), ("REQUIRED", "A", 10)])
    s.db.execute("INSERT INTO menu VALUES ('M4401', 'RUN BP XFRRECV', 'XFRRECV', 900, NULL)")
    s.commit()
    domains._CACHE.update(key=None, map=None)
    monkeypatch.setattr(server, "_store", s)
    monkeypatch.setitem(server._LIVE_CALLS, "n", 0)
    return s


def test_trace_and_process_are_condensed_with_their_pages(st):
    t = server.trace_field("TRANSFER", 10)
    assert t["set_by"][0]["program"] == "XFRRECV" and t["set_by"][0]["sets"][0]["screen"] == "FRMXFR.TXTDTREQ"
    assert t["set_by"][0]["menu"] == "M4401 via XFRRECV" and t["page"] == "/trace?file=TRANSFER&attr=10"
    p = server.process_flow("transfer")
    received = next(s for s in p["states"] if s["code"] == "R")
    assert received["label"] == "Received" and received["set_by"][0]["from"] == "S"
    assert p["page"] == "/process?p=transfer"
    assert "error" in server.process_flow("nope")


def test_data_link_checks_the_query_and_never_touches_test(st):
    r = server.test_data_link("transfer", 'WITH MODE = "R"', ["mode", "NOPE"])
    q = parse_qs(urlparse(r["url"]).query)
    assert q == {"file": ["TRANSFER"], "q": ['WITH MODE = "R"'], "cols": ["MODE"], "run": ["1"]}
    assert "error" in server.test_data_link("TRANSFER", "DELETE TRANSFER")


def test_live_examples_are_opt_in_budgeted_and_refuse_sensitive_files(st, monkeypatch):
    assert "off" in server.live_examples("TRANSFER", 'WITH MODE = "R"')["error"]
    monkeypatch.setenv("ATLAS_LIVE_EXAMPLES", "1")
    monkeypatch.setattr(server.sync, "live_client", lambda cfg: object())
    monkeypatch.setattr(finder, "run", lambda store, client, table, crit, limit: {
        "criteria": {"query": crit["query"], "columns": ["MODE"]}, "total_matches": 7,
        "matches": [{"key": "812345", "values": {"MODE": "R"}}][:limit]})
    r = server.live_examples("TRANSFER", 'WITH MODE = "R"', ["MODE"], limit=10)
    assert r["records"] == [{"key": "812345", "MODE": "R"}] and r["matched"] == 7
    assert r["more"].startswith("/test-data?")
    assert "budget" in server.live_examples("TRANSFER", 'WITH MODE = "R"')["error"]        # one call allowed
    monkeypatch.setenv("ATLAS_LIVE_EXAMPLES", "5")
    monkeypatch.setattr(server.cfgmod, "load", lambda: SimpleNamespace(live=SimpleNamespace(deny_tables={"PAYROLL"})))
    assert "sensitive" in server.live_examples("payroll", "")["error"]


def test_live_record_reads_one_key_within_the_shared_budget(st, monkeypatch):
    assert "off" in server.live_record("ALT-PN", "MIS")["error"]
    monkeypatch.setenv("ATLAS_LIVE_EXAMPLES", "2")
    monkeypatch.setattr(server, "_LIVE_CALLS", {"n": 0})
    monkeypatch.setattr(server.sync, "live_client", lambda cfg: object())

    def fake_record(store, client, table, key, related=None):
        if key != "MIS":
            raise finder.FinderError(f"Couldn't read {table} {key}: HTTP 404: not found")
        return {"key": key, "fetched_at": "now", "fields": [
            {"attr": 1, "names": ["CTRL"], "raw": "S1000001", "values": ["S1000001"]},
            {"attr": 2, "names": [], "raw": "", "values": []}]}
    monkeypatch.setattr(finder, "record", fake_record)
    r = server.live_record("alt-pn", "MIS")
    assert r["found"] and r["source"] == "TEST"
    assert r["fields"] == [{"attr": 1, "names": ["CTRL"], "values": ["S1000001"]}]      # empty attributes dropped
    assert server.live_record("ALT-PN", "NOPE") == {"file": "ALT-PN", "key": "NOPE", "found": False}
    assert "budget" in server.live_examples("PRODUCT", 'WITH @ID LIKE "S..."')["error"]   # the budget is shared


def test_test_reads_are_logged_per_person_and_capped_per_day(st, monkeypatch):
    from atlas import auth
    monkeypatch.setenv("ATLAS_LIVE_EXAMPLES", "10")
    monkeypatch.setenv("ATLAS_LIVE_DAILY", "2")
    monkeypatch.setenv("ATLAS_USER_ID", "u-max")
    monkeypatch.setattr(server, "_LIVE_CALLS", {"n": 0})
    monkeypatch.setattr(server.sync, "live_client", lambda cfg: object())
    monkeypatch.setattr(finder, "record", lambda store, client, table, key, related=None: {
        "key": key, "fetched_at": "now", "fields": []})
    assert server.live_record("PRODUCT", "1")["found"] and server.live_record("PRODUCT", "2")["found"]
    assert "daily TEST read limit" in server.live_record("PRODUCT", "3")["error"]
    s = server._st()
    assert auth.test_reads_today(s, "u-max") == 2 and auth.test_reads_today(s, "u-ada") == 0
    rows = [r["detail"] for r in s.db.execute("SELECT detail FROM audit WHERE action='test.read'")]
    assert '"what": "record 1"' in rows[0] and '"via": "ask-atlas"' in rows[0]
