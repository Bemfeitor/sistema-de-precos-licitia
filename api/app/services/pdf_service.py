import io
import json
import logging
import re
from typing import Any, List, Optional

import google.generativeai as genai
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class ItemExtracted(BaseModel):
    numero_item: Optional[str] = Field(None, description="Número abstrato do item, se houver")
    descricao: str = Field(
        ...,
        description="Nome do produto ou serviço (se não encontrar texto limpo, coloque o bloco inteiro)",
    )
    quantidade: Optional[Any] = Field(None, description="Quantidade do produto")
    unidade_medida: Optional[str] = Field(None, description="Unidade de medida")
    valor_unitario_estimado: Optional[Any] = Field(None, description="Valor unitário estimado ou máximo aceito")
    valor_total_estimado: Optional[Any] = Field(None, description="Valor total estimado")


class LoteExtracted(BaseModel):
    numero_lote: Optional[str] = Field(None, description="Número do lote (ou grupo) ao qual pertence")
    itens: List[ItemExtracted]


class ExtracaoEdital(BaseModel):
    documento_valido: bool = Field(
        ...,
        description="Verdadeiro se encontrou qualquer indício de tabela, preço ou produto",
    )
    lotes: List[LoteExtracted]


MAX_GEMINI_TEXT_CHARS = 100000
CHUNK_TARGET_CHARS = 35000
PAGE_MARKER_RE = re.compile(r"--- P[ÁA]GINA\s+(?P<page>\d+)\s+---")
EXTRACTION_SYSTEM_PROMPT = (
    "Atue como um extrator de dados de alta precisão. Sua tarefa é ler o texto de um edital, "
    "ata de registro de preços, lista de compras ou planilha textual e extrair TODOS os produtos/serviços listados.\n"
    "REGRAS CRÍTICAS:\n"
    "1. Extraia o máximo de itens possível. Não pule nenhum item.\n"
    "2. Para cada item, identifique: descrição, quantidade, unidade de medida, valor unitário estimado, valor total estimado e número do item.\n"
    "3. Se o documento estiver em formato de ARP/ata, procure anexos, quadros de itens, listas com produtos e blocos com descrição + valor.\n"
    "4. Ignore cláusulas jurídicas, texto contratual e regras administrativas que não representem itens compráveis.\n"
    "5. Se encontrar qualquer item, defina documento_valido como true.\n"
    "6. Retorne apenas JSON válido, sem markdown.\n"
    "Formato esperado:\n"
    '{"documento_valido": true, "lotes": [{"numero_lote": "1", "itens": [{"numero_item": "1", "descricao": "Papel A4", "quantidade": 10.0, "unidade_medida": "CX", "valor_unitario_estimado": 25.50, "valor_total_estimado": 255.0}]}]}'
)
FULL_LINE_PATTERN = re.compile(
    r"^(?P<item>\d{1,4})\s+"
    r"(?P<descricao>.+?)\s+"
    r"(?P<marca>[A-ZÀ-Ú0-9./-]{2,})\s+"
    r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
    r"(?P<unidade>[A-Za-zÀ-ÿ./]+)\s+"
    r"(?P<valor>\d[\d.,]*)$"
)
SPLIT_META_PATTERN = re.compile(
    r"^(?P<item>\d{1,4})\s+"
    r"(?P<marca>[A-ZÀ-Ú0-9./-]{2,})\s+"
    r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
    r"(?P<unidade>[A-Za-zÀ-ÿ./]+)\s+"
    r"(?P<valor>\d[\d.,]*)$"
)
PRICE_HINT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
HEADER_LIKE_CELL_RE = re.compile(
    r"^(?:descri(?:cao|ção)|item|lote|quant(?:idade)?|un(?:id(?:ade)?)?|valor(?:es)?|observa(?:cao|ção)|marca)\:?$",
    re.IGNORECASE,
)
EXTRACTION_NOISE_RE = re.compile(
    r"^(?:descri(?:cao|ção)|observa(?:cao|ção)|item|itens|lote|lotes|marca|quant(?:idade)?|un(?:id(?:ade)?)?|valor(?:es)?|estim\s*unit)\:?$",
    re.IGNORECASE,
)
FRACTIONAL_INCH_RE = re.compile(
    r'(?<!\d)(?P<whole>\d)\.\s*(?P<fraction>\d/\d)(?=(?:\s*(?:pol|")|\b))'
)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate for logging/cost analysis."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


