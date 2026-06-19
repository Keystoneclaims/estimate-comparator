import re
from typing import List
from rapidfuzz import fuzz
from .schemas import ComparisonResponse, ComparisonRow, ComparisonSummary, EstimateLine, MissingItemSummary

def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(remove|replace|install|detach|reset|r&r|r and r)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def line_key(line: EstimateLine) -> str:
    return " | ".join([
        normalize_text(line.room),
        normalize_text(line.category),
        normalize_text(line.description),
        normalize_text(line.unit),
    ])

def match_score(carrier: EstimateLine, company: EstimateLine) -> float:
    desc_score = fuzz.token_set_ratio(normalize_text(carrier.description), normalize_text(company.description))
    room_score = fuzz.token_set_ratio(normalize_text(carrier.room), normalize_text(company.room)) if carrier.room or company.room else 100
    cat_score = fuzz.token_set_ratio(normalize_text(carrier.category), normalize_text(company.category)) if carrier.category or company.category else 100
    unit_score = 100 if normalize_text(carrier.unit) == normalize_text(company.unit) else 80
    return round((desc_score * 0.65) + (room_score * 0.15) + (cat_score * 0.10) + (unit_score * 0.10), 2)

def reason_for_missing_item(line: EstimateLine) -> str:
    """Create a plain-English scope justification for an item in our estimate that is absent from the carrier estimate.

    This is intentionally rules-based in v1 so the report is predictable and defensible.
    You can later replace or supplement this with claim-specific notes or an AI narrative layer.
    """
    text = (f"{line.category} {line.description}" or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    room = line.room or "the affected area"

    rules = [
        (("paint", "prime", "seal"), f"This item was included because the related finish work in {room} requires paint/finish restoration to return the affected surface to a uniform, pre-loss condition."),
        (("drywall", "gypsum", "sheetrock", "plaster"), f"This item was included because damaged wall or ceiling material in {room} requires removal, replacement, finishing, and blending as part of the covered repair scope."),
        (("texture", "skim", "float"), f"This item was included because repaired wall or ceiling areas in {room} must be textured or floated to match the surrounding surface before painting."),
        (("baseboard", "trim", "casing", "molding"), f"This item was included because trim components in {room} are typically disturbed or damaged during access and finish repairs and must be reset or replaced for a complete repair."),
        (("detach", "reset", "remove reset", "d r"), f"This item was included because existing components in {room} must be detached and reset to properly perform the covered repairs without damaging adjacent materials."),
        (("floor", "laminate", "vinyl", "tile", "carpet", "wood", "hardwood"), f"This item was included because the flooring in {room} is part of the affected repair area and must be addressed to restore the property to a consistent and usable condition."),
        (("debris", "dump", "haul", "cleanup", "clean up"), f"This item was included because debris removal and jobsite cleanup are necessary consequences of performing the covered repair work."),
        (("mask", "protect", "cover", "plastic", "floor protection"), f"This item was included because reasonable protection of unaffected areas is required while repairs are performed."),
        (("content", "contents", "pack", "move", "manipulation"), f"This item was included because personal property or contents must be moved, protected, or reset to provide access for the covered repairs."),
        (("plumb", "toilet", "sink", "vanity", "faucet", "supply", "drain"), f"This item was included because plumbing components in {room} must be accessed, removed, reset, or restored as part of the repair sequence."),
        (("electric", "light", "fixture", "outlet", "switch", "fan"), f"This item was included because electrical fixtures or devices in {room} must be safely removed, reset, or addressed during the repair work."),
        (("op", "overhead", "profit", "supervision"), "This item was included because the scope involves multiple trades and coordination, making overhead and profit appropriate for a complete repair estimate."),
    ]

    for keywords, reason in rules:
        if any(keyword in text for keyword in keywords):
            return reason

    return f"This item was included because it is part of the repair scope identified in {room} and is necessary to complete the covered restoration work in a reasonable, workmanlike manner."

def carrier_language_for_missing_item(line: EstimateLine) -> str:
    room = line.room or "the affected area"
    return (
        f"The carrier estimate does not appear to include {line.description} in {room}. "
        f"This item should be added because it is necessary to complete the covered repair scope and return the affected property to its pre-loss condition."
    )

def build_missing_item_summaries(rows: List[ComparisonRow]) -> List[MissingItemSummary]:
    summaries: List[MissingItemSummary] = []
    for row in rows:
        if row.status != "missing_from_carrier" or row.company is None:
            continue
        line = row.company
        summaries.append(MissingItemSummary(
            room=line.room,
            category=line.category,
            description=line.description,
            quantity=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
            total=line.total,
            reason_included=reason_for_missing_item(line),
            suggested_carrier_language=carrier_language_for_missing_item(line),
        ))
    return summaries

def compare_estimates(carrier_lines: List[EstimateLine], company_lines: List[EstimateLine], threshold: float = 78) -> ComparisonResponse:
    used_carrier = set()
    rows: List[ComparisonRow] = []

    for company in company_lines:
        best_idx = None
        best_score = -1.0
        for idx, carrier in enumerate(carrier_lines):
            if idx in used_carrier:
                continue
            score = match_score(carrier, company)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx is None or best_score < threshold:
            rows.append(ComparisonRow(
                status="missing_from_carrier",
                match_score=max(best_score, 0),
                carrier=None,
                company=company,
                quantity_delta=company.quantity,
                unit_price_delta=company.unit_price,
                total_delta=company.total,
                note="Your estimate contains this item, but no strong carrier match was found.",
            ))
            continue

        carrier = carrier_lines[best_idx]
        used_carrier.add(best_idx)
        quantity_delta = round(company.quantity - carrier.quantity, 2)
        unit_price_delta = round(company.unit_price - carrier.unit_price, 2)
        total_delta = round(company.total - carrier.total, 2)
        changed = abs(quantity_delta) > 0.01 or abs(unit_price_delta) > 0.01 or abs(total_delta) > 0.01
        rows.append(ComparisonRow(
            status="changed" if changed else "matched",
            match_score=best_score,
            carrier=carrier,
            company=company,
            quantity_delta=quantity_delta,
            unit_price_delta=unit_price_delta,
            total_delta=total_delta,
            note="Matched with differences." if changed else "Matched with no material difference.",
        ))

    for idx, carrier in enumerate(carrier_lines):
        if idx not in used_carrier:
            rows.append(ComparisonRow(
                status="only_in_carrier",
                match_score=0,
                carrier=carrier,
                company=None,
                quantity_delta=-carrier.quantity,
                unit_price_delta=-carrier.unit_price,
                total_delta=-carrier.total,
                note="Carrier estimate contains this item, but it was not found in your estimate.",
            ))

    carrier_total = round(sum(x.total for x in carrier_lines), 2)
    company_total = round(sum(x.total for x in company_lines), 2)
    summary = ComparisonSummary(
        carrier_total=carrier_total,
        company_total=company_total,
        total_difference=round(company_total - carrier_total, 2),
        missing_from_carrier_count=sum(1 for r in rows if r.status == "missing_from_carrier"),
        only_in_carrier_count=sum(1 for r in rows if r.status == "only_in_carrier"),
        changed_count=sum(1 for r in rows if r.status == "changed"),
        matched_count=sum(1 for r in rows if r.status == "matched"),
    )
    rows.sort(key=lambda r: {"missing_from_carrier": 0, "changed": 1, "only_in_carrier": 2, "matched": 3}.get(r.status, 9))
    return ComparisonResponse(summary=summary, rows=rows, missing_item_summaries=build_missing_item_summaries(rows))
