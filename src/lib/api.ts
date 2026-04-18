import type {
  AuthResponse,
  DashboardStats,
  MarketStats,
  Offer,
  Product,
  Project,
  ProjectListResponse,
  Quotation,
  User,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const AUTH_EXPIRED_EVENT = "auth:expired";

function clearBrowserSession() {
  if (typeof window === "undefined") {
    return;
  }

  localStorage.removeItem("token");
  localStorage.removeItem("user");
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
}

function redirectToLoginOnUnauthorized() {
  if (typeof window === "undefined") {
    return;
  }

  const currentPath = window.location.pathname;
  if (currentPath.startsWith("/login") || currentPath.startsWith("/register")) {
    return;
  }

  const nextUrl = `/login?reason=session-expired&next=${encodeURIComponent(`${currentPath}${window.location.search}`)}`;
  window.location.replace(nextUrl);
}

function getToken(): string | null {
  if (typeof window !== "undefined") {
    return localStorage.getItem("token");
  }

  return null;
}

function buildHeaders(options?: RequestInit): Headers {
  const headers = new Headers(options?.headers);
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return headers;
}

function normalizeErrorMessage(payload: unknown, status: number, statusText: string) {
  if (typeof payload === "string" && payload.trim()) {
    try {
      const parsed = JSON.parse(payload);
      if (parsed?.detail) {
        return parsed.detail as string;
      }
    } catch {
      return payload;
    }
  }

  if (payload && typeof payload === "object") {
    const record = payload as { detail?: string; message?: string };
    if (record.detail) {
      return record.detail;
    }
    if (record.message) {
      return record.message;
    }
  }

  return `Erro ${status}: ${statusText}`;
}

async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...options,
      cache: "no-store",
      headers: buildHeaders(options),
    });

    const contentType = response.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const payload = isJson ? await response.json().catch(() => null) : await response.text();

    if (!response.ok) {
      if (response.status === 401) {
        clearBrowserSession();
        redirectToLoginOnUnauthorized();
        throw new Error("Sua sessão expirou. Faça login novamente.");
      }

      throw new Error(normalizeErrorMessage(payload, response.status, response.statusText));
    }

    return payload as T;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "";
    if (error instanceof TypeError || message.toLowerCase().includes("fetch")) {
      throw new Error(`Não foi possível conectar ao servidor. Verifique se o backend está rodando em ${API_URL}`);
    }

    throw error;
  }
}

export const api = {
  auth: {
    login: (data: { email: string; password: string }) =>
      fetchApi<AuthResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    register: (data: { email: string; name: string; password: string }) =>
      fetchApi<AuthResponse>("/api/auth/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    me: () => fetchApi<User>("/api/auth/me"),
  },

  dashboard: {
    stats: () => fetchApi<DashboardStats>("/api/dashboard/stats"),
  },

  projects: {
    list: () => fetchApi<ProjectListResponse>("/api/projects"),
    get: (projectId: string) => fetchApi<Project>(`/api/projects/${projectId}`),
    upload: (file: File, name: string, pagesConfig?: string) => {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("name", name);

      if (pagesConfig?.trim()) {
        formData.append("pages_config", pagesConfig.trim());
      }

      return fetchApi<Project>("/api/projects/upload", {
        method: "POST",
        body: formData,
      });
    },
    uploadManual: (name: string, description: string, quantity: number) =>
      fetchApi<Project>("/api/projects/manual-json", {
        method: "POST",
        body: JSON.stringify({ name, product_name: description, quantity }),
      }),
    delete: (projectId: string) =>
      fetchApi<{ detail: string }>(`/api/projects/${projectId}`, {
        method: "DELETE",
      }),
  },

  products: {
    list: (projectId: string) => fetchApi<Product[]>(`/api/products/project/${projectId}`),
    updateStatus: (id: string, status: string) =>
      fetchApi<Product>(`/api/products/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status }),
      }),
    updateMargin: (id: string, margin: number) =>
      fetchApi<Product>(`/api/products/${id}/margin`, {
        method: "PATCH",
        body: JSON.stringify({ margin }),
      }),
    bulkMargin: (projectId: string, margin: number, productIds?: string[]) =>
      fetchApi<{ detail: string }>(`/api/products/project/${projectId}/bulk-margin`, {
        method: "POST",
        body: JSON.stringify({ margin, product_ids: productIds }),
      }),
    delete: (id: string) =>
      fetchApi<{ detail: string }>(`/api/products/${id}`, {
        method: "DELETE",
      }),
  },

  offers: {
    search: (productId: string) =>
      fetchApi<{ offers: Offer[]; menor_preco?: number; produto?: string }>(
        `/api/offers/search?product_id=${productId}`
      ),
    searchAll: (projectId: string, bestSellers = false, force = false) =>
      fetchApi<{ detail: string; total_offers?: number; products_searched?: number }>(
        `/api/offers/search-all/${projectId}?best_sellers=${bestSellers}&force=${force}`,
        {
          method: "POST",
        }
      ),
    get: (productId: string) => fetchApi<Offer[]>(`/api/offers/${productId}`),
    stats: (productId: string) => fetchApi<MarketStats>(`/api/offers/${productId}/stats`),
    another: (productId: string) =>
      fetchApi<Offer>(`/api/offers/${productId}/another`, {
        method: "POST",
      }),
  },

  quotations: {
    get: (projectId: string) => fetchApi<Quotation>(`/api/quotations/${projectId}`),
    generate: (projectId: string) =>
      fetchApi<Quotation>(`/api/quotations/generate/${projectId}`, {
        method: "POST",
      }),
  },
};
