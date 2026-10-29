// Server-side fetch helper. Server components call `atlas serve` directly;
// client components use relative /api/* paths, which next.config.mjs forwards.

const API = process.env.ATLAS_API ?? "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Server components call the API as the signed-in person: pass their session cookie along.
async function sessionHeaders(): Promise<Record<string, string>> {
  if (typeof window !== "undefined") return {};
  const { cookies } = await import("next/headers");
  const token = cookies().get(SESSION_COOKIE)?.value;
  return token ? { Cookie: `${SESSION_COOKIE}=${token}` } : {};
}

export const SESSION_COOKIE = "atlas_session";

export async function api<T = any>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { cache: "no-store", headers: await sessionHeaders() });
  } catch {
    throw new ApiError(503, "Atlas API is not running. Start it with: uv run atlas serve");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const enc = encodeURIComponent;

export function programHref(name: string, line?: number, provenance = "git") {
  const q = new URLSearchParams();
  if (line) q.set("line", String(line));
  if (provenance !== "git") q.set("prov", provenance);
  const s = q.toString();
  return `/program/${enc(name)}/source${s ? `?${s}` : ""}`;
}

export function fmtNum(n: number | null | undefined) {
  return n == null ? "—" : n.toLocaleString("en-US");
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
