# Search Hardening Notes

## Caso analisado

- Produto: `Item 21 - madeira de 1,60cm`
- Problema observado: links de produtos sem relação com o item, incluindo perfume e móveis genéricos.

## Causa raiz

- A busca estava usando `product.name`, incluindo prefixos como `Item 21 -`, o que poluiu a consulta.
- O catálogo do Mercado Livre retornou itens irrelevantes contendo o termo genérico `item`.
- A compatibilidade aceitava forte aderência ao catálogo mesmo sem aderência suficiente ao item buscado.
- A validação do link confirmava preço, mas não confirmava identidade do produto no anúncio.

## Correções aplicadas

- Sanitização da query antes da busca no Mercado Livre.
- Priorização da descrição do produto sobre o nome bruto com prefixo de item.
- Filtro mais rígido para medidas e termos âncora.
- Bloqueio de ofertas com sinal de compra internacional.
- Validação do link passou a verificar conteúdo/título da página contra o item buscado.
- Busca de projeto mantida em lotes de no máximo 50 produtos por rodada.

## Recomendações adicionais

- Persistir no banco um relatório do checklist de compatibilidade por oferta rejeitada.
- Expor na UI o motivo da rejeição: `medida divergente`, `compra internacional`, `link incompatível`.
- Adicionar testes automatizados com itens ambíguos como madeira, tubos, brocas e conexões.
