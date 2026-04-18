import logging
import threading
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, get_db, Base
from app.services.schema_bootstrap import ensure_offer_columns
from app.models.user import User
from app.routers import auth, projects, products, offers, quotations, ml_auth
from fastapi import Depends
from sqlalchemy.orm import Session
from app.routers.auth import get_current_user

# Import all models so they register with Base
from app.models import user, project, product, offer, quotation  # noqa: F401

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _bootstrap_offer_schema_async() -> None:
    def _run() -> None:
        try:
            ensure_offer_columns(engine)
        except Exception as exc:
            logger.error(f"Offer schema bootstrap failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()

# Create FastAPI app
app = FastAPI(
    title="Preço Inteligente API",
    description="Plataforma de cotação inteligente de preços",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Create tables (Commented out for Vercel startup performance)
# In production, tables should be pre-created or managed via migrations.
# Base.metadata.create_all(bind=engine)
_bootstrap_offer_schema_async()

# Register routers
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(products.router)
app.include_router(offers.router)
app.include_router(quotations.router)
app.include_router(ml_auth.router)


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy", 
        "service": "Preço Inteligente API",
        "environment": "Vercel"
    }


@app.get("/api/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Dashboard statistics endpoint scoped to the current user."""
    from app.models.project import Project
    from app.models.product import Product
    from app.models.offer import Offer
    from sqlalchemy import func
    from datetime import datetime, timedelta

    try:
        # User's projects
        user_projects = db.query(Project.id).filter(Project.user_id == current_user.id).subquery()
        total_projects = db.query(Project).filter(Project.user_id == current_user.id).count()

        # User's products
        user_products = db.query(Product.id).filter(Product.project_id.in_(user_projects)).subquery()
        total_products = db.query(Product).filter(Product.project_id.in_(user_projects)).count()

        # User's offers
        total_offers = db.query(Offer).filter(Offer.product_id.in_(user_products)).count()

        # User's approved products
        approved = db.query(Product).filter(
            Product.project_id.in_(user_projects),
            Product.status == "APPROVED"
        ).count()

        # DAILY ACTIVITY (Last 7 days)
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        activity_data = db.query(
            func.date(Product.created_at).label('date'),
            func.count(Product.id).label('count')
        ).filter(
            Product.project_id.in_(user_projects),
            Product.created_at >= seven_days_ago
        ).group_by(
            func.date(Product.created_at)
        ).order_by(
            func.date(Product.created_at)
        ).all()

        days_map = {0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 4: "Sex", 5: "Sáb", 6: "Dom"}
        
        # Build a complete 7-day array to ensure empty days exist
        area_chart_data = []
        for i in range(6, -1, -1):
            d = datetime.utcnow() - timedelta(days=i)
            day_str = days_map[d.weekday()]
            
            # Find if we have data for this date
            count = 0
            for row in activity_data:
                # row.date could be a string or datetime.date object depending on DB backend
                row_date_str = str(row.date)
                if row_date_str == d.strftime('%Y-%m-%d'):
                    count = row.count
                    break
            
            area_chart_data.append({"name": day_str, "uv": count})

        # SAVINGS PER PRODUCT (Top 4 products with the highest difference between max and min offer)
        # 1. Get min and max offers per product
        savings_query = db.query(
            Product.name,
            (func.max(Offer.price) - func.min(Offer.price)).label('economy')
        ).join(
            Offer, Product.id == Offer.product_id
        ).filter(
            Product.project_id.in_(user_projects)
        ).group_by(
            Product.id, Product.name
        ).having(
            func.count(Offer.id) > 1  # Only products with at least 2 offers have "economy"
        ).order_by(
            (func.max(Offer.price) - func.min(Offer.price)).desc()
        ).limit(4).all()

        bar_chart_data = []
        for row in savings_query:
            # truncate name so it looks decent in the chart
            trunc_name = (row.name[:12] + '..') if len(row.name) > 12 else row.name
            bar_chart_data.append({
                "name": trunc_name.title(), 
                "economia": round(row.economy, 2)
            })

        # Fallback if no savings data available
        if not bar_chart_data:
            bar_chart_data = [
                {"name": "Eletro", "economia": 0},
                {"name": "Limpeza", "economia": 0},
                {"name": "Papelaria", "economia": 0},
                {"name": "TI", "economia": 0},
            ]

        return {
            "total_projects": total_projects,
            "total_products": total_products,
            "total_offers": total_offers,
            "approved_products": approved,
            "areaChartData": area_chart_data,
            "barChartData": bar_chart_data,
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return {
            "total_projects": 0, 
            "total_products": 0, 
            "total_offers": 0, 
            "approved_products": 0,
            "areaChartData": [],
            "barChartData": []
        }
