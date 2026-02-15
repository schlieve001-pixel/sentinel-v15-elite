# VeriFuse V2 — Colorado Surplus Foreclosure Intelligence

Legal intelligence platform for Colorado attorneys recovering surplus funds from foreclosure sales under C.R.S. § 38-38-111.

## What It Does

VeriFuse scrapes public record data from Colorado county Public Trustee offices, extracts foreclosure sale financials (bid amounts, indebtedness, overbid/surplus), and presents verified leads to licensed attorneys through a secure SaaS platform.

## Architecture

```
verifuse_v2/                   # Backend (Python/FastAPI)
├── server/
│   ├── api.py                 # FastAPI endpoints (25 routes)
│   ├── auth.py                # JWT authentication + admin
│   ├── dossier_gen.py         # PDF dossier generator (4-section)
│   ├── motion_gen.py          # Court motion PDF generator
│   ├── billing.py             # Stripe subscription billing
│   └── obfuscator.py          # PII obfuscation (text → PNG)
├── scrapers/
│   ├── denver_pdf_parser.py   # Denver excess funds PDF parser
│   ├── jefferson_scraper.py   # Jefferson County CSV import
│   ├── adams_postsale_scraper.py   # Adams County post-sale PDF
│   ├── elpaso_postsale_scraper.py  # El Paso County pre-sale PDF
│   ├── vertex_engine.py       # Vertex AI PDF extraction (Engine #4)
│   └── ...                    # Signal, outcome, tax lien scrapers
├── db/
│   ├── database.py            # SQLite abstraction layer
│   ├── schema.sql             # Database DDL
│   └── migrate.py             # Migration utilities
├── pipeline_manager.py        # Engine 0: Governor (rate limiter + orchestrator)
├── daily_healthcheck.py       # Daily regrade, dedup, integrity checks
└── data/                      # Runtime data (not tracked in git)

verifuse/site/app/             # Frontend (React 19 + TypeScript + Vite)
├── src/
│   ├── pages/
│   │   ├── Dashboard.tsx      # Lead cards with filtering
│   │   └── LeadDetail.tsx     # Asset detail + unlock flow
│   ├── lib/
│   │   ├── api.ts             # API client
│   │   └── auth.tsx           # JWT auth context
│   └── App.css                # Dark theme (WCAG AA compliant)
└── .env                       # API URL config
```

## Production Deploy (Phase 2 — Atomic Blue/Green)

```
~/verifuse_titanium_prod/
├── releases/           # Versioned code copies
│   └── v8.0.0/         # Each sprint = new release
├── current -> releases/v8.0.0   # Atomic symlink swap
├── data/               # PERSISTENT — never touched by deploys
│   └── verifuse_v2.db  # Production database
├── logs/               # PERSISTENT — log files
└── secrets.env         # JWT + API keys (chmod 600)
```

### First-time deploy
```bash
bash verifuse_v2/deploy/deploy.sh 8.0.0
```

### Subsequent deploys
```bash
git pull
bash verifuse_v2/deploy/deploy.sh 8.1.0
```

The deploy script: copies code to `releases/v{version}/`, WAL-checkpoints the DB, atomically swaps the `current` symlink, and restarts systemd services.

## Development Setup

### Backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r verifuse_v2/requirements.txt

# Set environment
export VERIFUSE_DB_PATH=$PWD/verifuse_v2/data/verifuse_v2.db
export VERIFUSE_JWT_SECRET=dev-secret

# Run schema migrations
python -m verifuse_v2.db.fix_leads_schema

# Run API server
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd verifuse/site/app
npm install
npm run dev          # Development
npm run build        # Production build
```

### Run Scrapers
```bash
# Denver (monthly excess funds PDF)
python -m verifuse_v2.scrapers.denver_pdf_parser

# Adams County (weekly post-sale PDFs — 100% verified data)
python -m verifuse_v2.scrapers.adams_postsale_scraper

# El Paso County (weekly pre-sale PDFs)
python -m verifuse_v2.scrapers.elpaso_postsale_scraper

# Jefferson County (CSV import)
python -m verifuse_v2.scrapers.jefferson_scraper --csv /path/to/data.csv

# Daily healthcheck (regrade + dedup)
python -m verifuse_v2.daily_healthcheck
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login → JWT token |
| GET | `/api/auth/me` | Current user profile |
| GET | `/api/stats` | Pipeline statistics |
| GET | `/api/leads` | Browse leads (filterable) |
| GET | `/api/lead/{id}` | Lead detail |
| POST | `/api/unlock/{id}` | Unlock lead (1 credit) |
| GET | `/api/dossier/{id}` | Download PDF dossier |
| POST | `/api/billing/checkout` | Create Stripe checkout |
| GET | `/api/admin/*` | Admin endpoints (stats, leads, regrade, dedup, users) |

## Data Pipeline

| Engine | Name | Source | Data Quality |
|--------|------|--------|-------------|
| 0 | Governor | Rate limiter | N/A |
| 1 | Signal | Denver Public Trustee | Foreclosure signals |
| 2 | Outcome | Denver sale results | Sale outcomes |
| 3 | Entity | Property records | Owner enrichment |
| 4 | Vertex AI | PDF bid sheets | OCR extraction |
| 5 | El Paso | Pre-sale PDFs | Indebtedness (verified) |
| 6 | Adams | Post-sale PDFs | Full financials (verified) |

## Legal Compliance

- **C.R.S. § 38-38-111**: 180-day claim window enforcement
- **C.R.S. § 38-38-111(2.5)(c)**: 6-month restriction period tracking
- **C.R.S. § 38-13-1302(5)**: Attorney-client exemption for restricted access
- **C.R.S. § 38-13-1304**: 2-year finder fee blackout period

All data sourced exclusively from public records. No skip-tracing, no homeowner contact.

## License

Proprietary. All rights reserved.
