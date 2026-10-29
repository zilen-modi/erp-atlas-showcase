import Link from "next/link";
import { SparkIcon } from "@/components/Icons";

// Jumps to Ask Atlas with a ready-made question about the thing on this page.
export default function AskButton({ question, label = "Ask about this", primary = false }: {
  question: string; label?: string; primary?: boolean;
}) {
  return (
    <Link href={`/ask?q=${encodeURIComponent(question)}`} className={`btn ${primary ? "primary" : ""}`}>
      <SparkIcon size={14} /> {label}
    </Link>
  );
}
