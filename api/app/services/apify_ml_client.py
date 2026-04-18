import asyncio
import copy
import logging
import re
import time
from statistics import median
from typing import Any, Dict, List, Tuple
from urllib.parse import quote

import aiohttp

from app.config import get_settings
from app.services.ml_api_client import (
    _extract_measure_map,
    _is_offer_compatible,
    _normalize_text,
    _sanitize_search_query,
    _tokenize,
)

logger = logging.getLogger(__name__)


class ApifyHardLimitExceeded(RuntimeError):
    """Raised when Apify blocks execution because the account hit a hard limit."""

APIFY_BASE_URL = "https://api.apify.com/v2"
RUN_SYNC_TIMEOUT_SECONDS = 45
RUN_ASYNC_TIMEOUT_SECONDS = 90
RUN_POLL_INTERVAL_SECONDS = 2
DEFAULT_MAX_PAGES = 1
FALLBACK_MAX_PAGES = 2
CACHE_TTL_SECONDS = 900
HIGH_CONFIDENCE_THRESHOLD = 0.93
VALIDATE_TOP1_THRESHOLD = 0.85
VALIDATE_TOP2_THRESHOLD = 0.75
LOW_PRICE_ALERT_RATIO = 0.60
LEGACY_ACTOR_FALLBACK_ID = "l43NkeQ5ZTbdljNRj"

COUNTRY_DOMAINS = {
    "BR": "https://lista.mercadolivre.com.br",
    "AR": "https://listado.mercadolibre.com.ar",
    "MX": "https://listado.mercadolibre.com.mx",
    "CO": "https://listado.mercadolibre.com.co",
    "CL": "https://listado.mercadolibre.cl",
    "PE": "https://listado.mercadolibre.com.pe",
}

AUTOMATIC_EXCLUSION_TERMS = {
    "capa",
    "case",
    "pelicula",
    "refil",
    "reposicao",
    "reposicao",
    "peca",
    "pecas",
    "usado",
    "recondicionado",
    "vitrine",
    "defeito",
    "compativel com",
    "similar",
}
ACCESSORY_TERMS = {
    "acessorio",
    "adaptador",
    "anel",
    "boia",
    "escova",
    "escova sanitaria",
    "fixacao",
    "kit reparo",
    "mecanismo",
    "parafuso",
    "porta escova",
    "porta papel",
    "refil",
    "reposicao",
    "suporte",
    "tampa",
    "torneira",
    "valvula",
}
COLOR_TERMS = {
    "branco",
    "branca",
    "preto",
    "preta",
    "black",
    "cinza",
    "grafite",
    "bege",
    "azul",
    "vermelho",
    "verde",
}
KNOWN_BRANDS = (
    "amanco",
    "astra",
    "brastemp",
    "celite",
    "deca",
    "docol",
    "electrolux",
    "hydra",
    "incepa",
    "lorenzetti",
    "philips walita",
    "philips",
    "roca",
    "suvinil",
    "tigre",
    "tramontina",
)
CATEGORY_PATTERNS = (
    ("vaso sanitario", ("vaso", "sanitario")),
    ("caixa de descarga", ("caixa", "descarga")),
    ("assento sanitario", ("assento", "sanitario")),
    ("caixa sifonada", ("caixa", "sifonada")),
    ("engate flexivel", ("engate", "flexivel")),
    ("adaptador flange", ("adaptador", "flange")),
    ("caixa dagua", ("caixa", "dagua")),
    ("reservatorio", ("reservatorio",)),
    ("air fryer", ("air", "fryer")),
)

