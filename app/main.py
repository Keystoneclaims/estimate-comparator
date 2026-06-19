from pathlib import Path
import os
from typing import Any, Dict

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .comparison import compare_estimates
from .parser import parse_estimate_file

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Insurance Estimate Comparator", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CleanReportRequest(BaseModel):
    raw_report: str
    comparison_data: Dict[str, Any] | None = None
    tone: str = "professional carrier-facing"


def fallback_clean_report(raw_report: str) -> str:
    """Rules-based fallback when no OpenAI API key is configured.

    This keeps the feature usable even before the owner adds an API key in Render.
    """
    text = (raw_report or "").strip()
    if not text:
        return "No report text was provided."
    intro = (
        "Please see the estimate comparison summary below. The comparison identifies the "
        "difference between the carrier estimate and our estimate, including omitted scope, "
        "changed line items, and the repair components required to complete the covered work.\n\n"
    )
    close = (
        "\n\nBased on this comparison, the carrier estimate should be revised to include the omitted "
        "scope items and related repair sequencing necessary to restore the affected property "
        "to its pre-loss condition in a reasonable and workmanlike manner."
    )
    return intro + text + close


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/compare")
async def compare(
    carrier_file: UploadFile = File(...),
    company_file: UploadFile = File(...),
):
    try:
        carrier_content = await carrier_file.read()
        company_content = await company_file.read()
        carrier_lines = parse_estimate_file(carrier_file.filename or "carrier.csv", carrier_content, "carrier")
        company_lines = parse_estimate_file(company_file.filename or "company.csv", company_content, "company")
        if not carrier_lines:
            raise ValueError("Carrier estimate did not contain readable line items.")
        if not company_lines:
            raise ValueError("Your estimate did not contain readable line items.")
        return compare_estimates(carrier_lines, company_lines)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/report/clean")
async def clean_report(payload: CleanReportRequest):
    raw_report = (payload.raw_report or "").strip()
    if not raw_report:
        raise HTTPException(status_code=400, detail="No report text was provided.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "mode": "rules_based_fallback",
            "report": fallback_clean_report(raw_report),
            "note": "OPENAI_API_KEY is not configured. Add it in Render Environment Variables to enable AI rewrite."
        }

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        prompt = f"""
You are preparing a professional insurance estimate comparison report for a public adjuster.
Rewrite the raw comparison into a polished, carrier-facing report.

Rules:
- Keep all dollar amounts, counts, rooms, categories, and line item facts accurate.
- Do not invent coverage facts, policy language, inspections, admissions, or causation facts.
- Do not remove material scope differences.
- Use a professional but firm tone.
- Organize with headings, short paragraphs, and clear bullet points.
- Include: overall totals, category/room differences, major omitted categories, missing line items, and closing request to revise the carrier estimate.
- Avoid legal conclusions unless the raw text expressly states them.

Raw report:
{raw_report}
""".strip()
        response = client.responses.create(
            model=model,
            input=prompt,
            temperature=0.2,
        )
        cleaned = getattr(response, "output_text", None) or fallback_clean_report(raw_report)
        return {"mode": "ai", "report": cleaned, "note": f"Cleaned with {model}."}
    except Exception as exc:
        return {
            "mode": "rules_based_fallback_after_ai_error",
            "report": fallback_clean_report(raw_report),
            "note": f"AI rewrite could not be completed: {str(exc)}"
        }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
