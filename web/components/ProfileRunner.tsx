"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import JobProgress from "@/components/JobProgress";
import { SyncIcon } from "@/components/Icons";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

// Start (or re-run) a data profile of one file, with live progress; refreshes the page when done.
export default function ProfileRunner({ file, again = false, onDone }: { file: string; again?: boolean; onDone?: () => void }) {
  const router = useRouter();
  const [size, setSize] = useState(1000);
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") {
        reportJob(j, "Data profile", `Profiled ${file}`);
        if (onDone) onDone(); else router.refresh();
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, file, router, onDone]);

  const running = job?.state === "running";
  return (
    <div className="prof-runner">
      {!running && (
        <div className="row" style={{ gap: 8 }}>
          <select value={size} onChange={(e) => setSize(Number(e.target.value))} title="How many records to sample from TEST">
            {[250, 500, 1000, 2000, 5000].map((n) => <option key={n} value={n}>{n.toLocaleString()} records</option>)}
          </select>
          <button className={again ? "" : "primary"} onClick={async () => {
            const j = await startJob("/api/jobs/profile", { pick_file: file, sample: size }, "Data profile");
            if (j) setJob(j);
          }}>
            <SyncIcon size={14} /> {again ? "Profile again" : "Profile this file"}
          </button>
        </div>
      )}
      {running && job && (
        <JobProgress job={job} title={`Profiling ${file} on TEST`} expectedKind="profile"
          hint="Reads a sample of records through the python layer (read-only), then checks every attribute against the DICT and the files the code looks its values up in. 1,000 records take about a minute." />
      )}
    </div>
  );
}
