"use client";

import { useEffect } from "react";

// Brings the highlighted source line into view when a citation link is opened.
export default function ScrollToLine({ line }: { line?: number }) {
  useEffect(() => {
    if (line) document.getElementById(`L${line}`)?.scrollIntoView({ block: "center" });
  }, [line]);
  return null;
}
