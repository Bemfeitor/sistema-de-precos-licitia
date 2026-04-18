"""
Marketplace Service - Unified Price Search Pipeline

Pipeline:
  1. Bright Data Mercado Livre dataset (primary)
  2. Apify Mercado Livre search (secondary ML coverage)
  3. Google marketplace discovery (cross-marketplace complement)
  4. Mercado Livre official/public search (secondary enrichment)
  5. Firecrawl scraping (diagnostic fallback, last resort)
"""

import asyncio
import logging
import re
from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.config import get_settings
from app.services.apify_ml_client import (
    _extract_price_candidates,
    _extract_title_candidates,
    search_apify_mercadolivre_bundle,
)
from app.services.brightdata_ml_client import search_brightdata_mercadolivre
from app.services.ml_api_client import _is_offer_compatible, get_ml_client

logger = logging.getLogger(__name__)

GOOGLE_MARKETPLACE_DOMAINS = (
    "mercadolivre.com.br",
    "amazon.com.br",
    "magazineluiza.com.br",
    "shopee.com.br",
)
GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
DEFAULT_GOOGLE_RESULT_LIMIT = 5
DEFAULT_GOOGLE_SOURCE_PRIORITY = 2
MARKETPLACE_DEFAULT_CONFIDENCE = {
    "brightdata": 0.95,
    "apify": 0.9,
    "google_search": 0.82,
    "ml_api": 0.84,
    "ml_public": 0.8,
    "firecrawl": 0.76,
}
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

SERVICE_PREFIX_RE = re.compile(
    r"^(?:item\s*\d+\s*-\s*)?(?:servi[cç]o\s+com\s+fornecimento\s+de\s+material(?:\s+sendo)?|fornecimento\s+de\s+material(?:\s+sendo)?)\s*:\s*",
    re.IGNORECASE,
)
SERVICE_TAIL_RE = re.compile(
    r"\b(?:n[ãa]o\s+incluso.*|faixa\s+de\s+pot[êe]ncia.*|demanda\s*\(kva\).*|classifica[cç][ãa]o.*)$",
    re.IGNORECASE,
)

INVALID_PRODUCT_QUERY_RE = re.compile(
    r"^(?:descri(?:cao|Ã§Ã£o)|observa(?:cao|Ã§Ã£o)|item|lote|marca|quant(?:idade)?|un(?:id(?:ade)?)?|valor(?:es)?)\:?$",
    re.IGNORECASE,
)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def build_marketplace_query(product_or_text: Any) -> str:
    if hasattr(product_or_text, "description") or hasattr(product_or_text, "name"):
        raw_query = (getattr(product_or_text, "description", None) or getattr(product_or_text, "name", "") or "").strip()
    else:
        raw_query = str(product_or_text or "").strip()

    if not raw_query:
        return ""

    query = re.sub(r"^\s*item\s*\d+\s*-\s*", "", raw_query, flags=re.IGNORECASE)
    query = SERVICE_PREFIX_RE.sub("", query)
    query = re.sub(r"\([^)]*n[ãa]o\s+incluso[^)]*\)", "", query, flags=re.IGNORECASE)
    query = SERVICE_TAIL_RE.sub("", query)
    query = re.sub(r"\s+", " ", query).strip(" -:;,")
    compact_query = _compact_marketplace_query(query or raw_query)
    return compact_query or query or raw_query


