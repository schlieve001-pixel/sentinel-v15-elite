# VERIFUSE V2 — OPERATIONS PLAN
## Last Updated: February 14, 2026

---

## SYSTEM STATUS: OPERATIONAL (11 Counties, 10 Engines)

### Database Summary
| Metric | Value |
|--------|-------|
| Total Assets | 46+ (growing with new county scrapers) |
| Total Pipeline Value | $5,195,751.75+ |
| GOLD-Grade Verified Leads | 6 |
| SILVER-Grade Leads | 7+ |
| Attorney-Ready (GOLD+SILVER, surplus >= $1K) | 13+ |
| Counties Active | 11 (Denver, Arapahoe, Jefferson, Adams, El Paso, Larimer, Weld, Boulder, Pueblo, Mesa, Teller, Douglas) |
| Deduplication | 21 duplicates removed |
| Staging Pipeline | 691 PDFs awaiting Vertex AI processing |

### County Breakdown
| County | Assets | Total Surplus | Avg Confidence | Data Source | Engine |
|--------|--------|--------------|----------------|-------------|--------|
| Denver | 17 | $1,421,630 | 0.88 | Monthly excess funds PDF (no indebtedness) | #1-3 |
| Arapahoe | 12 | $1,426,297 | 0.92 | Overbid list (no indebtedness) | Manual |
| Jefferson | 5 | $2,026,675 | 0.64 | CSV import with written_bid (has indebtedness) | Manual |
| Adams | 4 | $258,106 | 0.95 | Weekly Post Sale List PDF (100% verified) | #6 |
| El Paso | 5 | $0 (pre-sale) | 0.95 | Weekly Pre Sale List PDF (has indebtedness) | #5 |
| Larimer | NEW | Pre-sale data | 0.95 | Weekly Pre Sale List PDF via GTS | #7 |
| Weld | NEW | Pre-sale data | 0.95 | Weekly Pre Sale List PDF (weld.gov) | #8 |
| Boulder | NEW | Pre-sale data | 0.95 | Weekly Pre Sale List PDF via GTS | #9 |
| Pueblo | NEW | Schedule only | 0.50 | Sale schedule page (limited data) | #10 |
| Mesa | 1 | $40,000 | 1.00 | Manual import | Manual |
| Douglas | 1 | $4,798 | 0.70 | Manual import | Manual |
| Teller | 1 | $18,246 | 0.70 | Manual import | Manual |

### Data Quality Grades
| Grade | Count | Meaning |
|-------|-------|---------|
| GOLD | 6 | Fully verified: surplus + indebtedness + sale_date + confidence >= 0.7 |
| SILVER | 7+ | Good data but missing indebtedness or other field for GOLD |
| BRONZE | 4+ | Has surplus but incomplete data |
| REJECT | 29 | Expired deadlines, no surplus, or insufficient data |

---

## WHAT'S DONE (Completed Workstreams)

### WS1: Data Integrity
- Deduplication engine: finds/removes duplicate case_numbers, keeps most complete record
- Confidence scoring: penalizes missing indebtedness (max 0.5) and missing sale_date (max 0.6)
- Grade gating: GOLD requires indebtedness > 0, sale_date, confidence >= 0.7, completeness >= 1.0
- Daily regrade via healthcheck cron

### WS2: Admin Account System
- `schlieve001@gmail.com` auto-upgraded to sovereign + admin + 9999 credits on startup
- Admin endpoints: `/api/admin/stats`, `/api/admin/leads`, `/api/admin/regrade`, `/api/admin/dedup`, `/api/admin/users`, `/api/admin/upgrade-user`
- Admin bypasses rate limits and credit checks

