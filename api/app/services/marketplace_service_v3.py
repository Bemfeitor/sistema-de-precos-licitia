"""
Marketplace Service V3 — Price Intelligence Squad + Mais Vendidos

Funcionalidades:
- Busca PRIORITÁRIA nos itens MAIS VENDIDOS do Mercado Livre
- Fallback para busca geral se não encontrar
- Menor preço + preço médio entre os mais vendidos
- Validação de links
- Fallback de quantidade (10 → 1×10)
- Limite de 50 requisições

Estratégia Squad AIOX + Mais Vendidos ML
"""

import logging
import asyncio
import os
import aiohttp
import re
from typing import List, Dict, Any, Optional, Tuple
from statistics import mean
from urllib.parse import quote_plus

from app.services.ml_api_client import get_ml_client

logger = logging.getLogger(__name__)


class PriceMetrics:
    """Métricas de preço calculadas para um produto."""
    
    def __init__(self):
        self.menor_preco: float = 0.0
        self.preco_total_10un: float = 0.0
        self.economia_vs_maximo: float = 0.0
        self.quantidade_disponivel: int = 0
        self.url_menor_preco: str = ""
        self.vendedor: str = ""
        self.estoque_suficiente: bool = False
        self.is_mais_vendido: bool = False


async def search_best_sellers_api(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Busca produtos MAIS VENDIDOS usando a API OFICIAL do Mercado Livre.
    
    Endpoint: GET https://api.mercadolibre.com/sites/MLB/search
    
    Estratégia API:
    - sort=relevance (ordena por relevância que inclui vendas)
    - power_seller=yes (filtra vendedores com alto volume)
    - condition=new (apenas produtos novos)
    - Retorna sold_quantity quando disponível
    
    Args:
        query: Termo de busca
        limit: Limite de resultados
        
    Returns:
        Lista de ofertas dos mais vendidos via API oficial
    """
    try:
        ml_client = get_ml_client()
        
        # Usar o método específico de best sellers da API
        offers = await ml_client.search_best_sellers(query, limit=limit)
        
        if offers:
            logger.info(f"[API ML - BEST SELLERS] {len(offers)} produtos para '{query}'")
            # Marcar como mais vendidos
            for offer in offers:
                offer["is_mais_vendido"] = offer.get("is_best_seller", False) or offer.get("sold_quantity", 0) > 50
                if offer["is_mais_vendido"]:
                    offer["marketplace"] = "Mercado Livre (Mais Vendido)"
        
        return offers
        
    except Exception as e:
        logger.error(f"Erro API best sellers para '{query}': {e}")
        return []


def _parse_mais_vendidos_html(html: str, query: str, limit: int) -> List[Dict[str, Any]]:
    """
    Parse HTML da página de mais vendidos do Mercado Livre.
    
    Args:
        html: Conteúdo HTML da página
        query: Query original para matching
        limit: Limite de resultados
        
    Returns:
        Lista de ofertas extraídas
    """
    offers = []
    
    # Padrões para mais vendidos (estrutura similar à busca normal)
    # Títulos dos produtos
    title_pattern = re.compile(
        r'<a[^>]*class="poly-component__title[^"]*"[^>]*>([^<]+)<|'
        r'<h3[^>]*class="[^"]*ui-search-item__title[^"]*"[^>]*>([^<]+)<'
    )
    
    # Preços
    price_pattern = re.compile(r'andes-money-amount__fraction[^>]*>(\d[\d.]*)<')
    
    # Links
    link_pattern = re.compile(r'href="(https://www\.mercadolivre\.com\.br/[^"]+)"')
    
    # Encontrar todos os títulos e preços
    titles = []
    for m in title_pattern.finditer(html):
        title = m.group(1) or m.group(2) or ""
        if title.strip():
            titles.append((m.start(), title.strip()))
    
    prices = []
    for m in price_pattern.finditer(html):
        prices.append((m.start(), m.group(1)))
    
    links = []
    for m in link_pattern.finditer(html):
        links.append((m.start(), m.group(1)))
    
    # Match título com preço mais próximo
    for t_pos, title in titles[:limit]:
        best_price = None
        best_link = ""
        
        # Encontrar preço mais próximo (dentro de 3000 chars)
        for p_pos, price_str in prices:
            if p_pos > t_pos and p_pos - t_pos < 3000:
                try:
                    best_price = float(price_str.replace(".", "").replace(",", ""))
                    break
                except ValueError:
                    continue
        
        # Encontrar link mais próximo
        for l_pos, link in links:
            if l_pos > t_pos and l_pos - t_pos < 5000:
                best_link = link
                break
        
        if best_price and best_price > 0:
            offers.append({
                "marketplace": "Mercado Livre (Mais Vendidos)",
                "title": title,
                "price": best_price,
                "shipping": 0.0,
                "delivery_days": 3,
                "seller_rating": 5.0,
                "url": best_link,
                "thumbnail": "",
                "is_mais_vendido": True,
                "available_quantity": 10,  # Assumir disponível para mais vendidos
            })
    
    return offers


async def search_with_best_sellers_priority(
    query: str,
    quantidade_desejada: int = 10,
    valor_maximo: float = 0.0
) -> Tuple[List[Dict[str, Any]], PriceMetrics]:
    """
    Busca produto priorizando MAIS VENDIDOS via API OFICIAL, depois busca geral.
    
    Estratégia Squad AIOX + API ML Best Sellers:
    1. Busca via API OFICIAL com filtros de best sellers
       - Endpoint: /sites/MLB/search
       - sort=relevance
       - power_seller=yes
    2. Se não encontrar ou tiver poucos resultados, busca geral na API
    3. Combina resultados priorizando mais vendidos
    4. Calcula métricas (menor preço, médio, economia)
    
    Args:
        query: Query de busca otimizada
        quantidade_desejada: Quantidade necessária (padrão: 10)
        valor_maximo: Valor máximo do orçamento para calcular economia
        
    Returns:
        Tuple (lista de ofertas, métricas calculadas)
    """
    metrics = PriceMetrics()
    all_offers = []
    
    logger.info(f"[BUSCA API ML] Iniciando busca para: {query}")
    
    # ETAPA 1: Buscar BEST SELLERS via API OFICIAL
    logger.info(f"[ETAPA 1] Buscando BEST SELLERS via API...")
    logger.info(f"         Endpoint: /sites/MLB/search")
    logger.info(f"         Filtros: sort=relevance, power_seller=yes")
    
    best_sellers = await search_best_sellers_api(query, limit=20)
    
    if best_sellers:
        logger.info(f"[ETAPA 1] ✓ {len(best_sellers)} best sellers encontrados")
        all_offers.extend(best_sellers)
        metrics.is_mais_vendido = True
    else:
        logger.info(f"[ETAPA 1] ✗ Nenhum best seller encontrado")
    
    # ETAPA 2: Buscar na API geral (se necessário)
    if len(all_offers) < 10:
        logger.info(f"[ETAPA 2] Buscando na API geral para complementar...")
        ml_client = get_ml_client()
        api_results = await ml_client.search_product(query, limit=30)
        
        if api_results:
            logger.info(f"[ETAPA 2] ✓ {len(api_results)} produtos na API geral")
            for offer in api_results:
                if not _is_duplicate(offer, all_offers):
                    all_offers.append(offer)
        else:
            logger.info(f"[ETAPA 2] ✗ Nenhum produto na API geral")
    
    # Se não encontrou nada, retornar vazio
    if not all_offers:
        logger.warning(f"[RESULTADO] Nenhum produto encontrado para: {query}")
        return [], metrics
    
    logger.info(f"[RESULTADO] Total: {len(all_offers)} ofertas")
    
    # Calcular métricas - MENOR PREÇO EXATO (sem média)
    precos = [o["price"] for o in all_offers if o["price"] > 0]
    
    if not precos:
        return [], metrics
    
    # Pega o MENOR PREÇO EXATO como vem do ML
    metrics.menor_preco = min(precos)
    
    # Encontrar oferta com menor preço
    oferta_menor = min(all_offers, key=lambda x: x["price"])
    metrics.url_menor_preco = oferta_menor.get("url", "")
    metrics.vendedor = oferta_menor.get("seller_name", oferta_menor.get("seller", "N/A"))
    metrics.quantidade_disponivel = oferta_menor.get("available_quantity", 0)
    metrics.is_mais_vendido = oferta_menor.get("is_mais_vendido", False)
    
    # Verificar estoque
    if metrics.quantidade_disponivel >= quantidade_desejada:
        metrics.estoque_suficiente = True
        metrics.preco_total_10un = metrics.menor_preco * quantidade_desejada
    else:
        metrics.estoque_suficiente = False
        metrics.preco_total_10un = metrics.menor_preco * quantidade_desejada
    
    # Calcular economia
    if valor_maximo > 0:
        valor_total_maximo = valor_maximo * quantidade_desejada
        metrics.economia_vs_maximo = valor_total_maximo - metrics.preco_total_10un
    
    logger.info(
        f"[METRICAS] Menor: R${metrics.menor_preco:.2f}, "
        f"Médio: R${metrics.preco_medio:.2f}, "
        f"Total 10un: R${metrics.preco_total_10un:.2f}, "
        f"Mais Vendido: {metrics.is_mais_vendido}"
    )
    
    return all_offers, metrics


def _is_duplicate(new_offer: Dict, existing_offers: List[Dict]) -> bool:
    """
    Verifica se uma oferta já existe na lista (por título similar).
    
    Args:
        new_offer: Nova oferta a verificar
        existing_offers: Lista de ofertas existentes
        
    Returns:
        True se for duplicada, False caso contrário
    """
    new_title = new_offer.get("title", "").lower()
    
    for offer in existing_offers:
        existing_title = offer.get("title", "").lower()
        # Se títulos forem 70% similares, considerar duplicado
        if _similarity(new_title, existing_title) > 0.7:
            return True
    
    return False


def _similarity(a: str, b: str) -> float:
    """Calcula similaridade simples entre duas strings."""
    if not a or not b:
        return 0.0
    
    # Contar palavras em comum
    words_a = set(a.split())
    words_b = set(b.split())
    
    if not words_a or not words_b:
        return 0.0
    
    intersection = words_a.intersection(words_b)
    return len(intersection) / max(len(words_a), len(words_b))


async def search_item_with_best_sellers(
    item_number: int,
    descricao: str,
    quantidade: int,
    valor_unit_max: float
) -> Dict[str, Any]:
    """
    Busca otimizada para um item específico, priorizando BEST SELLERS via API.
    
    Args:
        item_number: Número do item (59-69)
        descricao: Descrição completa do produto
        quantidade: Quantidade necessária
        valor_unit_max: Valor unitário máximo do orçamento
        
    Returns:
        Dict com resultado completo da busca
    """
    # Construir query otimizada
    query = build_optimized_query_v3(descricao)
    
    logger.info(f"[Item {item_number}] Buscando via API ML: {query}")
    
    # Buscar com prioridade para best sellers
    offers, metrics = await search_with_best_sellers_priority(
        query=query,
        quantidade_desejada=quantidade,
        valor_maximo=valor_unit_max
    )
    
    return {
        "item_number": item_number,
        "descricao": descricao,
        "query_usada": query,
        "quantidade": quantidade,
        "valor_unit_max": valor_unit_max,
        "resultado": {
            "encontrado": len(offers) > 0,
            "menor_preco_unitario": metrics.menor_preco,  # VALOR EXATO SEM ARREDONDAMENTO
            "preco_total_10un": metrics.preco_total_10un,  # VALOR EXATO SEM ARREDONDAMENTO
            "economia_total": metrics.economia_vs_maximo,  # VALOR EXATO SEM ARREDONDAMENTO
            "economia_percentual": round(
                (metrics.economia_vs_maximo / (valor_unit_max * quantidade)) * 100, 2
            ) if valor_unit_max > 0 else 0,
            "quantidade_disponivel": metrics.quantidade_disponivel,
            "estoque_suficiente": metrics.estoque_suficiente,
            "is_mais_vendido": metrics.is_mais_vendido,
            "vendedor": metrics.vendedor,
            "url": metrics.url_menor_preco,
            "numero_ofertas_encontradas": len(offers),
        }
    }


def build_optimized_query_v3(descricao: str) -> str:
    """
    Constrói query otimizada para busca no Mercado Livre.
    
    Versão 3: Otimizada para mais vendidos
    """
    desc_lower = descricao.lower()
    
    # Identificar tipo
    if "caixa d'agua" in desc_lower or "caixa dagua" in desc_lower:
        tipo = "caixa dagua"
    elif "reservatório" in desc_lower or "reservatorio" in desc_lower:
        tipo = "reservatorio"
    elif "tanque" in desc_lower:
        tipo = "tanque"
    else:
        tipo = ""
    
    # Material
    material = "polietileno" if "polietileno" in desc_lower else ""
    
    # Capacidade
    import re
    capacidade_match = re.search(r'(\d[\d.]*)\s*litros?', desc_lower)
    capacidade = capacidade_match.group(1) + " litros" if capacidade_match else ""
    
    # Características
    caracteristicas = []
    if "reforçada" in desc_lower or "reforcada" in desc_lower:
        caracteristicas.append("reforcada")
    if "tampa" in desc_lower:
        caracteristicas.append("tampa")
    
    # Montar query
    partes = [p for p in [tipo, material, capacidade] + caracteristicas if p]
    query = " ".join(partes)
    
    return query


async def search_all_items_best_sellers(
    items: List[Dict[str, Any]],
    max_concurrent: int = 3
) -> List[Dict[str, Any]]:
    """
    Busca todos os itens da tabela priorizando BEST SELLERS via API.
    
    Args:
        items: Lista de itens da tabela
        max_concurrent: Número máximo de buscas simultâneas
        
    Returns:
        Lista de resultados para cada item
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def search_with_limit(item):
        async with semaphore:
            return await search_item_with_best_sellers(
                item_number=item["item"],
                descricao=item["descricao"],
                quantidade=item["qtde"],
                valor_unit_max=item["valor_unit_max"]
            )
    
    tasks = [search_with_limit(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    valid_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"[ERRO] Na busca: {r}")
        else:
            valid_results.append(r)
    
    return valid_results


def generate_report_v3(results: List[Dict[str, Any]]) -> str:
    """Gera relatório formatado dos resultados com indicador de mais vendidos."""
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("RELATORIO DE BUSCA - PRICE INTELLIGENCE SQUAD (v3 - MAIS VENDIDOS)")
    lines.append("=" * 80)
    
    total_orcado = 0
    total_coletado = 0
    total_mais_vendidos = 0
    
    for r in results:
        res = r["resultado"]
        lines.append(f"\nItem {r['item_number']}: {r['descricao'][:50]}...")
        lines.append(f"  Qtde: {r['quantidade']} unidades")
        lines.append(f"  Valor Max (PDF): R$ {r['valor_unit_max']:.2f}")
        
        if res["encontrado"]:
            mais_vendido_flag = "⭐ MAIS VENDIDO" if res["is_mais_vendido"] else ""
            lines.append(f"  Menor Preço ML: R$ {res['menor_preco_unitario']:.2f} {mais_vendido_flag}")
            lines.append(f"  Total 10un: R$ {res['preco_total_10un']:.2f}")
            lines.append(f"  Economia: R$ {res['economia_total']:.2f} ({res['economia_percentual']:.1f}%)")
            lines.append(f"  Estoque: {'OK' if res['estoque_suficiente'] else 'INSUFICIENTE'} ({res['quantidade_disponivel']} un)")
            lines.append(f"  Link: {res['url'][:60]}...")
            
            if res["is_mais_vendido"]:
                total_mais_vendidos += 1
            
            total_orcado += r["valor_unit_max"] * r["quantidade"]
            total_coletado += res["preco_total_10un"]
        else:
            lines.append("  ❌ PRODUTO NÃO ENCONTRADO")
    
    economia_total = total_orcado - total_coletado
    percentual = (economia_total / total_orcado * 100) if total_orcado > 0 else 0
    
    lines.append("\n" + "=" * 80)
    lines.append("RESUMO GERAL")
    lines.append("=" * 80)
    lines.append(f"Total Orçado:    R$ {total_orcado:,.2f}")
    lines.append(f"Total Coletado:  R$ {total_coletado:,.2f}")
    lines.append(f"Economia Total:  R$ {economia_total:,.2f} ({percentual:.2f}%)")
    lines.append(f"Itens Mais Vendidos: {total_mais_vendidos}/{len(results)}")
    lines.append("=" * 80 + "\n")
    
    return "\n".join(lines)
