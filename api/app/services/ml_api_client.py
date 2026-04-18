"""
Mercado Livre Search Client.

Observed behavior for this application:
- OAuth refresh_token flow works correctly.
- /products/search is available and useful for catalog matching.
- /sites/MLB/search and item competition endpoints return 403.

Because of that, this client uses the official catalog API as the primary
matching layer and only falls back to public HTML for listing and price
extraction when the official APIs do not expose the needed data.
"""

import os
import json
import time
import logging
import asyncio
import re
import base64
import hashlib
import hmac
import secrets
import unicodedata
import aiohttp
from typing import List, Dict, Optional, Any
from pathlib import Path
from urllib.parse import urlencode

from app.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = Path(__file__).parent.parent.parent / ".ml_token_cache.json"
STOP_WORDS = {
    "de", "da", "do", "das", "dos", "com", "sem", "para", "por", "em", "no", "na",
    "e", "ou", "um", "uma", "tipo", "conforme", "especificado", "nominal", "produto",
    "servico", "rigido", "rigida",
    "item", "itens", "lote", "lotes",
}
STRICT_MEASURE_TERMS = {
    "tubo",
    "cano",
    "broca",
    "barra",
    "abracadeira",
    "madeira",
    "tabua",
    "tabela",
    "ripa",
    "sarrafo",
    "tanque",
    "reservatorio",
    "cisterna",
    "caixa",
}
STRICT_COMPARISON_UNITS = {"mm", "cm", "m", "pol", "l", "kg", "g"}
INTERNATIONAL_MARKERS = {
    "compra internacional", "envio internacional", "produto internacional", "do exterior",
    "importado", "internacional",
}
FRACTIONAL_SIZE_RE = re.compile(
    r'(?<!\d)(?P<whole>\d)\.\s*(?P<fraction>\d/\d)(?=(?:\s*(?:pol|")|\b))'
)


def _normalize_text(value: str) -> str:
    value = FRACTIONAL_SIZE_RE.sub(r"\g<whole> \g<fraction>", value or "")
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&amp;", "&")
    text = (
        text.replace("d'agua", "dagua")
        .replace("d agua", "dagua")
        .replace("dagua", "dagua")
    )
    text = re.sub(r"[^a-z0-9/\".,%-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(value: str) -> set[str]:
    return {
        token.strip('.,%"-')
        for token in _normalize_text(value).split()
        if ((len(token.strip('.,%"-')) >= 3) or (token.strip('.,%"-').isdigit() and len(token.strip('.,%"-')) >= 2))
        and token.strip('.,%"-') not in STOP_WORDS
    }


def _extract_measure_map(value: str) -> dict[str, set[str]]:
    normalized = (
        _normalize_text(value)
        .replace("litros", "l")
        .replace("litro", "l")
        .replace("polegadas", "pol")
        .replace("polegada", "pol")
    )
    pattern = re.compile(
        r'(?:\b\d+\s+\d/\d\s*(?:mm|cm|m|kg|g|l|lt|pol|")|\b\d+(?:[.,/]\d+)?\s*(?:mm|cm|m|kg|g|l|lt|pol|"))'
    )
    measures: dict[str, set[str]] = {}
    for match in pattern.finditer(normalized):
        compact = match.group(0).replace('"', 'pol')
        compact = re.sub(r"(\d+)\s+(\d/\d)", r"\1-\2", compact)
        compact = compact.replace(" ", "")
        unit_match = re.search(r"(mm|cm|m|kg|g|lt|l|pol)$", compact)
        if not unit_match:
            continue
        unit = unit_match.group(1)
        if unit == "lt":
            unit = "l"
        amount = _normalize_measure_amount(compact[: -len(unit)])
        if not amount:
            continue
        measures.setdefault(unit, set()).add(amount)
    return measures


def _normalize_measure_amount(value: str) -> str:
    if not value:
        return ""
    if "-" in value and "/" in value:
        return value

    normalized = value.replace(",", ".")
    if normalized.count(".") == 1:
        whole, fraction = normalized.split(".", 1)
        if len(fraction) == 3 and whole.isdigit():
            normalized = f"{whole}{fraction}"

    if "." in normalized and re.fullmatch(r"\d+(?:\.\d+)?", normalized):
        normalized = normalized.rstrip("0").rstrip(".")

    return normalized


def _extract_measures(value: str) -> set[str]:
    return {
        f"{amount}{unit}"
        for unit, amounts in _extract_measure_map(value).items()
        for amount in amounts
    }


def _sanitize_search_query(value: str) -> str:
    value = FRACTIONAL_SIZE_RE.sub(r"\g<whole> \g<fraction>", value or "")
    cleaned = re.sub(r"^\s*(item|lote)\s*\d+\s*[-:]\s*", "", value or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(item|lote)\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:item|itens|lote|lotes|codigo|c[oÃ³]digo|n[Âºo])\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:")
    return cleaned or (value or "").strip()


def _normalize_numeric_token(value: str) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    mixed_fraction = re.fullmatch(r"(\d+)\s+(\d/\d+)", compact)
    if mixed_fraction:
        return f"{_normalize_measure_amount(mixed_fraction.group(1))}-{mixed_fraction.group(2)}"

    return _normalize_measure_amount(compact.replace(" ", ""))


def _extract_numeric_tokens(value: str) -> list[str]:
    normalized = _normalize_text(value)
    found: list[str] = []

    def add(token: str) -> None:
        if token and token not in found:
            found.append(token)

    for mixed_fraction in re.finditer(r"\b\d+\s+\d/\d+\b", normalized):
        add(_normalize_numeric_token(mixed_fraction.group(0)))

    cleaned = re.sub(r"\b\d+\s+\d/\d+\b", " ", normalized)
    for token in re.finditer(r"\b\d+(?:[.,]\d+)?(?:/\d+)?\b", cleaned):
        add(_normalize_numeric_token(token.group(0)))

    for amounts in _extract_measure_map(value).values():
        for amount in amounts:
            add(amount)

    return found


def _extract_x_dimensions(value: str) -> list[str]:
    normalized = _normalize_text(value)
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?(?:\s+\d/\d+)?)\s*x\s*(\d+(?:[.,]\d+)?(?:\s+\d/\d+)?)(?:\s*x\s*(\d+(?:[.,]\d+)?(?:\s+\d/\d+)?))?",
        normalized,
    )
    if not match:
        return []

    return [
        _normalize_numeric_token(group)
        for group in match.groups()
        if group
    ]