def _extract_page_sections(raw_text: str) -> List[tuple[int, str]]:
    matches = list(PAGE_MARKER_RE.finditer(raw_text))
    if not matches:
        return [(1, raw_text)]

    pages: List[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        pages.append((int(match.group("page")), raw_text[start:end].strip()))
    return pages


def _score_page_for_items(page_text: str) -> int:
    lines = [re.sub(r"\s+", " ", line).strip() for line in page_text.splitlines() if line.strip()]
    score = 0

    for line in lines:
        upper = line.upper()
        if "ITEM" in upper and ("ESPECIFICA" in upper or "DESCRI" in upper):
            score += 4
        if ("QUANT" in upper and "VALOR" in upper) or upper in {"ESTIM UNIT", "QUANT VALOR"}:
            score += 2
        if "R$" in upper or PRICE_HINT_PATTERN.search(line):
            score += 1
        if FULL_LINE_PATTERN.match(line) or SPLIT_META_PATTERN.match(line):
            score += 3

    return score


def _select_candidate_page_text(raw_text: str) -> str:
    pages = _extract_page_sections(raw_text)
    if len(pages) <= 2:
        return raw_text

    direct_hits = {index for index, (_, text) in enumerate(pages) if _score_page_for_items(text) >= 3}
    if not direct_hits:
        return raw_text

    selected_indices = set()
    for index in direct_hits:
        selected_indices.add(index)
        if index > 0:
            selected_indices.add(index - 1)
        if index + 1 < len(pages):
            selected_indices.add(index + 1)

    candidate_text = "\n".join(pages[index][1] for index in sorted(selected_indices)).strip()
    if not candidate_text:
        return raw_text

    logger.info(
        "Seleção de páginas para LLM: %s/%s páginas (%s -> %s chars, ~%s -> ~%s tokens).",
        len(selected_indices),
        len(pages),
        len(raw_text),
        len(candidate_text),
        _estimate_tokens(raw_text),
        _estimate_tokens(candidate_text),
    )
    return candidate_text


def parse_page_ranges(pages_config: str, max_pages: int) -> List[int]:
    """Parse a string like '1-3, 5' into a list of 0-based page indices: [0, 1, 2, 4]."""
    if not pages_config or not pages_config.strip():
        return list(range(max_pages))

    selected_pages = set()
    for part in pages_config.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            try:
                start, end = part.split("-")
                start_idx = int(start.strip()) - 1
                end_idx = int(end.strip()) - 1
                start_idx = max(0, min(start_idx, max_pages - 1))
                end_idx = max(0, min(end_idx, max_pages - 1))
                if start_idx <= end_idx:
                    for page_idx in range(start_idx, end_idx + 1):
                        selected_pages.add(page_idx)
            except ValueError:
                continue
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < max_pages:
                    selected_pages.add(idx)
            except ValueError:
                continue

    if not selected_pages:
        return list(range(max_pages))

    return sorted(selected_pages)


def safe_float(val) -> Optional[float]:
    """Safely convert strings like '1.500,00', '10,5', or 'R$ 10.0' into valid floats."""
    if val is None or val == "":
        return None

    val_str = str(val).strip().upper().replace("R$", "").replace(" ", "")
    if val_str == "" or val_str in {"NULL", "NULO"}:
        return None

    try:
        if "," in val_str and "." in val_str:
            if val_str.rfind(",") > val_str.rfind("."):
                val_str = val_str.replace(".", "").replace(",", ".")
            else:
                val_str = val_str.replace(",", "")
        elif "," in val_str:
            val_str = val_str.replace(",", ".")

        return float(val_str)
    except Exception:
        return None


def _is_header_like_cell(value: Any) -> bool:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    if not normalized:
        return True
    return bool(HEADER_LIKE_CELL_RE.match(normalized))


def _normalize_item_key(numero_lote: Optional[str], item: ItemExtracted) -> tuple[str, str, str]:
    descricao = re.sub(r"\s+", " ", (item.descricao or "").strip().lower())
    return (numero_lote or "", item.numero_item or "", descricao)


def _normalize_measure_notation(value: Any, item_number: Optional[str] = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""

    text = (
        text.replace("â€™", "'")
        .replace("â€œ", '"')
        .replace("â€", '"')
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    text = FRACTIONAL_INCH_RE.sub(r"\g<whole> \g<fraction>", text)

    if item_number and str(item_number).isdigit():
        text = re.sub(
            rf'(?<!\d)(?P<whole>\d)\.{re.escape(str(item_number))}(?=(?:\s*(?:pol|")|\b))',
            r"\g<whole>",
            text,
        )

    text = re.sub(r'\s+"', '"', text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -:;")


def _sanitize_item(item: ItemExtracted) -> Optional[ItemExtracted]:
    numero_item = str(item.numero_item).strip() if item.numero_item else None
    descricao = _normalize_measure_notation(item.descricao, item_number=numero_item)
    if not descricao or len(descricao) < 3:
        return None
    if _is_header_like_cell(descricao) or EXTRACTION_NOISE_RE.match(descricao):
        return None

    unidade = str(item.unidade_medida).strip() if item.unidade_medida else None
    return ItemExtracted(
        numero_item=numero_item,
        descricao=descricao,
        quantidade=safe_float(item.quantidade),
        unidade_medida=unidade,
        valor_unitario_estimado=safe_float(item.valor_unitario_estimado),
        valor_total_estimado=safe_float(item.valor_total_estimado),
    )


def _derive_unit_price_from_total(
    quantity: Optional[float],
    unit_price: Optional[float],
    total_price: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    qty = safe_float(quantity)
    unit_val = safe_float(unit_price)
    total_val = safe_float(total_price)

    if qty and qty > 0:
        if total_val and (not unit_val or unit_val <= 0):
            unit_val = round(total_val / qty, 2)
        elif unit_val and unit_val > 0 and (not total_val or total_val <= 0):
            total_val = round(unit_val * qty, 2)

    return unit_val, total_val


def _sanitize_extraction(extraction: ExtracaoEdital) -> ExtracaoEdital:
    cleaned_lotes: List[LoteExtracted] = []
    seen: set[tuple[str, str, str]] = set()

    for lote in extraction.lotes:
        lote_num = str(lote.numero_lote).strip() if lote.numero_lote else None
        cleaned_items: List[ItemExtracted] = []
        for raw_item in lote.itens:
            cleaned_item = _sanitize_item(raw_item)
            if not cleaned_item:
                continue

            key = _normalize_item_key(lote_num, cleaned_item)
            if key in seen:
                continue
            seen.add(key)
            cleaned_items.append(cleaned_item)

        if cleaned_items:
            cleaned_lotes.append(LoteExtracted(numero_lote=lote_num, itens=cleaned_items))

    return ExtracaoEdital(documento_valido=bool(cleaned_lotes), lotes=cleaned_lotes)


def _merge_extractions(extractions: List[ExtracaoEdital]) -> ExtracaoEdital:
    merged: dict[str, list[ItemExtracted]] = {}
    seen: set[tuple[str, str, str]] = set()

    for extraction in extractions:
        for lote in extraction.lotes:
            lote_num = str(lote.numero_lote) if lote.numero_lote else "1"
            merged.setdefault(lote_num, [])
            for item in lote.itens:
                key = _normalize_item_key(lote_num, item)
                if key in seen:
                    continue
                seen.add(key)
                merged[lote_num].append(item)

    return _sanitize_extraction(ExtracaoEdital(
        documento_valido=any(extraction.documento_valido for extraction in extractions) and any(merged.values()),
        lotes=[
            LoteExtracted(numero_lote=lote_num, itens=items)
            for lote_num, items in merged.items()
            if items
        ],
    ))


def _split_text_into_chunks(raw_text: str, max_chars: int = CHUNK_TARGET_CHARS) -> List[str]:
    pages = re.split(r"(?=--- PÁGINA \d+ ---)", raw_text)
    pages = [page for page in pages if page.strip()]
    if not pages:
        return [raw_text[:MAX_GEMINI_TEXT_CHARS]]

    chunks: List[str] = []
    current = ""
    for page in pages:
        if len(page) > max_chars:
            if current.strip():
                chunks.append(current)
                current = ""
            for start in range(0, len(page), max_chars):
                chunks.append(page[start:start + max_chars])
            continue

        if len(current) + len(page) > max_chars and current.strip():
            chunks.append(current)
            current = page
        else:
            current += page

    if current.strip():
        chunks.append(current)

    return [chunk[:MAX_GEMINI_TEXT_CHARS] for chunk in chunks if chunk.strip()]


def _parse_products_from_text_table(raw_text: str) -> ExtracaoEdital:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    header_found = False
    pending_description: list[str] = []
    itens: list[ItemExtracted] = []

    full_line_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?P<descricao>.+?)\s+"
        r"(?P<marca>[A-ZÀ-Ú0-9●./-]{2,})\s+"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unidade>[A-Za-zÀ-ÿ./]+)\s+"
        r"(?P<valor>\d[\d.,]*)$"
    )
    split_meta_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?P<marca>[A-ZÀ-Ú0-9●./-]{2,})\s+"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unidade>[A-Za-zÀ-ÿ./]+)\s+"
        r"(?P<valor>\d[\d.,]*)$"
    )

    def is_structural_noise(line: str) -> bool:
        return (
            line.startswith("--- P")
            or line.startswith("Página")
            or "PREFEITURA DO MUNICÍPIO" in line.upper()
            or "ESTADO DO PARANÁ" in line.upper()
            or "CNPJ" in line.upper()
        )

    stop_markers = (
        "MUNICÍPIO DE",
        "PREFEITURA DO MUNICÍPIO",
        "FH CONSTRUCOES",
        "CPF.",
        "RG.",
    )

    index = 0
    while index < len(lines):
        line = lines[index]
        upper = line.upper()
        if not header_found and "ITEM" in upper and "ESPECIFICA" in upper:
            header_found = True
            index += 1
            continue

        if not header_found:
            if full_line_pattern.match(line) or split_meta_pattern.match(line):
                header_found = True
            else:
                index += 1
                continue

        if any(marker in upper for marker in stop_markers):
            break

        if is_structural_noise(line) or upper in {"QUANT VALOR", "ESTIM UNIT"}:
            index += 1
            continue

        full_match = full_line_pattern.match(line)
        if full_match:
            descricao_parts = pending_description + [full_match.group("descricao")]
            pending_description = []
            itens.append(
                ItemExtracted(
                    numero_item=full_match.group("item"),
                    descricao=" ".join(descricao_parts).strip(" -"),
                    quantidade=safe_float(full_match.group("quantidade")),
                    unidade_medida=full_match.group("unidade"),
                    valor_unitario_estimado=safe_float(full_match.group("valor")),
                    valor_total_estimado=None,
                )
            )
            index += 1
            continue

        split_match = split_meta_pattern.match(line)
        if split_match:
            descricao_parts = list(pending_description)
            pending_description = []

            look_ahead = index + 1
            while look_ahead < len(lines):
                next_line = lines[look_ahead]
                next_upper = next_line.upper()
                if any(marker in next_upper for marker in stop_markers):
                    break
                if "ITEM" in next_upper and "ESPECIFICA" in next_upper:
                    break
                if is_structural_noise(next_line):
                    look_ahead += 1
                    continue
                if full_line_pattern.match(next_line) or split_meta_pattern.match(next_line):
                    break
                descricao_parts.append(next_line)
                look_ahead += 1

            itens.append(
                ItemExtracted(
                    numero_item=split_match.group("item"),
                    descricao=" ".join(descricao_parts).strip(" -"),
                    quantidade=safe_float(split_match.group("quantidade")),
                    unidade_medida=split_match.group("unidade"),
                    valor_unitario_estimado=safe_float(split_match.group("valor")),
                    valor_total_estimado=None,
                )
            )
            index = look_ahead
            continue

        pending_description.append(line)
        index += 1

    logger.info(f"Fallback textual encontrou {len(itens)} itens.")
    return _sanitize_extraction(ExtracaoEdital(
        documento_valido=len(itens) > 0,
        lotes=[LoteExtracted(numero_lote="1", itens=itens)] if itens else [],
    ))


