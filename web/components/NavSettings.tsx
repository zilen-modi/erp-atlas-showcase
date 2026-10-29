"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { HIDEABLE } from "@/components/Sidebar";
import { errorText, toast } from "@/components/Toaster";

// Settings → Navigation: choose which tabs show in the sidebar. Saved for everyone using this Atlas;
// hidden pages still open from links, search and the Overview.
export default function NavSettings() {
  const router = useRouter();
  const [hidden, setHidden] = useState<string[] | null>(null);
  useEffect(() => {
    fetch("/api/settings/nav").then(async (r) => setHidden(r.ok ? (await r.json()).hidden : []))
      .catch(() => setHidden([]));
  }, []);

  async function save(next: string[], what: string) {
    const prev = hidden;
    setHidden(next);
    const r = await fetch("/api/settings/nav", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hidden: next }),
    }).catch(() => null);
    if (!r?.ok) { setHidden(prev); toast.error("Couldn't save", await errorText(r)); return; }
    setHidden((await r.json()).hidden);
    router.refresh();                               // the sidebar re-renders with the new list
    toast.success(what);
  }

  if (!hidden) return null;
  const groups = ["Main", "Browse"];
  return (
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h2>Navigation</h2>
        <span className="sub">Tabs shown in the sidebar · {HIDEABLE.length - hidden.length} of {HIDEABLE.length} visible</span>
        <span className="spacer" />
        {hidden.length > 0 && <button className="ghost sm" onClick={() => save([], "All tabs shown")}>Show all</button>}
      </div>
      <div className="card-body nav-settings">
        {groups.map((g) => (
          <div key={g}>
            <div className="sc-h">{g}</div>
            {HIDEABLE.filter((t) => t.group === g).map((t) => {
              const on = !hidden.includes(t.href);
              return (
                <label key={t.href} className="nav-toggle">
                  <span className="switch">
                    <input type="checkbox" checked={on}
                      onChange={() => save(on ? [...hidden, t.href] : hidden.filter((h) => h !== t.href), `${t.label} ${on ? "hidden" : "shown"}`)} />
                    <span className="knob" />
                  </span>
                  <span>{t.label}</span>
                  <span className="faint mono">{t.href}</span>
                </label>
              );
            })}
          </div>
        ))}
      </div>
      <div className="card-foot"><span className="sub">Overview and Settings are always shown. Hidden pages still open from links, search and the Overview.</span></div>
    </section>
  );
}
