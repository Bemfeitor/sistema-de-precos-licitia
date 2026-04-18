"""
Script para limpar dados de teste do banco de dados.
Remove ofertas, produtos e projetos de teste.
"""

import os
import sys

os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'

from sqlalchemy import create_engine, text

# Conectar ao banco
database_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
engine = create_engine(database_url)


def cleanup_database():
    """Limpa dados de teste do banco."""
    print("\n" + "=" * 80)
    print("LIMPEZA DO BANCO DE DADOS - PRICE INTELLIGENCE SQUAD")
    print("=" * 80)
    
    with engine.connect() as conn:
        # 1. Contar registros atuais
        print("\n[1/5] Verificando registros atuais...")
        
        result = conn.execute(text("SELECT COUNT(*) FROM offers"))
        offers_count = result.fetchone()[0]
        print(f"   Ofertas encontradas: {offers_count}")
        
        result = conn.execute(text("SELECT COUNT(*) FROM products"))
        products_count = result.fetchone()[0]
        print(f"   Produtos encontrados: {products_count}")
        
        result = conn.execute(text("SELECT COUNT(*) FROM projects"))
        projects_count = result.fetchone()[0]
        print(f"   Projetos encontrados: {projects_count}")
        
        # 2. Deletar ofertas
        print("\n[2/5] Deletando ofertas...")
        conn.execute(text("DELETE FROM offers"))
        print(f"   OK - Todas as ofertas removidas")
        
        # 3. Deletar produtos (exceto os que têm ofertas - já foram deletados)
        print("\n[3/5] Deletando produtos...")
        result = conn.execute(text("DELETE FROM products"))
        deleted_products = result.rowcount
        print(f"   OK - {deleted_products} produtos removidos")
        
        # 4. Deletar projetos (deixar apenas o primeiro se existir)
        print("\n[4/5] Deletando projetos...")
        # Primeiro, manter um projeto base se existir
        result = conn.execute(text("""
            DELETE FROM projects 
            WHERE id NOT IN (
                SELECT id FROM projects 
                ORDER BY created_at ASC 
                LIMIT 1
            )
        """))
        deleted_projects = result.rowcount
        print(f"   OK - {deleted_projects} projetos removidos")
        print(f"   (Mantido o projeto mais antigo como base)")
        
        # 5. Resetar status dos produtos restantes
        print("\n[5/5] Resetando status...")
        conn.execute(text("UPDATE products SET status = 'PENDING'"))
        print(f"   OK - Status resetado para PENDING")
        
        # Commit
        conn.commit()
        
        # Verificar estado final
        print("\n" + "=" * 80)
        print("ESTADO FINAL DO BANCO:")
        print("=" * 80)
        
        result = conn.execute(text("SELECT COUNT(*) FROM offers"))
        print(f"   Ofertas: {result.fetchone()[0]}")
        
        result = conn.execute(text("SELECT COUNT(*) FROM products"))
        print(f"   Produtos: {result.fetchone()[0]}")
        
        result = conn.execute(text("SELECT COUNT(*) FROM projects"))
        print(f"   Projetos: {result.fetchone()[0]}")
        
        print("\n" + "=" * 80)
        print("BANCO LIMPO E PRONTO PARA NOVO TESTE!")
        print("=" * 80)
        print("\nProximos passos:")
        print("   1. Execute: python insert_table_items_v3.py")
        print("   2. Acesse:  http://localhost:3000")
        print("   3. Faca login e teste a nova busca")
        print("")


if __name__ == "__main__":
    confirmacao = input("Tem certeza que deseja limpar todos os dados de teste? (s/n): ")
    if confirmacao.lower() == 's':
        cleanup_database()
    else:
        print("\nOperacao cancelada.")
