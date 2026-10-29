"use client";

import { useEffect, useState } from "react";
import { errorText, toast } from "@/components/Toaster";

type Values = { python_layer_url: string; universe_host: string; universe_port: number | string };
type View = { values: Values; defaults: Values; saved: Partial<Values>; env_override: boolean; file: string };
type Probe = { ok: boolean; ms?: number; error?: string };

// Connection settings: the python layer Atlas reads TEST through, and the UniVerse host the VPN check pings.
export default function SettingsForm() {
  const [view, setView] = useState<View | null>(null);
  const [v, setV] = useState<Values>({ python_layer_url: "", universe_host: "", universe_port: "" });
  const [busy, setBusy] = useState<"" | "test" | "save">("");
  const [probe, setProbe] = useState<{ python_layer: Probe; universe: Probe; vpn_required?: boolean } | null>(null);

  function load(d: View) {
    setView(d);
    setV({ python_layer_url: d.values.python_layer_url, universe_host: d.values.universe_host, universe_port: d.values.universe_port });
  }
  useEffect(() => {
    fetch("/api/settings").then(async (r) => (r.ok ? load(await r.json()) : toast.error("Couldn't load settings", await errorText(r))))
      .catch(() => toast.error("Couldn't load settings", "Atlas API is not reachable. Start it with: uv run atlas serve"));
  }, []);

  async function send(method: "POST" | "PUT", body: Values) {
    const r = await fetch(method === "POST" ? "/api/settings/test" : "/api/settings", {
      method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).catch(() => null);
    if (!r?.ok) { toast.error(method === "POST" ? "Test failed" : "Couldn't save", await errorText(r)); return null; }
    return r.json();
  }
  async function test() {
    setBusy("test");
    const d = await send("POST", v);
    setBusy("");
    if (!d) return;
    setProbe(d);
    const vpnOk = d.universe.ok || !d.vpn_required;
    if (d.python_layer.ok && vpnOk) toast.success("Connection works", d.vpn_required ? "Python layer is up and UniVerse is reachable." : "Python layer is up. It's remote, so this machine's VPN isn't needed.");
    else toast.error("Connection check failed", [!d.python_layer.ok && (d.python_layer.error ?? "python layer not reachable"), !vpnOk && "UniVerse not reachable (VPN?)"].filter(Boolean).join(", "));
  }
  async function save(body: Values) {
    setBusy("save");
    const d = await send("PUT", body);
    setBusy("");
    if (!d) return;
    load(d);
    setProbe({ python_layer: d.health.python_layer, universe: d.health.universe, vpn_required: d.health.vpn_required });
    toast.success("Settings saved", d.health.python_layer.ok ? "Atlas now reads TEST through the new python layer." : "Saved, but the python layer isn't reachable at that URL yet.");
  }

  if (!view) return <section className="card"><div className="card-body sub">Loading…</div></section>;
  const dirty = v.python_layer_url !== view.values.python_layer_url || v.universe_host !== view.values.universe_host
    || String(v.universe_port) !== String(view.values.universe_port);
  const custom = Object.keys(view.saved).length > 0;
  const pill = (p?: Probe) => p && <span className={`badge ${p.ok ? "green" : "red"}`} title={p.error}>{p.ok ? `OK · ${p.ms} ms` : p.error?.startsWith("HTTP") ? "wrong URL" : p.error ?? "unreachable"}</span>;
  const remote = probe ? probe.vpn_required === false : !/^https?:\/\/(localhost|127\.0\.0\.1|host\.docker\.internal)(:|\/|$)/i.test(v.python_layer_url);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Connection</h2>
        <span className="sub">{custom ? "Custom settings" : "Using defaults from config/policy.yaml"}</span>
      </div>
      <div className="card-body stack">
        {view.env_override && (
          <div className="st-note">UNIVERSE_API_URL is set in the environment of <code>atlas serve</code>; it wins over the URL saved here.</div>
        )}
        <label className="setting">
          <span>Python layer URL {pill(probe?.python_layer)}</span>
          <input className="mono" value={v.python_layer_url} placeholder={view.defaults.python_layer_url}
            onChange={(e) => setV({ ...v, python_layer_url: e.target.value })} />
          <small className="faint">e.g. http://localhost:6000 (local Docker, needs VPN) or https://qa.example.com/api/universe/v1 (a remote server). <code>/api/v1</code> is added if the URL has no <code>/api/</code> path. Use <code>localhost</code>, not 127.0.0.1: the python layer rejects it.</small>
        </label>
        <div className="form-grid three">
          <label className="setting">
            <span>UniVerse host {remote ? <span className="badge">not needed for a remote python layer</span> : pill(probe?.universe)}</span>
            <input className="mono" value={v.universe_host} placeholder={String(view.defaults.universe_host)}
              onChange={(e) => setV({ ...v, universe_host: e.target.value })} />
          </label>
          <label className="setting">
            <span>UniVerse port</span>
            <input className="mono" value={v.universe_port} placeholder={String(view.defaults.universe_port)}
              onChange={(e) => setV({ ...v, universe_port: e.target.value })} />
          </label>
        </div>
        <small className="faint">The UniVerse host and port are only used for the VPN check (a TCP connect, no data), and only when the python layer runs on this machine. Atlas only ever reads: the endpoint allowlist is fixed in code.</small>
      </div>
      <div className="card-foot">
        <span className="faint">Saved in <code>{view.file}</code></span>
        <span className="spacer" />
        {custom && <button className="ghost" disabled={!!busy} onClick={() => save({ python_layer_url: "", universe_host: "", universe_port: "" })}>Reset to defaults</button>}
        <button disabled={!!busy} onClick={test}>{busy === "test" ? <><span className="spinner" /> Testing…</> : "Test connection"}</button>
        <button className="primary" disabled={!!busy || !dirty} onClick={() => save(v)}>{busy === "save" ? "Saving…" : "Save"}</button>
      </div>
    </section>
  );
}
