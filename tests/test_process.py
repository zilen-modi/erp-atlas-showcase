from fastapi.testclient import TestClient

from atlas import api, domains, process
from atlas.parse.program import parse_program
from atlas.store.db import Store


def put(st: Store, name: str, lines: list[str]) -> None:
    h = st.put_source("git", "BP", name, f"src/BP/{name}", "\n".join(lines))
    st.put_program("git", parse_program(name, lines), h)


def demo(path) -> Store:
    st = Store(path)
    put(st, "XFRNEW", [                                   # creates the transfer: blank -> O
        "      SUBROUTINE XFRNEW(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      READ XF FROM XFFILE, K ELSE XF = ''",
        "      IF XF<2> = '' THEN XF<2> = 'O'",
        "      XF<10> = DATE()",
        "      WRITE XF ON XFFILE, K",
        "      RETURN"])
    put(st, "XFRRECV", [                                  # receives it: S -> R, keeps a history leg
        "      SUBROUTINE XFRRECV(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      OPEN 'TRANSFER-HIST' TO XFHFILE ELSE RETURN",
        "      READ XF FROM XFFILE, K ELSE RETURN",
        "      IF XF<2> = 'S' THEN",
        "         XF<2> = 'R'",
        "         XF<12> = DATE()",
        "      END",
        "      WRITE XF ON XFHFILE, K:'-2'",
        "      DELETE XFFILE, K",
        "      RETURN"])
    put(st, "ORDSTUFF", [                                 # TEST<2> here is an ORDER, not a transfer
        "      SUBROUTINE ORDSTUFF(K)",
        "      OPEN 'TRANSFER' TO XFFILE ELSE RETURN",
        "      OPEN 'ORDER' TO ORDFILE ELSE RETURN",
        "      READ TEST FROM XFFILE, K ELSE TEST = ''",
        "      READV TEST FROM ORDFILE, K, 2 ELSE TEST = ''",
        "      TEST<2> = 'B'",
        "      RETURN"])
    st.db.execute("INSERT INTO menu VALUES ('M4401', 'RUN BP XFRNEW', 'XFRNEW', 900, NULL)")
    st.commit()
    return st


def test_transfer_states_steps_and_archive(tmp_path):
    domains._CACHE.update(key=None, map=None)
    j = process.process_flow(demo(tmp_path / "atlas.db"), "transfer")
    steps = {(s["program"], s["to"]): s for s in j["steps"]}
    assert set(steps) == {("XFRNEW", "O"), ("XFRRECV", "R")}            # ORDSTUFF's TEST<2> is an ORDER
    new = steps[("XFRNEW", "O")]
    assert new["from"] is None and new["saved_to"] == "TRANSFER" and new["also_sets"] == [10]
    recv = steps[("XFRRECV", "R")]
    assert recv["from"] == "S" and recv["saved_to"] == "TRANSFER-HIST" and 12 in recv["also_sets"]
    assert [s["code"] for s in j["states"]] == ["O", "S", "R"] and j["states"][0]["label"] == "Ordered"
    assert j["programs"]["XFRNEW"]["menus"][0]["menu"] == "M4401"
    assert j["leave"][0]["program"] == "XFRRECV" and j["leave"][0]["archives_to"] == ["TRANSFER-HIST"]


def test_process_endpoints(tmp_path, monkeypatch):
    demo(tmp_path / "atlas.db").close()
    monkeypatch.setattr(api.CFG, "store", tmp_path / "atlas.db")
    domains._CACHE.update(key=None, map=None)
    c = TestClient(api.app)
    assert c.get("/api/processes").json()[0]["key"] == "transfer"
    assert c.get("/api/process/transfer").json()["process"]["file"] == "TRANSFER"
    assert c.get("/api/process/nope").status_code == 404
