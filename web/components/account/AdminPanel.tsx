"use client";

import { useEffect, useState } from "react";
import { errorText, toast } from "@/components/Toaster";
import { ago, fmtTime } from "@/lib/api";

type User = { id: string; email: string; name: string; role: "admin" | "member"; active: boolean; must_change: boolean;
  last_login: string | null; claude: { kind: string; hint: string } | null };
type Usage = { id: string; name: string; email: string; asked: number; cost: number; asked_30d: number; cost_30d: number; last_asked: string | null; claude: string | null };
type Audit = { at: string; action: string; detail: Record<string, unknown>; name: string | null; email: string | null };

const money = (n: number) => `$${(n ?? 0).toFixed(2)}`;
const ACTION: Record<string, string> = {
  "login": "Signed in", "login.failed": "Failed sign-in", "login.locked": "Sign-in blocked (too many tries)", "user.create": "Added a user", "user.update": "Changed a user",
  "user.reset_password": "Reset a password", "user.change_password": "Changed their password",
  "claude.connect": "Connected Claude", "claude.disconnect": "Disconnected Claude",
  "fact.accept": "Accepted a fact", "fact.retire": "Retired a fact", "fact.recite": "Re-cited a fact",
  "settings.shared_claude": "Changed shared Claude", "test.read": "Read from TEST", "backup": "Made a backup",
};

// Shows a one-time password once, with a copy button: it isn't stored anywhere it can be read back.
function OneTime({ who, pw, onClose }: { who: string; pw: string; onClose: () => void }) {
  return (
    <div className="acct-onetime" role="status">
      <div><strong>One-time password for {who}</strong><div className="faint">Send it to them privately. It's shown only now; they choose their own at first sign-in.</div></div>
      <code>{pw}</code>
      <button className="sm" onClick={() => { navigator.clipboard?.writeText(pw); toast.success("Copied"); }}>Copy</button>
      <button className="sm ghost" onClick={onClose}>Done</button>
    </div>
  );
}

