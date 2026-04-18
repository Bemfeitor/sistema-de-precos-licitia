"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DashboardStats } from "@/lib/types";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  DollarSign,
  FileSpreadsheet,
  FolderOpen,
  Package,
  ShoppingBag,
  Upload,
} from "lucide-react";

const statCards = [
  { label: "Projetos ativos", key: "total_projects" as const, icon: FolderOpen, color: "#67e8f9", bg: "rgba(56, 189, 248, 0.12)" },
  { label: "Produtos processados", key: "total_products" as const, icon: Package, color: "#99f6e4", bg: "rgba(20, 184, 166, 0.12)" },
  { label: "Ofertas encontradas", key: "total_offers" as const, icon: ShoppingBag, color: "#fde68a", bg: "rgba(251, 191, 36, 0.12)" },
  { label: "Itens aprovados", key: "approved_products" as const, icon: CheckCircle2, color: "#86efac", bg: "rgba(52, 211, 153, 0.12)" },
];

export default function DashboardPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.dashboard
      .stats()
      .then((data) => setStats(data))
      .catch(() =>
        setStats({
          total_projects: 0,
          total_products: 0,
          total_offers: 0,
          approved_products: 0,
          areaChartData: [],
          barChartData: [],
        })
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ display: "grid", gap: 24 }}>
      <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="glass-card" style={{ padding: "clamp(1.25rem, 3vw, 2rem)" }}>
        <div style={{ display: "grid", gap: 16 }}>
          <span className="section-eyebrow">Dashboard executivo</span>
          <div>
            <h1 className="page-title">Bem-vindo de volta, {user?.name?.split(" ")[0]}</h1>
            <p className="page-subtitle" style={{ marginTop: 12 }}>
              Acompanhe a saúde da operação, encontre oportunidades de economia e avance rapidamente do PDF até o orçamento final.
            </p>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <Link href="/dashboard/upload">
              <button className="btn-primary" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Upload size={16} />
                Nova análise
              </button>
            </Link>
            <Link href="/dashboard/products">
              <button className="btn-secondary" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <ArrowRight size={16} />
                Revisar itens
              </button>
            </Link>
            <Link href="/dashboard/quotation">
              <button className="btn-secondary" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <FileSpreadsheet size={16} />
                Gerar orçamentos
              </button>
            </Link>
          </div>
        </div>
      </motion.section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 18 }}>
        {statCards.map((card, index) => {
          const Icon = card.icon;
          const value = stats?.[card.key] ?? 0;

          return (
            <motion.div
              key={card.label}
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.08 }}
              className="glass-card"
              style={{ padding: 20, display: "grid", gap: 14 }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <div style={{ color: "var(--text-secondary)", fontWeight: 600 }}>{card.label}</div>
                <div style={{ width: 42, height: 42, borderRadius: 14, display: "grid", placeItems: "center", background: card.bg }}>
                  <Icon size={18} color={card.color} />
                </div>
              </div>

              <div style={{ fontSize: 34, fontWeight: 700, lineHeight: 1 }}>
                {loading ? <div className="skeleton" style={{ width: 72, height: 34 }} /> : value}
              </div>
            </motion.div>
          );
        })}
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))", gap: 18 }}>
        <div className="glass-card" style={{ padding: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>Atividade da semana</div>
              <div className="helper-text">Itens processados nos últimos 7 dias</div>
            </div>
            <Activity size={18} color="var(--text-muted)" />
          </div>

          <div style={{ height: 320, width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stats?.areaChartData || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="dashboardActivity" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.42} />
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="rgba(148, 163, 184, 0.12)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "rgba(8, 17, 31, 0.94)", border: "1px solid rgba(148, 163, 184, 0.14)", borderRadius: 16 }} />
                <Area type="monotone" dataKey="uv" stroke="#38bdf8" strokeWidth={3} fill="url(#dashboardActivity)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="glass-card" style={{ padding: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>Maior potencial de economia</div>
              <div className="helper-text">Produtos com maior variação entre ofertas</div>
            </div>
            <DollarSign size={18} color="var(--text-muted)" />
          </div>

          <div style={{ height: 320, width: "100%" }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stats?.barChartData || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="rgba(148, 163, 184, 0.12)" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "rgba(8, 17, 31, 0.94)", border: "1px solid rgba(148, 163, 184, 0.14)", borderRadius: 16 }} />
                <Bar dataKey="economia" fill="#14b8a6" radius={[10, 10, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>
    </div>
  );
}
