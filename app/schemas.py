from pydantic import BaseModel
from typing import List, Optional

class EstimateLine(BaseModel):
    source: str
    room: str = ""
    category: str = ""
    description: str
    quantity: float = 0
    unit: str = ""
    unit_price: float = 0
    total: float = 0
    raw: dict = {}

class ComparisonRow(BaseModel):
    status: str
    match_score: float
    carrier: Optional[EstimateLine] = None
    company: Optional[EstimateLine] = None
    quantity_delta: float = 0
    unit_price_delta: float = 0
    total_delta: float = 0
    note: str = ""

class MissingItemSummary(BaseModel):
    room: str = ""
    category: str = ""
    description: str
    quantity: float = 0
    unit: str = ""
    unit_price: float = 0
    total: float = 0
    reason_included: str
    suggested_carrier_language: str

class ComparisonSummary(BaseModel):
    carrier_total: float
    company_total: float
    total_difference: float
    missing_from_carrier_count: int
    only_in_carrier_count: int
    changed_count: int
    matched_count: int

class ComparisonResponse(BaseModel):
    summary: ComparisonSummary
    rows: List[ComparisonRow]
    missing_item_summaries: List[MissingItemSummary] = []
