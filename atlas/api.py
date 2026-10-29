"""HTTP API for the web UI (`atlas serve`).  Binds to 127.0.0.1 only.

Thin wrapper over atlas.query / atlas.memory.facts / atlas.sync -- the UI, CLI
and MCP server all give the same answers.  Slow work (git sync, live fetches)
runs as background jobs so a request never blocks on the TEST server.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import subprocess
import threading
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from atlas import (
    ask_eval,
    auth,
    chat,
    compare,
    dashboard,
    dictmodel,
    erpnext,
    finder,
    insights,
    knowledge,
    legacy,
    network,
    process,
    profile,
    query,
    reports,
    screens,
    semantic,
    suggest,
    sync,
    trace,
)
from atlas import config as cfgmod
from atlas.memory import facts
from atlas.store.db import Store

app = FastAPI(title="ERP Atlas", version="0.1.0")
CFG = cfgmod.load()
# Sign-in is always on; ATLAS_AUTH=off exists only so the unit tests can call endpoints directly.
AUTH = os.environ.get("ATLAS_AUTH", "on") != "off"


@contextmanager
def store() -> Iterator[Store]:
    st = Store(CFG.store)          # one connection per request: sqlite objects are thread-bound
    try:
        yield st
    finally:
        st.close()


def _q(fn: Callable[..., Any], *args: Any) -> Any:
    with store() as st:
        return fn(st, *args)


# ------------------------------------------------------------------ who's asking

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/state", "/api/auth/logout"}
# the first password change is the one thing an account with a temporary password may do
FIRST_PASSWORD = {"/api/auth/me", "/api/account/password"}
ADMIN_ONLY: list[tuple[str, re.Pattern[str]]] = [
    ("*", re.compile(r"^/api/admin/")),
    ("PUT", re.compile(r"^/api/settings")), ("POST", re.compile(r"^/api/settings")),
    ("POST", re.compile(r"^/api/facts/[^/]+/(accept|retire|recite)$")),
    ("POST", re.compile(r"^/api/facts/check-stale$")),
    ("POST", re.compile(r"^/api/jobs/sync$")),
    ("POST", re.compile(r"^/api/jobs/(summaries|embed|ask-eval)$")),
    ("*", re.compile(r"^/api/eval/")),
]


@app.middleware("http")
async def require_user(request: Request, call_next: Callable[[Request], Any]) -> Any:
    """Every /api call needs a signed-in person; a few need an admin."""
    path = request.url.path
    request.state.user = None
    if not AUTH or not path.startswith("/api/") or path in PUBLIC:
        return await call_next(request)
    token = request.cookies.get(auth.COOKIE)
    head = request.headers.get("authorization", "")
    if head.lower().startswith("bearer "):
        token = head[7:].strip()
    with store() as st:
        user = auth.session_user(st, token)
    if user is None:
        return JSONResponse({"detail": "Sign in to use Atlas"}, status_code=401)
    if user["must_change"] and path not in FIRST_PASSWORD:
        return JSONResponse({"detail": "Choose your own password first"}, status_code=403)
    if user["role"] != "admin" and any((m == "*" or m == request.method) and rx.search(path) for m, rx in ADMIN_ONLY):
        return JSONResponse({"detail": "Only an admin can do that"}, status_code=403)
    request.state.user = user
    CURRENT_USER.set(user)
    return await call_next(request)


# The signed-in person for code that has no request in hand (background jobs, activity tracking).
CURRENT_USER: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("atlas_user", default=None)


def _me(request: Request) -> dict[str, Any] | None:
    user: dict[str, Any] | None = getattr(request.state, "user", None)
    return user


def _who(request: Request, typed: str = "") -> str:
    """The name on a fact, a review or a piece of feedback: the signed-in person, never a typed name."""
    u = _me(request)
    return auth.fingerprint(u) if u else typed


def _person(st: Store, request: Request) -> chat.Person:
    """Run Claude as the signed-in person: their own Claude, or the server's if an admin allows that."""
    u = _me(request)
    if u is None:
        return chat.Person()
    return chat.Person(u["name"], u["id"], auth.claude_env(st, u["id"], cfgmod.allow_shared_claude()),
                       auth.get_pref(st, u["id"], "model") or "")


# ------------------------------------------------------------------ read

_HEALTH: dict[str, Any] = {"at": 0.0, "value": None}