def _slugify_search_query(value: str) -> str:
    normalized = _normalize_text(_sanitize_search_query(value))
    normalized = re.sub(r"[^a-z0-9\s-]+", " ", normalized)
    return re.sub(r"[\s-]+", "-", normalized).strip("-")


def _is_international_offer(offer: Dict[str, Any]) -> bool:
    normalized_title = _normalize_text(offer.get("title", ""))
    normalized_url = _normalize_text(offer.get("url", ""))
    raw_markers = " ".join(
        str(value)
        for value in [
            offer.get("international_delivery_mode", ""),
            " ".join(offer.get("shipping_tags", []) or []),
            " ".join(offer.get("tags", []) or []),
            offer.get("logistic_type", ""),
        ]
        if value
    )
    normalized_markers = _normalize_text(raw_markers)
    return any(
        marker in normalized_title or marker in normalized_url or marker in normalized_markers
        for marker in INTERNATIONAL_MARKERS
    )


def _is_water_storage_query(normalized_query: str, query_tokens: set[str]) -> bool:
    if any(term in normalized_query for term in {"reservatorio", "cisterna", "tanque"}):
        return True

    has_caixa = "caixa" in query_tokens or "caixa" in normalized_query
    has_water = bool({"agua", "dagua", "gua"}.intersection(query_tokens)) or any(
        marker in normalized_query for marker in {"caixa dagua", "caixa d agua", "caixa d gua"}
    )
    return has_caixa and has_water


def _is_strict_measure_query(normalized_query: str) -> bool:
    return any(term in normalized_query for term in STRICT_MEASURE_TERMS)


