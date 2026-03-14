> Updated: March 14, 2026

# VeriFuse

**Automated Colorado foreclosure surplus intelligence platform.**

VeriFuse identifies, validates, and classifies post-sale overbid equity so attorneys can pursue rightful funds on behalf of claimants under Colorado law. The platform automates the entire workflow from public record scraping through court-ready filing packet generation.

**Legal basis**: C.R.S. § 38-38-111 (foreclosure surplus), § 38-13-1304 (unclaimed property), HB25-1224 (10% fee cap, effective June 4 2025). Consult qualified counsel before acting on any classification output.

---

## Platform Status

| Metric | Current |
|---|---|
| Active counties | 20 |
| GOLD leads (verified surplus) | 59+ |
| Total verified surplus | $6.2M+ |
| Active scraper adapters | 7 |
| Gauntlet (test suite) | **62/62 PASS** |
| Legal filing templates | 6 (motion, notice, affidavit, certificate of service, exhibit A/B) |

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111+ (Python 3.11), ThreadPoolExecutor DB pool, SQLite WAL-mode |
| Scraper | Playwright 1.45+ (Chromium headless), Universal GovSoft Adapter |
| Frontend | React 18 + TypeScript + Vite, JWT auth, PWA (service worker + manifest) |
| Auth | HS256 JWT, RBAC (admin / attorney / public), token version revocation |
| Billing | Stripe Checkout + Webhooks, FIFO credit ledger, annual/monthly subscriptions |
| Email | SendGrid (transactional), HTML branded templates, SPF + DKIM configured |
| Testing | `bin/vf gauntlet` — 62 deterministic assertions |

---

## Subscription Tiers

| Tier | Price | Monthly Credits | Skip Trace |
|---|---|---|---|
| **Investigator** | $199/mo | 30 | $29/trace |
| **Partner** | $399/mo | 75 | $29/trace |
| **Enterprise** | $899/mo | 200 | 10 included/month |

> **Founding Attorney Program**: First 10 subscribers lock in current pricing forever.
> After 10 founding members, standard pricing increases to $299/$599/$1,199/mo.
> Sign-up bonus: 5 credits on registration.

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

# 5. Start frontend dev server (port 5173)
cd verifuse/site/app && npm run dev
```

---

## Key Commands

```bash
bin/vf gauntlet                          # Full test suite (62/62 PASS required)
bin/vf migrate                           # Apply pending SQL migrations
bin/vf scrape <county>                   # Scrape county foreclosure listings
bin/vf scrape <county> --case J2500346   # Single-case scrape
bin/vf gate4 <county>                    # Run Gate 4 dual-validation batch
bin/vf gate4 --lead-id <id>              # Re-grade a specific lead
bin/vf gate4 all                         # All counties Gate 4 batch
bin/vf pre-sale-scan                     # Pre-sale opportunity scan
bin/vf promote-eligible                  # Promote eligible leads by tier
bin/vf enrich-owners --all-counties      # Enrichment across all counties
bin/vf health-check                      # Run daily healthcheck now
bin/vf coverage-report                   # County coverage audit
bin/vf backup                            # Database backup
bin/vf serve                             # FastAPI dev server (port 8000)
```

---

## Architecture

### Data Pipeline (8 Gates)

```
BRONZE (scraped) → Gate 4 dual-validation → GOLD (verified surplus)
```

| Gate | Purpose |
|---|---|
| Gate 0 | Baseline integrity — raw case data from public trustee portals |
| Gate 1 | Security hardening — auth, rate limiting, BFCache, Stripe guard |
| Gate 2 | Evidence schema — html_snapshots, evidence_documents, field_evidence |
| Gate 3 | Scraper hardening — adaptive pagination, session management, anti-bot |
| Gate 4 | Dual-validation — HTML math check + voucher cross-check → GOLD or BRONZE |
| Gate 5 | Equity resolution — 5-tier classification, lien stack, net owner equity |
| Gate 6 | Attorney workspace — case tracking, territory claiming, court filings |
| Gate 7 | Evidence access — RBAC gate on document download, attorney-only |
| Gate 8 | One-command ops — `bin/vf` CLI, systemd services, monitoring |

### Verification States

| State | Meaning |
|---|---|
| `RAW` | Just scraped, no validation |
| `BRONZE` | Pre-validation or math mismatch |
| `SILVER` | Partial extraction |
| `GOLD` | Dual-validated: HTML math confirmed + provenance present |
| `READY_TO_FILE` | All 7 RTF criteria met — court packet can be generated |

### Equity Classifications (5-Tier)

| Classification | Meaning |
|---|---|
| `OWNER_ELIGIBLE` | Net equity > 0 after lien deduction |
| `LIEN_ABSORBED` | Junior liens ≥ gross surplus |
| `TREASURER_TRANSFERRED` | Explicit transfer evidence (CERTQH doc or TRANSFER_RE match) |
| `RESOLUTION_PENDING` | Insufficient data or < 30 months post-sale |
| `NEEDS_REVIEW_TREASURER_WINDOW` | > 30 months post-sale, no explicit transfer evidence |

---

## Project Layout

```
verifuse_v2/
  core/                   equity_resolution_engine.py, outcome_intelligence.py
  ingest/                 govsoft_extract.py (Gate 4 dual-validation)
  migrations/             001–020 SQL migration files
  scrapers/
    adapters/             govsoft_engine.py + 5 national adapter stubs
    county_registry.py    Canonical 20-county registry (adapter, URL, schema version)
  server/
    api.py                FastAPI server (3,200+ lines, 80+ endpoints)
    pricing.py            Canonical pricing (CREDIT_COSTS, ROLLOVER_DAYS, tiers)
  templates/court_filings/ motion, notice, affidavit, certificate, exhibit A/B
  daily_healthcheck.py    Self-healing county monitor (auto-triggers Gate 4)
  state_rules/            CO-specific statutory rule stubs

