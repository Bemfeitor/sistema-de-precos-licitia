"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
    BadgeCheck,
    Clock,
    ExternalLink,
    Loader2,
    Plus,
    ShoppingBag,
    Star,
    Store,
    Tag,
    Truck,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Offer, Product, Project } from "@/lib/types";
import { formatCurrency } from "@/lib/utils";

const marketplaceColors: Record<string, { bg: string; color: string }> = {
    "Mercado Livre": { bg: "rgba(255,224,51,0.12)", color: "#ffe033" },
    Shopee: { bg: "rgba(238,77,45,0.12)", color: "#ee4d2d" },
    Amazon: { bg: "rgba(255,153,0,0.12)", color: "#ff9900" },
};

const ITEMS_PER_PAGE = 12;

function offerConfidenceBadges(offer: Offer) {
    const badges: Array<{ label: string; bg: string; color: string }> = [];

    if (offer.price_match) {
        badges.push({
            label: "Preço Validado",
            bg: "rgba(34,197,94,0.12)",
            color: "#22c55e",
        });
    }

    if (offer.is_best_seller) {
        badges.push({
            label: "Mais Vendido",
            bg: "rgba(59,130,246,0.12)",
            color: "#60a5fa",
        });
    }

    return badges;
}

export default function OffersPage() {
    const [projects, setProjects] = useState<Project[]>([]);
    const [selectedProject, setSelectedProject] = useState("");
    const [products, setProducts] = useState<Product[]>([]);
    const [offersMap, setOffersMap] = useState<Record<string, Offer[]>>({});
    const [loading, setLoading] = useState(true);
    const [loadingOffer, setLoadingOffer] = useState("");
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
                setOffersMap({});
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
    const loadingVisibleOffers = useMemo(
        () => paginatedProducts.some((product) => offersMap[product.id] === undefined),
        [offersMap, paginatedProducts]
    );

    useEffect(() => {
        if (!paginatedProducts.length) {
            return;
        }

        const missingProducts = paginatedProducts.filter((product) => offersMap[product.id] === undefined);
        if (!missingProducts.length) {
            return;
        }

        let active = true;

        Promise.all(
            missingProducts.map(async (product) => {
                try {
                    const productOffers = await api.offers.get(product.id);
                    return [product.id, productOffers] as const;
                } catch {
                    return [product.id, []] as const;
                }
            })
        )
            .then((entries) => {
                if (!active) {
                    return;
                }

                setOffersMap((previous) => ({
                    ...previous,
                    ...Object.fromEntries(entries),
                }));
            });

        return () => {
            active = false;
        };
    }, [offersMap, paginatedProducts]);

    const handleAnotherOffer = async (productId: string) => {
        setLoadingOffer(productId);
        try {
            const offer = await api.offers.another(productId);
            setOffersMap((prev) => ({
                ...prev,
                [productId]: [...(prev[productId] || []), offer],
            }));
        } finally {
            setLoadingOffer("");
        }
    };

    return (
        <div>
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
                <h1 style={{ fontSize: 26, fontWeight: 700, marginBottom: 4 }}>Ofertas</h1>
                <p style={{ color: "var(--text-secondary)", fontSize: 15, marginBottom: 24 }}>
                    Ofertas encontradas nos marketplaces, com destaque para preço validado e itens mais vendidos.
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
                        <div key={index} className="skeleton" style={{ height: 140, borderRadius: 12 }} />
                    ))}
                </div>
            ) : products.length === 0 ? (
                <div className="glass-card" style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
                    <ShoppingBag size={48} style={{ opacity: 0.3, marginBottom: 12 }} />
                    <div>Nenhum produto com ofertas</div>
                </div>
            ) : (
                <div style={{ display: "grid", gap: 24 }}>
                    {loadingVisibleOffers ? (
                        <div className="helper-text">
                            Carregando apenas as ofertas da página atual para manter a navegação mais rápida.
                        </div>
                    ) : null}
                    {paginatedProducts.map((product) => {
                        const offers = offersMap[product.id];
                        return (
                            <motion.div
                                key={product.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="glass-card"
                                style={{ padding: 24 }}
                            >
                                <div
                                    style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                        marginBottom: 16,
                                        flexWrap: "wrap",
                                        gap: 8,
                                    }}
                                >
                                    <div>
                                        <h3 style={{ fontSize: 16, fontWeight: 600 }}>{product.name}</h3>
                                        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4, display: "flex", gap: 12, flexWrap: "wrap" }}>
                                            <span>Qtd real: {product.quantity}</span>
                                            {product.unidade_medida ? <span>Unidade: {product.unidade_medida}</span> : null}
                                            {product.best_marketplace ? <span>Referência atual: {product.best_marketplace}</span> : null}
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => handleAnotherOffer(product.id)}
                                        disabled={loadingOffer === product.id}
                                        className="btn-secondary"
                                        style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 14px", fontSize: 13 }}
                                    >
                                        {loadingOffer === product.id ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                        Outra oferta
                                    </button>
                                </div>

                                {offers === undefined ? (
                                    <div className="skeleton" style={{ height: 96 }} />
                                ) : offers.length === 0 ? (
                                    <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                                        Nenhuma oferta. Busque preços na página de Produtos.
                                    </div>
                                ) : (
                                    <div
                                        style={{
                                            display: "grid",
                                            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
                                            gap: 12,
                                        }}
                                    >
                                        {offers.map((offer, index) => {
                                            const mp = marketplaceColors[offer.marketplace] || marketplaceColors["Mercado Livre"];
                                            const badges = offerConfidenceBadges(offer);

                                            return (
                                                <div
                                                    key={offer.id || `${product.id}-${index}`}
                                                    style={{
                                                        background: "var(--bg-secondary)",
                                                        border: "1px solid var(--border)",
                                                        borderRadius: 12,
                                                        padding: 16,
                                                    }}
                                                >
                                                    <div
                                                        style={{
                                                            display: "flex",
                                                            justifyContent: "space-between",
                                                            alignItems: "center",
                                                            marginBottom: 12,
                                                            gap: 8,
                                                        }}
                                                    >
                                                        <span
                                                            style={{
                                                                background: mp.bg,
                                                                color: mp.color,
                                                                padding: "4px 10px",
                                                                borderRadius: 20,
                                                                fontSize: 11,
                                                                fontWeight: 600,
                                                            }}
                                                        >
                                                            <Store size={12} style={{ marginRight: 4, verticalAlign: "middle" }} />
                                                            {offer.marketplace}
                                                        </span>
                                                        {offer.url && (
                                                            <a
                                                                href={offer.url}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                style={{ color: "var(--text-muted)", display: "flex", alignItems: "center" }}
                                                            >
                                                                <ExternalLink size={14} />
                                                            </a>
                                                        )}
                                                    </div>

                                                    {badges.length > 0 && (
                                                        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                                                            {badges.map((badge) => (
                                                                <span
                                                                    key={badge.label}
                                                                    style={{
                                                                        display: "inline-flex",
                                                                        alignItems: "center",
                                                                        gap: 4,
                                                                        background: badge.bg,
                                                                        color: badge.color,
                                                                        padding: "4px 8px",
                                                                        borderRadius: 999,
                                                                        fontSize: 11,
                                                                        fontWeight: 600,
                                                                    }}
                                                                >
                                                                    <BadgeCheck size={12} />
                                                                    {badge.label}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}

                                                    <div
                                                        style={{
                                                            fontSize: 13,
                                                            color: "var(--text-secondary)",
                                                            marginBottom: 12,
                                                            lineHeight: 1.4,
                                                            display: "-webkit-box",
                                                            WebkitLineClamp: 2,
                                                            WebkitBoxOrient: "vertical",
                                                            overflow: "hidden",
                                                        }}
                                                    >
                                                        {offer.title || offer.marketplace}
                                                    </div>

                                                    <div style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)", marginBottom: 8 }}>
                                                        {formatCurrency(offer.price)}
                                                    </div>

                                                    {offer.validated_price && (
                                                        <div style={{ fontSize: 12, color: "#86efac", marginBottom: 10 }}>
                                                            Valor confirmado no anúncio: {formatCurrency(offer.validated_price)}
                                                        </div>
                                                    )}

                                                    <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 10 }}>
                                                        Quantidade do item no projeto: {product.quantity}
                                                    </div>

                                                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, fontSize: 12, color: "var(--text-muted)" }}>
                                                        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                                            <Truck size={12} />
                                                            {offer.shipping > 0 ? formatCurrency(offer.shipping) : "Grátis"}
                                                        </span>
                                                        {offer.delivery_days && (
                                                            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                                                <Clock size={12} />
                                                                {offer.delivery_days}d
                                                            </span>
                                                        )}
                                                        {offer.seller_rating && (
                                                            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                                                <Star size={12} />
                                                                {offer.seller_rating.toFixed(1)}
                                                            </span>
                                                        )}
                                                        {offer.sold_quantity ? (
                                                            <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                                                <Tag size={12} />
                                                                {offer.sold_quantity}+ vendas
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                </div>
                                            );
                                        })}
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
