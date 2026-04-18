"""
Marketplace Service V2 — Price Intelligence Squad Implementation

Funcionalidades:
- Busca por menor preço + preço médio
- Validação de links
- Fallback de quantidade (10 → 1×10)
- Limite de 50 requisições
- Estruturação precisa de queries

Baseado na estratégia da Squad AIOX: price-intelligence-squad
"""

import logging
import asyncio
import os
import aiohttp
from typing import List, Dict, Any, Optional, Tuple
from statistics import mean

from app.services.ml_api_client import get_ml_client

logger = logging.getLogger(__name__)


class PriceMetrics:
    """Métricas de preço calculadas para um produto."""
    
    def __init__(self):
        self.menor_preco: float = 0.0
        self.preco_medio: float = 0.0
        self.preco_total_10un: float = 0.0
        self.economia_vs_maximo: float = 0.0
        self.quantidade_disponivel: int = 0
        self.url_menor_preco: str = ""
        self.vendedor: str = ""
        self.estoque_suficiente: bool = False


async def validate_link(url: str) -> Dict[str, Any]:
    """
    Valida se o link do Mercado Livre está acessível e retorna informações.
    
    Args:
        url: URL do produto no Mercado Livre
        
    Returns:
        Dict com status da validação
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html",
                },
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True,
            ) as resp:
                return {
                    "valid": resp.status == 200,
                    "status_code": resp.status,
                    "accessible": resp.status == 200,
                    "final_url": str(resp.url),
                }
    except Exception as e:
        logger.error(f"Link validation error for {url}: {e}")
        return {
            "valid": False,
            "status_code": 0,
            "accessible": False,
            "error": str(e),
        }


async def search_with_metrics(
    query: str,
    quantidade_desejada: int = 10,
    valor_maximo: float = 0.0
) -> Tuple[List[Dict[str, Any]], PriceMetrics]:
    """
    Busca produto no Mercado Livre com métricas completas.
    
    Estratégia Squad AIOX:
    1. Busca com sort=price_asc (menor preço primeiro)
    2. Coleta até 50 resultados para calcular média
    3. Verifica disponibilidade de quantidade
    4. Fallback: se não tiver 10 unidades, calcula 1 unidade × 10
    5. Valida o link do produto com menor preço
    
    Args:
        query: Query de busca otimizada
        quantidade_desejada: Quantidade necessária (padrão: 10)
        valor_maximo: Valor máximo do orçamento para calcular economia
        
    Returns:
        Tuple (lista de ofertas, métricas calculadas)
    """
    metrics = PriceMetrics()
    ml_client = get_ml_client()
    
    logger.info(f"[Squad] Buscando: {query} (Qtde: {quantidade_desejada})")
    
    # Busca com limite máximo (50) para calcular média precisa
    offers = await ml_client.search_product(query, limit=50)
    
    if not offers:
        logger.warning(f"[Squad] Nenhum resultado para: {query}")
        return [], metrics
    
    # Extrair todos os preços válidos
    precos = [o["price"] for o in offers if o["price"] > 0]
    
    if not precos:
        return [], metrics
    
    # Calcular métricas
    metrics.menor_preco = min(precos)
    metrics.preco_medio = mean(precos)
    
    # Encontrar oferta com menor preço
    oferta_menor = min(offers, key=lambda x: x["price"])
    metrics.url_menor_preco = oferta_menor.get("url", "")
    metrics.vendedor = oferta_menor.get("seller_name", "N/A")
    metrics.quantidade_disponivel = oferta_menor.get("available_quantity", 0)
    
    # Verificar se tem quantidade suficiente
    if metrics.quantidade_disponivel >= quantidade_desejada:
        metrics.estoque_suficiente = True
        metrics.preco_total_10un = metrics.menor_preco * quantidade_desejada
        logger.info(f"[Squad] Estoque OK: {metrics.quantidade_disponivel} un disponíveis")
    else:
        # Fallback: calcular preço para 10 unidades individuais
        metrics.estoque_suficiente = False
        metrics.preco_total_10un = metrics.menor_preco * quantidade_desejada
        logger.warning(
            f"[Squad] Estoque insuficiente: {metrics.quantidade_disponivel} un. "
            f"Usando fallback: {quantidade_desejada} × {metrics.menor_preco}"
        )
    
    # Calcular economia vs valor máximo
    if valor_maximo > 0:
        valor_total_maximo = valor_maximo * quantidade_desejada
        metrics.economia_vs_maximo = valor_total_maximo - metrics.preco_total_10un
    
    # Validar link do produto com menor preço
    if metrics.url_menor_preco:
        link_validation = await validate_link(metrics.url_menor_preco)
        oferta_menor["link_validated"] = link_validation["valid"]
        oferta_menor["link_accessible"] = link_validation["accessible"]
        logger.info(f"[Squad] Link validado: {link_validation['valid']}")
    
    logger.info(
        f"[Squad] Resultados: Menor=R${metrics.menor_preco:.2f}, "
        f"Médio=R${metrics.preco_medio:.2f}, Total 10un=R${metrics.preco_total_10un:.2f}"
    )
    
    return offers, metrics


async def search_item_optimized(
    item_number: int,
    descricao: str,
    quantidade: int,
    valor_unit_max: float
) -> Dict[str, Any]:
    """
    Busca otimizada para um item específico da tabela.
    
    Estratégia:
    1. Extrair keywords da descrição
    2. Montar query otimizada
    3. Buscar com métricas completas
    4. Retornar resultado estruturado
    
    Args:
        item_number: Número do item (59-69)
        descricao: Descrição completa do produto
        quantidade: Quantidade necessária
        valor_unit_max: Valor unitário máximo do orçamento
        
    Returns:
        Dict com resultado completo da busca
    """
    # Extrair keywords e montar query otimizada
    query = build_optimized_query(descricao)
    
    logger.info(f"[Squad Item {item_number}] Query: {query}")
    
    # Buscar com métricas
    offers, metrics = await search_with_metrics(
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
            "menor_preco_unitario": round(metrics.menor_preco, 2),
            "preco_medio_unitario": round(metrics.preco_medio, 2),
            "preco_total_10un": round(metrics.preco_total_10un, 2),
            "economia_total": round(metrics.economia_vs_maximo, 2),
            "economia_percentual": round(
                (metrics.economia_vs_maximo / (valor_unit_max * quantidade)) * 100, 2
            ) if valor_unit_max > 0 else 0,
            "quantidade_disponivel": metrics.quantidade_disponivel,
            "estoque_suficiente": metrics.estoque_suficiente,
            "vendedor": metrics.vendedor,
            "url": metrics.url_menor_preco,
            "link_validado": True if offers else False,
            "numero_ofertas_encontradas": len(offers),
        }
    }


def build_optimized_query(descricao: str) -> str:
    """
    Constrói query otimizada para busca no Mercado Livre.
    
    Regras Squad AIOX:
    1. Remover palavras irrelevantes
    2. Manter: Tipo + Material + Capacidade + Características
    3. Usar sinônimos comuns (água → agua)
    
    Args:
        descricao: Descrição original do produto
        
    Returns:
        Query otimizada
    """
    # Mapeamento de termos
    desc_lower = descricao.lower()
    
    # Identificar tipo
    if "caixa d'água" in desc_lower or "caixa dagua" in desc_lower:
        tipo = "caixa dagua"
    elif "reservatório" in desc_lower or "reservatorio" in desc_lower:
        tipo = "reservatorio"
    elif "tanque" in desc_lower:
        tipo = "tanque"
    else:
        tipo = ""
    
    # Identificar material
    material = "polietileno" if "polietileno" in desc_lower else ""
    
    # Identificar capacidade (extrair número + litros)
    import re
    capacidade_match = re.search(r'(\d[\d.]*)\s*litros?', desc_lower)
    capacidade = capacidade_match.group(1) + " litros" if capacidade_match else ""
    
    # Identificar características
    caracteristicas = []
    if "reforçada" in desc_lower or "reforcada" in desc_lower:
        caracteristicas.append("reforcada")
    if "tampa" in desc_lower:
        caracteristicas.append("tampa")
    
    # Montar query
    partes = [p for p in [tipo, material, capacidade] + caracteristicas if p]
    query = " ".join(partes)
    
    return query


async def search_all_items_from_table(
    items: List[Dict[str, Any]],
    max_concurrent: int = 3
) -> List[Dict[str, Any]]:
    """
    Busca todos os itens da tabela com controle de concorrência.
    
    Args:
        items: Lista de itens da tabela (com item_number, descricao, qtde, etc.)
        max_concurrent: Número máximo de buscas simultâneas
        
    Returns:
        Lista de resultados para cada item
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def search_with_limit(item):
        async with semaphore:
            return await search_item_optimized(
                item_number=item["item"],
                descricao=item["descricao"],
                quantidade=item["qtde"],
                valor_unit_max=item["valor_unit_max"]
            )
    
    tasks = [search_with_limit(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtrar exceções
    valid_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"[Squad] Erro na busca: {r}")
        else:
            valid_results.append(r)
    
    return valid_results


def generate_report(results: List[Dict[str, Any]]) -> str:
    """
    Gera relatório formatado dos resultados.
    
    Args:
        results: Lista de resultados da busca
        
    Returns:
        String com relatório formatado
    """
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append("RELATÓRIO DE BUSCA - PRICE INTELLIGENCE SQUAD")
    lines.append("=" * 80)
    
    total_orcado = 0
    total_coletado = 0
    
    for r in results:
        res = r["resultado"]
        lines.append(f"\nItem {r['item_number']}: {r['descricao'][:50]}...")
        lines.append(f"  Qtde: {r['quantidade']} unidades")
        lines.append(f"  Valor Max (PDF): R$ {r['valor_unit_max']:.2f}")
        
        if res["encontrado"]:
            lines.append(f"  Menor Preço ML: R$ {res['menor_preco_unitario']:.2f}")
            lines.append(f"  Preço Médio ML: R$ {res['preco_medio_unitario']:.2f}")
            lines.append(f"  Total 10un: R$ {res['preco_total_10un']:.2f}")
            lines.append(f"  Economia: R$ {res['economia_total']:.2f} ({res['economia_percentual']:.1f}%)")
            lines.append(f"  Estoque: {'OK' if res['estoque_suficiente'] else 'INSUFICIENTE'} ({res['quantidade_disponivel']} un)")
            lines.append(f"  Link: {res['url'][:60]}...")
            
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
    lines.append("=" * 80 + "\n")
    
    return "\n".join(lines)
