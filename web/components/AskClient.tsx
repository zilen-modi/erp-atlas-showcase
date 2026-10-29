"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { isPrint } from "@/lib/print";
import ModelPicker from "@/components/account/ModelPicker";
import AtlasMarkdown from "@/components/AtlasMarkdown";
import {
  CheckIcon, CopyIcon, EditIcon, PlusIcon, SendIcon, SparkIcon, SyncIcon, ThumbDownIcon, ThumbUpIcon, TrashIcon,
} from "@/components/Icons";
import { toast } from "@/components/Toaster";

type Step = { id: string; name: string; input: Record<string, unknown>; done?: boolean; error?: boolean; preview?: string };
type Checks = { cites: number; ok: number; problems: { cite: string; why: string }[] };
type Turn = {
  checks?: Checks | null;       // the answer's citations, checked against git when it was written
  question: string;
  answer: string;
  steps: Step[];
  answerId?: string;
  cost?: number | null;
  durationMs?: number | null;
  error?: string;
  streaming?: boolean;
  elapsed?: number;
  feedback?: { verdict: string; correction?: string } | null;
};
type ChatSummary = { id: string; title: string; updated_at: string; turns: number };

const EXAMPLES: [string, string][] = [
  ["Flow", "Walk me through what happens when a user saves a new transfer in M4401."],
  ["Field", "What is TRANSFER<88> and who writes it? DICT doesn't name it."],
  ["Data", "Which Pick files does order entry (LG.ORDER.MAINT) write to, and which matter most?"],
  ["Program", "Explain what LG.KIT.EXPLODE does, in plain language."],
];

const TOOL_LABEL: Record<string, string> = {
  search: "Searched", flow: "Traced flow", read_lines: "Read code", program_overview: "Looked at program",
  who_writes: "Found writers of", who_reads: "Found readers of", field_info: "Looked up field", file_detail: "Looked up file",
  drift: "Checked TEST version of", callers: "Found callers of", menu: "Looked up menu", search_code: "Searched code for",
  fact_lookup: "Checked notes on", fact_propose: "Noted", status: "Checked index status",
};

function stepLabel(s: Step) {
  const vals = Object.entries(s.input ?? {})
    .filter(([k, v]) => typeof v !== "object" && !["provenance", "limit", "proposed_by", "kind", "rationale"].includes(k))
    .map(([, v]) => String(v));
  const args = s.name === "fact_propose" ? String((s.input as any).scope ?? "") : vals.slice(0, 3).join(" ");
  return `${TOOL_LABEL[s.name] ?? s.name} ${args}`.trim();
}

function readName(): string {
  try { return localStorage.getItem("atlas.reviewer") ?? ""; } catch { return ""; }
}

function eventsToSteps(events: any[]): Step[] {
  const steps: Step[] = [];
  for (const e of events) {
    if (e.type === "tool") steps.push({ id: e.id, name: e.name, input: e.input, done: false });
    if (e.type === "tool_result") {
      const s = steps.find((x) => x.id === e.id);
      if (s) Object.assign(s, { done: true, error: e.error, preview: e.preview });
    }
  }
  return steps;
}

function Activity({ steps, streaming, elapsed }: { steps: Step[]; streaming?: boolean; elapsed?: number }) {
  if (steps.length === 0) {
    return streaming ? <div className="activity"><div className="row" style={{ padding: "8px 12px" }}><span className="spinner" /> Thinking…{elapsed ? <span className="faint"> {elapsed}s</span> : null}</div></div> : null;
  }
  const running = steps.filter((s) => !s.done).length;
  return (
    <details className="activity" open={streaming}>
      <summary>
        {streaming && running > 0 ? <span className="spinner" /> : <CheckIcon size={14} />}
        {streaming && running > 0 ? `Looking things up… (${steps.length})${elapsed ? ` · ${elapsed}s` : ""}` : `Looked up ${steps.length} thing${steps.length === 1 ? "" : "s"} in Atlas`}
      </summary>
      <div className="steps">
        {steps.map((s) => (
          <div key={s.id} className="step" title={s.preview}>
            {!s.done ? <span className="spinner" /> : s.error ? <span className="bad">✕</span> : <CheckIcon size={13} className="ok" />}
            <code>{stepLabel(s)}</code>
          </div>
        ))}
      </div>
    </details>
  );
}