def _build_catalog_queries(query: str) -> list[str]:
    original = _sanitize_search_query(query)
    normalized = _normalize_text(original)
    normalized = normalized.replace('"', ' pol ')
    normalized = re.sub(r"[^a-z0-9/%.\- ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    measure_map = _extract_measure_map(original)
    liters = sorted(measure_map.get("l", set()), key=len)
    millimeters = sorted(measure_map.get("mm", set()), key=len)
    meters = sorted(measure_map.get("m", set()), key=len)

    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = re.sub(r"\s+", " ", (candidate or "")).strip(" -")
        if not candidate:
            return
        key = _normalize_text(candidate)
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    add(original)
    add(normalized)
    add(re.split(r";", original, maxsplit=1)[0])
    add(re.split(r",", original, maxsplit=1)[0])

    if _is_water_storage_query(normalized, _tokenize(normalized)) and liters:
        capacity = liters[-1]
        add(f"caixa dagua {capacity} litros")
        add(f"tanque polietileno {capacity} litros")
        add(f"tanque {capacity} litros")

    if "tubo" in normalized and millimeters:
        diameter = millimeters[-1]
        add(f"tubo pvc esgoto {diameter}mm")
        add(f"tubo pvc {diameter}mm")
        if meters:
            add(f"tubo pvc esgoto {diameter}mm {meters[-1]}m")

    if "bracadeira" in normalized or "abracadeira" in normalized:
        add(normalized.replace(" pol", ""))
        if "bracadeira" in normalized:
            add(normalized.replace("bracadeira", "abracadeira").replace(" pol", ""))

    return candidates


def _build_public_site_queries(query: str) -> list[str]:
    original = _sanitize_search_query(query)
    normalized = _normalize_text(original)
    measure_map = _extract_measure_map(original)
    x_dimensions = _extract_x_dimensions(original)

    candidates: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        candidate = re.sub(r"\s+", " ", (candidate or "")).strip(" -")
        if not candidate:
            return
        key = _normalize_text(candidate)
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    for candidate in _build_catalog_queries(original):
        add(candidate)

    add(re.split(r";", original, maxsplit=1)[0])
    add(re.split(r",", original, maxsplit=1)[0])

    if "adaptador" in normalized and "flange" in normalized:
        if x_dimensions:
            formatted = " x ".join(dimension.replace("-", " ") for dimension in x_dimensions[:2])
            add(f"adaptador flange caixa dagua {formatted}")
            add(f"adaptador flange {x_dimensions[0]}")
        add("adaptador flange caixa dagua")

    if "anel de vedacao" in normalized and "vaso" in normalized:
        add("anel vedacao com guia vaso sanitario")

    if "assento sanitario" in normalized:
        add("assento sanitario branco")
        if "almofad" in normalized:
            add("assento sanitario almofadado branco")

    if "caixa de descarga" in normalized:
        add("caixa de descarga branca")
        if "sem engate" in normalized:
            add("caixa de descarga sem engate branca")

    if "caixa sifonada" in normalized:
        add("caixa sifonada")
        if x_dimensions:
            add(f"caixa sifonada {' x '.join(dimension.replace('-', ' ') for dimension in x_dimensions)}")

    if "engate flexivel" in normalized:
        centimeters = sorted(measure_map.get("cm", set()), key=len)
        if centimeters:
            add(f"engate flexivel {centimeters[-1]}cm")

    if "cloro" in normalized and "10 em 1" in normalized:
        kilos = sorted(measure_map.get("kg", set()), key=len)
        if kilos:
            add(f"cloro 10 em 1 {kilos[-1]}kg")

    return candidates


def _blocked_terms_for_query(query: str) -> set[str]:
    normalized = _normalize_text(query)
    query_tokens = _tokenize(normalized)
    blocked: set[str] = set()

    if "tubo" in normalized or "cano" in normalized:
        blocked.update({"luva", "tampao", "joelho", "te", "adaptador", "conexao", "anel"})

    if "broca" in normalized and "kit" not in normalized and "jogo" not in normalized:
        blocked.update({"kit", "jogo", "serra", "serra copo"})

    if "aco rapido" in normalized or "hss" in normalized:
        blocked.update({"concreto", "madeira", "widea", "serra", "serra copo"})

    if "arame" in normalized and "farpado" not in normalized:
        blocked.add("farpado")

    if "arame" in normalized and "ovalado" not in normalized:
        blocked.add("ovalado")

    if _is_water_storage_query(normalized, query_tokens):
        blocked.update(
            {
                "tampa",
                "tinta",
                "epson",
                "pulse",
                "radiador",
                "expansao",
                "combustivel",
                "gasolina",
                "moto",
                "carro",
                "automotivo",
            }
        )

    if "tanque" in normalized and "tinta" not in normalized:
        blocked.update({"tinta", "epson", "pulse", "expansao"})

    if "assento sanitario" in normalized:
        blocked.update({"parafuso", "fixacao", "bidet", "acessorio"})

    if "caixa de descarga" in normalized:
        blocked.update({"reparo", "mecanismo", "boia", "valvula"})
        if "engate" not in normalized:
            blocked.add("engate")

    if "caixa sifonada" in normalized:
        blocked.update({"sifonagem", "refil"})

    return blocked


def _required_anchor_terms(query: str) -> set[str]:
    normalized = _normalize_text(query)
    query_tokens = _tokenize(normalized)
    anchors: set[str] = set()

    if "broca" in normalized:
        anchors.add("broca")
    if "aco rapido" in normalized or "hss" in normalized:
        anchors.update({"aco", "rapido", "hss"})
    if "concreto" in normalized:
        anchors.add("concreto")
    if "tubo" in normalized or "cano" in normalized:
        anchors.update({"tubo", "cano"})
    if "arruela" in normalized:
        anchors.add("arruela")
    if "arame" in normalized:
        anchors.add("arame")
    if "galvanizado" in normalized:
        anchors.add("galvanizado")
    if "abracadeira" in normalized or "bracadeira" in normalized:
        anchors.add("abracadeira")
    if "inox" in normalized:
        anchors.add("inox")
    if "barra rosque" in normalized:
        anchors.add("barra")
    if "reservatorio" in normalized:
        anchors.add("reservatorio")
    if "cisterna" in normalized:
        anchors.add("cisterna")
    if "tanque" in normalized:
        anchors.add("tanque")
    if _is_water_storage_query(normalized, query_tokens):
        anchors.add("caixa")
    if "madeira" in normalized:
        anchors.add("madeira")
    if "tabua" in normalized or "tÃ¡bua" in normalized:
        anchors.add("tabua")
    if "ripa" in normalized:
        anchors.add("ripa")
    if "sarrafo" in normalized:
        anchors.add("sarrafo")
    if "assento sanitario" in normalized:
        anchors.update({"assento", "sanitario"})
    if "caixa de descarga" in normalized:
        anchors.update({"caixa", "descarga"})
    if "caixa sifonada" in normalized:
        anchors.update({"caixa", "sifonada"})
    if "engate flexivel" in normalized:
        anchors.update({"engate", "flexivel"})
    if "adaptador" in normalized and "flange" in normalized:
        anchors.update({"adaptador", "flange"})

    return anchors


def _title_indicates_package(normalized_title: str) -> bool:
    if re.search(r"\b(?:kit|jogo|conjunto|combo|pacote|pack|cartela|blister|sortido)\b", normalized_title):
        return True
    if re.search(r"\b(?:caixa|cx)\s+com\b", normalized_title):
        return True
    if re.search(r"\b(?:com|c/)\s*\d+\s*(?:pecas|unid|unidades)\b", normalized_title):
        return True
    return bool(re.search(r"\b\d+\s*(?:pecas|unid|unidades)\b", normalized_title))


def _query_allows_package(normalized_query: str, query_tokens: set[str]) -> bool:
    if {"kit", "jogo", "conjunto", "combo", "pacote", "pack", "cartela", "blister"}.intersection(query_tokens):
        return True
    if re.search(r"\b(?:saco|sc|embalagem|fardo)\b", normalized_query):
        return True
    return bool(re.search(r"\bcaixa\s+com\b", normalized_query))


def _is_offer_compatible(query: str, title: str, catalog_titles: Optional[List[str]] = None) -> bool:
    normalized_query = _normalize_text(_sanitize_search_query(query))
    normalized_title = _normalize_text(title)
    if not normalized_title:
        return False

    query_tokens = _tokenize(normalized_query)
    title_tokens = _tokenize(normalized_title)
    overlap = len(query_tokens.intersection(title_tokens))
    water_storage_query = _is_water_storage_query(normalized_query, query_tokens)
    query_x_dimensions = _extract_x_dimensions(normalized_query)
    special_x_dimension_query = bool(query_x_dimensions) and "adaptador" in normalized_query and "flange" in normalized_query

    if _title_indicates_package(normalized_title) and not _query_allows_package(normalized_query, query_tokens):
        return False

    if water_storage_query and any(
        normalized_title.startswith(prefix) for prefix in {"tampa ", "boia ", "torneira ", "registro "}
    ):
        return False

    query_measure_map = _extract_measure_map(normalized_query)
    title_measure_map = _extract_measure_map(normalized_title)
    query_measures = {
        f"{amount}{unit}" for unit, amounts in query_measure_map.items() for amount in amounts
    }
    title_measures = {
        f"{amount}{unit}" for unit, amounts in title_measure_map.items() for amount in amounts
    }
    if not special_x_dimension_query and query_measures and title_measures and query_measures.isdisjoint(title_measures):
        shared_units = set(query_measure_map).intersection(title_measure_map)
        if not shared_units:
            return False
        if any(query_measure_map[unit].isdisjoint(title_measure_map[unit]) for unit in shared_units):
            return False
    if not special_x_dimension_query and query_measures and not title_measures and _is_strict_measure_query(normalized_query):
        return False
    if not special_x_dimension_query and _is_strict_measure_query(normalized_query):
        for unit, query_values in query_measure_map.items():
            if unit not in STRICT_COMPARISON_UNITS:
                continue
            title_values = title_measure_map.get(unit)
            if not title_values or query_values.isdisjoint(title_values):
                return False
    if not special_x_dimension_query and query_measures and title_measures:
        for unit, query_values in query_measure_map.items():
            title_values = title_measure_map.get(unit)
            if title_values and query_values.isdisjoint(title_values):
                return False
    if water_storage_query and any(
        accessory in title_tokens for accessory in {"tampa", "boia", "torneira", "registro"}
    ) and not any(accessory in query_tokens for accessory in {"tampa", "boia", "torneira", "registro"}):
        return False

    for blocked_term in _blocked_terms_for_query(normalized_query):
        if blocked_term in normalized_title and blocked_term not in normalized_query:
            return False

    if "inox" in normalized_query and "inox" not in normalized_title:
        return False

    if (
        any(color in normalized_query for color in {"branco", "branca"})
        and any(color in normalized_title for color in {"preto", "preta", "black"})
    ):
        return False

    if "assento sanitario" in normalized_query:
        if "assento" not in title_tokens or not any(token.startswith("sanit") for token in title_tokens):
            return False
        if any(term in normalized_title for term in {"parafuso", "fixacao", "bidet", "acessorio"}):
            return False
        if "almofad" in normalized_query and not any(
            term in normalized_title for term in {"almofad", "acolcho", "estofad"}
        ):
            return False

    if "caixa de descarga" in normalized_query:
        if "caixa" not in title_tokens or "descarga" not in title_tokens:
            return False
        if any(term in normalized_title for term in {"reparo", "mecanismo", "boia", "valvula"}):
            return False
        if (
            "sem engate" in normalized_query
            and re.search(r"\bengate\b", normalized_title)
            and "sem engate" not in normalized_title
        ):
            return False

    if "caixa sifonada" in normalized_query:
        if "caixa" not in title_tokens or not any(term in normalized_title for term in {"sifon", "sifonada"}):
            return False
        if any(term in normalized_title for term in {"sifonagem", "refil"}):
            return False
        query_dimensions = _extract_x_dimensions(normalized_query)
        if query_dimensions:
            title_numbers = set(_extract_numeric_tokens(normalized_title))
            for dimension in query_dimensions[:2]:
                if dimension not in title_numbers:
                    return False

    if "engate flexivel" in normalized_query:
        if "engate" not in title_tokens or "flexivel" not in normalized_title:
            return False

    if "adaptador" in normalized_query and "flange" in normalized_query:
        if "adaptador" not in title_tokens or "flange" not in title_tokens:
            return False
        if query_x_dimensions:
            title_numbers = set(_extract_numeric_tokens(normalized_title))
            if query_x_dimensions[0] not in title_numbers:
                return False

    if "cloro" in normalized_query and "10 em 1" in normalized_query and "10 em 1" not in normalized_title:
        return False

    anchors = _required_anchor_terms(normalized_query)
    if anchors and anchors.isdisjoint(title_tokens):
        return False

    if "galvanizado" in normalized_query and "galvanizado" not in normalized_title:
        return False

    if "arame" in normalized_query:
        query_numbers = {token for token in query_tokens if token.isdigit()}
        title_numbers = {token for token in title_tokens if token.isdigit()}
        if query_numbers and query_numbers.isdisjoint(title_numbers):
            return False

    if ("aco rapido" in normalized_query or "hss" in normalized_query) and not (
        "aco rapido" in normalized_title or "hss" in normalized_title
    ):
        return False

    if water_storage_query and "caixa" in query_tokens and not (
        ("caixa" in title_tokens and bool({"agua", "dagua", "gua"}.intersection(title_tokens)))
        or "caixa dagua" in normalized_title
        or "caixa d agua" in normalized_title
    ):
        return False

    if "reservatorio" in normalized_query and "tanque" not in normalized_query and "reservatorio" not in title_tokens:
        return False

    if "cisterna" in normalized_query and "cisterna" not in title_tokens:
        return False

    catalog_titles = catalog_titles or []
    catalog_token_sets = [_tokenize(candidate) for candidate in catalog_titles if candidate]
    catalog_overlap = max(
        (len(title_tokens.intersection(candidate_tokens)) for candidate_tokens in catalog_token_sets),
        default=0,
    )
    if catalog_titles and catalog_overlap >= 2 and overlap >= 1:
        return True

    if len(query_tokens) <= 2:
        return overlap >= 1

    return overlap >= 2


def _offer_score(query: str, title: str, catalog_titles: Optional[List[str]] = None) -> int:
    normalized_query = _normalize_text(_sanitize_search_query(query))
    normalized_title = _normalize_text(title)
    query_tokens = _tokenize(normalized_query)
    title_tokens = _tokenize(normalized_title)

    score = len(query_tokens.intersection(title_tokens))

    query_measures = _extract_measures(normalized_query)
    title_measures = _extract_measures(normalized_title)
    if query_measures and title_measures and not query_measures.isdisjoint(title_measures):
        score += 3

    anchors = _required_anchor_terms(normalized_query)
    score += len(anchors.intersection(title_tokens)) * 2

    if normalized_query and normalized_query in normalized_title:
        score += 4

    catalog_titles = catalog_titles or []
    for catalog_title in catalog_titles:
        score += min(len(title_tokens.intersection(_tokenize(catalog_title))), 3)

    return score


def _deduplicate_offers(offers: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    unique_offers: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for offer in offers:
        key = offer.get("url") or f"{_normalize_text(offer.get('title', ''))}:{offer.get('price')}"
        if key in seen:
            continue
        seen.add(key)
        unique_offers.append(offer)
        if len(unique_offers) >= limit:
            break

    return unique_offers


class MLAuthManager:
    """Manages OAuth 2.0 tokens for Mercado Livre API."""

    AUTH_URL = "https://api.mercadolibre.com/oauth/token"
    AUTHORIZE_URL = "https://auth.mercadolivre.com.br/authorization"

    def __init__(self, client_id: str = None, client_secret: str = None):
        settings = get_settings()
        self.client_id = client_id or settings.ML_CLIENT_ID or os.getenv("ML_CLIENT_ID", "")
        self.client_secret = client_secret or settings.ML_CLIENT_SECRET or os.getenv("ML_CLIENT_SECRET", "")
        self.redirect_uri = settings.ML_REDIRECT_URI or os.getenv("ML_REDIRECT_URI", "")
        self.state_secret = settings.ML_OAUTH_STATE_SECRET or settings.SECRET_KEY or os.getenv("SECRET_KEY", "")
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at: float = 0
        self._token_type: str = "Bearer"
        self._scope: str = ""
        self._user_id: Optional[int] = None
        self._load_cached_token()

    def _load_cached_token(self):
        settings = get_settings()
        try:
            if TOKEN_CACHE_PATH.exists():
                data = json.loads(TOKEN_CACHE_PATH.read_text())
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._expires_at = data.get("expires_at", 0)
                self._token_type = data.get("token_type", "Bearer")
                self._scope = data.get("scope", "")
                self._user_id = data.get("user_id")
        except Exception as e:
            logger.warning(f"Could not load ML token cache: {e}")

        # The Mercado Livre refresh_token rotates on every refresh.
        # Environment values are treated only as bootstrap values so the
        # latest cached token pair is not overwritten by stale env data.
        if settings.ML_ACCESS_TOKEN and not self._access_token:
            self._access_token = settings.ML_ACCESS_TOKEN
        if settings.ML_REFRESH_TOKEN and not self._refresh_token:
            self._refresh_token = settings.ML_REFRESH_TOKEN
        if settings.ML_TOKEN_EXPIRES_AT and not self._expires_at:
            self._expires_at = float(settings.ML_TOKEN_EXPIRES_AT)
        if settings.ML_TOKEN_SCOPE and not self._scope:
            self._scope = settings.ML_TOKEN_SCOPE
        if settings.ML_TOKEN_USER_ID and not self._user_id:
            self._user_id = settings.ML_TOKEN_USER_ID

    def _save_cached_token(self):
        try:
            TOKEN_CACHE_PATH.write_text(json.dumps({
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._expires_at,
                "token_type": self._token_type,
                "scope": self._scope,
                "user_id": self._user_id,
            }))
        except Exception as e:
            logger.warning(f"Could not save ML token cache: {e}")

    @property
    def is_token_valid(self) -> bool:
        return bool(self._access_token and self._expires_at > time.time() + 60)

    @property
    def is_authorized(self) -> bool:
        return bool(self._refresh_token or self.is_token_valid)

    def seed_tokens(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: int = 21600,
        scope: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        if access_token:
            self._access_token = access_token
            self._expires_at = time.time() + expires_in
        if refresh_token:
            self._refresh_token = refresh_token
        if scope:
            self._scope = scope
        if user_id is not None:
            self._user_id = user_id
        self._save_cached_token()

    def get_auth_status(self) -> Dict[str, Any]:
        expires_in = max(0, int(self._expires_at - time.time())) if self._expires_at else 0
        return {
            "authorized": self.is_authorized,
            "token_valid": self.is_token_valid,
            "refresh_token_present": bool(self._refresh_token),
            "expires_in_seconds": expires_in,
            "redirect_uri": self.redirect_uri,
            "client_id_configured": bool(self.client_id),
            "client_secret_configured": bool(self.client_secret),
            "user_id": self._user_id,
            "scope": self._scope,
        }

    def generate_state(self, ttl_seconds: int = 900) -> str:
        nonce = secrets.token_urlsafe(16)
        expires_at = int(time.time()) + ttl_seconds
        payload = f"{nonce}.{expires_at}"
        signature = hmac.new(
            self.state_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        raw = f"{payload}.{signature}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")

    def verify_state(self, state: str) -> bool:
        try:
            padded = state + "=" * (-len(state) % 4)
            raw = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            nonce, expires_at_str, signature = raw.split(".", 2)
            if not nonce:
                return False

            payload = f"{nonce}.{expires_at_str}"
            expected_signature = hmac.new(
                self.state_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                return False

            return int(expires_at_str) >= int(time.time())
        except Exception:
            return False

    def get_authorization_url(self, state: Optional[str] = None) -> str:
        if not self.client_id:
            raise ValueError("ML_CLIENT_ID nÃ£o configurado")
        if not self.redirect_uri:
            raise ValueError("ML_REDIRECT_URI nÃ£o configurado")

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state or self.generate_state(),
        }
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"

    async def get_access_token(self) -> Optional[str]:
        if self.is_token_valid:
            return self._access_token

        if self._refresh_token:
            try:
                return await self._refresh_access_token()
            except Exception as error:
                logger.warning(f"ML refresh failed, new authorization is required: {error}")

        logger.warning("Mercado Livre OAuth ainda nÃ£o autorizado. Gere o link em /api/integrations/mercadolivre/authorize")
        return None

    async def exchange_authorization_code(self, code: str) -> Dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise ValueError("Credenciais do Mercado Livre nÃ£o configuradas")
        if not self.redirect_uri:
            raise ValueError("ML_REDIRECT_URI nÃ£o configurado")

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.AUTH_URL, data=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise Exception(f"ML authorization_code failed ({resp.status}): {data}")

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._expires_at = time.time() + data.get("expires_in", 21600)
        self._token_type = data.get("token_type", "Bearer")
        self._scope = data.get("scope", "")
        self._user_id = data.get("user_id")
        self._save_cached_token()

        logger.info(f"ML token obtained via authorization_code (expires in {data.get('expires_in', 0)}s)")
        return data

    async def _refresh_access_token(self) -> Optional[str]:
        async with aiohttp.ClientSession() as session:
            payload = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
            }
            async with session.post(self.AUTH_URL, data=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise Exception(f"ML refresh failed ({resp.status}): {data}")

                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                self._expires_at = time.time() + data.get("expires_in", 21600)
                self._token_type = data.get("token_type", self._token_type)
                self._scope = data.get("scope", self._scope)
                self._user_id = data.get("user_id", self._user_id)
                self._save_cached_token()
                logger.info(f"ML token refreshed successfully (expires in {data.get('expires_in', 0)}s)")
                return self._access_token


class MLSearchClient:
    """Searches Mercado Livre using OAuth plus the official catalog API first."""

    API_SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"
    PRODUCT_SEARCH_URL = "https://api.mercadolibre.com/products/search"
    HTML_SEARCH_BASE_URL = "https://lista.mercadolivre.com.br"

    def __init__(self):
        settings = get_settings()
        self.auth = MLAuthManager()
        self._semaphore = asyncio.Semaphore(5)
        self._api_available = True
        self._catalog_api_available = True
        self._official_only = settings.ML_OFFICIAL_ONLY
        self._max_requests_per_search = max(1, int(settings.ML_MAX_REQUESTS_PER_SEARCH))

    def seed_tokens(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        expires_in: int = 21600,
        scope: str = "",
        user_id: Optional[int] = None,
    ) -> None:
        self.auth.seed_tokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scope=scope,
            user_id=user_id,
        )

    def get_authorization_url(self) -> str:
        return self.auth.get_authorization_url()

    def get_auth_status(self) -> Dict[str, Any]:
        status = self.auth.get_auth_status()
        status["search_api_available"] = self._api_available
        status["catalog_api_available"] = self._catalog_api_available
        return status

    async def search_product(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search Mercado Livre using official APIs only when configured."""
        query = _sanitize_search_query(query)
        request_budget = {"remaining": self._max_requests_per_search}
        async with self._semaphore:
            catalog_results = await self.search_catalog_products(
                query,
                limit=max(limit, 8),
                request_budget=request_budget,
            )
            catalog_titles = [item["title"] for item in catalog_results if item.get("title")]

            if self._official_only:
                official_offers = await self._search_via_catalog_items(
                    query=query,
                    catalog_results=catalog_results,
                    limit=limit,
                    request_budget=request_budget,
                )
                if official_offers:
                    logger.info(f"ML official catalog/items: {len(official_offers)} offers for '{query}'")
                else:
                    logger.info(f"ML official catalog/items returned 0 priced offers for '{query}'")
                return official_offers

            if self._api_available:
                results = await self._search_via_api(
                    query=query,
                    limit=max(limit * 2, limit),
                    catalog_titles=catalog_titles,
                    request_budget=request_budget,
                )
                if results:
                    return _deduplicate_offers(results, limit)

            html_offers: List[Dict[str, Any]] = []
            for refined_query in self._build_refined_queries(query, catalog_results):
                html_results = await self._search_via_html(
                    query=refined_query,
                    limit=max(limit * 2, limit),
                    catalog_titles=catalog_titles,
                    original_query=query,
                )
                html_offers.extend(html_results)
                if len(html_offers) >= limit * 3:
                    break

            filtered_html = self._filter_offers_by_context(query, html_offers, catalog_titles)
            if filtered_html:
                logger.info(f"ML HTML fallback: {len(filtered_html)} compatible offers for '{query}'")
            return _deduplicate_offers(filtered_html, limit)

    async def search_catalog_products(
        self,
        query: str,
        limit: int = 10,
        request_budget: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """Use the official catalog endpoint to get normalized product candidates."""
        query = _sanitize_search_query(query)
        aggregated: list[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for candidate_query in _build_catalog_queries(query):
            data = await self._fetch_json(
                url=self.PRODUCT_SEARCH_URL,
                params={
                    "site_id": "MLB",
                    "status": "active",
                    "q": candidate_query,
                    "limit": min(max(limit, 1), 20),
                },
                description=f"ML catalog search for '{candidate_query}'",
                disable_search_api=False,
                request_budget=request_budget,
            )
            if not data:
                continue

            self._catalog_api_available = True
            catalog_results = [
                item for item in self._parse_catalog_results(data, limit)
                if _is_offer_compatible(query, item.get("title", ""), [])
            ]
            for item in catalog_results:
                item_id = item.get("id")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                aggregated.append(item)
                if len(aggregated) >= limit:
                    logger.info(f"ML catalog: {len(aggregated)} candidates for '{query}'")
                    return aggregated[:limit]

        if not aggregated:
            self._catalog_api_available = False
            return []

        logger.info(f"ML catalog: {len(aggregated)} candidates for '{query}'")
        return aggregated[:limit]

    async def search_public_site(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Query Mercado Livre public search pages directly when official APIs do not expose prices."""
        query = _sanitize_search_query(query)
        aggregated: List[Dict[str, Any]] = []

        for candidate_query in _build_public_site_queries(query):
            html_results = await self._search_via_html(
                query=candidate_query,
                limit=max(limit * 2, limit),
                catalog_titles=[],
                original_query=query,
            )
            aggregated.extend(html_results)
            if len(aggregated) >= limit * 4:
                break

        filtered = self._filter_offers_by_context(query, aggregated, [])
        if filtered:
            logger.info(f"ML public site fallback: {len(filtered)} compatible offers for '{query}'")
        return _deduplicate_offers(filtered, limit)

    async def _fetch_public_json(
        self,
        url: str,
        description: str,
        request_budget: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if request_budget is not None:
            if request_budget["remaining"] <= 0:
                logger.warning(f"{description} skipped: ML request budget exhausted")
                return None
            request_budget["remaining"] -= 1

        headers = {"Accept": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"{description} failed ({resp.status}): {body[:240]}")
                        return None
                    return await resp.json()
        except Exception as error:
            logger.error(f"{description} request error: {error}")
            return None

    async def _fetch_product_detail(
        self,
        product_id: str,
        request_budget: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        return await self._fetch_json(
            url=f"https://api.mercadolibre.com/products/{product_id}",
            params={},
            description=f"ML product detail for '{product_id}'",
            disable_search_api=False,
            request_budget=request_budget,
        )

    async def _search_via_catalog_items(
        self,
        query: str,
        catalog_results: List[Dict[str, Any]],
        limit: int,
        request_budget: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        catalog_titles = [item["title"] for item in catalog_results if item.get("title")]
        offers: List[Dict[str, Any]] = []

        for catalog in catalog_results[: max(limit * 2, 6)]:
            product_id = catalog.get("id")
            if not product_id:
                continue

            detail = await self._fetch_product_detail(product_id, request_budget=request_budget)
            if not detail:
                continue

            item_ids: list[str] = []
            winner = detail.get("buy_box_winner")
            if isinstance(winner, dict):
                winner_id = winner.get("item_id") or winner.get("id")
                if isinstance(winner_id, str) and winner_id.startswith("MLB"):
                    item_ids.append(winner_id)

            for child_id in detail.get("children_ids") or []:
                if isinstance(child_id, str) and child_id.startswith("MLB") and child_id not in item_ids:
                    item_ids.append(child_id)

            for item_id in item_ids[:3]:
                item = await self._fetch_public_json(
                    url=(
                        f"https://api.mercadolibre.com/items/{item_id}"
                        "?attributes=id,title,price,base_price,available_quantity,sold_quantity,permalink,condition,shipping,tags"
                    ),
                    description=f"ML public item detail for '{item_id}'",
                    request_budget=request_budget,
                )
                if not item:
                    continue

                price = item.get("price") or item.get("base_price")
                if not price:
                    continue

                offers.append(
                    {
                        "marketplace": "Mercado Livre",
                        "title": item.get("title", catalog.get("title", query)),
                        "price": float(price),
                        "original_price": float(item.get("base_price") or price),
                        "shipping": 0.0,
                        "delivery_days": 3,
                        "seller_rating": 5.0,
                        "url": item.get("permalink", ""),
                        "ml_item_id": item.get("id", item_id),
                        "available_quantity": item.get("available_quantity", 0),
                        "sold_quantity": item.get("sold_quantity", 0),
                        "condition": item.get("condition", "new"),
                        "tags": item.get("tags", []) or [],
                        "shipping_tags": [],
                    }
                )

        filtered = self._filter_offers_by_context(query, offers, catalog_titles)
        return _deduplicate_offers(filtered, limit)

    async def _fetch_json(
        self,
        url: str,
        params: Dict[str, Any],
        description: str,
        disable_search_api: bool,
        request_budget: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, Any]]:
        if request_budget is not None:
            if request_budget["remaining"] <= 0:
                logger.warning(f"{description} skipped: ML request budget exhausted")
                return None
            request_budget["remaining"] -= 1

        token = await self.auth.get_access_token()
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                for attempt in range(2):
                    async with session.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as resp:
                        if resp.status == 401 and attempt == 0:
                            self.auth._access_token = None
                            refreshed_token = await self.auth.get_access_token()
                            if not refreshed_token:
                                return None
                            headers["Authorization"] = f"Bearer {refreshed_token}"
                            continue

                        if resp.status == 403:
                            if disable_search_api:
                                self._api_available = False
                            logger.warning(f"{description} returned 403")
                            return None

                        if resp.status != 200:
                            body = await resp.text()
                            logger.warning(f"{description} failed ({resp.status}): {body[:240]}")
                            return None

                        return await resp.json()
        except Exception as error:
            logger.error(f"{description} request error: {error}")

        return None

    async def _search_via_api(
        self,
        query: str,
        limit: int,
        catalog_titles: Optional[List[str]] = None,
        sort_by: str = "relevance",
        request_budget: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """Try the official /sites/MLB/search endpoint when it is available."""
        params: Dict[str, Any] = {
            "q": query,
            "limit": min(limit, 50),
            "sort": sort_by if sort_by in {"price_asc", "price_desc", "relevance"} else "relevance",
        }

        if sort_by == "sold_quantity":
            params["power_seller"] = "yes"
            params["official_store"] = "all"
            params["condition"] = "new"

        data = await self._fetch_json(
            url=self.API_SEARCH_URL,
            params=params,
            description=f"ML listing search for '{query}'",
            disable_search_api=True,
            request_budget=request_budget,
        )
        if not data:
            return []

        offers = self._parse_api_results(data, query, limit=min(limit, 50))
        return self._filter_offers_by_context(query, offers, catalog_titles)

    async def _search_via_html(
        self,
        query: str,
        limit: int,
        catalog_titles: Optional[List[str]] = None,
        original_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Parse Mercado Livre HTML search results as a controlled fallback."""
        try:
            slug = _slugify_search_query(query)
            if not slug:
                return []
            url = f"{self.HTML_SEARCH_BASE_URL}/{slug}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }

            def fetch_html() -> tuple[int, str]:
                import requests

                response = requests.get(
                    url,
                    headers=headers,
                    timeout=20,
                    allow_redirects=True,
                )
                return response.status_code, response.text

            status_code, html = await asyncio.to_thread(fetch_html)
            if status_code != 200:
                logger.error(f"ML HTML search failed ({status_code}) for '{query}'")
                return []

            offers = self._parse_html_results(html, query, limit=max(limit, 10))
            base_query = original_query or query
            return self._filter_offers_by_context(base_query, offers, catalog_titles)

        except asyncio.TimeoutError:
            logger.error(f"ML HTML search timeout for '{query}'")
            return []
        except Exception as e:
            logger.error(f"ML HTML search error for '{query}': {e}")
            return []

    def _filter_offers_by_context(
        self,
        query: str,
        offers: List[Dict[str, Any]],
        catalog_titles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        scored_offers: List[Dict[str, Any]] = []
        for offer in offers:
            if _is_international_offer(offer):
                continue
            title = offer.get("title", "")
            if not _is_offer_compatible(query, title, catalog_titles):
                continue

            candidate = dict(offer)
            candidate["_score"] = _offer_score(query, title, catalog_titles)
            scored_offers.append(candidate)

        scored_offers.sort(key=lambda item: (-item["_score"], item.get("price") or float("inf")))
        return [
            {key: value for key, value in offer.items() if key != "_score"}
            for offer in scored_offers
        ]

    def _build_refined_queries(self, query: str, catalog_results: List[Dict[str, Any]]) -> List[str]:
        candidates = _build_public_site_queries(query)
        candidates.extend(item.get("title", "") for item in catalog_results[:6])

        refined_queries: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = re.sub(r"\s+", " ", (candidate or "")).strip()
            normalized = _normalize_text(candidate)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            refined_queries.append(candidate)

        return refined_queries

    def _parse_html_results(self, html: str, query: str, limit: int) -> List[Dict[str, Any]]:
        """Extract product cards from Mercado Livre search HTML."""
        offers: List[Dict[str, Any]] = []
        seen: set[str] = set()

        script_pattern = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
        for script in script_pattern.finditer(html):
            raw_payload = (script.group(1) or "").strip()
            if not raw_payload:
                continue
            try:
                data = json.loads(raw_payload)
            except Exception:
                continue

            graph = data.get("@graph") if isinstance(data, dict) else None
            if not isinstance(graph, list):
                continue

            for node in graph:
                if not isinstance(node, dict) or node.get("@type") != "Product":
                    continue

                offer_data = node.get("offers") or {}
                title = str(node.get("name") or "").strip()
                raw_url = str(offer_data.get("url") or "").strip()
                price_value = offer_data.get("price")
                try:
                    price = float(price_value)
                except (TypeError, ValueError):
                    continue

                if not title or not raw_url or price <= 0:
                    continue

                clean_url = raw_url.replace("&amp;", "&")
                if clean_url.startswith("//"):
                    clean_url = f"https:{clean_url}"
                elif clean_url.startswith("/"):
                    clean_url = f"https://www.mercadolivre.com.br{clean_url}"

                offer_key = clean_url or f"{title}:{price}"
                if offer_key in seen:
                    continue
                seen.add(offer_key)

                offers.append({
                    "marketplace": "Mercado Livre",
                    "title": title,
                    "price": price,
                    "shipping": 0.0,
                    "delivery_days": 3,
                    "seller_rating": 5.0,
                    "url": clean_url,
                    "thumbnail": node.get("image", ""),
                    "shipping_tags": [],
                    "tags": [],
                })
                if len(offers) >= limit:
                    logger.info(f"ML HTML raw: {len(offers)} cards parsed for '{query}' via JSON-LD")
                    return offers

        if offers:
            logger.info(f"ML HTML raw: {len(offers)} cards parsed for '{query}' via JSON-LD")
            return offers[:limit]

        title_pattern = re.compile(
            r'<a[^>]*(?:href="([^"]+)")[^>]*class="poly-component__title[^"]*"[^>]*>([^<]+)<|'
            r'<a[^>]*class="poly-component__title[^"]*"[^>]*(?:href="([^"]+)")[^>]*>([^<]+)<'
        )
        price_pattern = re.compile(r'andes-money-amount__fraction[^>]*>(\d[\d.]*)<')

        titles_with_pos = []
        for m in title_pattern.finditer(html):
            href = m.group(1) or m.group(3) or ""
            title = m.group(2) or m.group(4) or ""
            titles_with_pos.append((m.start(), href, title.strip()))

        prices_with_pos = []
        for m in price_pattern.finditer(html):
            prices_with_pos.append((m.start(), m.group(1)))

        for t_pos, href, title in titles_with_pos:
            if len(offers) >= limit:
                break

            best_price = None
            for p_pos, price_str in prices_with_pos:
                if p_pos > t_pos and p_pos - t_pos < 3000:
                    best_price = price_str
                    break

            if best_price:
                try:
                    price = float(best_price.replace(".", ""))
                except ValueError:
                    continue
                if price <= 0:
                    continue

                clean_url = href.replace("&amp;", "&")
                if clean_url.startswith("//"):
                    clean_url = f"https:{clean_url}"
                elif clean_url.startswith("/"):
                    clean_url = f"https://www.mercadolivre.com.br{clean_url}"

                offers.append({
                    "marketplace": "Mercado Livre",
                    "title": title,
                    "price": price,
                    "shipping": 15.0,
                    "delivery_days": 3,
                    "seller_rating": 5.0,
                    "url": clean_url,
                    "thumbnail": "",
                    "shipping_tags": [],
                    "tags": [],
                })

        logger.info(f"ML HTML raw: {len(offers)} cards parsed for '{query}'")
        return offers

    def _parse_api_results(self, data: Dict[str, Any], query: str, limit: int) -> List[Dict[str, Any]]:
        """Parse the listing search response into standard offers."""
        results = data.get("results", [])
        offers: List[Dict[str, Any]] = []
        for item in results[:limit]:
            price = item.get("price")
            if not price or price <= 0:
                continue

            offers.append({
                "marketplace": "Mercado Livre",
                "title": item.get("title", query),
                "price": float(price),
                "original_price": float(item.get("original_price") or price),
                "shipping": 0.0 if item.get("shipping", {}).get("free_shipping") else 15.0,
                "free_shipping": item.get("shipping", {}).get("free_shipping", False),
                "delivery_days": 3,
                "seller_rating": 5.0,
                "seller_name": item.get("seller", {}).get("nickname", ""),
                "condition": item.get("condition", "new"),
                "url": item.get("permalink", ""),
                "thumbnail": item.get("thumbnail", ""),
                "ml_item_id": item.get("id", ""),
                "available_quantity": item.get("available_quantity", 0),
                "sold_quantity": item.get("sold_quantity", 0),
                "domain_id": item.get("domain_id", ""),
                "tags": item.get("tags", []) or [],
                "shipping_tags": item.get("shipping", {}).get("tags", []) or [],
                "logistic_type": item.get("shipping", {}).get("logistic_type", ""),
                "international_delivery_mode": item.get("shipping", {}).get("international_delivery_mode", ""),
            })

        logger.info(f"ML listing API: {len(offers)} raw results for '{query}'")
        return offers

    def _parse_catalog_results(self, data: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Parse /products/search results into catalog candidates."""
        catalog_results: List[Dict[str, Any]] = []
        for item in data.get("results", [])[:limit]:
            attributes = item.get("attributes") or []
            attribute_map = {
                attribute.get("id"): attribute.get("value_name")
                for attribute in attributes
                if attribute.get("id")
            }
            title = item.get("name") or attribute_map.get("MODEL") or item.get("id", "")
            catalog_results.append({
                "id": item.get("id") or item.get("catalog_product_id", ""),
                "title": title,
                "domain_id": item.get("domain_id", ""),
                "brand": attribute_map.get("BRAND", ""),
                "model": attribute_map.get("MODEL", ""),
                "status": item.get("status", ""),
            })

        return catalog_results

    async def search_best_sellers(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Best-seller search with graceful fallback when listing API is blocked."""
        query = _sanitize_search_query(query)
        if self._official_only:
            offers = await self.search_product(query, limit)
            for offer in offers:
                offer["is_best_seller"] = bool(offer.get("sold_quantity", 0) > 100)
            return offers

        catalog_results = await self.search_catalog_products(query, limit=max(limit, 8))
        catalog_titles = [item["title"] for item in catalog_results if item.get("title")]

        if self._api_available:
            offers = await self._search_via_api(
                query=query,
                limit=limit,
                catalog_titles=catalog_titles,
                sort_by="sold_quantity",
            )
            if offers:
                for offer in offers:
                    offer["is_best_seller"] = bool(offer.get("sold_quantity", 0) > 100)
                return offers

        fallback_offers = await self.search_product(query, limit)
        for offer in fallback_offers:
            offer["is_best_seller"] = False
        return fallback_offers

    async def search_batch(self, queries: List[str], limit_per_query: int = 3) -> Dict[str, List[Dict]]:
        """Search multiple products concurrently."""
        async def _search_one(query: str):
            await asyncio.sleep(0.5)  # Respect rate limits for HTML scraping
            return query, await self.search_product(query, limit_per_query)

        tasks = [_search_one(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Batch search error: {result}")
                continue
            query, offers = result
            output[query] = offers

        return output


# Singleton instance
_ml_client: Optional[MLSearchClient] = None


def get_ml_client() -> MLSearchClient:
    global _ml_client
    if _ml_client is None:
        _ml_client = MLSearchClient()
    return _ml_client
