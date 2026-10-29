import Link from "next/link";
import AskButton from "@/components/AskButton";
import { Card, ErrorBox, LineLink, PageHeader } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

function Files({ files, kind }: { files: string[]; kind: "r" | "w" }) {
  if (!files.length) return null;
  return (
    <span className="io">
      <span className={`io-tag ${kind}`}>{kind === "w" ? "WRITES" : "READS"}</span>
      {files.slice(0, 8).map((f) => <Link key={f} href={`/files/${enc(f)}`} className="file-chip">{f}</Link>)}
      {files.length > 8 && <span className="faint">+{files.length - 8}</span>}
    </span>
  );
}

function Node({ n, parent, root = false }: { n: any; parent?: string; root?: boolean }) {
  return (
    <li>
      <div className={`node ${root ? "is-root" : ""}`}>
        <Link href={`/program/${enc(n.program)}`} className="prog">{n.program}</Link>
        {parent && n.line && <span className="sub">line <LineLink program={parent} line={n.line} /></span>}
        {n.repeat && <span className="sub">(shown above)</span>}
        {n.known === false && <span className="sub">not in the index</span>}
        {!n.repeat && <Files files={n.writes ?? []} kind="w" />}
        {!n.repeat && <Files files={n.reads ?? []} kind="r" />}
        {!n.repeat && !root && n.children?.length > 0 && (
          <Link href={`/flow/${enc(n.program)}`} className="btn sm ghost" style={{ marginLeft: "auto" }}>Focus</Link>
        )}
      </div>
      {n.children?.length > 0 && (
        <ul className="tree">
          {n.children.map((c: any, i: number) => <Node key={`${c.program}-${i}`} n={c} parent={n.program} />)}
          {n.more > 0 && <li className="sub" style={{ paddingLeft: 4 }}>…and {n.more} more calls</li>}
        </ul>
      )}
    </li>
  );
}

export default async function FlowPage({ params, searchParams }: { params: { name: string }; searchParams: { depth?: string } }) {
  const name = decodeURIComponent(params.name).toUpperCase();
  const depth = Math.min(3, Math.max(1, parseInt(searchParams.depth ?? "2", 10) || 2));
  let d: any;
  try {
    d = await api(`/api/flow/${enc(name)}?depth=${depth}&track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const count = (n: any): number => 1 + (n.children ?? []).reduce((s: number, c: any) => s + count(c), 0);
  return (
    <>
      <PageHeader
        eyebrow="Flow"
        title={d.menu ? d.menu.code : d.root}
        mono
        meta={<>
          {d.menu && <><span>runs <code>{d.menu.exec}</code></span><span>·</span><span>{fmtNum(d.menu.used)} launches</span><span>·</span></>}
          <span>{count(d.tree)} programs shown</span>
        </>}
        actions={<>
          <div className="seg">
            {[1, 2, 3].map((n) => (
              <Link key={n} href={`/flow/${enc(name)}?depth=${n}`} className={n === depth ? "active" : ""}>{n} level{n > 1 ? "s" : ""}</Link>
            ))}
          </div>
          <AskButton primary label="Explain this flow"
            question={`Walk me through the ${d.menu ? `menu ${d.menu.code}` : `program ${d.root}`} flow end to end: what the user does, the main steps, and which files are read and written.`} />
        </>}
      />
      <Card>
        <div className="card-body" style={{ overflowX: "auto" }}>
          <ul className="tree root"><Node n={d.tree} root /></ul>
        </div>
        <div className="card-foot">GUI calls (ATGUI*) and I/O plumbing (IOREADU / IORELEASE) are left out to keep the flow readable.</div>
      </Card>
    </>
  );
}
