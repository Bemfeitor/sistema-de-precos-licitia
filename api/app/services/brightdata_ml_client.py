import asyncio
import copy
import logging
import re
import time
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.config import get_settings
from app.services.ml_api_client import _is_offer_compatible, _sanitize_search_query, get_ml_client

logger = logging.getLogger(__name__)

BRIGHT_DATA_BASE_URL = "https://api.brightdata.com/datasets/v3"
ML_LIST_BASE_URL = "https://lista.mercadolivre.com.br"
GOOGLE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"
DISCOVERY_CACHE_TTL_SECONDS = 900
RESULT_CACHE_TTL_SECONDS = 900
DEFAULT_COMPATIBILITY_CONFIDENCE = {
    "HIGH": 0.96,
    "MEDIUM": 0.86,
    "LOW": 0.72,
}
ACCESSORY_TERMS = {
    "tampa",
    "assento",
    "escova",
    "aromatizador",
    "desodorizador",
    "limpador",
    "refil",
    "kit reparo",
    "mecanismo",
    "valvula",
    "suporte",
}
SPECIALIZED_TERMS = {
    "smart toilet",
    "inteligente",
    "automatico",
    "automático",
}
VOLTAGE_TERMS = {"127v", "220v", "bivolt"}
DISCOVERY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
}

_DISCOVERED_URLS_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_BRIGHTDATA_RESULTS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def _extract_mlb_ids(url: str) -> List[str]:
    return re.findall(r"MLB[-]?\d+|MLBU\d+", url or "", flags=re.IGNORECASE)


def _is_direct_ml_product_url(url: str) -> bool:
    normalized = (url or "").strip().lower()
    if not normalized:
        return False
    if "mercadolivre.com.br" not in normalized:
        return False
    if "lista.mercadolivre.com.br" in normalized:
        return False
    return "/p/" in normalized or "/mlb-" in normalized or "produto.mercadolivre.com.br" in normalized


def _normalize_product_url(url: str) -> str:
    normalized = (url or "").strip().replace("&amp;", "&")
    if not normalized:
        return ""
    if normalized.startswith("//"):
        normalized = f"https:{normalized}"
    elif normalized.startswith("/"):
        normalized = f"https://www.mercadolivre.com.br{normalized}"
    return normalized.split("#", 1)[0].split("?", 1)[0]