### WS3: Card UI Readability
- WCAG AA contrast compliance (--text-muted: #8b9fc2)
- Larger font sizes for case numbers, badges, confidence text
- Pill-shaped badges for grade, confidence, days remaining
- Stacked card actions (UNLOCK INTEL + FREE DOSSIER)

### WS4+5: Dossier Generator
- 4-section professional layout: Asset Profile, Forensic Financial Analysis, Entity Intelligence, Recovery Strategy
- UNVERIFIED watermark when indebtedness missing
- Math proof: "Winning Bid ($X) - Total Indebtedness ($Y) = Surplus ($Z)"
- Legal disclaimer page for restricted leads

### WS6: Restricted Lead Sales
- `/api/unlock-restricted/{asset_id}` endpoint with attorney verification
- Requires bar_number + disclaimer acceptance (C.R.S. § 38-13-1302(5))

### WS7: Engine #4 (Vertex AI) — Production Rewrite
- **Old**: `vertex_engine.py` — broken draft referencing non-existent `leads` table
- **New**: `vertex_engine_production.py` — Gold Master production engine
  - Pre-flight checks: validates credentials JSON, schema columns, staged record count
  - OCR-aware `parse_money()` (handles O→0, spaces, parentheses)
  - Forced JSON schema extraction via Gemini
  - Exponential backoff (2^n + jitter, max 5 retries) on 429/503/500
  - JSONL audit log at `verifuse_v2/logs/engine4_audit.jsonl`
  - Computes confidence/grade using `daily_healthcheck` functions

### WS8: Frontend Migration
- Removed Airtable API keys from client-side .env
- Rewrote Hero.tsx to use V2 API Stats
- All API client functions updated for V2 endpoints

### WS9: Git + GitHub
- Full codebase committed (118+ files)
- Pushed to github.com/schlieve001-pixel/sentinel-v15-elite.git

### WS10: System Unification
- **`migrate_master.py`**: Idempotent migration utility
  - Checks all tables exist via `sqlite_master`
  - Adds missing columns: `assets_staging.{pdf_path, status, processed_at, engine_version}`, `assets.{winning_bid, vertex_processed}`
  - Verifies all required indexes
  - Logs migration event to `pipeline_events`
  - Run: `python -m verifuse_v2.db.migrate_master`
- **`verify_system.py`**: Green Light diagnostic
  - 8 check categories: DB, Schema, Data Integrity, Credentials, Vertex AI, Staging, API Server, File System
  - Formatted pass/fail output with totals
  - Run: `python -m verifuse_v2.verify_system`

### WS11: County Expansion (4 New Counties)
- **Larimer County** (Engine #7): Pre Sale List PDF scraper via apps.larimer.org GTS Search
- **Weld County** (Engine #8): Pre Sale List PDF scraper from weld.gov (predictable URL patterns)
- **Boulder County** (Engine #9): Pre Sale List PDF scraper via bouldercountypt.org GTS Search
- **Pueblo County** (Engine #10): Sale schedule page scraper (limited data, BRONZE grade)

---

## HOW TO RUN EACH COMPONENT

### Step-by-Step: Daily Operations

**1. Run the migration (first time or after schema changes):**
```bash
cd /home/schlieve001/origin/continuity_lab
python -m verifuse_v2.db.migrate_master
```
Expected output: "ALL CHECKS PASSED" with list of tables/columns/indexes.

**2. Run system verification:**
```bash
python -m verifuse_v2.verify_system
```
Expected output: GREEN LIGHT with pass/fail for each subsystem.

**3. Run all scrapers (via Governor pipeline):**
```bash
python -c "from verifuse_v2.pipeline_manager import Governor; g = Governor(); print(g.run_pipeline())"
```
This runs Engines 1-10 in sequence. Each engine downloads PDFs, parses data, and ingests into the database.

**4. Run individual county scrapers:**
```bash
# Adams County (post-sale, 100% verified data)
python -m verifuse_v2.scrapers.adams_postsale_scraper

# El Paso County (pre-sale, indebtedness data)
python -m verifuse_v2.scrapers.elpaso_postsale_scraper

# Larimer County (pre-sale)
python -m verifuse_v2.scrapers.larimer_scraper

# Weld County (pre-sale)
python -m verifuse_v2.scrapers.weld_scraper

# Boulder County (pre-sale)
python -m verifuse_v2.scrapers.boulder_scraper

# Pueblo County (sale schedule)
python -m verifuse_v2.scrapers.pueblo_scraper

# Denver (excess funds PDF)
python -m verifuse_v2.scrapers.denver_pdf_parser
```

**5. Process staged PDFs with Vertex AI (Engine #4):**
```bash
# Step A: Set up Google credentials
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/google_credentials.json"

# Step B: Run pre-flight checks only
python -m verifuse_v2.scrapers.vertex_engine_production --preflight-only

# Step C: Process 50 staged PDFs
python -m verifuse_v2.scrapers.vertex_engine_production --limit 50

# Step D: Process all staged PDFs
python -m verifuse_v2.scrapers.vertex_engine_production --limit 691
```

**6. Run daily healthcheck (regrade all assets):**
```bash
python -m verifuse_v2.daily_healthcheck
```
This re-evaluates all assets, updates grades/classes, closes expired deadlines, and generates a JSON report.

**7. Start the API server:**
```bash
cd /home/schlieve001/origin/continuity_lab
uvicorn verifuse_v2.api.server:app --host 0.0.0.0 --port 8000
```

### Automation: Cron Schedule
```bash
# Edit crontab
crontab -e

# Add these lines:
# Daily healthcheck at 6:00 AM MT (12:00 UTC)
0 12 * * * cd /home/schlieve001/origin/continuity_lab && python -m verifuse_v2.daily_healthcheck >> /var/log/verifuse_healthcheck.log 2>&1

# Weekly scraper run on Wednesdays at 2:00 PM MT (20:00 UTC) — after all county sales complete
0 20 * * 3 cd /home/schlieve001/origin/continuity_lab && python -c "from verifuse_v2.pipeline_manager import Governor; Governor().run_pipeline()" >> /var/log/verifuse_scrapers.log 2>&1

# Weekly Vertex AI processing on Thursdays at 6:00 AM MT
0 12 * * 4 cd /home/schlieve001/origin/continuity_lab && python -m verifuse_v2.scrapers.vertex_engine_production --limit 100 >> /var/log/verifuse_vertex.log 2>&1
```

---

## WHAT NEEDS TO BE DONE (Remaining Work)

### Priority 1: CRITICAL (This Week)
| # | Task | Status | How To Do It |
|---|------|--------|-------------|
| 1 | Deploy API server to verifuse.tech | NOT STARTED | Create `/etc/systemd/system/verifuse.service` with `ExecStart=uvicorn verifuse_v2.api.server:app --host 127.0.0.1 --port 8000`. Run `sudo systemctl enable --now verifuse`. |
| 2 | Build React frontend | NOT STARTED | `cd verifuse/site/app && npm install && npm run build`. Output goes to `dist/`. |
| 3 | Configure Caddy reverse proxy | NOT STARTED | Install Caddy: `sudo apt install caddy`. Create `/etc/caddy/Caddyfile`: `verifuse.tech { root * /path/to/dist file_server reverse_proxy /api/* localhost:8000 }`. Run `sudo systemctl restart caddy`. |
| 4 | Test Stripe billing end-to-end | NOT STARTED | Set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` env vars. Use Stripe CLI: `stripe listen --forward-to localhost:8000/api/stripe/webhook`. Create test checkout. |
| 5 | Set up Google credentials for Vertex AI | NOT STARTED | Place `google_credentials.json` in a secure location. Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/google_credentials.json`. Run `python -m verifuse_v2.scrapers.vertex_engine_production --preflight-only` to verify. |
| 6 | Process 691 staged PDFs via Vertex AI | NOT STARTED | After credentials setup: `python -m verifuse_v2.scrapers.vertex_engine_production --limit 691`. Monitor logs at `verifuse_v2/logs/engine4_audit.jsonl`. |

### Priority 2: HIGH (Next Sprint)
| # | Task | Status | How To Do It |
|---|------|--------|-------------|
| 7 | Automate daily healthcheck via cron | NOT STARTED | See cron schedule above. Verify: `crontab -l`. |
| 8 | Set up error monitoring (Sentry) | NOT STARTED | `pip install sentry-sdk`. Add `sentry_sdk.init(dsn="...")` to `api/server.py` startup. |
| 9 | Download more Adams County PDFs | EASY | Run `python -m verifuse_v2.scrapers.adams_postsale_scraper` — it auto-discovers new PDFs. |
| 10 | Monitor new county scrapers for data | ONGOING | Check logs after Wednesday sales. Adjust PDF URL patterns if needed. |

### Priority 3: MEDIUM (Post-Launch)
| # | Task | Status | How To Do It |
|---|------|--------|-------------|
| 11 | Migrate SQLite → Supabase PostgreSQL | NOT STARTED | Create Supabase project. Run `schema.sql` against it. Update `database.py` `get_connection()` to use `psycopg2`. |
| 12 | Email notifications for high-value leads | NOT STARTED | Use SendGrid or SES. Add hook in `ingest_records()` when GOLD lead created. |
| 13 | Admin dashboard UI | NOT STARTED | React admin panel calling `/api/admin/*` endpoints. |
| 14 | Monthly credit reset | NOT STARTED | Stripe webhook `invoice.paid` → reset user credits. |

---

## PIPELINE ARCHITECTURE

```
Engine 0: Governor (pipeline_manager.py)
  ├── Engine 1: Denver Signal Scraper (signal_denver.py)
  ├── Engine 2: Denver Outcome Scraper (outcome_denver.py)
  ├── Engine 3: Entity Resolver (entity_resolver.py)
  ├── Engine 4: Vertex AI PDF Extraction (vertex_engine_production.py)  ← PRODUCTION REWRITE
  ├── Engine 5: El Paso Pre-Sale Scraper (elpaso_postsale_scraper.py)
  ├── Engine 6: Adams Post-Sale Scraper (adams_postsale_scraper.py)
  ├── Engine 7: Larimer Pre-Sale Scraper (larimer_scraper.py)           ← NEW
  ├── Engine 8: Weld Pre-Sale Scraper (weld_scraper.py)                 ← NEW
  ├── Engine 9: Boulder Pre-Sale Scraper (boulder_scraper.py)           ← NEW
  └── Engine 10: Pueblo Schedule Scraper (pueblo_scraper.py)            ← NEW

Standalone Scrapers:
  ├── Denver PDF Parser (denver_pdf_parser.py)
  ├── Jefferson CSV Import (jefferson_scraper.py)
  └── Tax Lien Scraper (tax_lien_scraper.py)

System Utilities:
  ├── migrate_master.py    — Idempotent DB migration                    ← NEW
  └── verify_system.py     — Green Light diagnostic                     ← NEW
```

## COUNTY DATA SOURCES

| County | Platform | URL | Data Type | PDF Format |
|--------|----------|-----|-----------|------------|
| Denver | Custom | denvergov.org | Excess funds | Monthly PDF |
| Arapahoe | Custom | arapahoeco.gov | Overbid list | Manual |
| Jefferson | GTS | gts.co.jefferson.co.us | CSV export | Manual |
| Adams | GTS | apps.adcogov.org/PTForeclosureSearch | Post Sale List | Weekly PDF (Wed) |
| El Paso | GTS | elpasopublictrustee.com/GTSSearch | Pre Sale List | Weekly PDF (Wed) |
| Larimer | Custom | apps.larimer.org/publictrustee/search | Pre Sale List | Weekly PDF (Wed) |
| Weld | GTS | wcpto.com | Pre Sale List | Weekly PDF (Wed) |
| Boulder | GTS | bouldercountypt.org/GTSSearch | Pre Sale List | Weekly PDF (Wed) |
| Pueblo | Custom | county.pueblo.org | Sale schedule | HTML table |

## TECH STACK
- **Backend**: FastAPI + uvicorn (Python 3.11)
- **Database**: SQLite WAL mode (verifuse_v2.db)
- **Frontend**: React 19 + TypeScript + Vite
- **PDF Generation**: fpdf2 (dossiers, motions)
- **PDF Parsing**: pdfplumber (scrapers)
- **Auth**: JWT (HS256, 72-hour tokens) + bcrypt
- **Billing**: Stripe (3 tiers: recon $199, operator $399, sovereign $699)
- **AI**: Google Vertex AI / Gemini (Engine #4 PDF extraction)
- **Deployment Target**: verifuse.tech via Caddy + systemd

## LEGAL COMPLIANCE
- C.R.S. § 38-38-111: 180-day claim window enforced in all scrapers
- C.R.S. § 38-38-111(2.5)(c): Restriction period (6 months from sale) tracked per asset
- C.R.S. § 38-13-1304: 2-year blackout after transfer to State Treasurer
- C.R.S. § 38-13-1302(5): Attorney-client exemption for restricted lead access
- PII obfuscation: Owner names rendered as PNG images (not searchable text)
- No skip-tracing, no phone numbers, no direct homeowner contact

## TROUBLESHOOTING

| Problem | Solution |
|---------|----------|
| `Table 'leads' missing columns` | You're running the OLD vertex_engine.py. Use `vertex_engine_production.py` instead. |
| `Missing columns in assets_staging` | Run `python -m verifuse_v2.db.migrate_master` to add missing columns. |
| `GOOGLE_APPLICATION_CREDENTIALS not set` | Export the env var: `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json` |
| Vertex AI 429 errors | The engine has automatic exponential backoff. If persistent, wait 1 hour. |
| No PDFs downloaded for county X | Check URL patterns in the scraper. County websites change PDF paths periodically. |
| `verify_system.py` shows FAIL | Read the detail column — it tells you exactly what's missing and how to fix it. |
| API server not responding | Check `uvicorn` is running: `ps aux | grep uvicorn`. Restart: `sudo systemctl restart verifuse`. |
| Database locked | SQLite WAL mode handles this. If persistent: `sqlite3 verifuse_v2.db "PRAGMA wal_checkpoint(FULL)"` |

## FINANCIAL SUMMARY
| Metric | Value |
|--------|-------|
| Total Pipeline Value | $5,195,751.75+ |
| GOLD Verified Surplus | $338,106 |
| SILVER Actionable Surplus | $2,519,464+ |
| Staged for Vertex Processing | 691 PDFs |
| Active Counties | 11 |
| Active Engines | 10 |
| Subscription Tiers | 3 ($199 / $399 / $699 per month) |
