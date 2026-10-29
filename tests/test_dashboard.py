from atlas import compare, dashboard
from atlas.store.db import Store


def test_runs_and_open_issues():
    st = Store(":memory:")
    fid = compare.save_flow(st, {"name": "Doc", "steps": [{"name": "After create"}, {"name": "After ship"}],
                                 "files": [{"pick_file": "DOC", "key_template": "{key}"}]})
    step = compare.get_flow(st, fid)["steps"][0]["id"]
    rid = compare.create_run(st, fid, "1", "2")
    file_id = compare.get_flow(st, fid)["files"][0]["id"]
    for side, lines in (("legacy", '["A", "X"]'), ("new", '["A", "Y"]')):
        st.db.execute("INSERT INTO cmp_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (rid, step, side, file_id, "1", 1, lines, "h", None, "2026-09-27T10:00:00+00:00"))
    st.commit()
    compare.add_note(st, rid, "DOC", 2, "bug", "new side writes the wrong status", "Tester", remember=False)
    compare.add_note(st, rid, "DOC", 1, "expected", "fine", "Tester", remember=False)
    [run] = dashboard.recent_runs(st)
    assert run["captured_steps"] == 1 and run["steps"] == 2 and run["differences"] == 1 and run["bugs"] == 1
    issues = dashboard.open_issues(st)
    assert issues["total"] == 1 and issues["items"][0]["attr"] == 2
    assert issues["items"][0]["href"] == f"/compare/runs/{rid}"