export default function AdminPanel({ meId }: { meId: string }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [shared, setShared] = useState(false);
  const [backup, setBackup] = useState<{ at: string; count: number; bytes: number } | null>(null);
  const [form, setForm] = useState({ email: "", name: "", role: "member" });
  const [onetime, setOnetime] = useState<{ who: string; pw: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function get(path: string) {
    const r = await fetch(path).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't load", await errorText(r)); return null; }
    return r.json();
  }
  async function load() {
    const [u, g, a, s] = await Promise.all([get("/api/admin/users"), get("/api/admin/usage"), get("/api/admin/audit?limit=100"), get("/api/admin/settings")]);
    if (u) setUsers(u.users);
    if (g) setUsage(g.usage);
    if (a) setAudit(a.audit);
    if (s) { setShared(s.allow_shared_claude); setBackup(s.backup); }
  }
  useEffect(() => { load(); }, []);

  async function send(method: string, path: string, body?: unknown) {
    const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't save", await errorText(r)); return null; }
    return r.json();
  }
  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const d = await send("POST", "/api/admin/users", form);
    setBusy(false);
    if (!d) return;
    setOnetime({ who: d.user.name, pw: d.temp_password });
    setForm({ email: "", name: "", role: "member" });
    load();
  }
  async function edit(u: User, patch: Partial<Pick<User, "role" | "active">>) {
    if (patch.active === false && !window.confirm(`Deactivate ${u.name}? They're signed out and can't sign in until you reactivate them.`)) return;
    if (await send("PATCH", `/api/admin/users/${u.id}`, patch)) load();
  }
  async function reset(u: User) {
    if (!window.confirm(`Give ${u.name} a new one-time password? Their current password stops working and they're signed out.`)) return;
    const d = await send("POST", `/api/admin/users/${u.id}/reset`);
    if (d) { setOnetime({ who: u.name, pw: d.temp_password }); load(); }
  }
  async function backupNow() {
    const r = await fetch("/api/admin/backup", { method: "POST" }).catch(() => null);
    if (!r?.ok) { toast.error("Backup failed", await errorText(r)); return; }
    const d = await r.json();
    setBackup(d.latest);
    toast.success("Backed up", d.path);
  }

  async function toggleShared(on: boolean) {
    const d = await send("PUT", "/api/admin/settings", { allow_shared_claude: on });
    if (d) setShared(d.allow_shared_claude);
  }

  if (!users) return <section className="card"><div className="card-body sub">Loading…</div></section>;
  const spent = usage.reduce((s, u) => s + (u.cost_30d ?? 0), 0);
  return (
    <div className="stack">
      <section className="card">
        <div className="card-head"><h2>People</h2><span className="sub">{users.filter((u) => u.active).length} active · {users.filter((u) => u.role === "admin" && u.active).length} admin</span></div>
        <div className="card-body stack">
          {onetime && <OneTime {...onetime} onClose={() => setOnetime(null)} />}
          <form className="acct-add" onSubmit={add}>
            <input placeholder="Full name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} aria-label="Full name" />
            <input type="email" placeholder="email@acme.com" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} aria-label="Email" />
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} aria-label="Role">
              <option value="member">Member</option><option value="admin">Admin</option>
            </select>
            <button className="primary" disabled={busy || !form.name || !form.email}>Add person</button>
          </form>
          <div className="table-wrap">
            <table className="acct-table">
              <thead><tr><th>Name</th><th>Role</th><th>Claude</th><th>Last sign-in</th><th>Status</th><th /></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className={u.active ? "" : "off"}>
                    <td><div className="acct-name">{u.name}{u.id === meId && <span className="faint"> (you)</span>}</div><div className="faint">{u.email}</div></td>
                    <td>
                      <select value={u.role} disabled={!u.active} onChange={(e) => edit(u, { role: e.target.value as User["role"] })} aria-label={`Role for ${u.name}`}>
                        <option value="member">Member</option><option value="admin">Admin</option>
                      </select>
                    </td>
                    <td>{u.claude ? <span className="badge green">Subscription {u.claude.hint}</span> : <span className="badge">{shared ? "server's" : "none"}</span>}</td>
                    <td>{u.must_change ? <span className="badge amber">waiting for first sign-in</span> : ago(u.last_login)}</td>
                    <td>{u.active ? <span className="badge green">active</span> : <span className="badge red">deactivated</span>}</td>
                    <td className="acct-actions">
                      <button className="sm ghost" onClick={() => reset(u)}>Reset password</button>
                      {u.id !== meId && <button className="sm ghost" onClick={() => edit(u, { active: !u.active })}>{u.active ? "Deactivate" : "Reactivate"}</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Claude usage</h2><span className="sub">{money(spent)} in the last 30 days</span></div>
        <div className="card-body stack">
          <label className="acct-toggle">
            <input type="checkbox" checked={shared} onChange={(e) => toggleShared(e.target.checked)} />
            <span><strong>Let people without their own Claude use the server's</strong><br />
              <small className="faint">Off: everyone connects their own Claude before asking. On: their questions run on the account <code>atlas serve</code> is signed in to, and cost lands there.</small></span>
          </label>
          <div className="table-wrap">
            <table className="acct-table">
              <thead><tr><th>Person</th><th className="num">Questions (30 d)</th><th className="num">Cost (30 d)</th><th className="num">Questions (all)</th><th className="num">Cost (all)</th><th>Last asked</th></tr></thead>
              <tbody>
                {usage.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}</td><td className="num">{u.asked_30d ?? 0}</td><td className="num">{money(u.cost_30d)}</td>
                    <td className="num">{u.asked}</td><td className="num">{money(u.cost)}</td><td>{ago(u.last_asked)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <small className="faint">Cost is what Claude Code reports per answer. On a subscription it counts against that person's plan rather than a bill.</small>
        </div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Backups</h2>
          <span className="sub">{backup ? `Last ${ago(backup.at)} · ${backup.count} kept · ${(backup.bytes / 1e6).toFixed(0)} MB` : "None yet"}</span>
          <span className="spacer" /><button className="sm" onClick={backupNow}>Back up now</button></div>
        <div className="card-body"><p className="sub" style={{ margin: 0 }}>Atlas backs up once a day what git can't rebuild: accounts, confirmed facts, summaries, saved scenarios, compare notes, chats, and the key for saved Claude tokens. The newest 14 are kept in <code>.data/backups</code>, on this machine: copy that folder somewhere else to survive losing it.</p></div>
      </section>

      <section className="card">
        <div className="card-head"><h2>Activity</h2><span className="sub">Sign-ins, account changes and fact reviews</span></div>
        <div className="card-body">
          <ul className="acct-audit">
            {audit.map((a, i) => (
              <li key={i} className={a.action === "login.failed" ? "bad" : ""}>
                <span className="faint" title={a.at}>{fmtTime(a.at)}</span>
                <span>{a.name ?? (a.action === "login.failed" ? String(a.detail.email ?? "someone") : "CLI")}</span>
                <span>{ACTION[a.action] ?? a.action}{a.detail.fact ? ` ${a.detail.fact}` : ""}{a.detail.email && a.action === "user.create" ? `: ${a.detail.email}` : ""}
                  {a.action === "test.read" && <span className="faint"> {String(a.detail.file)} {String(a.detail.what ?? "")} · {a.detail.via === "ask-atlas" ? "Ask Atlas" : "Test data"}</span>}</span>
              </li>
            ))}
            {audit.length === 0 && <li className="faint">Nothing yet.</li>}
          </ul>
        </div>
      </section>
    </div>
  );
}
