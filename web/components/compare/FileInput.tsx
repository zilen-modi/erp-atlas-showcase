"use client";

import { useEffect, useId, useState } from "react";

// Text input with Pick file suggestions from the index.
export default function FileInput({ value, onChange, placeholder = "e.g. TRANSFER" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const id = useId();
  const [opts, setOpts] = useState<string[]>([]);
  useEffect(() => {
    const t = setTimeout(async () => {
      const r = await fetch(`/api/files?q=${encodeURIComponent(value.trim())}`).catch(() => null);
      if (r?.ok) setOpts(((await r.json()).files as any[]).slice(0, 30).map((f) => f.file));
    }, 180);
    return () => clearTimeout(t);
  }, [value]);
  return (
    <>
      <input list={id} value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} placeholder={placeholder}
        className="mono" autoComplete="off" spellCheck={false} />
      <datalist id={id}>{opts.map((o) => <option key={o} value={o} />)}</datalist>
    </>
  );
}
