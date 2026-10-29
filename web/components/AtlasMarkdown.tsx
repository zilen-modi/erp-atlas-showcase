"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FlowIcon, ProcessIcon, SearchIcon } from "@/components/Icons";

const enc = encodeURIComponent;
const PROG = "[A-Z][A-Z0-9._$%]{2,}";
const CITE = new RegExp(`\\b(live:)?(${PROG}):(\\d+)\\b`, "g");
const FIELD = /\b([A-Z][A-Z0-9.\-/]{1,})<(\d+)>/g;
const PROGRAM_TOKEN = new RegExp(`^${PROG}$`);
const MENU_TOKEN = /^M\d{3,5}$/;
const FACT_TOKEN = /^F-\d{4}$/;

// Turn citations into links before Markdown parsing -- outside code spans, fences and existing links.
function linkify(md: string): string {
  return md
    .split(/(```[\s\S]*?```|`[^`\n]*`|\[[^\]\n]*\]\([^)\s]*\))/g)
    .map((part, i) => {
      if (i % 2 === 1) return part; // code: handled by the `code` renderer; a link: already a link
      return part
        .replace(CITE, (_m, live, prog, line) =>
          `[${live ?? ""}${prog}:${line}](/program/${enc(prog)}/source?line=${line}${live ? "&prov=live" : ""})`)
        .replace(FIELD, (_m, f, a) => `[${f}<${a}>](/field/${enc(f)}/${a})`);
    })
    .join("");
}

function codeHref(text: string): string | null {
  const t = text.trim();
  let m = t.match(new RegExp(`^(live:)?(${PROG}):(\\d+)$`));
  if (m) return `/program/${enc(m[2])}/source?line=${m[3]}${m[1] ? "&prov=live" : ""}`;
  m = t.match(/^([A-Z][A-Z0-9.\-/]+)<(\d+)>$/);
  if (m) return `/field/${enc(m[1])}/${m[2]}`;
  if (MENU_TOKEN.test(t)) return `/menu/${t}`;
  if (FACT_TOKEN.test(t)) return `/facts?q=${t}`;
  // A bare name could be a program, a form or a control: let search decide (it jumps
  // straight to the program when one exists, otherwise lists what the name matches).
  if (PROGRAM_TOKEN.test(t) && /[A-Z]{3}/.test(t)) return `/search?q=${enc(t)}`;
  return null;
}

export default function AtlasMarkdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (!href?.startsWith("/")) return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
            // the actions an answer offers: run a search on TEST, trace a field, open a process board
            const act = href.startsWith("/test-data") ? { cls: "run", Icon: SearchIcon }
              : href.startsWith("/trace") ? { cls: "trace", Icon: FlowIcon }
              : href.startsWith("/process") ? { cls: "process", Icon: ProcessIcon } : null;
            return act
              ? <Link href={href} className={`ask-act ${act.cls}`}><act.Icon size={13} />{children}</Link>
              : <Link href={href}>{children}</Link>;
          },
          code: ({ className, children }) => {
            const text = String(children ?? "");
            if (className || text.includes("\n")) return <code className={className}>{children}</code>;
            const href = codeHref(text);
            return href ? <Link href={href} className="codelink"><code>{text}</code></Link> : <code>{text}</code>;
          },
        }}
      >
        {linkify(text)}
      </ReactMarkdown>
    </div>
  );
}
