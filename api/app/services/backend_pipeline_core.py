import os
import json
import logging
import re
import asyncio
import io
import aiohttp
import pdfplumber
import google.generativeai as genai
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from urllib.parse import quote
from app.config import get_settings

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# ==============================================================================
# 1. Configuração e Modelos de Dados
# ==============================================================================

settings = get_settings()

class AppConfig:
    """Configurações centralizadas do pipeline"""
    GEMINI_API_KEY = settings.GEMINI_API_KEY
    FIRECRAWL_BASE_URL = getattr(settings, "FIRECRAWL_URL", "http://localhost:3002")
    FIRECRAWL_TIMEOUT = 120
    MAX_CONCURRENT_SCRAPES = 3  # Reduzido para não sobrecarregar
    GEMINI_MODEL = "gemini-1.5-flash-latest" # Tentativa com a versão mais recente para evitar 404
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class PriceResult(BaseModel):
    """Modelo de resultado final de preço"""
    item_name: str = Field(description="Nome original do item extraído do edital")
    search_url: str = Field(description="URL de busca utilizada")
    preco: Optional[float] = Field(None, description="Menor preço encontrado")
    link_produto: Optional[str] = Field(None, description="Link direto do produto")
    titulo_encontrado: Optional[str] = Field(None, description="Título real do produto na plataforma")
    fonte: str = Field(default="mercado_livre")
    status: str = Field(default="success", description="success, partial_error ou error")
    erro: Optional[str] = Field(None, description="Descrição do erro, se houver")

class ExtractedItem(BaseModel):
    """Representa um item extraído do PDF"""
    nome: str
    pagina_origem: int

class ScrapedData(BaseModel):
    """Dados brutos retornados pelo Firecrawl ou Fallback"""
    url: str
    markdown: str
    item_ref: str

# ==============================================================================
# 2. Serviço de Extração de PDF (Gemini)
# ==============================================================================

logger = logging.getLogger(__name__)