def _compact_marketplace_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", str(query or "")).strip(" -:;,")
    if not normalized:
        return ""

    lowered = normalized.lower()

    if "entrada de energia" in lowered:
        phase = ""
        if "bif" in lowered:
            phase = "bifasico"
        elif "trif" in lowered:
            phase = "trifasico"
        elif "mono" in lowered:
            phase = "monofasico"

        cable_match = re.search(r"cabo\s+de\s+([\d.,]+)\s*mm2", lowered)
        breaker_match = re.search(r"disjuntor(?:\s+din)?\s+(\d{1,3})\s*a", lowered)
        parts = ["padrao entrada energia"]
        if phase:
            parts.append(phase)
        if "caixa de sobrepor" in lowered:
            parts.append("caixa sobrepor")
        if cable_match:
            parts.append(f"cabo {cable_match.group(1).replace(',', '.')}mm")
        if breaker_match:
            parts.append(f"disjuntor {breaker_match.group(1)}a")
        return " ".join(parts)

    if "poste de concreto" in lowered:
        parts = ["poste concreto"]
        if "duplo t" in lowered:
            parts.append("duplo t")
        dan_match = re.search(r"(\d{2,4})\s*dan", lowered)
        if dan_match:
            parts.append(f"{dan_match.group(1)}dan")
        length_match = re.search(r"(\d{1,2}[.,]\d{1,2})\s*m", lowered)
        if length_match:
            parts.append(length_match.group(1).replace(",", ".") + "m")
        return " ".join(parts)

    if "quadro distribu" in lowered:
        breaker_match = re.search(r"disj\w*\s+geral\s+(\d{1,3})a", lowered)
        parts = ["quadro distribuicao"]
        if breaker_match:
            parts.append(f"disjuntor geral {breaker_match.group(1)}a")
        return " ".join(parts)

    return normalized


