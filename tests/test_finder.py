import json

import httpx
import pytest

from atlas import finder
from atlas.sources.live import LiveClient
from atlas.store.db import Store


def store():
    st = Store(":memory:")
    st.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr) VALUES ('DOC',?,?,?)",
                      [("MODE", "A", 2), ("DATE-ORD", "A", 9)])
    st.commit()
    return st


def test_query_guard():
    assert finder.check_query('  WITH MODE = "S"   AND WITH DATE-ORD GE "09/01/2026" ') == \
        'WITH MODE = "S" AND WITH DATE-ORD GE "09/01/2026"'
    for bad in ('SELECT DOC', 'WITH X = "1"; DELETE DOC', 'WITH A = "1" \\ RUN BP X', "LIST DOC"):
        with pytest.raises(finder.FinderError):
            finder.check_query(bad)


def test_normalise_drops_unknown_columns_and_bad_related():
    related = [{"file": "doc-hist", "key": "{key}-1"}, {"file": "X", "key": "1"}]
    c = finder.normalise(store(), "DOC", {"query": 'WITH MODE = "S"', "columns": ["mode", "NOPE"], "related": related})
    assert c["columns"] == ["MODE"]
    assert c["related"] == [{"file": "DOC-HIST", "key": "{key}-1", "exists": True, "why": ""}]


def test_run_applies_related_checks(tmp_path):
    def handler(req):
        body = json.loads(req.content)
        if req.url.path.endswith("/table/query"):
            return httpx.Response(200, json={"success": True, "data": [
                {"ID": k, "mode": "S", "date-ord": "09/10/26"} for k in ("101", "102", "103")]})
        found = {"101-1", "103-1"}
        return httpx.Response(200, json={"success": True, "data": [
            {k: (["x"] if k in found else [])} for k in body["record_ids"]]})
    cl = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    r = finder.run(store(), cl, "doc", {"query": 'WITH MODE = "S"', "columns": ["MODE", "DATE-ORD"],
                                        "related": [{"file": "DOC-HIST", "key": "{key}-1", "exists": True}]}, 10)
    assert r["selected"] == 3 and [m["key"] for m in r["matches"]] == ["103", "101"]   # newest first
    assert r["matches"][0]["values"] == {"MODE": "S", "DATE-ORD": "09/10/26"}


def test_scenarios_crud():
    st = store()
    s = finder.save(st, {"pick_file": "doc", "name": "Shipped", "criteria": {"query": 'WITH MODE = "S"'}})
    assert finder.list_all(st, table="DOC")[0]["criteria"]["query"] == 'WITH MODE = "S"'
    finder.delete(st, s["id"])
    assert finder.list_all(st) == []


def test_show_converts_dates_and_scaled_numbers():
    assert finder.show("D2/", "21438") == "2026-09-10"           # a Pick day number
    assert finder.show("MD2", "12345") == "123.45" and finder.show("MR0", "7") == "7"
    assert finder.show("D", "not a day") == "not a day" and finder.show("", "ABC") == "ABC"


def test_fields_name_process_states():
    st = Store(":memory:")
    st.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr, conv, depth) VALUES ('TRANSFER',?,?,?,?,?)",
                      [("MODE", "A", 2, "", "S"), ("REQUIRED", "A", 10, "D2/", "S"), ("@ID", "D", 0, "", "S")])
    st.commit()
    by = {f["name"]: f for f in finder.fields(st, "transfer")}
    assert by["REQUIRED"]["kind"] == "date" and by["@ID"]["kind"] == "key"
    assert {v["value"]: v["label"] for v in by["MODE"]["values"]}["S"] == "Shipped"


def test_record_names_converts_and_reads_related(tmp_path):
    def handler(req):
        rid = req.url.params.get("record_id")
        if rid == "500":
            data = ["83", "S", ["A", "B"], "", "", "", "", "", "", "21438"]
            return httpx.Response(200, json={"success": True, "data": data})
        if rid == "500-1":
            return httpx.Response(200, json={"success": True, "data": ["83"]})
        return httpx.Response(404, json={"error": "Record not found"})

    st = Store(":memory:")
    st.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr, conv) VALUES (?,?,?,?,?)",
                      [("TRANSFER", "MODE", "A", 2, ""), ("TRANSFER", "REQUIRED", "A", 10, "D2/"),
                       ("TRANSFER", "DATEREQD", "A", 10, "D2/"), ("TRANSFER-HIST", "FROM", "A", 1, "")])
    st.commit()
    cl = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    r = finder.record(st, cl, "transfer", "500", [{"file": "TRANSFER-HIST", "key": "{key}-1"},
                                                  {"file": "TRANSFER-HIST", "key": "{key}-2"}])
    f = {x["attr"]: x for x in r["fields"]}
    assert f[2]["names"] == ["MODE"] and f[2]["values"] == ["S"]
    assert f[3]["values"] == ["A", "B"]                          # multivalued
    assert f[10]["names"] == ["DATEREQD", "REQUIRED"] and f[10]["values"] == ["2026-09-10"] and f[10]["raw"] == "21438"
    assert [(x["key"], x["exists"]) for x in r["related"]] == [("500-1", True), ("500-2", False)]
    assert r["related"][0]["fields"][0]["names"] == ["FROM"]


def test_run_asks_for_the_key_once_and_tells_unreachable_from_rejected(tmp_path):
    asked = []

    def handler(req):
        body = json.loads(req.content)
        asked.append(body["attributes"])
        return httpx.Response(200, json={"success": True, "data": [{"ID": "7", "mode": "S"}]})

    st = store()
    st.db.execute("INSERT INTO dict_attr (pick_file, name, type, attr) VALUES ('DOC', '@ID', 'D', 0)")
    cl = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    r = finder.run(st, cl, "DOC", {"query": 'WITH MODE = "S"', "columns": ["@ID", "MODE"]})
    assert asked == [["@ID", "MODE"]]                        # not ["@ID", "@ID", "MODE"]: a 422 on TEST
    assert r["matches"][0]["values"] == {"@ID": "7", "MODE": "S"}

    def down(req):
        raise httpx.ConnectError("nodename nor servname provided")

    cl2 = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(down))
    with pytest.raises(finder.FinderUnreachable):
        finder.run(st, cl2, "DOC", {"query": 'WITH MODE = "S"'})
