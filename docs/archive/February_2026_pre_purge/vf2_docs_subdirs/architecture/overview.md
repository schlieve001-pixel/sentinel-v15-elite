# System Architecture Overview

## System Diagram

```
                            ┌─────────────────────────────────────────────┐
                            │              verifuse.tech (Caddy)          │
                            │  ┌──────────────┐    ┌──────────────────┐  │
                            │  │  React SPA   │    │  FastAPI (8000)  │  │
    Users ──── HTTPS ──────►│  │  /dist        │    │  /api/*          │  │
                            │  │  index.html   │    │  /health         │  │
                            │  └──────────────┘    └────────┬─────────┘  │
                            └───────────────────────────────┼────────────┘
                                                            │
                                     ┌──────────────────────┼──────────────┐
                                     │                      ▼              │
                                     │     ┌──────────────────────────┐   │
                                     │     │    SQLite (WAL mode)     │   │
                                     │     │    verifuse_v2.db        │   │
                                     │     │                          │   │
                                     │     │  leads                   │   │
                                     │     │  users                   │   │
                                     │     │  lead_unlocks            │   │
                                     │     │  leads_quarantine        │   │
                                     │     │  pipeline_events         │   │
                                     │     │  vertex_usage            │   │
                                     │     │  vertex_queue            │   │
                                     │     │  download_audit          │   │
                                     │     │  lead_provenance         │   │
                                     │     └──────────────────────────┘   │
                                     │                 ▲                   │
                                     │     ┌───────────┴──────────────┐   │
                                     │     │                          │   │
                           ┌─────────┼─────┤   Pipeline Components    │   │
                           │         │     │                          │   │
                           │         │     │  engine_v2 (PDF parser)  │   │
                           │         │     │  pipeline (scoring)      │   │
                           │         │     │  quarantine (cleanup)    │   │
                           │         │     │  staging_promoter        │   │
                           │         │     └──────────────────────────┘   │
                           │         │                                     │
                           │         │         Server (VPS)                │
                           │         └─────────────────────────────────────┘
                           │
            ┌──────────────┴──────────────────────────────────────┐
            │              Scraper Layer (systemd timers)          │
            │                                                      │
            │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
            │  │ RealForeclose│  │     GTS      │  │ CountyPage│ │
            │  │   Adapter    │  │   Adapter    │  │  Adapter  │ │
            │  │              │  │              │  │           │ │
            │  │ El Paso      │  │ Adams        │  │ Denver    │ │
            │  │ Larimer      │  │ Arapahoe     │  │ Jefferson │ │
            │  │ Mesa         │  │ Boulder      │  │ Pueblo    │ │
            │  │ Summit       │  │ Douglas      │  │ Pitkin    │ │
            │  │ Eagle        │  │ Weld         │  │ Routt     │ │
            │  └──────────────┘  │ Garfield     │  │ + 20 more │ │
            │                    └──────────────┘  └───────────┘ │
            │  ┌──────────────┐                                   │
            │  │   GovEase    │  ┌──────────────────────────────┐ │
            │  │   Adapter    │  │  Manual (CORA) — 15 counties │ │
            │  │ Teller       │  └──────────────────────────────┘ │
            │  │ San Miguel   │                                   │
            │  └──────────────┘                                   │
            └─────────────────────────────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────┐
            │     County Public Trustee    │
            │     Websites (64 counties)   │
            └──────────────────────────────┘
```

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Frontend** | React + TypeScript + Vite | SPA served by Caddy |
| **API Server** | FastAPI + Uvicorn | Runs on port 8000 |
| **Database** | SQLite 3 (WAL mode) | Single file at `verifuse_v2/data/verifuse_v2.db` |
| **Reverse Proxy** | Caddy v2 | Auto-TLS, serves static + proxies API |
| **Auth** | JWT (HS256) + bcrypt | 72-hour token expiry |
| **Billing** | Stripe Checkout + Webhooks | Monthly subscription with credit reset |
| **PDF Parsing** | pdfplumber | Text extraction from county PDFs |
| **AI Enrichment** | Vertex AI (Gemini 2.0) | Optional; for non-standard PDF formats |
| **Scraping** | requests + BeautifulSoup | PoliteCrawler with rate limiting |
| **Scheduling** | systemd timers | Scrapers at 2 AM daily, health checks |
| **OS** | Debian Linux | Cloud VPS |

