"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type User } from "@/lib/api";

const TITLES: Record<string, string> = {
  "/new": "New batch",
  "/history": "History",
  "/settings": "Settings",
  "/audit": "Audit log",
};

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => router.replace("/login?error=session_expired"));
  }, [router]);

  if (!user) {
    return (
      <div className="boot">
        <span className="spinner" />
      </div>
    );
  }

  const title = path.startsWith("/batches/") ? "Batch" : TITLES[path] || "ARK HR";
  const item = (href: string, label: string) => (
    <Link href={href} className={path === href || path.startsWith(href + "/") ? "active" : ""} title={label}>
      <span>{label}</span>
    </Link>
  );

  return (
    <div className={collapsed ? "app-shell collapsed" : "app-shell"}>
      <aside className="side">
        <div className="side-head">
          <Link href="/new">
            <img src={collapsed ? "/logo-icon.svg" : "/logo-full.svg"} alt="ARK IMPEX" />
          </Link>
          <button type="button" aria-label="Collapse sidebar" onClick={() => setCollapsed((value) => !value)}>
            {collapsed ? "»" : "«"}
          </button>
        </div>
        <nav className="nav">
          {item("/new", "New batch")}
          {item("/history", "History")}
          {user.role === "admin" && user.phase >= 2 && item("/settings", "Settings")}
          {user.role === "admin" && user.phase >= 2 && item("/audit", "Audit log")}
        </nav>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="bg-grid" />
          <p className="crumbs">
            ARK HR <span>/ {title}</span>
          </p>
          <div className="account">
            <div>
              <strong>{user.name || "User"}</strong>
              <span>{user.role === "admin" ? "ARK HR admin" : "HR user"}</span>
            </div>
            <button
              className="ghost"
              onClick={async () => {
                await api("/auth/logout", { method: "POST" });
                router.replace("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        <main className="main">{children}</main>
      </div>
    </div>
  );
}
