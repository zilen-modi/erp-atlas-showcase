"""Ask Atlas: chat answered by Claude Code (headless) using only the Atlas MCP tools.

Runs `claude -p` as the person asking: with their own Claude (a subscription token or an API key, see
atlas.auth) when they've connected one, else the server's own Claude Code login when an admin allows it.
The session is locked down: no built-in tools (no files, no shell), no user
settings/plugins/skills, only `mcp__erp-atlas__*`.  Follow-up questions resume
the same Claude Code session so it keeps the conversation.

Every finished answer is also written to the `answer` table (episodic memory),
where people can mark it right or wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from atlas import citecheck
from atlas.config import ROOT, Config
from atlas.store.db import Store, now

Event = dict[str, Any]

SYSTEM = """You are Ask Atlas, the assistant for developers migrating a legacy Pick/UniVerse ERP
to a new system. Answer only from the erp-atlas tools; they index the legacy code (its git repository),
menus with real launch counts, DICT definitions, and reviewed facts.

Git main is the single source of truth. Explain behaviour from the git copy only and cite git
lines. Do not quote or cite the TEST server's copy. If `drift` shows the TEST server runs a
different version of a program you explain, add one short note at the end (for example "TEST runs
an older version of LG.XFER.MAINT, 2 commits behind") -- nothing more about TEST unless asked.

How to work:
- Find names with `search`, trace end-to-end behaviour with `flow`, then read the code that
  matters with `read_lines` before stating what it does.
- When the question describes behaviour in business words rather than names ("where is freight
  calculated?"), start with `search_meaning`. Its summaries are machine-written orientation, not evidence:
  read the lines they point to and cite the code, never the summary. `program_overview` includes a
  program's summary when one exists.
- Attribute writes like `XF<10> = ...` change the in-memory record; the record is persisted where
  `persisted_by_write_at` says. W5-converted programs do I/O through CALL IOREADU / IORELEASE.
- Confirmed facts are reviewed knowledge; unconfirmed facts must be labelled as unconfirmed.
- If you establish something non-obvious and can cite it, you may call fact_propose (use
  "Ask Atlas" as proposed_by); a person confirms it later. Never present it as confirmed.
- Say plainly when the index cannot answer something rather than guessing.
- For where a field's value comes from and goes, use `trace_field`; for a record's life through its statuses
  (e.g. how a transfer is ordered, shipped and received), use `process_flow` (`processes` lists them).
- When an answer is about data, end with links the reader can click, as Markdown links: the field's trace
  (the `page` from trace_field), the process board (the `page` from process_flow), and a Test data search
  built with `test_data_link` (use `test_data_fields` for real values; use the url it returns verbatim, never
  write one yourself). Label them plainly, e.g. "See received transfers on TEST".
- When the question is about specific data -- a particular code, product, record or value ("is MIS an SPN
  product?", "what's on transfer 1234567?", "which branch is 142?") -- check TEST, don't only reason from code:
  `live_record` reads one record by key (try ALT-PN when a product code isn't a PRODUCT key), and
  `live_examples` shows what records match a selection and how many. You have 6 TEST reads per answer; use
  them on the deciding records. Explain the meaning from the git code, then give the values, labelled as read
  just now from TEST (a small table helps). If TEST can't be reached, say so and give a Test data link.

Write for a developer who does not read Pick BASIC: plain language first, then detail. Cite
every code claim as PROGRAM:line and fields as FILE<attr>, e.g. LG.XFER.MAINT:4720, TRANSFER<10>.
Use Markdown."""

_CITE = re.compile(r"\b(?:live:)?([A-Z][A-Z0-9._$%]*):(\d+)\b")


PROPOSER = "Ask Atlas (Claude Code)"


class ChatUnavailable(RuntimeError):
    pass


def claude_bin() -> str:
    path = shutil.which("claude")
    if not path:
        raise ChatUnavailable("Claude Code CLI (`claude`) is not on PATH. Install Claude Code and run `claude` "
                              "once to sign in.")
    return path


# Models a person can pick for their questions ("" = the server default in config/policy.yaml).
MODELS: dict[str, str] = {
    "claude-opus-5-5": "Opus 5.5 · most capable, uses most of your plan",
    "claude-sonnet-5-5": "Sonnet 5.5 · quick and capable",
    "claude-haiku-4-5-20251001": "Haiku 4.5 · fastest, lightest",
    "claude-fable-5-1": "Fable 5.1",
}


@dataclass(frozen=True)
class Person:
    """Who a Claude run is for: named on answers and proposed facts, and run on their own Claude."""
    name: str = ""
    user_id: str | None = None
    env: dict[str, str] = field(default_factory=dict)      # their token or key, and their config dir
    model: str = ""                                         # their chosen model; "" = the server default

    @property
    def proposer(self) -> str:
        return f"Ask Atlas for {self.name}" if self.name else PROPOSER


# Claude runs on subscriptions only: a key in the server's environment would quietly switch it to per-call billing.
API_BILLING_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _env(person: Person | None) -> dict[str, str]:
    base = {k: v for k, v in os.environ.items() if k not in API_BILLING_VARS}
    return {**base, **(person.env if person else {})}


def mcp_config_path(person: Person | None = None) -> Path:
    # one file per person: their name goes on the facts the tools propose
    who = (person.user_id or person.name) if person else ""
    tag = hashlib.sha1(who.encode()).hexdigest()[:10] if who else ""
    p = ROOT / ".data" / (f"chat-mcp-{tag}.json" if tag else "chat-mcp.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mcpServers": {"erp-atlas": {
        "command": shutil.which("uv") or "uv", "args": ["run", "--directory", str(ROOT), "atlas", "mcp"],
        "env": {"ATLAS_PROPOSER": person.proposer if person else PROPOSER, "ATLAS_LIVE_EXAMPLES": "6",
                "ATLAS_USER_ID": (person.user_id if person else None) or ""}}}}))
    return p


def workspace() -> Path:
    # A dedicated cwd, so Claude Code's per-project state stays out of the user's repos.
    p = ROOT / ".data" / "chat-workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def build_command(cfg: Config, question: str, resume: str | None, person: Person | None = None) -> list[str]:
    cmd = [claude_bin(), "-p", question,
           "--output-format", "stream-json", "--verbose", "--include-partial-messages",
           "--mcp-config", str(mcp_config_path(person)), "--strict-mcp-config",
           "--tools", "",                                # no built-in tools: no files, no shell
           "--allowedTools", "mcp__erp-atlas__*",
           "--disable-slash-commands", "--setting-sources", "",
           "--permission-mode", "dontAsk",
           "--append-system-prompt", SYSTEM]
    model = (person.model if person else "") or cfg.chat.model
    if model:
        cmd += ["--model", model]
    if cfg.chat.effort:
        cmd += ["--effort", cfg.chat.effort]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def _preview(content: Any, limit: int = 600) -> str:
    if isinstance(content, list):
        content = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    s = str(content)
    return s if len(s) <= limit else s[:limit] + "…"


def _short_tool(name: str) -> str:
    return name.removeprefix("mcp__erp-atlas__")


def translate(line: str, state: dict[str, Any]) -> Iterator[Event]:
    """One stream-json line from Claude Code -> zero or more UI events."""
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return
    t = d.get("type")
    if t == "system" and d.get("subtype") == "init":
        state["session_id"] = d.get("session_id")
        state["model"] = d.get("model")
        bad = [m for m in d.get("mcp_servers", []) if m.get("status") != "connected"]
        if bad:
            yield {"type": "error", "message": f"Atlas tools failed to connect: {bad}"}
    elif t == "stream_event":
        ev = d.get("event", {})
        if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            text = ev["delta"]["text"]
            state["text"] += text
            yield {"type": "text", "text": text}
        elif ev.get("type") == "message_start" and state["text"] and not state["text"].endswith("\n\n"):
            state["text"] += "\n\n"          # a new assistant message after tool calls: new paragraph
            yield {"type": "text", "text": "\n\n"}
    elif t == "assistant":
        for b in d.get("message", {}).get("content", []):
            if b.get("type") == "tool_use":
                yield {"type": "tool", "id": b.get("id"), "name": _short_tool(b.get("name", "")),
                       "input": b.get("input", {})}
    elif t == "user":
        for b in d.get("message", {}).get("content", []):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                yield {"type": "tool_result", "id": b.get("tool_use_id"), "error": bool(b.get("is_error")),
                       "preview": _preview(b.get("content"))}
    elif t == "result":
        state["result"] = d
        if d.get("is_error"):
            msg = str(d.get("result") or d.get("subtype") or "Claude Code reported an error")
            if "log" in msg.lower() and "in" in msg.lower():
                msg += " (sign in by running `claude` once in a terminal)"
            yield {"type": "error", "message": msg}


# ------------------------------------------------------------------ storage

def _ensure_tables(store: Store) -> None:
    store.db.executescript("""
    CREATE TABLE IF NOT EXISTS chat (
        id TEXT PRIMARY KEY, title TEXT, session_id TEXT, created_at TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS chat_turn (
        chat_id TEXT, seq INTEGER, question TEXT, answer TEXT, events TEXT, answer_id TEXT,
        cost_usd REAL, duration_ms INTEGER, created_at TEXT
    );
    """)
    # chats belong to the person who asked (older ones, from before sign-in, to nobody: admins see those)
    if "user_id" not in {r["name"] for r in store.db.execute("PRAGMA table_info(chat)")}:
        store.db.execute("ALTER TABLE chat ADD COLUMN user_id TEXT")
        store.commit()
    # each answer's citations, checked against git when it was written (atlas.citecheck)
    if "checks" not in {r["name"] for r in store.db.execute("PRAGMA table_info(chat_turn)")}:
        store.db.execute("ALTER TABLE chat_turn ADD COLUMN checks TEXT")
        store.commit()


def list_chats(store: Store, user_id: str | None = None, admin: bool = True) -> list[dict[str, Any]]:
    """A person's own chats; an admin also sees those from before sign-in. No user: every chat."""
    _ensure_tables(store)
    where = ""
    args: tuple[str, ...] = ()
    if user_id:
        where = "WHERE c.user_id = ?" + (" OR c.user_id IS NULL" if admin else "")
        args = (user_id,)
    return [dict(r) for r in store.db.execute(
        "SELECT c.id, c.title, c.updated_at, COUNT(t.seq) turns FROM chat c LEFT JOIN chat_turn t ON t.chat_id=c.id "
        f"{where} GROUP BY c.id ORDER BY c.updated_at DESC LIMIT 100", args)]


def chat_owner(store: Store, chat_id: str) -> tuple[bool, str | None]:
    """Whether the chat exists, and whose it is."""
    _ensure_tables(store)
    r = store.db.execute("SELECT user_id FROM chat WHERE id=?", (chat_id,)).fetchone()
    return (r is not None, r["user_id"] if r else None)


def get_chat(store: Store, chat_id: str) -> dict[str, Any] | None:
    _ensure_tables(store)
    c = store.db.execute("SELECT * FROM chat WHERE id=?", (chat_id,)).fetchone()
    if c is None:
        return None
    turns = []
    for r in store.db.execute("SELECT * FROM chat_turn WHERE chat_id=? ORDER BY seq", (chat_id,)):
        fb = store.db.execute("SELECT verdict, correction, user FROM feedback WHERE answer_id=? "
                              "ORDER BY created_at DESC LIMIT 1", (r["answer_id"],)).fetchone()
        turns.append({**dict(r), "events": json.loads(r["events"] or "[]"), "feedback": dict(fb) if fb else None,
                      "checks": json.loads(r["checks"]) if r["checks"] else None})
    return {**dict(c), "turns": turns}


def delete_chat(store: Store, chat_id: str) -> None:
    _ensure_tables(store)
    store.db.execute("DELETE FROM chat_turn WHERE chat_id=?", (chat_id,))
    store.db.execute("DELETE FROM chat WHERE id=?", (chat_id,))
    store.commit()


def record_feedback(store: Store, answer_id: str, verdict: str, correction: str, user: str) -> None:
    if verdict not in ("up", "down"):
        raise ValueError("verdict must be up or down")
    store.db.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?)",
                     (uuid.uuid4().hex[:12], answer_id, user or "anonymous", verdict, correction, now()))
    store.commit()


# ------------------------------------------------------------------ run

HEARTBEAT_S = 10          # ping the browser this often while Claude Code is quiet
STALL_S = 300             # no output at all for this long: Claude Code is stuck
MAX_S = 1200              # hard cap on one answer


RETRY_NOTE = ("[The reader asked for this to be answered again, replacing your previous answer to it, which they may "
              "think is wrong or incomplete. Work it out afresh: re-check the code and, where it matters, the data. "
              "Don't lean on your previous answer.]\n\n")
EDIT_NOTE = ("[The reader replaced their previous question with the one below. Ignore your answer to the previous "
             "question; answer this one.]\n\n")


def ask(store: Store, cfg: Config, question: str, chat_id: str | None = None,
        person: Person | None = None, replace_last: bool = False) -> Iterator[Event]:
    """Stream one answer.  Yields UI events; the last one is `done` (or `error`).
    replace_last: a retry or an edit of the chat's latest question -- the new answer takes that turn's place."""
    _ensure_tables(store)
    question = question.strip()
    if not question:
        yield {"type": "error", "message": "Empty question"}
        return
    chat = store.db.execute("SELECT * FROM chat WHERE id=?", (chat_id,)).fetchone() if chat_id else None
    if chat is None:
        chat_id = uuid.uuid4().hex[:12]
        store.db.execute("INSERT INTO chat (id, title, session_id, created_at, updated_at, user_id) "
                         "VALUES (?,?,?,?,?,?)", (chat_id, question[:90], None, now(), now(),
                                                  person.user_id if person else None))
        store.commit()
        resume = None
    else:
        resume = chat["session_id"]
    prompt = question
    replaced: int | None = None          # the turn the new answer takes the place of, once it has finished
    if chat is not None and replace_last:
        last = store.db.execute("SELECT seq, question FROM chat_turn WHERE chat_id=? ORDER BY seq DESC LIMIT 1",
                                (chat_id,)).fetchone()
        if last is not None:
            replaced = int(last["seq"])
            # Claude Code can't rewind a session, so: the first question starts afresh; a later one keeps the
            # earlier context and is told to set the replaced answer aside
            if replaced == 1:
                resume = None
            else:
                prompt = (RETRY_NOTE if last["question"].strip() == question else EDIT_NOTE) + question
    yield {"type": "chat", "chat_id": chat_id}

    try:
        cmd = build_command(cfg, prompt, resume, person)
    except ChatUnavailable as e:
        yield {"type": "error", "message": str(e)}
        return

    state: dict[str, Any] = {"text": "", "session_id": None, "result": None}
    events: list[Event] = []
    errlog = ROOT / ".data" / "chat-stderr.log"
    errf = errlog.open("a")
    proc = subprocess.Popen(cmd, cwd=workspace(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=errf, text=True, bufsize=1, env=_env(person))
    # read Claude Code's output on a thread, so this loop can send heartbeats while it thinks
    # (proxies drop a silent stream) and give up if it stops producing anything at all
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        try:
            for ln in proc.stdout:
                lines.put(ln)
        finally:
            lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    started = last = time.monotonic()
    stalled = None
    try:
        while True:
            try:
                line = lines.get(timeout=HEARTBEAT_S)
            except queue.Empty:
                idle, total = time.monotonic() - last, time.monotonic() - started
                if idle > STALL_S:
                    stalled = f"Claude Code sent nothing for {int(idle // 60)} minutes and was stopped."
                    break
                if total > MAX_S:
                    stalled = f"The answer took longer than {MAX_S // 60} minutes and was stopped."
                    break
                yield {"type": "ping", "elapsed": int(total)}
                continue
            if line is None:
                break
            last = time.monotonic()
            for ev in translate(line, state):
                if ev["type"] != "text":
                    events.append(ev)
                yield ev
        if stalled is None:
            proc.wait(timeout=30)
    except GeneratorExit:              # browser went away (or Stop): stop Claude Code too
        proc.kill()
        raise
    finally:
        if proc.poll() is None:
            proc.kill()
        errf.close()
    if stalled:
        yield {"type": "error", "message": f"{stalled} Ask again, or ask a narrower question."}
        return

    if proc.returncode not in (0, None) and not state["result"]:
        err = errlog.read_text(errors="replace")[-600:]
        yield {"type": "error", "message": f"Claude Code exited with {proc.returncode}: {err.strip()}"}
        return

    res = state["result"] or {}
    answer = state["text"].strip() or str(res.get("result") or "")
    answer_id = uuid.uuid4().hex[:12]
    cites = sorted({f"{m.group(1)}:{m.group(2)}" for m in _CITE.finditer(answer)})
    tools_used = [e["name"] for e in events if e["type"] == "tool"]
    store.db.execute("INSERT INTO answer VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (answer_id, (person.name if person else "") or "local", question, answer, json.dumps(cites),
                      json.dumps(tools_used),
                      json.dumps({"backend": "claude-code", "session_id": state["session_id"], "chat_id": chat_id}),
                      state.get("model") or cfg.chat.model, "ask-atlas-v1", now()))
    if replaced is not None:             # the new answer arrived: now the old one goes
        store.db.execute("DELETE FROM chat_turn WHERE chat_id=? AND seq=?", (chat_id, replaced))
        if replaced == 1:
            store.db.execute("UPDATE chat SET title=?, session_id=NULL WHERE id=?", (question[:90], chat_id))
    checks = citecheck.check(store, answer)
    seq = store.db.execute("SELECT COUNT(*) n FROM chat_turn WHERE chat_id=?", (chat_id,)).fetchone()["n"] + 1
    store.db.execute("INSERT INTO chat_turn (chat_id, seq, question, answer, events, answer_id, cost_usd, "
                     "duration_ms, created_at, checks) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (chat_id, seq, question, answer, json.dumps(events), answer_id,
                      res.get("total_cost_usd"), res.get("duration_ms"), now(), json.dumps(checks)))
    store.db.execute("UPDATE chat SET session_id=COALESCE(?, session_id), updated_at=? WHERE id=?",
                     (state["session_id"], now(), chat_id))
    store.commit()
    yield {"type": "done", "chat_id": chat_id, "answer_id": answer_id, "cost_usd": res.get("total_cost_usd"),
           "duration_ms": res.get("duration_ms"), "turns": res.get("num_turns"), "cites": cites, "checks": checks}


def describe_tool(name: str, args: dict[str, Any]) -> str:
    """A tool call as a progress line a person can read."""
    a = args or {}
    f = f"{a.get('pick_file', '')}<{a.get('attr', '')}>"
    return {
        "field_info": f"Reading what {f} holds",
        "who_writes": f"Finding programs that write {f}",
        "who_reads": f"Finding programs that read {f}",
        "read_lines": f"Reading {a.get('name', '')} lines {a.get('start', '')}–{a.get('end', '')}",
        "program_overview": f"Looking at program {a.get('name', '')}",
        "callers": f"Finding who calls {a.get('name', '')}",
        "search_code": f"Searching the code for “{a.get('text', '')}”",
        "search": f"Searching Atlas for “{a.get('q', '')}”",
        "file_detail": f"Looking at file {a.get('pick_file', '')}",
        "flow": f"Tracing the flow of {a.get('name', '')}",
        "menu": f"Looking at menu {a.get('code', '')}",
        "drift": f"Checking TEST version of {a.get('name', '')}",
        "fact_lookup": "Checking what Atlas already knows",
        "search_meaning": f"Searching by meaning for “{a.get('description', '')}”",
        "status": "Checking Atlas status",
        "trace_field": f"Tracing the journey of {f}",
        "process_flow": f"Laying out the {a.get('process_key', 'transfer')} process",
        "processes": "Listing the business processes",
        "test_data_fields": f"Reading the fields of {a.get('pick_file', '')}",
        "test_data_link": f"Building a Test data search on {a.get('pick_file', '')}",
        "live_examples": f"Reading real {a.get('pick_file', '')} records from TEST",
        "live_record": f"Reading {a.get('pick_file', '')} {a.get('key', '')} from TEST",
    }.get(name, f"Using {name}")


def run_structured(cfg: Config, prompt: str, schema: dict[str, Any], effort: str = "medium",
                   timeout_s: int = 900, log: Any = None, person: Person | None = None,
                   tools: bool = True) -> dict[str, Any]:
    """One Claude Code call (the user's login, Atlas tools only) that must answer with JSON
    matching `schema`. Streams its progress to `log` (one readable line per tool call).
    Returns {"output": ..., "cost_usd": ...}. If `log` raises (a cancelled job), Claude stops."""
    import time
    say = log or (lambda _m: None)
    cmd = build_command(cfg, prompt, None, person)
    if "--effort" in cmd:
        cmd[cmd.index("--effort") + 1] = effort
    cmd = [c for c in cmd if c != "--include-partial-messages"]   # whole messages are enough here
    if not tools:                     # everything is in the prompt: no Atlas tools, so no wandering off
        for flag in ("--mcp-config", "--allowedTools"):
            i = cmd.index(flag)
            del cmd[i:i + 2]
        cmd[cmd.index("--append-system-prompt") + 1] = (
            "You document a legacy Pick/UniVerse BASIC ERP for developers migrating it. Everything you need is in "
            "the prompt; describe only what the code shown does.")
    cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.monotonic()
    errlog = (ROOT / ".data" / "chat-stderr.log").open("a")
    proc = subprocess.Popen(cmd, cwd=workspace(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=errlog, text=True, bufsize=1, env=_env(person))
    result: dict[str, Any] | None = None
    lookups = 0
    model = ""
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if time.monotonic() - t0 > timeout_s:
                raise RuntimeError(f"Claude Code took longer than {timeout_s // 60} minutes")
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t == "system" and d.get("subtype") == "init":
                model = str(d.get("model") or "")
                say("Claude Code started" + (f" ({model})" if model else ""))
            elif t == "assistant":
                for b in d.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use":
                        name = _short_tool(b.get("name", ""))
                        if name == "StructuredOutput":
                            say("Writing the answer…")
                        else:
                            lookups += 1
                            say(describe_tool(name, b.get("input", {})))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        say("Thinking: " + " ".join(b["text"].split())[:180])
            elif t == "result":
                result = d
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
        errlog.close()
    if result is None:
        raise RuntimeError(f"Claude Code returned no result (exit {proc.returncode})")
    if result.get("is_error"):
        raise RuntimeError(str(result.get("result") or "Claude Code reported an error"))
    out = result.get("structured_output")
    if out is None:
        try:
            out = json.loads(str(result.get("result") or ""))
        except json.JSONDecodeError:
            out = {}
    say(f"Claude Code finished in {round(time.monotonic() - t0)} s after {lookups} lookup{'s' if lookups != 1 else ''}")
    return {"output": out or {}, "cost_usd": result.get("total_cost_usd"), "model": model}
