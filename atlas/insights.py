"""Overview insights: what people look up, ideas worth asking, and what's new.

Activity is recorded locally when someone opens a program/field/file/menu/flow
page or runs a full search (typeahead suggestions are not counted).
"""

from __future__ import annotations

import re
from typing import Any

from atlas.config import Config
from atlas.parse.program import is_gui_callee
from atlas.query import usage_map
from atlas.sources.git_src import GitMirror
from atlas.store.db import Store, now

KINDS = {"program", "field", "file", "menu", "flow", "search"}
_FIELD = re.compile(r"^([A-Z0-9][A-Z0-9.\-/]*)<(\d+)>$")


def track(store: Store, kind: str, key: str, user_id: str | None = None) -> None:
    key = key.strip()
    if kind not in KINDS or not key or len(key) > 200:
        return
    store.db.execute("INSERT INTO activity (kind, key, at, user_id) VALUES (?,?,?,?)",
                     (kind, key if kind == "search" else key.upper(), now(), user_id))
    store.commit()


def href(kind: str, key: str) -> str:
    if kind == "program":
        return f"/program/{key}"
    if kind == "menu":
        return f"/menu/{key}"
    if kind == "file":
        return f"/files/{key}"
    if kind == "flow":
        return f"/flow/{key}"
    if kind == "screen":
        return f"/screen/{key}"
    if kind == "job":
        return f"/jobs/{key}"
    if kind == "report":
        return f"/legacy-reports/{key}"
    if kind == "field":
        m = _FIELD.match(key)
        return f"/field/{m.group(1)}/{m.group(2)}" if m else f"/search?q={key}"
    return f"/search?q={key}"


def most_looked_up(store: Store, limit: int = 10, days: int = 30, user_id: str | None = None) -> list[dict[str, Any]]:
    """What this person looks up most (everyone's, when there's no sign-in). Their own chat questions count too;
    nobody else's questions are ever shown."""
    mine = " AND user_id = ?" if user_id else ""
    rows = store.db.execute(
        "SELECT kind, key, COUNT(*) n, MAX(at) last FROM activity WHERE at >= datetime('now', ?)" + mine
        + " GROUP BY kind, key ORDER BY n DESC, last DESC LIMIT ?",
        (f"-{days} days", *([user_id] if user_id else []), limit)).fetchall()
    out = [{"kind": r["kind"], "key": r["key"], "count": r["n"], "last": r["last"],
            "href": href(r["kind"], r["key"])} for r in rows]
    # questions asked in chat count as lookups too
    asked = ("SELECT t.question, COUNT(*) n, MAX(t.created_at) last FROM chat_turn t JOIN chat c ON c.id = t.chat_id "
             "WHERE c.user_id = ? GROUP BY lower(t.question) ORDER BY n DESC, last DESC LIMIT 5") if user_id else (
             "SELECT question, COUNT(*) n, MAX(created_at) last FROM answer "
             "GROUP BY lower(question) ORDER BY n DESC, last DESC LIMIT 5")
    has_chat = "user_id" in {r["name"] for r in store.db.execute("PRAGMA table_info(chat)")}   # made on first chat
    for r in (store.db.execute(asked, (user_id,)) if user_id and has_chat else
              [] if user_id else store.db.execute(asked)):
        if r["n"] > 1:
            out.append({"kind": "question", "key": r["question"], "count": r["n"], "last": r["last"],
                        "href": f"/ask?q={r['question']}"})
    out.sort(key=lambda x: x["last"], reverse=True)       # newest first within equal counts...
    out.sort(key=lambda x: x["count"], reverse=True)      # ...then by count (stable sort keeps the tie order)
    return out[:limit]


def _asked_about(store: Store) -> str:
    return " ".join(r["question"].upper() for r in store.db.execute("SELECT question FROM answer"))


