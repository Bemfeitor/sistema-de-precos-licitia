export interface User {
  id: string;
  email: string;
  name: string;
  created_at?: string;
}

export interface AuthResponse {
  access_token: string;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  pdf_filename: string;
  status: string;
  created_at: string;
  product_count: number;
}

export interface ProjectListResponse {
  projects: Project[];
  total: number;
}

export interface Product {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  numero_lote?: string | null;
  unidade_medida?: string | null;
  valor_unitario_estimado?: number | null;
  valor_total_estimado?: number | null;
  quantity: number;
  status: string;
  margin: number;
  min_price?: number | null;
  best_marketplace?: string | null;
  best_offer_url?: string | null;
  best_validation_method?: string | null;
  best_price_match?: boolean | null;
  best_is_best_seller?: boolean | null;
  mid_price?: number | null;
  mid_marketplace?: string | null;
  mid_offer_url?: string | null;
  created_at: string;
}

export interface Offer {
  id: string;
  product_id: string;
  marketplace: string;
  title: string;
  price: number;
  shipping: number;
  delivery_days?: number | null;
  seller_rating?: number | null;
  seller_name?: string | null;
  validated_price?: number | null;
  price_match?: boolean;
  validation_method?: string | null;
  is_best_seller?: boolean | null;
  sold_quantity?: number | null;
  validation_checked_at?: string | null;
  url: string;
  created_at: string;
}

export interface MarketStats {
  min_price: number;
  max_price: number;
  avg_price: number;
  std_deviation: number;
  price_variation_pct: number;
  total_offers: number;
}

export interface QuotationItem {
  id: string;
  product_name: string;
  quantity: number;
  cost: number;
  margin: number;
  suggested_price: number;
  product_url?: string | null;
}

export interface Quotation {
  project_id: string;
  project_name: string;
  items: QuotationItem[];
  total_cost: number;
  total_suggested: number;
  created_at: string;
}

export interface DashboardStats {
  total_projects: number;
  total_products: number;
  total_offers: number;
  approved_products: number;
  areaChartData?: Array<{ name: string; uv: number }>;
  barChartData?: Array<{ name: string; economia: number }>;
}
