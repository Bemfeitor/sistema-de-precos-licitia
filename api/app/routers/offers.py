import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime
from app.database import get_db, SessionLocal
from app.models.user import User
from app.models.project import Project
from app.models.product import Product
from app.models.offer import Offer
from app.schemas.offer import OfferResponse, MarketStats
from app.services.marketplace_service import build_marketplace_query, search_marketplace_prices, search_additional_offer, search_and_save_offers
from app.services.stats_service import calculate_market_stats
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/offers", tags=["Offers"])
PROJECT_SEARCH_BATCH_SIZE = 50
logger = logging.getLogger(__name__)


def _build_product_query(product: Product) -> str:
    return build_marketplace_query(product)


def _build_offer_response(offer: Offer) -> OfferResponse:
    return OfferResponse(
        id=str(offer.id),
        product_id=str(offer.product_id),
        marketplace=offer.marketplace,
        title=offer.title,
        price=offer.price,
        shipping=offer.shipping,
        delivery_days=offer.delivery_days,
        seller_rating=offer.seller_rating,
        url=offer.url,
        validated_price=offer.validated_price,
        price_match=offer.price_match,
        validation_method=offer.validation_method,
        is_best_seller=offer.is_best_seller,
        sold_quantity=offer.sold_quantity,
        validation_checked_at=offer.validation_checked_at,
        created_at=offer.created_at,
    )


def _build_offer_model(product_id, offer_data: dict) -> Offer:
    validation_checked = None
    if offer_data.get("validation_method") or offer_data.get("price_match"):
        validation_checked = datetime.utcnow()

    return Offer(
        product_id=product_id,
        marketplace=offer_data.get("marketplace", "Mercado Livre"),
        title=offer_data.get("title", ""),
        price=offer_data.get("price", 0),
        shipping=offer_data.get("shipping"),
        delivery_days=offer_data.get("delivery_days"),
        seller_rating=offer_data.get("seller_rating"),
        url=offer_data.get("url", ""),
        validated_price=offer_data.get("price_validated"),
        price_match=bool(offer_data.get("price_match", False)),
        validation_method=offer_data.get("validation_method"),
        is_best_seller=bool(
            offer_data.get("is_best_seller", False) or offer_data.get("is_mais_vendido", False)
        ),
        sold_quantity=offer_data.get("sold_quantity"),
        validation_checked_at=validation_checked,
    )


async def _search_project_offers(
    project_id: str,
    current_user: User,
    db: Session,
    best_sellers: bool = True,
    force: bool = False,
):
    from app.services.marketplace_service_v4 import search_with_best_sellers_priority

    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    products = db.query(Product).filter(Product.project_id == project_id).all()
    product_ids = [product.id for product in products]

    if force:
        if product_ids:
            db.query(Offer).filter(Offer.product_id.in_(product_ids)).delete(synchronize_session=False)
            db.commit()

    total_offers = 0
    for start in range(0, len(product_ids), PROJECT_SEARCH_BATCH_SIZE):
        batch = product_ids[start:start + PROJECT_SEARCH_BATCH_SIZE]

        for product_id in batch:
            worker_db = SessionLocal()
            try:
                product = worker_db.query(Product).filter(Product.id == product_id).first()
                if not product:
                    continue

                if best_sellers:
                    offers_data, metrics = await search_with_best_sellers_priority(
                        query=_build_product_query(product),
                        quantidade_desejada=product.quantity or 1,
                        valor_maximo=product.valor_unitario_estimado or 0,
                    )
                    if not offers_data:
                        logger.info(
                            "Best-sellers path returned 0 offers for '%s'; using unified fallback pipeline",
                            _build_product_query(product),
                        )
                        offers_data = await search_marketplace_prices(
                            _build_product_query(product),
                            num_offers=3,
                        )
                    if metrics.url_menor_preco:
                        for offer_data in offers_data:
                            if offer_data.get("url") == metrics.url_menor_preco and metrics.preco_validado_no_link:
                                offer_data["marketplace"] = metrics.marketplace_label
                                offer_data["price"] = metrics.menor_preco
                else:
                    offers_data = await search_marketplace_prices(_build_product_query(product))

                if offers_data:
                    for offer_data in offers_data:
                        offer = _build_offer_model(product.id, offer_data)
                        worker_db.add(offer)
                        total_offers += 1
                    product.status = "SUCCESS"
                else:
                    product.status = "ERROR_NOT_FOUND"

                worker_db.commit()
            except Exception as exc:
                worker_db.rollback()
                logger.exception(
                    "Search failed for product_id=%s query=%r: %s",
                    product_id,
                    _build_product_query(product) if 'product' in locals() and product else "",
                    exc,
                )
                try:
                    failed_product = worker_db.query(Product).filter(Product.id == product_id).first()
                    if failed_product:
                        failed_product.status = "ERROR"
                        worker_db.commit()
                except Exception:
                    worker_db.rollback()
            finally:
                worker_db.close()

        if start + PROJECT_SEARCH_BATCH_SIZE < len(product_ids):
            await asyncio.sleep(2)

    return {
        "detail": f"Busca concluída: {total_offers} ofertas encontradas",
        "total_offers": total_offers,
        "products_searched": len(product_ids),
    }