def _build_listing_variations(query: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", str(query or "")).strip()
    variations: List[str] = []
    for candidate in [
        cleaned,
        cleaned.lower().replace("/", " ").replace("  ", " ").strip(),
        " ".join(cleaned.split()[:3]).strip(),
    ]:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if normalized and normalized not in variations:
            variations.append(normalized)
    return variations


def _build_google_product_query(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(query or "")).strip()
    return f'site:mercadolivre.com.br/p/MLB "{cleaned}" OR site:produto.mercadolivre.com.br "{cleaned}"'


def _extract_urls_from_listing_html(html: str) -> List[str]:
    urls: List[str] = []
    patterns = [
        r'https?://www\.mercadolivre\.com\.br/[^"\'<>\s]+/p/MLB\d+[^"\'<>\s]*',
        r'https?://produto\.mercadolivre\.com\.br/MLB-\d+-[^"\'<>\s?#]+',
        r'href=["\']([^"\']*mercadolivre\.com\.br/[^"\']*(?:/p/MLB\d+|MLB-\d+)[^"\']*)["\']',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, html or "", flags=re.IGNORECASE):
            raw_url = match.group(1) if match.groups() else match.group(0)
            normalized = _normalize_product_url(raw_url)
            if _is_direct_ml_product_url(normalized) and normalized not in urls:
                urls.append(normalized)
    return urls


def _catalog_candidate_to_product_url(candidate: Dict[str, Any]) -> str:
    candidate_id = str(candidate.get("id") or "").strip().upper()
    if re.fullmatch(r"MLB\d+", candidate_id):
        return f"https://www.mercadolivre.com.br/p/{candidate_id}"
    return ""


def _extract_google_result_url(href: str) -> str:
    raw_href = (href or "").strip()
    if not raw_href:
        return ""
    if raw_href.startswith("/url?"):
        parsed = urlparse(raw_href)
        params = parse_qs(parsed.query)
        redirected = params.get("q", [""])[0] or params.get("url", [""])[0]
        return _normalize_product_url(unquote(redirected))
    if raw_href.startswith("http://") or raw_href.startswith("https://"):
        return _normalize_product_url(raw_href)
    return ""


def _extract_review_summary(product: Dict[str, Any]) -> Tuple[float | None, int]:
    reviews = product.get("reviews") or []
    if isinstance(reviews, list) and reviews:
        summary = reviews[0] or {}
        try:
            rating = float(summary.get("average_rating")) if summary.get("average_rating") is not None else None
        except (TypeError, ValueError):
            rating = None
        try:
            total_reviews = int(summary.get("total_reviews") or 0)
        except (TypeError, ValueError):
            total_reviews = 0
        return rating, total_reviews
    return None, 0


def _contains_any(text: str, terms: set[str]) -> bool:
    normalized = (text or "").lower()
    return any(term in normalized for term in terms)


def _is_query_compatible_with_candidate(query: str, title: str) -> bool:
    normalized_query = (query or "").lower()
    normalized_title = (title or "").lower()
    if not _is_offer_compatible(query, title, []):
        return False
    if _contains_any(normalized_title, ACCESSORY_TERMS) and not _contains_any(normalized_query, ACCESSORY_TERMS):
        return False
    if _contains_any(normalized_title, SPECIALIZED_TERMS) and not _contains_any(normalized_query, SPECIALIZED_TERMS):
        return False
    if _contains_any(normalized_title, VOLTAGE_TERMS) and not _contains_any(normalized_query, VOLTAGE_TERMS):
        return False
    return True


def _extract_price(product: Dict[str, Any]) -> float:
    for field in ("final_price", "price", "original_price"):
        value = product.get(field)
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return round(price, 2)
    return 0.0


def _check_compatibility(product: Dict[str, Any], edital_desc: str) -> Dict[str, Any]:
    title = (product.get("title") or "").lower()
    desc = (product.get("description") or "").lower()
    feats = " ".join(str(feature) for feature in (product.get("product_features") or [])).lower()
    combined = f"{title} {desc} {feats}"
    edital_lower = (edital_desc or "").lower()

    combined_norm = re.sub(r"(\d+)/(\d+)", r"\1\2", combined)
    edital_norm = re.sub(r"(\d+)/(\d+)", r"\1\2", edital_lower)
    dim_pattern = r'\d+(?:[.,]\d+)?(?:\s*(?:mm|cm|m\b|kg\b|g\b|l\b|ml|pol|"|\s*x\s*\d+))?'
    dims = [value.replace(" ", "") for value in re.findall(dim_pattern, edital_norm) if len(value.strip()) > 1]
    matched_dims = sum(1 for value in dims if value in combined_norm.replace(" ", ""))
    total_dims = len(dims)

    stopwords = {
        "para",
        "com",
        "tipo",
        "agua",
        "fria",
        "quente",
        "uso",
        "geral",
        "kit",
        "unid",
        "peca",
        "und",
        "unidade",
        "item",
        "cada",
        "por",
        "mais",
        "menos",
        "outro",
        "essa",
        "este",
        "esse",
    }
    keywords = [
        token
        for token in re.split(r"\W+", edital_lower)
        if len(token) > 3 and token not in stopwords
    ]
    matched_kw = sum(1 for keyword in keywords if keyword in combined)
    total_kw = max(len(keywords), 1)

    dim_ratio = matched_dims / max(total_dims, 1)
    kw_ratio = matched_kw / total_kw

    if dim_ratio >= 0.7 and kw_ratio >= 0.6:
        score = "HIGH"
    elif kw_ratio >= 0.35 and (total_dims == 0 or dim_ratio >= 0.4):
        score = "MEDIUM"
    else:
        score = "LOW"

    return {
        "score": score,
        "reason": f"Dimensoes: {matched_dims}/{total_dims} | Palavras-chave: {matched_kw}/{total_kw}",
        "dim_ratio": round(dim_ratio, 2),
        "kw_ratio": round(kw_ratio, 2),
    }


async def _discover_urls_from_listing(
    session: aiohttp.ClientSession,
    query: str,
    max_urls: int,
) -> List[str]:
    found_urls: List[str] = []
    for variation in _build_listing_variations(query):
        search_url = f"{ML_LIST_BASE_URL}/{quote(variation.replace('/', ' ').strip(), safe='')}"
        try:
            async with session.get(
                search_url,
                headers=DISCOVERY_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    continue
                html = await response.text()
                if "account-verification" in str(response.url) or "account-verification" in html[:800]:
                    logger.warning("Mercado Livre listing blocked for '%s'", query)
                    return found_urls
        except Exception as error:
            logger.warning("ML listing discovery failed for '%s': %s", query, error)
            continue

        for url in _extract_urls_from_listing_html(html):
            if url not in found_urls:
                found_urls.append(url)
            if len(found_urls) >= max_urls:
                return found_urls[:max_urls]
    return found_urls[:max_urls]


async def _discover_urls_from_existing_searches(query: str, max_urls: int) -> List[str]:
    urls: List[str] = []
    ml_client = get_ml_client()
    search_tasks = [
        ml_client.search_public_site(query, limit=max_urls),
        ml_client.search_product(query, limit=max_urls),
        ml_client.search_catalog_products(query, limit=max_urls),
    ]
    if hasattr(ml_client, "_search_via_api"):
        search_tasks.append(ml_client._search_via_api(query, limit=max_urls, catalog_titles=[]))

    search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

    for result in search_results:
        if isinstance(result, Exception):
            continue
        for offer in result or []:
            normalized_url = _normalize_product_url(offer.get("url", ""))
            if not normalized_url:
                normalized_url = _normalize_product_url(_catalog_candidate_to_product_url(offer))
            if _is_direct_ml_product_url(normalized_url) and normalized_url not in urls:
                urls.append(normalized_url)
            if len(urls) >= max_urls:
                return urls[:max_urls]

    return urls[:max_urls]


async def _discover_urls_from_google(
    session: aiohttp.ClientSession,
    query: str,
    max_urls: int,
) -> List[str]:
    settings = get_settings()
    urls: List[str] = []
    cse_params = {
        "key": settings.GOOGLE_SEARCH_API_KEY,
        "cx": settings.GOOGLE_SEARCH_CX,
        "q": _build_google_product_query(query),
        "num": max(1, min(max_urls, 10)),
        "gl": "br",
        "hl": "pt-BR",
    }

    if settings.GOOGLE_SEARCH_API_KEY and settings.GOOGLE_SEARCH_CX:
        try:
            async with session.get(
                GOOGLE_CSE_URL,
                params=cse_params,
                headers=DISCOVERY_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status == 200:
                    payload = await response.json(content_type=None)
                    for item in payload.get("items") or []:
                        title = (item.get("title") or "").strip()
                        candidate_url = _normalize_product_url(item.get("link") or "")
                        if (
                            _is_direct_ml_product_url(candidate_url)
                            and title
                            and _is_query_compatible_with_candidate(query, title)
                            and candidate_url not in urls
                        ):
                            urls.append(candidate_url)
                        if len(urls) >= max_urls:
                            return urls[:max_urls]
        except Exception as error:
            logger.warning("Google CSE URL discovery failed for '%s': %s", query, error)

    html_params = {
        "q": _build_google_product_query(query),
        "num": max(1, min(max_urls, 10)),
        "hl": "pt-BR",
        "gl": "br",
        "gbv": "1",
    }
    try:
        async with session.get(
            GOOGLE_SEARCH_URL,
            params=html_params,
            headers=DISCOVERY_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status != 200:
                return urls[:max_urls]
            html = await response.text()
    except Exception as error:
        logger.warning("Google HTML URL discovery failed for '%s': %s", query, error)
        return urls[:max_urls]

    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("a[href]"):
        title_node = anchor.find("h3")
        if not title_node:
            continue
        title = title_node.get_text(" ", strip=True)
        candidate_url = _extract_google_result_url(anchor.get("href", ""))
        if (
            _is_direct_ml_product_url(candidate_url)
            and title
            and _is_query_compatible_with_candidate(query, title)
            and candidate_url not in urls
        ):
            urls.append(candidate_url)
        if len(urls) >= max_urls:
            break
    return urls[:max_urls]


async def discover_ml_product_urls(query: str, max_urls: int) -> List[str]:
    normalized_query = re.sub(r"\s+", " ", _sanitize_search_query(query)).strip().lower()
    cached = _DISCOVERED_URLS_CACHE.get(normalized_query)
    now = time.time()
    if cached and cached[0] > now:
        return list(cached[1])

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        discovered = await _discover_urls_from_listing(session, query, max_urls=max_urls)
        if len(discovered) < min(3, max_urls):
            google_urls = await _discover_urls_from_google(session, query, max_urls=max_urls)
            for url in google_urls:
                if url not in discovered:
                    discovered.append(url)
                if len(discovered) >= max_urls:
                    break

    if len(discovered) < min(3, max_urls):
        fallback_urls = await _discover_urls_from_existing_searches(query, max_urls=max_urls)
        for url in fallback_urls:
            if url not in discovered:
                discovered.append(url)
            if len(discovered) >= max_urls:
                break

    _DISCOVERED_URLS_CACHE[normalized_query] = (now + DISCOVERY_CACHE_TTL_SECONDS, discovered[:max_urls])
    return discovered[:max_urls]


async def _trigger_snapshot(
    session: aiohttp.ClientSession,
    api_key: str,
    dataset_id: str,
    payload: List[Dict[str, str]],
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{BRIGHT_DATA_BASE_URL}/trigger"
    params = {
        "dataset_id": dataset_id,
        "format": "json",
    }

    async with session.post(
        endpoint,
        headers=headers,
        params=params,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as response:
        if response.status >= 400:
            body = await response.text()
            logger.warning("Bright Data trigger failed (%s): %s", response.status, body)
            return ""
        data = await response.json(content_type=None)
    return str(data.get("snapshot_id") or "")


async def _poll_snapshot(
    session: aiohttp.ClientSession,
    api_key: str,
    snapshot_id: str,
    max_wait_seconds: int,
    poll_seconds: int,
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    endpoint = f"{BRIGHT_DATA_BASE_URL}/progress/{snapshot_id}"
    elapsed = 0

    while elapsed < max_wait_seconds:
        await asyncio.sleep(max(1, poll_seconds))
        elapsed += max(1, poll_seconds)
        async with session.get(
            endpoint,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status >= 400:
                logger.warning("Bright Data progress failed (%s): %s", response.status, await response.text())
                return {}
            data = await response.json(content_type=None)
        if data.get("status") in {"ready", "done", "failed"}:
            return data

    return {"status": "timeout", "records": 0, "errors": 1}


async def _download_snapshot(
    session: aiohttp.ClientSession,
    api_key: str,
    snapshot_id: str,
) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    endpoint = f"{BRIGHT_DATA_BASE_URL}/snapshot/{snapshot_id}"
    params = {"format": "json"}

    async with session.get(
        endpoint,
        headers=headers,
        params=params,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as response:
        if response.status >= 400:
            logger.warning("Bright Data snapshot download failed (%s): %s", response.status, await response.text())
            return []
        data = await response.json(content_type=None)
    return data if isinstance(data, list) else []


def _map_product_to_offer(query: str, product: Dict[str, Any]) -> Dict[str, Any] | None:
    title = (product.get("title") or "").strip()
    price = _extract_price(product)
    input_data = product.get("input") or {}
    input_url = input_data.get("url") if isinstance(input_data, dict) else ""
    product_url = _normalize_product_url(product.get("url") or input_url or "")
    if not title or price <= 0 or not _is_direct_ml_product_url(product_url):
        return None
    if not _is_query_compatible_with_candidate(query, title):
        return None

    compatibility = _check_compatibility(product, query)
    confidence = DEFAULT_COMPATIBILITY_CONFIDENCE.get(compatibility["score"], 0.72)
    rating, review_count = _extract_review_summary(product)
    try:
        sold_quantity = int(product.get("num_sold") or 0)
    except (TypeError, ValueError):
        sold_quantity = 0

    return {
        "marketplace": "Mercado Livre (Bright Data)",
        "title": title,
        "price": price,
        "currency": product.get("currency") or "BRL",
        "shipping": 0.0,
        "delivery_days": 5,
        "seller_rating": rating or 4.0,
        "seller_name": (product.get("seller_name") or "").strip() or None,
        "validated_price": price,
        "price_validated": price,
        "price_match": True,
        "validation_method": "brightdata_dataset",
        "validation_used": True,
        "is_best_seller": False,
        "sold_quantity": sold_quantity or None,
        "url": product_url,
        "listing_type": "ORGANIC",
        "available_quantity": 999 if product.get("in_stock") else 0,
        "in_stock": bool(product.get("in_stock")),
        "brand": (product.get("brand") or "").strip(),
        "model": (product.get("model") or "").strip(),
        "reviews_count": review_count,
        "source": "brightdata",
        "source_priority": 0,
        "search_strategy": "brightdata_ml_dataset",
        "confidence": confidence,
        "compatibility_score": compatibility["score"],
        "compatibility_reason": compatibility["reason"],
    }


async def search_brightdata_mercadolivre(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    settings = get_settings()
    if not settings.BRIGHT_DATA_API_KEY or not settings.BRIGHT_DATA_DATASET_ID:
        return []

    normalized_query = re.sub(r"\s+", " ", _sanitize_search_query(query)).strip().lower()
    cached = _BRIGHTDATA_RESULTS_CACHE.get(f"{normalized_query}:{limit}")
    now = time.time()
    if cached and cached[0] > now:
        return copy.deepcopy(cached[1])

    max_urls = max(1, int(settings.BRIGHT_DATA_MAX_URLS_PER_QUERY or 12))
    batch_size = max(1, int(settings.BRIGHT_DATA_BATCH_SIZE or max_urls))
    poll_seconds = max(1, int(settings.BRIGHT_DATA_POLL_SECONDS or 4))
    max_wait_seconds = max(poll_seconds, int(settings.BRIGHT_DATA_MAX_WAIT_SECONDS or 120))
    urls = await discover_ml_product_urls(query, max_urls=max_urls)
    if not urls:
        logger.info("Bright Data URL discovery returned 0 product URLs for '%s'", query)
        return []

    payload = [{"url": url} for url in urls[:max_urls]]
    products: List[Dict[str, Any]] = []
    timeout = aiohttp.ClientTimeout(total=max_wait_seconds + 30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for start in range(0, len(payload), batch_size):
            batch = payload[start : start + batch_size]
            snapshot_id = await _trigger_snapshot(
                session,
                api_key=settings.BRIGHT_DATA_API_KEY,
                dataset_id=settings.BRIGHT_DATA_DATASET_ID,
                payload=batch,
            )
            if not snapshot_id:
                continue

            status = await _poll_snapshot(
                session,
                api_key=settings.BRIGHT_DATA_API_KEY,
                snapshot_id=snapshot_id,
                max_wait_seconds=max_wait_seconds,
                poll_seconds=poll_seconds,
            )
            if status.get("status") not in {"ready", "done"}:
                logger.warning("Bright Data snapshot ended with status %s for '%s'", status.get("status"), query)
                continue

            batch_products = await _download_snapshot(
                session,
                api_key=settings.BRIGHT_DATA_API_KEY,
                snapshot_id=snapshot_id,
            )
            products.extend(batch_products)

    offers: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for product in products:
        offer = _map_product_to_offer(query, product)
        if not offer:
            continue
        url = offer.get("url") or ""
        if url in seen_urls:
            continue
        seen_urls.add(url)
        offers.append(offer)

    offers.sort(
        key=lambda offer: (
            float(offer.get("price", 0) or 0) <= 0,
            float(offer.get("price", 0) or 0),
            0 if offer.get("in_stock") else 1,
            -float(offer.get("confidence", 0) or 0),
        )
    )
    limited = offers[:limit]
    _BRIGHTDATA_RESULTS_CACHE[f"{normalized_query}:{limit}"] = (
        now + RESULT_CACHE_TTL_SECONDS,
        copy.deepcopy(limited),
    )
    if limited:
        logger.info("Bright Data returned %s offers for '%s' from %s URLs", len(limited), query, len(urls))
    return limited
