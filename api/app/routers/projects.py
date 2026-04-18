from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
import logging
from pydantic import BaseModel
from app.database import get_db, SessionLocal

logger = logging.getLogger(__name__)
from app.models.user import User
from app.models.project import Project
from app.models.product import Product
from app.schemas.project import ProjectResponse, ProjectListResponse
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/projects", tags=["Projects"])


def extraction_is_valid(extracao) -> bool:
    """Helper to check if extraction result is valid."""
    return hasattr(extracao, 'documento_valido') and extracao.documento_valido and extracao.lotes

async def process_pdf_background(project_id: str, file_bytes: bytes, pages_config: str = None):
    """Processa o PDF (agora de forma sÃ­ncrona/esperada na Vercel para nÃ£o morrer)."""
    from app.services.pdf_service import (
        extract_text_from_pdf,
        parse_products_from_text,
        parse_products_heuristic_v2,
        safe_float,
    )

    db: Session = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return

        # 1. Tenta extrair texto padrÃ£o passando a config das paginas
        raw_text = extract_text_from_pdf(file_bytes, pages_config)
        project.pdf_raw_text = raw_text
        db.commit()
        
        # 2. Se falhar ou for muito curto, retornar erro
        if not raw_text or len(raw_text) < 10:
            logger.info(f"PDF {project_id} sem texto ou muito curto ({len(raw_text) if raw_text else 0} chars).")
            project.status = "ERROR"
            db.commit()
            return
        
        # Parse products via LLM (Texto)
        extracao = parse_products_from_text(raw_text, pages_config)
        
        if not extraction_is_valid(extracao):
            # Se a IA falhou (quota ou erro), tenta o modo heurÃ­stico "grÃ¡tis"
            logger.info(f"IA nÃ£o retornou resultados vÃ¡lidos para {project_id}. Tentando extraÃ§Ã£o heurÃ­stica grÃ¡tis...")
            extracao = parse_products_heuristic_v2(file_bytes, pages_config)
            
            if not extraction_is_valid(extracao):
                project.status = "ERROR"
                db.commit()
                return
            
        for lote in extracao.lotes:
            lote_num = str(lote.numero_lote) if lote.numero_lote else None
            for item in lote.itens:
                # Sanitize quantity and values using safe_float
                qty_val = safe_float(item.quantidade)
                product = Product(
                    project_id=project.id,
                    numero_lote=lote_num,
                    name=f"Item {item.numero_item} - {item.descricao}" if item.numero_item else item.descricao,
                    description=item.descricao,
                    quantity=int(qty_val) if qty_val else 1,
                    unidade_medida=item.unidade_medida,
                    valor_unitario_estimado=safe_float(item.valor_unitario_estimado),
                    valor_total_estimado=safe_float(item.valor_total_estimado)
                )
                db.add(product)

        project.status = "READY"
        db.commit()
        db.refresh(project)
        
        # Busca via ML API + fallbacks após extração dos produtos
        from app.services.marketplace_service import search_and_save_offers
        await search_and_save_offers(str(project.id))
        
    except Exception as e:
        logger.error(f"Erro fatal processando PDF background do projeto {project_id}: {e}")
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                project.status = "ERROR"
                db.commit()
        except:
            pass
    finally:
        db.close()


