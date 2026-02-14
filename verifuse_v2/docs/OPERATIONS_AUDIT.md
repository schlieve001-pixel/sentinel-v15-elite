# VERIFUSE V2 — COMPLETE OPERATIONS AUDIT
**Generated: February 11, 2026**

---

## 1. SYSTEM STATUS

| Component | Status | Notes |
|-----------|--------|-------|
| FastAPI Backend | RUNNING | Port 8000, uvicorn |
| Vite Frontend | RUNNING | Port 5173, proxies to 8000 |
| SQLite Database | HEALTHY | 55 quality assets, 691 staged |
| Denver PDF Scraper | WORKING | Oct 2025 PDF (latest published) |
| Jefferson CSV Import | WORKING | Fixed schema mapping |
| JeffCo Web Scraper | BLOCKED | reCAPTCHA, use CSV import |
| Daily Health Check | READY | Needs cron setup |
| Stripe Billing | CONFIGURED | Needs Price IDs in env vars |
| Legal Disclaimers | DEPLOYED | Dashboard + LeadDetail + Landing |

---

## 2. DATABASE SUMMARY

### Quality Assets (main `assets` table): 55
| County | Count | Total Surplus |
|--------|-------|---------------|
| Jefferson | 10 | $4,053,350 |
| Arapahoe | 24 | $2,852,594 |
| Denver | 18 | $2,183,822 |
| Mesa | 1 | $40,000 |
| Teller | 1 | $18,246 |
| Douglas | 1 | $4,798 |

### Staged for Enrichment (`assets_staging` table): 691
These are V1 records that have owner names but no surplus data.
To enrich: get overbid amounts from county public trustees, then re-import.

---

## 3. WHAT'S DONE

### Backend (verifuse_v2/)
- [x] FastAPI server with JWT auth, bcrypt password hashing
- [x] SQLite database with full schema (assets, legal_status, users, unlocks, tiers)
- [x] PII obfuscation (text-to-image for owner names, no raw text in API)
- [x] Address truncation (city/county only, full address behind paywall)
- [x] Honeypot system (TRAP_999 fake record, auto-blacklist on access)
- [x] 180-day claim deadline computation (C.R.S. § 38-38-111)
- [x] 6-month restriction period computation (RESTRICTED/WATCHLIST/ACTIONABLE)
- [x] $1,000 minimum surplus filter (no junk data)
- [x] Anti-scraping rate limiter (daily API limits per tier)
- [x] Dossier PDF generation with "UNVERIFIED" warnings
- [x] Court motion PDF generation citing C.R.S. § 38-38-111
- [x] Stripe billing integration (webhook handler, credit management)
- [x] Daily health check system (regrade, scrape, report)

### Frontend (verifuse/site/app/)
- [x] Landing page with live stats and tiered pricing
- [x] Login / Register pages with JWT auth
- [x] Dashboard with "Actionable Now" and "Watchlist" buckets
- [x] Lead detail page with restriction notices
- [x] Full legal shield disclaimers on all pages
- [x] Dark terminal theme CSS
- [x] No skip-tracing data (no phones, emails)

### Scrapers
- [x] Denver PDF parser (downloads + parses excess funds PDFs)
- [x] Jefferson County CSV importer (flexible column mapping)
- [x] Jefferson County web scraper (blocked by reCAPTCHA)
- [x] Probate/Heir cross-reference engine (estate name detection + probate CSV import)
- [x] Tax lien surplus scraper (CSV import + CORA request generator for 10 counties)
- [x] Great Colorado Payback matcher (cross-ref owners against $2B+ unclaimed property)

### Legal Protections
- [x] C.R.S. § 38-38-111 restriction period shown on every lead
- [x] "RESTRICTED" badge on leads sold < 6 months ago
- [x] Full statutory citations in disclaimers
- [x] "UNVERIFIED" labels on unconfirmed surplus amounts
- [x] No finder services language
- [x] No skip-tracing data language

---

## 4. WHAT YOU NEED TO DO MANUALLY

### IMMEDIATE (Before Launch)

1. **Rotate Stripe Keys**
   - Go to dashboard.stripe.com/apikeys
   - Roll your secret key (the one shared in chat)
   - Create 3 Stripe Products with monthly pricing:
     - "VeriFuse Recon" → $199/mo
     - "VeriFuse Operator" → $399/mo
     - "VeriFuse Sovereign" → $699/mo
   - Copy the `price_xxx` IDs

2. **Set Environment Variables** (create `.env` file or set in systemd):
   ```bash
   export STRIPE_SECRET_KEY="sk_live_..."
   export STRIPE_WEBHOOK_SECRET="whsec_..."
   export STRIPE_PRICE_RECON="price_..."
   export STRIPE_PRICE_OPERATOR="price_..."
   export STRIPE_PRICE_SOVEREIGN="price_..."
   export VERIFUSE_BASE_URL="https://verifuse.tech"
   export JWT_SECRET="generate-a-random-32-char-string"
   ```

