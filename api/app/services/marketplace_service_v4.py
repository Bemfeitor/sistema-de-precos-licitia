"""
Marketplace Service V4 - exact-price validation and best-seller-first search.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Tuple

import aiohttp

from app.config import get_settings
from app.services.apify_ml_client import search_apify_mercadolivre_bundle
from app.services.brightdata_ml_client import search_brightdata_mercadolivre
from app.services.marketplace_service import (
    _offer_total_cost,
    build_offer_selection_key,
    search_google_marketplace_offers,
)
from app.services.ml_api_client import get_ml_client, _is_offer_compatible

logger = logging.getLogger(__name__)


class RequestQueue:
    """Throttle outbound validation/search requests in small batches."""

    def __init__(self, max_per_batch: int = 50, delay_between_requests: float = 1.0):
        self.max_per_batch = max_per_batch
        self.delay_between_requests = delay_between_requests
        self.request_count = 0
        self.batch_count = 0
        self.lock = asyncio.Lock()

    async def acquire_slot(self) -> Dict[str, int]:
        async with self.lock:
            if self.request_count >= self.max_per_batch:
                logger.info("[FILA] lote completo, aguardando proximo lote")
                self.request_count = 0
                self.batch_count += 1
                await asyncio.sleep(5.0)

            self.request_count += 1
            if self.request_count > 1:
                await asyncio.sleep(self.delay_between_requests)

            return {
                "batch": self.batch_count,
                "request": self.request_count,
                "total": self.batch_count * self.max_per_batch + self.request_count,
            }


request_queue = RequestQueue(max_per_batch=50, delay_between_requests=1.5)


class PriceMetrics:
    def __init__(self):
        self.menor_preco: float = 0.0
        self.preco_total_10un: float = 0.0
        self.economia_vs_maximo: float = 0.0
        self.quantidade_disponivel: int = 0
        self.url_menor_preco: str = ""
        self.vendedor: str = ""
        self.estoque_suficiente: bool = False
        self.is_mais_vendido: bool = False
        self.preco_validado_no_link: bool = False
        self.metodo_validacao: str = ""
        self.marketplace_label: str = "Mercado Livre"


def _normalize_price_text(value: str) -> float:
    cleaned = (value or "").strip().replace("R$", "").replace(" ", "")
    if not cleaned:
        return 0.0

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")

    return round(float(cleaned), 2)


def _extract_price_candidates(html: str) -> List[Tuple[str, float]]:
    patterns = [
        ("json_price", r'"price"\s*:\s*"?(?P<value>\d[\d.,]*)"?'),
        ("meta_price", r'"priceAmount"\s*:\s*"?(?P<value>\d[\d.,]*)"?'),
        ("andes_fraction", r'andes-money-amount__fraction[^>]*>(?P<value>\d[\d.]*)<'),
        ("reais_centavos", r'R\$\s*(?P<value>\d[\d.]*,\d{2})'),
    ]

    candidates: List[Tuple[str, float]] = []
    for source, pattern in patterns:
        for match in re.finditer(pattern, html):
            value = match.groupdict().get("value")
            if not value:
                continue
            try:
                price = _normalize_price_text(value)
            except Exception:
                continue
            if price > 0:
                candidates.append((source, price))
    return candidates


def _extract_title_candidates(html: str) -> List[str]:
    patterns = [
        r"<title>(?P<value>[^<]+)</title>",
        r'property="og:title"\s+content="(?P<value>[^"]+)"',
        r'"name"\s*:\s*"(?P<value>[^"]+)"',
    ]
    titles: List[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.IGNORECASE):
            value = (match.groupdict().get("value") or "").strip()
            if value and value not in titles:
                titles.append(value)
    return titles


def _is_exact_price_match(validated_price: float, expected_price: float) -> bool:
    return round(validated_price, 2) == round(expected_price, 2)


def _is_duplicate(new_offer: Dict[str, Any], existing_offers: List[Dict[str, Any]]) -> bool:
    new_title = new_offer.get("title", "").lower()
    new_url = (new_offer.get("url") or "").strip().lower()
    new_marketplace = (new_offer.get("marketplace") or "").strip().lower()
    for offer in existing_offers:
        existing_url = (offer.get("url") or "").strip().lower()
        existing_title = offer.get("title", "").lower()
        existing_marketplace = (offer.get("marketplace") or "").strip().lower()
        if new_url and existing_url and new_url == existing_url:
            return True
        if new_marketplace == existing_marketplace and _similarity(new_title, existing_title) > 0.85:
            return True
    return False


def _upsert_offer_prefer_lower_cost(new_offer: Dict[str, Any], existing_offers: List[Dict[str, Any]]) -> None:
    new_title = new_offer.get("title", "").lower()
    new_url = (new_offer.get("url") or "").strip().lower()
    new_marketplace = (new_offer.get("marketplace") or "").strip().lower()
    for index, offer in enumerate(existing_offers):
        existing_url = (offer.get("url") or "").strip().lower()
        existing_title = offer.get("title", "").lower()
        existing_marketplace = (offer.get("marketplace") or "").strip().lower()
        same_offer = (
            (new_url and existing_url and new_url == existing_url)
            or (
                new_marketplace == existing_marketplace
                and _similarity(new_title, existing_title) > 0.85
            )
        )
        if not same_offer:
            continue
        if _offer_total_cost(new_offer) < _offer_total_cost(offer):
            existing_offers[index] = new_offer
        return
    existing_offers.append(new_offer)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0

    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0

    return len(words_a.intersection(words_b)) / max(len(words_a), len(words_b))


async def validate_price_in_link(url: str, expected_price: float, query: str = "") -> Dict[str, Any]:
    if not url:
        return {
            "valid": False,
            "price_validated": 0.0,
            "price_match": False,
            "error": "URL vazia",
        }

    try:
        await request_queue.acquire_slot()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html",
                    "Accept-Language": "pt-BR,pt;q=0.9",
                },
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return {
                        "valid": False,
                        "price_validated": 0.0,
                        "price_match": False,
                        "error": f"HTTP {resp.status}",
                    }
                html = await resp.text()

        candidates = _extract_price_candidates(html)
        page_titles = _extract_title_candidates(html)
        if query and page_titles and not any(_is_offer_compatible(query, title, []) for title in page_titles):
            return {
                "valid": False,
                "price_validated": 0.0,
                "price_match": False,
                "error": "Link incompatível com o item buscado",
                "validation_method": "content_mismatch",
            }
        if not candidates:
            return {
                "valid": False,
                "price_validated": 0.0,
                "price_match": False,
                "error": "Nao foi possivel extrair preco do link",
            }

        for source, candidate_price in candidates:
            if _is_exact_price_match(candidate_price, expected_price):
                return {
                    "valid": True,
                    "price_validated": candidate_price,
                    "price_match": True,
                    "difference": 0.0,
                    "validation_method": source,
                }

        source, candidate_price = candidates[0]
        return {
            "valid": True,
            "price_validated": candidate_price,
            "price_match": False,
            "expected": expected_price,
            "difference": round(abs(candidate_price - expected_price), 2),
            "validation_method": source,
        }
    except Exception as error:
        logger.error(f"[VALIDACAO] erro ao validar preco no link: {error}")
        return {
            "valid": False,
            "price_validated": 0.0,
            "price_match": False,
            "error": str(error),
        }


async def search_best_sellers_api(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        await request_queue.acquire_slot()
        ml_client = get_ml_client()
        offers = await ml_client.search_best_sellers(query, limit=limit)
        for offer in offers:
            offer["is_mais_vendido"] = bool(
                offer.get("is_best_seller", False) or offer.get("sold_quantity", 0) > 50
            )
            if offer["is_mais_vendido"]:
                offer["marketplace"] = "Mercado Livre (Mais Vendido)"
        return offers
    except Exception as error:
        logger.error(f"Erro API best sellers: {error}")
        return []


def _sort_priority_offer(offer: Dict[str, Any]) -> tuple[int, int, float, float]:
    return build_offer_selection_key(offer)


def _sort_lowest_cost_offer(offer: Dict[str, Any]) -> tuple[int, float, int, float]:
    return (
        float(offer.get("price", 0) or 0) <= 0,
        _offer_total_cost(offer),
        0 if offer.get("url") else 1,
        -float(offer.get("confidence", 0) or 0),
    )


async def search_with_best_sellers_priority(
    query: str,
    quantidade_desejada: int = 10,
    valor_maximo: float = 0.0,
) -> Tuple[List[Dict[str, Any]], PriceMetrics]:
    settings = get_settings()
    metrics = PriceMetrics()
    all_offers: List[Dict[str, Any]] = []
    bright_only_mode = bool(settings.BRIGHT_DATA_ONLY_MODE)
    brightdata_offers = await search_brightdata_mercadolivre(query, limit=10)
    for offer in brightdata_offers:
        title = (offer.get("title") or "").strip()
        if (
            float(offer.get("confidence", 0) or 0) < 0.75
            or title and (title.strip().lower() == query.strip().lower() or not _is_offer_compatible(query, title, []))
        ):
            continue
        offer.setdefault("source_priority", 0)
        offer.setdefault("source", "brightdata")
        offer.setdefault("search_strategy", "brightdata_ml_dataset")
        offer.setdefault("confidence", 0.95)
        if bright_only_mode:
            _upsert_offer_prefer_lower_cost(offer, all_offers)
        elif not _is_duplicate(offer, all_offers):
            all_offers.append(offer)

    brightdata_confidence = max((float(offer.get("confidence", 0) or 0) for offer in brightdata_offers), default=0.0)

    apify_bundle = {"results": [], "meta": {}, "winner": None}
    apify_meta: Dict[str, Any] = {}
    if not bright_only_mode and (not brightdata_offers or brightdata_confidence < 0.93):
        apify_bundle = await search_apify_mercadolivre_bundle(query, limit=10)
        apify_results = apify_bundle.get("results") or []
        apify_meta = apify_bundle.get("meta") or {}
        for offer in apify_results:
            title = (offer.get("title") or "").strip()
            if (
                float(offer.get("confidence", 0) or 0) < 0.75
                or title and (title.strip().lower() == query.strip().lower() or not _is_offer_compatible(query, title, []))
            ):
                continue
            offer.setdefault("source_priority", 1)
            offer.setdefault("source", "apify")
            offer.setdefault("search_strategy", "mercadolivre_lowest_price_finder")
            offer.setdefault("confidence", 0.9)
            if not _is_duplicate(offer, all_offers):
                all_offers.append(offer)

    apify_confidence = float(apify_meta.get("best_confidence", 0) or 0)
    google_offers: List[Dict[str, Any]] = []
    if not bright_only_mode and (not brightdata_offers or max(brightdata_confidence, apify_confidence) < 0.93):
        google_offers = await search_google_marketplace_offers(
            query,
            num_offers=5,
            reference_offers=all_offers,
        )
    for offer in google_offers:
        offer.setdefault("source_priority", 2)
        offer.setdefault("source", "google_search")
        offer.setdefault("search_strategy", "google_marketplace_discovery")
        offer.setdefault("confidence", 0.82)
        if not _is_duplicate(offer, all_offers):
            all_offers.append(offer)

    if not bright_only_mode and ((not brightdata_offers and len(all_offers) < 10) or max(brightdata_confidence, apify_confidence) < 0.93):
        best_sellers = await search_best_sellers_api(query, limit=20)
        for offer in best_sellers:
            offer.setdefault("source_priority", 3)
            offer.setdefault("source", "ml_best_sellers")
            offer.setdefault("search_strategy", "ml_best_sellers")
            offer.setdefault("confidence", 0.88)
            if not _is_duplicate(offer, all_offers):
                all_offers.append(offer)

    if not bright_only_mode and ((not brightdata_offers and len(all_offers) < 10) or max(brightdata_confidence, apify_confidence) < 0.85):
        ml_client = get_ml_client()
        api_results = await ml_client.search_product(query, limit=30)
        for offer in api_results:
            offer.setdefault("source_priority", 4)
            offer.setdefault("source", "ml_api")
            offer.setdefault("search_strategy", "ml_official_catalog")
            offer.setdefault("confidence", 0.84)
            if not _is_duplicate(offer, all_offers):
                all_offers.append(offer)

    candidate_offers = [
        offer
        for offer in all_offers
        if float(offer.get("price", 0) or 0) > 0
        and (offer.get("title") or "").strip().lower() != query.strip().lower()
        and _is_offer_compatible(query, offer.get("title", ""), [])
    ]
    if not candidate_offers:
        return [], metrics

    if bright_only_mode:
        candidate_offers.sort(key=_sort_lowest_cost_offer)
    else:
        candidate_offers.sort(key=_sort_priority_offer)

    exact_validated_offer = None
    if not bright_only_mode and not settings.ML_OFFICIAL_ONLY:
        for offer in candidate_offers[:5]:
            url = offer.get("url", "")
            expected_price = float(offer.get("price", 0) or 0)
            if not url or expected_price <= 0:
                continue

            validation = await validate_price_in_link(url, expected_price, query=query)
            offer["validation_method"] = validation.get("validation_method", "")
            offer["price_validated"] = validation.get("price_validated", 0.0)
            offer["price_match"] = validation.get("price_match", False)

            if validation["valid"] and validation["price_match"]:
                offer["price"] = validation["price_validated"]
                exact_validated_offer = offer
                break

    selected_offer = exact_validated_offer or min(
        candidate_offers,
        key=_sort_lowest_cost_offer if bright_only_mode else _sort_priority_offer,
    )

    metrics.menor_preco = float(selected_offer["price"])
    metrics.url_menor_preco = selected_offer.get("url", "")
    metrics.vendedor = selected_offer.get("seller_name", selected_offer.get("seller", "N/A"))
    metrics.quantidade_disponivel = int(selected_offer.get("available_quantity", 0) or 0)
    metrics.is_mais_vendido = bool(
        selected_offer.get("is_mais_vendido") or selected_offer.get("is_best_seller")
    )
    metrics.preco_validado_no_link = bool(selected_offer.get("price_match"))
    metrics.metodo_validacao = selected_offer.get("validation_method", "")
    metrics.marketplace_label = selected_offer.get("marketplace") or "Mercado Livre"

    if metrics.is_mais_vendido:
        metrics.marketplace_label += " (Mais Vendido)"
    if metrics.preco_validado_no_link:
        metrics.marketplace_label += " (Validado)"

    selected_offer["marketplace"] = metrics.marketplace_label

    metrics.estoque_suficiente = metrics.quantidade_disponivel >= quantidade_desejada
    metrics.preco_total_10un = metrics.menor_preco * quantidade_desejada
    if valor_maximo > 0:
        metrics.economia_vs_maximo = valor_maximo * quantidade_desejada - metrics.preco_total_10un

    return all_offers, metrics


async def search_item_with_best_sellers(
    item_number: int,
    descricao: str,
    quantidade: int,
    valor_unit_max: float,
) -> Dict[str, Any]:
    query = build_optimized_query_v4(descricao)
    offers, metrics = await search_with_best_sellers_priority(
        query=query,
        quantidade_desejada=quantidade,
        valor_maximo=valor_unit_max,
    )

    return {
        "item_number": item_number,
        "descricao": descricao,
        "query_usada": query,
        "quantidade": quantidade,
        "valor_unit_max": valor_unit_max,
        "resultado": {
            "encontrado": len(offers) > 0,
            "menor_preco_unitario": metrics.menor_preco,
            "preco_total_10un": metrics.preco_total_10un,
            "economia_total": metrics.economia_vs_maximo,
            "economia_percentual": round(
                (metrics.economia_vs_maximo / (valor_unit_max * quantidade)) * 100, 2
            ) if valor_unit_max > 0 else 0,
            "quantidade_disponivel": metrics.quantidade_disponivel,
            "estoque_suficiente": metrics.estoque_suficiente,
            "is_mais_vendido": metrics.is_mais_vendido,
            "preco_validado_no_link": metrics.preco_validado_no_link,
            "vendedor": metrics.vendedor,
            "url": metrics.url_menor_preco,
            "numero_ofertas_encontradas": len(offers),
            "metodo_validacao": metrics.metodo_validacao,
        },
    }


def build_optimized_query_v4(descricao: str) -> str:
    desc_lower = descricao.lower()

    if "caixa d'agua" in desc_lower or "caixa dagua" in desc_lower:
        tipo = "caixa dagua"
    elif "reservatorio" in desc_lower or "reservatório" in desc_lower:
        tipo = "reservatorio"
    elif "tanque" in desc_lower:
        tipo = "tanque"
    else:
        tipo = ""

    material = "polietileno" if "polietileno" in desc_lower else ""

    capacidade_match = re.search(r"(\d[\d.]*)\s*litros?", desc_lower)
    capacidade = capacidade_match.group(1) + " litros" if capacidade_match else ""

    caracteristicas = []
    if "reforçada" in desc_lower or "reforcada" in desc_lower:
        caracteristicas.append("reforcada")
    if "tampa" in desc_lower:
        caracteristicas.append("tampa")

    return " ".join(part for part in [tipo, material, capacidade] + caracteristicas if part)


async def search_all_items_best_sellers(
    items: List[Dict[str, Any]],
    max_concurrent: int = 3,
) -> List[Dict[str, Any]]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def search_with_limit(item: Dict[str, Any]):
        async with semaphore:
            return await search_item_with_best_sellers(
                item_number=item["item"],
                descricao=item["descricao"],
                quantidade=item["qtde"],
                valor_unit_max=item["valor_unit_max"],
            )

    results = await asyncio.gather(*(search_with_limit(item) for item in items), return_exceptions=True)
    return [result for result in results if not isinstance(result, Exception)]


def generate_report_v4(results: List[Dict[str, Any]]) -> str:
    lines = [
        "",
        "=" * 80,
        "RELATORIO - PRICE INTELLIGENCE SQUAD V4",
        "=" * 80,
    ]

    total_orcado = 0.0
    total_coletado = 0.0
    total_validados = 0

    for result in results:
        current = result["resultado"]
        lines.append(f"\nItem {result['item_number']}: {result['descricao'][:50]}...")
        lines.append(f"  Qtde: {result['quantidade']}")
        lines.append(f"  Valor Max (PDF): R$ {result['valor_unit_max']}")

        if current["encontrado"]:
            if current["preco_validado_no_link"]:
                total_validados += 1
            lines.append(f"  Menor Preco ML: R$ {current['menor_preco_unitario']}")
            lines.append(f"  Total 10un: R$ {current['preco_total_10un']}")
            lines.append(f"  Economia: R$ {current['economia_total']} ({current['economia_percentual']}%)")
            lines.append(f"  Link: {current['url'][:60]}...")
            total_orcado += result["valor_unit_max"] * result["quantidade"]
            total_coletado += current["preco_total_10un"]
        else:
            lines.append("  NAO ENCONTRADO")

    economia_total = total_orcado - total_coletado
    percentual = (economia_total / total_orcado * 100) if total_orcado > 0 else 0
    lines.extend([
        "",
        "=" * 80,
        "RESUMO GERAL",
        "=" * 80,
        f"Total Orcado:    R$ {total_orcado}",
        f"Total Coletado:  R$ {total_coletado}",
        f"Economia:        R$ {economia_total} ({percentual:.2f}%)",
        f"Precos Validados: {total_validados}/{len(results)}",
        "=" * 80,
        "",
    ])
    return "\n".join(lines)
