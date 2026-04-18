from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ProductResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    numero_lote: Optional[str] = None
    unidade_medida: Optional[str] = None
    valor_unitario_estimado: Optional[float] = None
    valor_total_estimado: Optional[float] = None
    quantity: int
    status: str
    margin: float
    min_price: Optional[float] = None
    best_marketplace: Optional[str] = None
    best_offer_url: Optional[str] = None
    best_validation_method: Optional[str] = None
    best_price_match: Optional[bool] = None
    best_is_best_seller: Optional[bool] = None
    mid_price: Optional[float] = None
    mid_marketplace: Optional[str] = None
    mid_offer_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProductStatusUpdate(BaseModel):
    status: str  # APPROVED, DISCARDED, PENDING


class ProductMarginUpdate(BaseModel):
    margin: float


class BulkMarginUpdate(BaseModel):
    margin: float
    product_ids: Optional[List[str]] = None  # None = apply to all
