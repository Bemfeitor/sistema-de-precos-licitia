from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
import io
from app.database import get_db
from app.models.user import User
from app.models.project import Project
from app.models.product import Product
from app.models.offer import Offer
from app.models.quotation import Quotation
from app.schemas.quotation import QuotationResponse, QuotationItem
from app.services.excel_service import generate_quotation_excel
from app.services.offer_selection import select_best_offer
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/quotations", tags=["Quotations"])


@router.post("/generate/{project_id}", response_model=QuotationResponse)
def generate_quotation(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    products = db.query(Product).filter(
        Product.project_id == project_id,
        Product.status == "APPROVED",
    ).all()

    if not products:
        raise HTTPException(
            status_code=400,
            detail="Nenhum produto aprovado. Aprove produtos antes de gerar o orçamento."
        )

    # Delete existing quotations for this project
    db.query(Quotation).filter(Quotation.project_id == project_id).delete()

    items = []
    total_cost = 0
    total_suggested = 0

    for product in products:
        # Get best offer (lowest price)
        offers = db.query(Offer).filter(Offer.product_id == product.id).all()
        best_offer = select_best_offer(offers)

        if not best_offer:
            continue

        cost = best_offer.price
        margin = product.margin
        suggested_price = round(cost * (1 + margin / 100), 2)

        quotation = Quotation(
            project_id=project.id,
            product_id=product.id,
            cost=cost,
            margin=margin,
            suggested_price=suggested_price,
        )
        db.add(quotation)

        total_cost += cost * product.quantity
        total_suggested += suggested_price * product.quantity

        items.append(QuotationItem(
            id=str(product.id),
            product_name=product.name,
            quantity=product.quantity,
            cost=cost,
            margin=margin,
            suggested_price=suggested_price,
            product_url=best_offer.url,
        ))

    project.status = "COMPLETED"
    db.commit()

    return QuotationResponse(
        project_id=str(project.id),
        project_name=project.name,
        items=items,
        total_cost=round(total_cost, 2),
        total_suggested=round(total_suggested, 2),
        created_at=datetime.utcnow(),
    )


@router.get("/{project_id}", response_model=QuotationResponse)
def get_quotation(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    quotations = db.query(Quotation).filter(
        Quotation.project_id == project_id
    ).all()

    if not quotations:
        raise HTTPException(status_code=404, detail="Orçamento não gerado ainda")

    items = []
    total_cost = 0
    total_suggested = 0

    for q in quotations:
        product = db.query(Product).filter(Product.id == q.product_id).first()
        offers = db.query(Offer).filter(Offer.product_id == q.product_id).all()
        best_offer = select_best_offer(offers)

        if product:
            total_cost += q.cost * product.quantity
            total_suggested += q.suggested_price * product.quantity
            items.append(QuotationItem(
                id=str(product.id),
                product_name=product.name,
                quantity=product.quantity,
                cost=q.cost,
                margin=q.margin,
                suggested_price=q.suggested_price,
                product_url=best_offer.url if best_offer else None,
            ))

    return QuotationResponse(
        project_id=str(project.id),
        project_name=project.name,
        items=items,
        total_cost=round(total_cost, 2),
        total_suggested=round(total_suggested, 2),
        created_at=quotations[0].created_at if quotations else datetime.utcnow(),
    )


@router.get("/export/{project_id}")
def export_quotation(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")

    quotations = db.query(Quotation).filter(
        Quotation.project_id == project_id
    ).all()

    if not quotations:
        raise HTTPException(status_code=404, detail="Gere o orçamento antes de exportar")

    items = []
    for q in quotations:
        product = db.query(Product).filter(Product.id == q.product_id).first()
        offers = db.query(Offer).filter(Offer.product_id == q.product_id).all()
        best_offer = select_best_offer(offers)

        if product:
            items.append({
                "product_name": product.name,
                "quantity": product.quantity,
                "cost": q.cost,
                "margin": q.margin,
                "suggested_price": q.suggested_price,
                "product_url": best_offer.url if best_offer else "",
            })

    excel_bytes = generate_quotation_excel(project.name, items)

    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="orcamento_{project.name}.xlsx"'
        },
    )
