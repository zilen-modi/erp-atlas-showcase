"""The Overview page: what a developer on the migration needs when they open Atlas --
their work in progress (compare runs, open issues, recent pages, reports) and what
changed in the legacy code, ranked by how much of the business it touches."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from atlas import compare, insights, profile, query, reports
from atlas.config import Config
from atlas.store.db import Store, now

Result = dict[str, Any]
LABEL = {"job": "Job", "report": "Report", "screen": "Screen", "program": "Program", "field": "Field",
         "file": "File", "menu": "Menu", "flow": "Flow", "search": "Search"}


def recent_pages(store: Store, limit: int = 8, user_id: str | None = None) -> list[Result]:
    mine = " AND user_id = ?" if user_id else ""
    rows = store.db.execute(
        "SELECT kind, key, MAX(at) last, COUNT(*) n FROM activity WHERE kind != 'search'" + mine
        + " GROUP BY kind, key ORDER BY last DESC LIMIT ?", (*([user_id] if user_id else []), limit)).fetchall()
    return [{"kind": r["kind"], "label": LABEL.get(r["kind"], r["kind"]), "key": r["key"], "at": r["last"],
             "views": r["n"], "href": insights.href(r["kind"], r["key"])} for r in rows]


def _latest_step(store: Store, run_id: str) -> Any:
    return store.db.execute(
        "SELECT s.id, s.name, s.seq, MAX(x.fetched_at) at FROM cmp_snapshot x JOIN cmp_step s ON s.id = x.step_id "
        "WHERE x.run_id=? GROUP BY s.id ORDER BY s.seq DESC LIMIT 1", (run_id,)).fetchone()


def recent_runs(store: Store, limit: int = 5) -> list[Result]:
    out = []
    for r in store.db.execute(
            "SELECT r.*, f.name flow_name, (SELECT COUNT(*) FROM cmp_step s WHERE s.flow_id=r.flow_id) steps "
            "FROM cmp_run r JOIN cmp_flow f ON f.id = r.flow_id ORDER BY r.updated_at DESC LIMIT ?", (limit,)):
        captured = store.db.execute("SELECT COUNT(DISTINCT step_id) n FROM cmp_snapshot WHERE run_id=?",
                                    (r["id"],)).fetchone()["n"]
        step = _latest_step(store, r["id"])
        diffs = explained = missing = None
        if step is not None:
            d = compare.diff(store, r["id"], step["id"])
            diffs = sum(f["differences"] for f in d["files"])
            explained = sum(f["explained"] for f in d["files"])
            missing = sum(1 for f in d["files"] if f["old"] and f["new"] and not f["old"]["found"]
                          and not f["new"]["found"])
        notes = {n["verdict"]: n["c"] for n in store.db.execute(
            "SELECT verdict, COUNT(*) c FROM cmp_note WHERE run_id=? OR (run_id IS NULL AND flow_id=?) "
            "GROUP BY verdict", (r["id"], r["flow_id"]))}
        out.append({"id": r["id"], "name": r["name"], "flow": r["flow_name"], "flow_id": r["flow_id"],
                    "updated_at": r["updated_at"], "steps": r["steps"], "captured_steps": captured,
                    "step": step["name"] if step else None, "differences": diffs, "explained": explained,
                    "files_not_found": missing, "bugs": notes.get("bug", 0), "questions": notes.get("question", 0)})
    return out


def open_issues(store: Store, limit: int = 8) -> Result:
    """Compare notes still needing someone: marked bug or question (not expected / fixed)."""
    total = store.db.execute("SELECT COUNT(*) n FROM cmp_note WHERE verdict IN ('bug','question')").fetchone()["n"]
    rows = store.db.execute(
        "SELECT n.*, f.name flow_name, r.name run_name FROM cmp_note n LEFT JOIN cmp_flow f ON f.id = n.flow_id "
        "LEFT JOIN cmp_run r ON r.id = n.run_id WHERE n.verdict IN ('bug','question') "
        "ORDER BY n.verdict = 'bug' DESC, n.updated_at DESC LIMIT ?", (limit,)).fetchall()
    items = []
    for n in rows:
        names = [x["name"] for x in store.db.execute(
            "SELECT name FROM dict_attr WHERE pick_file=? AND attr=? LIMIT 2", (n["pick_file"], n["attr"]))]
        run_id = n["run_id"] or (store.db.execute("SELECT id FROM cmp_run WHERE flow_id=? ORDER BY updated_at DESC "
                                                  "LIMIT 1", (n["flow_id"],)).fetchone() or {"id": None})["id"]
        items.append({"id": n["id"], "verdict": n["verdict"], "text": n["text"], "pick_file": n["pick_file"],
                      "attr": n["attr"], "names": names, "flow": n["flow_name"], "run": n["run_name"],
                      "href": f"/compare/runs/{run_id}" if run_id else f"/compare/flows/{n['flow_id']}",
                      "at": n["updated_at"] or n["created_at"], "author": n["author"]})
    return {"total": total, "items": items}


def commits_with_impact(store: Store, cfg: Config, limit: int = 6, scan: int | None = None) -> list[Result]:
    """Recent legacy commits, each program marked with how many menu launches reach it
    and whether TEST runs a different version -- so the ones that matter stand out."""
    usage = query.usage_map(store)
    drifted = {r["program"] for r in store.db.execute(
        "SELECT DISTINCT program FROM drift WHERE class IN ('logic','git-only','live-only')")}
    out = []
    for c in insights.whats_new(store, cfg, commits=scan or limit * 2, keep_files=True)["commits"]:
        if not c["changed"]:
            continue                      # merge commits: the work is shown by the commits they bring in
        files = [{"name": f, "launches": usage.get(f), "test_differs": f in drifted} for f in c["all_files"][:6]]
        files.sort(key=lambda f: -(f["launches"] or 0))
        out.append({**c, "files": files, "impact": max((f["launches"] or 0 for f in files), default=0)})
    return out[:limit]


def recent_questions(store: Store, limit: int = 4, user_id: str | None = None) -> list[Result]:
    """This person's latest chats (chats are private: nobody else's questions show here)."""
    if user_id and "user_id" not in {r["name"] for r in store.db.execute("PRAGMA table_info(chat)")}:
        return []
    mine = " WHERE user_id = ?" if user_id else ""
    return [{"question": r["title"], "at": r["updated_at"], "chat_id": r["id"]} for r in store.db.execute(
        f"SELECT id, title, updated_at FROM chat{mine} ORDER BY updated_at DESC LIMIT ?",
        (*([user_id] if user_id else []), limit))]



# ------------------------------------------------------------------ what needs this person

def needs_you(store: Store, user: Result | None, allow_shared_claude: bool) -> list[Result]:
    """Things waiting on this person, most pressing first, each with where to deal with it."""
    from atlas import auth, knowledge
    items: list[Result] = []

    def add(level: str, title: str, detail: str, href: str, action: str = "") -> None:
        items.append({"level": level, "title": title, "detail": detail, "href": href, "action": action})

    uid = user["id"] if user else None
    admin = user is None or user.get("role") == "admin"
    if uid and not allow_shared_claude and not auth.get_claude(store, uid):
        add("high", "Connect your Claude", "Ask Atlas and “Describe the record you need” run on your own Claude "
            "subscription.", "/account")
    if admin:
        n = {r["status"]: r["n"] for r in store.db.execute("SELECT status, COUNT(*) n FROM fact GROUP BY status")}
        if n.get("stale"):
            add("high", f"{n['stale']} fact{'s' if n['stale'] != 1 else ''} went stale",
                "The code they cite has changed. Re-cite each one if it still holds, or retire it.", "/facts?tab=stale")
        if n.get("proposed"):
            add("normal", f"{n['proposed']} fact{'s' if n['proposed'] != 1 else ''} waiting for review",
                f"Proposed by Ask Atlas and others; {n.get('accepted', 0)} confirmed so far. Confirmed facts are what "
                "Ask Atlas can state without caveats.", "/facts?tab=proposed")
        st = store.get_state("git:erp")
        if st is not None:
            days = (datetime.now(UTC) - datetime.fromisoformat(st["synced_at"])).days
            if days >= 3:
                add("high" if days >= 7 else "normal", f"Last synced with git {days} days ago",
                    "Programs, facts and summaries may be behind the code.", "/", "sync")
        cov = knowledge.coverage(store)
        if cov["stale"]:
            add("normal", f"{cov['stale']} summar{'ies' if cov['stale'] != 1 else 'y'} out of date",
                "Their programs changed in git. The next summaries run rewrites them.", "/admin#knowledge")
        waiting = store.db.execute("SELECT COUNT(*) n FROM app_user WHERE must_change=1 AND active=1").fetchone()["n"]
        if waiting:
            add("normal", f"{waiting} {'people have' if waiting != 1 else 'person has'} not signed in yet",
                "They still have the one-time password you gave them.", "/admin")
    if uid:
        for s in store.db.execute("SELECT id, name, pick_file FROM finder_scenario WHERE user_id=? AND last_count=0 "
                                  "ORDER BY updated_at DESC LIMIT 3", (uid,)):
            add("normal", f"“{s['name']}” found nothing last time",
                f"No {s['pick_file']} record on TEST fits it any more. Run it again, or loosen it.",
                f"/test-data?scenario={s['id']}")
        mine = store.db.execute("SELECT COUNT(*) n FROM cmp_note WHERE verdict IN ('bug','question') AND author=?",
                                (auth.fingerprint(user),)).fetchone()["n"]
        if mine:
            add("normal", f"{mine} Compare issue{'s' if mine != 1 else ''} you raised still open",
                "Marked bug or question; set them to expected or fixed when they're resolved.", "#issues")
    items.sort(key=lambda i: i["level"] != "high")
    return items


# ------------------------------------------------------------------ what changed since this person last looked

def _last_looked(store: Store, uid: str | None) -> str | None:
    """When this person last opened the Overview, not counting the last hour (so a refresh doesn't reset it)."""
    if not uid:
        return None
    from atlas import auth
    seen, prev = auth.get_pref(store, uid, "overview_seen"), auth.get_pref(store, uid, "overview_prev")
    t = now()
    if seen is None or (datetime.fromisoformat(t) - datetime.fromisoformat(seen)).total_seconds() > 3600:
        prev = seen
        auth.set_pref(store, uid, "overview_prev", prev)
    auth.set_pref(store, uid, "overview_seen", t)
    return prev


def _yours(store: Store, uid: str) -> dict[str, str]:
    """Programs this person has reason to care about, and why: viewed them, or they write a field you looked at
    or search on in a saved scenario."""
    why: dict[str, str] = {}
    for r in store.db.execute("SELECT DISTINCT key FROM activity WHERE user_id=? AND kind='program'", (uid,)):
        why.setdefault(r["key"], "you looked at it")
    fields: dict[tuple[str, int], str] = {}
    for r in store.db.execute("SELECT DISTINCT key FROM activity WHERE user_id=? AND kind='field'", (uid,)):
        m = insights._FIELD.match(r["key"])
        if m:
            fields[(m.group(1), int(m.group(2)))] = f"writes {r['key']}, which you looked at"
    from atlas import finder_eval
    for s in store.db.execute("SELECT name, pick_file, criteria FROM finder_scenario WHERE user_id=?", (uid,)):
        q = (json.loads(s["criteria"]) or {}).get("query", "")
        for c in finder_eval.conditions(store, s["pick_file"], q):
            if c["attr"] is not None:
                fields.setdefault((s["pick_file"], c["attr"]),
                                  f"writes {s['pick_file']}<{c['attr']}>, used by your scenario “{s['name']}”")
    for (f, a), reason in fields.items():
        for r in store.db.execute("SELECT DISTINCT program FROM attr_ref WHERE provenance='git' AND pick_file=? "
                                  "AND attr=? AND access='write'", (f, a)):
            why.setdefault(r["program"], reason)
    return why


def changed_since(store: Store, cfg: Config, uid: str | None) -> Result:
    """Legacy commits since this person last looked; the programs they care about first, each with what it does."""
    since = _last_looked(store, uid)
    cutoff = (since or (datetime.now(UTC) - timedelta(days=14)).isoformat())[:10]
    commits = [c for c in commits_with_impact(store, cfg, limit=40, scan=80) if c["date"] >= cutoff]
    yours = _yours(store, uid) if uid else {}
    titles = {r["program"]: r["title"] for r in store.db.execute(
        "SELECT program, title FROM summary WHERE kind='program'")}
    mine: dict[str, Result] = {}
    for c in commits:
        for f in c["all_files"]:
            if f in yours and f not in mine:
                mine[f] = {"program": f, "why": yours[f], "summary": titles.get(f), "sha": c["sha"],
                           "commit": c["summary"], "author": c["author"], "date": c["date"]}
    return {"since": since, "cutoff": cutoff, "commits": commits[:8], "total": len(commits),
            "yours": list(mine.values())[:10], "tracking": len(yours)}


# ------------------------------------------------------------------ this person's own work

def your_work(store: Store, uid: str | None) -> Result:
    scen = [] if not uid else [
        {**dict(r), "shared": bool(r["shared"])} for r in store.db.execute(
            "SELECT id, name, pick_file, last_count, last_run, shared FROM finder_scenario WHERE user_id=? "
            "ORDER BY COALESCE(last_run, updated_at) DESC LIMIT 5", (uid,))]
    return {"scenarios": scen, "chats": recent_questions(store, 5, uid), "reports": reports.list_all(store, 4, uid)}


def knowledge_stats(store: Store) -> Result:
    f = {r["status"]: r["n"] for r in store.db.execute("SELECT status, COUNT(*) n FROM fact GROUP BY status")}
    return {"facts_confirmed": f.get("accepted", 0), "facts_open": f.get("proposed", 0) + f.get("stale", 0)}


def overview(store: Store, cfg: Config, user: Result | None = None, allow_shared_claude: bool = False) -> Result:
    user_id = user["id"] if user else None
    st = query.status(store)
    issues = open_issues(store)
    deploy = query.drift_overview(store)
    runs = store.db.execute("SELECT COUNT(*) n FROM cmp_run").fetchone()["n"]
    flows = store.db.execute("SELECT COUNT(*) n FROM cmp_flow").fetchone()["n"]
    return {
        "stats": {
            "programs": st["programs"].get("git", 0), "flows": flows, "runs": runs, "open_issues": issues["total"],
            "reports": store.db.execute("SELECT COUNT(*) n FROM report").fetchone()["n"],
            "test_checked": len(deploy["programs"]), "test_differs": deploy["totals"].get("drift", 0),
            "answers": st.get("answers", 0), **knowledge_stats(store),
        },
        "needs_you": needs_you(store, user, allow_shared_claude),
        "changed": changed_since(store, cfg, user_id),
        "work": your_work(store, user_id),
        "runs": recent_runs(store),
        "issues": issues,
        "recent": recent_pages(store, user_id=user_id),
        "reports": reports.list_all(store, 4, user_id),
        "quality": profile.overview(store)[:5],
        "ideas": insights.ideas(store, 4),
        "questions": recent_questions(store, user_id=user_id),
    }