verifuse/site/app/src/
  pages/                  Landing, Pricing, Dashboard, LeadDetail, Admin, Account,
                          MyCases, Coverage, TaxDeed, UnclaimedProperty, PreviewVault
  lib/api.ts              Typed API client (60+ functions)
  App.tsx                 Routes

docs/
  ARCHITECTURE.md         System architecture
  RUNBOOK.md              Operations runbook

bin/vf                    One-command ops CLI
```

---

## Active Counties (20)

| County | Adapter | Status |
|---|---|---|
| Adams | GovSoft | Active |
| Arapahoe | GovSoft | Active |
| Archuleta | GovSoft | Active |
| Boulder | GovSoft | Active |
| Broomfield | GovSoft | Active |
| Clear Creek | GovSoft | Active (SSL bypass) |
| Denver | Custom | Active |
| Douglas | GovSoft | Active |
| Eagle | GovSoft | Active |
| El Paso | GovSoft | Active |
| Elbert | GovSoft | Active |
| Fremont | GovSoft | Active (referer bypass) |
| Garfield | GovSoft | Active |
| Gilpin | GovSoft | Active |
| Jefferson | GovSoft | Active |
| La Plata | GovSoft | Active |
| Larimer | GovSoft | Active |
| San Miguel | GovSoft | Active |
| Teller | GovSoft | Active |
| Weld | GovSoft | Active |

---

## Credit System

All credit operations use a FIFO ledger (`unlock_ledger_entries`) with atomic `BEGIN IMMEDIATE` SQLite transactions. No direct balance mutation — all debits flow through `_fifo_spend()`.

| Action | Cost |
|---|---|
| Lead unlock | 1 credit |
| Court filing packet | 3 credits |
| Premium dossier | 5 credits |
| RTF unlock | 3 credits |
| Skip trace (non-Enterprise) | $29 flat (dedicated skip_trace token) |
| Skip trace (Enterprise) | 10 included/month |

---

## Services (Production)

```
verifuse-api.service         FastAPI on port 8000 (Caddy reverse proxy → verifuse.tech)
verifuse-scrapers.service    Daily scraper + Gate 4 batch (all 20 counties)
verifuse-orchestrator.service Background task orchestrator (healthcheck, alerts, backfill)
```

---

## Security

- JWT HS256, token version revocation on password change / logout
- Account lockout: 5 failed attempts → 15-minute lockout
- RBAC: admin / attorney / public (role hierarchy enforcement)
- Rate limiting + shadow block (IP-based, exempt for localhost)
- No credentials in source code — all secrets via `/etc/verifuse/verifuse.env`
- Court filing packets include SHA256 calculation fingerprint for audit trail

---

## Testing

```bash
bash bin/vf gauntlet   # Must output: Results: 62/62 PASS, 0/62 FAIL
```

The gauntlet runs 62 deterministic assertions covering auth, RBAC, billing webhooks, evidence gates, scraper anti-block, and API contract. Any regression = blocked deploy.

---

## Legal

VeriFuse Technologies LLC. All rights reserved.

Platform output is for informational purposes only. Not legal advice. Users must independently verify all surplus amounts and claim eligibility. Claim windows and statutory amounts are subject to change. Consult qualified Colorado counsel before filing.
