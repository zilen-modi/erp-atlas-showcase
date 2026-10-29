"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { SearchIcon } from "@/components/Icons";

// Labels (GOSUB targets / event handlers) in a program, filterable.
export default function BlockList({ blocks, current, hrefBase, prov }: {
  blocks: { label: string; line: number }[]; current: string | null; hrefBase: string; prov: string;
}) {
  const [q, setQ] = useState("");
  const list = useRef<HTMLDivElement>(null);
  // bring the block being viewed into sight in the list (not the page)
  useEffect(() => {
    const el = list.current?.querySelector<HTMLElement>("a.active");
    if (el && list.current) list.current.scrollTop = el.offsetTop - list.current.clientHeight / 3;
  }, [current]);
  const shown = useMemo(() => {
    const t = q.trim().toUpperCase();
    return t ? blocks.filter((b) => b.label.includes(t)) : blocks;
  }, [q, blocks]);
  const href = (start: number) => `${hrefBase.split("?")[0]}?${new URLSearchParams({ ...(prov !== "git" ? { prov } : {}), start: String(start) })}`;
  return (
    <div className="card blocklist">
      <div className="card-head" style={{ padding: "10px 12px" }}>
        <h2 style={{ fontSize: 13 }}>Blocks</h2>
        <span className="sub">{blocks.length}</span>
      </div>
      <div className="block-filter">
        <SearchIcon size={14} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter labels" />
      </div>
      <div className="list" ref={list}>
        {!q && <Link href={href(1)} className={!current ? "active" : ""}>(top)</Link>}
        {shown.map((b) => (
          <Link key={`${b.label}-${b.line}`} href={href(b.line)} title={`${b.label}, line ${b.line}`}
            className={current === b.label ? "active" : ""}>{b.label}</Link>
        ))}
        {shown.length === 0 && <div className="sub" style={{ padding: 8 }}>No labels match.</div>}
      </div>
    </div>
  );
}
