import LoginForm from "@/components/account/LoginForm";
import { api } from "@/lib/api";

export const metadata = { title: "Sign in · ERP Atlas" };

export default async function LoginPage({ searchParams }: { searchParams: { next?: string } }) {
  const state: any = await api("/api/auth/state").catch(() => null);
  const next = searchParams.next?.startsWith("/") && !searchParams.next.startsWith("//") ? searchParams.next : "/";
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand"><span className="brand-mark">A</span><div><div className="brand-name">ERP Atlas</div><div className="brand-sub">Legacy Pick ERP</div></div></div>
        {state === null ? (
          <p className="st-note">Atlas API is not running. Start it with: <code>uv run atlas serve</code></p>
        ) : state.setup_needed ? (
          <div className="stack">
            <h1>Set up the first admin</h1>
            <p className="sub">Atlas has no accounts yet. On the machine that runs Atlas, create yours:</p>
            <pre className="auth-cmd">uv run atlas user add you@acme.com --name "Your Name" --admin</pre>
            <p className="sub">It prints a one-time password. Sign in with it here and choose your own. Add everyone else from the Admin page.</p>
          </div>
        ) : (
          <LoginForm next={next} />
        )}
      </div>
    </div>
  );
}
