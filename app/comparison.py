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

def scope_category_for_line(line: EstimateLine) -> str:
    text = (f"{line.category} {line.description}" or "").lower()
    checks = [
        (("content", "contents", "pack", "manipulation", "move out"), "Contents handling / protection"),
        (("light", "fixture", "outlet", "switch", "electric", "wiring", "gfi", "thermostat", "heat/ac register", "register"), "Electrical / mechanical detach and reset"),
        (("sink", "faucet", "toilet", "plumbing", "supply line", "angle stop", "dishwasher connection", "water line", "p-trap", "vanity"), "Plumbing detach and reset"),
        (("cabinet", "knob", "pull"), "Cabinetry"),
        (("countertop", "granite", "marble"), "Countertops"),
        (("window", "skylight", "door", "hinge", "lockset", "jamb", "casing"), "Openings / windows / doors"),
        (("drywall", "sheetrock", "gypsum", "plaster", "tape joint", "texture", "skim", "float"), "Wall and ceiling repair"),
        (("paint", "prime", "seal", "wallpaper", "finish"), "Finish restoration"),
        (("floor", "hardwood", "wood", "vinyl", "laminate", "tile", "carpet", "baseboard", "quarter round", "base shoe"), "Flooring / trim restoration"),
        (("mask", "protect", "plastic", "cover", "film"), "Site protection"),
        (("final cleaning", "cleaning", "debris", "dump", "haul"), "Cleaning and debris removal"),
        (("temporary", "mitigation", "water extraction", "remediation"), "Mitigation / temporary repairs"),
    ]
    for keywords, label in checks:
        if any(k in text for k in keywords):
            return label
    return line.category or "General repair scope"


def reason_for_missing_item(line: EstimateLine) -> str:
    """Create a practical, scope-based justification for an item in our estimate that is absent from the carrier estimate."""
    text = (f"{line.category} {line.description}" or "").lower()
    text = re.sub(r"[^a-z0-9/& ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    room = line.room if line.room and line.room.lower() not in {"room", "pdf import"} else "the affected area"
    desc = (line.description or "this item").lower()
    category = scope_category_for_line(line)

    if category == "Contents handling / protection":
        return f"Contents handling is included so the work area in {room} can be accessed safely. Personal property must be moved, protected, and reset before and after the repair sequence; otherwise the covered repair work cannot be performed without creating additional damage or obstruction."
    if category == "Electrical / mechanical detach and reset":
        return f"This is part of the electrical/mechanical repair sequence in {room}. Fixtures, registers, outlets, switches, appliances, or related devices must be safely disconnected, protected, and reset when surrounding cabinets, walls, ceilings, or finishes are repaired."
    if category == "Plumbing detach and reset":
        return f"This is part of the plumbing access and reset sequence in {room}. Plumbing fixtures, supply lines, valves, drains, or appliance connections must be disconnected and reset to allow cabinet, countertop, wall, or finish repairs to be completed properly."
    if category == "Cabinetry":
        return f"Cabinetry is included because the repair scope in {room} requires removal, replacement, or reset of affected cabinet components to restore the kitchen/bath layout and allow related countertop, plumbing, and finish work to be completed."
    if category == "Countertops":
        return f"Countertop work is included because the affected cabinets, plumbing, sink components, and adjacent finishes in {room} cannot be repaired correctly without addressing the countertop removal/reset or replacement risk."
    if category == "Openings / windows / doors":
        return f"This opening component is included because the repair scope affects adjacent trim, wall finishes, or exterior/interior openings in {room}. Door, window, skylight, hardware, and casing components must be addressed so the completed repair is functional and visually consistent."
    if category == "Wall and ceiling repair":
        return f"Wall and ceiling repair is included because damaged or disturbed building materials in {room} must be removed, replaced, taped, floated, textured, and prepared before finish work can be completed."
    if category == "Finish restoration":
        return f"Finish restoration is included because the repaired surfaces in {room} require paint, seal, prime, wallpaper, or finish work to blend the repair area and return the affected surfaces to a uniform pre-loss condition."
    if category == "Flooring / trim restoration":
        return f"Flooring and trim restoration is included because the repair work affects floor surfaces, transitions, baseboards, shoe molding, or adjacent trim in {room}. These components are necessary to complete the repair and restore a consistent finished appearance."
    if category == "Site protection":
        return f"Site protection is included to protect unaffected finishes and contents while repairs are performed in {room}. Protection is a necessary construction step when multiple trades are working in occupied or finished areas."
    if category == "Cleaning and debris removal":
        return f"Cleaning and debris removal are included because construction-related dust, debris, and waste are direct consequences of the repair scope and must be addressed before the affected area can be returned to service."
    if category == "Mitigation / temporary repairs":
        return f"This item is included because temporary repairs, mitigation, or remediation were necessary to stabilize the loss, prevent further damage, and prepare the property for permanent repairs."

    return f"This item is included as part of the {category.lower()} required in {room}. It supports the repair sequence necessary to complete the covered restoration work in a reasonable and workmanlike manner."

def carrier_language_for_missing_item(line: EstimateLine) -> str:
    room = line.room if line.room and line.room.lower() not in {"room", "pdf import"} else "the affected area"
    scope_category = scope_category_for_line(line)
    return (
        f"The carrier estimate does not appear to include {line.description} in {room}. "
        f"This item falls within the {scope_category.lower()} portion of the repair sequence and should be added because it is necessary to perform the covered repairs completely, protect adjacent materials, and return the affected property to its pre-loss condition."
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
