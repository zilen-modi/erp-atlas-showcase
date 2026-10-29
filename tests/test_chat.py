import json

from atlas import chat
from atlas.config import load


def run(lines):
    state = {"text": "", "session_id": None, "result": None}
    events = [e for ln in lines for e in chat.translate(json.dumps(ln), state)]
    return events, state


def delta(text):
    return {"type": "stream_event", "event": {"type": "content_block_delta",
                                              "delta": {"type": "text_delta", "text": text}}}


def init(status="connected"):
    return {"type": "system", "subtype": "init", "session_id": "s1", "model": "claude-opus-5",
            "mcp_servers": [{"name": "erp-atlas", "status": status}]}


def test_translate_stream_json():
    events, state = run([
        init(),
        delta("Hi "),
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "mcp__erp-atlas__field_info",
             "input": {"pick_file": "TRANSFER", "attr": 88}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "{\"attr\":88}"}]}},
        {"type": "stream_event", "event": {"type": "message_start"}},
        delta("done"),
        {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.1},
    ])
    kinds = [e["type"] for e in events]
    assert kinds == ["text", "tool", "tool_result", "text", "text"]
    assert events[1]["name"] == "field_info" and events[1]["input"]["attr"] == 88
    assert state["session_id"] == "s1" and state["text"] == "Hi \n\ndone"


def test_errors_surface():
    events, _ = run([
        init("failed"),
        {"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"},
    ])
    assert [e["type"] for e in events] == ["error", "error"]
    assert "sign in" in events[1]["message"]


def test_command_is_locked_down():
    cmd = chat.build_command(load(), "q", "sess-1")
    i = cmd.index("--tools")
    assert cmd[i + 1] == ""                                     # no built-in tools at all
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__erp-atlas__*"
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--resume") + 1] == "sess-1"
    cfg = json.loads(chat.mcp_config_path().read_text())
    assert cfg["mcpServers"]["erp-atlas"]["env"]["ATLAS_PROPOSER"] == chat.PROPOSER
    assert cfg["mcpServers"]["erp-atlas"]["env"]["ATLAS_LIVE_EXAMPLES"] == "6"     # a few TEST reads per answer


def test_heartbeats_then_stall_is_reported(monkeypatch, tmp_path):
    """A Claude Code that goes silent: the stream keeps pinging, then gives up with a clear error."""
    import sys

    from atlas import chat as chatmod
    from atlas import config as cfgmod
    from atlas.store.db import Store
    monkeypatch.setattr(chatmod, "HEARTBEAT_S", 0.2)
    monkeypatch.setattr(chatmod, "STALL_S", 0.7)
    silent = [sys.executable, "-c", "import time; time.sleep(30)"]
    monkeypatch.setattr(chatmod, "build_command", lambda cfg, q, resume, person=None: silent)
    monkeypatch.setattr(chatmod, "workspace", lambda: tmp_path)
    evs = list(chatmod.ask(Store(":memory:"), cfgmod.load(), "anything"))
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "chat" and "ping" in kinds and kinds[-1] == "error"
    assert "sent nothing" in evs[-1]["message"]


def test_retry_and_edit_replace_the_last_answer_only_once_it_arrives(monkeypatch, tmp_path):
    import json as _json
    import sys

    from atlas import chat as chatmod
    from atlas import config as cfgmod
    from atlas.store.db import Store
    sent: list[tuple[str, str | None]] = []

    def fake_claude(answer, fail=False):
        lines = [{"type": "system", "subtype": "init", "session_id": "s-new"},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}},
                 {"type": "result", "result": answer, "session_id": "s-new", "total_cost_usd": 0.01}]
        prints = "".join(f"print({_json.dumps(_json.dumps(x))})\n" for x in lines)
        code = "import sys\n" + ("sys.exit(3)" if fail else prints)
        return [sys.executable, "-c", code]

    answers = iter(["first answer", "second answer", "BOOM", "edited answer", "retried answer"])

    def build(cfg, q, resume, person=None):
        sent.append((q, resume))
        a = next(answers)
        return fake_claude(a, fail=a == "BOOM")
    monkeypatch.setattr(chatmod, "build_command", build)
    monkeypatch.setattr(chatmod, "workspace", lambda: tmp_path)
    st, cfg = Store(":memory:"), cfgmod.load()
    cid = list(chatmod.ask(st, cfg, "Is MIS an SPN?"))[0]["chat_id"]
    list(chatmod.ask(st, cfg, "And MISSHIP?", cid))
    turns = lambda: [(t["seq"], t["question"], t["answer"]) for t in st.db.execute(  # noqa: E731
        "SELECT * FROM chat_turn WHERE chat_id=? ORDER BY seq", (cid,))]
    evs = list(chatmod.ask(st, cfg, "And MISSHIP?", cid, replace_last=True))          # retry fails...
    assert evs[-1]["type"] == "error" and turns()[-1][2] == "second answer"          # ...the old answer stays
    list(chatmod.ask(st, cfg, "And MISSHIP, on TEST?", cid, replace_last=True))       # an edit
    assert sent[-1][0].startswith(chatmod.EDIT_NOTE) and sent[-1][1] is not None     # keeps the context
    assert turns() == [(1, "Is MIS an SPN?", "first answer"), (2, "And MISSHIP, on TEST?", "edited answer")]
    st.db.execute("DELETE FROM chat_turn WHERE chat_id=? AND seq=2", (cid,))
    list(chatmod.ask(st, cfg, "Is MIS an SPN?", cid, replace_last=True))              # retry the only question
    assert sent[-1] == ("Is MIS an SPN?", None)                                      # starts afresh
    assert turns() == [(1, "Is MIS an SPN?", "retried answer")]
