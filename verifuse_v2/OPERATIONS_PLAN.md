# VERIFUSE V2 — OPERATIONS PLAN
## Last Updated: February 14, 2026

---

## SYSTEM STATUS: OPERATIONAL

### Database Summary
| Metric | Value |
|--------|-------|
| Total Assets | 46 (38 after REJECT filter) |
| Total Pipeline Value | $5,195,751.75 |
| GOLD-Grade Verified Leads | 6 |
| SILVER-Grade Leads | 7 |
| Attorney-Ready (GOLD+SILVER, surplus >= $1K) | 13 |
| Counties Active | 7 (Denver, Arapahoe, Jefferson, Adams, El Paso, Mesa, Teller, Douglas) |
| Deduplication | 21 duplicates removed |

### County Breakdown
| County | Assets | Total Surplus | Avg Confidence | Data Source |
|--------|--------|--------------|----------------|-------------|
| Denver | 17 | $1,421,630 | 0.88 | Monthly excess funds PDF (no indebtedness) |
| Arapahoe | 12 | $1,426,297 | 0.92 | Overbid list (no indebtedness) |
| Jefferson | 5 | $2,026,675 | 0.64 | CSV import with written_bid (has indebtedness) |
| Adams | 4 | $258,106 | 0.95 | Weekly Post Sale List PDF (100% verified) |
| El Paso | 5 | $0 (pre-sale) | 0.95 | Weekly Pre Sale List PDF (has indebtedness, awaiting auction) |
| Mesa | 1 | $40,000 | 1.00 | Manual import |
| Douglas | 1 | $4,798 | 0.70 | Manual import |
| Teller | 1 | $18,246 | 0.70 | Manual import |

### Data Quality Grades
| Grade | Count | Meaning |
|-------|-------|---------|
| GOLD | 6 | Fully verified: surplus + indebtedness + sale_date + confidence >= 0.7 |
| SILVER | 7 | Good data but missing indebtedness or other field for GOLD |
| BRONZE | 4 | Has surplus but incomplete data |
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
- No "Money Truth" — professional forensic terminology

### WS6: Restricted Lead Sales
- `/api/unlock-restricted/{asset_id}` endpoint with attorney verification
- Requires bar_number + disclaimer acceptance (C.R.S. § 38-13-1302(5))
- Frontend: "ATTORNEY ACCESS ONLY" button with confirmation dialog

### WS7: Engine #4 (Vertex AI)
- Clean `vertex_engine.py` with OCR preprocessing, exponential backoff, PDF safety checks
- JSONL audit log for chain-of-custody
- Registered in pipeline as Engine #4

### WS8: Frontend Migration
- Removed Airtable API keys from client-side .env
- Rewrote Hero.tsx to use V2 API Stats
- All API client functions updated for V2 endpoints

### WS9: Git + GitHub
- Full codebase committed (118+ files)
- Pushed to github.com/schlieve001-pixel/sentinel-v15-elite.git
- Proper .gitignore excluding secrets, DB files, logs, archives

### WS10 (Extra): New County Scrapers
- **Adams County** (Engine #6): Post Sale List PDF parser — 100% verified data with bid, deficiency, overbid, total indebtedness. 9 PDFs downloaded, 4 surplus leads ingested.
- **El Paso County** (Engine #5): Pre Sale List PDF parser — verified indebtedness data. 5 foreclosure records ingested as PIPELINE leads awaiting auction outcomes.

---

## WHAT NEEDS TO BE DONE (Remaining Work)

### Priority 1: CRITICAL (This Week)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Deploy API server to verifuse.tech | NOT STARTED | systemd unit + Caddy reverse proxy |
| 2 | Build React frontend for production | NOT STARTED | `npm run build` in verifuse/site/app/ |
| 3 | Configure Caddy to serve frontend + proxy API | NOT STARTED | HTTPS auto-cert via Let's Encrypt |
| 4 | Test Stripe billing end-to-end | NOT STARTED | Test mode checkout → webhook → credit add |
| 5 | Download more Adams County PDFs (all available weeks) | EASY | More URLs to try in date pattern |

### Priority 2: HIGH (Next Sprint)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 6 | Process 691 staged PDFs via Vertex AI (Engine #4) | NOT STARTED | Requires GOOGLE_APPLICATION_CREDENTIALS |
| 7 | Add Larimer County scraper | RESEARCH DONE | Reports portal exists, indebtedness field unconfirmed |
| 8 | Add Weld County scraper | RESEARCH DONE | Has excess_funds page, needs field confirmation |
| 9 | Automate daily healthcheck via cron | NOT STARTED | `0 6 * * * python -m verifuse_v2.daily_healthcheck` |
| 10 | Set up error monitoring (Sentry) | NOT STARTED | Track API errors, scraper failures |

### Priority 3: MEDIUM (Post-Launch)
| # | Task | Status | Notes |
|---|------|--------|-------|
| 11 | Migrate SQLite → Supabase PostgreSQL | NOT STARTED | For multi-server deployment |
| 12 | Email notifications for high-value leads | NOT STARTED | When GOLD lead ingested, email attorneys |
| 13 | Admin dashboard UI | NOT STARTED | React admin panel for CTO |
| 14 | Monthly credit reset via Stripe webhooks | NOT STARTED | subscription.updated → reset credits |
| 15 | Uptime monitoring | NOT STARTED | healthcheck endpoint + external monitor |

---

## PIPELINE ARCHITECTURE

```
Engine 0: Governor (pipeline_manager.py)
  ├── Engine 1: Denver Signal Scraper (signal_denver.py)
  ├── Engine 2: Denver Outcome Scraper (outcome_denver.py)
  ├── Engine 3: Entity Resolver (entity_resolver.py)
  ├── Engine 4: Vertex AI PDF Extraction (vertex_engine.py)
  ├── Engine 5: El Paso Pre-Sale Scraper (elpaso_postsale_scraper.py)
  └── Engine 6: Adams Post-Sale Scraper (adams_postsale_scraper.py)

Standalone Scrapers:
  ├── Denver PDF Parser (denver_pdf_parser.py)
  ├── Jefferson CSV Import (jefferson_scraper.py)
  └── Tax Lien Scraper (tax_lien_scraper.py)
```

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

## FINANCIAL SUMMARY
| Metric | Value |
|--------|-------|
| Total Pipeline Value | $5,195,751.75 |
| GOLD Verified Surplus | $338,106 |
| SILVER Actionable Surplus | $2,519,464 |
| Staged for Vertex Processing | 691 PDFs |
| Active Counties | 7 |
| Subscription Tiers | 3 ($199 / $399 / $699 per month) |
