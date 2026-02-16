# Codebase Map

File-by-file guide to the VeriFuse V2 codebase. All paths are relative to `verifuse_v2/`.

---

## Top-Level Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package init. Sets version string. |
| `requirements.txt` | Python dependencies (FastAPI, pdfplumber, bcrypt, stripe, etc.) |
| `README.md` | Brief project readme |
| `ARCHITECT_NOTES.md` | Architecture decision records |
| `OPERATIONS_PLAN.md` | Detailed operations planning document |
| `pipeline_manager.py` | Full pipeline orchestrator (discovery, enrichment, scoring, promotion) |
| `staging_promoter.py` | Promotes leads from staging to production after validation |
| `daily_healthcheck.py` | Comprehensive system health check script |
| `verify_system.py` | System verification: checks DB, API, schema, and data integrity |

---

## `server/` -- API Layer

| File | Lines | Purpose |
|------|-------|---------|
| `api.py` | ~1233 | **Main FastAPI application.** All endpoints live here: /health, /api/leads, /api/leads/{id}/unlock, /api/auth/*, /api/billing/*, /api/admin/*, /api/dossier/*, /api/letter/*, /api/case-packet/*. SafeAsset/FullAsset Pydantic models. Dynamic status computation (RESTRICTED/ACTIONABLE/EXPIRED). Atomic credit deduction. Rate limiting via slowapi. CORS for verifuse.tech. |
| `auth.py` | ~171 | JWT authentication. bcrypt password hashing. Token creation (HS256, 72h expiry) and verification. Registration and login functions. Helper functions: `get_current_user()`, `require_admin()`, `verify_attorney()`. |
| `billing.py` | ~212 | Stripe integration. Checkout session creation. Webhook handler for: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`. Per-tier credit allocation and daily API limits. |
| `models.py` | | Shared Pydantic models used across the server. |
| `obfuscator.py` | | PII obfuscation for SafeAsset projection. Rounds surplus, extracts city hints. |
| `dossier_gen.py` | | PDF dossier generation using fpdf2. |
| `motion_gen.py` | | Legal motion document generation. |
| `test_server.py` | | API tests. |

---

## `scrapers/` -- Scraper Layer

| File | Lines | Purpose |
|------|-------|---------|
| `base_scraper.py` | ~170 | **CountyScraper ABC.** Abstract base class for all platform adapters. Defines lifecycle: `discover_pdfs()` -> `download_pdfs()` -> `fetch_html_data()` -> `run()`. SHA256 content hashing for PDF dedup. PoliteCrawler integration. Context manager support. |
| `registry.py` | ~612 | **Titanium Parser Registry.** `CountyParser` ABC with `detect()`, `extract()`, `score()` methods. Confidence Function C formula. Concrete parsers: AdamsParser, DenverExcessParser, ElPasoPreSaleParser, ElPasoPostSaleParser, GenericExcessFundsParser. Helper functions: `clean_money()`, `parse_date()`. `PARSER_REGISTRY` list. |
| `runner.py` | ~210 | **Scraper Runner.** Config-driven orchestrator. Reads `config/counties.yaml`, maps platform to adapter class, runs scrape cycles. CLI: `--all`, `--county`, `--dry-run`, `--force`, `--status`. Logs results to pipeline_events. |
| `engine_v2.py` | ~368 | **Engine V2 (The Instrumentalist).** Scans `data/raw_pdfs/` for all PDFs, extracts text via pdfplumber, matches parsers, computes confidence/grade, routes by threshold (ENRICHED/REVIEW_REQUIRED/ANOMALY), upserts to leads table. |
| `adapters/realforeclose_adapter.py` | | RealForeclose.com adapter. Scrapes calendar pages, finds auction result PDFs. |
| `adapters/gts_adapter.py` | | GTS (ASP.NET) adapter. Handles ViewState forms, search submission. |
| `adapters/county_page_adapter.py` | | Generic county webpage adapter. Finds PDF links by pattern matching. |
| `adapters/govease_adapter.py` | | GovEase auction platform adapter. |
| `vertex_engine.py` | | Vertex AI (Gemini) integration for non-standard PDF formats. |
| `vertex_engine_enterprise.py` | | Enterprise version of Vertex engine with queue management. |
| `vertex_engine_production.py` | | Production-hardened Vertex engine with budget controls. |
| `denver_pdf_parser.py` | | Legacy Denver-specific PDF parser (superseded by registry). |
| `signal_denver.py` | | Denver signal detection. |
| `outcome_denver.py` | | Denver outcome tracking. |
| `boulder_scraper.py` | | Legacy Boulder-specific scraper. |
| `jefferson_scraper.py` | | Legacy Jefferson-specific scraper. |
| `larimer_scraper.py` | | Legacy Larimer-specific scraper. |
| `weld_scraper.py` | | Legacy Weld-specific scraper. |
| `pueblo_scraper.py` | | Legacy Pueblo-specific scraper. |
| `adams_postsale_scraper.py` | | Adams County post-sale list scraper. |
| `elpaso_postsale_scraper.py` | | El Paso County post-sale scraper. |
| `tax_lien_scraper.py` | | Tax lien data scraper. |
| `manual_ingest.py` | | Manual data ingestion from CORA responses. |
| `payback_matcher.py` | | Matches payback/redemption records to leads. |
| `probate_heir_engine.py` | | Probate/heir research engine. |

---

## `db/` -- Database Layer

| File | Purpose |
|------|---------|
| `database.py` | **Core database module.** Connection management (SQLite + WAL). CRUD operations for leads, users, unlocks. Deduplication. WAL checkpoint. Context manager `get_db()`. Designed for future Supabase swap. |
| `quarantine.py` | **Quarantine engine.** Moves ghost leads (zero-value Vertex artifacts) to `leads_quarantine`. Demotes Jefferson false-GOLDs. WAL checkpoint before mutations. All actions logged to pipeline_events. |
| `migrate.py` | Base schema migration. |
| `migrate_titanium.py` | Sprint 6 Titanium schema additions. |
| `migrate_master.py` | Sprint 9 master schema (Vertex gating, legal engine). |
| `migrate_sprint11.py` | Sprint 11 schema (attorney tools, download audit). |
| `migrate_plans.py` | Billing plan table migration. |
| `fix_leads_schema.py` | Schema repair utility for leads table. |

---

## `core/` -- Pipeline Engine

| File | Purpose |
|------|---------|
| `pipeline.py` | **Scoring engine.** Completeness scoring (% of Tier 2 fields). Confidence scoring (trust - age penalty). Data grade computation (GOLD/SILVER/BRONZE/REJECT). BS Detector (WHALE_CAP, DATE_GLITCH, RATIO_TEST). Batch evaluation of all leads. |

---

## `attorney/` -- Attorney Tools

| File | Purpose |
|------|---------|
| `dossier_docx.py` | Generates Word .docx intelligence dossiers for unlocked leads. |
| `case_packet.py` | Generates HTML case packets for GOLD/SILVER leads. Requires verified attorney status. |

---

## `legal/` -- Legal Document Generation

| File | Purpose |
|------|---------|
| `mail_room.py` | Rule 7.3 compliant solicitation letter generation. Requires verified attorney with firm details. |

---

## `scripts/` -- CLI Utilities

| File | Purpose |
|------|---------|
| `morning_report.py` | **Daily health dashboard.** Shows new leads, scraper health, Vertex budget, top GOLD leads, scoreboard, API health. First command to run every day. |
| `setup_stripe.py` | Stripe product setup helper. Prints instructions or auto-creates products via API. |
| `onboard_attorney.py` | Attorney verification workflow. Validates bar numbers. |
| `forensic_ingest.py` | Manual data ingestion for CORA records and non-standard sources. |
| `promote_jefferson.py` | Jefferson County data promotion script. |
| `dossier_markdown.py` | Markdown dossier generation. |

---

## `config/` -- Configuration

| File | Purpose |
|------|---------|
| `counties.yaml` | **Single source of truth** for all 64 county configurations. Platform, parser, URLs, patterns, tiers. Read by the runner at startup. |

---

## `utils/` -- Shared Utilities

| File | Purpose |
|------|---------|
| `polite_crawler.py` | HTTP client wrapper. Rate limiting (2 req/min), conditional GET, retry with backoff, session management. |
| `stealth.py` | Stealth/anti-detection utilities for scrapers. |

---

## `enrichment/` -- Data Enrichment

| File | Purpose |
|------|---------|
| `entity_resolver.py` | Entity resolution for matching records across sources. |

---

## `contracts/` -- Data Contracts

| File | Purpose |
|------|---------|
| `schemas.py` | Pydantic schemas for data validation and API contracts. |

---

## `ops/` -- Operations

| File | Purpose |
|------|---------|
| `create_superuser.py` | Create an admin/superuser account. |

---

## `deploy/` -- Deployment

| File | Purpose |
|------|---------|
| `Caddyfile` | Caddy reverse proxy config. Routes /api/* to FastAPI, serves React SPA. |
| `verifuse-api.service` | systemd service for the API server. |
| `verifuse-scrapers.service` | systemd service for scraper runs. |
| `verifuse-scrapers.timer` | systemd timer: 2 AM daily with 15-min jitter. |
| `verifuse-healthcheck.service` | Health check service. |
| `verifuse-healthcheck.timer` | Health check timer. |
| `verifuse-orchestrator.service` | Pipeline orchestration service. |
| `verifuse-orchestrator.timer` | Orchestration timer. |
| `verifuse-vertex.service` | Vertex AI processing service. |
| `verifuse-vertex.timer` | Vertex processing timer. |
| `deploy.sh` | Deployment script. |
| `launch.sh` | Launch script. |
| `LAUNCH_CHECKLIST.md` | Pre-launch verification checklist. |

---

## `data/` -- Data Storage (Not in Git)

| Path | Purpose |
|------|---------|
| `data/verifuse_v2.db` | SQLite database (WAL mode) |
| `data/verifuse_v2.db-wal` | WAL file |
| `data/verifuse_v2.db-shm` | Shared memory file |
| `data/raw_pdfs/{county_code}/` | Downloaded PDFs organized by county |
| `data/dossiers/` | Generated dossier documents |

---

## `logs/` -- Log Files

| Path | Purpose |
|------|---------|
| `logs/engine_v2_anomalies.jsonl` | Records that scored below 0.5 threshold |

---

## `docs/` -- Documentation

The directory you are reading now. See [README](../README.md) for the full index.