def _parse_products_from_structured_rows(raw_text: str) -> ExtracaoEdital:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    full_row_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?:(?P<descricao>.+?)\s+)?"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unidade>[A-Za-zÀ-ÿ./º°Çç]+)\s+"
        r"R\$\s*(?P<valor_unit>\d[\d.,]*)\s+"
        r"(?:R\$\s*)?(?P<valor_total>\d[\d.,]*)$"
    )
    partial_row_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?:(?P<descricao>.+?)\s+)?"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<unidade>[A-Za-zÀ-ÿ./º°Çç]+)\s+"
        r"R\$\s*(?P<valor_unit>\d[\d.,]*)$"
    )
    total_only_pattern = re.compile(r"^(?:R\$\s*)?(?P<valor_total>\d[\d.,]*)$")
    lote_pattern = re.compile(r"^LOTE\s+(\d+)", re.IGNORECASE)

    def is_structural_noise(line: str) -> bool:
        upper = line.upper()
        return (
            line.startswith("--- P")
            or line.startswith("PÃ¡gina")
            or upper in {"VALOR TOTAL", "UNID. VALOR UNIT.", "MEDIDA (R$)", "(R$)", "R$"}
            or "VALOR TOTAL DO LOTE" in upper
            or "PREFEITURA DO MUNICÃPIO" in upper
            or "ESTADO DO PARANÃ" in upper
            or "PROCESSO ADMINISTRATIVO" in upper
            or "MODALIDADE:" in upper
            or "TIPO:" in upper
            or "OBJETO:" in upper
            or "CNPJ" in upper
        )

    def is_row(line: str) -> bool:
        return bool(full_row_pattern.match(line) or partial_row_pattern.match(line))

    def looks_like_new_description(line: str) -> bool:
        if not line:
            return False
        return bool(re.match(r"^[A-ZÀ-Ý]", line))

    def collect_tail(start_index: int) -> tuple[list[str], int]:
        parts: list[str] = []
        index = start_index
        while index < len(lines):
            line = lines[index]
            upper = line.upper()
            if lote_pattern.match(line):
                break
            if "ITEM" in upper and "DESCRI" in upper:
                break
            if is_row(line):
                break
            if total_only_pattern.match(line):
                break
            if looks_like_new_description(line):
                break
            if is_structural_noise(line):
                index += 1
                continue
            parts.append(line)
            index += 1
        return parts, index

    itens_por_lote: dict[str, list[ItemExtracted]] = {}
    current_lote = "1"
    pending_description: list[str] = []
    header_found = False
    index = 0

    while index < len(lines):
        line = lines[index]
        upper = line.upper()
        lote_match = lote_pattern.match(line)
        if lote_match:
            current_lote = lote_match.group(1).lstrip("0") or lote_match.group(1)
            pending_description = []
            index += 1
            continue

        if not header_found and "ITEM" in upper and "DESCRI" in upper:
            header_found = True
            index += 1
            continue

        if not header_found and is_row(line):
            header_found = True

        if not header_found or is_structural_noise(line):
            index += 1
            continue

        if "ITEM" in upper and "DESCRI" in upper:
            pending_description = []
            index += 1
            continue

        match = full_row_pattern.match(line) or partial_row_pattern.match(line)
        if not match:
            pending_description.append(line)
            index += 1
            continue

        descricao_parts = list(pending_description)
        pending_description = []
        inline_desc = (match.group("descricao") or "").strip()
        if inline_desc:
            descricao_parts.append(inline_desc)

        next_index = index + 1
        valor_total = match.groupdict().get("valor_total")
        if not valor_total and next_index < len(lines):
            total_match = total_only_pattern.match(lines[next_index])
            if total_match:
                valor_total = total_match.group("valor_total")
                next_index += 1

        tail_parts, next_index = collect_tail(next_index)
        descricao_parts.extend(tail_parts)
        descricao = " ".join(part for part in descricao_parts if part).strip(" -")
        if descricao:
            itens_por_lote.setdefault(current_lote, []).append(
                ItemExtracted(
                    numero_item=match.group("item"),
                    descricao=descricao,
                    quantidade=safe_float(match.group("quantidade")),
                    unidade_medida=match.group("unidade"),
                    valor_unitario_estimado=safe_float(match.group("valor_unit")),
                    valor_total_estimado=safe_float(valor_total),
                )
            )

        index = next_index

    total_itens = sum(len(itens) for itens in itens_por_lote.values())
    logger.info(f"Parser estruturado encontrou {total_itens} itens.")
    return _sanitize_extraction(ExtracaoEdital(
        documento_valido=total_itens > 0,
        lotes=[
            LoteExtracted(numero_lote=lote_num, itens=itens)
            for lote_num, itens in itens_por_lote.items()
            if itens
        ],
    ))


