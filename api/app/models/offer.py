import uuid
from datetime import datetime
from sqlalchemy import Boolean, Column, String, DateTime, ForeignKey, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Offer(Base):
    __tablename__ = "offers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True)
    marketplace = Column(String, nullable=False)  # mercadolivre, shopee, amazon
    title = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    shipping = Column(Float, default=0.0)
    delivery_days = Column(Integer, nullable=True)
    seller_rating = Column(Float, nullable=True)
    url = Column(String, nullable=True)
    validated_price = Column(Float, nullable=True)
    price_match = Column(Boolean, nullable=False, default=False)
    validation_method = Column(String, nullable=True)
    is_best_seller = Column(Boolean, nullable=False, default=False)
    sold_quantity = Column(Integer, nullable=True)
    validation_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="offers")
