"use client";

import { useEffect, useState } from "react";
import { errorText, toast } from "@/components/Toaster";

type Models = { default: string; options: { id: string; label: string }[]; mine: string };

// The Claude model this person's questions run on. Saved to their account, so Ask Atlas and
// "Describe the record you need" both use it, on any device.
export default function ModelPicker({ compact = false }: { compact?: boolean }) {
  const [m, setM] = useState<Models | null>(null);
  useEffect(() => { fetch("/api/models").then((r) => (r.ok ? r.json() : null)).then(setM).catch(() => null); }, []);

  async function pick(model: string) {
    const prev = m;
    setM(m && { ...m, mine: model });
    const r = await fetch("/api/account/model", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }),
    }).catch(() => null);
    if (!r?.ok) { setM(prev); toast.error("Couldn't change the model", await errorText(r)); }
    else if (!compact) toast.success("Model saved", "Your next question uses it.");
  }

  if (!m) return null;
  const name = (id: string) => m.options.find((o) => o.id === id)?.label.split(" · ")[0] ?? id;
  return (
    <select className={compact ? "model-pick compact" : "model-pick"} value={m.mine} onChange={(e) => pick(e.target.value)}
      aria-label="Claude model" title="Which Claude model answers your questions">
      <option value="">{compact ? `Default (${name(m.default)})` : `Server default · ${name(m.default)}`}</option>
      {m.options.map((o) => <option key={o.id} value={o.id}>{compact ? o.label.split(" · ")[0] : o.label}</option>)}
    </select>
  );
}
