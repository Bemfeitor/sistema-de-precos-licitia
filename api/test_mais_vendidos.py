"""
Script de teste - Price Intelligence Squad v3
Busca REAL no Mercado Livre priorizando MAIS VENDIDOS

Uso: python test_mais_vendidos.py [project_id]
"""

import os
import sys
import asyncio

# Configurar environment
os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'
os.environ['SECRET_KEY'] = '9a2b8c7d6e5f4g3h2i1j0k9l8m7n6o5p'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.marketplace_service_v3 import (
    search_item_with_best_sellers,
    search_all_items_best_sellers,
    generate_report_v3,
    build_optimized_query_v3,
    search_best_sellers_api
)

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


def test_query_builder():
    """Testa a construção de queries otimizadas."""
    print("\n" + "=" * 80)
    print("TESTE 1: QUERY BUILDER v3 (Mais Vendidos)")
    print("=" * 80)
    
    for item in TABLE_ITEMS[:3]:
        query = build_optimized_query_v3(item["descricao"])
        print(f"\nItem {item['item']}: {item['descricao'][:50]}...")
        print(f"   Query: {query}")


async def test_best_sellers_api():
    """Testa busca de best sellers via API oficial."""
    print("\n" + "=" * 80)
    print("TESTE 2: BUSCA BEST SELLERS VIA API OFICIAL")
    print("=" * 80)
    
    query = "caixa dagua 500 litros"
    print(f"\nBuscando: {query}")
    print("Endpoint: https://api.mercadolibre.com/sites/MLB/search")
    print("Params: sort=relevance, power_seller=yes")
    
    try:
        resultados = await search_best_sellers_api(query, limit=5)
        
        if resultados:
            print(f"\n✅ ENCONTRADOS {len(resultados)} produtos!")
            for i, r in enumerate(resultados[:3], 1):
                mais_vendido = "⭐" if r.get('is_best_seller') else ""
                print(f"\n   {i}. {r['title'][:60]}... {mais_vendido}")
                print(f"      Preço: R$ {r['price']}")
                print(f"      Vendedor: {r.get('seller_name', 'N/A')}")
        else:
            print("\n⚠️ Nenhum produto encontrado")
            
    except Exception as e:
        print(f"\n❌ Erro: {e}")


