"use client";

import { useEffect, useState } from "react";
import { isPrint } from "@/lib/print";

// In print mode (?print=1): switch the page to its print layout and add the report masthead.
// The masthead also shows when a page is printed from the browser (Cmd+P).
export default function PrintMode({ sha, environment }: { sha: string | null; environment: string }) {
  const [at, setAt] = useState("");
  const [waiting, setWaiting] = useState(false);
  useEffect(() => {
    if (isPrint()) document.documentElement.classList.add("print-mode");
    setAt(new Date().toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }));
    const section = isPrint() ? new URLSearchParams(window.location.search).get("section") : null;
    if (!section) return;
    // one section only: hide everything else in <main> except the page header. Sections drawn by
    // client components appear after their data loads, so keep looking (the PDF renderer waits
    // while the busy marker below is present).
    setWaiting(true);
    const started = Date.now();
    const t = setInterval(() => {
      const el = document.querySelector(`[data-section="${CSS.escape(section)}"]`) as HTMLElement | null;
      if (!el && Date.now() - started < 20000) return;
      clearInterval(t);
      if (el) isolate(el);
      setWaiting(false);
    }, 250);
    return () => clearInterval(t);
  }, []);
  return (
    <>
    {waiting && <span hidden data-report-busy />}
    <div className="report-mast" aria-hidden>
      <div className="report-brand">
        <span className="brand-mark">A</span>
        <div>
          <div className="report-name">ERP Atlas</div>
          <div className="report-sub">Legacy Pick ERP · analysis report</div>
        </div>
      </div>
      <dl className="report-meta">
        <div><dt>Generated</dt><dd>{at}</dd></div>
        <div><dt>Source</dt><dd>git main {sha ?? "—"}</dd></div>
        <div><dt>Live data</dt><dd>{environment}</dd></div>
      </dl>
    </div>
    </>
  );
}

function isolate(el: HTMLElement) {
  let node: HTMLElement = el;
  while (node.parentElement && node.tagName !== "MAIN") {
    const parent = node.parentElement;
    for (const sib of Array.from(parent.children) as HTMLElement[]) {
      if (sib !== node && !sib.classList.contains("page-head")) sib.style.display = "none";
    }
    if (parent.tagName !== "MAIN") parent.style.display = "block";    // grids: let the section use the full width
    node = parent;
  }
  el.classList.add("print-focus");
}
