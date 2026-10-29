// View state kept in the address bar (without navigating), so page exports, section exports and
// shared links show exactly what's on screen: the step, the view, the filters.
export function readParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get(name);
}

export function writeParams(values: Record<string, string | null | undefined>) {
  if (typeof window === "undefined") return;
  const q = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === "") q.delete(k);
    else q.set(k, v);
  }
  const s = q.toString();
  const url = `${window.location.pathname}${s ? `?${s}` : ""}${window.location.hash}`;
  if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    window.history.replaceState(window.history.state, "", url);
  }
}
