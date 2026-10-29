"use client";

import { useState } from "react";
import { errorText } from "@/components/Toaster";

export default function LoginForm({ next }: { next: string }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    const r = await fetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
    }).catch(() => null);
    if (!r?.ok) { setError(await errorText(r)); setBusy(false); return; }
    window.location.assign(next);   // a full load, so the layout picks up the new session
  }

  return (
    <form className="stack" onSubmit={submit}>
      <h1>Sign in</h1>
      <label className="setting"><span>Email</span>
        <input type="email" autoComplete="username" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="setting"><span>Password</span>
        <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p className="st-note" role="alert">{error}</p>}
      <button className="primary" disabled={busy || !email || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      <p className="faint auth-help">Forgotten your password? Ask an Atlas admin to reset it.</p>
    </form>
  );
}
