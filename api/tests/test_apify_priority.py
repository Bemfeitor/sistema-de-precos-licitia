import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.apify_ml_client import _canonicalize_query, _rank_candidates
from app.services.marketplace_service import search_marketplace_prices
from app.services.marketplace_service_v4 import search_with_best_sellers_priority


def _offer(title: str, price: float, url: str, **extra):
    base = {
        "marketplace": "Mercado Livre (Apify)",
        "title": title,
        "price": price,
        "currency": "BRL",
        "shipping": 0.0,
        "delivery_days": 3,
        "seller_rating": 4.8,
        "url": url,
        "price_validated": None,
        "price_match": False,
        "validation_method": "apify_dataset",
        "validation_used": False,
        "sold_quantity": 15,
        "is_best_seller": False,
        "is_mais_vendido": False,
        "has_free_shipping": True,
        "listing_type": "ORGANIC",
        "brand": "",
        "source": "apify",
        "source_priority": 0,
        "search_strategy": "mercadolivre_lowest_price_finder",
    }
    base.update(extra)
    return base


class ApifyRerankingTests(unittest.TestCase):
    def test_ranking_prefers_real_product_over_accessory_and_wrong_color(self):
        query_spec = _canonicalize_query("Vaso sanitário, cor branca")
        ranked, discarded = _rank_candidates(
            query_spec,
            [
                _offer(
                    "Kit reparo mecanismo para vaso sanitário branco",
                    49.9,
                    "https://ml.local/kit-reparo",
                ),
                _offer(
                    "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
                    475.9,
                    "https://ml.local/vaso-branco",
                ),
                _offer(
                    "Vaso Sanitário Monobloco Caixa Acoplada Cor Preto",
                    399.9,
                    "https://ml.local/vaso-preto",
                ),
            ],
        )

        self.assertEqual(1, len(ranked))
        self.assertEqual("Vaso Sanitário Monobloco Caixa Acoplada Cor Branco", ranked[0]["title"])

        discarded_by_title = {item["title"]: item["reason"] for item in discarded}
        self.assertIn("Vaso Sanitário Monobloco Caixa Acoplada Cor Preto", discarded_by_title)
        self.assertIn("Kit reparo mecanismo para vaso sanitário branco", discarded_by_title)


class PipelinePriorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._marketplace_settings = patch(
            "app.services.marketplace_service.get_settings",
            return_value=SimpleNamespace(BRIGHT_DATA_ONLY_MODE=False),
        )
        self._marketplace_v4_settings = patch(
            "app.services.marketplace_service_v4.get_settings",
            return_value=SimpleNamespace(BRIGHT_DATA_ONLY_MODE=False, ML_OFFICIAL_ONLY=True),
        )
        self._marketplace_settings.start()
        self._marketplace_v4_settings.start()

    def tearDown(self):
        self._marketplace_settings.stop()
        self._marketplace_v4_settings.stop()

    async def test_unified_pipeline_bright_only_returns_cheapest_bright_offer(self):
        bright_offer_expensive = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            489.9,
            "https://ml.local/brightdata-vaso-branco-expensive",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.99,
            validation_method="brightdata_dataset",
            search_strategy="brightdata_ml_dataset",
        )
        bright_offer_cheapest = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            449.9,
            "https://ml.local/brightdata-vaso-branco-cheapest",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.83,
            validation_method="brightdata_dataset",
            search_strategy="brightdata_ml_dataset",
        )

        with patch(
            "app.services.marketplace_service.get_settings",
            return_value=SimpleNamespace(BRIGHT_DATA_ONLY_MODE=True),
        ), patch(
            "app.services.marketplace_service.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[bright_offer_expensive, bright_offer_cheapest]),
        ), patch(
            "app.services.marketplace_service.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value={"results": [], "winner": None, "meta": {}}),
        ) as apify_mock, patch(
            "app.services.marketplace_service.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ) as google_mock, patch(
            "app.services.marketplace_service.get_ml_client",
            return_value=MagicMock(),
        ) as ml_client_mock:
            offers = await search_marketplace_prices("Vaso sanitário, cor branca", num_offers=3)

        self.assertEqual(2, len(offers))
        self.assertEqual("https://ml.local/brightdata-vaso-branco-cheapest", offers[0]["url"])
        apify_mock.assert_not_awaited()
        google_mock.assert_not_awaited()
        ml_client_mock.assert_not_called()

    async def test_unified_pipeline_prefers_brightdata_and_skips_apify_when_enough_results(self):
        brightdata_offer = _offer(
            "Vaso SanitÃ¡rio Monobloco Caixa Acoplada Cor Branco",
            459.9,
            "https://ml.local/brightdata-vaso-branco",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.97,
            validation_method="brightdata_dataset",
            validation_used=True,
            price_validated=459.9,
            price_match=True,
            search_strategy="brightdata_ml_dataset",
        )
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[])
        ml_client.search_public_site = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[brightdata_offer]),
        ), patch(
            "app.services.marketplace_service.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value={"results": [], "winner": None, "meta": {}}),
        ) as apify_mock, patch(
            "app.services.marketplace_service.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ) as google_mock, patch(
            "app.services.marketplace_service.get_ml_client",
            return_value=ml_client,
        ):
            offers = await search_marketplace_prices("Vaso sanitÃ¡rio, cor branca", num_offers=1)

        self.assertEqual(1, len(offers))
        self.assertEqual("https://ml.local/brightdata-vaso-branco", offers[0]["url"])
        apify_mock.assert_not_awaited()
        google_mock.assert_not_awaited()
        ml_client.search_product.assert_not_awaited()
        ml_client.search_public_site.assert_not_awaited()

    async def test_unified_pipeline_keeps_apify_when_google_and_ml_add_nothing(self):
        apify_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            475.9,
            "https://ml.local/vaso-branco",
            confidence=0.96,
            match_reasons=["categoria correta", "atributo branco"],
        )
        apify_bundle = {
            "results": [apify_offer],
            "winner": apify_offer,
            "status": "ok",
            "meta": {
                "best_confidence": 0.96,
                "total_actor_calls": 1,
            },
        }
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[])
        ml_client.search_public_site = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value=apify_bundle),
        ), patch(
            "app.services.marketplace_service.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service.get_ml_client",
            return_value=ml_client,
        ):
            offers = await search_marketplace_prices("Vaso sanitário, cor branca", num_offers=1)

        self.assertEqual(1, len(offers))
        self.assertEqual("https://ml.local/vaso-branco", offers[0]["url"])
        ml_client.search_product.assert_not_awaited()
        ml_client.search_public_site.assert_not_awaited()

    async def test_unified_pipeline_prefers_lower_google_price_over_apify_priority(self):
        apify_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            475.9,
            "https://ml.local/vaso-branco",
            confidence=0.96,
            match_reasons=["categoria correta", "atributo branco"],
        )
        google_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            449.9,
            "https://amazon.com.br/dp/B0TESTE123",
            marketplace="Amazon",
            source="google_search",
            source_priority=1,
            confidence=0.84,
            validation_method="meta_price",
            validation_used=True,
            price_validated=449.9,
            price_match=True,
        )
        apify_bundle = {
            "results": [apify_offer],
            "winner": apify_offer,
            "status": "ok",
            "meta": {
                "best_confidence": 0.96,
                "total_actor_calls": 1,
            },
        }
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[])
        ml_client.search_public_site = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value=apify_bundle),
        ), patch(
            "app.services.marketplace_service.search_google_marketplace_offers",
            new=AsyncMock(return_value=[google_offer]),
        ), patch(
            "app.services.marketplace_service.get_ml_client",
            return_value=ml_client,
        ):
            offers = await search_marketplace_prices("Vaso sanitário, cor branca", num_offers=3)

        self.assertEqual("https://amazon.com.br/dp/B0TESTE123", offers[0]["url"])
        self.assertEqual(449.9, offers[0]["price"])

    async def test_unified_pipeline_ignores_low_confidence_apify_results(self):
        apify_offer = _offer(
            "Suporte Para Escova De Vaso Sanitário",
            69.9,
            "https://ml.local/suporte-escova",
            confidence=0.57,
        )
        apify_bundle = {
            "results": [apify_offer],
            "winner": apify_offer,
            "status": "needs_review",
            "meta": {
                "best_confidence": 0.57,
                "total_actor_calls": 2,
            },
        }
        ml_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            475.9,
            "https://ml.local/vaso-branco",
            marketplace="Mercado Livre",
            source="ml_api",
            source_priority=1,
        )
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[ml_offer])
        ml_client.search_public_site = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value=apify_bundle),
        ), patch(
            "app.services.marketplace_service.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service.get_ml_client",
            return_value=ml_client,
        ):
            offers = await search_marketplace_prices("Vaso sanitário, cor branca", num_offers=3)

        self.assertEqual("https://ml.local/vaso-branco", offers[0]["url"])

    async def test_v4_pipeline_prefers_lower_google_price_over_sticky_apify_winner(self):
        apify_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            475.9,
            "https://ml.local/vaso-branco",
            confidence=0.96,
            match_reasons=["categoria correta", "atributo branco"],
        )
        google_offer = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            449.9,
            "https://amazon.com.br/dp/B0TESTE123",
            marketplace="Amazon",
            source="google_search",
            source_priority=1,
            confidence=0.84,
            validation_method="meta_price",
            validation_used=True,
            price_validated=449.9,
            price_match=True,
        )
        apify_bundle = {
            "results": [apify_offer],
            "winner": apify_offer,
            "status": "ok",
            "meta": {
                "best_confidence": 0.96,
                "total_actor_calls": 1,
            },
        }
        best_sellers_mock = AsyncMock(return_value=[])
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service_v4.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.marketplace_service_v4.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value=apify_bundle),
        ), patch(
            "app.services.marketplace_service_v4.search_google_marketplace_offers",
            new=AsyncMock(return_value=[google_offer]),
        ), patch(
            "app.services.marketplace_service_v4.search_best_sellers_api",
            new=best_sellers_mock,
        ), patch(
            "app.services.marketplace_service_v4.get_ml_client",
            return_value=ml_client,
        ):
            offers, metrics = await search_with_best_sellers_priority(
                "Vaso sanitário, cor branca",
                quantidade_desejada=1,
                valor_maximo=0.0,
            )

        self.assertGreaterEqual(len(offers), 1)
        self.assertEqual("https://amazon.com.br/dp/B0TESTE123", metrics.url_menor_preco)
        self.assertEqual(449.9, metrics.menor_preco)

    async def test_v4_pipeline_uses_brightdata_as_primary_source(self):
        brightdata_offer = _offer(
            "Vaso SanitÃ¡rio Monobloco Caixa Acoplada Cor Branco",
            455.9,
            "https://ml.local/brightdata-v4-vaso-branco",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.97,
            validation_method="brightdata_dataset",
            validation_used=True,
            price_validated=455.9,
            price_match=True,
            search_strategy="brightdata_ml_dataset",
        )
        best_sellers_mock = AsyncMock(return_value=[])
        ml_client = MagicMock()
        ml_client.search_product = AsyncMock(return_value=[])

        with patch(
            "app.services.marketplace_service_v4.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[brightdata_offer]),
        ), patch(
            "app.services.marketplace_service_v4.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value={"results": [], "winner": None, "meta": {}}),
        ) as apify_mock, patch(
            "app.services.marketplace_service_v4.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ) as google_mock, patch(
            "app.services.marketplace_service_v4.search_best_sellers_api",
            new=best_sellers_mock,
        ), patch(
            "app.services.marketplace_service_v4.get_ml_client",
            return_value=ml_client,
        ):
            offers, metrics = await search_with_best_sellers_priority(
                "Vaso sanitÃ¡rio, cor branca",
                quantidade_desejada=1,
                valor_maximo=0.0,
            )

        self.assertGreaterEqual(len(offers), 1)
        self.assertEqual("https://ml.local/brightdata-v4-vaso-branco", metrics.url_menor_preco)
        self.assertEqual(455.9, metrics.menor_preco)
        apify_mock.assert_not_awaited()
        google_mock.assert_not_awaited()
        best_sellers_mock.assert_not_awaited()
        ml_client.search_product.assert_not_awaited()

    async def test_v4_pipeline_bright_only_selects_cheapest_bright_offer(self):
        bright_offer_expensive = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            515.9,
            "https://ml.local/bright-v4-expensive",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.99,
        )
        bright_offer_cheapest = _offer(
            "Vaso Sanitário Monobloco Caixa Acoplada Cor Branco",
            455.9,
            "https://ml.local/bright-v4-cheapest",
            marketplace="Mercado Livre (Bright Data)",
            source="brightdata",
            source_priority=0,
            confidence=0.8,
        )

        with patch(
            "app.services.marketplace_service_v4.get_settings",
            return_value=SimpleNamespace(BRIGHT_DATA_ONLY_MODE=True, ML_OFFICIAL_ONLY=True),
        ), patch(
            "app.services.marketplace_service_v4.search_brightdata_mercadolivre",
            new=AsyncMock(return_value=[bright_offer_expensive, bright_offer_cheapest]),
        ), patch(
            "app.services.marketplace_service_v4.search_apify_mercadolivre_bundle",
            new=AsyncMock(return_value={"results": [], "winner": None, "meta": {}}),
        ) as apify_mock, patch(
            "app.services.marketplace_service_v4.search_google_marketplace_offers",
            new=AsyncMock(return_value=[]),
        ) as google_mock, patch(
            "app.services.marketplace_service_v4.search_best_sellers_api",
            new=AsyncMock(return_value=[]),
        ) as best_sellers_mock, patch(
            "app.services.marketplace_service_v4.get_ml_client",
            return_value=MagicMock(),
        ) as ml_client_mock:
            offers, metrics = await search_with_best_sellers_priority(
                "Vaso sanitário, cor branca",
                quantidade_desejada=1,
                valor_maximo=0.0,
            )

        self.assertEqual(1, len(offers))
        self.assertEqual("https://ml.local/bright-v4-cheapest", metrics.url_menor_preco)
        self.assertEqual(455.9, metrics.menor_preco)
        apify_mock.assert_not_awaited()
        google_mock.assert_not_awaited()
        best_sellers_mock.assert_not_awaited()
        ml_client_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
