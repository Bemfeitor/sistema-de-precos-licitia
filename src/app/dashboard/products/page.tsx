"use client";

import {
  Suspense,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent,
} from "react";
import { motion } from "framer-motion";
import { useSearchParams } from "next/navigation";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  ExternalLink,
  Loader2,
  Package,
  Search,
  ShoppingBag,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Product, Project } from "@/lib/types";

const ITEMS_PER_PAGE = 50;

function formatCurrency(value?: number | null) {
  if (value === null || value === undefined) {
    return "---";
  }

  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function buildMarginDrafts(products: Product[]) {
  return Object.fromEntries(products.map((product) => [product.id, String(product.margin ?? 0)]));
}

function normalizeMarginInput(value: string) {
  const parsed = Number.parseFloat(value.replace(",", "."));
  return Number.isFinite(parsed) ? parsed : 0;
}

function getStatusMeta(status: string) {
  const normalized = status?.toUpperCase?.() || "PENDING";

  if (normalized === "APPROVED") {
    return { className: "badge-approved", icon: Check, label: "Aprovado" };
  }

  if (normalized === "DISCARDED") {
    return { className: "badge-discarded", icon: X, label: "Descartado" };
  }

  if (normalized === "SUCCESS") {
    return { className: "badge-approved", icon: Check, label: "Encontrado" };
  }

  if (normalized === "ERROR" || normalized === "ERROR_NOT_FOUND") {
    return { className: "badge-discarded", icon: X, label: "Não encontrado" };
  }

  return { className: "badge-pending", icon: Clock, label: "Pendente" };
}

function StatusBadge({ status }: { status: string }) {
  const meta = getStatusMeta(status);
  const Icon = meta.icon;

  return (
    <span className={`badge ${meta.className}`}>
      <Icon size={12} />
      {meta.label}
    </span>
  );
}

function ProductNameSummary({
  name,
  expanded,
  onToggle,
}: {
  name: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="product-name-cell">
      <button
        type="button"
        className="product-name-trigger"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className={`product-name-text${expanded ? " is-expanded" : ""}`}>{name}</span>
        <span className="product-name-tooltip">{name}</span>
      </button>
      <button type="button" className="product-name-toggle" onClick={onToggle}>
        {expanded ? (
          <>
            Recolher <ChevronUp size={14} />
          </>
        ) : (
          <>
            Ver completo <ChevronDown size={14} />
          </>
        )}
      </button>
    </div>
  );
}

function ProductLinks({ product }: { product: Product }) {
  return (
    <div className="product-link-stack">
      {product.min_price ? (
        <>
          {product.best_offer_url ? (
            <a
              href={product.best_offer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="product-link-box"
              title={`Acessar oferta econômica${product.best_marketplace ? ` no ${product.best_marketplace}` : ""}`}
            >
              Econômico <ExternalLink size={12} />
            </a>
          ) : (
            <span className="product-link-secondary">{product.best_marketplace || "Sem link"}</span>
          )}
          {product.mid_price && product.mid_offer_url ? (
            <a
              href={product.mid_offer_url}
              target="_blank"
              rel="noopener noreferrer"
              className="product-link-secondary"
              title="Acessar oferta intermediária"
            >
              Intermediário <ExternalLink size={12} />
            </a>
          ) : null}
        </>
      ) : (
        <span className="product-link-secondary is-muted">---</span>
      )}
    </div>
  );
}

function ProductRowActions({
  product,
  onApprove,
  onDiscard,
  onDelete,
}: {
  product: Product;
  onApprove: () => void;
  onDiscard: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="product-actions">
      <button
        type="button"
        onClick={onApprove}
        className="product-action-button product-action-approve"
      >
        <Check size={14} />
        Aprovar
      </button>
      <button
        type="button"
        onClick={onDiscard}
        className="product-action-button product-action-discard"
      >
        <X size={14} />
        Descartar
      </button>
      <button
        type="button"
        onClick={onDelete}
        className="product-action-button product-action-remove"
        title={`Remover ${product.name}`}
      >
        <Trash2 size={14} />
        Remover
      </button>
    </div>
  );
}

export default function ProductsPage() {
  return (
    <Suspense fallback={<div className="skeleton" style={{ height: "100vh", width: "100%" }} />}>
      <ProductsContent />
    </Suspense>
  );
}

function ProductsContent() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [filterStatus, setFilterStatus] = useState("ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const [globalMargin, setGlobalMargin] = useState("");
  const [searching, setSearching] = useState(false);
  const [selectedProductIds, setSelectedProductIds] = useState<string[]>([]);
  const [expandedProductIds, setExpandedProductIds] = useState<string[]>([]);
  const [marginDrafts, setMarginDrafts] = useState<Record<string, string>>({});
  const [savingMarginId, setSavingMarginId] = useState("");
  const [isUpdating, setIsUpdating] = useState(false);

  const searchParams = useSearchParams();
  const urlProjectId = searchParams.get("projectId");
  const deferredSearchTerm = useDeferredValue(searchTerm.trim().toLowerCase());

  useEffect(() => {
    let active = true;

    api.projects
      .list()
      .then((data) => {
        if (!active) {
          return;
        }

        setProjects(data.projects);
        const nextProjectId = urlProjectId || data.projects[0]?.id || "";
        setSelectedProject(nextProjectId);
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [urlProjectId]);

  useEffect(() => {
    if (!selectedProject) {
      startTransition(() => {
        setProducts([]);
        setMarginDrafts({});
      });
      return;
    }

    let active = true;
    setLoading(true);

    api.products
      .list(selectedProject)
      .then((data) => {
        if (!active) {
          return;
        }

        startTransition(() => {
          setProducts(data);
          setMarginDrafts(buildMarginDrafts(data));
          setSelectedProductIds([]);
          setExpandedProductIds([]);
        });
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

  useEffect(() => {
    setCurrentPage(1);
  }, [deferredSearchTerm, filterStatus, selectedProject]);

  const filteredProducts = useMemo(() => {
    return products.filter((product) => {
      const matchesSearch = product.name.toLowerCase().includes(deferredSearchTerm);
      const matchesStatus = filterStatus === "ALL" || product.status === filterStatus;
      return matchesSearch && matchesStatus;
    });
  }, [products, deferredSearchTerm, filterStatus]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredProducts.length / ITEMS_PER_PAGE)),
    [filteredProducts.length]
  );

  const paginatedProducts = useMemo(() => {
    const safePage = Math.min(currentPage, totalPages);
    const start = (safePage - 1) * ITEMS_PER_PAGE;
    return filteredProducts.slice(start, start + ITEMS_PER_PAGE);
  }, [currentPage, filteredProducts, totalPages]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const summary = useMemo(() => {
    return products.reduce(
      (acc, product) => {
        const normalized = product.status?.toUpperCase?.() || "PENDING";
        if (normalized === "APPROVED") {
          acc.approved += 1;
        } else if (normalized === "DISCARDED" || normalized === "ERROR" || normalized === "ERROR_NOT_FOUND") {
          acc.discarded += 1;
        } else if (normalized === "SUCCESS") {
          acc.success += 1;
        } else {
          acc.pending += 1;
        }
        return acc;
      },
      { pending: 0, approved: 0, discarded: 0, success: 0 }
    );
  }, [products]);

  const allCurrentPageSelected =
    paginatedProducts.length > 0 &&
    paginatedProducts.every((product) => selectedProductIds.includes(product.id));

  async function refreshProducts(projectId: string) {
    const data = await api.products.list(projectId);
    startTransition(() => {
      setProducts(data);
      setMarginDrafts(buildMarginDrafts(data));
      setSelectedProductIds([]);
      setExpandedProductIds([]);
    });
  }

  async function updateStatus(id: string, status: string) {
    await api.products.updateStatus(id, status);
    startTransition(() => {
      setProducts((previous) => previous.map((product) => (product.id === id ? { ...product, status } : product)));
    });
  }

  async function commitMargin(id: string) {
    const product = products.find((item) => item.id === id);
    if (!product) {
      return;
    }

    const margin = normalizeMarginInput(marginDrafts[id] ?? String(product.margin ?? 0));
    if (margin === product.margin) {
      setMarginDrafts((previous) => ({ ...previous, [id]: String(margin) }));
      return;
    }

    setSavingMarginId(id);
    try {
      await api.products.updateMargin(id, margin);
      startTransition(() => {
        setProducts((previous) => previous.map((item) => (item.id === id ? { ...item, margin } : item)));
        setMarginDrafts((previous) => ({ ...previous, [id]: String(margin) }));
      });
    } finally {
      setSavingMarginId("");
    }
  }

  async function deleteProduct(id: string) {
    if (!confirm("Tem certeza que deseja remover este produto?")) {
      return;
    }

    await api.products.delete(id);
    startTransition(() => {
      setProducts((previous) => previous.filter((product) => product.id !== id));
      setSelectedProductIds((previous) => previous.filter((productId) => productId !== id));
      setExpandedProductIds((previous) => previous.filter((productId) => productId !== id));
    });
  }

  async function applyGlobalMargin() {
    if (!globalMargin || !selectedProject) {
      return;
    }

    const margin = normalizeMarginInput(globalMargin);
    await api.products.bulkMargin(selectedProject, margin);
    startTransition(() => {
      setProducts((previous) => previous.map((product) => ({ ...product, margin })));
      setMarginDrafts((previous) => {
        const next = { ...previous };
        for (const product of products) {
          next[product.id] = String(margin);
        }
        return next;
      });
    });
  }

  async function searchAllPrices() {
    if (!selectedProject) {
      return;
    }

    setSearching(true);
    try {
      await api.offers.searchAll(selectedProject, true, true);
      await refreshProducts(selectedProject);
    } finally {
      setSearching(false);
    }
  }

  function handleSelectAll(checked: boolean) {
    if (!checked) {
      const currentPageIds = new Set(paginatedProducts.map((product) => product.id));
      setSelectedProductIds((previous) => previous.filter((id) => !currentPageIds.has(id)));
      return;
    }

    const currentPageIds = paginatedProducts.map((product) => product.id);
    setSelectedProductIds((previous) => Array.from(new Set([...previous, ...currentPageIds])));
  }

  function handleSelect(id: string) {
    setSelectedProductIds((previous) =>
      previous.includes(id) ? previous.filter((productId) => productId !== id) : [...previous, id]
    );
  }

  function toggleExpanded(id: string) {
    setExpandedProductIds((previous) =>
      previous.includes(id) ? previous.filter((productId) => productId !== id) : [...previous, id]
    );
  }

  function handleMarginKeyDown(event: KeyboardEvent<HTMLInputElement>, id: string) {
    if (event.key === "Enter") {
      void commitMargin(id);
    }

    if (event.key === "Escape") {
      const product = products.find((item) => item.id === id);
      setMarginDrafts((previous) => ({ ...previous, [id]: String(product?.margin ?? 0) }));
    }
  }

  async function bulkUpdateStatus(status: string) {
    if (!selectedProductIds.length) {
      return;
    }

    const actionLabel = status === "APPROVED" ? "aprovar" : "descartar";
    if (!confirm(`Tem certeza que deseja ${actionLabel} ${selectedProductIds.length} itens?`)) {
      return;
    }

    setIsUpdating(true);
    try {
      await Promise.all(selectedProductIds.map((id) => api.products.updateStatus(id, status)));
      startTransition(() => {
        setProducts((previous) =>
          previous.map((product) =>
            selectedProductIds.includes(product.id) ? { ...product, status } : product
          )
        );
        setSelectedProductIds([]);
      });
    } finally {
      setIsUpdating(false);
    }
  }

  async function bulkDelete() {
    if (!selectedProductIds.length) {
      return;
    }

    if (!confirm(`Tem certeza que deseja remover ${selectedProductIds.length} itens?`)) {
      return;
    }

    setIsUpdating(true);
    try {
      await Promise.all(selectedProductIds.map((id) => api.products.delete(id)));
      const removedIds = new Set(selectedProductIds);
      startTransition(() => {
        setProducts((previous) => previous.filter((product) => !removedIds.has(product.id)));
        setSelectedProductIds([]);
        setExpandedProductIds((previous) => previous.filter((id) => !removedIds.has(id)));
      });
    } finally {
      setIsUpdating(false);
    }
  }

  return (
    <div>
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 style={{ fontSize: 26, fontWeight: 700, marginBottom: 4 }}>Produtos</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 15, marginBottom: 24 }}>
          Itens pesquisados com leitura mais limpa, ações rápidas e navegação otimizada para desktop, tablet e celular.
        </p>
      </motion.div>

      <div className="products-toolbar">
        <select
          value={selectedProject}
          onChange={(event) => setSelectedProject(event.target.value)}
          className="input-field"
        >
          <option value="">Selecione o projeto</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>

        <label className="products-search">
          <Search size={16} />
          <input
            type="text"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Buscar item por nome"
            className="input-field"
          />
        </label>

        <select
          value={filterStatus}
          onChange={(event) => setFilterStatus(event.target.value)}
          className="input-field"
        >
          <option value="ALL">Todos os status</option>
          <option value="PENDING">Pendentes</option>
          <option value="SUCCESS">Encontrados</option>
          <option value="ERROR_NOT_FOUND">Não encontrados</option>
          <option value="APPROVED">Aprovados</option>
          <option value="DISCARDED">Descartados</option>
        </select>

        <button
          type="button"
          onClick={searchAllPrices}
          disabled={searching || !selectedProject}
          className={`btn-primary${searching ? " animate-pulse" : ""}`}
        >
          {searching ? <Loader2 size={18} className="animate-spin" /> : <ShoppingBag size={18} />}
          {searching ? "Buscando..." : "Buscar preços"}
        </button>
      </div>

      <div className="products-summary-bar">
        <span className="product-tag-pill">Total: {products.length}</span>
        <span className="product-tag-pill">Pendentes: {summary.pending}</span>
        <span className="product-tag-pill">Encontrados: {summary.success}</span>
        <span className="product-tag-pill">Sem match/descartados: {summary.discarded}</span>
        <span className="product-tag-pill">
          Página {Math.min(currentPage, totalPages)} de {totalPages}
        </span>
      </div>

      <div className="products-bulk-bar">
        <div className="product-margin-field">
          <span>Margem global</span>
          <div className="product-margin-input-wrap">
            <input
              type="number"
              value={globalMargin}
              onChange={(event) => setGlobalMargin(event.target.value)}
              placeholder="5"
              className="input-field"
            />
            <span className="product-margin-symbol">%</span>
          </div>
          <button type="button" className="btn-secondary" onClick={applyGlobalMargin}>
            Aplicar em todos
          </button>
        </div>

        {selectedProductIds.length > 0 ? (
          <div className="product-tag-list">
            <span className="product-tag-pill">{selectedProductIds.length} selecionado(s)</span>
            <button type="button" className="product-action-button product-action-approve" onClick={() => bulkUpdateStatus("APPROVED")} disabled={isUpdating}>
              <Check size={14} />
              Aprovar
            </button>
            <button type="button" className="product-action-button product-action-discard" onClick={() => bulkUpdateStatus("DISCARDED")} disabled={isUpdating}>
              <X size={14} />
              Descartar
            </button>
            <button type="button" className="product-action-button product-action-remove" onClick={bulkDelete} disabled={isUpdating}>
              <Trash2 size={14} />
              Remover
            </button>
          </div>
        ) : (
          <span className="helper-text">As margens agora salvam no blur ou Enter, evitando lentidão a cada tecla.</span>
        )}
      </div>

      <div className="glass-card products-table-shell">
        <div className="products-desktop-table">
          <table className="data-table products-data-table">
            <thead>
              <tr>
                <th style={{ width: 44, textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={allCurrentPageSelected}
                    onChange={(event) => handleSelectAll(event.target.checked)}
                  />
                </th>
                <th>Lote</th>
                <th>Produto</th>
                <th>Unid.</th>
                <th>Qtd</th>
                <th>V. edital</th>
                <th>Custo unit.</th>
                <th>Links</th>
                <th>Total</th>
                <th>Margem</th>
                <th>Venda sugerida</th>
                <th>Status</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, rowIndex) => (
                  <tr key={`loading-${rowIndex}`}>
                    {Array.from({ length: 13 }).map((_, cellIndex) => (
                      <td key={`loading-cell-${cellIndex}`}>
                        <div className="skeleton" style={{ height: 18, width: cellIndex === 2 ? "96%" : "72%" }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : paginatedProducts.length === 0 ? (
                <tr>
                  <td colSpan={13} style={{ textAlign: "center", padding: 44, color: "var(--text-muted)" }}>
                    <Package size={42} style={{ opacity: 0.28, marginBottom: 12 }} />
                    <div>Nenhum item encontrado com os filtros atuais.</div>
                  </td>
                </tr>
              ) : (
                paginatedProducts.map((product) => {
                  const expanded = expandedProductIds.includes(product.id);
                  const salePrice = product.min_price ? product.min_price * (1 + product.margin / 100) : null;
                  const totalCost = product.min_price ? product.min_price * product.quantity : null;

                  return (
                    <tr key={product.id}>
                      <td style={{ textAlign: "center" }}>
                        <input
                          type="checkbox"
                          checked={selectedProductIds.includes(product.id)}
                          onChange={() => handleSelect(product.id)}
                        />
                      </td>
                      <td>
                        <span className="products-lot-pill">{product.numero_lote || "-"}</span>
                      </td>
                      <td style={{ minWidth: 290, maxWidth: 360 }}>
                        <ProductNameSummary
                          name={product.name}
                          expanded={expanded}
                          onToggle={() => toggleExpanded(product.id)}
                        />
                      </td>
                      <td>{product.unidade_medida || "un"}</td>
                      <td>{product.quantity}</td>
                      <td>{formatCurrency(product.valor_unitario_estimado)}</td>
                      <td style={{ fontWeight: 700 }}>{product.min_price ? formatCurrency(product.min_price) : "Pendente"}</td>
                      <td>
                        <ProductLinks product={product} />
                      </td>
                      <td>{formatCurrency(totalCost)}</td>
                      <td>
                        <div className="product-margin-input-wrap">
                          <input
                            type="number"
                            value={marginDrafts[product.id] ?? String(product.margin ?? 0)}
                            onChange={(event) =>
                              setMarginDrafts((previous) => ({ ...previous, [product.id]: event.target.value }))
                            }
                            onBlur={() => void commitMargin(product.id)}
                            onKeyDown={(event) => handleMarginKeyDown(event, product.id)}
                            className="input-field"
                          />
                          <span className="product-margin-symbol">%</span>
                          {savingMarginId === product.id ? (
                            <Loader2 size={14} className="product-margin-loading animate-spin" />
                          ) : null}
                        </div>
                      </td>
                      <td style={{ color: "var(--accent)", fontWeight: 700 }}>{formatCurrency(salePrice)}</td>
                      <td>
                        <StatusBadge status={product.status} />
                      </td>
                      <td>
                        <ProductRowActions
                          product={product}
                          onApprove={() => void updateStatus(product.id, "APPROVED")}
                          onDiscard={() => void updateStatus(product.id, "DISCARDED")}
                          onDelete={() => void deleteProduct(product.id)}
                        />
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="products-mobile-list">
          {loading ? (
            Array.from({ length: 4 }).map((_, index) => (
              <div key={`mobile-loading-${index}`} className="product-mobile-card">
                <div className="skeleton" style={{ height: 148 }} />
              </div>
            ))
          ) : paginatedProducts.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
              Nenhum item encontrado com os filtros atuais.
            </div>
          ) : (
            paginatedProducts.map((product) => {
              const expanded = expandedProductIds.includes(product.id);
              const salePrice = product.min_price ? product.min_price * (1 + product.margin / 100) : null;
              const totalCost = product.min_price ? product.min_price * product.quantity : null;

              return (
                <article key={product.id} className="product-mobile-card">
                  <div className="product-mobile-card-top">
                    <label className="product-mobile-check">
                      <input
                        type="checkbox"
                        checked={selectedProductIds.includes(product.id)}
                        onChange={() => handleSelect(product.id)}
                      />
                      <span>Selecionar</span>
                    </label>
                    <div className="product-tag-list">
                      <span className="products-lot-pill">{product.numero_lote || "-"}</span>
                      <StatusBadge status={product.status} />
                    </div>
                  </div>

                  <ProductNameSummary
                    name={product.name}
                    expanded={expanded}
                    onToggle={() => toggleExpanded(product.id)}
                  />

                  <div className="product-mobile-meta-grid">
                    <div className="product-mobile-meta-item">
                      <span>Unidade</span>
                      <strong>{product.unidade_medida || "un"}</strong>
                    </div>
                    <div className="product-mobile-meta-item">
                      <span>Quantidade</span>
                      <strong>{product.quantity}</strong>
                    </div>
                    <div className="product-mobile-meta-item">
                      <span>Valor edital</span>
                      <strong>{formatCurrency(product.valor_unitario_estimado)}</strong>
                    </div>
                    <div className="product-mobile-meta-item">
                      <span>Custo unitário</span>
                      <strong>{product.min_price ? formatCurrency(product.min_price) : "Pendente"}</strong>
                    </div>
                    <div className="product-mobile-meta-item">
                      <span>Total</span>
                      <strong>{formatCurrency(totalCost)}</strong>
                    </div>
                    <div className="product-mobile-meta-item">
                      <span>Venda sugerida</span>
                      <strong>{formatCurrency(salePrice)}</strong>
                    </div>
                  </div>

                  <div className="product-margin-field">
                    <span>Margem do item</span>
                    <div className="product-margin-input-wrap">
                      <input
                        type="number"
                        value={marginDrafts[product.id] ?? String(product.margin ?? 0)}
                        onChange={(event) =>
                          setMarginDrafts((previous) => ({ ...previous, [product.id]: event.target.value }))
                        }
                        onBlur={() => void commitMargin(product.id)}
                        onKeyDown={(event) => handleMarginKeyDown(event, product.id)}
                        className="input-field"
                      />
                      <span className="product-margin-symbol">%</span>
                      {savingMarginId === product.id ? (
                        <Loader2 size={14} className="product-margin-loading animate-spin" />
                      ) : null}
                    </div>
                  </div>

                  <ProductLinks product={product} />

                  <div className="product-mobile-footer">
                    <ProductRowActions
                      product={product}
                      onApprove={() => void updateStatus(product.id, "APPROVED")}
                      onDiscard={() => void updateStatus(product.id, "DISCARDED")}
                      onDelete={() => void deleteProduct(product.id)}
                    />
                  </div>
                </article>
              );
            })
          )}
        </div>

        {!loading && filteredProducts.length > ITEMS_PER_PAGE ? (
          <div className="products-pagination">
            <span>
              Mostrando {(Math.min(currentPage, totalPages) - 1) * ITEMS_PER_PAGE + 1} a{" "}
              {Math.min(Math.min(currentPage, totalPages) * ITEMS_PER_PAGE, filteredProducts.length)} de{" "}
              {filteredProducts.length} itens
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
    </div>
  );
}
