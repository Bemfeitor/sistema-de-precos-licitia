"""
Script de teste - Price Intelligence Squad
Executa busca REAL no Mercado Livre para os 11 itens da tabela.

Uso: python test_squad_busca.py [project_id]
"""

import os
import sys
import asyncio
from decimal import Decimal

# Configurar environment
os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'
os.environ['SECRET_KEY'] = '9a2b8c7d6e5f4g3h2i1j0k9l8m7n6o5p'

# Adicionar o diretório do app ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.marketplace_service_v2 import (
    search_item_optimized,
    search_all_items_from_table,
    generate_report,
    build_optimized_query
)

# Dados da tabela (mesmo do insert_table_items.py)
TABLE_ITEMS = [
    {"item": 59, "descricao": "Caixa d'água polietileno reforçada com tampa 500 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 343.33, "valor_total_max": 3433.30},
    {"item": 60, "descricao": "Caixa d'água polietileno reforçada com tampa 10.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 7500.00, "valor_total_max": 75000.00},
    {"item": 61, "descricao": "Caixa d'água polietileno reforçada com tampa 1.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 566.67, "valor_total_max": 5666.70},
    {"item": 62, "descricao": "Reservatório tanque polietileno 1.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 920.00, "valor_total_max": 9200.00},
    {"item": 63, "descricao": "Reservatório tanque polietileno 10.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 8566.67, "valor_total_max": 85666.70},
    {"item": 64, "descricao": "Reservatório tanque polietileno 15.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 10033.33, "valor_total_max": 100333.30},
    {"item": 65, "descricao": "Reservatório tanque polietileno 2.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 2116.67, "valor_total_max": 21166.70},
    {"item": 66, "descricao": "Reservatório tanque polietileno 20.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 16100.00, "valor_total_max": 161000.00},
    {"item": 67, "descricao": "Reservatório tanque polietileno 310 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 600.00, "valor_total_max": 6000.00},
    {"item": 68, "descricao": "Reservatório tanque polietileno 5.000 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 3933.33, "valor_total_max": 39333.30},
    {"item": 69, "descricao": "Reservatório tanque polietileno 500 litros", "qtde": 10, "unid": "Un.", "valor_unit_max": 660.00, "valor_total_max": 6600.00},
]


def test_query_builder():
    """Testa a construção de queries otimizadas."""
    print("\n" + "=" * 80)
    print("TESTE 1: QUERY BUILDER (Squad AIOX Strategy)")
    print("=" * 80)
    
    for item in TABLE_ITEMS[:3]:  # Testar apenas 3 primeiros
        query = build_optimized_query(item["descricao"])
        print(f"\nItem {item['item']}: {item['descricao'][:50]}...")
        print(f"   Query: {query}")


async def test_single_item():
    """Testa busca de um único item."""
    print("\n" + "=" * 80)
    print("TESTE 2: BUSCA DE ITEM ÚNICO (Item 59)")
    print("=" * 80)
    
    item = TABLE_ITEMS[0]  # Item 59
    print(f"\nBuscando: {item['descricao']}")
    print(f"Quantidade: {item['qtde']} unidades")
    print(f"Valor máximo: R$ {item['valor_unit_max']}")
    print("\n⏳ Executando busca... (pode levar alguns segundos)")
    
    try:
        resultado = await search_item_optimized(
            item_number=item["item"],
            descricao=item["descricao"],
            quantidade=item["qtde"],
            valor_unit_max=item["valor_unit_max"]
        )
        
        res = resultado["resultado"]
        
        print("\n✅ RESULTADO:")
        print(f"   Encontrado: {res['encontrado']}")
        print(f"   Query usada: {resultado['query_usada']}")
        print(f"   Menor preço: R$ {res['menor_preco_unitario']:.2f}")
        print(f"   Preço médio: R$ {res['preco_medio_unitario']:.2f}")
        print(f"   Total 10un: R$ {res['preco_total_10un']:.2f}")
        print(f"   Economia: R$ {res['economia_total']:.2f} ({res['economia_percentual']:.1f}%)")
        print(f"   Estoque: {res['quantidade_disponivel']} un ({'OK' if res['estoque_suficiente'] else 'INSUFICIENTE'})")
        print(f"   Vendedor: {res['vendedor']}")
        print(f"   Link: {res['url'][:70]}...")
        
        return resultado
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_all_items():
    """Testa busca de todos os 11 itens."""
    print("\n" + "=" * 80)
    print("TESTE 3: BUSCA COMPLETA (11 ITENS)")
    print("=" * 80)
    print("\n⏳ Buscando todos os itens (pode levar 1-2 minutos)...")
    print("   Concorrência: 3 buscas simultâneas")
    print("   Limite: 50 requisições")
    
    try:
        resultados = await search_all_items_from_table(
            items=TABLE_ITEMS,
            max_concurrent=3
        )
        
        # Gerar relatório
        relatorio = generate_report(resultados)
        print(relatorio)
        
        return resultados
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return []


async def save_results_to_db(results, project_id=None):
    """Salva resultados no banco de dados."""
    print("\n" + "=" * 80)
    print("SALVANDO RESULTADOS NO BANCO")
    print("=" * 80)
    
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models.product import Product
    from app.models.offer import Offer
    from app.models.project import Project
    import uuid
    
    db = SessionLocal()
    try:
        # Se não tem project_id, criar um novo projeto
        if not project_id:
            user = db.query(Product).first()
            if user:
                from app.models.user import User
                user = db.query(User).first()
            
            if not user:
                print("   ⚠️ Nenhum usuário encontrado. Criando dados de teste...")
                # Criar usuário e projeto temporários
                from app.models.user import User
                from passlib.context import CryptContext
                
                pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
                user = User(
                    id=uuid.uuid4(),
                    email="squad@test.com",
                    hashed_password=pwd_context.hash("test"),
                    name="Squad Test"
                )
                db.add(user)
                db.commit()
            
            project = Project(
                id=uuid.uuid4(),
                user_id=user.id,
                name="Squad Test - Caixas e Reservatórios",
                description="Teste da Price Intelligence Squad",
                status="READY"
            )
            db.add(project)
            db.commit()
            project_id = project.id
            print(f"   ✅ Projeto criado: {project_id}")
        
        # Buscar produtos do projeto
        products = db.query(Product).filter(Product.project_id == project_id).all()
        if not products:
            print(f"   ⚠️ Nenhum produto encontrado para o projeto {project_id}")
            print("   Execute primeiro: python insert_table_items.py")
            return
        
        # Criar mapeamento item_number -> product_id
        product_map = {int(p.numero_lote): p for p in products if p.numero_lote}
        
        offers_created = 0
        for result in results:
            res = result["resultado"]
            if not res["encontrado"]:
                continue
            
            product = product_map.get(result["item_number"])
            if not product:
                print(f"   ⚠️ Produto não encontrado para item {result['item_number']}")
                continue
            
            # Criar oferta
            offer = Offer(
                id=uuid.uuid4(),
                product_id=product.id,
                marketplace="Mercado Livre",
                title=f"Item {result['item_number']} - Melhor Preço",
                price=res["menor_preco_unitario"],
                shipping=0.0,
                delivery_days=3,
                seller_rating=5.0,
                url=res["url"]
            )
            db.add(offer)
            
            # Atualizar produto
            product.status = "SUCCESS"
            
            offers_created += 1
        
        db.commit()
        print(f"   ✅ {offers_created} ofertas salvas no banco")
        
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        db.rollback()
    finally:
        db.close()


def print_summary(results):
    """Imprime resumo final."""
    print("\n" + "=" * 80)
    print("RESUMO DA EXECUÇÃO - PRICE INTELLIGENCE SQUAD")
    print("=" * 80)
    
    encontrados = [r for r in results if r["resultado"]["encontrado"]]
    nao_encontrados = [r for r in results if not r["resultado"]["encontrado"]]
    
    print(f"\n✅ Itens encontrados: {len(encontrados)}/11")
    if nao_encontrados:
        print(f"❌ Itens não encontrados: {len(nao_encontrados)}")
        for r in nao_encontrados:
            print(f"   - Item {r['item_number']}: {r['descricao'][:40]}...")
    
    if encontrados:
        total_orcado = sum(r["valor_unit_max"] * r["quantidade"] for r in encontrados)
        total_coletado = sum(r["resultado"]["preco_total_10un"] for r in encontrados)
        economia = total_orcado - total_coletado
        percentual = (economia / total_orcado * 100) if total_orcado > 0 else 0
        
        print(f"\n💰 Total orçado: R$ {total_orcado:,.2f}")
        print(f"💰 Total coletado: R$ {total_coletado:,.2f}")
        print(f"💚 Economia: R$ {economia:,.2f} ({percentual:.2f}%)")
    
    print("\n" + "=" * 80)


async def main():
    """Função principal."""
    project_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    print("\n" + "=" * 80)
    print("🤖 PRICE INTELLIGENCE SQUAD - TESTE DE BUSCA REAL")
    print("=" * 80)
    print("\nEstratégia Squad AIOX:")
    print("  ✓ Menor preço + Preço médio")
    print("  ✓ Validação de links")
    print("  ✓ Fallback de quantidade (10→1×10)")
    print("  ✓ Limite 50 requisições")
    print("  ✓ Queries otimizadas")
    
    # Teste 1: Query Builder
    test_query_builder()
    
    # Perguntar se quer continuar
    print("\n" + "-" * 80)
    resposta = input("\nDeseja executar a BUSCA REAL no Mercado Livre? (s/n): ")
    
    if resposta.lower() != 's':
        print("\n❌ Teste cancelado pelo usuário.")
        return
    
    # Teste 2: Busca de item único
    resultado_unico = await test_single_item()
    
    if not resultado_unico:
        print("\n❌ Falha no teste de item único. Abortando.")
        return
    
    # Perguntar se quer buscar todos
    print("\n" + "-" * 80)
    resposta = input("\nDeseja buscar TODOS os 11 itens? (s/n): ")
    
    if resposta.lower() != 's':
        print("\n✅ Teste parcial concluído.")
        return
    
    # Teste 3: Busca completa
    resultados = await test_all_items()
    
    if resultados:
        print_summary(resultados)
        
        # Perguntar se quer salvar no banco
        print("\n" + "-" * 80)
        resposta = input("\nDeseja salvar os resultados no banco de dados? (s/n): ")
        
        if resposta.lower() == 's':
            await save_results_to_db(resultados, project_id)
            
            if project_id:
                print(f"\n🔗 Acesse o dashboard:")
                print(f"   http://localhost:3000/dashboard/products?projectId={project_id}")
    
    print("\n" + "=" * 80)
    print("✅ TESTE CONCLUÍDO")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
