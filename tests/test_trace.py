from fastapi.testclient import TestClient

from atlas import api, domains, trace
from atlas.parse.program import parse_program
from atlas.store.db import Store


def put(st: Store, name: str, lines: list[str]) -> None:
    h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


def demo(path) -> Store:
    st = Store(path)
    # the screen: the user types the required date, the program converts it and saves the transfer
    put(st, "XFRSCREEN", [
        "      SUBROUTINE XFRSCREEN(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      READ XF FROM XFFILE, K ELSE XF = ''",
        "      CALL ATGUIGETPROP(GUIAPP, 'FRMXFR', 'TXTDTREQ', GPVALUE, 0, 0, REQDT, GUIERRORS, GUISTATE)",
        "      XF<10> = ICONV(REQDT, 'D2/')",
        "      IF REQDT = '' THEN XF<10> = ''",
        "      WRITE XF ON XFFILE, K",
        "      RETURN"])
    put(st, "XFRMENU", ["      PROGRAM XFRMENU", "      CALL XFRSCREEN(K)", "      END"])
    # a batch job stamps today's date
    put(st, "NIGHTLY", [
        "      PROGRAM NIGHTLY",
        "      OPEN 'TRANSFER' TO XFFILE ELSE STOP",
        "      READ XF FROM XFFILE, K ELSE STOP",
        "      XF<10> = DATE()",
        "      WRITE XF ON XFFILE, K",
        "      END"])
    # a reader copies it on into the workflow file, and shows it on a screen
    put(st, "DOCREADY", [
        "      SUBROUTINE DOCREADY(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      OPEN 'WORKFLOW' TO WKFILE ELSE RETURN",
        "      READ XF FROM XFFILE, K ELSE RETURN",
        "      READ WK FROM WKFILE, K ELSE WK = ''",
        "      WK<1> = XF<10>",
        "      CALL ATGUISETPROP(GUIAPP, 'FRMDOC', 'LBLREQ', GPVALUE, '', '', OCONV(XF<10>, 'D2/'), GUIERRORS, X)",
        "      WRITE WK ON WKFILE, K",
        "      RETURN"])
    st.db.execute("INSERT INTO menu VALUES ('M4401', 'RUN BP XFRMENU', 'XFRMENU', 900, NULL)")
    st.commit()
    return st


def test_field_journey_from_screen_to_downstream_copy(tmp_path):
    domains._CACHE.update(key=None, map=None)
    j = trace.field_journey(demo(tmp_path / "atlas.db"), "TRANSFER", 10)
    src = {s["program"]: s for s in j["sources"]}
    screen = src["XFRSCREEN"]
    assert screen["menus"] == [{"menu": "M4401", "used": 900, "path": ["XFRMENU", "XFRSCREEN"]}]
    kinds = {x["line"]: x for x in screen["sets"]}
    assert kinds[5]["kind"] == "screen" and kinds[5]["converted"]
    assert kinds[5]["screen"] == {"form": "FRMXFR", "control": "TXTDTREQ", "line": 4}
    assert kinds[6]["kind"] == "clear" and screen["saved"] == [7]
    assert src["NIGHTLY"]["no_menu"] and src["NIGHTLY"]["sets"][0]["kind"] == "system"
    doc = next(r for r in j["readers"] if r["program"] == "DOCREADY")
    assert doc["copies"][0]["to"] == {"file": "WORKFLOW", "attr": 1, "var": "WK"} and doc["copies"][0]["line"] == 6
    assert doc["shown"] == [{"line": 7, "form": "FRMDOC", "control": "LBLREQ"}]


def test_trace_endpoint(tmp_path, monkeypatch):
    demo(tmp_path / "atlas.db").close()
    monkeypatch.setattr(api.CFG, "store", tmp_path / "atlas.db")
    domains._CACHE.update(key=None, map=None)
    r = TestClient(api.app).get("/api/trace/field/transfer/10").json()
    assert r["field"]["file"] == "TRANSFER" and r["counts"]["writers"] == 2
