import Link from "next/link";
import BlockList from "@/components/BlockList";
import ProgramHeader from "@/components/ProgramHeader";
import ScrollToLine from "@/components/ScrollToLine";
import { Code, ErrorBox } from "@/components/ui";
import { api, enc } from "@/lib/api";

export const dynamic = "force-dynamic";

const WINDOW = 250;

export default async function SourcePage({
  params,
  searchParams,
}: {
  params: { name: string };
  searchParams: { line?: string; start?: string; prov?: string };
}) {
  const name = decodeURIComponent(params.name);
  const prov = searchParams.prov === "live" || searchParams.prov === "worktree" ? searchParams.prov : "git";
  const line = searchParams.line ? parseInt(searchParams.line, 10) : undefined;
  let p: any, blocks: any;
  try {
    [p, blocks] = await Promise.all([
      api(`/api/program/${enc(name)}?provenance=${prov}`),
      api(`/api/program/${enc(name)}/blocks?provenance=${prov}`),
    ]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  if (p.error) return <ErrorBox error={p.error} />;
  const total: number = p.lines;
  let start = searchParams.start ? parseInt(searchParams.start, 10) : line ? Math.max(1, line - 60) : 1;
  start = Math.min(Math.max(1, start), Math.max(1, total - 20));
  const end = Math.min(total, start + WINDOW - 1);
  const src: any = await api(`/api/lines/${enc(name)}?start=${start}&end=${end}&provenance=${prov}`);
  const lines: string[] = (src.lines ?? []).map((l: string) => l.replace(/^\d+: /, ""));
  const base = `/program/${enc(name)}/source`;
  const q = (extra: Record<string, string | number>) => {
    const s = new URLSearchParams({ ...(prov !== "git" ? { prov } : {}), ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, String(v)])) });
    return `${base}?${s}`;
  };
  const current = [...blocks.blocks].reverse().find((b: any) => b.line <= (line ?? start));

  return (
    <>
      <ProgramHeader p={p} tab="source" />
      {prov !== "git" && (
        <div className="notice" style={{ marginBottom: 12 }}>
          Showing the TEST server's copy for comparison. <Link href={`${base}${line ? `?line=${line}` : ""}`}>Back to git</Link>
        </div>
      )}
      <div className="source-layout">
        <BlockList blocks={blocks.blocks} current={current?.label ?? null} hrefBase={q({}).replace(/\?$/, "")} prov={prov} />
        <div className="card" style={{ overflow: "hidden" }}>
          <div className="card-head" style={{ padding: "10px 16px" }}>
            <span className="mono" style={{ fontWeight: 600 }}>{current?.label ?? "(top of program)"}</span>
            <span className="sub">lines {start.toLocaleString()}–{end.toLocaleString()} of {total.toLocaleString()}</span>
            <span className="spacer" />
            {start > 1 ? <Link className="btn sm" href={q({ start: Math.max(1, start - WINDOW) })}>↑ Earlier</Link> : null}
            {end < total ? <Link className="btn sm" href={q({ start: end + 1 })}>Later ↓</Link> : null}
          </div>
          <Code lines={lines} start={start} highlight={line} program={name} provenance={prov} className="flush source-code" />
        </div>
      </div>
      <ScrollToLine line={line} />
    </>
  );
}