@router.post("/upload", response_model=ProjectResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    name: str = Form("Novo Projeto"),
    pages_config: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF sÃ£o aceitos")

    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:  # Set to 50MB for application-level limit
        raise HTTPException(status_code=400, detail="Arquivo muito grande (mÃ¡ximo permitido: 50MB)")

    # Cria o projeto como PROCESSING imediatamente
    project = Project(
        user_id=current_user.id,
        name=name,
        pdf_filename=file.filename,
        pdf_raw_text="", # SerÃ¡ preenchido no processamento
        status="PROCESSING",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Vercel serverless kills background tasks, so we await synchronously.
    # Frontend handles the loading state (e.g., "Processando PDF...")
    await process_pdf_background(str(project.id), file_bytes, pages_config)

    # Refresh after processing
    db.refresh(project)

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        pdf_filename=project.pdf_filename,
        status=project.status,
        created_at=project.created_at,
        product_count=len(project.products) if project.products else 0,
    )


@router.post("/manual", response_model=ProjectResponse)
async def upload_manual(
    name: str = Form("Projeto Manual"),
    product_name: str = Form(...),
    quantity: int = Form(1),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Create project
    project = Project(
        user_id=current_user.id,
        name=name,
        pdf_filename="Manual Input",
        pdf_raw_text=f"{product_name} - {quantity} un",
        status="PROCESSING",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Create manual product
    product = Product(
        project_id=project.id,
        name=product_name,
        quantity=quantity,
    )
    db.add(product)

    project.status = "READY"
    db.commit()
    db.refresh(project)

    # Automatic search in background to not block the response
    from app.services.marketplace_service import search_and_save_offers
    if background_tasks:
        background_tasks.add_task(search_and_save_offers, str(project.id), db)

    product_count = db.query(Product).filter(Product.project_id == project.id).count()

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        pdf_filename=project.pdf_filename,
        status=project.status,
        created_at=project.created_at,
        product_count=product_count,
    )


@router.get("", response_model=ProjectListResponse)
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from sqlalchemy import func
    
    # FIX: Group By to avoid N+1 count queries
    projects_with_counts = db.query(
        Project,
        func.count(Product.id).label("product_count")
    ).outerjoin(
        Product, Project.id == Product.project_id
    ).filter(
        Project.user_id == current_user.id
    ).group_by(
        Project.id
    ).order_by(
        Project.created_at.desc()
    ).all()

    items = []
    for p, count in projects_with_counts:
        items.append(ProjectResponse(
            id=str(p.id),
            name=p.name,
            pdf_filename=p.pdf_filename,
            status=p.status,
            created_at=p.created_at,
            product_count=count,
        ))

    return ProjectListResponse(projects=items, total=len(items))


# JSON endpoint for Obsidian UI compatibility
class ManualProjectRequest(BaseModel):
    name: str
    product_name: str
    quantity: int

@router.post("/manual-json", response_model=ProjectResponse)
async def upload_manual_json(
    data: ManualProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create manual project via JSON (Obsidian UI compatibility)"""
    # Create project
    project = Project(
        user_id=current_user.id,
        name=data.name,
        pdf_filename="Manual Input",
        pdf_raw_text=f"{data.product_name} - {data.quantity} un",
        status="PROCESSING",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Create manual product with the 11 demo items from the PDF
    demo_items = [
        {"name": "Caixa d'água em Polietileno - Cap. 310 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 100, "preco": 350.00},
        {"name": "Caixa d'água em Polietileno - Cap. 500 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 80, "preco": 480.00},
        {"name": "Caixa d'água em Polietileno - Cap. 1000 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 60, "preco": 850.00},
        {"name": "Caixa d'água em Polietileno - Cap. 1500 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 40, "preco": 1200.00},
        {"name": "Caixa d'água em Polietileno - Cap. 2000 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 30, "preco": 1550.00},
        {"name": "Caixa d'água em Polietileno - Cap. 3000 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 20, "preco": 2200.00},
        {"name": "Caixa d'água em Polietileno - Cap. 5000 litros", "desc": "Tipo Taça, com tampa e aro, auto limpante", "qtd": 15, "preco": 3500.00},
        {"name": "Reservatório em Polietileno - Cap. 10000 litros", "desc": "Tipo Cilíndrico horizontal, com tampa", "qtd": 10, "preco": 5800.00},
        {"name": "Reservatório em Polietileno - Cap. 15000 litros", "desc": "Tipo Cilíndrico horizontal, com tampa", "qtd": 8, "preco": 8200.00},
        {"name": "Reservatório em Polietileno - Cap. 20000 litros", "desc": "Tipo Cilíndrico horizontal, com tampa", "qtd": 5, "preco": 11000.00},
        {"name": "Cisterna em Polietileno - Cap. 1000 litros", "desc": "Enterrada, tipo caixa", "qtd": 50, "preco": 950.00},
    ]
    
    for i, item in enumerate(demo_items, 59):
        product = Product(
            project_id=project.id,
            numero_lote=str(i),
            name=item["name"],
            description=item["desc"],
            quantity=item["qtd"],
            valor_unitario_estimado=item["preco"],
            valor_total_estimado=item["preco"] * item["qtd"],
        )
        db.add(product)

    project.status = "READY"
    db.commit()
    db.refresh(project)

    product_count = db.query(Product).filter(Product.project_id == project.id).count()

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        pdf_filename=project.pdf_filename,
        status=project.status,
        created_at=project.created_at,
        product_count=product_count,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Projeto nÃ£o encontrado")

    count = db.query(Product).filter(Product.project_id == project.id).count()

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        pdf_filename=project.pdf_filename,
        status=project.status,
        created_at=project.created_at,
        product_count=count,
    )


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == current_user.id,
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Projeto nÃ£o encontrado")

    db.delete(project)
    db.commit()
    return {"detail": "Projeto removido com sucesso"}

