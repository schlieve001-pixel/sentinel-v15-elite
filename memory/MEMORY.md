# VeriFuse — Project Memory

## What This Project Is
**VeriFuse**: Automated Colorado foreclosure surplus intelligence platform.
Identifies, validates, and classifies post-sale overbid equity for attorneys/claimants.
Legal basis: C.R.S. § 38-38-111 and § 38-13-1304 (HB25-1224: 10% fee cap, eff. June 4 2025).

## Stack
- **API**: FastAPI (Python 3.11), SQLite WAL-mode, ThreadPoolExecutor DB pool
- **Scraper**: Playwright 1.45+ (Chromium headless), Universal GovSoft Adapter
- **Frontend**: React 18 + TypeScript + Vite, JWT auth (localStorage), Stripe billing
- **Auth**: HS256 JWT, RBAC (admin / attorney / public)
- **Testing**: `bin/vf gauntlet` — 62 assertions (PASS)

## Key Directories
- `verifuse_v2/` — backend (API, scrapers, ingest, migrations, core logic)
- `verifuse_v2/server/api.py` — FastAPI server (3200+ lines)
- `verifuse_v2/server/pricing.py` — Canonical pricing (CREDIT_COSTS, ROLLOVER_DAYS, etc.)
- `verifuse_v2/ingest/govsoft_extract.py` — Gate 4 dual-validation
- `verifuse_v2/scrapers/adapters/govsoft_engine.py` — Universal GovSoft Adapter
- `verifuse_v2/core/equity_resolution_engine.py` — 5-tier equity classification
- `verifuse_v2/core/heir_notification.py` — Heir letter PDF generator (reportlab)
- `verifuse_v2/scrapers/assessor_lookup.py` — Assessor owner/mailing address lookup
- `verifuse_v2/scrapers/tax_lien_scraper.py` — Tax lien surplus (§ 39-11-151), writes to leads table
- `verifuse/site/app/src/pages/Admin.tsx` — 4-tab admin panel (Attorney Queue/Leads/Users/System)
- `verifuse/site/app/src/App.tsx` — Routes including /admin
- `verifuse/site/app/` — React frontend
- `bin/vf` — one-command ops CLI

## Gates Built (All Complete)
- Gate 0–8 fully implemented as of Feb 22-25, 2026
- Gate 8 = docs + one-command ops (`bin/vf`)

## Older Session History
See `memory/session_history.md` for Sessions 2–13 detail.

---

## Session 14 (Mar 5, 2026) — Dashboard Fixes + Auth Security + Competitive Edge
- **A1**: `counties_covered` in /api/stats = active GovSoft counties WITH real leads (was counting all 25 county_profiles). Dashboard KPI now uses `stats.counties_covered`.
- **A2**: system-stats user_counts now `WHERE is_admin = 0`.
- **A3**: pipeline-status: split `bronze_no_overbid` → `bronze_not_extracted` (NULL) + `bronze_zero_overbid` (confirmed $0). Added `no_surplus` action. Added `last_ingestion_ts` from ingestion_runs.
- **B1**: `_trigger_verification_email()` helper in api.py — auto-sends code at registration.
- **B2**: `_validate_password()` in auth.py — 8+ chars, uppercase, number, special char (HTTPException 400).
- **B3**: Password strength meter in Register.tsx (4-segment bar, Weak/Fair/Strong/Very Strong).
- **B4**: Account lockout: 5 failed attempts → 15-min lockout. Stored in `users.locked_until`. Returns 429.
- **B5**: POST /api/auth/forgot-password + POST /api/auth/reset-password + POST /api/auth/change-password.
- **B6**: ForgotPassword.tsx + ResetPassword.tsx new pages. Login.tsx "Forgot password?" link.
- **C1**: Claim deadline countdown panel in LeadDetail.tsx — progress bar + urgency label.
- **C2**: "NEW" badge (pulsing) in Dashboard LeadCard for GOLD/SILVER leads with data_age_days ≤ 7.
- **C3**: GOLD% column in Admin pipeline table. "no_surplus" and "✓ NO SURPLUS" label.
- **Migration 016**: failed_login_count, locked_until, password_reset_token, password_reset_sent_at added to users table.
- gauntlet: 62/62 PASS | npm build: 0 errors

