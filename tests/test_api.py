from fastapi.testclient import TestClient

from atlas import api
from atlas.parse.program import parse_program
from atlas.store.db import Store

LINES = ["      SUBROUTINE W4DEMO(A)", "      CALL *OPEN.FILE('TRANSFER',XFFILE)",
         "      READ XF FROM XFFILE, K ELSE XF = ''", "      XF<10> = DATE()",
         "      WRITE XF ON XFFILE, K", "      RETURN"]


def client(tmp_path, monkeypatch):
    db = tmp_path / "atlas.db"
    st = Store(db)
    h = st.put_source("git", "BP", "W4DEMO", "src/BP/W4DEMO", "\n".join(LINES))
    st.put_program("git", parse_program("W4DEMO", LINES), h)
    st.db.execute("INSERT INTO menu VALUES ('M1','RUN BP W4DEMO','W4DEMO',42,'2026-04-09')")
    st.db.execute("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading) "
                  "VALUES ('TRANSFER','REQUIRED','A',10,'D2/','REQ')")
    st.commit()
    st.close()
    monkeypatch.setattr(api.CFG, "store", db)
    return TestClient(api.app)


def test_search_and_field(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.get("/api/search", params={"q": "TRANSFER<10>"}).json()
    assert r["fields"] == [{"file": "TRANSFER", "attr": 10, "dict_names": ["REQUIRED"]}]
    r = c.get("/api/search", params={"q": "demo"}).json()
    assert r["programs"][0] == {"name": "W4DEMO", "reached_launches": 42}
    assert c.get("/api/search", params={"q": "REQUIRED"}).json()["dict_names"][0]["attr"] == 10
    f = c.get("/api/field/TRANSFER/10").json()
    w = f["writes"]["programs"][0]
    assert w["program"] == "W4DEMO" and w["sites"][0]["line"] == 4 and w["persisted_by_write_at"] == [5]


def test_fact_review_needs_a_human(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    r = c.post("/api/facts", json={"text": "demo sets required date", "kind": "meaning",
                                   "cites": ["git:W4DEMO:4"], "by": "claude"})
    fid = r.json()["id"]
    assert c.post(f"/api/facts/{fid}/accept", json={"by": "agent"}).status_code == 400
    assert c.post(f"/api/facts/{fid}/retire", json={"by": "Ben"}).status_code == 400   # reason required
    ok = c.post(f"/api/facts/{fid}/accept", json={"by": "Ben"})
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert c.post("/api/facts", json={"text": "x", "cites": ["nope"], "by": "z"}).status_code == 400


def test_blocks_lines_and_drift_empty(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.get("/api/lines/W4DEMO", params={"start": 4, "end": 4}).json()["lines"] == ["4:       XF<10> = DATE()"]
    assert c.get("/api/drift/W4DEMO").json()["drift"] == "not fetched live yet"
    assert c.get("/api/drift").json()["programs"] == []


def test_jobs_attach_and_cancel(tmp_path, monkeypatch):
    import time

    c = client(tmp_path, monkeypatch)
    api.JOBS.clear()

    def slow(st, log):
        for i in range(200):
            log(f"step {i}")
            time.sleep(0.02)

    job = api._run_job("capture", "r1", slow)
    busy = c.post("/api/jobs/sync", json={"live": False})
    assert busy.status_code == 409 and busy.json()["detail"]["job"]["id"] == job["id"]
    c.post(f"/api/jobs/{job['id']}/cancel")
    for _ in range(100):
        if api.JOBS[job["id"]]["state"] != "running":
            break
        time.sleep(0.02)
    assert api.JOBS[job["id"]]["state"] == "cancelled"
    api.JOBS.clear()


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.delenv("UNIVERSE_API_URL", raising=False)
    monkeypatch.setattr(api, "CFG", api.CFG)             # restored after the test: PUT reloads it
    monkeypatch.setattr(api, "_probe_python_layer", lambda url=None: {"ok": True, "ms": 1, "url": url})
    monkeypatch.setattr(api, "_probe_universe", lambda host=None, port=None: {"ok": True, "ms": 1})
    c = TestClient(api.app)
    assert c.put("/api/settings", json={"python_layer_url": "ftp://x"}).status_code == 400
    assert c.put("/api/settings", json={"universe_port": "99999"}).status_code == 400
    r = c.put("/api/settings", json={"python_layer_url": "http://pylayer.local:7000/", "universe_host": "10.1.2.3"})
    assert r.status_code == 200
    v = r.json()["values"]
    assert v["python_layer_url"] == "http://pylayer.local:7000/api/v1" and v["universe_host"] == "10.1.2.3"
    assert api.CFG.live.base_url == "http://pylayer.local:7000/api/v1"
    assert api.CFG.live.cache_dir.name == "_pylayer_local_7000"      # other server, other cache
    r = c.put("/api/settings", json={}).json()                         # reset to policy.yaml
    assert r["values"]["python_layer_url"] == r["defaults"]["python_layer_url"] and r["saved"] == {}


def test_vpn_only_matters_for_a_local_python_layer():
    assert api._is_local("http://localhost:6000/api/v1")
    assert not api._is_local("https://qa.example.com/api/universe/v1")


def test_hidden_tabs_kept_apart_from_connection(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(api, "CFG", api.CFG)
    monkeypatch.setattr(api, "_probe_python_layer", lambda url=None: {"ok": True, "ms": 1, "url": url})
    monkeypatch.setattr(api, "_probe_universe", lambda host=None, port=None: {"ok": True, "ms": 1})
    c = TestClient(api.app)
    r = c.put("/api/settings/nav", json={"hidden": ["/network", "/", "/settings", "/jobs", "bad"]}).json()
    assert r["hidden"] == ["/jobs", "/network"]                   # Overview and Settings can't be hidden
    c.put("/api/settings", json={"python_layer_url": "http://localhost:6000"})
    assert c.get("/api/settings/nav").json()["hidden"] == ["/jobs", "/network"]   # survives a connection save
