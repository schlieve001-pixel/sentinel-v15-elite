# Data Flow

This document traces the complete lifecycle of a foreclosure surplus lead from county website to end-user delivery.

## High-Level Pipeline

```
 County Public Trustee Website
           │
           ▼
 ┌─────────────────────┐
 │  SCRAPER LAYER      │   systemd timer → 2 AM daily
 │                     │
 │  Runner reads       │   counties.yaml → adapter selection
 │  counties.yaml      │
 │                     │
 │  Adapter scrapes:   │
 │  ├─ discover_pdfs() │   Find PDF URLs on county site
 │  ├─ download_pdfs() │   Download + deduplicate by SHA256
 │  └─ fetch_html()    │   Scrape HTML tables for structured data
 │                     │
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  RAW PDF STORAGE    │   verifuse_v2/data/raw_pdfs/{county_code}/
 │                     │   Filename: {county}_{sha256[:12]}.pdf
 │  Content-hashed     │   Duplicate PDFs detected and skipped
 │  deduplication      │
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  ENGINE V2          │   python -m verifuse_v2.scrapers.engine_v2
 │  (Titanium Parser)  │
 │                     │
 │  1. pdfplumber      │   Extract text from each PDF
 │     extract_text()  │
 │                     │
 │  2. Parser Registry │   Iterate PARSER_REGISTRY:
 │     detect(text)    │     AdamsParser → DenverExcessParser →
 │                     │     ElPasoPreSaleParser → ElPasoPostSaleParser →
 │                     │     GenericExcessFundsParser (fallback)
 │                     │
 │  3. extract(text)   │   Pull structured records:
 │                     │     case_number, owner_name, property_address,
 │                     │     winning_bid, total_debt, surplus_amount,
 │                     │     overbid_amount, sale_date
 │                     │
 │  4. score(record)   │   Confidence Function C ∈ [0.0, 1.0]
 │                     │
 │  5. grade(surplus,  │   GOLD / SILVER / BRONZE / IRON
 │     confidence)     │
 │                     │
 │  6. Threshold       │   conf > 0.8 → ENRICHED (write to DB)
 │     Routing         │   conf > 0.5 → REVIEW_REQUIRED (write to DB)
 │                     │   conf ≤ 0.5 → ANOMALY (log only, skip DB)
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  PIPELINE SCORING   │   python -m verifuse_v2.core.pipeline --evaluate-all
 │                     │
 │  completeness()     │   % of Tier 2 fields populated
 │  confidence()       │   Source trust - age penalty
 │  data_grade()       │   GOLD/SILVER/BRONZE/REJECT
 │  bs_detect()        │   WHALE_CAP / DATE_GLITCH / RATIO_TEST
 │                     │
 │  Re-grades all      │   Upgrades and downgrades logged to
 │  leads in DB        │   pipeline_events
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  QUARANTINE          │   python -m verifuse_v2.db.quarantine
 │                     │
 │  Ghost leads        │   conf ≤ 0.15 AND surplus = 0 → leads_quarantine
 │  Jefferson demote   │   False-GOLD without bid data → PIPELINE_STAGING
 │  Portal noise       │   Eagle/San Miguel debt-only → leads_quarantine
 │                     │
 │  WAL checkpoint     │   Always runs before mutations
 │  before mutations   │
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  SQLite DATABASE     │   verifuse_v2/data/verifuse_v2.db
 │  (WAL mode)         │
 │                     │
 │  leads table        │   The canonical lead store
 │  pipeline_events    │   Full audit trail
 │  lead_provenance    │   SHA256 provenance chain
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  FASTAPI SERVER     │   uvicorn verifuse_v2.server.api:app --port 8000
 │                     │
 │  GET /api/leads     │   SafeAsset projection (no PII)
 │                     │     - Surplus rounded to nearest $100
 │                     │     - City hint instead of full address
 │                     │     - Dynamic status: RESTRICTED/ACTIONABLE/EXPIRED
 │                     │
 │  POST /unlock       │   FullAsset (PII revealed)
 │                     │     - Requires JWT + credits
 │                     │     - Double Gate for RESTRICTED
 │                     │     - Atomic credit deduction
 │                     │
 │  GET /dossier       │   Generated document download
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  CADDY PROXY        │   verifuse.tech:443
 │                     │
 │  /api/* → :8000     │   Reverse proxy to FastAPI
 │  /*     → React     │   Serve SPA from /dist
 │                     │
 │  Auto-TLS (ACME)    │   Let's Encrypt certificates
 │  Security headers   │   X-Frame-Options, CSP, etc.
 └────────┬────────────┘
          │
          ▼
 ┌─────────────────────┐
 │  REACT FRONTEND     │   verifuse/site/app/
 │                     │
 │  Lead Grid          │   Browse leads by county, surplus, grade
 │  Lead Detail        │   View SafeAsset, request unlock
 │  Unlock Flow        │   Credit check → disclaimer → FullAsset
 │  Dashboard          │   County stats, scoreboard
 └─────────────────────┘
```

