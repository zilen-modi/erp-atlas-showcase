import Link from "next/link";
import AskButton from "@/components/AskButton";
import { CompareIcon, ScreenIcon } from "@/components/Icons";
import { Badge, PageHeader } from "@/components/ui";
import { enc, fmtNum } from "@/lib/api";

// Git is the source of truth; how TEST differs is on the "TEST vs git" tab.
export default function ProgramHeader({ p, tab }: { p: any; tab: "overview" | "source" | "drift" | "flow" }) {
  const name = p.program;
  const kind = p.kind === "NONE" ? "Program" : p.kind.charAt(0) + p.kind.slice(1).toLowerCase();
  const launches = (p.menus ?? []).reduce((n: number, m: any) => Math.max(n, m.used ?? 0), 0);
  return (
    <>
      <PageHeader
        eyebrow={<Link href="/programs">Program</Link>}
        title={name}
        mono
        meta={<>
          <Badge kind="">{kind}</Badge>
          {p.folder && <span className="badge violet" title="Where this program lives in the ERP repo">{p.folder}</span>}
          {p.params?.length > 0 && <code title="Parameters">({p.params.join(", ")})</code>}
          <span>·</span><span>{fmtNum(p.lines)} lines</span>
          <span>·</span><span>{p.labels} labels</span>
          {launches > 0 && <><span>·</span><span>{fmtNum(launches)} menu launches</span></>}
        </>}
        actions={<>
          {p.screens?.length > 0 && (
            <Link href={`/screen/${enc(p.screens[0])}`} className="btn" title={`The screen this program drives: ${p.screens.join(", ")}`}>
              <ScreenIcon size={14} /> Screen
            </Link>
          )}
          <Link href={`/compare/flows/new?program=${enc(name)}`} className="btn" title="Suggested old-vs-new test flows for this program">
            <CompareIcon size={14} /> Compare flows
          </Link>
          <AskButton question={`Explain what ${name} does in plain language: its purpose, main steps, and the data it reads and writes.`} />
        </>}
      />
      <nav className="tabs">
        <Link href={`/program/${enc(name)}`} className={tab === "overview" ? "active" : ""}>Overview</Link>
        <Link href={`/program/${enc(name)}/source`} className={tab === "source" ? "active" : ""}>Source</Link>
        <Link href={`/flow/${enc(name)}`} className={tab === "flow" ? "active" : ""}>Flow</Link>
        {tab === "drift" && <Link href={`/drift/${enc(name)}`} className="active">Differences on TEST</Link>}
      </nav>
    </>
  );
}
