import httpx
import pytest

from atlas import compare
from atlas.sources.live import LiveClient
from atlas.store.db import Store

# What the fake TEST server holds: (file, key) -> attributes.  The records change between steps.
DB: dict[tuple[str, str], list[str]] = {}


def client(tmp_path):
    def handler(req):
        key = (req.url.params["table_name"], req.url.params["record_id"])
        if key not in DB:
            return httpx.Response(200, json={"success": False, "data": [], "error": "Record not found"})
        return httpx.Response(200, json={"success": True, "data": DB[key], "error": None})
    return LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))


def setup():
    st = Store(":memory:")
    st.db.execute("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading) "
                  "VALUES ('DOC','REQUIRED','A',2,'D2/','REQ')")
    st.db.execute("INSERT INTO dict_attr (pick_file, name, type, attr, conv, heading) "
                  "VALUES ('DOC','STATUS','A',3,'','ST')")
    st.commit()
    fid = compare.save_flow(st, {"name": "Doc lifecycle", "steps": [{"name": "After create"}, {"name": "After ship"}],
                                 "files": [{"pick_file": "doc", "key_template": "{key}"},
                                           {"pick_file": "DOC-LOG", "key_template": "{key}-1"}]})
    return st, fid


def test_flow_crud_keeps_ids():
    st, fid = setup()
    f = compare.get_flow(st, fid)
    assert [s["name"] for s in f["steps"]] == ["After create", "After ship"]
    assert [x["pick_file"] for x in f["files"]] == ["DOC", "DOC-LOG"]
    step_ids = [s["id"] for s in f["steps"]]
    f["steps"].append({"name": "After invoice"})
    compare.save_flow(st, f, fid)
    again = compare.get_flow(st, fid)
    assert [s["id"] for s in again["steps"]][:2] == step_ids           # edits keep existing ids
    assert len(again["steps"]) == 3
    with pytest.raises(compare.CompareError):
        compare.save_flow(st, {"name": "x", "steps": [], "files": [{"pick_file": "A"}]})


def test_capture_diff_changes_notes(tmp_path):
    st, fid = setup()
    cl = client(tmp_path)
    create, ship = [s["id"] for s in compare.get_flow(st, fid)["steps"]]
    rid = compare.create_run(st, fid, "100", "900")
    assert compare.get_run(st, rid)["files"][1]["keys"] == {"legacy": "100-1", "new": "900-1"}

    DB.clear()
    DB[("DOC", "100")] = ["A", "21438", "OPEN", "x\xfdy"]
    DB[("DOC", "900")] = ["A", "21438", "OPEN", "xy"]        # same data, PUA-encoded mark
    DB[("DOC-LOG", "100-1")] = ["created"]
    compare.capture(st, cl, rid, create, log=lambda _m: None)
    d = compare.diff(st, rid, create)
    doc, log = d["files"]
    assert doc["differences"] == 0                                   # PUA vs raw mark is not a difference
    assert doc["rows"][1]["names"] == ["REQUIRED"] and doc["rows"][1]["old"]["date"] == "2026-09-10"
    assert log["new"]["found"] is False and log["rows"][0]["status"] == "old-only"

    DB[("DOC", "100")] = ["A", "21438", "SHIPPED", "x\xfdy"]
    DB[("DOC", "900")] = ["A", "21439", "SHIPPED", "x\xfdy"]
    compare.capture(st, cl, rid, ship, log=lambda _m: None)
    ch = compare.changes(st, rid, create, ship)["files"][0]["rows"]
    assert {(r["attr"], r["change"]) for r in ch} == {(2, "new-only"), (3, "both")}

    nid = compare.add_note(st, rid, "DOC", 2, "bug", "new system moves the required date", "Zilen")
    rid2 = compare.create_run(st, fid, "101", "901")
    DB[("DOC", "101")], DB[("DOC", "901")] = ["A", "1"], ["A", "2"]
    compare.capture(st, cl, rid2, create, log=lambda _m: None)
    row = compare.diff(st, rid2, create)["files"][0]["rows"][1]
    assert row["notes"][0]["id"] == nid and row["notes"][0]["scope"] == "flow"   # remembered for the next run
    compare.update_note(st, nid, "expected", None)
    md = compare.report_markdown(st, rid)
    assert "After ship" in md and "expected: new system moves the required date" in md

    compare.update_run(st, rid, {"overrides": [{"file_id": compare.get_flow(st, fid)["files"][1]["id"],
                                                "side": "new", "key": "900-9"}]})
    assert compare.get_run(st, rid)["files"][1]["keys"]["new"] == "900-9"


def test_quick_compare(tmp_path):
    st, _ = setup()
    DB.clear()
    DB[("DOC", "1")], DB[("DOC", "2")] = ["A", "5", "X"], ["A", "6", ""]
    q = compare.quick(client(tmp_path), st, "doc", "1", "2")
    assert [(r["attr"], r["status"]) for r in q["rows"]] == [(1, "same"), (2, "different"), (3, "old-only")]
    assert q["differences"] == 2


def test_key_variants_per_file(tmp_path):
    """One document, keyed T11027 in one file and 11027 in another: capture finds both
    and remembers the working pattern on the flow."""
    st = Store(":memory:")
    fid = compare.save_flow(st, {"name": "Transfer", "steps": [{"name": "After create"}],
                                 "files": [{"pick_file": "TRANSFER", "key_template": "{key}"},
                                           {"pick_file": "XFER-LOG", "key_template": "{key}"},
                                           {"pick_file": "TRANSFER-HIST", "key_template": "{num}-1"}]})
    step = compare.get_flow(st, fid)["steps"][0]["id"]
    rid = compare.create_run(st, fid, "T11027", "11030")
    DB.clear()
    DB[("TRANSFER", "11027")] = ["A"]
    DB[("TRANSFER", "11030")] = ["B"]
    DB[("XFER-LOG", "T11027")] = ["L1"]
    DB[("XFER-LOG", "T11030")] = ["L2"]           # new side only has it with the prefix
    DB[("TRANSFER-HIST", "11027-1")] = ["H"]
    msgs: list[str] = []
    compare.capture(st, client(tmp_path), rid, step, log=msgs.append)
    snaps = {(r["side"], r["record_key"]): r["found"] for r in st.db.execute("SELECT * FROM cmp_snapshot")}
    assert snaps[("legacy", "11027")] and snaps[("new", "11030")]
    assert snaps[("legacy", "T11027")] and snaps[("new", "T11030")]
    assert snaps[("legacy", "11027-1")]
    pats = {f["pick_file"]: f["key_template"] for f in compare.get_flow(st, fid)["files"]}
    assert pats["TRANSFER"] == "{num}" and pats["XFER-LOG"] == "T{num}" and pats["TRANSFER-HIST"] == "{num}-1"
    assert any("found 11027" in m for m in msgs)
    assert not any(m.startswith("WARNING") for m in msgs)
    assert compare.resolve_key("T{num}", "11027") == "T11027" == compare.resolve_key("T{num}", "T11027")


def test_quick_compare_tries_variants(tmp_path):
    st = Store(":memory:")
    DB.clear()
    DB[("TRANSFER", "11027")] = ["A"]
    DB[("TRANSFER", "11030")] = ["B"]
    r = compare.quick(client(tmp_path), st, "transfer", "T11027", "11030")
    assert r["old"]["key"] == "11027" and r["old"]["error"] is None and r["differences"] == 1