## Status Lifecycle

A lead's status is computed dynamically (never stored) based on UTC dates:

```
                    sale_date
                       │
                       ▼
            ┌──────────────────┐
            │    RESTRICTED    │   Within 6 calendar months of sale
            │                  │   (C.R.S. § 38-38-111)
            │  Requires:       │
            │  - Verified atty │
            │  - OPERATOR or   │
            │    SOVEREIGN     │
            └────────┬─────────┘
                     │  6 months pass
                     ▼
            ┌──────────────────┐
            │    ACTIONABLE    │   Past restriction period,
            │                  │   before claim deadline
            │  Any paid user   │
            │  with credits    │
            └────────┬─────────┘
                     │  claim_deadline passes
                     ▼
            ┌──────────────────┐
            │     EXPIRED      │   Claim deadline passed
            │                  │
            │  Cannot unlock   │   HTTP 410 Gone
            └──────────────────┘
```

## Data Grade Flow

```
  Parser output (surplus, confidence)
           │
           ▼
  ┌────────────────────────────────────────────────┐
  │  Engine V2 Grading (registry.py)               │
  │                                                │
  │  surplus >= $10,000 AND conf >= 0.8  → GOLD    │
  │  surplus >= $5,000  AND conf >= 0.6  → SILVER  │
  │  surplus > $0                        → BRONZE  │
  │  otherwise                           → IRON    │
  └────────────────────┬───────────────────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────┐
  │  Pipeline Re-grade (pipeline.py)               │
  │                                                │
  │  completeness=1.0 AND conf>=0.7 AND            │
  │    surplus>0 AND days_remaining>30   → GOLD    │
  │  completeness>=0.8 AND conf>=0.5     → SILVER  │
  │  completeness<0.8 or conf<0.5        → BRONZE  │
  │  expired or conf<0.2 or surplus<=0   → REJECT  │
  └────────────────────┬───────────────────────────┘
                       │
                       ▼
  ┌────────────────────────────────────────────────┐
  │  Quarantine (quarantine.py)                    │
  │                                                │
  │  Ghost leads (conf≤0.15, surplus=0)  → REMOVED │
  │  Jefferson false-GOLD                → DEMOTED │
  └────────────────────────────────────────────────┘
```

## Provenance Chain

Every lead that reaches attorney-ready status must have a provenance record:

```
  PDF file on county website
       │
       ├── SHA256 hash of PDF content
       │
       ▼
  lead_provenance table
       │
       ├── lead_id
       ├── source_url
       ├── source_hash (SHA256)
       ├── extracted_at
       │
       ▼
  attorney_packet_ready = 1
       │
       ▼
  Available via /api/leads/attorney-ready
```

The provenance chain is required before a lead can be marked `attorney_packet_ready=1` via the `POST /api/leads/{id}/attorney-ready` endpoint.
