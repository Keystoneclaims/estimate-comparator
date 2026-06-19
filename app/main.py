from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .comparison import compare_estimates
from .parser import parse_estimate_file

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Insurance Estimate Comparator", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
