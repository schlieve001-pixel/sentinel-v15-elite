# Roadmap

Future development plans for VeriFuse, organized by priority and complexity.

---

## Near Term (Sprint 12-14)

### GovEase Adapter Hardening

**Status:** Teller and San Miguel counties are configured but disabled.

**Tasks:**
- Complete the GovEase adapter to handle JavaScript-rendered pages
- Test with Teller and San Miguel county data
- Enable in counties.yaml once stable

### Automated Pipeline Orchestration

**Status:** Pipeline components exist but run independently.

**Tasks:**
- Wire up `pipeline_manager.py` as a single daily orchestration job:
  1. Run scrapers (all enabled counties)
  2. Process PDFs through Engine V2
  3. Run pipeline scoring/re-grading
  4. Run quarantine
  5. Generate morning report
- Single systemd timer replaces individual timers

### Attorney Onboarding Flow

**Status:** Manual process via `scripts/onboard_attorney.py`.

**Tasks:**
- Build self-service attorney verification in the React frontend
- Colorado Attorney Registration lookup integration
- Automated bar number validation
- Email verification workflow

### Frontend Polish

**Tasks:**
- Lead detail page with RESTRICTED/ACTIONABLE/EXPIRED visual states
- Unlock flow with disclaimer modal for RESTRICTED leads
- Dashboard with county map visualization
- Credit balance and usage history page
- Mobile-responsive improvements

---

## Medium Term (Sprint 15-20)

### Supabase Migration

**Status:** Database module (`db/database.py`) is designed for swap. `SUPABASE_URL` and `SUPABASE_KEY` env vars are already placeholder-defined.

**Tasks:**
- Set up Supabase project with matching schema
- Swap `get_connection()` to return Supabase client
- Migrate data from SQLite to Supabase
- Enable Row Level Security (RLS) for multi-tenant access
- Replace `BEGIN IMMEDIATE` with Supabase transactions
- Update deploy guide for Supabase connection

**Benefits:**
- Real-time subscriptions (live lead updates)
- Built-in authentication (can replace custom JWT)
- Horizontal scaling for API reads
- Automatic backups
- Dashboard/analytics built-in

### Multi-State Expansion

> **PROJECTION -- TBD WITH CITATIONS**
>
> Multi-state expansion requires state-by-state analysis of foreclosure surplus statutes.

**Architecture:**
- Add `state` field to counties.yaml and leads table
- Create state-specific parser modules (e.g., `texas/`, `florida/`)
- State-specific restriction period logic (not all states have 6-month holds)
- State-specific compliance rules

**Priority States (by foreclosure volume):**
1. Texas -- Non-judicial foreclosure, different surplus rules
2. California -- Judicial and non-judicial, high property values
3. Florida -- Judicial foreclosure, 5-year surplus claim window
4. Ohio -- Sheriff sale surplus

**Per-State Work:**
- Research statutes governing surplus fund disposition
- Map county/clerk websites and data formats
- Build platform adapters for each state's auction systems
- Compliance review for state-specific solicitation rules

### Notification System

**Tasks:**
- Email alerts for new GOLD leads matching subscriber preferences
- County-specific watchlists
- Claim deadline approaching reminders (30 days, 7 days)
- Credit balance low warnings
- New county data available notifications

### Enhanced Scoring

**Tasks:**
- Property value cross-referencing (Zillow/Redfin API integration)
- Tax assessment data enrichment
- Historical sale price analysis
- Neighborhood-level surplus trend analysis
- Seasonal foreclosure pattern detection

---

## Long Term (Sprint 20+)

### Mobile Application

> **PROJECTION -- TBD WITH CITATIONS**
>
> Mobile app development timeline and cost estimates require validation.

**Approach:**
- React Native or Flutter for cross-platform
- Core features: lead browsing, unlock, dossier download
- Push notifications for new GOLD leads
- Offline dossier caching for field use

### API-First Platform

**Tasks:**
- Public API documentation (OpenAPI/Swagger)
- API key authentication for third-party integrations
- Webhook delivery for new leads matching criteria
- CRM integration (Clio, PracticePanther)
- Zapier/Make.com integration

### Advanced Attorney Tools

**Tasks:**
- Automated court filing preparation
- Motion templates for surplus fund claims
- Case timeline generator
- Multi-party surplus claim tracking (multiple claimants per surplus)
- Outcome tracking (claim success/failure with amounts recovered)

### Data Marketplace

> **PROJECTION -- TBD WITH CITATIONS**
>
> Marketplace revenue model requires market validation.

**Concept:**
- Bulk data exports for institutional buyers
- White-label data feeds for title companies
- Research API for academic/journalistic use
- Anonymous aggregate statistics (free tier)

### ML Enrichment Layer

**Tasks:**
- Train surplus amount predictor from historical data
- Property type classification from address
- Owner contact likelihood scoring
- Claim success probability model
- Automated parser generation from PDF samples

---

## Technical Debt

### Known Issues to Address

| Issue | Priority | Notes |
|-------|----------|-------|
| Legacy scrapers | Medium | Individual county scrapers (boulder_scraper.py, etc.) should be fully migrated to adapter pattern |
| Test coverage | High | Limited test suite; needs unit tests for parsers, integration tests for API |
| Error handling | Medium | Some adapter error paths silently swallow exceptions |
| WAL growth | Low | Need automated WAL checkpoint schedule |
| Log rotation | Low | No log rotation for anomaly JSONL file |
| Frontend build | Medium | Frontend requires separate build step; consider SSR or SSG |

### Architecture Improvements

| Improvement | Complexity | Impact |
|-------------|-----------|--------|
| Async database access | Medium | Better API concurrency (SQLite is sync) |
| Background task queue | Medium | Celery/RQ for PDF processing, email sending |
| Caching layer | Low | Redis for frequently-accessed lead lists |
| CDN for static assets | Low | Faster frontend load times |
| Health check alerting | Low | PagerDuty/Slack integration for failures |
| CI/CD pipeline | Medium | Automated testing and deployment |
| Container deployment | Medium | Docker + Docker Compose for reproducible deploys |

---

## Version History

| Sprint | Theme | Key Deliverables |
|--------|-------|-----------------|
| Sprint 5 | Schema Unification | Leads-native API, Enterprise Engine |
| Sprint 6 | Titanium Registry | Deterministic parser interface, Engine V2 |
| Sprint 7 | System Hardening | Frontend API contract, Gemini 2.0 fix |
| Sprint 8 | Production Hardening | Atomic deploys, quarantine, API key auth |
| Sprint 9 | Master Builder | Vertex gating, legal engine, full automation |
| Sprint 11 | Current | 64-county expansion, attorney tools, Sprint 11 deploy |
