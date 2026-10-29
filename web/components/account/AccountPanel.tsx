"use client";

import { useEffect, useState } from "react";
import ModelPicker from "@/components/account/ModelPicker";
import PasswordForm from "@/components/account/PasswordForm";
import { errorText, toast } from "@/components/Toaster";
import { ago } from "@/lib/api";

type Claude = { kind: "subscription"; hint: string; added_at: string; last_used: string | null } | null;
type Me = { user: { name: string; email: string; role: string; last_login: string | null }; claude: Claude; shared_claude: boolean };

// Subscriptions only: an API key would bill every call, so Atlas doesn't take one.
const HELP = <>Pro, Max, Team or Enterprise. In a terminal run <code>claude setup-token</code>, sign in, and paste the token it prints (it starts <code>sk-ant-oat01-</code>). Usage counts against your plan; Atlas never uses API keys, so nothing is billed per call.</>;

export default function AccountPanel({ welcome }: { welcome: boolean }) {
  const [me, setMe] = useState<Me | null>(null);
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "test" | "remove">("");
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);

  const load = () => fetch("/api/auth/me").then(async (r) => (r.ok ? setMe(await r.json()) : toast.error("Couldn't load your account", await errorText(r))));
  useEffect(() => { load(); }, []);

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy("save"); setTest(null);
    const r = await fetch("/api/account/claude", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "subscription", secret }),
    }).catch(() => null);
    setBusy("");
    if (!r?.ok) { toast.error("Couldn't connect Claude", await errorText(r)); return; }
    setSecret("");
    await load();
    toast.success("Claude connected", "Checking it works…");
    runTest();
  }
  async function runTest() {
    setBusy("test");
    const r = await fetch("/api/account/claude/test", { method: "POST" }).catch(() => null);
    setBusy("");
    setTest(r?.ok ? await r.json() : { ok: false, message: await errorText(r) });
  }
  async function remove() {
    if (!window.confirm("Disconnect your Claude account from Atlas? The saved token is deleted.")) return;
    setBusy("remove");
    await fetch("/api/account/claude", { method: "DELETE" }).catch(() => null);
    setBusy(""); setTest(null);
    load();
  }

  if (!me) return <section className="card"><div className="card-body sub">Loading…</div></section>;
  const c = me.claude;
  return (
    <div className="stack">
      {welcome && !c && (
        <div className="acct-welcome">
          <strong>You're signed in.</strong> One more step: connect your Claude account below so Ask Atlas can answer your questions.
        </div>
      )}
      <section className="card">
        <div className="card-head"><h2>Profile</h2><span className={`badge ${me.user.role === "admin" ? "violet" : ""}`}>{me.user.role}</span></div>
        <div className="card-body acct-profile">
          <div><span className="faint">Name</span>{me.user.name}</div>
          <div><span className="faint">Email</span>{me.user.email}</div>
          <div><span className="faint">Signed in</span>{ago(me.user.last_login)}</div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Claude</h2>
          {c ? <span className="badge green">Connected · Claude subscription {c.hint}</span>
             : me.shared_claude ? <span className="badge">Using the server's Claude</span>
             : <span className="badge red">Not connected</span>}
        </div>
        <div className="card-body stack">
          <p className="sub">Ask Atlas, “Describe the record you need” and AI field names run on <strong>your</strong> Claude account, so usage is yours and your chats stay yours. The token is stored encrypted and is never shown again.</p>
          {c && (
            <div className="acct-claude">
              <span>Added {ago(c.added_at)} · last used {ago(c.last_used)}</span>
              <span className="spacer" />
              {test && <span className={`badge ${test.ok ? "green" : "red"}`} title={test.message}>{test.ok ? "Works" : "Failed"}</span>}
              <button className="sm" onClick={runTest} disabled={!!busy}>{busy === "test" ? "Testing…" : "Test"}</button>
              <button className="sm ghost" onClick={remove} disabled={!!busy}>Disconnect</button>
            </div>
          )}
          {test && !test.ok && <p className="st-note">{test.message}</p>}
          <form className="stack" onSubmit={connect}>
            <label className="setting">
              <span>{c ? "Replace with a new token" : "Claude subscription token"}</span>
              <input type="password" className="mono" autoComplete="off" spellCheck={false} placeholder="sk-ant-oat01-…"
                value={secret} onChange={(e) => setSecret(e.target.value)} />
              <small className="faint">{HELP}</small>
            </label>
            <div><button className="primary" disabled={!!busy || secret.trim().length < 20}>{busy === "save" ? "Connecting…" : c ? "Replace" : "Connect"}</button></div>
          </form>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Model</h2></div>
        <div className="card-body stack">
          <p className="sub">Which Claude model answers your questions. A lighter model is quicker and uses less of your plan; Opus gives the most careful answers on long programs. You can also switch it under the Ask Atlas box.</p>
          <ModelPicker />
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Password</h2></div>
        <div className="card-body"><PasswordForm /></div>
      </section>
    </div>
  );
}