_APIFY_QUERY_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _build_actor_ref(actor_id: str) -> str:
    raw = (actor_id or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("/", "~")
    return quote(normalized, safe="~")


def _build_search_url(keyword: str, country: str = "BR") -> str:
    base_url = COUNTRY_DOMAINS.get((country or "BR").upper(), COUNTRY_DOMAINS["BR"])
    slug = quote((keyword or "").strip().replace(" ", "-"), safe="-")
    return f"{base_url}/{slug}"


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


def _extract_voltage(normalized_query: str) -> str:
    match = re.search(r"\b(110|127|220)\s*v?\b", normalized_query)
    return f"{match.group(1)}v" if match else ""


def _extract_capacity(measure_map: Dict[str, set[str]]) -> str:
    for unit in ("l", "kg", "mm", "cm", "m", "pol"):
        values = sorted(measure_map.get(unit, set()), key=len, reverse=True)
        if values:
            return f"{values[0]}{unit}"
    return ""


def _detect_brand(normalized_query: str) -> str:
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if brand in normalized_query:
            return brand
    return ""


def _detect_category(normalized_query: str) -> str:
    for label, tokens in CATEGORY_PATTERNS:
        if all(token in normalized_query for token in tokens):
            return label
    return ""


def _looks_like_attribute(token: str) -> bool:
    if token in COLOR_TERMS:
        return True
    if re.fullmatch(r"\d+(?:[.,]\d+)?(?:mm|cm|m|l|kg|g|pol|v)", token):
        return True
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", token))


def _build_model(normalized_query: str, brand: str, category: str) -> str:
    brand_tokens = set(_tokenize(brand))
    category_tokens = set(_tokenize(category))
    model_tokens: List[str] = []

    for token in normalized_query.split():
        cleaned = token.strip()
        if not cleaned:
            continue
        if cleaned in brand_tokens:
            continue
        if cleaned in category_tokens and category_tokens:
            model_tokens.append(cleaned)
            continue
        if _looks_like_attribute(cleaned):
            continue
        model_tokens.append(cleaned)

    compact = " ".join(model_tokens[:4]).strip()
    if compact:
        return compact
    return category or normalized_query


def _build_must_have_tokens(
    normalized_query: str,
    brand: str,
    model: str,
    category: str,
    voltage: str,
    measure_map: Dict[str, set[str]],
) -> List[str]:
    must_have: List[str] = []

    for token in sorted(_tokenize(brand), key=len, reverse=True):
        if token not in must_have:
            must_have.append(token)

    for token in sorted(_tokenize(model), key=len, reverse=True):
        if token not in must_have:
            must_have.append(token)

    for token in sorted(_tokenize(category), key=len, reverse=True):
        if token not in must_have:
            must_have.append(token)

    if voltage and voltage not in must_have:
        must_have.append(voltage)

    for color in COLOR_TERMS:
        if color in normalized_query and color not in must_have:
            must_have.append(color)

    for unit in ("l", "kg", "mm", "cm", "m", "pol"):
        for value in sorted(measure_map.get(unit, set()), key=len, reverse=True):
            token = f"{value}{unit}"
            if token not in must_have:
                must_have.append(token)

    return must_have


def _build_must_not_have(normalized_query: str, voltage: str) -> List[str]:
    must_not_have = set(AUTOMATIC_EXCLUSION_TERMS)
    must_not_have.update({"usado", "recondicionado"})

    if voltage:
        for candidate in ("110v", "127v", "220v"):
            if candidate != voltage:
                must_not_have.add(candidate)

    if "branco" in normalized_query or "branca" in normalized_query:
        must_not_have.update({"preto", "preta", "black"})

    return sorted(must_not_have)


def _canonicalize_query(query: str) -> Dict[str, Any]:
    raw = _sanitize_search_query(query or "")
    normalized = _normalize_text(raw)
    measure_map = _extract_measure_map(raw)
    voltage = _extract_voltage(normalized)
    brand = _detect_brand(normalized)
    category = _detect_category(normalized)
    model = _build_model(normalized, brand, category)
    must_have = _build_must_have_tokens(normalized, brand, model, category, voltage, measure_map)
    must_not_have = _build_must_not_have(normalized, voltage)

    return {
        "raw": raw,
        "normalized": normalized,
        "brand": brand,
        "model": model,
        "category": category,
        "category_tokens": sorted(_tokenize(category)),
        "capacity": _extract_capacity(measure_map),
        "voltage": voltage,
        "condition": "new",
        "must_have": must_have,
        "must_not_have": must_not_have,
        "measure_map": measure_map,
        "tokens": sorted(_tokenize(normalized)),
        "cache_key": normalized,
    }


def _build_query_variants(query_spec: Dict[str, Any]) -> List[str]:
    variants: List[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        cleaned = re.sub(r"\s+", " ", _sanitize_search_query(candidate or "")).strip(" -,:;")
        key = _normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            variants.append(cleaned)

    raw = query_spec["raw"]
    add(raw)
    add(raw.replace(",", " "))
    if "," in raw:
        add(raw.split(",", 1)[0])

    without_color = " ".join(
        token for token in raw.split()
        if _normalize_text(token) not in COLOR_TERMS
    )
    add(without_color)

    compact_parts = [query_spec["category"], query_spec["brand"], query_spec["capacity"], query_spec["voltage"]]
    add(" ".join(part for part in compact_parts if part))
    return variants[:4]


def _normalize_offer(item: Dict[str, Any]) -> Dict[str, Any] | None:
    offered = item.get("item_offered") or {}
    price = offered.get("price") or item.get("price")
    url = offered.get("url") or item.get("url") or ""
    title = item.get("name") or item.get("title") or ""

    if not title or not url:
        return None

    try:
        price_value = float(price)
    except (TypeError, ValueError):
        return None

    if price_value <= 0:
        return None

    aggregate_rating = item.get("aggregate_rating") or {}
    rating_value = aggregate_rating.get("rating_value")
    rating_count = aggregate_rating.get("rating_count")
    listing_type = item.get("type") or "ORGANIC"
    marketplace = "Mercado Livre (Apify)"
    if listing_type == "FEATURED":
        marketplace = "Mercado Livre (Apify Patrocinado)"

    return {
        "marketplace": marketplace,
        "title": title,
        "price": round(price_value, 2),
        "currency": offered.get("price_currency") or "BRL",
        "shipping": 0.0,
        "delivery_days": 3,
        "seller_rating": float(rating_value) if rating_value else 4.0,
        "url": url,
        "price_validated": None,
        "price_match": False,
        "validation_method": "apify_dataset",
        "validation_used": False,
        "sold_quantity": rating_count if rating_count else None,
        "is_best_seller": False,
        "is_mais_vendido": False,
        "has_free_shipping": bool(item.get("has_free_shipping")),
        "listing_type": listing_type,
        "brand": ((item.get("brand_attribute") or {}).get("name") or "").strip(),
        "source": "apify",
        "source_priority": 0,
        "search_strategy": "mercadolivre_lowest_price_finder",
    }


def _measure_tokens(measure_map: Dict[str, set[str]]) -> set[str]:
    return {f"{value}{unit}" for unit, values in measure_map.items() for value in values}


def _contains_any_phrase(text: str, phrases: set[str]) -> str:
    for phrase in sorted(phrases, key=len, reverse=True):
        if phrase in text:
            return phrase
    return ""


def _has_voltage_conflict(query_spec: Dict[str, Any], normalized_title: str) -> bool:
    required_voltage = query_spec.get("voltage") or ""
    if not required_voltage:
        return False

    title_voltage = _extract_voltage(normalized_title)
    return bool(title_voltage and title_voltage != required_voltage)


def _has_capacity_conflict(query_spec: Dict[str, Any], normalized_title: str) -> bool:
    query_measures = _measure_tokens(query_spec.get("measure_map") or {})
    if not query_measures:
        return False

    title_measures = _measure_tokens(_extract_measure_map(normalized_title))
    if not title_measures:
        return False

    query_units = {}
    title_units = {}
    for token in query_measures:
        unit = re.sub(r"^[\d.,-]+", "", token)
        query_units.setdefault(unit, set()).add(token)
    for token in title_measures:
        unit = re.sub(r"^[\d.,-]+", "", token)
        title_units.setdefault(unit, set()).add(token)

    for unit, values in query_units.items():
        if unit in title_units and values.isdisjoint(title_units[unit]):
            return True
    return False


def _score_candidate(query_spec: Dict[str, Any], offer: Dict[str, Any], median_price: float | None = None) -> Dict[str, Any]:
    normalized_title = _normalize_text(offer.get("title", ""))
    raw_title = offer.get("title", "")
    candidate = copy.deepcopy(offer)
    candidate["confidence"] = 0.0
    candidate["match_reasons"] = []
    candidate["discarded_candidates"] = []
    candidate["needs_review"] = False

    if not _is_offer_compatible(query_spec["raw"], raw_title, []):
        candidate["discard_reason"] = "mismatch_semantico"
        return candidate

    blocked = _contains_any_phrase(normalized_title, set(query_spec["must_not_have"]))
    if blocked:
        candidate["discard_reason"] = f"termo_proibido:{blocked}"
        return candidate

    accessory = _contains_any_phrase(normalized_title, ACCESSORY_TERMS)
    if accessory and accessory not in query_spec["normalized"]:
        candidate["discard_reason"] = f"acessorio:{accessory}"
        return candidate

    if any(term in normalized_title for term in ("usado", "recondicionado")):
        candidate["discard_reason"] = "condicao_invalida"
        return candidate

    if _has_voltage_conflict(query_spec, normalized_title):
        candidate["discard_reason"] = "voltagem_divergente"
        return candidate

    if _has_capacity_conflict(query_spec, normalized_title):
        candidate["discard_reason"] = "capacidade_divergente"
        return candidate

    score = 0.20
    match_reasons: List[str] = []
    title_tokens = _tokenize(normalized_title)

    brand_tokens = _tokenize(query_spec["brand"])
    if brand_tokens and brand_tokens.issubset(title_tokens):
        score += 0.25
        match_reasons.append("marca exata")

    model_tokens = _tokenize(query_spec["model"])
    if model_tokens and model_tokens.issubset(title_tokens):
        score += 0.30
        match_reasons.append("modelo exato")

    critical_matches = [token for token in query_spec["must_have"] if token in normalized_title]
    if query_spec["must_have"] and len(critical_matches) == len(query_spec["must_have"]):
        score += 0.25
        for token in critical_matches:
            if token not in match_reasons:
                match_reasons.append(f"atributo {token}")
    elif critical_matches:
        score += min(0.25, 0.08 * len(critical_matches))
        for token in critical_matches[:3]:
            match_reasons.append(f"atributo {token}")

    category_tokens = set(query_spec["category_tokens"])
    if category_tokens and category_tokens.issubset(title_tokens):
        score += 0.10
        match_reasons.append("categoria correta")

    if (offer.get("sold_quantity") or 0) > 0 or (offer.get("seller_rating") or 0) >= 4:
        score += 0.05
        match_reasons.append("consistencia vendedor/titulo")

    if offer.get("listing_type") == "FEATURED":
        score -= 0.05

    suspicious_price = False
    if median_price and median_price > 0:
        current_price = float(offer.get("price", 0) or 0)
        if current_price >= median_price * LOW_PRICE_ALERT_RATIO:
            score += 0.05
            match_reasons.append("faixa de preco plausivel")
        else:
            suspicious_price = True
            candidate["price_alert"] = "preco 40% abaixo da mediana"

    candidate["confidence"] = round(max(0.0, min(score, 0.99)), 2)
    candidate["match_reasons"] = match_reasons
    candidate["suspicious_price"] = suspicious_price
    return candidate


def _median_price(candidates: List[Dict[str, Any]]) -> float | None:
    prices = [
        float(candidate.get("price", 0) or 0)
        for candidate in sorted(candidates, key=lambda offer: float(offer.get("price", 0) or 0))[:5]
        if float(candidate.get("price", 0) or 0) > 0
    ]
    if not prices:
        return None
    return float(median(prices))


def _rank_candidates(query_spec: Dict[str, Any], offers: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    preliminar: List[Dict[str, Any]] = []
    discarded: List[Dict[str, Any]] = []

    for offer in offers:
        candidate = _score_candidate(query_spec, offer)
        if candidate.get("discard_reason"):
            discarded.append(
                {
                    "title": offer.get("title", ""),
                    "price": offer.get("price"),
                    "reason": candidate["discard_reason"],
                }
            )
            continue
        preliminar.append(candidate)

    median_price = _median_price(preliminar)
    ranked = [_score_candidate(query_spec, candidate, median_price=median_price) for candidate in preliminar]
    ranked = [candidate for candidate in ranked if not candidate.get("discard_reason")]
    ranked.sort(
        key=lambda candidate: (
            -float(candidate.get("confidence", 0) or 0),
            1 if candidate.get("listing_type") == "FEATURED" else 0,
            float(candidate.get("price", 0) or 0),
        )
    )
    return ranked, discarded


async def _validate_offer_url(url: str, expected_price: float, query: str) -> Dict[str, Any]:
    if not url:
        return {"valid": False, "price_match": False, "error": "url_vazia"}

    try:
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
            ) as response:
                if response.status != 200:
                    return {
                        "valid": False,
                        "price_match": False,
                        "error": f"http_{response.status}",
                    }
                html = await response.text()
    except Exception as error:
        logger.error("Apify deep validation failed for '%s': %s", url, error)
        return {"valid": False, "price_match": False, "error": str(error)}

    titles = _extract_title_candidates(html)
    if query and titles and not any(_is_offer_compatible(query, title, []) for title in titles):
        return {
            "valid": False,
            "price_match": False,
            "error": "titulo_incompativel",
        }

    prices = _extract_price_candidates(html)
    if not prices:
        return {
            "valid": False,
            "price_match": False,
            "error": "preco_nao_extraido",
        }

    for source, price in prices:
        if round(price, 2) == round(expected_price, 2):
            return {
                "valid": True,
                "price_validated": price,
                "price_match": True,
                "validation_method": source,
            }

    source, price = prices[0]
    return {
        "valid": True,
        "price_validated": price,
        "price_match": False,
        "validation_method": source,
    }


def _decide_validation_depth(best_score: float, suspicious_price: bool) -> int:
    if suspicious_price:
        return 1
    if best_score >= HIGH_CONFIDENCE_THRESHOLD:
        return 0
    if best_score >= VALIDATE_TOP1_THRESHOLD:
        return 1
    if best_score >= VALIDATE_TOP2_THRESHOLD:
        return 2
    return 3


async def _apply_conditional_validation(
    query_spec: Dict[str, Any],
    ranked_candidates: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any] | None, List[Dict[str, Any]], int, str]:
    if not ranked_candidates:
        return None, ranked_candidates, 0, "empty"

    best_candidate = ranked_candidates[0]
    validation_depth = min(
        len(ranked_candidates),
        _decide_validation_depth(
            float(best_candidate.get("confidence", 0) or 0),
            bool(best_candidate.get("suspicious_price")),
        ),
    )

    validated_candidates: List[Dict[str, Any]] = []
    validation_calls = 0
    if validation_depth > 0:
        for candidate in ranked_candidates[:validation_depth]:
            validation = await _validate_offer_url(
                candidate.get("url", ""),
                float(candidate.get("price", 0) or 0),
                query_spec["raw"],
            )
            validation_calls += 1
            candidate["validation_used"] = True
            candidate["validation_method"] = validation.get("validation_method") or candidate.get("validation_method")
            candidate["price_validated"] = validation.get("price_validated")
            candidate["price_match"] = bool(validation.get("price_match"))
            if validation.get("valid"):
                if validation.get("price_validated"):
                    candidate["price"] = float(validation["price_validated"])
                candidate["confidence"] = round(min(0.99, float(candidate.get("confidence", 0) or 0) + 0.03), 2)
                validated_candidates.append(candidate)

    if validated_candidates:
        winner = min(
            validated_candidates,
            key=lambda candidate: (
                float(candidate.get("price", 0) or 0),
                -float(candidate.get("confidence", 0) or 0),
            ),
        )
    else:
        winner = ranked_candidates[0]

    status = "ok"
    if float(winner.get("confidence", 0) or 0) < VALIDATE_TOP2_THRESHOLD:
        winner["needs_review"] = True
        status = "needs_review"

    return winner, ranked_candidates, validation_calls, status


def _candidate_actor_refs(actor_id: str) -> List[str]:
    refs: List[str] = []
    for candidate in [actor_id, LEGACY_ACTOR_FALLBACK_ID]:
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in refs:
            refs.append(cleaned)
    return refs


async def _run_sync_dataset_items(
    session: aiohttp.ClientSession,
    actor_id: str,
    api_key: str,
    search_url: str,
    max_pages: int,
    limit: int,
    preferred_endpoint: str,
) -> List[Dict[str, Any]]:
    actor_ref = _build_actor_ref(actor_id)
    if not actor_ref:
        return []

    endpoint = f"{APIFY_BASE_URL}/acts/{actor_ref}/{preferred_endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": search_url,
        "max_pages": max(1, max_pages),
    }
    params = {
        "format": "json",
        "clean": "1",
    }

    try:
        async with session.post(
            endpoint,
            headers=headers,
            params=params,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=RUN_SYNC_TIMEOUT_SECONDS),
        ) as response:
            if response.status >= 400:
                error_text = await response.text()
                if response.status == 403 and "platform-feature-disabled" in error_text.lower():
                    raise ApifyHardLimitExceeded(error_text)
                logger.warning("Apify sync dataset failed (%s): %s", response.status, error_text)
                return []

            result = await response.json(content_type=None)
            return result if isinstance(result, list) else []
    except ApifyHardLimitExceeded:
        raise
    except Exception as error:
        logger.warning("Apify sync dataset error for actor '%s': %s", actor_id, error)
        return []