def _build_extraction_prompt(truncated_text: str) -> str:
    return f"{EXTRACTION_SYSTEM_PROMPT}\n\nTexto para extrair:\n{truncated_text}"


def _parse_llm_json(raw_json: str) -> ExtracaoEdital:
    payload = (raw_json or "").strip()
    if payload.startswith("```json"):
        payload = payload[7:]
    elif payload.startswith("```"):
        payload = payload[3:]
    if payload.endswith("```"):
        payload = payload[:-3]
    payload = payload.strip()

    parsed_dict = json.loads(payload)
    lotes = []
    for lote in parsed_dict.get("lotes", []):
        itens = []
        for item in lote.get("itens", []):
            itens.append(
                ItemExtracted(
                    numero_item=str(item.get("numero_item")) if item.get("numero_item") else None,
                    descricao=str(item.get("descricao", "Item sem nome")),
                    quantidade=safe_float(item.get("quantidade")),
                    unidade_medida=str(item.get("unidade_medida")) if item.get("unidade_medida") else None,
                    valor_unitario_estimado=safe_float(item.get("valor_unitario_estimado")),
                    valor_total_estimado=safe_float(item.get("valor_total_estimado")),
                )
            )
        lotes.append(
            LoteExtracted(
                numero_lote=str(lote.get("numero_lote")) if lote.get("numero_lote") else None,
                itens=itens,
            )
        )

    return _sanitize_extraction(
        ExtracaoEdital(documento_valido=parsed_dict.get("documento_valido", True), lotes=lotes)
    )


