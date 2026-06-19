# Insurance Estimate Comparator - PDF Version

Backend-powered web app for comparing a carrier estimate to your estimate.

## Supported uploads

- PDF (text-based PDFs exported from estimating software work best)
- CSV
- XLSX

Scanned/image-only PDFs may not extract line items correctly unless OCR is added.

## Render deployment settings

Root Directory: leave blank

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

This repo includes `.python-version` to force Render to use Python 3.11.10.

## Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000