## Session 15 (Mar 6, 2026) — Mega-Refactor: EPICs 1-4 + CO Expansion + PWA
- **Migration 017**: attorney_cases, attorney_territories tables + lead/user/county_profiles columns. `run_migrations.py` handles "duplicate column" OperationalError gracefully.
- **EPIC 3A**: net_to_borrower = gross - trustee_fees - foreclosure_costs - senior_debt - liens. confidence_pct (40/65/85%).
- **EPIC 3B**: `_require_role(user, min_role)` + role hierarchy. `create_token()` includes `role` + `is_admin` JWT claims. nginx_admin_subdomain.conf generated.
- **EPIC 3E**: `_build_html_email()` branded HTML template. Verification + forgot-password send HTML via SendGrid.
- **EPIC 1A-E**: Landing copy, Dashboard BRONZE→"PENDING VERIFICATION", LeadDetail "FILING WINDOW STATUS", Admin GRADE→CONFIDENCE.
- **EPIC 2A**: `GET /api/search?q=` + Dashboard search bar (300ms debounce).
- **EPIC 2B**: Advanced filter panel (date range, surplus range, actionable-only, sort-by) in Dashboard.
- **EPIC 2C**: `GET /api/lead/{id}/timeline` + collapsible CASE TIMELINE panel in LeadDetail.
- **EPIC 2D**: `quality_badge` (VERIFIED/PARTIAL/ESTIMATED) in `_row_to_full()`.
- **EPIC 2E**: `GET /api/coverage-map` (no auth). `/coverage` page with 64-county grid + county detail panel.
- **EPIC 2G**: Scraper Health table in Admin System tab.
- **EPIC 2H**: Activity log paginated UI with action-type filter buttons in Admin.
- **EPIC 2I**: `POST/GET/DELETE /api/admin/users/{id}/api-key` + Admin Users tab API Key column.
- **EPIC 4A**: attorney_cases CRUD + `/my-cases` Kanban page (5 columns).
- **EPIC 4B**: `_compute_opportunity_score()` 0-10 score in `_row_to_full()`.
- **EPIC 4C**: `GET /api/lead/{id}/title-stack` + collapsible TITLE STACK panel in LeadDetail.
- **EPIC 4D**: `POST /api/lead/{id}/court-filing` ZIP endpoint + templates (motion, notice, affidavit).
- **EPIC 4E**: `/api/territories` CRUD. Territory warning placeholder in LeadDetail.
- **EPIC 4H**: `POST /api/my-cases/{id}/outcome` + attorney outcomes summary in system-stats.
- **EPIC 1C**: Owner name masking in `_row_to_full()` (J. Smith pattern when locked + non-admin).
- **PWA**: manifest.json, sw.js (shell precache), service worker registration in main.tsx. theme-color #0f172a.
- **CO Expansion**: bin/vf coverage-report, pdf-intake, research-county, scraper-run added. PDF intake creates BRONZE lead.
- **Routes**: `/coverage` + `/my-cases` added to App.tsx.
- gauntlet: 62/62 PASS | npm build: 0 errors (3.80s)

## Session 16 (Mar 8, 2026) — Pre-Sale Pipeline Fix + Admin Ops Center + Production

### Pre-Sale Pipeline Root Cause Found
- DB audit revealed: ZERO PRE_SALE processing_status leads — pending-sales scraper had NEVER run
- govsoft_engine.py bug: `_upsert_presale()` hard-rejected ALL cases without `scheduled_sale_date`
- Fix: removed hard reject — now accepts cases even without date (soft quality gate: only reject confirmed past dates)
- SOTA HTML parser: 3× date regexes (MM/DD/YYYY, ISO, Month D YYYY), <dd>/<td>/plain-text fallbacks for owner/address/lender
- bin/vf promote-presale: DB scan of future-dated PENDING leads → PRE_SALE (0 today, but ready when scraper runs)

### Admin Ops Center (default tab on /admin load)
- POST /api/admin/ops/run — trigger any pipeline job (14-command whitelist, no shell injection)
- GET /api/admin/ops/jobs — list recent jobs
- GET /api/admin/ops/jobs/{id} — full output + live polling
- POST /api/admin/ops/promote-presale — instant PRE_SALE promotion
- GET /api/admin/ops/pipeline-summary — GOLD/SILVER/BRONZE/PRE_SALE/gate4_ready/snapshot_counts
- Admin.tsx: OPS CENTER tab (opens by default) — KPI row, county selector, 11 command buttons, job list, terminal log viewer
- Migration 018: ops_jobs table auto-created at startup

### Production State
- API v4.8 live — 62/62 gauntlet PASS — npm build 0 errors
- gate4_ready: 251 BRONZE leads have SALE_INFO snapshots ready for extraction
- Key: html_snapshots.asset_id = 'FORECLOSURE:CO:{COUNTY_UPPER}:{CASE_NUMBER}' (NOT UUID)
- subprocess uses /bin/bash explicitly (env PATH doesn't have bash in spawned proc)
- ops_jobs table stores job output (64KB cap) + exit code + duration

### Next Steps for Pre-Sale Data
- Run: bin/vf gate4-run-all (or via Ops Center) to promote 251 BRONZE → GOLD/SILVER
- Run: bin/vf pending-sales --county {adams|jefferson|weld|boulder|...} to capture future auctions
- All Ops Center buttons are connected and working
