# VeriFuse — Colorado Surplus Foreclosure Intelligence

Legal intelligence platform for Colorado attorneys recovering surplus funds from foreclosure sales under C.R.S. § 38-38-111.

VeriFuse monitors 64 Colorado county Public Trustee offices, extracts foreclosure sale financials, and delivers verified, attorney-ready leads through a secure SaaS platform with credit-based unlocking.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USERS (Attorneys)                        │
│                   Landing → Preview → Dashboard                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
┌────────────────────────────▼────────────────────────────────────┐
│                     Caddy (TLS + Reverse Proxy)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐  ┌──────▼──────┐  ┌─────────▼────────┐
│  React Frontend │  │  FastAPI    │  │  Scraper Runner  │
│  (Vite + TS)    │  │  (api.py)   │  │  (runner.py)     │
│                 │  │  30+ routes │  │  engine_v2.py    │
└─────────────────┘  └──────┬──────┘  └────────┬─────────┘
                             │                   │
                     ┌───────▼───────────────────▼───────┐
                     │         SQLite (WAL mode)         │
                     │         verifuse_v2.db             │
                     └───────────────────────────────────┘
```

## Quick Start

### Backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r verifuse_v2/requirements.txt

export VERIFUSE_DB_PATH=$PWD/verifuse_v2/data/verifuse_v2.db
export VERIFUSE_JWT_SECRET=dev-secret

# Run migrations
python -m verifuse_v2.db.migrate_sprint11_5

# Start API server
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd verifuse/site/app
npm install
npm run dev          # Development (port 5173)
npm run build        # Production build
```

### Run Scrapers

```bash
python -m verifuse_v2.scrapers.runner       # Full pipeline run
python -m verifuse_v2.scripts.coverage_report  # Coverage summary
python -m verifuse_v2.scripts.data_audit       # Data quality audit
```

## Project Structure

```
verifuse_v2/                   # Backend (Python / FastAPI)
├── server/
│   ├── api.py                 # FastAPI endpoints (30+ routes)
│   ├── auth.py                # JWT authentication + admin
│   ├── dossier_gen.py         # PDF/DOCX dossier generator
│   ├── motion_gen.py          # Court motion PDF generator
│   ├── billing.py             # Stripe subscription billing
│   └── obfuscator.py          # PII obfuscation (text → PNG)
├── scrapers/
│   ├── engine_v2.py           # Core parsing engine w/ stats
│   ├── runner.py              # Pipeline orchestrator + events
│   └── ...                    # County-specific parsers
├── db/
│   ├── database.py            # SQLite abstraction layer
│   ├── schema.sql             # Database DDL
│   └── migrate_sprint11_5.py  # Sprint 11.5 migration
├── scripts/
│   ├── coverage_report.py     # Pipeline coverage report
│   ├── data_audit.py          # Data quality audit
│   └── smoke_11_5.sh          # Smoke test suite
└── docs/                      # Technical documentation

verifuse/site/app/             # Frontend (React 19 + TypeScript + Vite)
├── src/
│   ├── pages/
│   │   ├── Landing.tsx        # Landing page + value props
│   │   ├── Dashboard.tsx      # Lead vault + preview mode
│   │   └── LeadDetail.tsx     # Asset detail + unlock flow
│   ├── lib/
│   │   ├── api.ts             # API client + downloadSecure
│   │   └── auth.tsx           # JWT auth context
│   └── App.css                # Dark theme (WCAG AA)
└── .env                       # API URL config
```

## Key Features (Sprint 11.5 + Hardening PR)

- **Preview Mode**: Unauthenticated users can preview leads (county, surplus, grade, confidence) without PII exposure
- **Sample Dossier**: Non-PII PDF dossier via O(1) preview_key lookup (no auth required)
- **Stable HMAC Keys**: Preview keys use only `leads.id` + secret (stable across re-grading)
- **Mobile-Safe Downloads**: Auth blob downloads work on iOS/Android (replaces `<a href>` pattern)
- **Grade Filters + Sorting**: Filter by GOLD/SILVER/BRONZE, sort by surplus/date/grade
- **Email Verification**: Non-blocking banner + 403 gate on unlock endpoints
- **Credit Tracking**: `credits_remaining` returned on every unlock response
- **Stripe Guard**: 503 if Stripe not configured (prevents silent billing failures)
- **Admin Simulation**: `X-Verifuse-Simulate: user` header strips admin privileges for testing
- **Error Boundary**: React ErrorBoundary wraps Dashboard + LeadDetail (no white screens)
- **Health Poll**: Dashboard polls `/health` every 30s with green/red indicator (fail closed)
- **401 Auto-Redirect**: Expired tokens trigger localStorage cleanup + redirect to /login
- **Vary Deduplication**: Middleware ensures Vary header includes Authorization + X-Verifuse-Simulate
- **Unlock Tracking**: `unlocked_by_me` field on leads (scalable IN-query on paginated IDs)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health check |
| GET | `/api/preview/leads` | Preview leads (no PII, no auth) |
| GET | `/api/leads` | Browse leads (filterable) |
| GET | `/api/lead/{id}` | Lead detail |
| GET | `/api/stats` | Pipeline statistics |
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | Login → JWT token |
| GET | `/api/auth/me` | Current user profile |
| POST | `/api/auth/send-verification` | Send email verification code |
| POST | `/api/auth/verify-email` | Verify email with code |
| POST | `/api/unlock/{id}` | Unlock lead (1 credit) |
| POST | `/api/unlock-restricted/{id}` | Unlock restricted lead (attorney only) |
| GET | `/api/dossier/sample/{key}` | Sample dossier PDF (no auth) |
| GET | `/api/dossier/{id}` | Download dossier (text) |
| GET | `/api/dossier/{id}/docx` | Download dossier (DOCX) |
| GET | `/api/dossier/{id}/pdf` | Download dossier (PDF) |
| GET | `/api/case-packet/{id}` | Case packet (HTML) |
| POST | `/api/letter/{id}` | Generate Rule 7.3 letter |
| POST | `/api/billing/checkout` | Create Stripe checkout |
| GET | `/api/admin/coverage` | Admin coverage report |
| GET | `/api/admin/*` | Admin endpoints |

## Data Pipeline

| Engine | Source | Output |
|--------|--------|--------|
| Signal | Denver Public Trustee | Foreclosure signals |
| Outcome | Denver sale results | Sale outcomes |
| Entity | Property records | Owner enrichment |
| Vertex AI | PDF bid sheets | OCR extraction |
| El Paso | Pre-sale PDFs | Indebtedness (verified) |
| Adams | Post-sale PDFs | Full financials (verified) |

## Legal Compliance

- **C.R.S. § 38-38-111**: 180-day claim window enforcement
- **C.R.S. § 38-38-111(2.5)(c)**: 6-month restriction period tracking
- **C.R.S. § 38-13-1302(5)**: Attorney-client exemption for restricted access
- **C.R.S. § 38-13-1304**: 2-year finder fee blackout period

All data sourced exclusively from public records. No skip-tracing, no homeowner contact.

## Production Deploy

```bash
bash verifuse_v2/deploy/deploy.sh <version>
```

The deploy script copies code to `releases/v{version}/`, WAL-checkpoints the DB, atomically swaps the `current` symlink, and restarts systemd services.

## License

Proprietary. All rights reserved.