class PDFExtractor:
    """Responsável por extrair texto de páginas específicas de PDFs e interpretar itens."""
    
    def __init__(self):
        genai.configure(api_key=AppConfig.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(AppConfig.GEMINI_MODEL)
    
    def extrair_texto_pagina(self, pdf_bytes: bytes, page_number: int) -> str:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                if page_number < 1 or page_number > len(pdf.pages):
                    raise ValueError(f"Página {page_number} inválida.")
                page = pdf.pages[page_number - 1]
                return page.extract_text() or ""
        except Exception as e:
            logger.error(f"Erro na extração de texto do PDF: {e}")
            return ""
    
    async def extrair_itens_licitacao(self, pdf_bytes: bytes, page_number: int) -> List[ExtractedItem]:
        texto_pagina = self.extrair_texto_pagina(pdf_bytes, page_number)
        if not texto_pagina: return []
        
        prompt = f"""
        Lista de Itens (Pag {page_number}):
        {texto_pagina[:30000]}
        
        Extraia APENAS os nomes dos produtos como lista JSON de strings.
        Ex: ["Produto A", "Produto B"]
        """
        try:
            response = await self.model.generate_content_async(prompt)
            nomes = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            return [ExtractedItem(nome=n.strip(), pagina_origem=page_number) for n in nomes if n.strip()]
        except Exception as e:
            logger.error(f"Erro Gemini Parser: {e}")
            return []

# ==============================================================================
# 3. Construtor de URLs (Mercado Livre)
# ==============================================================================

class MercadoLivreURLBuilder:
    BASE_URL = "https://lista.mercadolivre.com.br"
    
    def formatar_termo_busca(self, nome_item: str) -> str:
        termo = re.sub(r'[^\w\s]', '', nome_item.lower())
        return re.sub(r'\s+', '-', termo.strip())
    
    def construir_urls(self, itens: List[ExtractedItem]) -> List[dict]:
        return [{
            "item": item,
            "search_url": f"{self.BASE_URL}/{quote(self.formatar_termo_busca(item.nome))}"
        } for item in itens]

# ==============================================================================
# 4. Scraper Assíncrono (Firecrawl com Fallback)
# ==============================================================================

class FirecrawlScraper:
    def __init__(self):
        self.base_url = AppConfig.FIRECRAWL_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=AppConfig.FIRECRAWL_TIMEOUT),
            headers={
                "User-Agent": AppConfig.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=1.7",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session: await self.session.close()
    
    async def _fallback_scrape(self, url: str, item_name: str, retry=0) -> ScrapedData:
        logger.info(f"Fallback Scraping (Attempt {retry+1}): {url}")
        
        # User agents variados para evitar bloqueio
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
        ]
        
        headers = {
            "User-Agent": user_agents[retry % len(user_agents)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive"
        }
        
        try:
            async with self.session.get(url, headers=headers, allow_redirects=True) as resp:
                if resp.status != 200:
                    return ScrapedData(url=url, markdown="", item_ref=item_name)
                
                html = await resp.text()
                
                # Detecção de Bot/Challenge
                if "robot" in html.lower() or "captcha" in html.lower() or "human" in html.lower():
                    if retry < 1:
                        logger.warning(f"Detection triggered for {url}. Retrying with different UA...")
                        await asyncio.sleep(5)
                        return await self._fallback_scrape(url, item_name, retry + 1)
                
                # Limpeza inteligente para preservar links
                content = ""
                if BeautifulSoup:
                    soup = BeautifulSoup(html, 'html.parser')
                    # Remove lixo
                    for element in soup(["script", "style", "nav", "footer", "header", "svg"]):
                        element.decompose()
                    
                    # Converte links para formato legível [Title](URL)
                    for a in soup.find_all("a", href=True):
                        # Só interessa links de produto ou busca interna
                        if "mercadolivre.com" in a["href"] or a["href"].startswith("/MLB"):
                            link_text = a.get_text(strip=True)
                            href = a["href"]
                            if href.startswith("/"):
                                href = f"https://www.mercadolivre.com.br{href}"
                            # Substitui o elemento original por um placeholder textual
                            a.replace_with(f" [{link_text}]({href}) ")
                    
                    content = soup.get_text(separator=' ', strip=True)
                else:
                    content = html[:30000]
                
                return ScrapedData(url=url, markdown=content[:50000], item_ref=item_name)
        except Exception as e:
            logger.error(f"Fallback Error for {url}: {e}")
            return ScrapedData(url=url, markdown="", item_ref=item_name)

    async def processar_url(self, item_data: dict) -> ScrapedData:
        url = item_data['search_url']
        item_name = item_data['item'].nome
        
        try:
            # Tenta Firecrawl primeiro (mais potente)
            async with self.session.post(f"{self.base_url}/v1/scrape", json={"url": url, "formats": ["markdown"]}, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    markdown = data.get('data', {}).get('markdown', '')
                    if markdown:
                        return ScrapedData(url=url, markdown=markdown, item_ref=item_name)
            
            # Se Firecrawl falhou ou deu vazio, tenta o scraping direto
            s_data = await self._fallback_scrape(url, item_name)
            
            # Se ainda está vazio OU MUITO CURTO (indicativo de bloqueio/página de erro), tenta o termo simplificado
            if len(s_data.markdown) < 500:
                palavras = item_name.split()
                if len(palavras) > 2:
                    termo_simples = " ".join(palavras[:3])
                    logger.info(f"Retrying with simplified term: {termo_simples}")
                    simple_url = f"https://lista.mercadolivre.com.br/{termo_simples.replace(' ', '-')}"
                    return await self._fallback_scrape(simple_url, item_name)
            
            return s_data
            
        except Exception as e:
            logger.warning(f"Strategy failed for {url}: {e}. Final fallback...")
            return await self._fallback_scrape(url, item_name)
    
    async def processar_lote(self, itens_url: List[dict], max_concurrent: int = 1) -> List[ScrapedData]:
        # Forçamos concorrência 1 para evitar bloqueios de IP (Anti-bot)
        semaphore = asyncio.Semaphore(1)
        
        async def sem_processar(item):
            async with semaphore:
                import random
                # Delay aleatório entre 2 e 5 segundos para parecer humano
                delay = random.uniform(2.0, 5.0)
                await asyncio.sleep(delay)
                return await self.processar_url(item)
        
        return await asyncio.gather(*(sem_processar(url) for url in itens_url))

# ==============================================================================
# 5. Parser de Preços (Gemini + RegEx Fallback)
# ==============================================================================

class PriceParser:
    def __init__(self):
        genai.configure(api_key=AppConfig.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(AppConfig.GEMINI_MODEL)
    
    def _regex_price_extraction(self, text: str, item_name: str, url: str) -> PriceResult:
        """RegEx de última instância: Foca em qualquer seqüência R$ + números"""
        if not text: return None
        
        # Normalização: Mantém o texto limpo mas preserve espaços significativos
        text = re.sub(r'\s+', ' ', text)
        
        # Pattern mais flexível: R$ seguido de números, aceitando espaços e centavos OPCIONAIS
        # Ex: R$ 323 , 10  OR R$ 45
        pattern = r'R\$\s*(\d[\d\.\s]*?)(?:\s*[\.,]\s*(\d{2}))?\b'
        
        matches = list(re.finditer(pattern, text))
        if not matches:
            return None
            
        results = []
        for m in matches:
            try:
                inteiro_str = m.group(1)
                decimal_str = m.group(2) if m.group(2) else "00"
                
                inteiro = re.sub(r'\D', '', inteiro_str)
                if not inteiro: continue
                
                price = float(f"{inteiro}.{decimal_str}")
                
                # Busca por um link (URL) próximo a este preço no texto original
                # Procuramos num raio de 300 caracteres ao redor do match
                start_pos = max(0, m.start() - 300)
                end_pos = min(len(text), m.end() + 300)
                context = text[start_pos:end_pos]
                
                link_match = re.search(r'\(https://[^\)]+\)', context)
                link = link_match.group(0)[1:-1] if link_match else url
                
                # Filtra valores extremos (ajustado para > 15.0 para evitar ruído de frete/prazos)
                if 15.0 < price < 500000.0:
                    results.append({"price": price, "link": link})
            except:
                continue
        
        if results:
            # Moda Estatística baseada no PREÇO
            from collections import Counter
            prices_found = [r["price"] for r in results]
            counts = Counter(prices_found)
            most_common_price, _ = counts.most_common(1)[0]
            
            # Pega o link associado à PRIMEIRA ocorrência desse preço mais comum
            final_link = next(r["link"] for r in results if r["price"] == most_common_price)
            
            return PriceResult(
                item_name=item_name, 
                search_url=url, 
                preco=most_common_price, 
                link_produto=final_link,
                titulo_encontrado=item_name, # Fallback para o nome do item no modo RegEx
                status="partial_error", 
                erro="RegEx Localized Mode"
            )
        return None

    async def extrair_preco_item(self, scraped: ScrapedData, retry_count=0) -> PriceResult:
        if not scraped.markdown:
            return PriceResult(item_name=scraped.item_ref, search_url=scraped.url, status="error", erro="Sem conteúdo")
        
        prompt = f"""
        Tarefa: Extraia o PREÇO TOTAL e o LINK REAL do produto para o item: '{scraped.item_ref}'.
        
        Instruções Críticas:
        1. Ignore nomes genéricos como 'Econômico', 'Intermediário' ou 'Melhor Preço'. Use o TÍTULO REAL do anúncio.
        2. Ignore preços de PARCELAS (ex: R$ 20 mensais). Pegue apenas o valor TOTAL do produto.
        3. O Link deve ser o URL direto do Mercado Livre (ex: produto.mercadolivre.com.br/MLB-...).
        4. Se houver vários itens, escolha o que mais se assemelha a '{scraped.item_ref}'.
        5. Formato de Saída (APENAS JSON): {{"titulo": "string", "preco": float, "link": "string"}}
        
        Conteúdo da Página:
        {scraped.markdown[:20000]}
        """
        
        try:
            # Rate limiting sleep para Free Tier
            if retry_count > 0:
                await asyncio.sleep(20 * retry_count) 
            
            response = await self.model.generate_content_async(prompt, generation_config={"response_mime_type": "application/json"})
            dados = json.loads(response.text)
            preco = float(dados.get("preco")) if dados.get("preco") else None
            
            if preco and preco > 25.0: # Filtro extra contra parcelas mensais de R$ 20
                return PriceResult(
                    item_name=scraped.item_ref, search_url=scraped.url, 
                    preco=preco,
                    link_produto=dados.get("link"),
                    titulo_encontrado=dados.get("titulo"),
                    status="success"
                )
            # Se a IA não achou, tenta RegEx antes de desistir
            regex_res = self._regex_price_extraction(scraped.markdown, scraped.item_ref, scraped.url)
            if regex_res:
                return regex_res
                
            return PriceResult(item_name=scraped.item_ref, search_url=scraped.url, status="partial_error", erro="IA retornou preco nulo")
            
        except Exception as e:
            if "429" in str(e) and retry_count < 2:
                logger.warning(f"Gemini Rate Limit for {scraped.item_ref}, retrying...")
                return await self.extrair_preco_item(scraped, retry_count + 1)
            
            # Última tentativa: RegEx
            regex_res = self._regex_price_extraction(scraped.markdown, scraped.item_ref, scraped.url)
            if regex_res:
                return regex_res
                
            return PriceResult(item_name=scraped.item_ref, search_url=scraped.url, status="error", erro=str(e))
    
    async def processar_lote(self, scraped_data_list: list[ScrapedData]) -> list[PriceResult]:
        # Processamento sequencial ou semi-sequencial para evitar 429
        semaphore = asyncio.Semaphore(1) # UM por vez para respeitar quota do Free Tier
        async def work(s):
            async with semaphore:
                return await self.extrair_preco_item(s)
        return await asyncio.gather(*(work(s) for s in scraped_data_list))

# ==============================================================================
# 6. Pipeline Principal
# ==============================================================================

class PriceIntelligencePipeline:
    def __init__(self):
        self.extractor = PDFExtractor()
        self.url_builder = MercadoLivreURLBuilder()
        self.parser = PriceParser()
    
    async def processar(self, pdf_bytes: bytes, page_number: int, max_concurrent: int = 5) -> List[PriceResult]:
        itens = await self.extractor.extrair_itens_licitacao(pdf_bytes, page_number)
        if not itens: return []
        itens_com_url = self.url_builder.construir_urls(itens)
        async with FirecrawlScraper() as scraper:
            scraped = await scraper.processar_lote(itens_com_url, max_concurrent=2)
        return await self.parser.processar_lote([s for s in scraped if s.markdown])
