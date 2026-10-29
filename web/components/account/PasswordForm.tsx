"use client";

import { useState } from "react";
import { errorText, toast } from "@/components/Toaster";

// Change your password. `first` is the forced change after signing in with a one-time password.
export default function PasswordForm({ first = false, onDone }: { first?: boolean; onDone?: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mismatch = again.length > 0 && again !== next;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    const r = await fetch("/api/account/password", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current, new: next }),
    }).catch(() => null);
    setBusy(false);
    if (!r?.ok) { setError(await errorText(r)); return; }
    setCurrent(""); setNext(""); setAgain("");
    toast.success("Password changed");
    onDone?.();
  }

  return (
    <form className="stack" onSubmit={submit}>
      <label className="setting"><span>{first ? "One-time password" : "Current password"}</span>
        <input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
      </label>
      <label className="setting"><span>New password</span>
        <input type="password" autoComplete="new-password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} />
        <small className="faint">At least 8 characters.</small>
      </label>
      <label className="setting"><span>New password again</span>
        <input type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} />
      </label>
      {(error || mismatch) && <p className="st-note" role="alert">{mismatch ? "The new passwords don't match" : error}</p>}
      <div><button className="primary" disabled={busy || next.length < 8 || next !== again || !current}>{busy ? "Saving…" : first ? "Set password and continue" : "Change password"}</button></div>
    </form>
  );
}
