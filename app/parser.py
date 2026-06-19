import csv
import io
import re
from typing import Dict, Iterable, List, Sequence

import pdfplumber
from openpyxl import load_workbook

from .schemas import EstimateLine

HEADER_ALIASES = {
    "room": ["room", "area", "location", "loc", "trade room"],
    "category": ["category", "cat", "trade", "division", "coverage"],
    "description": ["description", "desc", "line item", "line_item", "item", "scope", "activity", "activity desc"],
    "quantity": ["quantity", "qty", "quan", "qnty"],
    "unit": ["unit", "uom", "measure"],
    "unit_price": ["unit_price", "unit price", "unit cost", "price", "rate", "unit $", "unit cost"],
    "total": ["total", "rcv", "amount", "line total", "replacement cost", "recoverable total", "total rcv"],
}

COMMON_UNITS = {
    "EA", "SF", "LF", "SY", "SQ", "HR", "DAY", "MO", "CY", "CF", "YD", "GL", "GAL", "LB", "TN", "TON", "BAG", "BOX", "ROLL", "SET", "PR", "PAIR", "LS", "JOB"
}

SUMMARY_WORDS = {
    "subtotal", "total", "tax", "overhead", "profit", "depreciation", "deductible", "net claim", "replacement cost", "actual cash value", "rcv", "acv"
}

ROOM_HINTS = [
    "kitchen", "bathroom", "master bathroom", "bedroom", "master bedroom", "living room", "dining room", "family room", "hallway", "foyer", "entry", "laundry", "garage", "closet", "basement", "attic", "office", "den", "pantry", "exterior", "roof", "main level", "second floor", "first floor"
]


def _clean_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _money_to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("$", "").replace(",", "").replace("(", "-").replace(")", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        return float(text)
    except ValueError:
        return 0.0


def _map_headers(headers: Iterable[str]) -> Dict[str, str]:
    cleaned = {_clean_header(h): h for h in headers}
    mapping = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias in cleaned:
                mapping[canonical] = cleaned[alias]
                break
    return mapping


def _line_from_row(row: Dict[str, object], mapping: Dict[str, str], source: str) -> EstimateLine | None:
    description = str(row.get(mapping.get("description", ""), "") or "").strip()
    if not description:
        return None

    qty = _money_to_float(row.get(mapping.get("quantity", "")))
    unit_price = _money_to_float(row.get(mapping.get("unit_price", "")))
    total = _money_to_float(row.get(mapping.get("total", "")))
    if total == 0 and qty and unit_price:
        total = qty * unit_price

    return EstimateLine(
        source=source,
        room=str(row.get(mapping.get("room", ""), "") or "").strip(),
        category=str(row.get(mapping.get("category", ""), "") or "").strip(),
        description=description,
        quantity=qty,
        unit=str(row.get(mapping.get("unit", ""), "") or "").strip(),
        unit_price=unit_price,
        total=round(total, 2),
        raw={str(k): v for k, v in row.items()},
    )


def parse_csv_bytes(content: bytes, source: str) -> List[EstimateLine]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    mapping = _map_headers(reader.fieldnames)
    if "description" not in mapping:
        raise ValueError("Could not find a description column. Add a header like description, desc, line item, or item.")
    return [line for row in reader if (line := _line_from_row(row, mapping, source))]


def parse_xlsx_bytes(content: bytes, source: str) -> List[EstimateLine]:
    wb = load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(c or "") for c in rows[0]]
    mapping = _map_headers(headers)
    if "description" not in mapping:
        raise ValueError("Could not find a description column in the first row.")
    lines = []
    for raw_values in rows[1:]:
        row = {headers[i]: raw_values[i] if i < len(raw_values) else None for i in range(len(headers))}
        line = _line_from_row(row, mapping, source)
        if line:
            lines.append(line)
    return lines


def _looks_like_summary(description: str) -> bool:
    desc = _clean_header(description)
    if len(desc) < 3:
        return True
    return any(word == desc or desc.startswith(word + " ") for word in SUMMARY_WORDS)


def _guess_room_from_line(text: str, current_room: str) -> str:
    clean = _clean_header(text).strip(":")
    if not clean or len(clean) > 45:
        return current_room
    if clean in ROOM_HINTS:
        return text.strip().strip(":")
    if clean.endswith("room") or clean.endswith("bath") or clean.endswith("bathroom"):
        return text.strip().strip(":")
    if text.strip().lower().startswith(("room:", "area:", "location:")):
        return text.split(":", 1)[1].strip()
    return current_room


