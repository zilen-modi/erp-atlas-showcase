import json

import pytest
from fastapi.testclient import TestClient

from atlas import api, auth, chat
from atlas.store.db import Store


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "atlas.db"
    Store(db).close()
    monkeypatch.setattr(api.CFG, "store", db)
    monkeypatch.setattr(api, "AUTH", True)
    monkeypatch.setattr(auth, "KEY_FILE", tmp_path / "secret.key")
    monkeypatch.setattr(auth, "ROOT", tmp_path)
    st = Store(db)
    admin, _ = auth.create_user(st, "ada@acme.test", "Ada Admin", "admin", password="admin-pass-1")
    member, _ = auth.create_user(st, "max@acme.test", "Max Member", "member", password="member-pass-1")
    st.close()
    return db, admin, member


def signed_in(email, pw):
    c = TestClient(api.app)
    assert c.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 200
    return c


def test_passwords_hash_and_check():
    h = auth.hash_password("correct horse")
    assert h.startswith("scrypt$") and "correct horse" not in h
    assert auth.check_password("correct horse", h) and not auth.check_password("wrong", h)
    with pytest.raises(auth.AuthError):
        auth.hash_password("short")


def test_api_needs_sign_in(env):
    c = TestClient(api.app)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/chats").status_code == 401
    assert c.post("/api/auth/login", json={"email": "ada@acme.test", "password": "nope"}).status_code == 400
    st = c.get("/api/auth/state").json()
    assert st["auth"] and not st["setup_needed"] and st["user"] is None


def test_session_cookie_is_httponly_and_logout_ends_it(env):
    c = TestClient(api.app)
    r = c.post("/api/auth/login", json={"email": "ADA@acme.test ", "password": "admin-pass-1"})
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/auth/me").json()["user"]["email"] == "ada@acme.test"
    c.post("/api/auth/logout")
    assert c.get("/api/chats").status_code == 401


def test_members_cannot_do_admin_things(env):
    m = signed_in("max@acme.test", "member-pass-1")
    assert m.get("/api/chats").status_code == 200
    assert m.get("/api/admin/users").status_code == 403
    assert m.post("/api/facts/F-0001/accept", json={}).status_code == 403
    assert m.post("/api/jobs/sync", json={}).status_code == 403
    a = signed_in("ada@acme.test", "admin-pass-1")
    assert len(a.get("/api/admin/users").json()["users"]) == 2


def test_new_user_must_choose_a_password(env):
    a = signed_in("ada@acme.test", "admin-pass-1")
    r = a.post("/api/admin/users", json={"email": "new@acme.test", "name": "New Person"}).json()
    temp = r["temp_password"]
    n = signed_in("new@acme.test", temp)
    assert n.get("/api/chats").status_code == 403
    assert n.post("/api/account/password", json={"current": temp, "new": "my-own-pass"}).status_code == 200
    assert n.get("/api/chats").status_code == 200


def test_the_last_admin_stays(env):
    db, admin, member = env
    a = signed_in("ada@acme.test", "admin-pass-1")
    assert a.patch(f"/api/admin/users/{admin['id']}", json={"role": "member"}).status_code == 400
    assert a.patch(f"/api/admin/users/{member['id']}", json={"active": False}).status_code == 200
    c = TestClient(api.app)
    assert c.post("/api/auth/login", json={"email": "max@acme.test", "password": "member-pass-1"}).status_code == 400


