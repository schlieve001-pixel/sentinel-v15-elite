# VeriFuse — Session History (Sessions 2–13)

## Session 2 (Mar 1, 2026) — 4-Issue Bug Sprint (commit 70bc11c)
- attorney_ready + total_claimable_surplus exclude REJECT grade (was inflated by 12 leads + $1.47M)
- county_list returns raw slugs (not title-cased) — county filter now matches DB correctly
- Admin bypasses RESTRICTED gate in /api/leads/{id}/unlock (added `and not _effective_admin()`)
- stream_breakdown added to /api/stats — shows revenue by surplus_stream
- 011_county_expansion.sql: county_profiles expanded from 10 → 25 real CO counties
  - Fixed el_paso+larimer (010 used invalid platform_type='realforeclose', silently failed)
  - Added: denver, teller, summit, san_miguel, garfield, pueblo, fremont, la_plata, montrose, morgan, elbert, chaffee, gunnison
- county_profiles CHECK allows only ('govsoft','custom','unknown') — never 'realforeclose'!
- Dashboard: revenue streams section (admin), county display fixes ("EL PASO" not "EL_PASO")
- gauntlet: 62/62 PASS

## Session 3 (Mar 1, 2026) — Data Integrity + OCR Fixes
- J2500358 GOLD promotion: extracted sale_date from SALE_INFO HTML, ran Gemini OCR on ckreq.pdf
- J2500402 GOLD: was already promoted in prior session via ckreq.pdf OCR (all 3 dup doc IDs)
- field_evidence CHECK constraint updated: added 'gemini_unverified','gemini' to ocr_source
- GEMINI_MODEL: gemini-1.5-flash-002 (404) → gemini-2.0-flash in /etc/verifuse/verifuse.env
- Deleted 2 unverifiable seeded Adams leads (A202581412, A202581417 — no ingestion_source)
- Fixed govsoft_county_configs search_path for adams, douglas, jefferson, larimer, broomfield, gilpin → '/'
- Ran 4-year window scrapers on all active counties: only finding current redemption-period cases
- All 12 GOLD leads now have property_address (extracted from CASE_DETAIL HTML snippets)
- gauntlet: 62/62 PASS, heir letter tests: 9/9 PASS

## Session (Mar 1, 2026) — Full Product Buildout + Dashboard Overhaul
E1-E8: All complete. Committed f7787a2.
- E1: Admin role gets attorney UI via is_admin flag
- E2: Sovereign→250 credits, ROLLOVER_DAYS, MAX_BANK_MULTIPLIER, CREDIT_COSTS, INVESTIGATION_PACK
- E3: Admin.tsx (4 tabs) + /admin route + reject endpoint
- E4: 010_surplus_streams.sql + seed_counties() + bin/vf seed-counties
- E5: extract_with_gemini() + canonical ID snapshot fallback in govsoft_extract
- E6: assessor_lookup.py (Jefferson/Arapahoe/Adams/Denver)
- E7: leads table with surplus_stream='TAX_LIEN' + bin/vf tax-lien-run
- E8: heir_notification.py + POST /api/assets/{asset_id}/heir-letter
- H1: /api/stats adds silver_grade, bronze_grade, reject_grade, county_list
- H2: 8 KPI cards, 30s polling, dynamic county filter, grade badges, admin county table
- K1: setup_stripe.py rewritten, K4: billing.py tier names fixed

## Data State (as of Mar 2, 2026 — Session 4)
- 1297 total leads (17 GOLD, 12 SILVER, 600 BRONZE, 668 REJECT)
- Jefferson sequential enum (J250 0001-0500) added ~500 leads (all BRONZE initially, Gate 4 needed)
- Pipeline surplus: $3.2M (GOLD+SILVER+BRONZE non-zero)
- Jefferson now has 573 leads (up from 74)

## Session 4 (Mar 2, 2026) — Admin Power-Up + Pricing Page
### Scraper improvements:
- GovSoft "Deeded" status scraping added to run_date_window() — iterates Sold+Deeded
- Sequential case enumerator added to govsoft_engine.py + ingest_runner + bin/vf scraper-enum
- El Paso .tif skip: reads SALE_INFO HTML first, skips docs if overbid=$0
- Jefferson enum (J250 0001-0500): found 500+ more cases

### Admin System Tab (Task #11):
- `/api/admin/system-stats` — new endpoint: DB size, scoreboard, user counts, Stripe status, audit log (50 entries)
- `/api/admin/audit-log` — paginated audit log (admin only, filterable by action/email)
- coverage_report.py: added `leads_count` per county + field aliases
- Admin.tsx SystemTab: full rebuild with 6 sections (health/DB, scoreboard, users/billing, county coverage, activity feed, admin actions)

### Admin auth + restricted view (Task #12):
- GET /api/lead/{id}: admin now gets auto-unlock (unlocked_by_me=True, returns _row_to_full() with PII)
- POST /api/leads/{id}/unlock: EXPIRED check now bypassed for admin
- `/api/admin/lead-audit/{lead_id}` — forensic audit trail: all DB records for a case
- LeadDetail.tsx: admin "CASE AUDIT TRAIL" section (expandable)