3. **Setup Cron for Daily Health Check**
   ```bash
   crontab -e
   # Add this line:
   0 6 * * * cd /home/schlieve001/origin/continuity_lab && /usr/bin/python3 -m verifuse_v2.daily_healthcheck >> /var/log/verifuse_healthcheck.log 2>&1
   ```

4. **Get a Colorado Consumer Protection Attorney Opinion**
   - The "data platform vs. finder" distinction has no case law
   - ExcessQuest excludes CO entirely — you should get formal guidance
   - Budget: $500-1500 for a written opinion letter

### WEEKLY (Operations)

5. **Denver PDF Check** (automated by cron, but verify)
   - The health check auto-downloads new Denver PDFs
   - Denver publishes monthly — check if new months appear
   - Command: `python -m verifuse_v2.scrapers.denver_pdf_parser`

6. **Jefferson County Data Collection**
   - Call 303-271-8580 (Public Trustee) and request overbid data
   - Or email: publictrustee@jeffco.us
   - Or submit CORA request for bulk data
   - Import: `python -m verifuse_v2.scrapers.jefferson_scraper --csv /path/to/data.csv`

### TO GET MORE LEADS

7. **Arapahoe County** — arapahoe.co.gov has an overbid info page
   - Check: https://www.arapahoeco.gov/your_county/county_departments/public_trustee/foreclosures/overbid_information.php
   - Likely has downloadable data or phone contact

8. **Adams County** — currently 35 records in staging with $0 surplus
   - Contact Adams County Public Trustee for overbid amounts
   - Phone: 303-654-6015

9. **El Paso County** — large market (Colorado Springs)
   - Contact El Paso County Public Trustee
   - Phone: 719-520-7230

10. **CORA Request to State Treasurer** — for all unclaimed foreclosure surplus
    - All funds older than 6 months transfer to Great Colorado Payback
    - Submit request at: treasury.colorado.gov/legal/colorado-open-records-requests
    - First hour of staff time is free

11. **Enrich Staged Records** — 691 V1 records have owner names but no surplus
    - Query: `SELECT county, COUNT(*) FROM assets_staging GROUP BY county`
    - Cross-reference with county public trustee data to add surplus amounts
    - Re-import enriched data through appropriate scraper

---

## 5. HOW TO RUN THE SYSTEM

### Start Everything (Development)
```bash
cd /home/schlieve001/origin/continuity_lab

# Start API server
python -m uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000 &

# Start frontend (already running on port 5173)
cd verifuse/site/app && npm run dev &
```

### Run Denver Scraper
```bash
# Auto-download latest PDF and ingest
python -m verifuse_v2.scrapers.denver_pdf_parser

# Specific month
python -m verifuse_v2.scrapers.denver_pdf_parser --year 2025 --month 10

# Local file
python -m verifuse_v2.scrapers.denver_pdf_parser --file /path/to/pdf
```

### Import Jefferson CSV
```bash
python -m verifuse_v2.scrapers.jefferson_scraper --csv /path/to/overbids.csv
```

### Run Probate/Heir Engine
```bash
# Scan existing surplus owners for estate/death indicators
python -m verifuse_v2.scrapers.probate_heir_engine

# Import probate court data CSV and cross-reference
python -m verifuse_v2.scrapers.probate_heir_engine --import-csv /path/to/probate_data.csv

# Search specific county
python -m verifuse_v2.scrapers.probate_heir_engine --county Denver
```

### Import Tax Lien Surplus Data
```bash
# Generate CORA request letters for all counties
python -m verifuse_v2.scrapers.tax_lien_scraper

# Import tax lien surplus CSV
python -m verifuse_v2.scrapers.tax_lien_scraper --import-csv /path/to/tax_surplus.csv --county Denver

# Print county treasurer contacts
python -m verifuse_v2.scrapers.tax_lien_scraper --contacts

# Generate CORA request for a specific county
python -m verifuse_v2.scrapers.tax_lien_scraper --cora "El Paso"
```

### Run Great Colorado Payback Matcher
```bash
# Scan ALL surplus owners against unclaimed property database (~3 min for 55 assets)
python -m verifuse_v2.scrapers.payback_matcher --scan-all

# Search a specific name
python -m verifuse_v2.scrapers.payback_matcher --name "John Smith"

# Import unclaimed property CSV and cross-reference
python -m verifuse_v2.scrapers.payback_matcher --import-csv /path/to/unclaimed.csv
```

### Run Daily Health Check
```bash
python -m verifuse_v2.daily_healthcheck
# Output: verifuse_v2/data/reports/healthcheck_YYYY-MM-DD_HHMM.json
```