def test_proposed_facts_carry_the_signed_in_name(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(api.facts, "propose", lambda st, text, kind, cites, by, *a: seen.setdefault("by", by) and "F-1")
    m = signed_in("max@acme.test", "member-pass-1")
    m.post("/api/facts", json={"text": "x", "kind": "behaviour", "cites": [], "by": "Someone Else"})
    assert seen["by"] == "Max Member <max@acme.test>"


def test_claude_secret_is_encrypted_and_per_person(env):
    db, admin, member = env
    st = Store(db)
    token = "sk-ant-oat01-" + "a" * 40
    auth.set_claude(st, member["id"], "subscription", token)
    raw = st.db.execute("SELECT secret, hint FROM user_claude").fetchone()
    assert token not in raw["secret"] and raw["hint"] == "…aaaa"
    e = auth.claude_env(st, member["id"], allow_shared=False)
    assert e["CLAUDE_CODE_OAUTH_TOKEN"] == token and member["id"] in e["CLAUDE_CONFIG_DIR"]
    with pytest.raises(auth.AuthError, match="Connect your Claude"):
        auth.claude_env(st, admin["id"], allow_shared=False)
    assert auth.claude_env(st, admin["id"], allow_shared=True) == {}
    with pytest.raises(auth.AuthError, match="subscriptions only"):
        auth.set_claude(st, admin["id"], "api_key", "sk-ant-api03-" + "k" * 40)
    with pytest.raises(auth.AuthError, match="subscriptions only"):     # a key pasted as a subscription
        auth.set_claude(st, admin["id"], "subscription", "sk-ant-api03-" + "k" * 40)
    st.close()


def test_chats_are_private(env):
    db, admin, member = env
    st = Store(db)
    chat._ensure_tables(st)
    st.db.execute("INSERT INTO chat (id, title, created_at, updated_at, user_id) VALUES ('c1','mine','t','t',?)",
                  (member["id"],))
    st.db.execute("INSERT INTO chat (id, title, created_at, updated_at, user_id) VALUES ('c0','old','t','t',NULL)")
    st.commit()
    st.close()
    m = signed_in("max@acme.test", "member-pass-1")
    assert [c["id"] for c in m.get("/api/chats").json()["chats"]] == ["c1"]
    assert m.get("/api/chats/c0").status_code == 404
    a = signed_in("ada@acme.test", "admin-pass-1")
    assert {c["id"] for c in a.get("/api/chats").json()["chats"]} == {"c0"}
    assert a.get("/api/chats/c1").status_code == 200


def test_usage_works_before_any_chat(env):
    a = signed_in("ada@acme.test", "admin-pass-1")
    rows = a.get("/api/admin/usage").json()["usage"]
    assert {r["name"] for r in rows} == {"Ada Admin", "Max Member"} and all(r["asked"] == 0 for r in rows)


def test_wrapped_token_is_joined(env):
    db, _, member = env
    st = Store(db)
    auth.set_claude(st, member["id"], "subscription", "sk-ant-oat01-" + "a" * 30 + " \n" + "b" * 30)
    assert auth.claude_env(st, member["id"], False)["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-" + "a" * 30 + "b" * 30
    st.close()


def test_each_person_picks_their_model(env):
    m = signed_in("max@acme.test", "member-pass-1")
    assert m.get("/api/models").json()["mine"] == ""
    assert m.put("/api/account/model", json={"model": "made-up"}).status_code == 400
    assert m.put("/api/account/model", json={"model": "claude-sonnet-5-5"}).status_code == 200
    assert m.get("/api/models").json()["mine"] == "claude-sonnet-5-5"
    cmd = chat.build_command(api.CFG, "q", None, chat.Person("Max", "u1", {}, "claude-sonnet-5-5"))
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    cmd = chat.build_command(api.CFG, "q", None, chat.Person("Max"))
    assert cmd[cmd.index("--model") + 1] == api.CFG.chat.model


def test_saved_searches_are_private_unless_shared(env):
    m = signed_in("max@acme.test", "member-pass-1")
    a = signed_in("ada@acme.test", "admin-pass-1")
    body = {"pick_file": "TRANSFER", "name": "Max's received", "criteria": {}}
    mine = m.post("/api/finder/scenarios", json=body).json()
    team = m.post("/api/finder/scenarios", json={**body, "name": "For everyone", "shared": True}).json()
    assert {s["name"] for s in m.get("/api/finder/scenarios").json()} == {"Max's received", "For everyone"}
    assert [s["name"] for s in a.get("/api/finder/scenarios").json()] == ["For everyone"]
    st = Store(env[0])
    st.db.execute("INSERT INTO finder_scenario (id, pick_file, name, criteria) VALUES ('old','TRANSFER','Before','{}')")
    st.commit()
    st.close()
    assert "Before" in {s["name"] for s in m.get("/api/finder/scenarios").json()}    # pre-sign-in ones stay visible
    assert m.put("/api/finder/scenarios/old", json=body).status_code == 403          # ...but only admins change them
    assert a.delete(f"/api/finder/scenarios/{mine['id']}").status_code == 404        # private: not even seen
    assert a.put(f"/api/finder/scenarios/{team['id']}", json=body).status_code == 200  # admins tidy shared ones
    u = signed_in("ada@acme.test", "admin-pass-1")
    assert u.delete(f"/api/finder/scenarios/{team['id']}").status_code == 200


def test_personal_jobs_and_looked_up_are_per_person(env, monkeypatch):
    import threading
    m = signed_in("max@acme.test", "member-pass-1")
    a = signed_in("ada@acme.test", "admin-pass-1")
    gate = threading.Event()
    monkeypatch.setattr(api, "_person", lambda st, request: chat.Person("Max"))
    monkeypatch.setattr(api.finder, "suggest", lambda *a, **k: (gate.wait(5), {"criteria": {}})[1])
    j = m.post("/api/jobs/finder-suggest", json={"pick_file": "TRANSFER", "description": "secret plan"}).json()
    try:
        assert any(x["id"] == j["id"] for x in m.get("/api/jobs").json()["jobs"])
        assert all(x["id"] != j["id"] for x in a.get("/api/jobs").json()["jobs"])
        assert a.get(f"/api/jobs/{j['id']}").status_code == 404
        assert a.post(f"/api/jobs/{j['id']}/cancel").status_code == 404
    finally:
        gate.set()
    m.get("/api/search", params={"q": "freight", "track": True})
    a.get("/api/search", params={"q": "invoices", "track": True})
    keys = lambda c: {x["key"] for x in c.get("/api/insights").json()["most_looked_up"]}  # noqa: E731
    assert keys(m) == {"freight"} and keys(a) == {"invoices"}


def test_an_api_key_in_the_server_environment_never_reaches_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-server")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "x")
    e = chat._env(chat.Person(env={"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-mine"}))
    assert "ANTHROPIC_API_KEY" not in e and "ANTHROPIC_AUTH_TOKEN" not in e
    assert e["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-mine"
    assert "ANTHROPIC_API_KEY" not in chat._env(None)            # the server's own login: subscription too


def test_pdf_export_renders_signed_in_as_the_asker(env, monkeypatch, tmp_path):
    from atlas import reports
    db, admin, member = env
    seen = {}

    def fake_render(page, title, sha, env_, out, timeout_s=90, session=None):
        st = Store(db)
        seen["user"] = (auth.session_user(st, session) or {}).get("email")
        st.close()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4")
        return 1
    monkeypatch.setattr(reports, "render_pdf", fake_render)
    monkeypatch.setattr(reports, "REPORT_DIR", tmp_path / "reports")
    m = signed_in("max@acme.test", "member-pass-1")
    r = m.post("/api/reports", json={"page": "/program/W4DEMO", "title": "Demo"}).json()
    assert seen["user"] == "max@acme.test"                       # the browser was signed in as Max...
    st = Store(db)
    assert st.db.execute("SELECT COUNT(*) n FROM app_session WHERE user_id=?", (member["id"],)).fetchone()["n"] == 1
    st.close()                                                   # ...and that sign-in is gone again
    a = signed_in("ada@acme.test", "admin-pass-1")
    assert [x["id"] for x in m.get("/api/reports").json()] == [r["id"]]
    assert a.get("/api/reports").json() == []                    # Ada's list holds only her own PDFs
    assert a.get(f"/api/reports/{r['id']}/pdf").status_code == 200   # but the shared link opens


def test_overview_shows_only_your_own_questions_and_views(env):
    db, admin, member = env
    st = Store(db)
    chat._ensure_tables(st)
    st.db.execute("INSERT INTO chat (id, title, created_at, updated_at, user_id) VALUES "
                  "('c1','Max asks about freight','t','t',?)", (member["id"],))
    st.commit()
    st.close()
    m = signed_in("max@acme.test", "member-pass-1")
    a = signed_in("ada@acme.test", "admin-pass-1")
    m.get("/api/program/W4NOPE", params={"track": True})
    assert [q["question"] for q in m.get("/api/dashboard").json()["questions"]] == ["Max asks about freight"]
    d = a.get("/api/dashboard").json()
    assert d["questions"] == [] and d["recent"] == []


def test_needs_you_differs_for_admins_and_members(env):
    from atlas import dashboard
    db, admin, member = env
    st = Store(db)
    st.db.execute("INSERT INTO fact (id, text, kind, status, proposed_by, created_at, updated_at) VALUES "
                  "('F-0001','x','rule','proposed','Ask Atlas','t','t'), "
                  "('F-0002','y','rule','stale','Ask Atlas','t','t')")
    st.db.execute("INSERT INTO finder_scenario (id, pick_file, name, criteria, user_id, last_count) "
                  "VALUES ('s1','TRANSFER','Received','{}',?,0)", (member["id"],))
    st.commit()
    a = {i["title"] for i in dashboard.needs_you(st, admin, allow_shared_claude=False)}
    m = {i["title"] for i in dashboard.needs_you(st, member, allow_shared_claude=False)}
    assert "1 fact went stale" in a and "1 fact waiting for review" in a and "Connect your Claude" in a
    assert not any("fact" in t for t in m)                         # reviewing facts is an admin's job
    assert "“Received” found nothing last time" in m and "Connect your Claude" in m
    assert "Connect your Claude" not in {i["title"] for i in dashboard.needs_you(st, member, allow_shared_claude=True)}
    items = dashboard.needs_you(st, admin, False)
    assert items[0]["level"] == "high"                             # most pressing first
    st.close()


def test_changes_you_care_about(env):
    from atlas import dashboard
    from atlas.parse.program import parse_program
    db, admin, member = env
    st = Store(db)
    lines = ["      SUBROUTINE W4RCV", "      XF<10> = DATE()", "      WRITE XF ON F, K", "      RETURN"]
    st.put_program("git", parse_program("W4RCV", lines), st.put_source("git", "BP", "W4RCV", "p", "\n".join(lines)))
    st.db.execute("INSERT INTO dict_attr (pick_file, name, type, attr) VALUES ('TRANSFER','REQUIRED','A',10)")
    st.db.execute("INSERT INTO attr_ref VALUES ('git','W4RCV',2,'XF','TRANSFER',10,NULL,'write')")
    st.db.execute("INSERT INTO finder_scenario (id, pick_file, name, criteria, user_id) VALUES "
                  "('s1','TRANSFER','Due soon',?,?)", (json.dumps({"query": 'WITH REQUIRED GE "1"'}), member["id"]))
    st.db.execute("INSERT INTO activity (kind, key, at, user_id) VALUES ('program','W4OTHER','t',?)", (member["id"],))
    st.commit()
    why = dashboard._yours(st, member["id"])
    assert why["W4OTHER"] == "you looked at it"
    assert "your scenario “Due soon”" in why["W4RCV"]
    assert dashboard._yours(st, admin["id"]) == {}
    assert dashboard._last_looked(st, member["id"]) is None        # first visit
    assert dashboard._last_looked(st, member["id"]) is None        # a refresh doesn't move it
    st.close()


def test_fact_review_queue_shows_what_changed(env):
    db, admin, member = env
    st = Store(db)
    lines = ["      SUBROUTINE W4X", "      A = 2", "      RETURN"]
    st.put_source("git", "BP", "W4X", "p", "\n".join(lines))
    st.db.execute("INSERT INTO fact (id, text, kind, status, proposed_by, created_at, updated_at) "
                  "VALUES ('F-0009','A is one','rule','stale','Ask Atlas','t','t')")
    st.db.execute("INSERT INTO fact_cite VALUES ('F-0009','git','W4X',2,'      A = 1','h','')")
    st.commit()
    st.close()
    a = signed_in("ada@acme.test", "admin-pass-1")
    c = a.get("/api/facts/review").json()["stale"][0]["cites"][0]
    assert c["changed"] and c["line_text"].strip() == "A = 1" and c["now_text"].strip() == "A = 2"


def test_repeated_wrong_passwords_lock_the_account_for_a_while(env):
    c = TestClient(api.app)
    for _ in range(auth.MAX_FAILS_EMAIL):
        assert c.post("/api/auth/login", json={"email": "max@acme.test", "password": "nope-nope"}).status_code == 400
    r = c.post("/api/auth/login", json={"email": "max@acme.test", "password": "member-pass-1"})
    assert r.status_code == 400 and "Too many" in r.json()["detail"]          # even the right password waits
    assert c.post("/api/auth/login", json={"email": "ada@acme.test", "password": "admin-pass-1"}).status_code == 200


def test_cookie_is_secure_over_https(env):
    c = TestClient(api.app)
    r = c.post("/api/auth/login", json={"email": "ada@acme.test", "password": "admin-pass-1"},
               headers={"x-forwarded-proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()
