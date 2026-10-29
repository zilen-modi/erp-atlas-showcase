"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowIcon, DownloadIcon, ExportIcon, LinkIcon, ReportIcon, SyncIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";

type Report = { id: string; title: string; pages: number; bytes: number; filename: string };

export function shareUrl(id: string) {
  return `${window.location.origin}/reports/${id}`;
}

export async function copy(text: string, what: string) {
  try { await navigator.clipboard.writeText(text); toast.success(`${what} copied`, text); }
  catch { toast.info(what, text); }
}

// The page's own title, for the report: eyebrow + heading ("Compare · 11095 vs 11094").
function pageTitle(): string {
  const h1 = document.querySelector("main h1")?.textContent?.trim();
  const eyebrow = document.querySelector("main .eyebrow")?.textContent?.trim();
  const base = h1 || document.title;
  return eyebrow && h1 ? `${eyebrow} · ${h1}` : base;
}

// Export: the whole page (top bar) or one section of it (the icon in each card's header),
// as a PDF report with a shareable link.
export default function ExportButton({ section, sectionTitle }: { section?: string; sectionTitle?: string } = {}) {
  const path = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Report | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { setDone(null); }, [path]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (path.startsWith("/reports/") && !section) return null;       // already a report

  function sectionPage() {
    const q = new URLSearchParams(window.location.search);
    q.delete("print");
    q.set("section", section!);
    return `${window.location.pathname}?${q}`;
  }
  async function makePdf() {
    setBusy(true);
    const page = section ? sectionPage() : window.location.pathname + window.location.search;
    const title = section ? `${pageTitle()} · ${sectionTitle ?? section}` : pageTitle();
    const r = await fetch("/api/reports", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, title }),
    }).catch(() => null);
    setBusy(false);
    if (!r?.ok) { toast.error("Couldn't create the PDF", await errorText(r)); return; }
    const rep: Report = await r.json();
    setDone(rep);
    setOpen(true);
    toast.success("Report ready", `${rep.pages} page${rep.pages === 1 ? "" : "s"} · ${rep.title}`);
  }

  return (
    <div className={`export ${section ? "export-section" : ""}`} ref={ref}>
      {section ? (
        <button className="ghost icon-btn sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} disabled={busy}
          aria-label={`Export ${sectionTitle ?? "this section"}`} title={`Export “${sectionTitle ?? "this section"}”`}>
          {busy ? <span className="spinner" /> : <ExportIcon size={14} />}
        </button>
      ) : (
        <button className="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} disabled={busy}>
          {busy ? <><span className="spinner" /> Creating PDF…</> : <><ExportIcon size={14} /> Export</>}
        </button>
      )}
      {open && (
        <div className="export-menu" role="menu">
          {done ? (
            <>
              <div className="export-done">
                <ReportIcon size={18} />
                <div style={{ minWidth: 0 }}>
                  <div className="export-done-title" title={done.title}>{done.title}</div>
                  <div className="sub">{done.pages} page{done.pages === 1 ? "" : "s"} · {Math.max(1, Math.round(done.bytes / 1024))} KB</div>
                </div>
              </div>
              <a className="export-item" href={`/api/reports/${done.id}/pdf`} target="_blank" rel="noreferrer"><ReportIcon size={14} /> Open PDF</a>
              <a className="export-item" href={`/api/reports/${done.id}/pdf?download=true`}><DownloadIcon size={14} /> Download PDF</a>
              <button className="export-item" onClick={() => copy(shareUrl(done.id), "Share link")}><LinkIcon size={14} /> Copy share link</button>
              <Link className="export-item" href={`/reports/${done.id}`} onClick={() => setOpen(false)}><ArrowIcon size={14} /> View report page</Link>
              <div className="export-sep" />
              <button className="export-item" onClick={makePdf}><SyncIcon size={14} /> Create again</button>
            </>
          ) : (
            <>
              {section && <div className="export-for sub">“{sectionTitle ?? section}”</div>}
              <button className="export-item" onClick={() => { setOpen(false); makePdf(); }}>
                <ReportIcon size={14} /> {section ? "PDF of this section" : "PDF report of this page"}
              </button>
              <button className="export-item" onClick={() => section
                ? copy(`${window.location.origin}${window.location.pathname}${window.location.search}#${
                  document.querySelector(`[data-section="${CSS.escape(section)}"]`)?.id || `sec-${section}`}`, "Section link")
                : copy(window.location.href, "Page link")}>
                <LinkIcon size={14} /> {section ? "Copy link to this section" : "Copy page link"}
              </button>
            </>
          )}
          <div className="export-sep" />
          <Link className="export-item faint" href="/reports" onClick={() => setOpen(false)}>All reports</Link>
        </div>
      )}
    </div>
  );
}
