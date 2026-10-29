"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertIcon, ChatIcon, FlowIcon, ProcessIcon, NetworkIcon, ClockIcon, ScreenIcon, SearchIcon, CompareIcon, FilesIcon, GitIcon, HomeIcon, MenuIcon, PanelIcon, ProgramIcon, ReportIcon, SettingsIcon, UsersIcon, LogoutIcon, FactIcon, BridgeIcon } from "@/components/Icons";

const NAV = [
  { href: "/", label: "Overview", Icon: HomeIcon, match: (p: string) => p === "/" },
  { href: "/ask", label: "Ask Atlas", Icon: ChatIcon, match: (p: string) => p.startsWith("/ask") },
  { href: "/compare", label: "Compare", Icon: CompareIcon, match: (p: string) => p.startsWith("/compare") },
  { href: "/network", label: "Network", Icon: NetworkIcon, match: (p: string) => p.startsWith("/network") },
  { href: "/process", label: "Processes", Icon: ProcessIcon, match: (p: string) => p.startsWith("/process") },
  { href: "/trace", label: "Trace", Icon: FlowIcon, match: (p: string) => p.startsWith("/trace") },
  { href: "/erpnext", label: "ERP Next", Icon: BridgeIcon, match: (p: string) => p.startsWith("/erpnext") },
  { href: "/test-data", label: "Test data", Icon: SearchIcon, match: (p: string) => p.startsWith("/test-data") },
  { href: "/reports", label: "Reports", Icon: ReportIcon, match: (p: string) => p.startsWith("/reports") },
];
const BROWSE = [
  { href: "/screens", label: "Screens", Icon: ScreenIcon, match: (p: string) => p.startsWith("/screen") },
  { href: "/menus", label: "Menus", Icon: MenuIcon, match: (p: string) => p.startsWith("/menu") },
  { href: "/programs", label: "Programs", Icon: ProgramIcon,
    match: (p: string) => p.startsWith("/program") || p.startsWith("/flow") || p.startsWith("/drift") },
  { href: "/files", label: "Files & fields", Icon: FilesIcon,
    match: (p: string) => (p.startsWith("/files") && !p.endsWith("/profile")) || p.startsWith("/field") },
  { href: "/jobs", label: "Background jobs", Icon: ClockIcon, match: (p: string) => p.startsWith("/jobs") },
  { href: "/facts", label: "Facts", Icon: FactIcon, match: (p: string) => p.startsWith("/facts") },
  { href: "/quality", label: "Data quality", Icon: AlertIcon, match: (p: string) => p.startsWith("/quality") || p.endsWith("/profile") },
];

// Tabs that can be hidden in Settings → Navigation (Overview and Settings always show).
export const HIDEABLE = [...NAV.slice(1), ...BROWSE].map(({ href, label }) => ({ href, label, group: NAV.some((n) => n.href === href) ? "Main" : "Browse" }));

const KEY = "atlas.sidebar";

// Collapsed state lives on <html> (set before paint by the inline script in layout.tsx) and in localStorage.
function setCollapsed(on: boolean) {
  document.documentElement.classList.toggle("sidebar-collapsed", on);
  try { localStorage.setItem(KEY, on ? "collapsed" : "open"); } catch { /* private mode: still toggles */ }
}

type User = { name: string; email: string; role: string } | null;

async function signOut() {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
  window.location.assign("/login");
}

export default function Sidebar({ sha, synced, hidden = [], user = null }: { sha: string | null; synced: string | null; hidden?: string[]; user?: User }) {
  const path = usePathname() ?? "/";
  const [collapsed, setC] = useState(false);
  useEffect(() => { setC(document.documentElement.classList.contains("sidebar-collapsed")); }, []);
  const toggle = () => { setCollapsed(!collapsed); setC(!collapsed); };

  // Cmd/Ctrl + B toggles, like most editors
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b" && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        const on = !document.documentElement.classList.contains("sidebar-collapsed");
        setCollapsed(on); setC(on);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const item = (n: (typeof NAV)[number]) => (
    <Link key={n.href} href={n.href} className={`nav-item ${n.match(path) ? "active" : ""}`} title={collapsed ? n.label : undefined}>
      <n.Icon size={17} /> <span className="nav-text">{n.label}</span>
    </Link>
  );
  return (
    <aside className="sidebar">
      <Link href="/" className="brand" title={collapsed ? "ERP Atlas" : undefined}>
        <span className="brand-mark">A</span>
        <span className="nav-text">
          <div className="brand-name">ERP Atlas</div>
          <div className="brand-sub">Legacy Pick ERP</div>
        </span>
      </Link>
      {NAV.filter((n) => !hidden.includes(n.href)).map(item)}
      {BROWSE.some((n) => !hidden.includes(n.href)) && <div className="nav-label"><span className="nav-text">Browse</span></div>}
      {BROWSE.filter((n) => !hidden.includes(n.href)).map(item)}
      {user?.role === "admin" && <>
        <div className="nav-label"><span className="nav-text">Admin</span></div>
        {item({ href: "/admin", label: "People", Icon: UsersIcon, match: (p: string) => p.startsWith("/admin") })}
        {item({ href: "/settings", label: "Settings", Icon: SettingsIcon, match: (p: string) => p.startsWith("/settings") })}
      </>}
      {user && (
        <div className="sb-user">
          <Link href="/account" className={`sb-user-link ${path.startsWith("/account") ? "active" : ""}`} title={collapsed ? `${user.name}: your account` : "Your account"}>
            <span className="sb-avatar" aria-hidden="true">{user.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}</span>
            <span className="nav-text sb-user-text"><span className="sb-user-name">{user.name}</span><span className="sb-user-role">{user.role}</span></span>
          </Link>
          <button className="ghost sm icon-btn" onClick={signOut} title="Sign out" aria-label="Sign out"><LogoutIcon size={15} /></button>
        </div>
      )}
      <div className="sidebar-foot">
        <span className="nav-text"><span className="dot" />Source: git main</span>
        <span className="row nav-text" style={{ gap: 6 }}><GitIcon size={13} /> <code>{sha ?? "—"}</code></span>
        {synced && <span className="nav-text">Synced {synced}</span>}
        <button className="ghost sm sidebar-toggle" onClick={toggle} aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={`${collapsed ? "Expand" : "Collapse"} sidebar (⌘B)`}>
          <PanelIcon size={16} /> <span className="nav-text">Collapse</span>
        </button>
      </div>
    </aside>
  );
}
