import json

from atlas import finder_eval
from atlas.store.db import Store


def store() -> Store:
    st = Store(":memory:")
    st.db.executemany("INSERT INTO dict_attr (pick_file, name, type, attr) VALUES ('TRANSFER',?,?,?)",
                      [("MODE", "A", 2), ("S/ORD#", "A", 2), ("VIA", "A", 15), ("REQUIRED", "A", 10)])
    st.commit()
    return st


CASE = {"id": "T", "status": "verified", "file": "TRANSFER", "description": "an open transfer going by UPS",
        "expect": {"conditions": [{"attr": 2, "op": "=", "values": ["O"]}, {"attr": 15, "op": "=", "values": ["UPS"]}],
                   "related": [{"file": "TRANSFER-HIST", "key": "{key}-1", "exists": False}]}}


def test_conditions_resolve_synonyms_and_kinds():
    q = 'WITH S/ORD# = "O" AND WITH VIA # "" AND WITH REQUIRED GE "10/01/2026"'
    got = [(g["attr"], g["op"], g["value"]) for g in finder_eval.conditions(store(), "TRANSFER", q)]
    assert got == [(2, "=", "O"), (15, "filled", ""), (10, "range", "10/01/2026")]       # S/ORD# is MODE: <2>


def test_score_counts_fields_related_and_live_checks():
    crit = {"query": 'WITH S/ORD# = "O" AND WITH VIA = "UPS"', "related": []}
    r = finder_eval.score(store(), CASE, crit, {"total_matches": 3}, None)
    assert r["checks"] == {"valid": 1.0, "found": 1.0, "fields": 1.0, "related": 0.0, "keys": None}
    assert r["score"] == 0.75 and r["missing"] == [CASE["expect"]["related"][0]]
    wrong = finder_eval.score(store(), CASE, {"query": 'WITH MODE = "R"', "related": []}, None, "TEST rejected it")
    assert wrong["checks"]["valid"] == 0.0 and wrong["checks"]["fields"] == 0.0


def test_case_file_is_well_formed():
    cases = finder_eval.load()
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["status"] in ("draft", "verified") and c["file"] and c["description"]
        assert c["expect"].get("conditions") or c["expect"].get("related")
        json.dumps(c)
