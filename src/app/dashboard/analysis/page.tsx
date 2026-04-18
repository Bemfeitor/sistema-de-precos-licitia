"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
    type LucideIcon,
    Activity,
    ArrowDownUp,
    BarChart3,
    Hash,
    Minus,
    TrendingDown,
    TrendingUp,
} from "lucide-react";
import { api } from "@/lib/api";
import type { MarketStats, Product, Project } from "@/lib/types";
import { formatCurrency, formatPercent } from "@/lib/utils";

type StatsMap = Record<string, MarketStats | null>;

const ITEMS_PER_PAGE = 12;

export default function AnalysisPage() {
    const [projects, setProjects] = useState<Project[]>([]);
    const [selectedProject, setSelectedProject] = useState("");
    const [products, setProducts] = useState<Product[]>([]);
    const [statsMap, setStatsMap] = useState<StatsMap>({});
    const [loading, setLoading] = useState(true);
    const [currentPage, setCurrentPage] = useState(1);

    useEffect(() => {
        api.projects
            .list()
            .then((data) => {
                setProjects(data.projects);
                if (data.projects.length > 0) {
                    setSelectedProject(data.projects[0].id);
                }
            })
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        if (!selectedProject) {
            return;
        }

        let active = true;
        Promise.resolve().then(() => setLoading(true));

        api.products
            .list(selectedProject)
            .then((data) => {
                if (!active) {
                    return;
                }

                setProducts(data);
                setStatsMap({});
                setCurrentPage(1);
            })
            .finally(() => {
                if (active) {
                    setLoading(false);
                }
            });

        return () => {
            active = false;
        };
    }, [selectedProject]);

    const totalPages = useMemo(() => Math.max(1, Math.ceil(products.length / ITEMS_PER_PAGE)), [products.length]);
    const paginatedProducts = useMemo(() => {
        const safePage = Math.min(currentPage, totalPages);
        const start = (safePage - 1) * ITEMS_PER_PAGE;
        return products.slice(start, start + ITEMS_PER_PAGE);
    }, [currentPage, products, totalPages]);
    const loadingVisibleStats = useMemo(
        () => paginatedProducts.some((product) => statsMap[product.id] === undefined),
        [paginatedProducts, statsMap]
    );

    useEffect(() => {
        if (!paginatedProducts.length) {
            return;
        }

        const missingProducts = paginatedProducts.filter((product) => statsMap[product.id] === undefined);
        if (!missingProducts.length) {
            return;
        }

        let active = true;

        Promise.all(
            missingProducts.map(async (product) => {
                try {
                    const stats = await api.offers.stats(product.id);
                    return [product.id, stats] as const;
                } catch {
                    return [product.id, null] as const;
                }
            })
        )
            .then((entries) => {
                if (!active) {
                    return;
                }

                setStatsMap((previous) => ({
                    ...previous,
                    ...Object.fromEntries(entries),
                }));
            });

        return () => {
            active = false;
        };
    }, [paginatedProducts, statsMap]);

    const statCard = (
        label: string,
        value: string,
        icon: LucideIcon,
        color: string,
        bg: string
    ) => {
        const Icon = icon;
        return (
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    background: bg,
                    borderRadius: 10,
                    minWidth: 140,
                }}
            >
                <Icon size={18} color={color} />
                <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{label}</div>
                </div>
            </div>
        );
    };

    return (
        <div>
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
                <h1 style={{ fontSize: 26, fontWeight: 700, marginBottom: 4 }}>Análise de Preços</h1>
                <p style={{ color: "var(--text-secondary)", fontSize: 15, marginBottom: 24 }}>
                    Estatísticas de mercado para apoio. A escolha principal prioriza preço validado no link e itens mais vendidos.
                </p>
            </motion.div>

            <select
                value={selectedProject}
                onChange={(event) => {
                    setSelectedProject(event.target.value);
                    setLoading(true);
                }}
                className="input-field"
                style={{ width: 260, padding: "10px 14px", marginBottom: 24 }}
            >
                <option value="">Selecione o projeto</option>
                {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                        {project.name}
                    </option>
                ))}
            </select>

            {loading ? (
                <div style={{ display: "grid", gap: 16 }}>
                    {Array.from({ length: 3 }).map((_, index) => (
                        <div key={index} className="skeleton" style={{ height: 120, borderRadius: 12 }} />
                    ))}
                </div>
            ) : products.length === 0 ? (
                <div className="glass-card" style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
                    <BarChart3 size={48} style={{ opacity: 0.3, marginBottom: 12 }} />
                    <div>Nenhum produto para analisar</div>
                </div>
            ) : (
                <div style={{ display: "grid", gap: 16 }}>
                    {loadingVisibleStats ? (
                        <div className="helper-text">
                            Carregando apenas as estatísticas da página atual para abrir a tela com mais fluidez.
                        </div>
                    ) : null}
                    {paginatedProducts.map((product, index) => {
                        const stats = statsMap[product.id];
                        return (
                            <motion.div
                                key={product.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: index * 0.05 }}
                                className="glass-card"
                                style={{ padding: 24 }}
                            >
                                <div
                                    style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "flex-start",
                                        marginBottom: 16,
                                        flexWrap: "wrap",
                                        gap: 8,
                                    }}
                                >
                                    <div>
                                        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                                            {product.name}
                                        </h3>
                                        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
                                            Qtd: {product.quantity}
                                        </span>
                                    </div>
                                    <span className={`badge badge-${product.status.toLowerCase()}`}>
                                        {product.status}
                                    </span>
                                </div>

                                {stats === undefined ? (
                                    <div className="skeleton" style={{ height: 96 }} />
                                ) : stats && stats.total_offers > 0 ? (
                                    <div style={{ display: "grid", gap: 12 }}>
                                        <div
                                            style={{
                                                padding: "12px 14px",
                                                borderRadius: 10,
                                                background: "rgba(34,197,94,0.08)",
                                                border: "1px solid rgba(34,197,94,0.16)",
                                                color: "var(--text-secondary)",
                                                fontSize: 13,
                                            }}
                                        >
                                            Referência operacional: a decisão do orçamento não usa média. O sistema prioriza anúncio com preço validado exatamente no link e, na sequência, ofertas de catálogo mais vendido.
                                        </div>
                                        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                                            {statCard("Menor anúncio", formatCurrency(stats.min_price), TrendingDown, "#22c55e", "rgba(34,197,94,0.08)")}
                                            {statCard("Média mercado", formatCurrency(stats.avg_price), Minus, "#f59e0b", "rgba(245,158,11,0.08)")}
                                            {statCard("Maior anúncio", formatCurrency(stats.max_price), TrendingUp, "#ef4444", "rgba(239,68,68,0.08)")}
                                            {statCard("Desvio", formatCurrency(stats.std_deviation), Activity, "#38bdf8", "rgba(56,189,248,0.08)")}
                                            {statCard("Variação", formatPercent(stats.price_variation_pct), ArrowDownUp, "#14b8a6", "rgba(20,184,166,0.08)")}
                                            {statCard("Ofertas", stats.total_offers.toString(), Hash, "#fbbf24", "rgba(251,191,36,0.08)")}
                                        </div>
                                    </div>
                                ) : (
                                    <div
                                        style={{
                                            padding: "16px",
                                            background: "rgba(56,189,248,0.05)",
                                            borderRadius: 8,
                                            fontSize: 13,
                                            color: "var(--text-muted)",
                                            textAlign: "center",
                                        }}
                                    >
                                        Nenhuma oferta encontrada. Busque preços na página de Produtos.
                                    </div>
                                )}
                            </motion.div>
                        );
                    })}
                    {products.length > ITEMS_PER_PAGE ? (
                        <div className="products-pagination" style={{ borderRadius: 16, border: "1px solid var(--border)" }}>
                            <span>
                                Mostrando {(Math.min(currentPage, totalPages) - 1) * ITEMS_PER_PAGE + 1} a{" "}
                                {Math.min(Math.min(currentPage, totalPages) * ITEMS_PER_PAGE, products.length)} de{" "}
                                {products.length} produtos
                            </span>
                            <div className="product-tag-list">
                                <button
                                    type="button"
                                    className="btn-secondary"
                                    onClick={() => setCurrentPage((previous) => Math.max(1, previous - 1))}
                                    disabled={currentPage === 1}
                                >
                                    Anterior
                                </button>
                                <span className="product-tag-pill">
                                    {Math.min(currentPage, totalPages)} / {totalPages}
                                </span>
                                <button
                                    type="button"
                                    className="btn-secondary"
                                    onClick={() => setCurrentPage((previous) => Math.min(totalPages, previous + 1))}
                                    disabled={currentPage >= totalPages}
                                >
                                    Próxima
                                </button>
                            </div>
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    );
}