@router.post("/search/{product_id}", response_model=List[OfferResponse])
async def search_offers(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verify ownership
    project = db.query(Project).filter(
        Project.id == product.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="Acesso negado")

    # Search marketplaces
    offers_data = await search_marketplace_prices(_build_product_query(product))

    # Save offers
    created_offers = []
    if offers_data:
        for o in offers_data:
            offer = _build_offer_model(product.id, o)
            db.add(offer)
            created_offers.append(offer)
        product.status = "SUCCESS"
    else:
        product.status = "ERROR_NOT_FOUND"

    db.commit()

    return [
        _build_offer_response(o)
        for o in created_offers
    ]


@router.get("/{product_id}", response_model=List[OfferResponse])
def get_offers(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    offers = db.query(Offer).filter(
        Offer.product_id == product_id
    ).order_by(Offer.price).all()

    return [
        _build_offer_response(o)
        for o in offers
    ]


@router.get("/{product_id}/stats", response_model=MarketStats)
def get_market_stats(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offers = db.query(Offer).filter(Offer.product_id == product_id).all()
    prices = [o.price for o in offers]
    return calculate_market_stats(prices)


@router.post("/{product_id}/another", response_model=OfferResponse)
async def get_another_offer(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    offer_data = await search_additional_offer(_build_product_query(product))
    if not offer_data:
        raise HTTPException(status_code=404, detail="Nenhuma oferta encontrada")

    offer = _build_offer_model(product.id, offer_data)
    db.add(offer)
    db.commit()
    db.refresh(offer)

    return _build_offer_response(offer)


@router.post("/search-all/{project_id}")
async def search_all_products(
    project_id: str,
    best_sellers: bool = True,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if best_sellers or force:
        return await _search_project_offers(
            project_id=project_id,
            current_user=current_user,
            db=db,
            best_sellers=best_sellers,
            force=force,
        )

    total_offers = await search_and_save_offers(project_id, db)
    return {"detail": f"Busca concluída: {total_offers} ofertas encontradas"}


# GET endpoints for Obsidian UI compatibility
@router.get("/search")
async def search_offers_get(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search offers for a product (GET method for Obsidian UI)"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    # Verify ownership
    project = db.query(Project).filter(
        Project.id == product.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="Acesso negado")

    # Search marketplaces
    offers_data = await search_marketplace_prices(_build_product_query(product))

    # Save offers
    created_offers = []
    if offers_data:
        for o in offers_data:
            offer = _build_offer_model(product.id, o)
            db.add(offer)
            created_offers.append(offer)
        product.status = "SUCCESS"
    else:
        product.status = "ERROR_NOT_FOUND"

    db.commit()

    # Find lowest price
    menor_preco = min([o.price for o in created_offers]) if created_offers else None

    return {
        "offers": [
            _build_offer_response(o)
            for o in created_offers
        ],
        "menor_preco": menor_preco,
        "produto": product.name,
    }


@router.get("/search-all")
async def search_all_get(
    project_id: str,
    best_sellers: bool = True,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search all offers for a project (GET method for compatibility)."""
    return await _search_project_offers(
        project_id=project_id,
        current_user=current_user,
        db=db,
        best_sellers=best_sellers,
        force=force,
    )
