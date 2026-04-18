from __future__ import annotations

from typing import Iterable, Optional


def _marketplace_text(offer) -> str:
    return (getattr(offer, "marketplace", "") or "").lower()


def _offer_url(offer) -> str:
    return (getattr(offer, "url", "") or "").lower()


def _bool_attr(offer, name: str) -> bool | None:
    value = getattr(offer, name, None)
    if value is None:
        return None
    return bool(value)


def is_exact_validated_offer(offer) -> bool:
    explicit = _bool_attr(offer, "price_match")
    if explicit is not None:
        return explicit
    marketplace = _marketplace_text(offer)
    return "validado" in marketplace


def is_best_seller_offer(offer) -> bool:
    explicit = _bool_attr(offer, "is_best_seller")
    if explicit is not None:
        return explicit
    marketplace = _marketplace_text(offer)
    return "mais vendido" in marketplace


def is_direct_offer_url(offer) -> bool:
    url = _offer_url(offer)
    if not url:
        return False
    if "click1.mercadolivre.com.br" in url:
        return True
    if "mercadolivre.com.br" in url:
        return "lista.mercadolivre.com.br" not in url and (
            "/p/" in url or "/_jm" in url or "/mlb-" in url
        )
    if "magazineluiza.com.br" in url:
        return "/p/" in url and "/busca/" not in url
    if "amazon.com.br" in url:
        return "/dp/" in url or "/gp/product/" in url
    if "shopee.com.br" in url:
        return "/product/" in url
    return True


def offer_priority_key(offer) -> tuple[int, int, int, int, float, float]:
    sold_quantity = int(getattr(offer, "sold_quantity", 0) or 0)
    return (
        0 if is_exact_validated_offer(offer) else 1,
        0 if is_best_seller_offer(offer) else 1,
        0 if is_direct_offer_url(offer) else 1,
        -sold_quantity,
        float(getattr(offer, "price", 0.0) or 0.0),
        float(getattr(offer, "shipping", 0.0) or 0.0),
    )


def select_best_offer(offers: Iterable) -> Optional[object]:
    offers = list(offers)
    if not offers:
        return None
    direct_offers = [offer for offer in offers if is_direct_offer_url(offer)]
    pool = direct_offers or offers
    return min(pool, key=offer_priority_key)


def select_mid_offer(offers: Iterable, best_offer) -> Optional[object]:
    offers = [offer for offer in offers if offer is not best_offer]
    if not offers:
        return None

    direct_offers = [offer for offer in offers if is_direct_offer_url(offer)]
    pool = direct_offers or offers

    higher_offers = [
        offer
        for offer in sorted(pool, key=offer_priority_key)
        if float(getattr(offer, "price", 0.0) or 0.0)
        > float(getattr(best_offer, "price", 0.0) or 0.0) * 1.05
    ]
    if higher_offers:
        return higher_offers[len(higher_offers) // 2]

    return min(pool, key=offer_priority_key)