def _parse_table_rows(table: Sequence[Sequence[object]], source: str) -> List[EstimateLine]:
    lines: List[EstimateLine] = []
    if not table:
        return lines
    cleaned_rows = [[str(cell or "").strip() for cell in row] for row in table if any(str(cell or "").strip() for cell in row)]
    if len(cleaned_rows) < 2:
        return lines

    # Try every early row as the header because PDF table extraction often includes title rows first.
    for header_index in range(min(5, len(cleaned_rows) - 1)):
        headers = cleaned_rows[header_index]
        mapping = _map_headers(headers)
        if "description" not in mapping:
            continue
        for values in cleaned_rows[header_index + 1:]:
            row = {headers[i]: values[i] if i < len(values) else "" for i in range(len(headers))}
            line = _line_from_row(row, mapping, source)
            if line and not _looks_like_summary(line.description):
                lines.append(line)
        if lines:
            return lines
    return lines


LINE_RE = re.compile(
    r"^\s*(?:\d{1,4}[.)]?\s+)?(?P<desc>.+?)\s+"
    r"(?P<qty>-?\d[\d,]*(?:\.\d+)?)\s+"
    r"(?P<unit>[A-Za-z]{1,6})\s+"
    r"\$?(?P<unit_price>-?\d[\d,]*(?:\.\d+)?)\s+"
    r"\$?(?P<total>-?\d[\d,]*(?:\.\d+)?)\s*$"
)


def _parse_text_line(text: str, source: str, current_room: str) -> EstimateLine | None:
    line = re.sub(r"\s+", " ", text or "").strip()
    if not line:
        return None
    match = LINE_RE.match(line)
    if not match:
        return None
    desc = match.group("desc").strip(" -–—")
    # Remove common Xactimate item-code prefixes but keep the human description.
    desc = re.sub(r"^[A-Z]{2,5}\s+[A-Z0-9._-]+\s+", "", desc).strip()
    unit = match.group("unit").upper()
    if unit not in COMMON_UNITS:
        # Still accept uncommon units, but reject obvious false positives like dates or words.
        if len(unit) > 6:
            return None
    if _looks_like_summary(desc):
        return None
    qty = _money_to_float(match.group("qty"))
    unit_price = _money_to_float(match.group("unit_price"))
    total = _money_to_float(match.group("total"))
    if not total and qty and unit_price:
        total = qty * unit_price
    if not desc or total == 0:
        return None
    return EstimateLine(
        source=source,
        room=current_room,
        category="PDF import",
        description=desc,
        quantity=qty,
        unit=unit,
        unit_price=unit_price,
        total=round(total, 2),
        raw={"pdf_text_line": line},
    )


def parse_pdf_bytes(content: bytes, source: str) -> List[EstimateLine]:
    """Best-effort PDF estimate parser.

    Works best with text-based estimate PDFs or PDFs that have readable tables. Scanned/image-only
    PDFs need OCR and should be converted/exported from Xactimate/Symbility when possible.
    """
    lines: List[EstimateLine] = []
    seen = set()
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            # First try actual table extraction.
            for table in page.extract_tables() or []:
                for parsed in _parse_table_rows(table, source):
                    key = (parsed.room, parsed.description, parsed.quantity, parsed.unit, parsed.total)
                    if key not in seen:
                        seen.add(key)
                        lines.append(parsed)

            # Then try line-by-line extraction from page text.
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            current_room = ""
            for raw_line in text.splitlines():
                clean_line = raw_line.strip()
                current_room = _guess_room_from_line(clean_line, current_room)
                parsed = _parse_text_line(clean_line, source, current_room)
                if parsed:
                    key = (parsed.room, parsed.description, parsed.quantity, parsed.unit, parsed.total)
                    if key not in seen:
                        seen.add(key)
                        lines.append(parsed)

    if not lines:
        raise ValueError(
            "I could not read line items from this PDF. It may be a scanned/image PDF or a format that needs custom parsing. "
            "Try exporting the estimate as a text-based PDF, CSV, or XLSX."
        )
    return lines


def parse_estimate_file(filename: str, content: bytes, source: str) -> List[EstimateLine]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return parse_csv_bytes(content, source)
    if lower.endswith(".xlsx"):
        return parse_xlsx_bytes(content, source)
    if lower.endswith(".pdf"):
        return parse_pdf_bytes(content, source)
    raise ValueError("Unsupported file type. Use .pdf, .csv, or .xlsx.")
