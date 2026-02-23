> Updated: February 23, 2026

# VeriFuse

Automated Colorado foreclosure surplus intelligence platform. Identifies, validates, and classifies post-sale overbid equity so attorneys and claimants can pursue rightful funds under C.R.S. § 38-38-111 and § 38-13-1304. Consult qualified counsel before acting on any classification output.

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111+ (Python 3.11), ThreadPoolExecutor DB pool |
| Database | SQLite WAL-mode (`PRAGMA journal_mode=WAL`), `busy_timeout=30 s` |
| Scraper | Playwright 1.45+ (Chromium headless), Universal GovSoft Adapter |
| Frontend | React 18 + TypeScript + Vite, JWT auth (localStorage) |
| Auth | HS256 JWT, RBAC (admin / attorney / public) |
| Billing | Stripe Checkout + Webhooks |
| Testing | Custom gauntlet (`bin/vf gauntlet`) — 62+ assertions |

---

## Quick Start

```bash
# 1. Python dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Node dependencies (frontend)
cd verifuse/site/app && npm install && cd ../../..

# 3. Initialize / migrate database
bin/vf migrate

# 4. Start API server (port 8000)
bin/vf serve

# 5. Start frontend dev server (separate terminal, port 5173)
cd verifuse/site/app && npm run dev
```

---

## Key Commands

```bash
bin/vf gauntlet                          # Full test suite (must pass 62+)
bin/vf migrate                           # Apply pending SQL migrations
bin/vf scrape <county>                   # Scrape county date-window (govsoft)
bin/vf scrape <county> --case J2500346   # Single-case scrape
bin/vf coverage <county> --days 60       # Coverage audit (browser vs DB count)
bin/vf serve                             # FastAPI dev server
```

---

## Dual-Track Architecture

**Track 1 — Platform Hardening**
- SQLite WAL + ThreadPoolExecutor DB pool (no blocking main thread)
- BFCache hardening (`Cache-Control: no-store`) on all authenticated routes
- AbortController cleanup in React hooks
- Stripe downgrade guard (tier rank enforcement)

**Track 2 — Statewide Forensic Ingestion**
- Universal GovSoft Adapter — adaptive date-window bisection, pagination, document download
- Gate 4 dual-validation: HTML math + voucher cross-check → GOLD or BRONZE
- `surplus_math_audit` provenance table — every GOLD/BRONZE decision is auditable
- Equity resolution: 5-tier classification with LIENOR_TAB + CERTQH provenance
- Coverage audit: `coverage_audit.py` — browser count vs DB count per county

---

## Equity Classifications (5-Tier)

| Classification | Meaning |
|---|---|
| `OWNER_ELIGIBLE` | Net equity > 0 after lien deduction |
| `LIEN_ABSORBED` | Junior liens ≥ gross surplus (requires LIENOR_TAB or evidence provenance) |
| `TREASURER_TRANSFERRED` | Explicit transfer evidence: CERTQH doc or TRANSFER_RE match |
| `RESOLUTION_PENDING` | Insufficient data or < 30 months post-sale |
| `NEEDS_REVIEW_TREASURER_WINDOW` | > 30 months post-sale, no explicit transfer evidence |

---

## Data Grades

| Grade | Meaning |
|---|---|
| `GOLD` | Dual-validated: HTML math confirmed AND provenance (snapshot_id or doc_id) present |
| `BRONZE` | Pre-validation, math mismatch, voucher pending OCR, or provenance absent |

---

## Project Layout

```
verifuse_v2/
  core/                 equity_resolution_engine.py
  ingest/               govsoft_extract.py (Gate 4 dual-validation)
  migrations/           001–009 SQL migration files
  scrapers/adapters/    govsoft_engine.py (Universal GovSoft Adapter)
  scripts/              coverage_audit.py, stress_test.py
  server/               api.py (FastAPI)
  data/                 verifuse_v2.db (SQLite WAL, gitignored)
verifuse/site/app/      React 18 frontend
docs/                   ARCHITECTURE.md, RUNBOOK.md
bin/vf                  CLI wrapper
```
