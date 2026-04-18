from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class OfferResponse(BaseModel):
    id: str
    product_id: str
    marketplace: str
    title: Optional[str] = None
    price: float
    shipping: float
    delivery_days: Optional[int] = None
    seller_rating: Optional[float] = None
    url: Optional[str] = None
    validated_price: Optional[float] = None
    price_match: bool = False
    validation_method: Optional[str] = None
    is_best_seller: bool = False
    sold_quantity: Optional[int] = None
    validation_checked_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class MarketStats(BaseModel):
    min_price: float
    max_price: float
    avg_price: float
    std_deviation: float
    price_variation_pct: float
    total_offers: int