def extract_text_from_pdf(file_bytes: bytes, pages_config: str = None) -> str:
    """Extract text from PDF using pdfplumber with PyPDF fallback."""
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            selected_indices = parse_page_ranges(pages_config, len(pdf.pages))
            for idx in selected_indices:
                page_text = pdf.pages[idx].extract_text()
                if page_text:
                    text += f"--- PÁGINA {idx + 1} ---\n{page_text}\n"
        if text.strip() and len(text.strip()) > 100:
            logger.info("Text extracted via pdfplumber")
            return text.strip()
    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        selected_indices = parse_page_ranges(pages_config, len(reader.pages))
        for idx in selected_indices:
            page_text = reader.pages[idx].extract_text()
            if page_text:
                text += f"--- PÁGINA {idx + 1} ---\n{page_text}\n"
        if text.strip() and len(text.strip()) > 100:
            logger.info("Text extracted via PyPDF")
            return text.strip()
    except Exception as e:
        logger.warning(f"PyPDF failed: {e}")

    return ""


def _parse_products_with_gemini(raw_text: str) -> ExtracaoEdital:
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        logger.info("Gemini não configurado para extração")
        return ExtracaoEdital(documento_valido=False, lotes=[])

    truncated_text = raw_text[:MAX_GEMINI_TEXT_CHARS]
    prompt = _build_extraction_prompt(truncated_text)
    logger.info(
        "Enviando para Gemini %s caracteres (~%s tokens).",
        len(prompt),
        _estimate_tokens(prompt),
    )

    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(response_mime_type="application/json"),
        )
        raw_json = response.text.strip()
        usage = getattr(response, "usage_metadata", None)
        if usage:
            logger.info(
                "Gemini usage prompt=%s candidate=%s total=%s",
                getattr(usage, "prompt_token_count", None),
                getattr(usage, "candidates_token_count", None),
                getattr(usage, "total_token_count", None),
            )
        logger.info("Gemini Response Length: %s chars (~%s tokens)", len(raw_json), _estimate_tokens(raw_json))
        return _parse_llm_json(raw_json)
    except Exception as e:
        logger.error(f"Gemini-based extraction failed: {e}")
        return ExtracaoEdital(documento_valido=False, lotes=[])


