"""
Script de teste V4 - Validação EXATA de preço no link + Fila de 50 em 50
"""

import os
import sys
import asyncio

os.environ['DATABASE_URL'] = 'postgresql://postgres:i5xPnLQon5bJStnU@db.kepshoeqyivtgsrolttt.supabase.co:5432/postgres'
os.environ['SECRET_KEY'] = '9a2b8c7d6e5f4g3h2i1j0k9l8m7n6o5p'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.marketplace_service_v4 import (
    search_item_with_best_sellers,
    search_all_items_best_sellers,
    generate_report_v4,
    validate_price_in_link,
    request_queue
)

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


async def test_price_validation():
    """Testa validação de preço no link."""
    print("\n" + "=" * 80)
    print("TESTE: VALIDAÇÃO DE PREÇO EXATO NO LINK")
    print("=" * 80)
    
    # Testar com um link de exemplo do ML
    url = "https://produto.mercadolivre.com.br/MLB-1234567890"
    expected_price = 299.99
    
    print(f"\nValidando preço no link...")
    print(f"URL: {url}")
    print(f"Preço esperado (API): R$ {expected_price}")
    
    result = await validate_price_in_link(url, expected_price)
    
    print(f"\nResultado:")
    print(f"  Válido: {result['valid']}")
    print(f"  Preço validado: R$ {result.get('price_validated', 0)}")
    print(f"  Match: {result.get('price_match', False)}")
    if 'error' in result:
        print(f"  Erro: {result['error']}")


async def test_single_item():
    """Testa busca de um item com validação exata."""
    print("\n" + "=" * 80)
    print("TESTE: BUSCA DE ITEM COM VALIDAÇÃO EXATA")
    print("=" * 80)
    
    item = TABLE_ITEMS[0]
    print(f"\nItem {item['item']}: {item['descricao']}")
    print(f"Quantidade: {item['qtde']}")
    print(f"Valor max: R$ {item['valor_unit_max']}")
    print("\n⏳ Buscando e validando preço no link...")
    
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
    print(f"  Encontrado: {res['encontrado']}")
    print(f"  Query: {resultado['query_usada']}")
    print(f"  Menor Preço ML: R$ {res['menor_preco_unitario']}")
    validado = "✓ VALIDADO" if res['preco_validado_no_link'] else "? NÃO VALIDADO"
    print(f"  Validação no link: {validado}")
    print(f"  Total 10un: R$ {res['preco_total_10un']}")
    print(f"  Economia: R$ {res['economia_total']}")
    print(f"  Estoque: {res['quantidade_disponivel']} un")
    print(f"  Link: {res['url'][:70]}...")
    print("-" * 80)
    
    return resultado


async def test_all_items():
    """Testa busca de todos os itens com fila de 50."""
    print("\n" + "=" * 80)
    print("TESTE: BUSCA COMPLETA COM FILA (Lotes de 50)")
    print("=" * 80)
    print(f"\nTotal de itens: {len(TABLE_ITEMS)}")
    print(f"Sistema de fila: Lotes de {request_queue.max_per_batch} requisições")
    print(f"Delay entre reqs: {request_queue.delay_between_requests}s")
    print(f"Delay entre lotes: 5s")
    print("\n⏳ Iniciando busca...")
    
    resultados = await search_all_items_best_sellers(
        items=TABLE_ITEMS,
        max_concurrent=3
    )
    
    relatorio = generate_report_v4(resultados)
    print(relatorio)
    
    return resultados


async def main():
    """Função principal."""
    print("\n" + "=" * 80)
    print("🤖 PRICE INTELLIGENCE SQUAD V4")
    print("=" * 80)
    print("\nFuncionalidades:")
    print("  ✓ Validação EXATA do preço no link do produto")
    print("  ✓ Fila de requisições em LOTES de 50")
    print("  ✓ Delay entre requisições para respeitar rate limits")
    print("  ✓ Sistema de espera entre lotes")
    
    # Perguntar teste
    print("\n" + "-" * 80)
    resposta = input("\nDeseja testar validação de preço em link? (s/n): ")
    if resposta.lower() == 's':
        await test_price_validation()
    
    print("\n" + "-" * 80)
    resposta = input("\nDeseja buscar UM item com validação? (s/n): ")
    if resposta.lower() == 's':
        await test_single_item()
    
    print("\n" + "-" * 80)
    resposta = input("\nDeseja buscar TODOS os 11 itens? (s/n): ")
    if resposta.lower() == 's':
        await test_all_items()
    
    print("\n" + "=" * 80)
    print("✅ TESTE CONCLUÍDO")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