### Pricing page (Task #13):
- `/pricing` route added to App.tsx + Pricing.tsx created
- Shows all 7 products: Associate/Partner/Sovereign + Starter/Investigation/Filing Pack/Premium Dossier
- `/api/billing/one-time` endpoint added (handles all 4 one-time SKUs)
- billing.py tier rank fixed: scout/operator → associate/partner; cancelled tier → 'associate'

### Stripe (Task #13 — COMPLETE):
- All 7 products live in Stripe test mode: Associate $149/mo, Partner $399/mo, Sovereign $899/mo, Starter $49, Investigation $99, Filing Pack $49, Premium Dossier $79
- Webhook: https://verifuse.tech/api/webhook
- All keys in /etc/verifuse/verifuse.env
- gauntlet: 62/62 PASS

## Session (Mar 5, 2026) — Ownership UX + Fortune 1000 Polish
- SendGrid key live in /etc/verifuse/verifuse.env, service restarted
- Toast: `src/components/Toast.tsx` — `toast(msg, type)` singleton, `ToastContainer` mounted in App.tsx
- LeadDetail: auto-unlock useEffect when `lead.unlocked_by_me===true` (silent re-unlock)
- LeadDetail: "ALREADY UNLOCKED — INTEL BELOW ↓" banner; toast on unlock success
- Dashboard: viewMode (actionable/watchlist/my_leads) + view-tabs CSS
- Dashboard: LeadCard shows OWNED badge, "OPEN INTEL →" button, green border for owned leads

## Session 12 (Mar 5, 2026) — Fortune 1000 Backend + Hover Tooltips + Gate 4 (commit d35214b)
- api.py v4.2.0: GZip, request_lifecycle_middleware (X-Request-ID, X-Response-Time, HSTS, X-Frame-Options)
- Global + HTTP exception handlers: `{"error":{"code","message","request_id"}}` envelope
- /health: full dependency status (DB size/leads/WAL, Stripe, SendGrid, GCP)
- _thread_conn: +PRAGMA cache_size=-65536 (64MB), mmap_size=268435456 (256MB), temp_store=MEMORY
- _with_busy_retry: exponential backoff on SQLite locked errors
- _stats_cache: 30s TTL in-process cache for /api/stats
- /api/admin/pipeline-status: per-county Gate 4 readiness endpoint
- verifuse_v2/utils/logging_setup.py: JSON structured logger → verifuse_v2/logs/api_structured.jsonl
- Tooltip.tsx: CSS-positioned popover (180ms delay, 4 positions, aria-describedby)
- KpiCard: tooltip prop — all 9 KPI cards have explanatory tooltips
- LeadCard: tooltips on grade badge, timer badge, restriction/owned badges, surplus; MAX FEE display (10% HB25-1224)
- Admin: Coming Soon revenue stream tiles (TAX_DEED/HOA/UNCLAIMED_PROPERTY) with CO market estimates
- bin/vf gate4-run-all: Phase 1 (adams/weld/douglas/gilpin/arapahoe/denver) + Phase 2 (jefferson/boulder/broomfield)
- Gate 4 Phase 1: 45 → 48 GOLD | Jefferson SALE_INFO backfill started (Playwright, 534 cases)
- county_profiles: last_scraped_at column does NOT exist — use last_verified_ts
- html_snapshots: uses snapshot_type (NOT tab_name) and asset_id canonical format (NOT case_number)
- county_badge in LeadCard now applies .replace(/_/g, " ").toUpperCase() for display

## Session 13 (Mar 5, 2026) — 11 New GovSoft Counties + Engine Fixes (commits 8ba3acc, a630bd9)
- Research: 21 CO counties confirmed GovSoft/GTSData; 4 RealForeclose; ~35 rural paper-only
- Added 11 new govsoft_county_configs entries: garfield, la_plata, teller, elbert, clear_creek, archuleta, san_miguel, routt, delta, gunnison + existing fremont
- WORKING new counties: garfield (2 leads), la_plata (4 leads, 2 GOLD!), teller (11 leads, 3 GOLD), elbert (2 leads), archuleta (1 GOLD), san_miguel (1 GOLD)
- Blocked new counties: fremont (403), routt (404), delta (DNS fail), clear_creek (SSL expired), gunnison (DNS fail)
- La Plata URL: `https://foreclosures.lpcgov.org/` + requires_accept_terms=1
- govsoft_engine.py bug fix: _navigate_and_search now does goto(search_url) before form interaction
- govsoft_extract.py bug fix: result["data_grade"] was stale — now re-reads actual grade from DB after _write_results
- Jefferson SALE_INFO backfill: 100% failure — GovSoft requires ASP.NET session; cannot fix without session establishment
- Total GOLD: 54 (was 48) | SILVER: 9
- gauntlet: 62/62 PASS