def _parse_products_with_kimi(raw_text: str) -> ExtracaoEdital:
    settings = get_settings()
    if not settings.KIMI_API_KEY:
        logger.info("Kimi não configurado para extração")
        return ExtracaoEdital(documento_valido=False, lotes=[])

    truncated_text = raw_text[:MAX_GEMINI_TEXT_CHARS]
    prompt = f"Texto para extrair:\n{truncated_text}"
    logger.info(
        "Enviando para Kimi %s caracteres (~%s tokens) via %s usando %s.",
        len(EXTRACTION_SYSTEM_PROMPT) + len(prompt),
        _estimate_tokens(EXTRACTION_SYSTEM_PROMPT) + _estimate_tokens(prompt),
        settings.KIMI_BASE_URL,
        settings.KIMI_MODEL,
    )

    try:
        client = OpenAI(api_key=settings.KIMI_API_KEY, base_url=settings.KIMI_BASE_URL)
        response = client.chat.completions.create(
            model=settings.KIMI_MODEL,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw_json = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        if usage:
            logger.info(
                "Kimi usage prompt=%s completion=%s total=%s",
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                getattr(usage, "total_tokens", None),
            )
        logger.info("Kimi Response Length: %s chars (~%s tokens)", len(raw_json), _estimate_tokens(raw_json))
        return _parse_llm_json(raw_json)
    except Exception as e:
        logger.error(f"Kimi-based extraction failed: {e}")
        return ExtracaoEdital(documento_valido=False, lotes=[])


def _parse_products_from_chunk(raw_text: str) -> ExtracaoEdital:
    settings = get_settings()
    if not settings.GEMINI_API_KEY and not settings.KIMI_API_KEY:
        logger.error("ERRO: nenhuma API key de extração configurada (Gemini/Kimi)!")
        return ExtracaoEdital(documento_valido=False, lotes=[])

    gemini_result = _parse_products_with_gemini(raw_text)
    if gemini_result.documento_valido and gemini_result.lotes:
        return gemini_result

    kimi_result = _parse_products_with_kimi(raw_text)
    if kimi_result.documento_valido and kimi_result.lotes:
        return kimi_result

    return ExtracaoEdital(documento_valido=False, lotes=[])


def _parse_products_from_service_table(raw_text: str) -> ExtracaoEdital:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    row_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?:(?P<descricao>.+?)\s+)?"
        r"(?P<unidade>[A-Za-zÃ€-Ã¿./ÂºÂ°Ã‡Ã§]{1,8})\s+"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<valor_unit>\d[\d.,]*)\s+"
        r"(?P<valor_total>\d[\d.,]*)$"
    )
    service_banner_pattern = re.compile(
        r"^SERVI[CÃ‡]O\s+COM\s+FORNECIMENTO\s+DE\s+MATERIAL(?:\s+SENDO)?\:?\s*$",
        re.IGNORECASE,
    )

    def is_structural_noise(line: str) -> bool:
        upper = line.upper()
        return (
            line.startswith("--- P")
            or upper in {"VALOR", "UNID. DE VALOR", "MEDIDA TOTAL (R$)", "(R$)"}
            or "PROCESSO ADMINISTRATIVO" in upper
            or "MODALIDADE:" in upper
            or "TIPO:" in upper
            or "OBJETO:" in upper
            or "CNPJ" in upper
        )

    itens: list[ItemExtracted] = []
    pending_description: list[str] = []
    header_found = False
    index = 0

    while index < len(lines):
        line = lines[index]
        upper = line.upper()

        if not header_found and "ITEM" in upper and "DESCRI" in upper and ("QTDE" in upper or "QUANTIDADE" in upper):
            header_found = True
            index += 1
            continue

        if not header_found:
            index += 1
            continue

        if is_structural_noise(line):
            index += 1
            continue

        if "ITEM" in upper and "DESCRI" in upper:
            pending_description = []
            index += 1
            continue

        if service_banner_pattern.match(line):
            index += 1
            continue

        match = row_pattern.match(line)
        if not match:
            pending_description.append(line)
            index += 1
            continue

        descricao_parts = list(pending_description)
        pending_description = []

        inline_desc = (match.group("descricao") or "").strip()
        if inline_desc:
            descricao_parts.append(inline_desc)

        next_index = index + 1
        while next_index < len(lines):
            next_line = lines[next_index]
            next_upper = next_line.upper()
            if row_pattern.match(next_line):
                break
            if service_banner_pattern.match(next_line):
                break
            if "ITEM" in next_upper and "DESCRI" in next_upper:
                break
            if is_structural_noise(next_line):
                next_index += 1
                continue
            descricao_parts.append(next_line)
            next_index += 1

        descricao = " ".join(part for part in descricao_parts if part).strip(" -")
        if descricao:
            itens.append(
                ItemExtracted(
                    numero_item=match.group("item"),
                    descricao=descricao,
                    quantidade=safe_float(match.group("quantidade")),
                    unidade_medida=match.group("unidade"),
                    valor_unitario_estimado=safe_float(match.group("valor_unit")),
                    valor_total_estimado=safe_float(match.group("valor_total")),
                )
            )

        index = next_index

    logger.info(f"Parser de servicos encontrou {len(itens)} itens.")
    return _sanitize_extraction(ExtracaoEdital(
        documento_valido=len(itens) > 0,
        lotes=[LoteExtracted(numero_lote="1", itens=itens)] if itens else [],
    ))