// Every PROGRAM:line the answer cites, checked against the git code when it was written: does the line exist,
// and does quoted code match it? A made-up or misquoted line shows here instead of being trusted.
function CiteBadge({ checks }: { checks?: Checks | null }) {
  const [open, setOpen] = useState(false);
  if (!checks || checks.cites === 0) return null;
  const bad = checks.problems.length;
  if (!bad) return <span className="cite-ok" title="Every cited line exists in git, and quoted code matches it">✓ {checks.cites} citation{checks.cites === 1 ? "" : "s"} checked</span>;
  return (
    <span className="cite-bad-wrap">
      <button className="ghost sm cite-bad" onClick={() => setOpen(!open)} aria-expanded={open}>
        ⚠ {bad} citation{bad === 1 ? "" : "s"} don't check out
      </button>
      {open && (
        <ul className="cite-problems">
          {checks.problems.map((p, i) => <li key={i}><code>{p.cite}</code> {p.why}</li>)}
          <li className="faint">Checked against the git code when this answer was written. Read those lines before relying on them.</li>
        </ul>
      )}
    </span>
  );
}

function Tools({ turn }: { turn: Turn }) {
  const [verdict, setVerdict] = useState(turn.feedback?.verdict ?? "");
  const [asking, setAsking] = useState(false);
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  if (!turn.answerId) return null;
  async function send(v: string, correction = "") {
    await fetch(`/api/answers/${turn.answerId}/feedback`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict: v, correction, user: readName() }),
    });
    setVerdict(v);
    setAsking(false);
  }
  async function copy() {
    try { await navigator.clipboard.writeText(turn.answer); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  }
  return (
    <>
      <div className="msg-tools">
        <button className="ghost" onClick={copy} title="Copy answer">{copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />} {copied ? "Copied" : "Copy"}</button>
        {verdict ? (
          <span className="sub">{verdict === "up" ? "Marked helpful" : "Marked not helpful"}</span>
        ) : (
          <>
            <button className="ghost icon-btn" onClick={() => send("up")} title="Helpful" aria-label="Helpful"><ThumbUpIcon size={14} /></button>
            <button className="ghost icon-btn" onClick={() => setAsking(true)} title="Not helpful" aria-label="Not helpful"><ThumbDownIcon size={14} /></button>
          </>
        )}
        <CiteBadge checks={turn.checks} />
        <span className="spacer" />
        <span className="faint">
          {turn.durationMs ? `${Math.round(turn.durationMs / 1000)}s` : ""}
          {turn.cost != null ? ` · $${turn.cost.toFixed(2)} of plan usage` : ""}
        </span>
      </div>
      {asking && !verdict && (
        <form className="row" style={{ marginTop: 8 }} onSubmit={(e) => { e.preventDefault(); send("down", text); }}>
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="What was wrong or missing?" style={{ flex: 1 }} />
          <button type="submit" className="primary">Send</button>
          <button type="button" className="ghost" onClick={() => setAsking(false)}>Cancel</button>
        </form>
      )}
    </>
  );
}