async def test_single_item():
    """Testa busca de um único item com estratégia best sellers."""
    print("\n" + "=" * 80)
    print("TESTE 3: BUSCA DE ITEM UNICO (Item 59 - API ML Best Sellers)")
    print("=" * 80)
    
    item = TABLE_ITEMS[0]  # Item 59
    print(f"\nBuscando: {item['descricao']}")
    print(f"Quantidade: {item['qtde']} unidades")
    print(f"Valor máximo: R$ {item['valor_unit_max']}")
    print("\n⏳ Executando busca via API ML (best sellers)...")
    
    try:
        resultado = await search_item_with_best_sellers(
            item_number=item["item"],
            descricao=item["descricao"],
            quantidade=item["qtde"],
            valor_unit_max=item["valor_unit_max"]
        )
        
        res = resultado["resultado"]
        
        print("\n" + "-" * 80)
        print("RESULTADO:")
        print("-" * 80)
        print(f"   Encontrado: {'SIM ✅' if res['encontrado'] else 'NÃO ❌'}")
        print(f"   Query usada: {resultado['query_usada']}")
        print(f"   Mais Vendido: {'⭐ SIM' if res['is_mais_vendido'] else 'NÃO'}")
        print(f"   Menor preço: R$ {res['menor_preco_unitario']}")
        print(f"   Total 10un: R$ {res['preco_total_10un']}")
        print(f"   Economia: R$ {res['economia_total']:.2f} ({res['economia_percentual']:.1f}%)")
        print(f"   Estoque: {res['quantidade_disponivel']} un ({'OK' if res['estoque_suficiente'] else 'INSUFICIENTE'})")
        print(f"   Vendedor: {res['vendedor']}")
        print(f"   Link: {res['url'][:70]}...")
        print("-" * 80)
        
        return resultado
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_all_items():
    """Testa busca de todos os 11 itens."""
    print("\n" + "=" * 80)
    print("TESTE 4: BUSCA COMPLETA DOS 11 ITENS (API ML Best Sellers)")
    print("=" * 80)
    print("\n⏳ Buscando todos os itens...")
    print("   Estratégia:")
    print("   1. Busca via API: /sites/MLB/search")
    print("   2. Filtros: sort=relevance, power_seller=yes")
    print("   3. Se necessário, complementa com API geral")
    print(f"   Concorrência: 3 buscas simultâneas")
    print("")
    
    try:
        resultados = await search_all_items_best_sellers(
            items=TABLE_ITEMS,
            max_concurrent=3
        )
        
        # Gerar relatório
        relatorio = generate_report_v3(resultados)
        print(relatorio)
        
        # Estatísticas
        encontrados = [r for r in resultados if r["resultado"]["encontrado"]]
        mais_vendidos = [r for r in resultados if r["resultado"].get("is_mais_vendido")]
        
        print("\n" + "=" * 80)
        print("ESTATÍSTICAS FINAIS")
        print("=" * 80)
        print(f"Total de itens: {len(resultados)}")
        print(f"Itens encontrados: {len(encontrados)}/{len(resultados)}")
        print(f"Itens em 'Mais Vendidos': {len(mais_vendidos)}/{len(resultados)}")
        
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
    
    from sqlalchemy import create_engine, text
    
    database_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+pg8000://')
    engine = create_engine(database_url)
    
    try:
        with engine.connect() as conn:
            # Se não tem project_id, criar um novo
            if not project_id:
                project_id = str(__import__('uuid').uuid4())
                user_result = conn.execute(text("SELECT id FROM users LIMIT 1"))
                user_row = user_result.fetchone()
                
                if user_row:
                    user_id = str(user_row[0])
                    conn.execute(text("""
                        INSERT INTO projects (id, user_id, name, pdf_filename, status, created_at)
                        VALUES (:id, :user_id, 'Teste Mais Vendidos', 'test.pdf', 'READY', NOW())
                    """), {"id": project_id, "user_id": user_id})
                    conn.commit()
                    print(f"   ✅ Projeto criado: {project_id}")
            
            # Inserir produtos e ofertas
            offers_created = 0
            
            for result in results:
                res = result["resultado"]
                if not res["encontrado"]:
                    continue
                
                # Criar produto
                product_id = str(__import__('uuid').uuid4())
                conn.execute(text("""
                    INSERT INTO products (id, project_id, name, description, numero_lote, 
                                         unidade_medida, valor_unitario_estimado, 
                                         valor_total_estimado, quantity, status, margin, created_at)
                    VALUES (:id, :project_id, :name, :description, :lote, 'Un.', 
                            :valor_unit, :valor_total, :qtde, 'SUCCESS', 0.0, NOW())
                """), {
                    "id": product_id,
                    "project_id": project_id,
                    "name": result["descricao"],
                    "description": f"Item {result['item_number']} - {'⭐ Mais Vendido' if res.get('is_mais_vendido') else 'Busca Geral'}",
                    "lote": str(result["item_number"]),
                    "valor_unit": result["valor_unit_max"],
                    "valor_total": result["valor_unit_max"] * result["quantidade"],
                    "qtde": result["quantidade"]
                })
                
                # Criar oferta
                offer_id = str(__import__('uuid').uuid4())
                marketplace = "ML - Mais Vendidos" if res.get("is_mais_vendido") else "Mercado Livre"
                
                conn.execute(text("""
                    INSERT INTO offers (id, product_id, marketplace, title, price, shipping, 
                                       delivery_days, seller_rating, url, created_at)
                    VALUES (:id, :product_id, :marketplace, :title, :price, 0.0, 3, 5.0, :url, NOW())
                """), {
                    "id": offer_id,
                    "product_id": product_id,
                    "marketplace": marketplace,
                    "title": f"Item {result['item_number']} - Menor Preço",
                    "price": res["menor_preco_unitario"],
                    "url": res["url"]
                })
                
                offers_created += 1
            
            conn.commit()
            print(f"   ✅ {offers_created} ofertas salvas no banco")
            
            if project_id:
                print(f"\n   🔗 Acesse o dashboard:")
                print(f"      http://localhost:3000/dashboard/products?projectId={project_id}")
                
    except Exception as e:
        print(f"   ❌ Erro: {e}")


async def main():
    """Função principal."""
    project_id = sys.argv[1] if len(sys.argv) > 1 else None
    
    print("\n" + "=" * 80)
    print("🤖 PRICE INTELLIGENCE SQUAD - TESTE API ML BEST SELLERS")
    print("=" * 80)
    print("\nEstratégia:")
    print("  ⭐ Busca PRIORITÁRIA via API: /sites/MLB/search")
    print("  🔧 Filtros: sort=relevance + power_seller=yes")
    print("  🔍 Fallback: API geral se necessário")
    print("  📊 Combina resultados")
    print("  💰 Calcula: Menor preço + Preço médio")
    print("  ✅ Identifica best sellers")
    
    # Teste 1: Query Builder
    test_query_builder()
    
    # Perguntar se quer continuar
    print("\n" + "-" * 80)
    resposta = input("\nDeseja testar busca BEST SELLERS via API? (s/n): ")
    
    if resposta.lower() == 's':
        await test_best_sellers_api()
    
    # Perguntar sobre busca de item único
    print("\n" + "-" * 80)
    resposta = input("\nDeseja executar BUSCA REAL de um item (Item 59)? (s/n): ")
    
    if resposta.lower() != 's':
        print("\n✅ Teste cancelado pelo usuário.")
        return
    
    # Teste 3: Busca de item único
    resultado_unico = await test_single_item()
    
    if not resultado_unico:
        print("\n❌ Falha no teste de item único.")
        return
    
    # Perguntar sobre buscar todos
    print("\n" + "-" * 80)
    resposta = input("\nDeseja buscar TODOS os 11 itens? (s/n): ")
    
    if resposta.lower() != 's':
        print("\n✅ Teste parcial concluído.")
        return
    
    # Teste 4: Busca completa
    resultados = await test_all_items()
    
    if resultados:
        # Perguntar se quer salvar
        print("\n" + "-" * 80)
        resposta = input("\nDeseja salvar os resultados no banco de dados? (s/n): ")
        
        if resposta.lower() == 's':
            await save_results_to_db(resultados, project_id)
    
    print("\n" + "=" * 80)
    print("✅ TESTE CONCLUÍDO")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