def _parse_products_from_service_table_v2(raw_text: str) -> ExtracaoEdital:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]

    row_pattern = re.compile(
        r"^(?P<item>\d{1,4})\s+"
        r"(?:(?P<descricao>.+?)\s+)?"
        r"(?P<unidade>\S{1,8})\s+"
        r"(?P<quantidade>\d+(?:[.,]\d+)?)\s+"
        r"(?P<valor_unit>\d[\d.,]*)\s+"
        r"(?P<valor_total>\d[\d.,]*)$"
    )
    service_banner_pattern = re.compile(
        r"^SERVI.*FORNECIMENTO\s+DE\s+MATERIAL(?:\s+SENDO)?\:?\s*$",
        re.IGNORECASE,
    )

    def is_structural_noise(line: str) -> bool:
        upper = line.upper()
        return (
            line.startswith("--- P")
            or upper in {"VALOR", "UNID. DE VALOR", "MEDIDA TOTAL (R$)", "(R$)"}
            or "PROCESSO ADMINISTRATIVO" in upper
            or "MODALIDADE:" in upper
            or "TIPO:" in upper
            or "OBJETO:" in upper
            or "CNPJ" in upper
        )

    itens: list[ItemExtracted] = []
    pending_description: list[str] = []
    header_found = False
    index = 0

    while index < len(lines):
        line = lines[index]
        upper = line.upper()

        if not header_found and "ITEM" in upper and "DESCRI" in upper and ("QTDE" in upper or "QUANTIDADE" in upper):
            header_found = True
            index += 1
            continue

        if not header_found:
            index += 1
            continue

        if is_structural_noise(line):
            index += 1
            continue

        if "ITEM" in upper and "DESCRI" in upper:
            pending_description = []
            index += 1
            continue

        if service_banner_pattern.match(line):
            index += 1
            continue

        match = row_pattern.match(line)
        if not match:
            pending_description.append(line)
            index += 1
            continue

        descricao_parts = list(pending_description)
        pending_description = []

        inline_desc = (match.group("descricao") or "").strip()
        if inline_desc:
            descricao_parts.append(inline_desc)

        next_index = index + 1
        while next_index < len(lines):
            next_line = lines[next_index]
            next_upper = next_line.upper()
            if row_pattern.match(next_line):
                break
            if service_banner_pattern.match(next_line):
                break
            if "ITEM" in next_upper and "DESCRI" in next_upper:
                break
            if is_structural_noise(next_line):
                next_index += 1
                continue
            descricao_parts.append(next_line)
            next_index += 1

        descricao = " ".join(part for part in descricao_parts if part).strip(" -")
        if descricao:
            itens.append(
                ItemExtracted(
                    numero_item=match.group("item"),
                    descricao=descricao,
                    quantidade=safe_float(match.group("quantidade")),
                    unidade_medida=match.group("unidade"),
                    valor_unitario_estimado=safe_float(match.group("valor_unit")),
                    valor_total_estimado=safe_float(match.group("valor_total")),
                )
            )

        index = next_index

    logger.info(f"Parser de servicos v2 encontrou {len(itens)} itens.")
    return _sanitize_extraction(ExtracaoEdital(
        documento_valido=len(itens) > 0,
        lotes=[LoteExtracted(numero_lote="1", itens=itens)] if itens else [],
    ))


def parse_products_from_text(raw_text: str, pages_config: str = None) -> ExtracaoEdital:
    """Parse product list from extracted PDF text using Gemini, Kimi, and chunk merge."""
    table_result = _parse_products_from_service_table_v2(raw_text)
    if table_result.documento_valido:
        logger.info("Parser textual de servicos resolveu o PDF sem LLM.")
        return table_result

    table_result = _parse_products_from_structured_rows(raw_text)
    if not table_result.documento_valido:
        table_result = _parse_products_from_text_table(raw_text)
    if table_result.documento_valido:
        logger.info("Parser textual resolveu o PDF sem LLM.")
        return table_result

    llm_text = _select_candidate_page_text(raw_text)
    chunks = _split_text_into_chunks(llm_text)
    logger.info(
        "PDF parser recebeu %s caracteres (~%s tokens) divididos em %s bloco(s).",
        len(llm_text),
        _estimate_tokens(llm_text),
        len(chunks),
    )
    if len(chunks) == 1:
        result = _parse_products_from_chunk(chunks[0])
        if result.documento_valido and result.lotes:
            return _sanitize_extraction(result)
        return ExtracaoEdital(documento_valido=False, lotes=[])

    logger.info(f"PDF grande detectado, extraindo em {len(chunks)} blocos")
    extractions = [_parse_products_from_chunk(chunk) for chunk in chunks]
    merged = _merge_extractions(extractions)
    if merged.documento_valido:
        return _sanitize_extraction(merged)
    return ExtracaoEdital(documento_valido=False, lotes=[])


