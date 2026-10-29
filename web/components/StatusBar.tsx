"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "@/components/Toaster";

type Probe = { ok: boolean; ms?: number; error?: string; url?: string; host?: string };
type Health = { api: Probe; python_layer: Probe; universe: Probe; vpn_required?: boolean; environment: string; checked_at: string };

const HELP: Record<string, string> = {
  api: "Start it with: uv run atlas serve",
  python_layer: "Start the python-layer Docker container, or change its URL in Settings.",
  universe: "Connect the VPN. TEST reads, captures and deployment checks need it.",
};

// Live connection status in the top bar: Atlas API, python layer, and VPN (UniVerse reachable).
export default function StatusBar() {
  const router = useRouter();
  const [h, setH] = useState<Health | null>(null);
  const [apiDown, setApiDown] = useState(false);
  const prev = useRef<Record<string, boolean>>({});

  const check = useCallback(async (fresh = false) => {
    const r = await fetch(`/api/health${fresh ? "?fresh=true" : ""}`).catch(() => null);
    if (!r?.ok) { setApiDown(true); return; }
    setApiDown(false);
    setH(await r.json());
  }, []);

  useEffect(() => {
    check();
    const t = setInterval(() => check(), 20000);
    return () => clearInterval(t);
  }, [check]);

  // tell the user when something goes down, or comes back
  useEffect(() => {
    const now: Record<string, boolean> = {
      api: !apiDown, python_layer: !!h?.python_layer.ok, universe: !!h?.universe.ok || h?.vpn_required === false,
    };
    const label: Record<string, string> = { api: "Atlas API", python_layer: "Python layer", universe: "VPN / UniVerse" };
    for (const k of Object.keys(now)) {
      if (k !== "api" && apiDown) continue;
      if (prev.current[k] === true && now[k] === false) toast.error(`${label[k]} is down`, HELP[k]);
      if (prev.current[k] === false && now[k] === true) toast.success(`${label[k]} is back`);
    }
    if (h || apiDown) prev.current = now;
  }, [h, apiDown]);

  const all: [string, string, boolean | null, string][] = [
    ["python_layer", "Python layer", apiDown ? null : h ? h.python_layer.ok : null,
      h?.python_layer.ok ? `Up at ${h.python_layer.url} (${h.python_layer.ms} ms)` : `Not working at ${h?.python_layer.url ?? "localhost:6000"}${h?.python_layer.error ? ` (${h.python_layer.error})` : ""}. ${HELP.python_layer}`],
    ["universe", "VPN", apiDown ? null : h ? h.universe.ok : null,
      h?.universe.ok ? `Connected: UniVerse ${h.universe.host} reachable (${h.universe.ms} ms)` : `UniVerse ${h?.universe.host ?? ""} not reachable. ${HELP.universe}`],
  ];

  // a remote python layer (e.g. QA) reaches UniVerse on its own: this machine's VPN doesn't matter
  const items = all.filter(([k]) => k !== "universe" || h?.vpn_required !== false);

  return (
    <div className="statusbar">
      {apiDown ? (
        <button className="status-pill down" onClick={() => { toast.error("Atlas API is not running", HELP.api); check(true); }}>
          <span className="sdot down" /> Atlas API down
        </button>
      ) : items.map(([k, label, ok, tip]) => (
        <button key={k} className={`status-pill ${ok === null ? "" : ok ? "up" : "down"}`} title={tip}
          onClick={() => { if (ok === false) { toast.error(`${label} is not connected`, HELP[k]); router.push("/settings"); } check(true); }}>
          <span className={`sdot ${ok === null ? "" : ok ? "up" : "down"}`} /> {label}
        </button>
      ))}
    </div>
  );
}