def _is_local(url: str | None = None) -> bool:
    """A python layer on this machine reaches UniVerse through this machine's VPN;
    a remote one (e.g. the QA server) has its own route, so the local VPN doesn't matter."""
    from urllib.parse import urlparse
    host = (urlparse(url or CFG.live.base_url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "host.docker.internal") or host.endswith(".localhost")


def _probe_python_layer(url: str | None = None) -> dict[str, Any]:
    """GET <base>/table with no arguments: the python layer answers 422 'table_name required'
    at once, which proves the URL is the python layer without reading any data."""
    import time

    import httpx
    base = (url or CFG.live.base_url).rstrip("/")
    t = time.monotonic()
    try:
        r = httpx.get(f"{base}/table", timeout=10.0, follow_redirects=True)
    except httpx.HTTPError as e:
        return {"ok": False, "error": type(e).__name__, "url": base}
    ms = round((time.monotonic() - t) * 1000)
    try:
        body = r.json()
    except ValueError:
        body = None
    looks_right = r.status_code == 422 and "table_name" in json.dumps(body)
    if looks_right or r.status_code == 200:
        return {"ok": True, "ms": ms, "url": base}
    return {"ok": False, "ms": ms, "url": base,
            "error": f"HTTP {r.status_code}: this URL doesn't look like the python layer's API (expected .../v1)"}


def _probe_universe(host: str | None = None, port: int | None = None) -> dict[str, Any]:
    import socket
    import time
    host, port = host or CFG.live.universe_host, port or CFG.live.universe_port
    t = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return {"ok": True, "ms": round((time.monotonic() - t) * 1000), "host": f"{host}:{port}"}
    except OSError as e:
        return {"ok": False, "error": type(e).__name__, "host": f"{host}:{port}"}


@app.get("/api/health")
def health(fresh: bool = False) -> Any:
    """Is the python layer up, and is UniVerse reachable (i.e. the VPN is connected)? Cached 10 s."""
    import time
    if fresh or _HEALTH["value"] is None or time.monotonic() - _HEALTH["at"] > 10:
        _HEALTH["value"] = {"api": {"ok": True}, "python_layer": _probe_python_layer(),
                            "universe": _probe_universe(), "vpn_required": _is_local(),
                            "environment": CFG.environment,
                            "checked_at": datetime.now(UTC).isoformat(timespec="seconds")}
        _HEALTH["at"] = time.monotonic()
    return _HEALTH["value"]


def _vpn_preflight() -> None:
    """Fail fast when a local python layer can't reach UniVerse (VPN down)."""
    if _is_local() and not _probe_universe()["ok"]:
        raise HTTPException(503, f"VPN is not connected: UniVerse {CFG.live.universe_host}:{CFG.live.universe_port} "
                                 f"isn't reachable. Connect the VPN and try again.")


# ------------------------------------------------------------------ settings

class SettingsBody(BaseModel):
    python_layer_url: str = ""
    universe_host: str = ""
    universe_port: int | str | None = None


def _settings_view() -> dict[str, Any]:
    lv = cfgmod.policy_live()
    return {
        "values": {"python_layer_url": CFG.live.base_url, "universe_host": CFG.live.universe_host,
                   "universe_port": CFG.live.universe_port},
        "defaults": {"python_layer_url": lv["base_url"], "universe_host": lv.get("universe_host", ""),
                     "universe_port": lv.get("universe_port")},
        "saved": cfgmod.read_settings(),
        "env_override": bool(os.environ.get("UNIVERSE_API_URL")),
        "file": str(cfgmod.settings_path()),
    }


def _checked(body: SettingsBody) -> dict[str, Any]:
    try:
        return cfgmod.normalise_settings(body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.get("/api/settings")
def get_settings() -> Any:
    return _settings_view()


class NavBody(BaseModel):
    hidden: list[str] = []


@app.get("/api/settings/nav")
def nav_get() -> Any:
    """Sidebar tabs hidden for everyone using this Atlas (pages still open by link)."""
    return {"hidden": cfgmod.hidden_tabs()}


@app.put("/api/settings/nav")
def nav_put(body: NavBody) -> Any:
    return {"hidden": cfgmod.save_hidden_tabs(body.hidden)}


@app.post("/api/settings/test")
def test_settings(body: SettingsBody) -> Any:
    """Probe the given connection without saving it."""
    v = {**_settings_view()["values"], **_checked(body)}
    return {"python_layer": _probe_python_layer(v["python_layer_url"]),
            "universe": _probe_universe(v["universe_host"], int(v["universe_port"])),
            "vpn_required": _is_local(v["python_layer_url"])}


@app.put("/api/settings")
def put_settings(body: SettingsBody) -> Any:
    """Save connection settings and apply them at once; fields left empty fall back to policy.yaml."""
    global CFG
    if any(j["state"] == "running" for j in JOBS.values()):
        raise HTTPException(409, "A background job is running. Wait for it, or cancel it, "
                                 "before changing the connection.")
    cfgmod.save_settings(_checked(body))
    CFG = cfgmod.load()
    _HEALTH["value"] = None
    return {**_settings_view(), "health": health(fresh=True)}


@app.get("/api/dashboard")
def get_dashboard(request: Request) -> Any:
    return _q(lambda st: dashboard.overview(st, CFG, _me(request), cfgmod.allow_shared_claude()))


@app.get("/api/status")
def status() -> Any:
    out = _q(query.status)
    out["environment"] = CFG.environment
    out["slices"] = list(CFG.slices)
    return out


def _track(kind: str, key: str, on: bool) -> None:
    if on:
        with store() as st:
            insights.track(st, kind, key, (CURRENT_USER.get() or {}).get("id"))


@app.get("/api/search")
def search(q: str = "", limit: int = 20, track: bool = False) -> Any:
    _track("search", q, track)
    return _q(query.search, q, max(1, min(limit, 50)))


@app.get("/api/code")
def code_search(q: str, limit: int = 60) -> Any:
    """Matches inside the git source (case-insensitive substring)."""
    if len(q.strip()) < 3:
        return {"query": q, "hits": [], "truncated": False}
    return _q(query.search_code, q.strip(), "git", max(1, min(limit, 200)))


@app.get("/api/program/{name}")
def program(name: str, provenance: str = "git", track: bool = False) -> Any:
    _track("program", name, track)
    return _q(query.program_overview, name, provenance)


@app.get("/api/program/{name}/blocks")
def program_blocks(name: str, provenance: str = "git") -> Any:
    return _q(query.blocks, name, provenance)


@app.get("/api/callers/{name}")
def callers(name: str) -> Any:
    return _q(query.callers, name)


@app.get("/api/lines/{name}")
def lines(name: str, start: int = 1, end: int = 200, provenance: str = "git") -> Any:
    return _q(query.read_lines, name, start, end, provenance)


@app.get("/api/menu/{code}")
def menu(code: str, track: bool = False) -> Any:
    _track("menu", code, track)
    return _q(query.menu, code)


@app.get("/api/field/{pick_file}/{attr}")
def field(pick_file: str, attr: int, track: bool = False) -> Any:
    _track("field", f"{pick_file}<{attr}>", track)
    with store() as st:
        return {"writes": query.attr_sites(st, pick_file, attr, "write"),
                "reads": query.attr_sites(st, pick_file, attr, "read")}


@app.get("/api/drift")
def drift_overview() -> Any:
    return _q(query.drift_overview)


@app.get("/api/drift/{name}")
def drift(name: str, all: bool = False) -> Any:  # noqa: A002 - query param name
    classes = {"whitespace", "comment", "label", "logic", "git-only", "live-only"} if all else None
    return _q(query.drift, name, classes)


@app.get("/api/slices/{slice_name}")
def slice_programs(slice_name: str) -> Any:
    sl = CFG.slices.get(slice_name)
    if sl is None:
        raise HTTPException(404, f"no slice {slice_name}")
    with store() as st:
        progs = sync.slice_programs(st, sl.seeds, sl.menus, sl.expand_calls)
        ov = {r["program"]: r for r in query.drift_overview(st)["programs"]}
        return {"slice": slice_name, "seeds": sl.seeds, "menus": sl.menus,
                "programs": [ov.get(p, {"program": p, "state": "not fetched"}) for p in progs]}


# ------------------------------------------------------------------ facts

class ProposeBody(BaseModel):
    text: str
    kind: str = "rule"
    scope: str = ""
    rationale: str = ""
    cites: list[str]
    by: str = ""


class ReviewBody(BaseModel):
    by: str = ""
    reason: str = ""


def _parse_cite(s: str) -> facts.Cite:
    parts = s.split(":")
    if len(parts) >= 3 and parts[0] in facts.CODE_SOURCES:
        return facts.Cite(parts[0], parts[1], int(parts[2]))
    if len(parts) >= 2:
        return facts.Cite(parts[0], ":".join(parts[1:]))
    raise HTTPException(400, f"bad cite {s!r}; use git:PROG:LINE, live:PROG:LINE, doc:PATH or parity:RUN")


def _fact_call(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except facts.FactError as e:
            raise HTTPException(400, str(e)) from e


@app.get("/api/facts/review")
def fact_review() -> Any:
    """Facts waiting on a person: stale ones (their cited code changed) and proposed ones, each citation with the
    line as it was cited and as it reads in git now."""
    with store() as st:
        out: dict[str, list[dict[str, Any]]] = {"stale": [], "proposed": []}
        lines: dict[tuple[str, str], list[str] | None] = {}
        for status in out:
            for f in facts.search(st, "", status, None, limit=500):
                cites = []
                cited: list[dict[str, Any]] = f["cites"]  # type: ignore[assignment]
                for c in cited:
                    now_text = None
                    if c["src"] in ("git", "live") and c["line"]:
                        k = (c["src"], c["ref"])
                        if k not in lines:
                            lines[k] = st.source_lines(c["src"], c["ref"])
                        src = lines[k]
                        now_text = src[c["line"] - 1] if src and 0 < c["line"] <= len(src) else None
                    was = (c["line_text"] or "").strip()
                    changed = now_text is not None and now_text.strip() != was
                    cites.append({**c, "now_text": now_text, "changed": changed})
                out[status].append({**f, "cites": cites, "home": query.fact_home(f)})
        return {**out, "accepted": st.db.execute("SELECT COUNT(*) n FROM fact WHERE status='accepted'").fetchone()["n"]}


@app.get("/api/facts")
def fact_list(q: str = "", status: str = "", scope: str = "") -> Any:
    with store() as st:
        rows = facts.search(st, q, status or None, scope or None, limit=500)
        events = {}
        for f in rows:
            events[f["id"]] = [dict(r) for r in st.db.execute(
                "SELECT at, actor, action, detail FROM fact_event WHERE fact_id=? ORDER BY at", (f["id"],))]
        return {"facts": [{**f, "events": events[str(f["id"])], "home": query.fact_home(f)} for f in rows]}


@app.get("/api/facts/{fid}")
def fact_one(fid: str) -> Any:
    with store() as st:
        try:
            f = facts.get(st, fid.upper())
        except facts.FactError as e:
            raise HTTPException(404, str(e)) from e
        return {**f, "home": query.fact_home(f)}


@app.post("/api/facts")
def fact_propose(body: ProposeBody, request: Request) -> Any:
    cites = [_parse_cite(c) for c in body.cites]
    by = _who(request, body.by)
    return {"id": _fact_call(lambda st: facts.propose(st, body.text, body.kind, cites, by,
                                                        body.rationale, body.scope))}


def _review(request: Request, body: ReviewBody, fid: str, action: str, fn: Callable[[Store, str], Any]) -> Any:
    by = _who(request, body.by)
    _fact_call(lambda st: fn(st, by))
    with store() as st:
        auth.audit(st, (_me(request) or {}).get("id"), f"fact.{action}", {"fact": fid.upper()})
    return _q(facts.get, fid)


@app.post("/api/facts/{fid}/accept")
def fact_accept(fid: str, body: ReviewBody, request: Request) -> Any:
    return _review(request, body, fid, "accept", lambda st, by: facts.accept(st, fid, by))


@app.post("/api/facts/{fid}/retire")
def fact_retire(fid: str, body: ReviewBody, request: Request) -> Any:
    if not body.reason.strip():
        raise HTTPException(400, "a reason is required to retire a fact")
    return _review(request, body, fid, "retire", lambda st, by: facts.retire(st, fid, by, body.reason))


@app.post("/api/facts/{fid}/recite")
def fact_recite(fid: str, body: ReviewBody, request: Request) -> Any:
    return _review(request, body, fid, "recite", lambda st, by: facts.recite(st, fid, by))


@app.post("/api/facts/check-stale")
def fact_check_stale() -> Any:
    return {"staled": _q(facts.check_stale)}


# ------------------------------------------------------------------ browse sections

@app.get("/api/programs")
def programs(q: str = "", sort: str = "usage", limit: int = 100, offset: int = 0) -> Any:
    return _q(query.programs_list, q, sort, max(1, min(limit, 500)), max(0, offset))


@app.get("/api/menus")
def menus(q: str = "", limit: int = 200, offset: int = 0) -> Any:
    return _q(query.menus_list, q, max(1, min(limit, 1000)), max(0, offset))


@app.get("/api/files")
def files(q: str = "") -> Any:
    return _q(query.files_list, q)


@app.get("/api/files/{pick_file}")
def file_detail(pick_file: str, track: bool = False) -> Any:
    _track("file", pick_file, track)
    return _q(query.file_detail, pick_file)


@app.get("/api/flow/{name}")
def flow(name: str, depth: int = 2, track: bool = False) -> Any:
    _track("flow", name, track)
    return _q(query.flow, name, max(1, min(depth, 3)))


@app.get("/api/insights")
def overview_insights() -> Any:
    with store() as st:
        uid = (CURRENT_USER.get() or {}).get("id")
        return {"most_looked_up": insights.most_looked_up(st, user_id=uid), "ideas": insights.ideas(st),
                "whats_new": insights.whats_new(st, CFG)}


# ------------------------------------------------------------------ Ask Atlas (chat)

class AskBody(BaseModel):
    question: str
    chat_id: str | None = None
    user: str = ""
    replace_last: bool = False       # a retry or edit of the chat's latest question


@app.post("/api/chat")
def chat_ask(body: AskBody, request: Request) -> StreamingResponse:
    """Server-sent events: chat, text (deltas), tool, tool_result, done | error."""
    me = _me(request)
    if body.chat_id and me:
        with store() as st:
            _, owner = chat.chat_owner(st, body.chat_id)
        if owner not in (None, me["id"]):
            raise HTTPException(404, "no such chat")

    def events() -> Iterator[str]:
        st = Store(CFG.store)
        try:
            try:
                person = _person(st, request)
            except auth.AuthError as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                return
            if not me:
                person = chat.Person(body.user)
            for ev in chat.ask(st, CFG, body.question, body.chat_id, person, body.replace_last):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        finally:
            st.close()
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.get("/api/chats")
def chats(request: Request) -> Any:
    me = _me(request)
    return {"chats": _q(chat.list_chats, me["id"] if me else None, bool(me and me["role"] == "admin"))}


def _own_chat(request: Request, chat_id: str) -> None:
    """A chat is its asker's; an admin may also open the ones from before sign-in (and anyone's)."""
    me = _me(request)
    with store() as st:
        found, owner = chat.chat_owner(st, chat_id)
    if not found or (me and owner != me["id"] and me["role"] != "admin"):
        raise HTTPException(404, "no such chat")


@app.get("/api/chats/{chat_id}")
def chat_get(chat_id: str, request: Request) -> Any:
    _own_chat(request, chat_id)
    c = _q(chat.get_chat, chat_id)
    if c is None:
        raise HTTPException(404, "no such chat")
    return c


@app.delete("/api/chats/{chat_id}")
def chat_delete(chat_id: str, request: Request) -> Any:
    _own_chat(request, chat_id)
    _q(chat.delete_chat, chat_id)
    return {"deleted": chat_id}


class FeedbackBody(BaseModel):
    verdict: str
    correction: str = ""
    user: str = ""


@app.post("/api/answers/{answer_id}/feedback")
def answer_feedback(answer_id: str, body: FeedbackBody, request: Request) -> Any:
    with store() as st:
        try:
            chat.record_feedback(st, answer_id, body.verdict, body.correction, _who(request, body.user))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return {"ok": True}


# ------------------------------------------------------------------ jobs

JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()          # one job at a time: live TEST gets one call at a time anyway


class JobCancelled(Exception):
    pass


JOB_LABEL = {"sync": "A sync", "drift": "A TEST check", "capture": "A capture", "suggest": "Flow naming",
             "dict-names": "Field naming", "profile": "A data profile", "finder": "Writing search criteria",
             "network": "A network refresh", "summaries": "Writing summaries", "embed": "Building the meaning index",
             "ask-eval": "An answer-quality run"}
# Writing summaries takes a long time and needs no TEST: it runs beside the other jobs, one at a time.
LANE = {"summaries": "knowledge", "embed": "knowledge", "ask-eval": "eval"}


# Jobs that carry what someone typed and what Claude thought about it: only whoever started one sees it.
PERSONAL_JOBS = {"finder"}


def _uid_now() -> str | None:
    return (CURRENT_USER.get() or {}).get("id")


def _job_seen(j: dict[str, Any], me: dict[str, Any] | None) -> bool:
    return me is None or j["kind"] not in PERSONAL_JOBS or j.get("user_id") in (None, me["id"])


def _job_view(j: dict[str, Any], me: dict[str, Any] | None) -> dict[str, Any]:
    """A job as this person may see it: someone else's personal job shows only that it's running."""
    if _job_seen(j, me):
        return j
    return {k: j[k] for k in ("id", "kind", "state", "started_at", "finished_at", "user_name")} | {
        "target": "", "log": [], "error": None, "result": None}


def _run_job(kind: str, target: str, work: Callable[[Store, Callable[[str], None]], Any],
             needs_vpn: bool = False) -> dict[str, Any]:
    with _LOCK:
        running = [j for j in JOBS.values() if j["state"] == "running"
                   and LANE.get(j["kind"], "main") == LANE.get(kind, "main")]
    if running:
        r = running[0]
        who = f" by {r['user_name']}" if r.get("user_name") and r.get("user_id") != _uid_now() else ""
        # tell the client which job it is, so it can show that job's progress instead of an error
        raise HTTPException(409, {"message": f"{JOB_LABEL.get(r['kind'], 'A job')} is already running{who} "
                                             f"(started {r['started_at'][11:16]} UTC). Wait for it, or cancel it.",
                                  "job": _job_view(r, CURRENT_USER.get())})
    if needs_vpn:
        _vpn_preflight()
    job: dict[str, Any] = {"id": uuid.uuid4().hex[:8], "kind": kind, "target": target, "state": "running",
                           "log": [], "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                           "finished_at": None, "error": None, "cancel": False, "result": None,
                           "user_id": _uid_now(), "user_name": (CURRENT_USER.get() or {}).get("name")}
    JOBS[job["id"]] = job

    def log(msg: str) -> None:
        # every progress line is also a cancellation point
        if job["cancel"]:
            raise JobCancelled()
        job["log"].append(msg)
        del job["log"][:-400]

    def target_fn() -> None:
        st = Store(CFG.store)
        try:
            job["result"] = work(st, log)      # optional payload for the client (e.g. suggested criteria)
            job["state"] = "done"
        except JobCancelled:
            job["state"] = "cancelled"
            job["log"].append("cancelled")
        except Exception as e:  # surfaced to the UI, never swallowed
            job["state"] = "failed"
            job["error"] = f"{type(e).__name__}: {e}"
            log(traceback.format_exc(limit=3))
        finally:
            job["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            st.close()

    threading.Thread(target=target_fn, daemon=True).start()
    return job


class SyncBody(BaseModel):
    live: bool = False
    budget: int | None = None


@app.post("/api/jobs/sync")
def job_sync(body: SyncBody) -> Any:
    def work(st: Store, log: Callable[[str], None]) -> None:
        sync.sync_git(st, CFG, log=log)
        if body.live:
            sync.sync_live(st, CFG, body.budget, log=log)
    return _run_job("sync", "live" if body.live else "git", work, needs_vpn=body.live)


@app.post("/api/jobs/drift/{name}")
def job_drift(name: str) -> Any:
    def work(st: Store, log: Callable[[str], None]) -> None:
        rep = sync.fetch_live_programs(st, CFG, [name], refresh=True, log=log)
        if rep.errors:
            raise RuntimeError("; ".join(rep.errors))
        sync.compute_drift(st, CFG, name)
        log(f"drift recomputed for {name.upper()}")
    return _run_job("drift", name.upper(), work, needs_vpn=True)


# ------------------------------------------------------------------ compare

def _cmp(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except compare.CompareError as e:
            raise HTTPException(400, str(e)) from e


@app.get("/api/compare/flows")
def cmp_flows() -> Any:
    return {"flows": _cmp(compare.list_flows)}


@app.post("/api/compare/flows")
def cmp_flow_create(body: dict[str, Any]) -> Any:
    return {"id": _cmp(lambda st: compare.save_flow(st, body))}


@app.get("/api/compare/flows/{flow_id}")
def cmp_flow_get(flow_id: str) -> Any:
    return _cmp(lambda st: {**compare.get_flow(st, flow_id), "all_notes": compare.flow_notes(st, flow_id)})


@app.put("/api/compare/flows/{flow_id}")
def cmp_flow_update(flow_id: str, body: dict[str, Any]) -> Any:
    return {"id": _cmp(lambda st: compare.save_flow(st, body, flow_id))}


@app.delete("/api/compare/flows/{flow_id}")
def cmp_flow_delete(flow_id: str) -> Any:
    _cmp(lambda st: compare.delete_flow(st, flow_id))
    return {"deleted": flow_id}


class RunBody(BaseModel):
    flow_id: str
    legacy_key: str = ""
    new_key: str = ""
    name: str = ""


@app.post("/api/compare/runs")
def cmp_run_create(body: RunBody) -> Any:
    return {"id": _cmp(lambda st: compare.create_run(st, body.flow_id, body.legacy_key, body.new_key, body.name))}


@app.get("/api/compare/runs")
def cmp_runs(limit: int = 20) -> Any:
    with store() as st:
        rows = st.db.execute("SELECT r.*, f.name flow_name FROM cmp_run r JOIN cmp_flow f ON f.id=r.flow_id "
                             "ORDER BY r.updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return {"runs": [dict(r) for r in rows]}


@app.get("/api/compare/runs/{run_id}")
def cmp_run_get(run_id: str) -> Any:
    return _cmp(lambda st: compare.get_run(st, run_id))


@app.put("/api/compare/runs/{run_id}")
def cmp_run_update(run_id: str, body: dict[str, Any]) -> Any:
    _cmp(lambda st: compare.update_run(st, run_id, body))
    return _cmp(lambda st: compare.get_run(st, run_id))


@app.delete("/api/compare/runs/{run_id}")
def cmp_run_delete(run_id: str) -> Any:
    _cmp(lambda st: compare.delete_run(st, run_id))
    return {"deleted": run_id}


@app.get("/api/compare/runs/{run_id}/diff")
def cmp_diff(run_id: str, step_id: str) -> Any:
    return _cmp(lambda st: compare.diff(st, run_id, step_id))


@app.get("/api/compare/runs/{run_id}/changes")
def cmp_changes(run_id: str, from_step: str, to_step: str) -> Any:
    return _cmp(lambda st: compare.changes(st, run_id, from_step, to_step))


@app.get("/api/compare/runs/{run_id}/report")
def cmp_report(run_id: str) -> Any:
    return {"markdown": _cmp(lambda st: compare.report_markdown(st, run_id))}


class CaptureBody(BaseModel):
    step_id: str
    sides: list[str] = ["legacy", "new"]


@app.post("/api/jobs/capture/{run_id}")
def job_capture(run_id: str, body: CaptureBody) -> Any:
    sides = tuple(s for s in body.sides if s in compare.SIDES) or compare.SIDES

    def work(st: Store, log: Callable[[str], None]) -> None:
        compare.capture(st, sync.live_client(CFG, parallel=True), run_id, body.step_id, sides, log=log)
    return _run_job("capture", run_id, work, needs_vpn=True)


# ------------------------------------------------------------------ dictionary export

class DictModelBody(BaseModel):
    description: str | None = None
    fields: list[dict[str, Any]] = []


def _dm(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e


@app.get("/api/dict/{pick_file}/model")
def dict_model(pick_file: str) -> Any:
    return _dm(lambda st: dictmodel.get(st, pick_file))


@app.put("/api/dict/{pick_file}/model")
def dict_model_save(pick_file: str, body: DictModelBody) -> Any:
    data = body.model_dump(exclude_none=True)
    return _dm(lambda st: dictmodel.save(st, pick_file, data))


@app.delete("/api/dict/{pick_file}/model")
def dict_model_reset(pick_file: str) -> Any:
    return _dm(lambda st: dictmodel.reset(st, pick_file))


@app.get("/api/dict/{pick_file}/export")
def dict_export(pick_file: str, download: bool = False) -> Any:
    from fastapi.responses import JSONResponse
    doc = _dm(lambda st: dictmodel.export(st, pick_file))
    headers = {"Content-Disposition": f'attachment; filename="{doc["table_name"]}.json"'} if download else {}
    return JSONResponse(doc, headers=headers)


@app.get("/api/dict-export.zip")
def dict_export_all() -> Any:
    """Every dictionary in git as one JSON file each, zipped."""
    import io
    import zipfile

    from fastapi.responses import Response
    buf = io.BytesIO()
    with store() as st, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in st.db.execute("SELECT DISTINCT pick_file FROM dict_attr WHERE type IN ('A','D') ORDER BY 1"):
            try:
                z.writestr(f"{r['pick_file'].replace('/', '_')}.json",
                           json.dumps(dictmodel.export(st, r["pick_file"]), indent=2))
            except ValueError:
                continue
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="erp-dictionaries.json.zip"'})


class DictNamesBody(BaseModel):
    pick_file: str


@app.post("/api/jobs/dict-names")
def job_dict_names(body: DictNamesBody, request: Request) -> Any:
    with store() as st:
        try:
            person = _person(st, request)
        except auth.AuthError as e:
            raise HTTPException(400, str(e)) from e

    def work(st: Store, log: Callable[[str], None]) -> None:
        r = dictmodel.suggest_ai(st, CFG, body.pick_file, log=log, person=person)
        log(f"Done: {len(r['fields'])} fields named" + (f" · ${r['cost_usd']:.2f}" if r.get("cost_usd") else ""))
    return _run_job("dict-names", body.pick_file.upper(), work)


# ------------------------------------------------------------------ screens

def _git_sha(st: Store) -> str:
    s = st.get_state("git:erp")
    return (s["last_sha"] if s else "") or ""


@app.get("/api/screens")
def screen_list(q: str = "", limit: int = 200) -> Any:
    return _q(lambda st: screens.list_screens(st, q, limit))


@app.get("/api/screens/{project}")
def screen_get(project: str, track: bool = False) -> Any:
    _track("screen", project.upper(), track)
    return _dm(lambda st: screens.screen(st, project))


@app.get("/api/screens/{project}/{form}")
def screen_form(project: str, form: str) -> Any:
    return _dm(lambda st: screens.form(st, project, form, _git_sha(st)))


# ------------------------------------------------------------------ background jobs + reports catalogue

class ParityBody(BaseModel):
    status: str
    target: str = ""
    note: str = ""


@app.get("/api/bg-jobs")
def bg_jobs(schedule: str = "", q: str = "", all: bool = False) -> Any:  # noqa: A002
    return _q(lambda st: legacy.list_jobs(st, schedule, q, only_jobs=not all))


@app.get("/api/bg-jobs/{name}")
def bg_job(name: str, track: bool = False) -> Any:
    _track("job", name.upper(), track)
    return _dm(lambda st: legacy.job(st, name))


@app.get("/api/legacy-reports")
def legacy_reports(q: str = "", kind: str = "", status: str = "", screens: bool = False) -> Any:
    return _q(lambda st: legacy.list_reports(st, q, kind, status, include_screens=screens))


@app.get("/api/legacy-reports/{name}")
def legacy_report(name: str, track: bool = False) -> Any:
    _track("report", name.upper(), track)
    return _dm(lambda st: legacy.report(st, name))


@app.put("/api/parity/{kind}/{name}")
def parity_set(kind: str, name: str, body: ParityBody) -> Any:
    return _dm(lambda st: legacy.set_parity(st, kind, name, body.status, body.target, body.note))


@app.get("/api/files/{pick_file}/jobs")
def file_jobs(pick_file: str) -> Any:
    return _q(lambda st: legacy.jobs_writing(st, pick_file))


@app.get("/api/trace/field/{pick_file}/{attr}")
def trace_field(pick_file: str, attr: int, track: bool = False) -> Any:
    """A field's journey: how users reach its writers, where the value comes from, who reads it and where it goes on."""
    _track("field", f"{pick_file}<{attr}>", track)
    return _q(trace.field_journey, pick_file, attr)


@app.get("/api/processes")
def processes() -> Any:
    return process.catalog()


@app.get("/api/process/{key}")
def process_get(key: str) -> Any:
    """A business process read off the code: each state, who moves a record into it, and what else they touch."""
    if key not in process.PROCESSES:
        raise HTTPException(404, f"no process called {key}")
    return _q(process.process_flow, key)


# ------------------------------------------------------------------ branch network

@app.get("/api/network")
def network_get(days: int = 30) -> Any:
    """The last network snapshot (no TEST reads); {"empty": true} if there isn't one yet."""
    v = network.cached(sync.live_client(CFG, parallel=True), days)
    return {**v, "organisation": CFG.organisation} if v else {"empty": True}


class NetworkBody(BaseModel):
    days: int = 30


@app.post("/api/jobs/network")
def job_network(body: NetworkBody) -> Any:
    def work(st: Store, log: Callable[[str], None]) -> None:
        v = network.snapshot(sync.live_client(CFG, parallel=True), max(1, min(body.days, 180)), refresh=True, log=log)
        log(f"Done: {v['kpis']['branches']} branches, {v['kpis']['in_transit']} in transit, "
            f"{v['kpis']['open']} open transfers in {v['seconds']} s")
    return _run_job("network", f"{body.days} days", work, needs_vpn=True)


@app.get("/api/network/branch/{branch}")
def network_branch(branch: str, days: int = 30) -> Any:
    _vpn_preflight()
    return _dm(lambda st: network.branch_detail(sync.live_client(CFG, parallel=True), branch, days))


@app.get("/api/network/transfer/{xfn}")
def network_transfer(xfn: str) -> Any:
    _vpn_preflight()
    return _dm(lambda st: network.journey(sync.live_client(CFG, parallel=True), xfn))


# ------------------------------------------------------------------ test data finder

class FinderRunBody(BaseModel):
    pick_file: str
    criteria: dict[str, Any] = {}
    limit: int = 25
    scenario_id: str | None = None


class FinderSuggestBody(BaseModel):
    pick_file: str
    description: str


class ScenarioBody(BaseModel):
    pick_file: str
    name: str
    description: str = ""
    criteria: dict[str, Any] = {}
    flow_id: str | None = None
    shared: bool | None = None          # None on an edit: leave sharing as it is


def _fd(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except finder.FinderError as e:
            raise HTTPException(400, str(e)) from e


@app.post("/api/finder/run")
def finder_run(body: FinderRunBody) -> Any:
    """Find records on TEST that fit the criteria (a few seconds; read-only)."""
    _vpn_preflight()
    table = body.pick_file.strip().upper()
    if table in CFG.live.deny_tables:
        raise HTTPException(400, f"{table} holds sensitive data and is never read by Atlas.")

    def work(st: Store) -> Any:
        auth.audit(st, _uid_now(), "test.read", {"via": "test-data", "file": table,
                                                 "what": str(body.criteria.get("query", ""))[:200]})
        r = finder.run(st, sync.live_client(CFG, parallel=True), table, body.criteria, max(1, min(body.limit, 100)))
        sid = body.scenario_id
        row = st.db.execute("SELECT user_id, shared FROM finder_scenario WHERE id=?", (sid,)).fetchone() \
            if sid else None
        if sid and row and finder.visible(dict(row), _uid_now()):
            finder.mark_run(st, sid, r["total_matches"])
        return r
    return _fd(work)


@app.get("/api/finder/fields/{pick_file}")
def finder_fields(pick_file: str) -> Any:
    """The file's DICT as query-builder fields, with the values each one is known to take."""
    return _fd(lambda st: finder.fields(st, pick_file))


class RecordBody(BaseModel):
    pick_file: str
    key: str
    related: list[dict[str, Any]] = []


@app.post("/api/finder/record")
def finder_record(body: RecordBody) -> Any:
    """One TEST record, named and converted, with its related records (read-only)."""
    _vpn_preflight()
    table = body.pick_file.strip().upper()
    denied = [t for t in [table, *(str(r.get("file", "")).upper() for r in body.related)] if t in CFG.live.deny_tables]
    if denied:
        raise HTTPException(400, f"{denied[0]} holds sensitive data and is never read by Atlas.")
    client = sync.live_client(CFG, parallel=True)

    def work(st: Store) -> Any:
        auth.audit(st, _uid_now(), "test.read", {"via": "test-data", "file": table, "what": f"record {body.key}"})
        return finder.record(st, client, table, body.key.strip(), body.related)
    return _fd(work)


@app.post("/api/jobs/finder-suggest")
def job_finder_suggest(body: FinderSuggestBody, request: Request) -> Any:
    if not body.description.strip():
        raise HTTPException(400, "Describe the record you need, e.g. “shipped transfer with serial numbers”.")
    with store() as st:
        try:
            person = _person(st, request)
        except auth.AuthError as e:
            raise HTTPException(400, str(e)) from e

    def work(st: Store, log: Callable[[str], None]) -> Any:
        return finder.suggest(st, CFG, body.pick_file, body.description, log, person)
    return _run_job("finder", body.pick_file.upper(), work)


@app.get("/api/finder/scenarios")
def scenarios(request: Request, flow_id: str | None = None, pick_file: str | None = None) -> Any:
    uid = (_me(request) or {}).get("id")
    return [{**s, "mine": uid is None or s["user_id"] == uid}
            for s in _fd(lambda st: finder.list_all(st, flow_id, pick_file, uid))]


@app.post("/api/finder/scenarios")
def scenario_create(body: ScenarioBody, request: Request) -> Any:
    uid = (_me(request) or {}).get("id")
    return _fd(lambda st: finder.save(st, body.model_dump(), user_id=uid))


def _own_scenario(request: Request, sid: str) -> None:
    """Saved searches are changed by whoever saved them (or an admin); the team only uses shared ones."""
    me = _me(request)
    s = _fd(lambda st: finder.get(st, sid))
    if me is None:
        return
    if not finder.visible(s, me["id"]):
        raise HTTPException(404, f"no scenario {sid}")
    if s["user_id"] != me["id"] and me["role"] != "admin":
        raise HTTPException(403, f"This is {s['owner']}'s scenario: save a copy to change it" if s.get("owner")
                            else "Only an admin can change scenarios saved before sign-in")


@app.put("/api/finder/scenarios/{sid}")
def scenario_update(sid: str, body: ScenarioBody, request: Request) -> Any:
    _own_scenario(request, sid)
    return _fd(lambda st: finder.save(st, body.model_dump(), sid))


@app.delete("/api/finder/scenarios/{sid}")
def scenario_delete(sid: str, request: Request) -> Any:
    _own_scenario(request, sid)
    _fd(lambda st: finder.delete(st, sid))
    return {"ok": True}


# ------------------------------------------------------------------ data profiler

class ProfileBody(BaseModel):
    pick_file: str
    sample: int = 1000


@app.post("/api/jobs/profile")
def job_profile(body: ProfileBody) -> Any:
    table = body.pick_file.strip().upper()
    if table in CFG.live.deny_tables:
        raise HTTPException(400, f"{table} holds sensitive data and is never read by Atlas.")

    def work(st: Store, log: Callable[[str], None]) -> None:
        sha = (query.status(st).get("freshness", {}).get("git:erp") or {}).get("sha") or ""
        profile.run(st, sync.live_client(CFG, parallel=True), table, body.sample, log, CFG.environment, sha)
    return _run_job("profile", table, work, needs_vpn=True)


@app.get("/api/profiles")
def profiles() -> Any:
    return _q(profile.overview)


@app.get("/api/profiles/{pick_file}")
def profile_latest(pick_file: str) -> Any:
    with store() as st:
        return {"latest": profile.latest(st, pick_file), "history": profile.history(st, pick_file, 10)}


@app.get("/api/profile/{rid}")
def profile_get(rid: str) -> Any:
    return _dm(lambda st: profile.get(st, rid))


# ------------------------------------------------------------------ reports

class ReportBody(BaseModel):
    page: str
    title: str = ""


def _rep(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except reports.ReportError as e:
            raise HTTPException(400 if "export" in str(e) else 404, str(e)) from e


@app.post("/api/reports")
def report_create(body: ReportBody, request: Request) -> Any:
    """Render an Atlas page to PDF (takes a few seconds) and keep it for sharing. The server's browser loads the
    page as the person asking, on a sign-in that lasts only as long as the print."""
    me = _me(request)

    def work(st: Store) -> Any:
        sha = (query.status(st).get("freshness", {}).get("git:erp") or {}).get("sha") or ""
        session = auth.render_session(st, me["id"]) if me else None
        try:
            return reports.create(st, body.page, body.title, sha, CFG.environment, me["id"] if me else None, session)
        except reports.ReportError:
            raise
        except Exception as e:  # browser missing, page timed out, web UI not running...
            raise HTTPException(502, f"Couldn't render the PDF: {str(e).splitlines()[0][:300]}. "
                                     f"Is the web UI running at {reports.WEB_URL}?") from e
        finally:
            auth.logout(st, session)
    return _rep(work)


@app.get("/api/reports")
def report_list(request: Request) -> Any:
    uid = (_me(request) or {}).get("id")
    return _rep(lambda st: reports.list_all(st, user_id=uid))


@app.get("/api/reports/{rid}")
def report_get(rid: str) -> Any:
    return _rep(lambda st: reports.get(st, rid))


@app.get("/api/reports/{rid}/pdf")
def report_pdf(rid: str, download: bool = False) -> Any:
    r = _rep(lambda st: reports.get(st, rid))
    p = reports.REPORT_DIR / r["file"]
    if not p.exists():
        raise HTTPException(404, "the PDF file is missing from .data/reports")
    return FileResponse(p, media_type="application/pdf", filename=r["filename"],
                        content_disposition_type="attachment" if download else "inline")


@app.delete("/api/reports/{rid}")
def report_delete(rid: str, request: Request) -> Any:
    me = _me(request)
    owner = _rep(lambda st: st.db.execute("SELECT user_id FROM report WHERE id=?", (rid,)).fetchone())
    if me and owner and owner["user_id"] not in (None, me["id"]) and me["role"] != "admin":
        raise HTTPException(403, "Only whoever made this PDF, or an admin, can delete it")
    _rep(lambda st: reports.delete(st, rid))
    return {"ok": True}


class QuickBody(BaseModel):
    pick_file: str
    old_key: str
    new_key: str


@app.get("/api/compare/suggest")
def cmp_suggest(topic: str = "", program: str = "") -> Any:
    """Code-only suggestions now, plus Claude's named flows if they were generated before."""
    if not topic.strip() and not program.strip():
        return {"quick": None, "ai": None}
    with store() as st:
        return {"quick": suggest.quick(st, topic, program or None),
                "ai": suggest.cached(st, topic, program or None)}


class SuggestBody(BaseModel):
    topic: str = ""
    program: str = ""


@app.post("/api/jobs/suggest")
def job_suggest(body: SuggestBody) -> Any:
    def work(st: Store, log: Callable[[str], None]) -> None:
        suggest.suggest(st, CFG, body.topic, body.program or None, log=log)
    return _run_job("suggest", body.program or body.topic, work)


@app.post("/api/compare/quick")
def cmp_quick(body: QuickBody) -> Any:
    _vpn_preflight()
    cl = sync.live_client(CFG, parallel=True)
    return _cmp(lambda st: compare.quick(cl, st, body.pick_file, body.old_key, body.new_key))


class NoteBody(BaseModel):
    run_id: str = ""
    pick_file: str = ""
    attr: int = 0
    verdict: str = "question"
    text: str = ""
    author: str = ""
    remember: bool = True


@app.post("/api/compare/notes")
def cmp_note_add(body: NoteBody, request: Request) -> Any:
    author = _who(request, body.author)
    return {"id": _cmp(lambda st: compare.add_note(st, body.run_id, body.pick_file, body.attr, body.verdict,
                                                   body.text, author, body.remember))}


@app.put("/api/compare/notes/{note_id}")
def cmp_note_update(note_id: str, body: dict[str, Any]) -> Any:
    _cmp(lambda st: compare.update_note(st, note_id, body.get("verdict"), body.get("text")))
    return {"ok": True}


@app.delete("/api/compare/notes/{note_id}")
def cmp_note_delete(note_id: str) -> Any:
    _cmp(lambda st: compare.delete_note(st, note_id))
    return {"deleted": note_id}


@app.post("/api/jobs/{jid}/cancel")
def job_cancel(jid: str, request: Request) -> Any:
    me = _me(request)
    j = JOBS.get(jid)
    if j is None or not _job_seen(j, me):
        raise HTTPException(404, "no such job")
    if me and j.get("user_id") not in (None, me["id"]) and me["role"] != "admin":
        raise HTTPException(403, f"Only {j.get('user_name') or 'whoever started it'} or an admin can cancel this")
    j["cancel"] = True          # the job stops at its next progress line (e.g. after the current read)
    return j


@app.get("/api/jobs")
def jobs(request: Request) -> Any:
    me = _me(request)
    mine = [_job_view(j, me) for j in JOBS.values() if _job_seen(j, me)]
    return {"jobs": sorted(mine, key=lambda j: j["started_at"], reverse=True)[:20]}


@app.get("/api/jobs/{jid}")
def job(jid: str, request: Request) -> Any:
    j = JOBS.get(jid)
    if j is None or not _job_seen(j, _me(request)):
        raise HTTPException(404, "no such job")
    return j



# ------------------------------------------------------------------ summaries and search by meaning

class SummariesBody(BaseModel):
    limit: int = 25
    model: str = "claude-sonnet-5-5"
    programs: list[str] = []          # just these (e.g. the ERP Next helpers), rewritten even if current


# ------------------------------------------------------------------ answer quality (admins)

class EvalRunBody(BaseModel):
    cases: list[str] = []
    model: str = ""


class EvalCaseBody(BaseModel):
    answer_id: str = ""
    question: str = ""
    expected: str = ""
    must_cite: list[str] = []


class EvalVerifyBody(BaseModel):
    expected: str | None = None


@app.get("/api/eval")
def eval_overview() -> Any:
    """The golden set, the latest runs, and thumbs-down answers with a correction that could become cases."""
    with store() as st:
        asked = {c["q"].strip().lower() for c in ask_eval.cases()}
        cand = [dict(r) for r in st.db.execute(
            "SELECT f.answer_id, f.correction, f.user, f.created_at, a.question, a.answer FROM feedback f "
            "JOIN answer a ON a.id = f.answer_id WHERE f.verdict='down' AND TRIM(COALESCE(f.correction,''))!='' "
            "ORDER BY f.created_at DESC LIMIT 50")]
        return {"cases": ask_eval.cases(), "runs": ask_eval.history(st),
                "candidates": [{**c, "answer": c["answer"][:600]} for c in cand
                               if c["question"].strip().lower() not in asked]}


@app.post("/api/eval/cases")
def eval_add(body: EvalCaseBody, request: Request) -> Any:
    q, expected = body.question, body.expected
    if body.answer_id:                           # from a corrected thumbs-down: its question, the correction
        with store() as st:
            r = st.db.execute("SELECT a.question, f.correction FROM answer a LEFT JOIN feedback f "
                              "ON f.answer_id=a.id AND f.verdict='down' WHERE a.id=? ORDER BY f.created_at DESC",
                              (body.answer_id,)).fetchone()
        if r is None:
            raise HTTPException(404, "no such answer")
        q, expected = q or r["question"], expected or (r["correction"] or "")
    if not q.strip():
        raise HTTPException(400, "A case needs a question")
    return ask_eval.add_case(q, expected, body.must_cite, f"answer {body.answer_id}" if body.answer_id else "admin",
                             _who(request))


@app.post("/api/eval/cases/{case_id}/verify")
def eval_verify(case_id: str, body: EvalVerifyBody, request: Request) -> Any:
    try:
        return ask_eval.verify(case_id, _who(request, "admin"), body.expected)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/jobs/ask-eval")
def job_ask_eval(body: EvalRunBody, request: Request) -> Any:
    """Ask every golden question (or the chosen ones) and score the answers, on the admin's own Claude."""
    person = _summary_person(request, body.model)
    ids = body.cases or None

    def work(st: Store, log: Callable[[str], None]) -> Any:
        return ask_eval.run(st, CFG, person, ids, log)
    return _run_job("ask-eval", f"{len(ids)} cases" if ids else "all cases", work)


@app.get("/api/erpnext")
def erp_next() -> Any:
    """The subroutines the ERP Next API calls, and the old programs and files they still depend on."""
    return _q(erpnext.overview)


@app.get("/api/knowledge")
def knowledge_status() -> Any:
    with store() as st:
        n = st.db.execute("SELECT COUNT(*) n FROM embedding WHERE model=?", (semantic.MODEL,)).fetchone()["n"]
        return {**knowledge.coverage(st), "index": {"entries": n, "model": semantic.MODEL,
                                                    "available": semantic.available()},
                "models": [{"id": k, "label": v} for k, v in chat.MODELS.items()]}


@app.get("/api/knowledge/estimate")
def knowledge_estimate(limit: int = 25) -> Any:
    return _q(knowledge.estimate, max(1, min(limit, 500)))


@app.get("/api/program/{name}/summary")
def program_summary(name: str) -> Any:
    return _q(knowledge.get, name)


def _summary_person(request: Request, model: str = "") -> chat.Person:
    with store() as st:
        try:
            p = _person(st, request)
        except auth.AuthError as e:
            raise HTTPException(400, str(e)) from e
    if model and model not in chat.MODELS:
        raise HTTPException(400, f"Unknown model {model}")
    return replace(p, model=model or p.model)


@app.post("/api/program/{name}/summarize")
def program_summarize(name: str, request: Request) -> Any:
    """(Re)write one program's summary, on the asker's own Claude."""
    person = _summary_person(request)
    if not _q(knowledge.get, name)["indexed"]:
        raise HTTPException(404, f"{name.upper()} isn't in the git index")

    def work(st: Store, log: Callable[[str], None]) -> Any:
        return knowledge.summarize(st, CFG, 1, person, log, only=[name])
    return _run_job("summaries", name.upper(), work)


@app.post("/api/jobs/summaries")
def job_summaries(body: SummariesBody, request: Request) -> Any:
    person = _summary_person(request, body.model)
    limit = max(1, min(body.limit, 500))

    only = [p.upper() for p in body.programs][:500] or None

    def work(st: Store, log: Callable[[str], None]) -> Any:
        return knowledge.summarize(st, CFG, len(only) if only else limit, person, log, only=only)
    return _run_job("summaries", f"{len(only)} named" if only else f"next {limit}", work)


@app.post("/api/jobs/embed")
def job_embed() -> Any:
    return _run_job("embed", "all", lambda st, log: semantic.index(st, log))


@app.get("/api/meaning")
def meaning(q: str = "", limit: int = 10) -> Any:
    """Summaries and facts closest in meaning to a description."""
    return _q(semantic.search, q, max(1, min(limit, 30)))


# ------------------------------------------------------------------ sign-in, account, admin

class LoginBody(BaseModel):
    email: str
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


class ClaudeBody(BaseModel):
    kind: str
    secret: str


class NewUserBody(BaseModel):
    email: str
    name: str
    role: str = "member"


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None


class AdminSettingsBody(BaseModel):
    allow_shared_claude: bool


def _auth_call(fn: Callable[[Store], Any]) -> Any:
    with store() as st:
        try:
            return fn(st)
        except auth.AuthError as e:
            raise HTTPException(400, str(e)) from e


def _uid(request: Request) -> str:
    me = _me(request)
    if me is None:
        raise HTTPException(401, "Sign in to use Atlas")
    return str(me["id"])


@app.get("/api/auth/state")
def auth_state(request: Request) -> Any:
    with store() as st:
        user = auth.session_user(st, request.cookies.get(auth.COOKIE)) if AUTH else None
        return {"auth": AUTH, "setup_needed": AUTH and auth.count_users(st) == 0, "user": user}


def _client_ip(request: Request) -> str:
    """The browser's address: behind ngrok or the Next proxy it's the first X-Forwarded-For hop."""
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")


@app.post("/api/auth/login")
def auth_login(body: LoginBody, request: Request, response: Response) -> Any:
    token, user = _auth_call(lambda st: auth.login(st, body.email, body.password, _client_ip(request)))
    # over https (ngrok, a reverse proxy) the cookie is only ever sent over https
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=https or os.environ.get("ATLAS_SECURE_COOKIE") == "1", path="/")
    return {"user": user}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> Any:
    with store() as st:
        auth.logout(st, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request) -> Any:
    uid = _uid(request)
    with store() as st:
        return {"user": auth.get_user(st, uid), "claude": auth.get_claude(st, uid),
                "shared_claude": cfgmod.allow_shared_claude(), "model": auth.get_pref(st, uid, "model") or ""}


class ModelBody(BaseModel):
    model: str = ""


@app.get("/api/models")
def models(request: Request) -> Any:
    """The models a person can pick, the server default, and their current choice."""
    me = _me(request)
    mine = _q(auth.get_pref, me["id"], "model") if me else None
    return {"default": CFG.chat.model, "options": [{"id": k, "label": v} for k, v in chat.MODELS.items()],
            "mine": mine or ""}


@app.put("/api/account/model")
def account_model(body: ModelBody, request: Request) -> Any:
    if body.model and body.model not in chat.MODELS:
        raise HTTPException(400, f"Unknown model {body.model}")
    _q(auth.set_pref, _uid(request), "model", body.model)
    return {"model": body.model}


@app.post("/api/account/password")
def account_password(body: PasswordBody, request: Request) -> Any:
    uid = _uid(request)
    _auth_call(lambda st: auth.change_password(st, uid, body.current, body.new))
    return {"ok": True}


@app.put("/api/account/claude")
def account_claude(body: ClaudeBody, request: Request) -> Any:
    uid = _uid(request)
    return _auth_call(lambda st: auth.set_claude(st, uid, body.kind, body.secret))


@app.delete("/api/account/claude")
def account_claude_remove(request: Request) -> Any:
    uid = _uid(request)
    _q(auth.remove_claude, uid)
    return {"ok": True}


@app.post("/api/account/claude/test")
def account_claude_test(request: Request) -> Any:
    """One tiny prompt on the person's own Claude, to prove the connection works."""
    uid = _uid(request)
    env = _auth_call(lambda st: auth.claude_env(st, uid, False))
    try:
        r = subprocess.run([chat.claude_bin(), "-p", "Reply with the single word: ok", "--output-format", "json"],
                           capture_output=True, text=True, timeout=90, env=chat._env(chat.Person(env=env)))
    except (OSError, subprocess.TimeoutExpired, chat.ChatUnavailable) as e:
        return {"ok": False, "message": str(e)[:300]}
    try:
        out = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        out = {}
    if r.returncode != 0 or out.get("is_error"):
        return {"ok": False, "message": (out.get("result") or r.stderr or r.stdout or "Claude didn't answer")[:300]}
    return {"ok": True, "message": "Connected: Claude answered on your account."}


@app.get("/api/admin/users")
def admin_users() -> Any:
    return {"users": _q(auth.list_users)}


@app.post("/api/admin/users")
def admin_user_add(body: NewUserBody, request: Request) -> Any:
    user, temp = _auth_call(lambda st: auth.create_user(st, body.email, body.name, body.role, by=_uid(request)))
    return {"user": user, "temp_password": temp}


@app.patch("/api/admin/users/{user_id}")
def admin_user_edit(user_id: str, body: UserPatch, request: Request) -> Any:
    by = _uid(request)
    if user_id == by and body.active is False:
        raise HTTPException(400, "You can't deactivate your own account")
    return _auth_call(lambda st: auth.update_user(st, user_id, by, body.role, body.active, body.name))


@app.post("/api/admin/users/{user_id}/reset")
def admin_user_reset(user_id: str, request: Request) -> Any:
    by = _uid(request)
    return {"temp_password": _auth_call(lambda st: auth.reset_password(st, user_id, by))}


@app.get("/api/admin/usage")
def admin_usage() -> Any:
    """Questions and Claude cost per person, all time and the last 30 days."""
    with store() as st:
        chat._ensure_tables(st)        # chats gain their owner column on first use
        rows = st.db.execute(
            "SELECT u.id, u.name, u.email, u.role, COUNT(t.seq) asked, COALESCE(SUM(t.cost_usd),0) cost, "
            "SUM(CASE WHEN t.created_at >= date('now','-30 day') THEN 1 ELSE 0 END) asked_30d, "
            "COALESCE(SUM(CASE WHEN t.created_at >= date('now','-30 day') THEN t.cost_usd END),0) cost_30d, "
            "MAX(t.created_at) last_asked, c.kind claude "
            "FROM app_user u LEFT JOIN chat ch ON ch.user_id = u.id "
            "LEFT JOIN chat_turn t ON t.chat_id = ch.id "
            "LEFT JOIN user_claude c ON c.user_id = u.id GROUP BY u.id ORDER BY cost DESC").fetchall()
        return {"usage": [dict(r) for r in rows]}


@app.get("/api/admin/audit")
def admin_audit(limit: int = 200) -> Any:
    with store() as st:
        rows = st.db.execute("SELECT a.at, a.action, a.detail, u.name, u.email FROM audit a "
                             "LEFT JOIN app_user u ON u.id = a.user_id ORDER BY a.at DESC LIMIT ?",
                             (min(limit, 1000),)).fetchall()
        return {"audit": [{**dict(r), "detail": json.loads(r["detail"] or "{}")} for r in rows]}


@app.get("/api/admin/settings")
def admin_settings() -> Any:
    from atlas import backup
    return {"allow_shared_claude": cfgmod.allow_shared_claude(), "backup": backup.latest()}


@app.post("/api/admin/backup")
def admin_backup(request: Request) -> Any:
    from atlas import backup
    r = backup.backup(CFG.store)
    with store() as st:
        auth.audit(st, _uid(request), "backup", {"path": r["path"]})
    return {**r, "latest": backup.latest()}


@app.put("/api/admin/settings")
def admin_settings_save(body: AdminSettingsBody, request: Request) -> Any:
    on = cfgmod.save_allow_shared_claude(body.allow_shared_claude)
    with store() as st:
        auth.audit(st, _uid(request), "settings.shared_claude", {"on": on})
    return {"allow_shared_claude": on}


def serve(port: int = 8765) -> None:
    import socket

    import uvicorn

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"Port {port} is already in use -- Atlas API may already be running at "
                             f"http://127.0.0.1:{port}/api/status. Stop it first, or use --port.")
    print(f"Atlas API on http://127.0.0.1:{port}  (web UI: cd web && npm run dev)", flush=True)
    from atlas import backup
    backup.start_daily(CFG.store)          # one backup a day of what git can't rebuild
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