def parse_products_heuristic(file_bytes: bytes, pages_config: str = None) -> ExtracaoEdital:
    """Extração 'grátis' usando tabelas nativas do pdfplumber sem IA."""
    import pdfplumber

    logger.info("Iniciando extração heurística (Free Mode)...")
    itens = []

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            selected_indices = parse_page_ranges(pages_config, len(pdf.pages))
            for idx in selected_indices:
                page = pdf.pages[idx]
                tables = page.extract_tables()

                for table in tables:
                    if not table or len(table) < 2:
                        continue

                    header = [str(c).lower() if c else "" for c in table[0]]
                    desc_idx = -1
                    qty_idx = -1
                    price_idx = -1
                    item_idx = -1
                    und_idx = -1

                    for i, col in enumerate(header):
                        if any(k in col for k in ["descri", "objeto", "produto", "especif"]):
                            desc_idx = i
                        elif any(k in col for k in ["qtd", "quant", "unid"]):
                            if "unid" in col and und_idx == -1:
                                und_idx = i
                            else:
                                qty_idx = i
                        elif any(k in col for k in ["valor", "preço", "unit", "estimado"]):
                            price_idx = i
                        elif any(k in col for k in ["item", "lote", "pos"]):
                            item_idx = i
                        elif "und" in col or "unidade" in col:
                            und_idx = i

                    if desc_idx == -1:
                        continue

                    for row in table[1:]:
                        if not row or len(row) <= desc_idx:
                            continue
                        desc = str(row[desc_idx]).strip() if row[desc_idx] else ""
                        if not desc or len(desc) < 3:
                            continue
                        if _is_header_like_cell(desc):
                            continue
                        non_empty_cells = [str(cell).strip() for cell in row if str(cell or "").strip()]
                        if non_empty_cells and all(_is_header_like_cell(cell) for cell in non_empty_cells):
                            continue

                        qty = safe_float(row[qty_idx]) if qty_idx != -1 and row[qty_idx] else 1.0
                        price = safe_float(row[price_idx]) if price_idx != -1 and row[price_idx] else 0.0
                        num_item = str(row[item_idx]).strip() if item_idx != -1 and row[item_idx] else None
                        und = str(row[und_idx]).strip() if und_idx != -1 and row[und_idx] else "UN"

                        itens.append(
                            ItemExtracted(
                                numero_item=num_item,
                                descricao=desc,
                                quantidade=qty,
                                unidade_medida=und,
                                valor_unitario_estimado=price,
                                valor_total_estimado=(qty or 1) * (price or 0),
                            )
                        )

        logger.info(f"Heurística encontrou {len(itens)} itens.")
        return _sanitize_extraction(ExtracaoEdital(
            documento_valido=len(itens) > 0,
            lotes=[LoteExtracted(numero_lote="1", itens=itens)],
        ))
    except Exception as e:
        logger.error(f"Heuristic extraction failed: {e}")
        return ExtracaoEdital(documento_valido=False, lotes=[])


def parse_products_heuristic_v2(file_bytes: bytes, pages_config: str = None) -> ExtracaoEdital:
    """Improved table extraction with separate unit and total price detection."""
    import pdfplumber

    logger.info("Iniciando extração heurística v2 (Free Mode)...")
    itens: list[ItemExtracted] = []

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            selected_indices = parse_page_ranges(pages_config, len(pdf.pages))
            for idx in selected_indices:
                page = pdf.pages[idx]
                for table in page.extract_tables():
                    if not table or len(table) < 2:
                        continue

                    header = [str(cell).lower() if cell else "" for cell in table[0]]
                    desc_idx = -1
                    qty_idx = -1
                    unit_price_idx = -1
                    total_price_idx = -1
                    item_idx = -1
                    und_idx = -1

                    for column_idx, column_name in enumerate(header):
                        if any(token in column_name for token in ["descri", "objeto", "produto", "especif"]):
                            desc_idx = column_idx
                        elif any(token in column_name for token in ["qtd", "quant", "unid"]):
                            if "unid" in column_name and und_idx == -1:
                                und_idx = column_idx
                            else:
                                qty_idx = column_idx
                        elif "total" in column_name:
                            total_price_idx = column_idx
                        elif any(token in column_name for token in ["valor", "pre", "unit", "estimado"]):
                            unit_price_idx = column_idx
                        elif any(token in column_name for token in ["item", "lote", "pos"]):
                            item_idx = column_idx
                        elif "und" in column_name or "unidade" in column_name:
                            und_idx = column_idx

                    if desc_idx == -1:
                        continue

                    for row in table[1:]:
                        if not row or len(row) <= desc_idx:
                            continue

                        desc = str(row[desc_idx]).strip() if row[desc_idx] else ""
                        if not desc or len(desc) < 3 or _is_header_like_cell(desc):
                            continue

                        non_empty_cells = [str(cell).strip() for cell in row if str(cell or "").strip()]
                        if non_empty_cells and all(_is_header_like_cell(cell) for cell in non_empty_cells):
                            continue

                        qty = safe_float(row[qty_idx]) if qty_idx != -1 and row[qty_idx] else 1.0
                        unit_price = (
                            safe_float(row[unit_price_idx])
                            if unit_price_idx != -1 and row[unit_price_idx]
                            else None
                        )
                        total_price = (
                            safe_float(row[total_price_idx])
                            if total_price_idx != -1 and row[total_price_idx]
                            else None
                        )
                        unit_price, total_price = _derive_unit_price_from_total(qty, unit_price, total_price)
                        num_item = str(row[item_idx]).strip() if item_idx != -1 and row[item_idx] else None
                        und = str(row[und_idx]).strip() if und_idx != -1 and row[und_idx] else "UN"

                        itens.append(
                            ItemExtracted(
                                numero_item=num_item,
                                descricao=desc,
                                quantidade=qty,
                                unidade_medida=und,
                                valor_unitario_estimado=unit_price,
                                valor_total_estimado=total_price,
                            )
                        )

        logger.info(f"Heurística v2 encontrou {len(itens)} itens.")
        return _sanitize_extraction(
            ExtracaoEdital(
                documento_valido=len(itens) > 0,
                lotes=[LoteExtracted(numero_lote="1", itens=itens)],
            )
        )
    except Exception as error:
        logger.error(f"Heuristic extraction v2 failed: {error}")
        return ExtracaoEdital(documento_valido=False, lotes=[])