## Component Map

### Server Layer (`verifuse_v2/server/`)

| Module | Responsibility |
|--------|---------------|
| `api.py` | FastAPI application. All endpoints. SafeAsset/FullAsset projection models. Lead status computation (RESTRICTED/ACTIONABLE/EXPIRED). Atomic credit deduction with `BEGIN IMMEDIATE`. |
| `auth.py` | JWT creation/verification, bcrypt password hashing, registration, login. |
| `billing.py` | Stripe integration: checkout sessions, webhook processing, credit resets. |
| `models.py` | Shared Pydantic models. |
| `obfuscator.py` | PII obfuscation for SafeAsset projection (city hints, rounded surplus). |
| `dossier_gen.py` | PDF dossier generation for unlocked leads. |
| `motion_gen.py` | Legal motion document generation. |

### Scraper Layer (`verifuse_v2/scrapers/`)

| Module | Responsibility |
|--------|---------------|
| `base_scraper.py` | `CountyScraper` ABC. Defines discover/download/parse lifecycle. |
| `registry.py` | `CountyParser` ABC + concrete parsers (Adams, Denver, El Paso, Generic). Confidence Function C. |
| `runner.py` | Config-driven orchestrator. Reads `counties.yaml`, instantiates adapters. |
| `engine_v2.py` | PDF enrichment engine. Scans `raw_pdfs/`, matches parsers, upserts to DB. |
| `adapters/` | Platform-specific adapters: RealForeclose, GTS, CountyPage, GovEase. |

### Data Layer (`verifuse_v2/db/`)

| Module | Responsibility |
|--------|---------------|
| `database.py` | Connection management, CRUD operations, dedup, WAL checkpoint. |
| `quarantine.py` | Ghost lead quarantine, Jefferson false-GOLD demotion. |
| `migrate*.py` | Schema migration scripts (one per sprint). |

### Pipeline Layer (`verifuse_v2/core/`)

| Module | Responsibility |
|--------|---------------|
| `pipeline.py` | Scoring engine: completeness, confidence, data grade, BS detector. |

### Attorney Tools (`verifuse_v2/attorney/`)

| Module | Responsibility |
|--------|---------------|
| `dossier_docx.py` | Word document dossier generation. |
| `case_packet.py` | HTML case packet for GOLD/SILVER leads. |

### Legal Module (`verifuse_v2/legal/`)

| Module | Responsibility |
|--------|---------------|
| `mail_room.py` | Rule 7.3 compliant solicitation letter generation. |

### Scripts (`verifuse_v2/scripts/`)

| Script | Purpose |
|--------|---------|
| `morning_report.py` | Daily health/value dashboard |
| `setup_stripe.py` | Stripe product creation helper |
| `onboard_attorney.py` | Attorney verification workflow |
| `forensic_ingest.py` | Manual data ingestion |
| `promote_jefferson.py` | Jefferson county data promotion |

## Request Lifecycle

1. User hits `https://verifuse.tech` -- Caddy serves React SPA
2. React calls `GET /api/leads?county=Denver&min_surplus=5000`
3. Caddy proxies to FastAPI on port 8000
4. FastAPI queries SQLite (WAL mode), projects SafeAsset (no PII)
5. User clicks "Unlock" -- `POST /api/leads/{id}/unlock`
6. API checks JWT, verifies tier/credits, enforces RESTRICTED gate
7. Atomic credit deduction via `BEGIN IMMEDIATE`
8. Returns FullAsset with PII (owner name, address, financial details)
