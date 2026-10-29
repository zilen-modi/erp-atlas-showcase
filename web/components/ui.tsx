import Link from "next/link";
import ExportButton from "@/components/ExportButton";
import { sectionSlug } from "@/lib/section";
import { AlertIcon, SearchIcon } from "@/components/Icons";
import { ToastOnMount } from "@/components/Toaster";
import { ago, enc, programHref } from "@/lib/api";

export function Badge({ kind, children }: { kind: string; children?: React.ReactNode }) {
  return <span className={`badge ${kind}`}>{children ?? kind}</span>;
}

export function ProgramLink({ name, strong = false }: { name: string; strong?: boolean }) {
  return <Link href={`/program/${enc(name)}`} className="mono" style={strong ? { fontWeight: 600 } : undefined}>{name}</Link>;
}

export function LineLink({ program, line, provenance = "git" }: { program: string; line: number; provenance?: string }) {
  return <Link href={programHref(program, line, provenance)} className="mono">{line}</Link>;
}

export function FieldLink({ file, attr }: { file: string; attr: number }) {
  return <Link href={`/field/${enc(file)}/${attr}`} className="mono">{file}&lt;{attr}&gt;</Link>;
}

export function Freshness({ f }: { f: Record<string, { sha: string | null; synced_at: string }> | undefined }) {
  if (!f) return null;
  const git = f["git:erp"];
  return <span className="sub">git main <code>{git?.sha ?? "—"}</code> · synced {ago(git?.synced_at)}</span>;
}

// Page-level failure: the message goes to a toast; the page keeps a quiet placeholder.
export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <>
      <ToastOnMount title="Couldn't load this page" detail={msg} />
      <div className="card empty-state">
        <div className="icon"><AlertIcon size={20} /></div>
        <b>Nothing to show</b>
        <span>This page couldn't load its data. The notification in the corner says why.</span>
      </div>
    </>
  );
}

export function PageHeader({ eyebrow, title, mono = false, desc, meta, actions }: {
  eyebrow?: React.ReactNode; title: React.ReactNode; mono?: boolean; desc?: React.ReactNode;
  meta?: React.ReactNode; actions?: React.ReactNode;
}) {
  return (
    <div className="page-head">
      <div style={{ minWidth: 0 }}>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1 className={mono ? "mono" : ""}>{title}</h1>
        {desc && <div className="desc">{desc}</div>}
        {meta && <div className="meta">{meta}</div>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, sub, actions, children, pad = false, className = "", style, sectionId, exportable = true }: {
  title?: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode;
  pad?: boolean; className?: string; style?: React.CSSProperties; sectionId?: string; exportable?: boolean;
}) {
  const label = typeof title === "string" ? title : sectionId;
  const sid = sectionId ?? (typeof title === "string" ? sectionSlug(title) : undefined);
  return (
    <section className={`card ${className}`} style={style} data-section={sid} id={sid ? `sec-${sid}` : undefined}>
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {sub && <span className="sub">{sub}</span>}
          <span className="spacer" />
          {actions}
          {exportable && sid && <ExportButton section={sid} sectionTitle={label} />}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </section>
  );
}

export function Stat({ icon, label, value, note, href }: {
  icon: React.ReactNode; label: string; value: React.ReactNode; note?: React.ReactNode; href?: string;
}) {
  const inner = (
    <>
      <div className="stat-icon">{icon}</div>
      <div style={{ minWidth: 0 }}>
        <div className="label">{label}</div>
        <div className="value">{value}</div>
        {note && <div className="note">{note}</div>}
      </div>
    </>
  );
  return href ? <Link href={href} className="card stat">{inner}</Link> : <div className="card stat">{inner}</div>;
}

export function EmptyState({ title, children, icon }: { title: string; children?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <div className="icon">{icon ?? <SearchIcon size={20} />}</div>
      <b>{title}</b>
      {children && <span>{children}</span>}
    </div>
  );
}

export function Pager({ page, pages, total, noun, href }: {
  page: number; pages: number; total: number; noun: string; href: (p: number) => string;
}) {
  return (
    <div className="pager">
      <span>{total.toLocaleString("en-US")} {noun}</span>
      <span className="spacer" />
      <span>Page {page + 1} of {Math.max(1, pages)}</span>
      {page > 0 ? <Link className="btn sm" href={href(page - 1)}>Previous</Link> : <span className="btn sm" style={{ opacity: 0.45 }}>Previous</span>}
      {page + 1 < pages ? <Link className="btn sm" href={href(page + 1)}>Next</Link> : <span className="btn sm" style={{ opacity: 0.45 }}>Next</span>}
    </div>
  );
}

// A GET form that filters a list page (keeps working without JavaScript).
export function Toolbar({ action, q, placeholder, children }: {
  action: string; q?: string; placeholder: string; children?: React.ReactNode;
}) {
  return (
    <form action={action} className="toolbar">
      <div className="field">
        <SearchIcon size={15} />
        <input name="q" defaultValue={q} placeholder={placeholder} />
      </div>
      {children}
      <button type="submit">Apply</button>
      {q && <Link href={action} className="btn ghost">Clear</Link>}
    </form>
  );
}

export function UsageBar({ value, max }: { value: number | null | undefined; max: number }) {
  const pct = max > 0 && value ? Math.max(2, (value / max) * 100) : 0;
  return <div className="bar" title={value ? `${value.toLocaleString("en-US")} launches` : "no launches"}><span style={{ width: `${pct}%` }} /></div>;
}

// Renders numbered source lines.  `start` is the first line's number.
export function Code({
  lines,
  start = 1,
  highlight,
  program,
  provenance = "git",
  mark,
  className = "",
  style,
}: {
  lines: string[];
  start?: number;
  highlight?: number;
  program?: string;
  provenance?: string;
  mark?: "add" | "del";
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`code ${className}`} style={style}>
      {lines.map((tx, i) => {
        const no = start + i;
        const isComment = /^\s*(\d+:?\s*)?[*!]/.test(tx);
        const cls = ["ln", no === highlight ? "hl" : "", mark ?? "", isComment ? "comment" : ""].join(" ");
        return (
          <div key={i} className={cls} id={`L${no}`}>
            <span className="no">
              {program ? <Link href={programHref(program, no, provenance)}>{no}</Link> : no}
            </span>
            <span className="tx">{tx || " "}</span>
          </div>
        );
      })}
    </div>
  );
}

export const DRIFT_HELP: Record<string, string> = {
  logic: "Same place, different code",
  "git-only": "In git, not on TEST (not deployed yet, or reverted on the server)",
  "live-only": "On TEST, not in git (edited on the server, or removed from git)",
  label: "Only a statement label differs",
  comment: "Only comment text differs",
  whitespace: "Only spacing differs",
};