def _filter_compatible_offers(query: str, offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    normalized_query = re.sub(r"\s+", " ", query or "").strip().lower()
    for offer in offers or []:
        title = (offer.get("title") or "").strip()
        if not title:
            continue
        normalized_title = re.sub(r"\s+", " ", title).strip().lower()
        if normalized_title == normalized_query:
            continue
        if _is_offer_compatible(query, title, []):
            filtered.append(offer)
    return filtered


def _build_product_query(product) -> str:
    return build_marketplace_query(product)


def _is_invalid_product_query(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(query or "")).strip()
    if not normalized or len(normalized) < 3:
        return True
    return bool(INVALID_PRODUCT_QUERY_RE.match(normalized))


def _is_direct_product_url(url: str) -> bool:
    normalized = (url or "").strip().lower()
    if not normalized:
        return False

    if "click1.mercadolivre.com.br" in normalized:
        return True
    if "mercadolivre.com.br" in normalized:
        return "lista.mercadolivre.com.br" not in normalized and (
            "/p/" in normalized or "/_jm" in normalized or "/mlb-" in normalized
        )
    if "magazineluiza.com.br" in normalized:
        return "/p/" in normalized and "/busca/" not in normalized
    if "amazon.com.br" in normalized:
        return "/dp/" in normalized or "/gp/product/" in normalized
    if "shopee.com.br" in normalized:
        return "/product/" in normalized
    return True


def _offer_confidence(offer: Dict[str, Any]) -> float:
    try:
        return float(offer.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _offer_total_cost(offer: Dict[str, Any]) -> float:
    return float(offer.get("price", 0) or 0) + float(offer.get("shipping", 0) or 0)


def build_offer_selection_key(offer: Dict[str, Any]) -> tuple[int, int, float, int, int, float, int]:
    confidence = _offer_confidence(offer)
    validation_bucket = 0 if offer.get("price_match") else 1 if offer.get("price_validated") else 2
    return (
        0 if confidence >= 0.75 else 1,
        0 if _is_direct_product_url(offer.get("url", "")) else 1,
        _offer_total_cost(offer),
        validation_bucket,
        1 if offer.get("listing_type") == "FEATURED" else 0,
        -confidence,
        int(offer.get("source_priority", 9) or 9),
    )


def _apply_offer_defaults(
    offer: Dict[str, Any],
    *,
    source_priority: int,
    source: str,
    default_confidence: float,
    search_strategy: str,
) -> Dict[str, Any]:
    candidate = dict(offer)
    candidate.setdefault("source_priority", source_priority)
    candidate.setdefault("source", source)
    candidate.setdefault("confidence", default_confidence)
    candidate.setdefault("search_strategy", search_strategy)
    candidate.setdefault("shipping", 0.0)
    candidate.setdefault("delivery_days", 5)
    candidate.setdefault("seller_rating", 4.0)
    candidate.setdefault("listing_type", "ORGANIC")
    candidate.setdefault("validation_used", False)
    candidate.setdefault("price_validated", candidate.get("price_validated"))
    candidate.setdefault("price_match", bool(candidate.get("price_match", False)))
    candidate.setdefault("validation_method", candidate.get("validation_method"))
    return candidate


def _dedupe_and_sort_offers(*offer_groups: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    combined: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for group in offer_groups:
        for raw_offer in group or []:
            offer = dict(raw_offer)
            url = (offer.get("url") or "").strip()
            title = (offer.get("title") or "").strip().lower()
            key = (url, title)
            if not url or key in seen_keys:
                continue
            seen_keys.add(key)
            combined.append(offer)

    combined.sort(key=build_offer_selection_key)
    return combined[:limit]


def _sort_lowest_total_cost_offers(offers: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    ordered = [
        offer
        for offer in offers
        if float(offer.get("price", 0) or 0) > 0
    ]
    ordered.sort(
        key=lambda offer: (
            _offer_total_cost(offer) <= 0,
            _offer_total_cost(offer),
            0 if _is_direct_product_url(offer.get("url", "")) else 1,
            -_offer_confidence(offer),
            int(offer.get("source_priority", 9) or 9),
        )
    )
    return ordered[:limit]


def _google_search_query(product_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(product_name or "")).strip()
    marketplaces = " OR ".join(f"site:{domain}" for domain in GOOGLE_MARKETPLACE_DOMAINS)
    return f"{cleaned} ({marketplaces})"


def _is_google_marketplace_url(url: str) -> bool:
    try:
        hostname = (urlparse(url).netloc or "").lower()
    except Exception:
        return False
    return any(domain in hostname for domain in GOOGLE_MARKETPLACE_DOMAINS) and _is_direct_product_url(url)


def _extract_google_result_url(href: str) -> str:
    raw_href = (href or "").strip()
    if not raw_href:
        return ""
    if raw_href.startswith("/url?"):
        parsed = urlparse(raw_href)
        params = parse_qs(parsed.query)
        redirected = params.get("q", [""])[0] or params.get("url", [""])[0]
        return unquote(redirected)
    if raw_href.startswith("http://") or raw_href.startswith("https://"):
        return raw_href
    return ""


def _reference_price_floor(reference_offers: Optional[List[Dict[str, Any]]] = None) -> float:
    prices = [
        _offer_total_cost(offer)
        for offer in (reference_offers or [])
        if _offer_total_cost(offer) > 0
    ]
    if not prices:
        return 0.0
    return round(float(median(sorted(prices)[:5])) * 0.60, 2)


def _marketplace_from_url(url: str) -> str:
    hostname = (urlparse(url).netloc or "").lower()
    if "mercadolivre.com.br" in hostname:
        return "Mercado Livre"
    if "amazon.com.br" in hostname:
        return "Amazon"
    if "magazineluiza.com.br" in hostname:
        return "Magazine Luiza"
    if "shopee.com.br" in hostname:
        return "Shopee"
    return "Google Search"


async def _google_custom_search_discovery(
    session: aiohttp.ClientSession,
    product_name: str,
    limit: int,
) -> List[Dict[str, str]]:
    settings = get_settings()
    if not settings.GOOGLE_SEARCH_API_KEY or not settings.GOOGLE_SEARCH_CX:
        return []

    params = {
        "key": settings.GOOGLE_SEARCH_API_KEY,
        "cx": settings.GOOGLE_SEARCH_CX,
        "q": _google_search_query(product_name),
        "num": max(1, min(limit, 10)),
        "gl": "br",
        "hl": "pt-BR",
    }
    try:
        async with session.get(
            GOOGLE_CSE_URL,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                logger.warning("Google Custom Search failed (%s): %s", response.status, await response.text())
                return []
            payload = await response.json(content_type=None)
    except Exception as error:
        logger.warning("Google Custom Search error for '%s': %s", product_name, error)
        return []

    discovered: List[Dict[str, str]] = []
    for item in payload.get("items") or []:
        url = (item.get("link") or "").strip()
        if not _is_google_marketplace_url(url):
            continue
        discovered.append(
            {
                "url": url,
                "title": (item.get("title") or "").strip(),
                "snippet": (item.get("snippet") or "").strip(),
            }
        )
    return discovered[:limit]


async def _google_html_search_discovery(
    session: aiohttp.ClientSession,
    product_name: str,
    limit: int,
) -> List[Dict[str, str]]:
    params = {
        "q": _google_search_query(product_name),
        "num": max(1, min(limit, 10)),
        "hl": "pt-BR",
        "gl": "br",
        "gbv": "1",
    }
    try:
        async with session.get(
            GOOGLE_SEARCH_URL,
            params=params,
            headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                logger.warning("Google HTML search failed (%s): %s", response.status, await response.text())
                return []
            html = await response.text()
    except Exception as error:
        logger.warning("Google HTML search error for '%s': %s", product_name, error)
        return []

    discovered: List[Dict[str, str]] = []
    seen_urls: set[str] = set()
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("a[href]"):
        title_node = anchor.find("h3")
        if not title_node:
            continue
        url = _extract_google_result_url(anchor.get("href", ""))
        if not url or url in seen_urls or not _is_google_marketplace_url(url):
            continue
        seen_urls.add(url)
        discovered.append(
            {
                "url": url,
                "title": title_node.get_text(" ", strip=True),
                "snippet": "",
            }
        )
        if len(discovered) >= limit:
            break
    return discovered


async def _google_discovery(
    session: aiohttp.ClientSession,
    product_name: str,
    limit: int,
) -> List[Dict[str, str]]:
    discovered = await _google_custom_search_discovery(session, product_name, limit)
    if discovered:
        return discovered
    return await _google_html_search_discovery(session, product_name, limit)


async def _google_result_to_offer(
    session: aiohttp.ClientSession,
    product_name: str,
    result: Dict[str, str],
    price_floor: float,
) -> Optional[Dict[str, Any]]:
    url = (result.get("url") or "").strip()
    fallback_title = (result.get("title") or "").strip()
    if not url:
        return None

    try:
        async with session.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as response:
            if response.status != 200:
                return None
            html = await response.text()
    except Exception as error:
        logger.warning("Google result fetch failed for '%s': %s", url, error)
        return None

    page_titles = _extract_title_candidates(html)
    title = next((candidate for candidate in page_titles if _is_offer_compatible(product_name, candidate, [])), "")
    if not title:
        title = fallback_title
    if not title or not _is_offer_compatible(product_name, title, []):
        return None

    price_candidates = _extract_price_candidates(html)
    if not price_candidates:
        return None

    selected_price: tuple[str, float] | None = None
    for method, candidate_price in price_candidates:
        if price_floor and candidate_price < price_floor:
            continue
        selected_price = (method, candidate_price)
        break

    if not selected_price:
        return None

    validation_method, price = selected_price
    confidence = 0.84 if validation_method in {"json_price", "meta_price"} else 0.78
    return {
        "marketplace": _marketplace_from_url(url),
        "title": title,
        "price": float(price),
        "shipping": 0.0,
        "delivery_days": 5,
        "seller_rating": 4.0,
        "url": url,
        "price_validated": float(price),
        "price_match": True,
        "validation_method": validation_method,
        "validation_used": True,
        "source": "google_search",
        "source_priority": DEFAULT_GOOGLE_SOURCE_PRIORITY,
        "search_strategy": "google_marketplace_discovery",
        "confidence": confidence,
        "listing_type": "ORGANIC",
    }


async def search_google_marketplace_offers(
    product_name: str,
    num_offers: int = 5,
    reference_offers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if _is_invalid_product_query(product_name):
        return []

    price_floor = _reference_price_floor(reference_offers)
    limit = max(1, min(num_offers, get_settings().GOOGLE_SEARCH_MAX_RESULTS or DEFAULT_GOOGLE_RESULT_LIMIT))
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            discovered = await _google_discovery(session, product_name=product_name, limit=limit)
            if not discovered:
                return []

            offers = await asyncio.gather(
                *[
                    _google_result_to_offer(
                        session,
                        product_name=product_name,
                        result=result,
                        price_floor=price_floor,
                    )
                    for result in discovered
                ],
                return_exceptions=True,
            )
    except Exception as error:
        logger.warning("Google marketplace discovery failed for '%s': %s", product_name, error)
        return []

    normalized_offers: List[Dict[str, Any]] = []
    for offer in offers:
        if isinstance(offer, Exception) or not offer:
            continue
        normalized_offers.append(
            _apply_offer_defaults(
                offer,
                source_priority=DEFAULT_GOOGLE_SOURCE_PRIORITY,
                source="google_search",
                default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["google_search"],
                search_strategy="google_marketplace_discovery",
            )
        )

    normalized_offers = _filter_compatible_offers(product_name, normalized_offers)
    deduped = _dedupe_and_sort_offers(normalized_offers, limit=num_offers)
    if deduped:
        logger.info("Google marketplace discovery returned %s offers for '%s'", len(deduped), product_name)
    return deduped


# ==============================================================================
# Google Marketplace Discovery
# ==============================================================================

async def _openai_web_search(product_name: str, num_offers: int = 3) -> List[Dict[str, Any]]:
    """Search using OpenAI Responses API with web_search_preview tool."""
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set, skipping OpenAI web search fallback")
        return []

    try:
        import aiohttp

        prompt = (
            f"Pesquise o preÃ§o atual do produto '{product_name}' em lojas online brasileiras "
            f"(Mercado Livre, Amazon Brasil, Magazine Luiza, Shopee). "
            f"Retorne atÃ© {num_offers} resultados no formato JSON array: "
            f'[{{"marketplace": "nome_loja", "title": "titulo_produto", "price": 123.45, "url": "link_direto"}}]. '
            f"Apenas JSON, sem texto adicional."
        )

        logger.info(
            "OpenAI web_search prompt para '%s': %s chars (~%s tokens).",
            product_name,
            len(prompt),
            _estimate_tokens(prompt),
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.OPENAI_MODEL,
                    "tools": [{"type": "web_search_preview"}],
                    "input": prompt,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"OpenAI web_search failed ({resp.status}): {error_text}")
                    return []

                data = await resp.json()
                usage = data.get("usage") or {}
                if usage:
                    logger.info(
                        "OpenAI web_search usage input=%s output=%s total=%s",
                        usage.get("input_tokens"),
                        usage.get("output_tokens"),
                        usage.get("total_tokens"),
                    )

                text_content = ""
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for content in item.get("content", []):
                            if content.get("type") == "output_text":
                                text_content = content.get("text", "")

                if not text_content:
                    return []

                import json

                json_match = re.search(r"\[.*\]", text_content, re.DOTALL)
                if not json_match:
                    return []

                results = json.loads(json_match.group())
                offers = []
                for result in results:
                    price = result.get("price")
                    if not price or float(price) <= 0:
                        continue
                    title = result.get("title", product_name)
                    url = result.get("url", "")
                    if not _is_direct_product_url(url):
                        continue
                    if not _is_offer_compatible(product_name, title, []):
                        continue
                    offers.append(
                        {
                            "marketplace": result.get("marketplace", "Web Search"),
                            "title": title,
                            "price": float(price),
                            "shipping": 0.0,
                            "delivery_days": 5,
                            "seller_rating": 4.0,
                            "url": url,
                        }
                    )

                logger.info(f"OpenAI web_search: {len(offers)} results for '{product_name}'")
                return offers

    except Exception as error:
        logger.error(f"OpenAI web_search error for '{product_name}': {error}")
        return []


# ==============================================================================
# Legacy Firecrawl fallback
# ==============================================================================

async def _firecrawl_search(product_name: str, num_offers: int = 3) -> List[Dict[str, Any]]:
    """Legacy Firecrawl scraping fallback. Only used when both ML API and OpenAI fail."""
    try:
        from app.services.backend_pipeline_core import (
            ExtractedItem,
            FirecrawlScraper,
            MercadoLivreURLBuilder,
            PriceParser,
        )

        url_builder = MercadoLivreURLBuilder()
        item = ExtractedItem(nome=product_name, pagina_origem=1)
        itens_url = url_builder.construir_urls([item])

        async with FirecrawlScraper() as scraper:
            scraped_data = await scraper.processar_lote(itens_url, max_concurrent=1)

        parser = PriceParser()
        resultados = await parser.processar_lote([scraped for scraped in scraped_data if scraped.markdown])

        offers = []
        for result in resultados:
            if (result.status == "success" or result.status == "partial_error") and result.preco:
                title = result.titulo_encontrado or product_name
                url = result.link_produto or result.search_url
                if not _is_direct_product_url(url):
                    continue
                if not _is_offer_compatible(product_name, title, []):
                    continue
                offers.append(
                    {
                        "marketplace": "ML Scraping",
                        "title": title,
                        "price": result.preco,
                        "shipping": 0.0,
                        "delivery_days": 2,
                        "seller_rating": 5.0,
                        "url": url,
                    }
                )

        logger.info(f"Firecrawl fallback: {len(offers)} results for '{product_name}'")
        return offers
    except Exception as error:
        logger.error(f"Firecrawl fallback failed for '{product_name}': {error}")
        return []


# ==============================================================================
# Unified Search Functions (Public API)
# ==============================================================================

async def search_marketplace_prices(product_name: str, num_offers: int = 5) -> List[Dict[str, Any]]:
    """
    Unified price search pipeline:
    1. Bright Data ML dataset (primary source)
    2. Apify ML scraper with local semantic reranking (secondary ML source)
    3. Google marketplace discovery (cross-marketplace complement)
    4. Mercado Livre official/public search (secondary ML enrichment)
    5. Firecrawl scraping (diagnostic last resort)
    """
    if _is_invalid_product_query(product_name):
        logger.warning(f"Skipping invalid marketplace query: {product_name!r}")
        return []

    settings = get_settings()
    brightdata_offers = await search_brightdata_mercadolivre(product_name, limit=num_offers)
    brightdata_offers = _filter_compatible_offers(product_name, brightdata_offers)
    brightdata_offers = [
        _apply_offer_defaults(
            offer,
            source_priority=0,
            source="brightdata",
            default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["brightdata"],
            search_strategy="brightdata_ml_dataset",
        )
        for offer in brightdata_offers
    ]
    brightdata_best_confidence = max((_offer_confidence(offer) for offer in brightdata_offers), default=0.0)

    if settings.BRIGHT_DATA_ONLY_MODE:
        bright_only_offers = _sort_lowest_total_cost_offers(brightdata_offers, limit=num_offers)
        logger.info(
            "Bright-only mode returned %s offers for '%s'",
            len(bright_only_offers),
            product_name,
        )
        return bright_only_offers

    apify_bundle: Dict[str, Any] = {"results": [], "meta": {}, "winner": None}
    apify_meta: Dict[str, Any] = {}
    apify_offers: List[Dict[str, Any]] = []
    if len(brightdata_offers) < num_offers or brightdata_best_confidence < 0.93:
        apify_bundle = await search_apify_mercadolivre_bundle(product_name, limit=num_offers)
        apify_meta = apify_bundle.get("meta") or {}
        apify_offers = [
            offer for offer in (apify_bundle.get("results") or [])
            if _is_direct_product_url(offer.get("url", ""))
            and float(offer.get("confidence", 0) or 0) >= 0.75
        ]
        apify_offers = _filter_compatible_offers(product_name, apify_offers)
        for offer in apify_offers:
            offer.update(
                _apply_offer_defaults(
                    offer,
                    source_priority=1,
                    source="apify",
                    default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["apify"],
                    search_strategy="mercadolivre_lowest_price_finder",
                )
            )

    reference_offers = brightdata_offers + apify_offers
    google_offers: List[Dict[str, Any]] = []
    if len(reference_offers) < num_offers or max(brightdata_best_confidence, float(apify_meta.get("best_confidence", 0) or 0)) < 0.93:
        google_offers = await search_google_marketplace_offers(
            product_name,
            num_offers=min(num_offers, DEFAULT_GOOGLE_RESULT_LIMIT),
            reference_offers=reference_offers,
        )

    api_offers: List[Dict[str, Any]] = []
    public_site_offers: List[Dict[str, Any]] = []
    if (
        len(brightdata_offers) + len(apify_offers) + len(google_offers) < num_offers
        or max(brightdata_best_confidence, float(apify_meta.get("best_confidence", 0) or 0)) < 0.88
    ):
        ml_client = get_ml_client()
        search_results = await asyncio.gather(
            ml_client.search_product(product_name, limit=num_offers),
            ml_client.search_public_site(product_name, limit=num_offers),
            return_exceptions=True,
        )

        api_offers = [
            offer for offer in (search_results[0] if not isinstance(search_results[0], Exception) else [])
            if _is_direct_product_url(offer.get("url", ""))
        ]
        public_site_offers = [
            offer for offer in (search_results[1] if not isinstance(search_results[1], Exception) else [])
            if _is_direct_product_url(offer.get("url", ""))
        ]

        api_offers = _filter_compatible_offers(product_name, api_offers)
        public_site_offers = _filter_compatible_offers(product_name, public_site_offers)
        api_offers = [
            _apply_offer_defaults(
                offer,
                source_priority=3,
                source="ml_api",
                default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["ml_api"],
                search_strategy="ml_official_catalog",
            )
            for offer in api_offers
        ]
        public_site_offers = [
            _apply_offer_defaults(
                offer,
                source_priority=4,
                source="ml_public",
                default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["ml_public"],
                search_strategy="ml_public_site",
            )
            for offer in public_site_offers
        ]

    combined_primary_offers = _dedupe_and_sort_offers(
        brightdata_offers,
        apify_offers,
        google_offers,
        api_offers,
        public_site_offers,
        limit=num_offers,
    )
    if combined_primary_offers:
        logger.info(
            "Primary search sources returned %s offers for '%s' (brightdata=%s apify=%s google=%s api=%s public=%s)",
            len(combined_primary_offers),
            product_name,
            len(brightdata_offers),
            len(apify_offers),
            len(google_offers),
            len(api_offers),
            len(public_site_offers),
        )
        return combined_primary_offers

    logger.info(
        "Primary sources returned 0 results for '%s', trying Firecrawl diagnostic fallback...",
        product_name,
    )
    firecrawl_offers = await _firecrawl_search(product_name, num_offers)
    firecrawl_offers = _filter_compatible_offers(product_name, firecrawl_offers)
    firecrawl_offers = [
        _apply_offer_defaults(
            offer,
            source_priority=5,
            source="firecrawl",
            default_confidence=MARKETPLACE_DEFAULT_CONFIDENCE["firecrawl"],
            search_strategy="firecrawl_fallback",
        )
        for offer in firecrawl_offers
    ]
    return _dedupe_and_sort_offers(firecrawl_offers, limit=num_offers)


async def search_additional_offer(product_name: str, marketplace: str = None) -> Optional[Dict[str, Any]]:
    """Search for one additional offer."""
    offers = await search_marketplace_prices(product_name, 1)
    return offers[0] if offers else None


async def search_and_save_offers(project_id: str, db=None):
    """Orchestrate search and save for all products in a project."""
    from app.database import SessionLocal
    from app.models.offer import Offer
    from app.models.product import Product
    from app.services.marketplace_service_v4 import search_with_best_sellers_priority

    standalone = False
    if db is None:
        db = SessionLocal()
        standalone = True

    try:
        products = db.query(Product).filter(Product.project_id == project_id).all()
        total_offers = 0
        batch_size = 50
        semaphore = asyncio.Semaphore(5)

        async def process_single_product(product_id):
            async with semaphore:
                worker_db = SessionLocal()
                try:
                    product = worker_db.query(Product).filter(Product.id == product_id).first()
                    if not product:
                        return 0

                    existing = worker_db.query(Offer).filter(Offer.product_id == product.id).count()
                    if existing > 0:
                        product.status = "SUCCESS"
                        worker_db.commit()
                        return 0

                    query = _build_product_query(product)
                    if _is_invalid_product_query(query):
                        logger.warning(f"Skipping invalid product query: {query!r}")
                        product.status = "ERROR_NOT_FOUND"
                        worker_db.commit()
                        return 0

                    offers_data, metrics = await search_with_best_sellers_priority(
                        query=query,
                        quantidade_desejada=product.quantity or 1,
                        valor_maximo=product.valor_unitario_estimado or 0,
                    )
                    if not offers_data:
                        offers_data = await search_marketplace_prices(query, num_offers=3)

                    if metrics.url_menor_preco:
                        for offer_data in offers_data:
                            if offer_data.get("url") == metrics.url_menor_preco:
                                offer_data["marketplace"] = metrics.marketplace_label
                                if metrics.preco_validado_no_link:
                                    offer_data["price"] = metrics.menor_preco

                    count = 0
                    if offers_data:
                        for offer_data in offers_data:
                            if not _is_direct_product_url(offer_data.get("url", "")):
                                continue

                            offer = Offer(
                                product_id=product.id,
                                marketplace=offer_data["marketplace"],
                                title=offer_data["title"],
                                price=offer_data["price"],
                                shipping=offer_data.get("shipping", 0.0),
                                delivery_days=offer_data.get("delivery_days", 3),
                                seller_rating=offer_data.get("seller_rating", 5.0),
                                url=offer_data.get("url", ""),
                                validated_price=offer_data.get("price_validated"),
                                price_match=bool(offer_data.get("price_match", False)),
                                validation_method=offer_data.get("validation_method"),
                                is_best_seller=bool(
                                    offer_data.get("is_best_seller", False)
                                    or offer_data.get("is_mais_vendido", False)
                                ),
                                sold_quantity=offer_data.get("sold_quantity"),
                                validation_checked_at=(
                                    datetime.utcnow()
                                    if offer_data.get("validation_method") or offer_data.get("price_match")
                                    else None
                                ),
                            )
                            worker_db.add(offer)
                            count += 1

                        if count > 0:
                            product.status = "SUCCESS"
                        else:
                            logger.warning(f"No direct offers found for: {_build_product_query(product)}")
                            product.status = "ERROR_NOT_FOUND"
                    else:
                        logger.warning(f"No offers found for: {_build_product_query(product)}")
                        product.status = "ERROR_NOT_FOUND"

                    worker_db.commit()
                    return count
                except Exception as error:
                    logger.error(f"Error searching product {product_id}: {error}")
                    worker_db.rollback()
                    return 0
                finally:
                    worker_db.close()

        for start in range(0, len(products), batch_size):
            batch = products[start:start + batch_size]
            logger.info(
                "Processando lote de busca %s-%s de %s produtos.",
                start + 1,
                start + len(batch),
                len(products),
            )
            tasks = [process_single_product(product.id) for product in batch]
            results = await asyncio.gather(*tasks)
            total_offers += sum(results)

            if start + batch_size < len(products):
                logger.info("Lote concluido, aguardando proximo lote de ate 50 produtos.")
                await asyncio.sleep(2)

        return total_offers
    finally:
        if standalone:
            db.close()
