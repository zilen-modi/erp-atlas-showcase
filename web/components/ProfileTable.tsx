"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { readParam, writeParams } from "@/lib/urlstate";
import ExportButton from "@/components/ExportButton";

const KIND_TIP: Record<string, string> = {
  date: "Pick day numbers", time: "Seconds past midnight", integer: "Whole numbers", decimal: "Numbers with decimals",
  code: "A small set of short codes", text: "Free text", empty: "Never filled in the sample",
};

// Pick day number -> ISO date (epoch 1967-12-31)
function pickDate(v: string) {
  if (!/^\d{1,6}$/.test(v)) return null;
  const d = new Date(Date.UTC(1967, 11, 31) + Number(v) * 86400000);
  return d.toISOString().slice(0, 10);
}

// Every attribute's profile: fill, multivalue use, value kind, lengths, distinct and top values, references.
export default function ProfileTable({ file, attributes, records }: { file: string; attributes: any[]; records: number }) {
  const [only, setOnly] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => { setOnly(readParam("only") === "problems"); setReady(true); }, []);      // after hydration
  useEffect(() => { if (ready) writeParams({ only: only ? "problems" : null }); }, [only, ready]);
  const rows = attributes.filter((a) => !only || a.problems.some((p: any) => p.level !== "info"));
  return (
    <section className="card" data-section="attributes" id="sec-attributes">
      <div className="card-head">
        <h2>Attributes</h2>
        <span className="sub">{attributes.length} attributes · {records.toLocaleString()} records</span>
        <span className="spacer" />
        <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} style={{ width: "auto", height: "auto" }} />
          Only with problems
        </label>
        <ExportButton section="attributes" sectionTitle="Attributes" />
      </div>
      <div className="table-wrap tall">
        <table className="prof-table">
          <thead>
            <tr><th className="num w-min">Attr</th><th>DICT</th><th style={{ width: 150 }}>Filled</th><th className="num">Multi</th>
              <th>Kind</th><th className="num">Distinct</th><th>Top values</th><th>Looked up in</th><th className="w-min" /></tr>
          </thead>
          <tbody>
            {rows.map((a) => {
              const errs = a.problems.filter((p: any) => p.level === "error").length;
              const warns = a.problems.filter((p: any) => p.level === "warn").length;
              const dictFmt = a.dict?.format;
              const kindClash = dictFmt && dictFmt !== "string" && a.kind !== "empty" && !(dictFmt === "number" && a.kind === "integer") && dictFmt !== a.kind;
              return (
                <tr key={a.pos} className={errs ? "st-different" : ""}>
                  <td className="num w-min"><Link href={`/field/${encodeURIComponent(file)}/${a.pos}`} className="mono" style={{ fontWeight: 600 }}>&lt;{a.pos}&gt;</Link></td>
                  <td className="nowrap">
                    {a.dict ? <><span className="mono">{a.names[0]}</span> <span className="faint mono" title="DICT depth and format">{a.dict.sm} · {a.dict.format}</span></>
                      : <span className="badge amber">not in DICT</span>}
                  </td>
                  <td>
                    <div className="fillbar" title={`${a.filled.toLocaleString()} of ${records.toLocaleString()} records`}><span style={{ width: `${a.filled_pct}%` }} /></div>
                    <span className="sub">{a.filled_pct}%</span>
                  </td>
                  <td className="num">
                    {a.multi_pct ? <span title={`up to ${a.max_values} values, ${a.avg_values} on average`} className={a.dict?.sm === "S" ? "warn-text" : ""}>{a.multi_pct}%</span> : <span className="faint">—</span>}
                  </td>
                  <td className="nowrap"><span title={KIND_TIP[a.kind]}>{a.kind}</span>{kindClash && <span className="badge red" style={{ marginLeft: 6 }}>DICT: {dictFmt}</span>}</td>
                  <td className="num nowrap">
                    {a.filled ? `${a.distinct.toLocaleString()}${a.distinct_capped ? "+" : ""}` : "—"}
                    {a.filled > 0 && <div className="sub" title="Length in characters">{a.len_min === a.len_max ? `${a.len_max} ch` : `${a.len_min}–${a.len_max} ch`}</div>}
                  </td>
                  <td>
                    <div className="topvals">
                      {a.top.slice(0, 4).map(([v, c]: [string, number]) => (
                        <span key={v} className="chip" title={`${v} · ${c.toLocaleString()} values`}>
                          <span className="mono">{v === "" ? "∅" : a.kind === "date" ? pickDate(v) ?? v : v}</span><span className="chip-meta">{c}</span>
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="refs-cell">
                    {a.refs.map((r: any) => (
                      <div key={r.file} className="sub" title={`${r.programs} program(s) read ${r.file} with this field${r.skipped ? ` · not checked: ${r.skipped}` : ""}`}>
                        <span className="mono">{r.file}</span>{" "}
                        {r.checked != null ? (r.missing ? <span className="warn-text">{r.missing}/{r.checked} missing</span> : <span className="ok-text">all found</span>)
                          : <span className="faint">{r.skipped ? "not readable" : "not checked"}</span>}
                      </div>
                    ))}
                  </td>
                  <td className="w-min nowrap">
                    {errs > 0 && <span className="badge red">{errs}</span>} {warns > 0 && <span className="badge amber">{warns}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
