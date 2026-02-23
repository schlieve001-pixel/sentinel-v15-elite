# VERIFUSE — ARCHITECT SESSION NOTES
## Last Updated: 2026-02-10
## Status: PRE-PRODUCTION AUDIT COMPLETE

---

## BUSINESS DECISIONS (LOCKED)

- **Model:** Subscription data platform (NOT finder, NOT percentage)
- **Customer:** Colorado attorneys (surplus recovery, RE, probate, consumer)
- **Pricing:** $199/mo (Recon) | $399/mo (Operator) | $699/mo (Sovereign)
- **Legal Entity:** LLC
- **Payments:** Stripe Subscriptions
- **Database:** Supabase PostgreSQL (free tier → $25/mo at scale)
- **Frontend:** React 19 + TypeScript + Vite (existing app at verifuse/site/app/)
- **Backend:** FastAPI (existing at verifuse_v2/server/api.py)
- **Domain:** verifuse.tech (Caddy reverse proxy, auto-HTTPS)
- **Landing:** Build into React app (single codebase, SOTA)
- **Renaissance Lab:** COMPLETELY SEPARATE. Never mention in same breath.

## LEGAL CONSTRAINTS (NON-NEGOTIABLE)

- NEVER contact property owners
- NEVER take percentage of recovery
- NEVER recommend specific attorneys to property owners
- NEVER provide legal advice
- Flat subscription fee only — no contingency, no per-recovery charge
- All disclaimers must appear on every page (see DISCLAIMERS section below)
- Colorado Surplus Funds Finders Act does NOT apply to data platforms
- Attorney-client fee arrangements are exempt from finder fee caps
- Must get CO attorney to review model before public launch

## DATABASE STATISTICS (as of 2026-02-10)

| Metric | Value |
|--------|-------|
| Total assets | 714 |
| ATTORNEY-class | 74 |
| GOLD-grade | 70 |
| GOLD with real surplus (>$0) | 12 |
| GOLD total claimable surplus | $1,426,297.16 |
| Top lead | Robert V. Kirk, Arapahoe, $380,969.23 |
| Average GOLD lead | $118,858 |
| Counties with actionable data | Arapahoe (12 leads), Jefferson (58 leads @ $0) |
| Expired/NULL days_remaining | 637 (89%) |
| Kill reason (670 CLOSED) | data_grade_reject |

## CRITICAL BUGS TO FIX

1. Jefferson 58 GOLD leads have $0 surplus — scraper not extracting overbid
2. Eagle (312) + San Miguel (250) = 562 assets all NULL days — portal shows debt only
3. Denver (8 assets) missing days_remaining — scraper not extracting sale_date
4. Scoring formula does NOT gate on surplus > $0 — allows $0 leads to reach GOLD
5. data_age_days always returns 0 — confidence never penalized
6. Airtable API key exposed client-side via VITE_ prefix in React .env

## WHAT EXISTS vs WHAT'S NEEDED

### EXISTS (working)
- V1 SQLite with 714 assets, scoring pipeline, audit trail
- V2 FastAPI with contracts, rate limiter, stealth session, obfuscator
- V2 dossier PDF generator, motion PDF generator
- React 19 frontend (dark terminal theme, scarcity UX, pricing cards)
- Caddy reverse proxy on verifuse.tech
- 21-county statute authority table
- Landing copy + Carrd embed CSS

### NEEDED (build next)
- [ ] Supabase PostgreSQL setup + V1 data migration
- [ ] V2 API connected to Supabase (not JSON files)
- [ ] JWT auth (Supabase Auth or custom)
- [ ] Stripe subscription integration
- [ ] React app connected to V2 API (not Airtable)
- [ ] Landing page built into React app
- [ ] Real lead grid from database (replace mock data)
- [ ] Unlock/credit system per tier
- [ ] Email alerts for new leads (weekly)
- [ ] Fix Jefferson/Denver scrapers
- [ ] Fix scoring gate (surplus > $1000)

## COMPETITOR LANDSCAPE

| Competitor | Price | Colorado? |
|------------|-------|-----------|
| ExcessQuest | $270-699/mo | EXCLUDED |
| ExcessElite | $40/pack | EXCLUDED |
| Surplus Systems | Unknown | EXCLUDED |
| PropStream | $99-699/mo | No surplus-specific |
| VERIFUSE | $199-699/mo | ONLY PLAYER |

## DISCLAIMERS (must appear on every page)

1. NOT AN ATTORNEY / NOT LEGAL ADVICE
2. NO ATTORNEY-CLIENT RELATIONSHIP
3. NO GUARANTEE OF FUNDS
4. RIGHT TO SELF-FILE (owner can contact Public Trustee directly)
5. PUBLIC RECORDS NOTICE (all data from public sources)
6. CONTINGENCY FEE DISCLOSURE (attorney sets own fees)
7. OPT-OUT mechanism
8. State compliance: C.R.S. § 38-38-111, C.R.S. § 38-13-1301

## ARCHITECTURE TARGET (SOTA)

```
verifuse.tech (landing + app)
├── / → Landing page (sales, pricing, disclaimers)
├── /login → Supabase Auth
├── /dashboard → Lead grid (obfuscated PII)
├── /lead/{id} → Lead detail + dossier download (free)
├── /unlock/{id} → Full data + motion PDF (costs credits)
└── /settings → Account, billing (Stripe portal)

api.verifuse.tech (FastAPI)
├── /api/leads → Paginated, filtered lead list
├── /api/lead/{id} → Single lead detail
├── /api/dossier/{id} → Generate + serve dossier PDF
├── /api/unlock/{id} → Deduct credit, return raw data + motion
├── /api/user/me → Profile + credit balance
├── /webhooks/stripe → Subscription events
└── /health → Status

Supabase (PostgreSQL)
├── assets (migrated from V1 SQLite)
├── legal_status (migrated)
├── statute_authority (migrated)
├── users (Supabase Auth)
├── subscriptions (Stripe sync)
├── unlocks (credit tracking)
└── pipeline_events (audit trail)
```
