import httpx

from atlas import profile
from atlas.sources.live import LiveClient
from atlas.store.db import Store

DICT = [{"pos": 1, "uv": "BR", "aliases": [], "sm": "S", "format": "string", "conv": ""},
        {"pos": 2, "uv": "DATE", "aliases": [], "sm": "S", "format": "date", "conv": "D2/"},
        {"pos": 3, "uv": "QTY", "aliases": [], "sm": "S", "format": "number", "conv": "MD0"},
        {"pos": 5, "uv": "OLD", "aliases": [], "sm": "S", "format": "string", "conv": ""}]


def recs():
    out = {}
    for i in range(100):
        out[str(1000 + i)] = [
            "57" if i % 10 else "999",                      # <1> branch; 999 isn't a branch
            "21438" if i != 7 else "00/00",                   # <2> Pick date; one bad value
            "5" if i != 3 else "S",                           # <3> number; one letter
            "a\xfdb" if i < 20 else "x",                      # <4> undocumented, sometimes multivalued
            "",                                               # <5> in DICT, never filled
            "OPEN " if i == 1 else ("Open" if i == 2 else "OPEN"),  # <6> code with spaces + case clash
        ]
    return out


def test_analyse_finds_the_problems():
    res = profile.analyse("DOC", recs(), DICT, {}, {4: 3})
    by = {a["pos"]: a for a in res["attributes"]}
    codes = {p: {x["code"] for x in by[p]["problems"]} for p in by}
    assert by[1]["filled_pct"] == 100.0 and "required" in codes[1]
    assert "date" in codes[2] and "number" in codes[3]
    assert "undocumented" in codes[4] and by[4]["multi_pct"] == 20.0
    assert "unused" in codes[5]
    assert {"spaces", "case"} <= codes[6]
    assert res["key_shapes"][0] == ("9{4}", 100)


def test_references_from_code_and_checked_on_test(tmp_path):
    st = Store(":memory:")
    st.db.executemany("INSERT INTO io_op VALUES ('git',?,?,?,?,?,?,?,NULL,NULL)", [
        ("P1", 10, "READ", "DF", "DOC", "D", "K"),
        ("P1", 11, "READ", "BF", "BRANCH", "B", "D<1>"),
        ("P2", 5, "MATREAD", "DF", "DOC", "D", "K"),
        ("P2", 9, "READ", "BF", "BRANCH", "B", "D<1,1>"),
        ("P2", 12, "READ", "WF", "SORTWK", "W", "D<1>"),      # work file: ignored
    ])
    refs = profile.key_references(st, "DOC")
    assert refs == {1: [{"file": "BRANCH", "programs": 2, "examples": ["P1", "P2"]}]}

    def handler(req):
        import json
        body = json.loads(req.content)
        return httpx.Response(200, json={"success": True, "data": [
            {k: (["BRANCH 57"] if k == "57" else [])} for k in body["record_ids"]]})
    cl = LiveClient("http://t/api/v1", min_interval_s=0, cache_dir=tmp_path, transport=httpx.MockTransport(handler))
    r = recs()
    res = profile.analyse("DOC", r, DICT, refs, {})
    profile.check_references(cl, "DOC", r, res, log=lambda _m: None)
    a1 = next(a for a in res["attributes"] if a["pos"] == 1)
    assert a1["refs"][0]["missing"] == 1 and a1["refs"][0]["missing_examples"] == ["999"]
    assert any(p["code"] == "ref" for p in a1["problems"])
