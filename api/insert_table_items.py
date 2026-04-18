"""
Script para inserir os 11 itens da tabela PDF no banco de dados.

Tabela de Origem:
| Item | Descrição                                                  | Qtde | Unid. | Valor Unit. Máx. (R$) | Valor Total Máx. (R$) |
| :--- | :--------------------------------------------------------- | :--: | :---: | :--------------------: | :--------------------: |
| 59   | Caixa d'água polietileno reforçada com tampa 500 litros    |  10  |  Un.  |         343,33         |        3.433,30        |
| 60   | Caixa d'água polietileno reforçada com tampa 10.000 litros |  10  |  Un.  |        7.500,00        |        75.000,00       |
| 61   | Caixa d'água polietileno reforçada com tampa 1.000 litros  |  10  |  Un.  |         566,67         |        5.666,70        |
| 62   | Reservatório tanque polietileno 1.000 litros               |  10  |  Un.  |         920,00         |        9.200,00        |
| 63   | Reservatório tanque polietileno 10.000 litros              |  10  |  Un.  |        8.566,67        |        85.666,70       |
| 64   | Reservatório tanque polietileno 15.000 litros              |  10  |  Un.  |        10.033,33       |       100.333,30       |
| 65   | Reservatório tanque polietileno 2.000 litros               |  10  |  Un.  |        2.116,67        |        21.166,70       |
| 66   | Reservatório tanque polietileno 20.000 litros              |  10  |  Un.  |        16.100,00       |       161.000,00       |
| 67   | Reservatório tanque polietileno 310 litros                 |  10  |  Un.  |         600,00         |        6.000,00        |
| 68   | Reservatório tanque polietileno 5.000 litros               |  10  |  Un.  |        3.933,33        |        39.333,30       |
| 69   | Reservatório tanque polietileno 500 litros                 |  10  |  Un.  |         660,00         |        6.600,00        |
"""

import os
import sys
from decimal import Decimal
from datetime import datetime

# Configurar environment
os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'
os.environ['SECRET_KEY'] = '9a2b8c7d6e5f4g3h2i1j0k9l8m7n6o5p'

# Adicionar o diretório do app ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models.product import Product
from app.models.project import Project
from app.models.user import User
import uuid


# Dados da tabela
TABLE_ITEMS = [
    {
        "item": 59,
        "descricao": "Caixa d'água polietileno reforçada com tampa 500 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 343.33,
        "valor_total_max": 3433.30
    },
    {
        "item": 60,
        "descricao": "Caixa d'água polietileno reforçada com tampa 10.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 7500.00,
        "valor_total_max": 75000.00
    },
    {
        "item": 61,
        "descricao": "Caixa d'água polietileno reforçada com tampa 1.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 566.67,
        "valor_total_max": 5666.70
    },
    {
        "item": 62,
        "descricao": "Reservatório tanque polietileno 1.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 920.00,
        "valor_total_max": 9200.00
    },
    {
        "item": 63,
        "descricao": "Reservatório tanque polietileno 10.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 8566.67,
        "valor_total_max": 85666.70
    },
    {
        "item": 64,
        "descricao": "Reservatório tanque polietileno 15.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 10033.33,
        "valor_total_max": 100333.30
    },
    {
        "item": 65,
        "descricao": "Reservatório tanque polietileno 2.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 2116.67,
        "valor_total_max": 21166.70
    },
    {
        "item": 66,
        "descricao": "Reservatório tanque polietileno 20.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 16100.00,
        "valor_total_max": 161000.00
    },
    {
        "item": 67,
        "descricao": "Reservatório tanque polietileno 310 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 600.00,
        "valor_total_max": 6000.00
    },
    {
        "item": 68,
        "descricao": "Reservatório tanque polietileno 5.000 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 3933.33,
        "valor_total_max": 39333.30
    },
    {
        "item": 69,
        "descricao": "Reservatório tanque polietileno 500 litros",
        "qtde": 10,
        "unid": "Un.",
        "valor_unit_max": 660.00,
        "valor_total_max": 6600.00
    }
]


def get_or_create_user(db: Session) -> User:
    """Busca usuário existente ou cria novo."""
    user = db.query(User).filter(User.email == "test@example.com").first()
    if user:
        return user
    
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password=pwd_context.hash("test123"),
        name="Test User",
        created_at=datetime.utcnow()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_project(db: Session, user_id: uuid.UUID) -> Project:
    """Cria projeto para os itens da tabela."""
    project = Project(
        id=uuid.uuid4(),
        user_id=user_id,
        name="Licitação - Caixas e Reservatórios Polietileno",
        description="11 itens: Caixas d'água e reservatórios de polietileno variados",
        status="READY",
        created_at=datetime.utcnow()
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def insert_items(db: Session, project_id: uuid.UUID):
    """Insere os 11 itens da tabela como produtos."""
    products = []
    
    for item_data in TABLE_ITEMS:
        product = Product(
            id=uuid.uuid4(),
            project_id=project_id,
            name=item_data["descricao"],
            description=f"Item {item_data['item']} - {item_data['descricao']}",
            numero_lote=str(item_data["item"]),
            unidade_medida=item_data["unid"],
            valor_unitario_estimado=item_data["valor_unit_max"],
            valor_total_estimado=item_data["valor_total_max"],
            quantity=item_data["qtde"],
            status="PENDING",
            margin=0.0,
            created_at=datetime.utcnow()
        )
        products.append(product)
        db.add(product)
    
    db.commit()
    return products


def main():
    """Função principal."""
    print("\n" + "=" * 80)
    print("INSERINDO ITENS DA TABELA NO BANCO DE DADOS")
    print("=" * 80)
    
    db = SessionLocal()
    try:
        # 1. Buscar/criar usuário
        print("\n[1/4] Verificando usuário...")
        user = get_or_create_user(db)
        print(f"   ✅ Usuário: {user.email}")
        
        # 2. Criar projeto
        print("\n[2/4] Criando projeto...")
        project = create_project(db, user.id)
        print(f"   ✅ Projeto criado: {project.name}")
        print(f"   📋 ID: {project.id}")
        
        # 3. Inserir itens
        print("\n[3/4] Inserindo 11 itens da tabela...")
        products = insert_items(db, project.id)
        print(f"   ✅ {len(products)} produtos inseridos")
        
        # 4. Resumo
        print("\n[4/4] Resumo:")
        total_orcado = sum(p.valor_total_estimado for p in products)
        print(f"   📊 Total orçado: R$ {total_orcado:,.2f}")
        print(f"   📦 Produtos: {len(products)}")
        print(f"   🔑 Project ID: {project.id}")
        
        print("\n" + "=" * 80)
        print("✅ ITENS INSERIDOS COM SUCESSO!")
        print("=" * 80)
        print(f"\n🔗 Para buscar preços, acesse:")
        print(f"   http://localhost:3000/dashboard/products?projectId={project.id}")
        print(f"\n📝 Ou execute o script de busca:")
        print(f"   python test_squad_busca.py {project.id}")
        print("")
        
        return project.id
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    project_id = main()
    print(f"\nPROJECT_ID={project_id}")
