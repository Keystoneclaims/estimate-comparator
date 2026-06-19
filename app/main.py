from pathlib import Path
import os
from typing import Any, Dict

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .comparison import compare_estimates
from .parser import parse_estimate_file

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Insurance Estimate Comparator", version="0.5.0")

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
    tone: str = "professional appraisal-facing"


def fallback_clean_report(raw_report: str) -> str:
    """Rules-based fallback when no OpenAI API key is configured."""
    text = (raw_report or "").strip()
    if not text:
        return "No report text was provided."
    intro = (
        "Please see the appraisal estimate comparison summary below. This is intended to help "
        "narrow the amount-of-loss issues by identifying major scope variances, omitted repair "
        "categories, and changed line items.\n\n"
    )
    close = (
        "\n\nFor appraisal purposes, the goal should be to reconcile these categories by room and trade, "
        "identify which items are agreed or disputed, and focus the panel discussion on the remaining "
        "scope and pricing differences."
    )
    return intro + text + close


def _plain_text_to_pdf_bytes(text: str) -> bytes:
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    left = 0.7 * inch
    right = width - 0.7 * inch
    top = height - 0.7 * inch
    bottom = 0.65 * inch
    line_height = 11.5
    font_name = "Helvetica"
    font_size = 9.5

    def wrap(line: str):
        words = line.split()
        if not words:
            return [""]
        out, current = [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            if c.stringWidth(candidate, font_name, font_size) <= (right - left):
                current = candidate
            else:
                if current:
                    out.append(current)
                current = word
        if current:
            out.append(current)
        return out

    y = top
    c.setTitle("Estimate Comparison Report")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(left, y, "Estimate Comparison Report")
    y -= 20
    c.setFont(font_name, font_size)

    for raw_line in (text or "").splitlines():
        for line in wrap(raw_line):
            if y < bottom:
                c.showPage()
                y = top
                c.setFont(font_name, font_size)
            if raw_line.isupper() and len(raw_line) < 80 and raw_line.strip():
                c.setFont("Helvetica-Bold", font_size)
                c.drawString(left, y, line)
                c.setFont(font_name, font_size)
            else:
                c.drawString(left, y, line)
            y -= line_height
        if not raw_line.strip():
            y -= 3
    c.save()
    return buffer.getvalue()


def _plain_text_to_rtf(text: str) -> str:
    def esc(s: str) -> str:
        return s.replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}')
    body = r'\\par\n'.join(esc(line) for line in (text or '').splitlines())
    return r'{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}\fs22 ' + body + '}'


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
You are preparing a professional insurance estimate comparison report for a public adjuster in the appraisal process.
Rewrite the raw comparison into a polished appraisal-facing report to an opposing appraiser.

Rules:
- Keep all dollar amounts, counts, rooms, categories, and line item facts accurate.
- Do not invent coverage facts, policy language, inspections, admissions, or causation facts.
- Do not remove material scope differences.
- Use a professional but firm tone.
- Organize with headings, short paragraphs, and clear bullet points.
- Include: overall totals, category/room differences, major omitted categories, representative missing line items, and a closing request to reconcile the disputed scope by room and trade.
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


class ExportReportRequest(BaseModel):
    report: str


@app.post("/report/pdf")
async def export_pdf(payload: ExportReportRequest):
    text = (payload.report or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No report text was provided.")
    pdf_bytes = _plain_text_to_pdf_bytes(text)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=estimate-comparison-report.pdf"},
    )


@app.post("/report/rtf")
async def export_rtf(payload: ExportReportRequest):
    text = (payload.report or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No report text was provided.")
    rtf = _plain_text_to_rtf(text)
    return Response(
        content=rtf.encode("utf-8"),
        media_type="application/rtf",
        headers={"Content-Disposition": "attachment; filename=estimate-comparison-report.rtf"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
