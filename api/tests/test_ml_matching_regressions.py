import unittest

from app.services.ml_api_client import _build_public_site_queries, _is_offer_compatible


class MercadoLivreMatchingRegressionTests(unittest.TestCase):
    def test_blocks_wrong_flange_dimension(self):
        query = 'Adaptador soldavel anel de vedacao para caixa (flange) 32 x 1"'
        title = "Adaptador Soldavel 25mm E Flange Anel Para Caixa Dagua Tigre"
        self.assertFalse(_is_offer_compatible(query, title, []))

    def test_accepts_matching_flange_dimension(self):
        query = 'Adaptador soldavel anel de vedacao para caixa (flange) 40 x 1 1/4"'
        title = "Adaptador Soldavel 40mm X 1.1/4 Com Anel E Flange - Amanco"
        self.assertTrue(_is_offer_compatible(query, title, []))

    def test_blocks_assento_accessory(self):
        query = "Assento sanitario de propileno na cor branca, incluindo acessorios"
        title = "Parafuso Fixacao Assento Sanitario Deca Izy Branco"
        self.assertFalse(_is_offer_compatible(query, title, []))

    def test_blocks_engate_for_caixa_descarga(self):
        query = "Caixa de descarga simples em polietileno, sem engate, na cor branca"
        title = "Engate Flexivel 40 Cm Branco Click Reparos Para Caixa De Descarga"
        self.assertFalse(_is_offer_compatible(query, title, []))

    def test_accepts_caixa_descarga_product(self):
        query = "Caixa de descarga simples em polietileno, sem engate, na cor branca"
        title = "Caixa De Descarga Branca Inova Vaso Sanitario 6 A 9 Litros"
        self.assertTrue(_is_offer_compatible(query, title, []))

    def test_builds_useful_public_query_variants(self):
        query = "Caixa de descarga simples em polietileno, sem engate, na cor branca"
        variants = _build_public_site_queries(query)
        self.assertIn("caixa de descarga sem engate branca", variants)
        self.assertIn("caixa de descarga branca", variants)


if __name__ == "__main__":
    unittest.main()
