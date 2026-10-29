import Link from "next/link";
import ProfileRunner from "@/components/ProfileRunner";
import ProfileTable from "@/components/ProfileTable";
import { AlertIcon, FilesIcon } from "@/components/Icons";
import { Card, EmptyState, ErrorBox, PageHeader, Stat } from "@/components/ui";
import { ago, api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

const LEVEL: Record<string, [string, string]> = { error: ["Error", "red"], warn: ["Warning", "amber"], info: ["Note", ""] };

export default async function ProfilePage({ params }: { params: { file: string } }) {
  const file = decodeURIComponent(params.file).toUpperCase();
  let d: any;
  try {
    d = await api(`/api/profiles/${enc(file)}`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const p = d.latest;
  const header = (
    <PageHeader
      eyebrow={<><Link href="/quality">Data quality</Link> · <Link href={`/files/${enc(file)}`} className="mono">{file}</Link></>}
      title={`${file} data profile`}
      mono
      desc={p ? <>Sampled {fmtNum(p.records)} records from {p.environment} {ago(p.finished_at)} (keys taken from the first {fmtNum(p.keys_seen)} in file order). Only counts and top values are kept, never whole records.</>
        : "What this file really holds on TEST, field by field, checked against its DICT and the files the code looks its values up in."}
      actions={p ? <ProfileRunner file={file} again /> : undefined}
    />
  );
  if (!p) {
    return (
      <>
        {header}
        <Card>
          <EmptyState title="Not profiled yet" icon={<FilesIcon size={20} />}>
            Atlas reads a sample of {file} records from TEST (read-only) and reports fill rates, multivalue use, value kinds,
            values that break the DICT, attributes missing from the DICT, and values that aren't keys in the files they point to.
            <div style={{ marginTop: 14, display: "flex", justifyContent: "center" }}><ProfileRunner file={file} /></div>
          </EmptyState>
        </Card>
      </>
    );
  }
  const problems = p.attributes.flatMap((a: any) => a.problems.map((x: any) => ({ ...x, pos: a.pos, names: a.names })));
  const serious = problems.filter((x: any) => x.level !== "info").sort((a: any, b: any) => (a.level === b.level ? a.pos - b.pos : a.level === "error" ? -1 : 1));
  const undocumented = p.attributes.filter((a: any) => !a.dict && a.filled).length;
  const filledAttrs = p.attributes.filter((a: any) => a.filled).length;

  return (
    <>
      {header}
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat icon={<FilesIcon size={18} />} label="Records sampled" value={fmtNum(p.records)} note={`key shapes: ${p.key_shapes.slice(0, 2).map((s: any) => s[0]).join(", ")}`} />
        <Stat icon={<AlertIcon size={18} />} label="Errors" value={<span style={p.errors ? { color: "var(--bad)" } : undefined}>{p.errors}</span>} note="Values that break the DICT or point nowhere" />
        <Stat icon={<AlertIcon size={18} />} label="Warnings" value={<span style={p.warnings ? { color: "var(--warn)" } : undefined}>{p.warnings}</span>} note="Worth a look before migrating" />
        <Stat icon={<FilesIcon size={18} />} label="Attributes in use" value={fmtNum(filledAttrs)} note={`${undocumented} not in the DICT`} />
      </div>

      <Card title="Problems" sub={serious.length ? `${serious.length} to review` : "None found in this sample"}>
        {serious.length === 0 ? <div className="empty">No errors or warnings in this sample.</div> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th className="w-min">Level</th><th className="num w-min">Attr</th><th>Name</th><th>What's wrong</th></tr></thead>
              <tbody>
                {serious.map((x: any, i: number) => (
                  <tr key={i}>
                    <td className="w-min"><span className={`badge ${LEVEL[x.level][1]}`}>{LEVEL[x.level][0]}</span></td>
                    <td className="num w-min"><Link href={`/field/${enc(file)}/${x.pos}`} className="mono" style={{ fontWeight: 600 }}>&lt;{x.pos}&gt;</Link></td>
                    <td className="mono sub nowrap">{x.names[0] ?? "—"}</td>
                    <td>{x.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div style={{ marginTop: 16 }}>
        <ProfileTable file={file} attributes={p.attributes} records={p.records} />
      </div>
    </>
  );
}
