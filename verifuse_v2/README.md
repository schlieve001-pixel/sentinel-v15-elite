# VeriFuse V2 — Colorado Surplus Intelligence Platform

Production-grade system for discovering, verifying, and serving Colorado foreclosure surplus leads to attorneys.

## Quick Start

```bash
# Set environment
export VERIFUSE_DB_PATH=/path/to/verifuse_v2.db
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# Install
pip install -r verifuse_v2/requirements.txt

# Patch schema (idempotent)
python -m verifuse_v2.db.fix_leads_schema

# Parse all PDFs (no AI needed)
python -m verifuse_v2.scrapers.engine_v2

# Start API
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

## Architecture

```
[County PDFs] → [Parser Registry] → [leads table] → [API] → [Frontend]
                 (5 parsers)          (734 rows)     (:8000)  (:4173)
```

**Parser Registry** (`registry.py`): Abstract `CountyParser` base class with `detect()`, `extract()`, `score()`. Parsers: Adams, Denver, El Paso (pre/post-sale), Generic Excess Funds.

**Engine V2** (`engine_v2.py`): Scans `data/raw_pdfs/`, matches PDFs to parsers, extracts records, scores confidence, upserts into `leads` table.

**Confidence Function C**: `0.25*bid + 0.25*debt + 0.15*date + 0.15*address + 0.10*owner + 0.10*V(delta)` where V checks `|surplus - (bid-debt)| <= $5`.

**Threshold routing**: score > 0.8 = ENRICHED, 0.5-0.8 = REVIEW_REQUIRED, < 0.5 = ANOMALY (logged, skipped).

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | System health check |
| `/api/leads` | GET | No | Paginated leads (SafeAsset projection) |
| `/api/leads/{id}/unlock` | POST | JWT | Unlock lead (credit deduction) |
| `/api/billing/upgrade` | POST | JWT | Upgrade tier + refill credits |
| `/api/auth/register` | POST | No | Create account |
| `/api/auth/login` | POST | No | Get JWT token |
| `/api/stats` | GET | No | Dashboard statistics |
| `/api/counties` | GET | No | County breakdown |

## Data Pipeline

| County | Leads | Parser | Grade |
|--------|-------|--------|-------|
| Jefferson | 64 | Web scraper | GOLD |
| Arapahoe | 12 | Web scraper | GOLD |
| Denver | 8 | DenverExcessParser | GOLD |
| Adams | 35 | AdamsParser | Mixed |
| El Paso | — | ElPasoPreSaleParser | Pipeline |
| Eagle | 312 | Portal scrape | Pre-sale |
| San Miguel | 250 | Portal scrape | Pre-sale |

## Key Files

| File | Purpose |
|------|---------|
| `scrapers/registry.py` | Parser ABC + 5 concrete parsers |
| `scrapers/engine_v2.py` | Deterministic PDF extraction engine |
| `scrapers/vertex_engine_enterprise.py` | Vertex AI (Gemini) extraction |
| `server/api.py` | FastAPI server (leads-native, NULL-safe) |
| `db/fix_leads_schema.py` | Schema auto-patcher (idempotent) |

See `OPERATIONS_PLAN.md` for full system documentation.