async def _start_actor_run(
    session: aiohttp.ClientSession,
    actor_id: str,
    api_key: str,
    search_url: str,
    max_pages: int,
    limit: int,
) -> Dict[str, str] | None:
    actor_ref = _build_actor_ref(actor_id)
    if not actor_ref:
        return None

    endpoint = f"{APIFY_BASE_URL}/acts/{actor_ref}/runs"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    params = {
        "maxTotalChargeUsd": round(max(0.01, max(limit, 10) * 0.003), 4),
    }
    payload = {
        "url": search_url,
        "max_pages": max(1, max_pages),
    }

    try:
        async with session.post(
            endpoint,
            headers=headers,
            params=params,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status >= 400:
                error_text = await response.text()
                if response.status == 403 and "platform-feature-disabled" in error_text.lower():
                    raise ApifyHardLimitExceeded(error_text)
                logger.warning("Apify actor start failed (%s): %s", response.status, error_text)
                return None

            data = await response.json(content_type=None)
            run = data.get("data") or {}
            run_id = run.get("id")
            dataset_id = run.get("defaultDatasetId")
            if not run_id or not dataset_id:
                logger.warning("Apify actor start returned incomplete payload: %s", data)
                return None
            return {"run_id": run_id, "dataset_id": dataset_id}
    except ApifyHardLimitExceeded:
        raise
    except Exception as error:
        logger.warning("Apify actor start error for '%s': %s", actor_id, error)
        return None


async def _wait_for_run(session: aiohttp.ClientSession, api_key: str, run_id: str) -> str:
    endpoint = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    deadline = asyncio.get_running_loop().time() + RUN_ASYNC_TIMEOUT_SECONDS

    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(RUN_POLL_INTERVAL_SECONDS)
        try:
            async with session.get(
                endpoint,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status >= 400:
                    logger.warning("Apify run status failed (%s): %s", response.status, await response.text())
                    return "FAILED"
                payload = await response.json(content_type=None)
        except Exception as error:
            logger.warning("Apify run status error for '%s': %s", run_id, error)
            return "FAILED"

        status = ((payload.get("data") or {}).get("status") or "").upper()
        if status == "SUCCEEDED":
            return status
        if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
            return status

    return "TIMED-OUT"


async def _fetch_dataset_items(
    session: aiohttp.ClientSession,
    api_key: str,
    dataset_id: str,
    limit: int,
) -> List[Dict[str, Any]]:
    endpoint = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items"
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "limit": max(limit, 10),
        "clean": "1",
        "format": "json",
    }

    try:
        async with session.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status >= 400:
                logger.warning("Apify dataset fetch failed (%s): %s", response.status, await response.text())
                return []
            payload = await response.json(content_type=None)
            return payload if isinstance(payload, list) else []
    except Exception as error:
        logger.warning("Apify dataset fetch error for '%s': %s", dataset_id, error)
        return []


async def _run_legacy_dataset_items(
    session: aiohttp.ClientSession,
    actor_id: str,
    api_key: str,
    search_url: str,
    max_pages: int,
    limit: int,
) -> List[Dict[str, Any]]:
    run_info = await _start_actor_run(
        session=session,
        actor_id=actor_id,
        api_key=api_key,
        search_url=search_url,
        max_pages=max_pages,
        limit=limit,
    )
    if not run_info:
        return []

    status = await _wait_for_run(
        session=session,
        api_key=api_key,
        run_id=run_info["run_id"],
    )
    if status not in {"SUCCEEDED", "ABORTED"}:
        logger.warning("Apify legacy actor run ended with status %s for actor '%s'", status, actor_id)
        return []

    return await _fetch_dataset_items(
        session=session,
        api_key=api_key,
        dataset_id=run_info["dataset_id"],
        limit=max(limit, 10),
    )


async def _collect_actor_items(
    session: aiohttp.ClientSession,
    actor_id: str,
    api_key: str,
    search_url: str,
    max_pages: int,
    limit: int,
    preferred_endpoint: str,
) -> Tuple[List[Dict[str, Any]], int]:
    attempts = 0
    for candidate_actor_id in _candidate_actor_refs(actor_id):
        attempts += 1
        items = await _run_sync_dataset_items(
            session=session,
            actor_id=candidate_actor_id,
            api_key=api_key,
            search_url=search_url,
            max_pages=max_pages,
            limit=limit,
            preferred_endpoint=preferred_endpoint,
        )
        if items:
            return items, attempts

        attempts += 1
        items = await _run_legacy_dataset_items(
            session=session,
            actor_id=candidate_actor_id,
            api_key=api_key,
            search_url=search_url,
            max_pages=max_pages,
            limit=limit,
        )
        if items:
            logger.info("Apify legacy fallback succeeded for actor '%s'.", candidate_actor_id)
            return items, attempts

    return [], attempts


def _merge_raw_items(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for item in group or []:
            url = ((item.get("item_offered") or {}).get("url") or item.get("url") or "").strip()
            title = (item.get("name") or item.get("title") or "").strip().lower()
            key = (url, title)
            if not url or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def _empty_bundle(query: str) -> Dict[str, Any]:
    return {
        "results": [],
        "winner": None,
        "status": "empty",
        "meta": {
            "input_query": query,
            "pages_used": DEFAULT_MAX_PAGES,
            "validation_calls": 0,
            "total_actor_calls": 0,
            "cost_mode": "optimized",
            "best_confidence": 0.0,
        },
    }


def _slice_bundle(bundle: Dict[str, Any], limit: int) -> Dict[str, Any]:
    cloned = copy.deepcopy(bundle)
    cloned["results"] = cloned.get("results", [])[:limit]
    winner = cloned.get("winner")
    if winner:
        cloned["winner"] = winner
    return cloned


async def search_apify_mercadolivre_bundle(
    query: str,
    limit: int = 5,
    country: str = "BR",
) -> Dict[str, Any]:
    settings = get_settings()
    if not settings.APIFY_API_KEY:
        return _empty_bundle(query)

    query_spec = _canonicalize_query(query)
    if not query_spec["normalized"]:
        return _empty_bundle(query)

    cache_hit = _APIFY_QUERY_CACHE.get(query_spec["cache_key"])
    if cache_hit and (time.time() - cache_hit[0]) < CACHE_TTL_SECONDS:
        return _slice_bundle(cache_hit[1], limit)

    variants = _build_query_variants(query_spec)
    raw_items: List[Dict[str, Any]] = []
    actor_calls = 0
    pages_used = DEFAULT_MAX_PAGES
    used_query = variants[0] if variants else query_spec["raw"]
    fetch_limit = max(limit * 4, 12)
    ranked_candidates: List[Dict[str, Any]] = []
    discarded: List[Dict[str, Any]] = []

    timeout = aiohttp.ClientTimeout(total=RUN_ASYNC_TIMEOUT_SECONDS + 30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if variants:
                used_query = variants[0]
                candidate_items, attempts = await _collect_actor_items(
                    session=session,
                    actor_id=settings.APIFY_ML_ACTOR_ID,
                    api_key=settings.APIFY_API_KEY,
                    search_url=_build_search_url(used_query, country=country),
                    max_pages=DEFAULT_MAX_PAGES,
                    limit=fetch_limit,
                    preferred_endpoint=settings.APIFY_PREFERRED_ENDPOINT,
                )
                actor_calls += attempts
                raw_items = candidate_items

            normalized_offers = [offer for item in raw_items if (offer := _normalize_offer(item))]
            ranked_candidates, discarded = _rank_candidates(query_spec, normalized_offers)

            best_confidence = float(ranked_candidates[0].get("confidence", 0) or 0) if ranked_candidates else 0.0
            if (not ranked_candidates or best_confidence < VALIDATE_TOP1_THRESHOLD) and len(variants) > 1:
                used_query = variants[1]
                variant_items, attempts = await _collect_actor_items(
                    session=session,
                    actor_id=settings.APIFY_ML_ACTOR_ID,
                    api_key=settings.APIFY_API_KEY,
                    search_url=_build_search_url(used_query, country=country),
                    max_pages=DEFAULT_MAX_PAGES,
                    limit=fetch_limit,
                    preferred_endpoint=settings.APIFY_PREFERRED_ENDPOINT,
                )
                actor_calls += attempts
                if variant_items:
                    raw_items = _merge_raw_items(raw_items, variant_items)
                    normalized_offers = [offer for item in raw_items if (offer := _normalize_offer(item))]
                    ranked_candidates, discarded = _rank_candidates(query_spec, normalized_offers)
                    best_confidence = float(ranked_candidates[0].get("confidence", 0) or 0) if ranked_candidates else 0.0

            if (not ranked_candidates or best_confidence < VALIDATE_TOP2_THRESHOLD) and FALLBACK_MAX_PAGES > DEFAULT_MAX_PAGES:
                extra_items, attempts = await _collect_actor_items(
                    session=session,
                    actor_id=settings.APIFY_ML_ACTOR_ID,
                    api_key=settings.APIFY_API_KEY,
                    search_url=_build_search_url(used_query, country=country),
                    max_pages=FALLBACK_MAX_PAGES,
                    limit=max(fetch_limit, 20),
                    preferred_endpoint=settings.APIFY_PREFERRED_ENDPOINT,
                )
                actor_calls += attempts
                if extra_items:
                    pages_used = FALLBACK_MAX_PAGES
                    merged_items = _merge_raw_items(raw_items, extra_items)
                    normalized_offers = [offer for item in merged_items if (offer := _normalize_offer(item))]
                    ranked_candidates, discarded = _rank_candidates(query_spec, normalized_offers)
    except ApifyHardLimitExceeded as error:
        logger.warning("Apify hard limit reached for '%s': %s", query, error)
        return _empty_bundle(query)
    except Exception as error:
        logger.error("Apify search failed for '%s': %s", query, error)
        return _empty_bundle(query)

    winner, ranked_candidates, validation_calls, status = await _apply_conditional_validation(query_spec, ranked_candidates)
    if winner:
        winner["discarded_candidates"] = discarded[:5]

    ordered_results: List[Dict[str, Any]] = []
    winner_url = (winner or {}).get("url")
    if winner_url:
        ordered_results.append(winner)
    for candidate in ranked_candidates:
        if candidate.get("url") == winner_url:
            continue
        ordered_results.append(candidate)

    best_confidence = float(winner.get("confidence", 0) or 0) if winner else 0.0
    bundle = {
        "results": ordered_results[:limit],
        "winner": winner,
        "status": status,
        "meta": {
            "input_query": query,
            "canonical_query": query_spec["raw"],
            "pages_used": pages_used,
            "validation_calls": validation_calls,
            "total_actor_calls": actor_calls,
            "cost_mode": "optimized",
            "best_confidence": round(best_confidence, 2),
            "used_query": used_query,
        },
    }
    _APIFY_QUERY_CACHE[query_spec["cache_key"]] = (time.time(), copy.deepcopy(bundle))
    logger.info(
        "Apify-first search for '%s': %s offers, confidence=%s, actor_calls=%s, pages=%s, status=%s",
        query,
        len(bundle["results"]),
        bundle["meta"]["best_confidence"],
        actor_calls,
        pages_used,
        status,
    )
    return _slice_bundle(bundle, limit)


async def search_apify_mercadolivre(
    query: str,
    limit: int = 5,
    country: str = "BR",
) -> List[Dict[str, Any]]:
    bundle = await search_apify_mercadolivre_bundle(query=query, limit=limit, country=country)
    return bundle.get("results", [])
