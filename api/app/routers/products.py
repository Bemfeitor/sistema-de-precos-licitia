from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.database import get_db
from app.models.user import User
from app.models.project import Project
from app.models.product import Product
from app.schemas.product import ProductResponse, ProductStatusUpdate, ProductMarginUpdate, BulkMarginUpdate
from app.services.offer_selection import select_best_offer, select_mid_offer
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/products", tags=["Products"])


def _verify_product_ownership(product_id: str, current_user: User, db: Session) -> Product:
    product = db.query(Product).options(joinedload(Product.offers)).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    project = db.query(Project).filter(
        Project.id == product.project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=403, detail="Acesso negado")

    return product


@router.get("/project/{project_id}", response_model=List[ProductResponse])
def list_products(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify project ownership
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    # FIX for N+1 queries: Eager load offers in the same query
    products = db.query(Product).options(joinedload(Product.offers)).filter(
        Product.project_id == project_id
    ).order_by(Product.created_at).all()

    # Calculate offers for each product
    response = []
    for p in products:
        best_offer = select_best_offer(p.offers)
        mid_offer = select_mid_offer(p.offers, best_offer) if best_offer else None
        
        response.append(
            ProductResponse(
                id=str(p.id),
                project_id=str(p.project_id),
                name=p.name,
                description=p.description,
                numero_lote=p.numero_lote,
                unidade_medida=p.unidade_medida,
                valor_unitario_estimado=p.valor_unitario_estimado,
                valor_total_estimado=p.valor_total_estimado,
                quantity=p.quantity,
                status=p.status,
                margin=p.margin,
                min_price=best_offer.price if best_offer else None,
                best_marketplace=best_offer.marketplace if best_offer else None,
                best_offer_url=best_offer.url if best_offer else None,
                best_validation_method=best_offer.validation_method if best_offer else None,
                best_price_match=best_offer.price_match if best_offer else None,
                best_is_best_seller=best_offer.is_best_seller if best_offer else None,
                mid_price=mid_offer.price if mid_offer else None,
                mid_marketplace=mid_offer.marketplace if mid_offer else None,
                mid_offer_url=mid_offer.url if mid_offer else None,
                created_at=p.created_at,
            )
        )
    return response


@router.patch("/{product_id}/status", response_model=ProductResponse)
def update_status(
    product_id: str,
    data: ProductStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.status not in ("PENDING", "APPROVED", "DISCARDED"):
        raise HTTPException(status_code=400, detail="Status inválido")

    product = _verify_product_ownership(product_id, current_user, db)
    product.status = data.status
    db.commit()
    db.refresh(product)

    best_offer = select_best_offer(product.offers)

    return ProductResponse(
        id=str(product.id),
        project_id=str(product.project_id),
        name=product.name,
        description=product.description,
        numero_lote=product.numero_lote,
        unidade_medida=product.unidade_medida,
        valor_unitario_estimado=product.valor_unitario_estimado,
        valor_total_estimado=product.valor_total_estimado,
        quantity=product.quantity,
        status=product.status,
        margin=product.margin,
        min_price=best_offer.price if best_offer else None,
        best_marketplace=best_offer.marketplace if best_offer else None,
        best_offer_url=best_offer.url if best_offer else None,
        best_validation_method=best_offer.validation_method if best_offer else None,
        best_price_match=best_offer.price_match if best_offer else None,
        best_is_best_seller=best_offer.is_best_seller if best_offer else None,
        created_at=product.created_at,
    )


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    data: ProductStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update product status (PUT method for Obsidian UI compatibility)"""
    if data.status not in ("PENDING", "APPROVED", "DISCARDED", "SUCCESS", "ERROR", "ERROR_NOT_FOUND"):
        raise HTTPException(status_code=400, detail="Status inválido")

    product = _verify_product_ownership(product_id, current_user, db)
    product.status = data.status
    db.commit()
    db.refresh(product)

    best_offer = select_best_offer(product.offers)

    return ProductResponse(
        id=str(product.id),
        project_id=str(product.project_id),
        name=product.name,
        description=product.description,
        numero_lote=product.numero_lote,
        unidade_medida=product.unidade_medida,
        valor_unitario_estimado=product.valor_unitario_estimado,
        valor_total_estimado=product.valor_total_estimado,
        quantity=product.quantity,
        status=product.status,
        margin=product.margin,
        min_price=best_offer.price if best_offer else None,
        best_marketplace=best_offer.marketplace if best_offer else None,
        best_offer_url=best_offer.url if best_offer else None,
        best_validation_method=best_offer.validation_method if best_offer else None,
        best_price_match=best_offer.price_match if best_offer else None,
        best_is_best_seller=best_offer.is_best_seller if best_offer else None,
        created_at=product.created_at,
    )


@router.patch("/{product_id}/margin", response_model=ProductResponse)
def update_margin(
    product_id: str,
    data: ProductMarginUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = _verify_product_ownership(product_id, current_user, db)
    product.margin = data.margin
    db.commit()
    db.refresh(product)

    best_offer = select_best_offer(product.offers)

    return ProductResponse(
        id=str(product.id),
        project_id=str(product.project_id),
        name=product.name,
        description=product.description,
        numero_lote=product.numero_lote,
        unidade_medida=product.unidade_medida,
        valor_unitario_estimado=product.valor_unitario_estimado,
        valor_total_estimado=product.valor_total_estimado,
        quantity=product.quantity,
        status=product.status,
        margin=product.margin,
        min_price=best_offer.price if best_offer else None,
        best_marketplace=best_offer.marketplace if best_offer else None,
        best_offer_url=best_offer.url if best_offer else None,
        best_validation_method=best_offer.validation_method if best_offer else None,
        best_price_match=best_offer.price_match if best_offer else None,
        best_is_best_seller=best_offer.is_best_seller if best_offer else None,
        created_at=product.created_at,
    )


@router.post("/project/{project_id}/bulk-margin")
def bulk_update_margin(
    project_id: str,
    data: BulkMarginUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    query = db.query(Product).filter(Product.project_id == project_id)
    if data.product_ids:
        query = query.filter(Product.id.in_(data.product_ids))

    updated = query.update({Product.margin: data.margin}, synchronize_session="fetch")
    db.commit()

    return {"detail": f"{updated} produtos atualizados com sucesso"}

@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = _verify_product_ownership(product_id, current_user, db)
    db.delete(product)
    db.commit()
    return {"detail": "Produto removido com sucesso"}


# GET endpoint for Obsidian UI compatibility
@router.get("/")
def list_products_query(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List products by project_id query param (Obsidian UI compatibility)"""
    return list_products(project_id, db, current_user)

