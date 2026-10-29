"use client";

import { useRouter } from "next/navigation";
import { copy, shareUrl } from "@/components/ExportButton";
import { LinkIcon, TrashIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";

export default function ReportActions({ id, compact = false }: { id: string; compact?: boolean }) {
  const router = useRouter();
  async function remove() {
    if (!window.confirm("Delete this report? Its share link will stop working.")) return;
    const r = await fetch(`/api/reports/${id}`, { method: "DELETE" }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't delete the report", await errorText(r)); return; }
    toast.success("Report deleted");
    if (compact) router.refresh(); else router.push("/reports");
  }
  return (
    <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
      <a className="btn sm" href={`/api/reports/${id}/pdf?download=true`}>Download</a>
      <button className="sm" onClick={() => copy(shareUrl(id), "Share link")}><LinkIcon size={13} /> {compact ? "Link" : "Copy share link"}</button>
      {!compact && <a className="btn sm" href={`/api/reports/${id}/pdf`} target="_blank" rel="noreferrer">Open PDF</a>}
      <button className="ghost icon-btn sm" aria-label="Delete report" title="Delete" onClick={remove}><TrashIcon size={13} /></button>
    </div>
  );
}