export default function AskClient({ initialChat, initialQ }: { initialChat?: string; initialQ?: string }) {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [chatId, setChatId] = useState<string | undefined>(initialChat);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [editing, setEditing] = useState(false);     // the composer holds the latest question, to change and resend
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const autoSent = useRef(false);

  const loadChats = useCallback(async () => {
    const r = await fetch("/api/chats").catch(() => null);
    if (r?.ok) setChats((await r.json()).chats);
  }, []);
  useEffect(() => { loadChats(); }, [loadChats]);

  const openChat = useCallback(async (id: string) => {
    setChatId(id);
    window.history.replaceState(null, "", `/ask?chat=${id}`);
    const r = await fetch(`/api/chats/${id}`);
    if (!r.ok) return;
    const c = await r.json();
    stick.current = true;
    setEditing(false);
    setTurns(c.turns.map((t: any) => ({
      question: t.question, answer: t.answer, steps: eventsToSteps(t.events).map((s) => ({ ...s, done: true })),
      answerId: t.answer_id, cost: t.cost_usd, durationMs: t.duration_ms, feedback: t.feedback, checks: t.checks,
    })));
  }, []);
  useEffect(() => { if (initialChat) openChat(initialChat); }, [initialChat, openChat]);

  // follow the answer while it streams, unless the reader scrolled up
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [turns]);
  function onScroll() {
    const el = scroller.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  // grow the composer with its content
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(200, el.scrollHeight)}px`;
  }, [q]);

  // replace: a retry or an edit of the latest question; its answer is swapped out once the new one arrives
  const ask = useCallback(async (question: string, replace = false) => {
    if (!question.trim() || busy) return;
    setEditing(false);
    const ctl = new AbortController();
    abortRef.current = ctl;
    let lastData = Date.now();
    let finished = false;                      // got "done" or "error"
    // the server pings every 10 s; a minute of nothing means the connection is gone
    const watchdog = setInterval(() => { if (Date.now() - lastData > 60000) ctl.abort("stalled"); }, 5000);
    setBusy(true);
    setQ("");
    stick.current = true;
    const idx = replace ? turns.length - 1 : turns.length;
    const saved = replace && !!turns[idx]?.answerId;     // only a finished answer exists to replace on the server
    setTurns((t) => [...(replace ? t.slice(0, -1) : t), { question, answer: "", steps: [], streaming: true }]);
    const patch = (fn: (t: Turn) => Turn) => setTurns((all) => all.map((t, i) => (i === idx ? fn(t) : t)));
    try {
      const res = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, chat_id: chatId, user: readName(), replace_last: saved }),
        signal: ctl.signal,
      });
      if (!res.ok || !res.body) throw new Error(`Atlas API returned ${res.status}. Is \`uv run atlas serve\` running?`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        lastData = Date.now();
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const p of parts) {
          if (!p.startsWith("data: ")) continue;
          const ev = JSON.parse(p.slice(6));
          if (ev.type === "chat" && ev.chat_id !== chatId) {
            setChatId(ev.chat_id);
            // update the address bar without navigating: a navigation would drop the live stream
            window.history.replaceState(null, "", `/ask?chat=${ev.chat_id}`);
          } else if (ev.type === "text") patch((t) => ({ ...t, answer: t.answer + ev.text }));
          else if (ev.type === "tool") patch((t) => ({ ...t, steps: [...t.steps, { id: ev.id, name: ev.name, input: ev.input }] }));
          else if (ev.type === "tool_result")
            patch((t) => ({ ...t, steps: t.steps.map((s) => (s.id === ev.id ? { ...s, done: true, error: ev.error, preview: ev.preview } : s)) }));
          else if (ev.type === "ping") patch((t) => ({ ...t, elapsed: ev.elapsed }));
          else if (ev.type === "done") { finished = true; patch((t) => ({ ...t, answerId: ev.answer_id, cost: ev.cost_usd, durationMs: ev.duration_ms, checks: ev.checks })); }
          else if (ev.type === "error") { finished = true; toast.error("Ask Atlas hit a problem", ev.message); patch((t) => ({ ...t, error: ev.message })); }
        }
      }
      if (!finished) {
        const msg = "The connection closed before the answer finished. Ask again to retry.";
        toast.error("Answer cut off", msg);
        patch((t) => ({ ...t, error: msg }));
      }
    } catch (e) {
      const reason = ctl.signal.reason;
      const msg = reason === "stopped" ? "Stopped." : reason === "stalled"
        ? "No response from Atlas for a minute; the connection looks dead. Ask again to retry."
        : e instanceof Error ? e.message : String(e);
      if (reason !== "stopped") toast.error("Couldn't get an answer", msg);
      patch((t) => ({ ...t, error: msg }));
    } finally {
      clearInterval(watchdog);
      abortRef.current = null;
      patch((t) => ({ ...t, streaming: false }));
      setBusy(false);
      loadChats();
      box.current?.focus();
    }
  }, [busy, chatId, turns, loadChats]);

  useEffect(() => {
    if (initialQ && !initialChat && !autoSent.current && !isPrint()) {
      autoSent.current = true;
      ask(initialQ);
    }
  }, [initialQ, initialChat, ask]);

  function newChat() {
    setChatId(undefined);
    setTurns([]);
    setEditing(false);
    window.history.replaceState(null, "", "/ask");
    box.current?.focus();
  }

  async function removeChat(id: string) {
    if (!window.confirm("Delete this conversation?")) return;
    await fetch(`/api/chats/${id}`, { method: "DELETE" });
    if (id === chatId) newChat();
    loadChats();
  }

  return (
    <div className="chat">
      {initialChat && turns.length === 0 && <span hidden data-report-busy />}
      <aside className="chat-side">
        <div className="chat-side-head">
          <button className="primary" onClick={newChat}><PlusIcon size={15} /> New question</button>
        </div>
        <div className="chat-list">
          <div className="label">Recent</div>
          {chats.length === 0 && <div className="sub" style={{ padding: "4px 8px" }}>No conversations yet.</div>}
          {chats.map((c) => (
            <div key={c.id} className={`chat-link ${c.id === chatId ? "active" : ""}`}>
              <Link href={`/ask?chat=${c.id}`} title={c.title} onClick={(e) => { e.preventDefault(); openChat(c.id); }}>{c.title}</Link>
              <button className="ghost icon-btn sm" onClick={() => removeChat(c.id)} title="Delete" aria-label="Delete conversation"><TrashIcon size={13} /></button>
            </div>
          ))}
        </div>
      </aside>

      <section className="chat-main">
        <div className="chat-scroll" ref={scroller} onScroll={onScroll}>
          <div className="chat-inner">
            {turns.length === 0 && (
              <div className="chat-welcome">
                <div className="logo"><SparkIcon size={22} /></div>
                <h2>Ask anything about the legacy ERP</h2>
                <p>Flows, fields, files and programs. Answers come from the git code, and every citation links to the exact line.</p>
                <div className="examples">
                  {EXAMPLES.map(([k, e]) => (
                    <button key={e} className="example" onClick={() => ask(e)} disabled={busy}>
                      <span className="k">{k}</span>{e}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((t, i) => (
              <div key={i}>
                <div className="msg user"><div className="bubble">{t.question}</div></div>
                <div className="msg bot">
                  <div className="avatar"><SparkIcon size={15} /></div>
                  <div className="body">
                    <Activity steps={t.steps} streaming={t.streaming} elapsed={t.elapsed} />
                    {(t.answer || t.error) && (
                      <div className="answer">
                        {t.answer && <AtlasMarkdown text={t.answer} />}
                        {t.streaming && t.answer && <span className="cursor" />}
                        {t.error && <div className="sub" style={{ marginTop: t.answer ? 10 : 0, color: "var(--bad)" }}>This answer didn't finish.</div>}
                      </div>
                    )}
                    {!t.streaming && <Tools turn={t} />}
                    {!t.streaming && !busy && i === turns.length - 1 && (
                      <div className="msg-redo">
                        <button className="ghost sm" onClick={() => ask(t.question, true)}
                          title={t.answerId ? "Ask the same question again; the new answer replaces this one" : "Try this question again"}>
                          <SyncIcon size={13} /> Retry</button>
                        <button className="ghost sm" onClick={() => { setQ(t.question); setEditing(true); box.current?.focus(); }}
                          title="Change the question and ask again; the new answer replaces this one">
                          <EditIcon size={13} /> Edit question</button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="composer-wrap">
          {editing && (
            <div className="composer-editing">
              <EditIcon size={13} /> Editing your last question: sending replaces its answer.
              <button type="button" className="ghost sm" onClick={() => { setEditing(false); setQ(""); }}>Cancel</button>
            </div>
          )}
          <form className="composer" onSubmit={(e) => { e.preventDefault(); ask(q, editing); }}>
            <textarea
              ref={box}
              rows={1}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q, editing); }
                else if (e.key === "Escape" && editing) { setEditing(false); setQ(""); }
              }}
              placeholder={turns.length ? "Ask a follow-up…" : "Ask about a menu, program, field or flow…"}
              disabled={busy}
              autoFocus
            />
            {busy ? (
              <button className="icon-btn" type="button" aria-label="Stop" title="Stop this answer"
                onClick={() => abortRef.current?.abort("stopped")} style={{ width: 36, height: 36, borderRadius: 10 }}>
                <span className="stop-square" />
              </button>
            ) : (
              <button className="primary icon-btn" type="submit" disabled={!q.trim()} aria-label="Send" style={{ width: 36, height: 36, borderRadius: 10 }}>
                <SendIcon size={16} />
              </button>
            )}
          </form>
          <div className="composer-hint">
            <ModelPicker compact />
            <span>Enter to send · Shift+Enter for a new line · follow-ups keep the context · runs on your Claude</span>
          </div>
        </div>
      </section>
    </div>
  );
}
