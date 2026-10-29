"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import FileInput from "@/components/compare/FileInput";
import { ArrowIcon } from "@/components/Icons";

export default function QualityStart() {
  const router = useRouter();
  const [file, setFile] = useState("");
  return (
    <section className="card">
      <form className="quick-form" onSubmit={(e) => { e.preventDefault(); if (file.trim()) router.push(`/files/${encodeURIComponent(file.trim())}/profile`); }}>
        <label><span>Profile a file</span><FileInput value={file} onChange={setFile} /></label>
        <button className="primary" type="submit" disabled={!file.trim()}>Open <ArrowIcon size={14} /></button>
      </form>
    </section>
  );
}