def ideas(store: Store, limit: int = 6) -> list[dict[str, Any]]:
    """Questions worth asking, generated from the data -- things nobody has asked about yet."""
    asked = _asked_about(store)
    known_facts = " ".join(str(r["scope"] or "").upper() + " " + r["text"].upper()
                           for r in store.db.execute("SELECT scope, text FROM fact WHERE status != 'retired'"))
    out: list[dict[str, Any]] = []

    # 1. undocumented attributes in the most-opened files, most-written first
    files = [r["pick_file"] for r in store.db.execute(
        "SELECT pick_file, COUNT(DISTINCT program) n FROM file_handle WHERE provenance='git' "
        "GROUP BY pick_file ORDER BY n DESC LIMIT 12")]
    for f in files:
        named = {r["attr"] for r in store.db.execute(
            "SELECT DISTINCT attr FROM dict_attr WHERE pick_file=? AND type IN ('A','D')", (f,))}
        row = store.db.execute(
            "SELECT attr, COUNT(DISTINCT program) n FROM attr_ref WHERE provenance='git' AND pick_file=? "
            "AND access='write' AND attr > 0 GROUP BY attr ORDER BY n DESC LIMIT 20", (f,)).fetchall()
        for r in row:
            tag = f"{f}<{r['attr']}>"
            if r["attr"] not in named and tag not in asked and tag not in known_facts:
                out.append({"kind": "field", "title": f"What is {tag}?",
                            "why": f"{r['n']} programs write it, but DICT {f} doesn't name it",
                            "question": f"What is {tag} and who writes it? DICT doesn't name it.",
                            "href": f"/field/{f}/{r['attr']}"})
                break
        if len(out) >= 3:
            break

    # 2. the busiest menus nobody has asked about
    for r in store.db.execute("SELECT code, program, used FROM menu WHERE program IS NOT NULL ORDER BY used DESC "
                              "LIMIT 40"):
        if r["code"] in asked or r["program"] in asked or is_gui_callee(r["program"]):
            continue
        out.append({"kind": "menu", "title": f"How does {r['code']} ({r['program']}) work?",
                    "why": f"{r['used']:,} launches, not explored yet",
                    "question": f"Walk me through menu {r['code']} ({r['program']}) end to end: what the user does, "
                                f"the main steps, and which files are read and written.",
                    "href": f"/flow/{r['code']}"})
        if len(out) >= limit - 1:
            break

    # 3. drift that matters: a heavily used program that TEST runs differently
    usage = usage_map(store)
    diff = [r["program"] for r in store.db.execute(
        "SELECT DISTINCT program FROM drift WHERE class IN ('logic','git-only','live-only')")]
    diff.sort(key=lambda p: -(usage.get(p) or 0))
    for p in diff:
        if f"MAIN OF {p} WERE DEPLOYED" not in asked:
            out.append({"kind": "deployment", "title": f"Is {p} safe to deploy to TEST?",
                        "why": "TEST runs an older version of this program",
                        "question": f"What behaviour would change on TEST if git main of {p} were deployed there? "
                                    f"Summarise the differences that matter to users.",
                        "href": f"/drift/{p}"})
            break
    return out[:limit]


def whats_new(store: Store, cfg: Config, commits: int = 6, keep_files: bool = False) -> dict[str, Any]:
    g = cfg.git
    try:
        recent = GitMirror(g.mirror, g.origin, g.local_fallback, g.branch).recent_commits(
            f"refs/heads/{g.branch}", ["src/BP", "src/MENU-ITEMS", "src/DICT"], commits)
    except Exception:
        recent = []
    for c in recent:
        files = c["files"]
        assert isinstance(files, list)
        c["changed"] = len(files)
        if keep_files:
            c["all_files"] = list(files)
        c["files"] = files[:6]
    learned = [{"id": r["id"], "text": r["text"], "scope": r["scope"], "status": r["status"], "at": r["created_at"]}
               for r in store.db.execute("SELECT id, text, scope, status, created_at FROM fact "
                                         "WHERE status != 'retired' ORDER BY created_at DESC LIMIT 5")]
    return {"commits": recent, "learned": learned}      # questions are private to their asker: never listed here
