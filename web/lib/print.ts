// Pages render as a print layout when the URL carries ?print=1 (used for PDF reports).
export function isPrint(): boolean {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("print") === "1";
}
