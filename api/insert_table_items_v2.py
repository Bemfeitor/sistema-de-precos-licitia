"""
Script para inserir os 11 itens da tabela PDF no banco de dados - VERSÃO SIMPLIFICADA
"""

import os
import sys
import uuid
from datetime import datetime

os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Conectar diretamente ao banco
database_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
engine = create_engine(database_url)

# Dados da tabela
TABLE_ITEMS = [
    {"item": 59, "descricao": "Caixa d'agua polietileno reforcada com tampa 500 litros", "qtde": 10, "valor_unit_max": 343.33},
    {"item": 60, "descricao": "Caixa d'agua polietileno reforcada com tampa 10000 litros", "qtde": 10, "valor_unit_max": 7500.00},
    {"item": 61, "descricao": "Caixa d'agua polietileno reforcada com tampa 1000 litros", "qtde": 10, "valor_unit_max": 566.67},
    {"item": 62, "descricao": "Reservatorio tanque polietileno 1000 litros", "qtde": 10, "valor_unit_max": 920.00},
    {"item": 63, "descricao": "Reservatorio tanque polietileno 10000 litros", "qtde": 10, "valor_unit_max": 8566.67},
    {"item": 64, "descricao": "Reservatorio tanque polietileno 15000 litros", "qtde": 10, "valor_unit_max": 10033.33},
    {"item": 65, "descricao": "Reservatorio tanque polietileno 2000 litros", "qtde": 10, "valor_unit_max": 2116.67},
    {"item": 66, "descricao": "Reservatorio tanque polietileno 20000 litros", "qtde": 10, "valor_unit_max": 16100.00},
    {"item": 67, "descricao": "Reservatorio tanque polietileno 310 litros", "qtde": 10, "valor_unit_max": 600.00},
    {"item": 68, "descricao": "Reservatorio tanque polietileno 5000 litros", "qtde": 10, "valor_unit_max": 3933.33},
    {"item": 69, "descricao": "Reservatorio tanque polietileno 500 litros", "qtde": 10, "valor_unit_max": 660.00},
]


def main():
    print("\n" + "=" * 80)
    print("INSERINDO ITENS DA TABELA NO BANCO DE DADOS")
    print("=" * 80)
    
    with engine.connect() as conn:
        # 1. Buscar usuário existente
        print("\n[1/4] Buscando usuario...")
        result = conn.execute(text("SELECT id FROM users LIMIT 1"))
        user_row = result.fetchone()
        
        if not user_row:
            print("   Criando usuario de teste...")
            user_id = str(uuid.uuid4())
            conn.execute(text("""
                INSERT INTO users (id, email, hashed_password, name, created_at)
                VALUES (:id, 'squad@test.com', '$2b$12$fakehash', 'Squad Test', NOW())
            """), {"id": user_id})
        else:
            user_id = str(user_row[0])
        
        print(f"   OK - User ID: {user_id}")
        
        # 2. Criar projeto
        print("\n[2/4] Criando projeto...")
        project_id = str(uuid.uuid4())
        conn.execute(text("""
            INSERT INTO projects (id, user_id, name, description, status, created_at)
            VALUES (:id, :user_id, 'Licitacao - Caixas e Reservatorios', 
                    '11 itens: Caixas dagua e reservatorios de polietileno', 'READY', NOW())
        """), {"id": project_id, "user_id": user_id})
        print(f"   OK - Project ID: {project_id}")
        
        # 3. Inserir produtos
        print("\n[3/4] Inserindo 11 produtos...")
        for item in TABLE_ITEMS:
            product_id = str(uuid.uuid4())
            valor_total = item["valor_unit_max"] * item["qtde"]
            
            conn.execute(text("""
                INSERT INTO products (id, project_id, name, description, numero_lote, 
                                     unidade_medida, valor_unitario_estimado, 
                                     valor_total_estimado, quantity, status, margin, created_at)
                VALUES (:id, :project_id, :name, :description, :lote, 'Un.', 
                        :valor_unit, :valor_total, :qtde, 'PENDING', 0.0, NOW())
            """), {
                "id": product_id,
                "project_id": project_id,
                "name": item["descricao"],
                "description": f"Item {item['item']} - {item['descricao']}",
                "lote": str(item["item"]),
                "valor_unit": item["valor_unit_max"],
                "valor_total": valor_total,
                "qtde": item["qtde"]
            })
        
        print(f"   OK - 11 produtos inseridos")
        
        # Commit
        conn.commit()
        
        # 4. Resumo
        print("\n[4/4] Resumo:")
        total = sum(i["valor_unit_max"] * i["qtde"] for i in TABLE_ITEMS)
        print(f"   Total orcado: R$ {total:,.2f}")
        
        print("\n" + "=" * 80)
        print("ITENS INSERIDOS COM SUCESSO!")
        print("=" * 80)
        print(f"\nProject ID: {project_id}")
        print(f"\nAcesse o dashboard:")
        print(f"   http://localhost:3000/dashboard/products?projectId={project_id}")
        print(f"\nExecute a busca:")
        print(f"   python test_squad_busca.py {project_id}")
        
        return project_id


if __name__ == "__main__":
    project_id = main()
