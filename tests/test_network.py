import json

import httpx

from atlas import network
from atlas.sources.live import LiveClient


def test_snapshot_builds_branches_lanes_and_kpis(tmp_path, monkeypatch):
    monkeypatch.setattr(network, "SAVED", tmp_path / "network.json")
    network._CACHE.update(at=0.0, key=None, value=None)

    def handler(req):
        if req.url.path.endswith("/table"):            # CONTROL CD.IDS not set on this TEST
            return httpx.Response(404, json={"error": "Record not found"})
        body = json.loads(req.content)
        if body["table_name"] == "BRANCH":
            rows = [{"ID": "1", "city": "LONDONDERRY", "tax-jur": "NH", "mother.br": "1"},
                    {"ID": "83", "city": "METHUEN", "tax-jur": "MA", "mother.br": "83"},
                    {"ID": "14", "city": "LEBANON", "tax-jur": "NH", "mother.br": "83"},
                    {"ID": "1.SALES", "city": "LONDONDERRY", "tax-jur": "NH", "mother.br": "1"}]
        elif 'MODE = "S"' in body["query"]:
            rows = [{"ID": "500", "from": "83", "to": "14", "mode": "S",
                     "date-ord": "01/02/20", "required": "01/03/20"}]
        else:
            rows = [{"ID": "600", "from": "83", "to": "14", "mode": "O",
                     "date-ord": "01/02/2099", "required": "12/31/2099"},
                    {"ID": "601", "from": "1", "to": "83", "mode": "O",
                     "date-ord": "01/02/2099", "required": "01/03/2020"}]
        return httpx.Response(200, json={"success": True, "data": rows})

    cl = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    s = network.snapshot(cl, 30, refresh=True)
    by = {b["id"]: b for b in s["branches"]}
    assert set(by) == {"1", "83", "14"}                         # 1.SALES is not a physical branch
    assert by["1"]["cd"] and by["83"]["hub"] and by["83"]["children"] == 1 and not by["14"]["hub"]
    assert s["kpis"]["in_transit"] == 1 and s["kpis"]["open"] == 2 and s["kpis"]["overdue"] == 2
    lane = next(ln for ln in s["lanes"] if ln["from"] == "83" and ln["to"] == "14")
    assert lane["open"] == 1 and lane["transit"] == 1 and lane["overdue"] == 1
    assert by["14"]["in_transit"] == 1 and by["14"]["overdue_in"] == 1
    assert network.cached(cl, 30)["kpis"] == s["kpis"]         # saved for the next start
