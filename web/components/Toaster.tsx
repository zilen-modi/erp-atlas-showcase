"use client";

import { useEffect, useState } from "react";
import { AlertIcon, CheckIcon, CloseIcon } from "@/components/Icons";

type Kind = "error" | "success" | "info";
type Toast = { id: number; kind: Kind; title: string; detail?: string };

const EVENT = "atlas:toast";

// Call from any client component: toast.error("Couldn't save", "HTTP 400: ...")
export const toast = {
  show(kind: Kind, title: string, detail?: string) {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(EVENT, { detail: { kind, title, detail } }));
  },
  error(title: string, detail?: string) { toast.show("error", title, detail); },
  success(title: string, detail?: string) { toast.show("success", title, detail); },
  info(title: string, detail?: string) { toast.show("info", title, detail); },
};

// Read a failed fetch Response into a readable message.
export async function errorText(r: Response | null | undefined): Promise<string> {
  if (!r) return "Atlas API is not reachable. Start it with: uv run atlas serve";
  // the session ended (expired, signed out elsewhere, or deactivated): back to sign-in
  if (r.status === 401 && typeof window !== "undefined") window.location.assign(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
  const d = await r.json().catch(() => ({}));
  return typeof d.detail === "string" ? d.detail : `HTTP ${r.status}`;
}

let seq = 0;

export default function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent).detail as Omit<Toast, "id">;
      const id = ++seq;
      setItems((list) => {
        // the same message twice in a row just refreshes it
        const rest = list.filter((t) => !(t.title === d.title && t.detail === d.detail));
        return [...rest, { id, ...d }].slice(-4);
      });
      setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), d.kind === "error" ? 8000 : 4000);
    };
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return (
    <div className="toaster" role="region" aria-live="polite" aria-label="Notifications">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
          <span className="toast-ico">{t.kind === "error" ? <AlertIcon size={16} /> : <CheckIcon size={16} />}</span>
          <div className="toast-body">
            <b>{t.title}</b>
            {t.detail && <span>{t.detail}</span>}
          </div>
          <button className="ghost icon-btn sm" aria-label="Dismiss" onClick={() => setItems((l) => l.filter((x) => x.id !== t.id))}>
            <CloseIcon size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}

// Server pages that fail to load render this: the message goes to a toast, the page shows a quiet placeholder.
export function ToastOnMount({ title, detail }: { title: string; detail?: string }) {
  useEffect(() => { toast.error(title, detail); }, [title, detail]);
  return null;
}