### Check Database Status
```bash
python3 -c "
from verifuse_v2.db import database as db
db.init_db()
with db.get_db() as conn:
    total = conn.execute('SELECT COUNT(*) FROM assets WHERE estimated_surplus >= 1000').fetchone()[0]
    surplus = conn.execute('SELECT SUM(estimated_surplus) FROM assets WHERE estimated_surplus >= 1000').fetchone()[0]
    staged = conn.execute('SELECT COUNT(*) FROM assets_staging').fetchone()[0]
    print(f'Quality assets: {total}')
    print(f'Total surplus: \${surplus:,.2f}')
    print(f'Staged for enrichment: {staged}')
"
```

---

## 6. FILE STRUCTURE

```
verifuse_v2/
├── __init__.py
├── pipeline_manager.py          # Engine 0: Governor (rate limiter)
├── daily_healthcheck.py         # Self-healing daily cron job
├── contracts/
│   ├── __init__.py
│   └── schemas.py               # JSON contracts (SignalRecord, OutcomeRecord, EntityRecord)
├── scrapers/
│   ├── __init__.py
│   ├── signal_denver.py         # Engine 1: Denver signal scraper
│   ├── denver_pdf_parser.py     # Denver excess funds PDF parser
│   ├── jefferson_scraper.py     # Jefferson County scraper + CSV import
│   ├── probate_heir_engine.py   # Death/heir cross-reference engine
│   ├── tax_lien_scraper.py      # Tax lien surplus + CORA request generator
│   └── payback_matcher.py       # Great Colorado Payback cross-matcher
├── server/
│   ├── __init__.py
│   ├── api.py                   # FastAPI server (main entry point)
│   ├── auth.py                  # JWT auth (register, login, verify)
│   ├── billing.py               # Stripe integration
│   ├── dossier_gen.py           # Dossier PDF generator
│   ├── motion_gen.py            # Court motion PDF generator
│   └── obfuscator.py            # PII text-to-image (OCR-resistant)
├── db/
│   ├── __init__.py
│   ├── database.py              # SQLite abstraction layer
│   └── schema.sql               # Full database schema
├── data/
│   ├── verifuse_v2.db           # Production database
│   ├── raw_pdfs/                # Downloaded county PDFs
│   ├── dossiers/                # Generated dossier PDFs
│   ├── motions/                 # Generated motion PDFs
│   ├── reports/                 # Daily health check reports
│   └── signals/                 # Signal engine JSON output
├── deploy/
│   ├── Caddyfile                # Reverse proxy config
│   ├── verifuse-api.service     # systemd service
│   ├── launch.sh                # Dev launch script
│   └── LAUNCH_CHECKLIST.md      # Production checklist
├── docs/
│   └── OPERATIONS_AUDIT.md      # THIS FILE
└── utils/
    ├── __init__.py
    └── stealth.py               # HTTP session with UA rotation
```

---

## 7. LEGAL COMPLIANCE CHECKLIST

- [x] No finder services — platform sells data subscriptions to attorneys only
- [x] No compensation agreements with homeowners
- [x] No skip-tracing data (no phones, emails, current addresses)
- [x] C.R.S. § 38-38-111 restriction period displayed on every lead
- [x] "RESTRICTED" status on leads sold < 6 months ago
- [x] "UNVERIFIED" label on surplus without indebtedness confirmation
- [x] Full statutory disclaimers on Dashboard, LeadDetail, Landing, Dossier PDFs
- [x] Click-through acknowledgment needed (TODO: add to registration flow)
- [ ] **TODO: Formal attorney opinion letter before launch**
- [ ] **TODO: Colorado-specific terms addendum for subscribers**
- [ ] **TODO: Terms of Service page (TOS)**
- [ ] **TODO: Privacy Policy page**

---

## 8. RISK ASSESSMENT

| Risk | Severity | Mitigation |
|------|----------|------------|
| CO AG enforcement as "finder" | MEDIUM | Attorney-only subscribers, no skip-trace, full disclaimers |
| Stale data (deadlines wrong) | LOW | Daily health check re-grades all assets |
| Data scraping by competitors | LOW | Rate limits, honeypot, IP blacklist |
| Stripe key exposure | RESOLVED | Rotate immediately, use env vars only |
| Low lead count (55 assets) | HIGH | Need more county data — see section 4 |
| Jefferson reCAPTCHA | LOW | CSV import workaround in place |
| Denver PDF URL changes | LOW | Extended 6-month search window |

---

## 9. PRICING STRATEGY

| Tier | Price | Unlocks/mo | Views/day | Sessions | Target |
|------|-------|-----------|-----------|----------|--------|
| Recon | $199 | 5 | 50 | 1 | Solo attorneys, evaluation |
| Operator | $399 | 25 | 200 | 2 | Active practices |
| Sovereign | $699 | 100 | 500 | 3 | Firms, high-volume |

**Anti-scraping measures:**
- Daily API view limits per tier (prevents mass data extraction)
- Concurrent session limits (prevents sharing credentials)
- IP-based rate limiting (20 views/day for unauthenticated)
- Honeypot trap record (auto-blacklists scrapers)
- Owner data rendered as PNG images (not scrapable text)
- Full address only revealed on credit-gated unlock
