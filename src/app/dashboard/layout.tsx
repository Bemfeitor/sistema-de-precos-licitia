"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import {
  BarChart3,
  FileSpreadsheet,
  LayoutDashboard,
  LogOut,
  Menu,
  Package,
  Search,
  ShoppingBag,
  Upload,
  X,
} from "lucide-react";

const navItems = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Visão Geral" },
  { href: "/dashboard/upload", icon: Upload, label: "Upload de PDFs" },
  { href: "/dashboard/products", icon: Package, label: "Produtos" },
  { href: "/dashboard/offers", icon: ShoppingBag, label: "Ofertas" },
  { href: "/dashboard/analysis", icon: BarChart3, label: "Análise" },
  { href: "/dashboard/quotation", icon: FileSpreadsheet, label: "Orçamentos" },
];

function getCurrentLabel(pathname: string) {
  if (pathname === "/dashboard") {
    return "Visão Geral";
  }

  return navItems.find((item) => pathname.startsWith(item.href))?.label || "Painel";
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const currentLabel = getCurrentLabel(pathname);

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, router, user]);

  if (isLoading || !user) {
    return (
      <div className="auth-shell">
        <div className="skeleton" style={{ width: 280, height: 48 }} />
      </div>
    );
  }

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  const renderNav = (mobile = false) => (
    <nav style={{ display: "grid", gap: 8 }}>
      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = pathname === item.href;

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-link${isActive ? " nav-link-active" : ""}`}
            onClick={() => {
              if (mobile) {
                setMobileOpen(false);
              }
            }}
          >
            <Icon size={18} />
            <span style={{ fontWeight: 600, fontSize: 14 }}>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <div className="glass-card" style={{ padding: 18, marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
            <div className="brand-mark">
              <LayoutDashboard size={18} color="white" />
            </div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 700 }}>Preço Inteligente</div>
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Dashboard operacional</div>
            </div>
          </div>

          <div style={{ color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.55 }}>
            Extração de itens, pesquisa de ofertas e geração de orçamentos em um fluxo único.
          </div>
        </div>

        {renderNav()}

        <div className="glass-card" style={{ marginTop: "auto", padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 14,
                background: "rgba(56, 189, 248, 0.16)",
                display: "grid",
                placeItems: "center",
                fontWeight: 700,
                color: "#bae6fd",
              }}
            >
              {user.name?.charAt(0).toUpperCase()}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{user.name}</div>
              <div style={{ color: "var(--text-muted)", fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>
                {user.email}
              </div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="btn-secondary"
            style={{ width: "100%", marginTop: 14, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
          >
            <LogOut size={16} />
            Sair
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 60,
            background: "rgba(2, 8, 23, 0.56)",
            backdropFilter: "blur(6px)",
          }}
        >
          <div
            className="glass-card"
            style={{
              width: "min(88vw, 320px)",
              height: "100dvh",
              borderRadius: 0,
              padding: 18,
              borderLeft: "none",
              borderTop: "none",
              borderBottom: "none",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="brand-mark">
                  <LayoutDashboard size={18} color="white" />
                </div>
                <div style={{ fontWeight: 700 }}>Preço Inteligente</div>
              </div>
              <button
                onClick={() => setMobileOpen(false)}
                style={{ background: "none", border: "none", color: "var(--text-primary)", cursor: "pointer" }}
              >
                <X size={20} />
              </button>
            </div>

            {renderNav(true)}
          </div>
        </div>
      )}

      <div className="workspace-main">
        <header className="workspace-topbar">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={() => setMobileOpen(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 42,
                height: 42,
                borderRadius: 14,
                border: "1px solid var(--border)",
                background: "rgba(11, 23, 40, 0.88)",
                color: "var(--text-primary)",
                cursor: "pointer",
              }}
              className="lg:hidden"
            >
              <Menu size={18} />
            </button>

            <div>
              <div className="section-eyebrow">Workspace</div>
              <div style={{ fontSize: 24, fontWeight: 700, marginTop: 8 }}>{currentLabel}</div>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              className="glass-card hidden md:flex"
              style={{ alignItems: "center", gap: 10, minWidth: 280, padding: "0.8rem 1rem" }}
            >
              <Search size={16} color="var(--text-muted)" />
              <span style={{ color: "var(--text-muted)", fontSize: 14 }}>Busca rápida do workspace</span>
            </div>

            <div className="glass-card" style={{ display: "flex", alignItems: "center", gap: 12, padding: "0.65rem 0.8rem" }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 14,
                  background: "linear-gradient(135deg, rgba(56, 189, 248, 0.22), rgba(20, 184, 166, 0.26))",
                  display: "grid",
                  placeItems: "center",
                  fontWeight: 700,
                  color: "#e0f2fe",
                }}
              >
                {user.name?.charAt(0).toUpperCase()}
              </div>
              <div className="hidden md:block">
                <div style={{ fontWeight: 700, fontSize: 14 }}>{user.name}</div>
                <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{user.email}</div>
              </div>
            </div>
          </div>
        </header>

        <div className="workspace-body">
          <main className="workspace-content">{children}</main>
        </div>
      </div>
    </div>
  );
}
