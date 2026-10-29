"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChatIcon, SearchIcon, SparkIcon } from "@/components/Icons";

type Hit = { kind: string; program?: string; start?: number | null; end?: number | null; title?: string; summary?: string;
  id?: string; text?: string; status?: string; stale?: boolean };

const enc = encodeURIComponent;

// "What are you looking for?": describe behaviour in words, get the programs whose summaries match.
export default function MeaningBox() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 4) { setHits(null); setNote(""); return; }
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      setBusy(true);
      try {
        const r = await fetch(`/api/meaning?q=${enc(term)}&limit=5`, { signal: ctl.signal });
        const d = r.ok ? await r.json() : null;
        setHits(d?.results ?? []);
        setNote(d?.ready === false ? d.note : "");
      } catch { /* aborted */ } finally { setBusy(false); }
    }, 350);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);

  const term = q.trim();
  return (
    <section className="card mb-box">
      <form className="mb-form" onSubmit={(e) => { e.preventDefault(); if (term) window.location.assign(`/search?q=${enc(term)}&type=meaning`); }}>
        <SparkIcon size={18} />
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Describe what you're looking for"
          placeholder="What are you looking for? e.g. where is a depot backorder released" />
        {busy && <span className="spinner" />}
        {term && <Link className="btn sm" href={`/ask?q=${enc(term)}`}><ChatIcon size={13} /> Ask Atlas</Link>}
      </form>
      {hits && (
        <div className="mb-hits">
          {note && <div className="sub">{note}</div>}
          {!note && hits.length === 0 && <div className="sub">Nothing close yet. Summaries exist for the most-used programs first, so try <Link href={`/search?q=${enc(term)}`}>searching by name</Link> or ask Atlas.</div>}
          {hits.map((h, i) => h.kind === "fact" ? (
            <Link key={`f${h.id}`} href={`/facts?q=${h.id}`} className="mb-hit">
              <span className="mono mb-name">{h.id}</span>
              <span className="mb-text">{h.text}</span>
              <span className={`badge ${h.status === "accepted" ? "green" : ""}`}>{h.status}</span>
            </Link>
          ) : (
            <Link key={`${h.program}${h.start ?? ""}${i}`} className="mb-hit"
              href={h.start ? `/program/${enc(h.program!)}/source?line=${h.start}` : `/program/${enc(h.program!)}`}>
              <span className="mono mb-name">{h.program}{h.start ? <span className="faint">:{h.start}</span> : null}</span>
              <span className="mb-text"><b>{h.title}</b> <span className="sub">{h.summary}</span></span>
              {h.stale && <span className="badge amber">out of date</span>}
            </Link>
          ))}
          {hits.length > 0 && <Link href={`/search?q=${enc(term)}&type=meaning`} className="mb-more"><SearchIcon size={13} /> All matches</Link>}
        </div>
      )}
    </section>
  );
}
