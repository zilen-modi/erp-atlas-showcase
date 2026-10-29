import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import SearchBox from "@/components/SearchBox";
import Sidebar from "@/components/Sidebar";
import StatusBar from "@/components/StatusBar";
import Toaster from "@/components/Toaster";
import ExportButton from "@/components/ExportButton";
import PrintMode from "@/components/PrintMode";
import FirstPassword from "@/components/account/FirstPassword";
import { ago, api, ApiError } from "@/lib/api";
import "./globals.css";

export const metadata: Metadata = {
  title: "ERP Atlas",
  description: "Understand the legacy Pick ERP: menus, programs, files, flows, and a chat that cites the code",
};

export const dynamic = "force-dynamic";

function Bare({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="bare">{children}<Toaster /></body>
    </html>
  );
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const path = headers().get("x-atlas-path") ?? "/";
  if (path.startsWith("/login")) return <Bare>{children}</Bare>;
  const me: any = await api("/api/auth/me").catch((e) => e);
  if (me instanceof ApiError && me.status === 401) redirect(`/login?next=${encodeURIComponent(path)}`);
  const user = me instanceof ApiError ? null : me?.user ?? null;
  if (user?.must_change) return <Bare><FirstPassword name={user.name} /></Bare>;
  const status: any = await api("/api/status").catch(() => null);
  const git = status?.freshness?.["git:erp"];
  const nav: any = await api("/api/settings/nav").catch(() => ({ hidden: [] }));
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* apply the saved sidebar state before first paint, so it doesn't flash open */}
        <script dangerouslySetInnerHTML={{ __html: `try{if(localStorage.getItem("atlas.sidebar")==="collapsed")document.documentElement.classList.add("sidebar-collapsed")}catch(e){}` }} />
      </head>
      <body>
        <div className="shell">
          <Sidebar sha={git?.sha ?? null} synced={git ? ago(git.synced_at) : null} hidden={nav.hidden ?? []} user={user} />
          <div className="main-col">
            <header className="topbar">
              <div className="search">
                <Suspense fallback={null}>
                  <SearchBox />
                </Suspense>
              </div>
              <span className="spacer" />
              <StatusBar />
              <ExportButton />
            </header>
            <div className="scroll">
              <PrintMode sha={git?.sha ?? null} environment={status?.environment ?? "TEST"} />
              <main>{children}</main>
            </div>
          </div>
        </div>
        <Toaster />
      </body>
    </html>
  );
}
