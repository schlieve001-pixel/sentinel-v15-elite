# Changelog

## [vNEXT Track 2] — 2026-02-22/23

Full implementation of Gates 0–8 on branch `vnext-track2`.

### Gate 0 — Baseline (39/39)
- Verified baseline integrity: 39/39 gauntlet PASS on Phase 0 core
- Branch: `vnext-track2` created from main

### Gate 1 — Security Hardening
- **Stripe downgrade guard**: `subscription_update` webhook now blocked by `TIER_RANK` guard; attempted downgrades logged to `audit_log`
- **Backend BFCache middleware**: `Cache-Control: no-store` on all auth/leads/dossier/assets/evidence routes; health and webhooks explicitly excluded
- **Frontend BFCache fix**: `logout()` clears sessionStorage + navigates with `replace: true`; `pageshow` listener revalidates auth on BFCache restore

### Gate 2 — Evidence + Observability Schema (Migration 004)
- New tables: `county_profiles`, `ingestion_runs`, `html_snapshots`, `evidence_documents`, `extraction_events`, `field_evidence`
- `asset_registry` extended: `processing_status` (CHECK 5 values), `treasurer_transfer_flag`
- Gauntlet: ≥47 PASS

### Gate 3 — GovSoft Playwright Raw Capture Engine
- `govsoft_engine.py`: county-isolated browser contexts, terms-acceptance flow, UpdatePanel timing, CAPTCHA HITL (sentinel file, 20min timeout), doc family classification, filename sanitization
- `ingest_runner.py`: `--single-case` and `--date-window` modes, stale RUNNING cleanup, flock protection
- `county_profiles` seeded for jefferson + arapahoe
- `requirements.txt`: added `playwright>=1.45.0`

### Gate 4 — Dual-Validation Gate (Fail-Closed)
- `govsoft_extract.py`: `parse_html_fields()` extracts overbid/bid/indebtedness from SALE_INFO HTML
- `validate_overbid()`: GOLD+VALIDATED (math match) or BRONZE+NEEDS_REVIEW (mismatch); voucher-blocked promotion when OCR pending
- Processing status machine: PENDING → EXTRACTED → VALIDATED | NEEDS_REVIEW
- Gauntlet: ≥53 PASS (inline math unit tests)

### Gate 5 — Hybrid OCR + Bounding Boxes
- `ocr_processor.py`: pdfplumber (text layer primary) → Document AI (fallback for TIFF scans)
- `field_evidence` rows with normalized bounding boxes, confidence, `ocr_source`
- Graceful degradation: Document AI returns `[]` if not configured (no crash)
- Jefferson County finding: all financial docs are TIFF-scanned image-only; DocAI required for production
- Gauntlet: 55/55 PASS

### Gate 6 — Equity Resolution Engine
- Migration 005: `lien_records` + `equity_resolution` tables
- `equity_resolution_engine.py`: 5-way classification (LIEN_ABSORBED, OWNER_ELIGIBLE, TREASURER_TRANSFERRED, RESOLUTION_PENDING, NEEDS_REVIEW_TREASURER_WINDOW)
- `seed_lien_records()`: parses LIENOR_TAB HTML snapshot
- `_detect_explicit_transfer()`: strict dt/dd pair check — label + non-empty adjacent value required; CERTQH is IRS lien claim NOT transfer evidence
- Runtime proof: J2500358 IRS lien (3000000¢) > gross (2693252¢) → LIEN_ABSORBED, net=0
- Gauntlet: 58/58 PASS

### Gate 7 — Attorney UI + Evidence Access + Automation
- `ClassificationBadge.tsx`: 5-state equity classification badge with color coding
- `LeadDetail.tsx`: equity panel (gross/net cents, classification badge); evidence document list auto-loaded for `approved_attorney`/`admin`; gated message for other users
- `api.ts`: `Lead` interface +4 equity fields; `EvidenceDoc` interface; `getAssetEvidence()`; `downloadEvidenceDoc()`
- `api.py`: `VAULT_ROOT`; `SafeAsset` +4 equity fields; `registry_asset_id` canonical key derivation; equity lookup in `/api/lead/{id}`; `GET /api/assets/{id}/evidence` (attorney-gated); `GET /api/evidence/{id}/download` (secure FileResponse, `commonpath` traversal check)
- `ops/verifuse-scrapers.service` + `.timer`: nightly 72h rolling ingest, flock overlap guard
- Gauntlet: 60/60 PASS

### Gate 8 — Docs + One-Command Ops
- `bin/vf`: one-command ops wrapper (migrate, gauntlet, api-start/stop/restart, logs, scraper-run-single/window, status, backup-db, db-shell, rebuild-frontend, deploy)
- `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md`, `docs/INGESTION.md`, `docs/DB_SCHEMA.md`, `docs/SECURITY.md`, `docs/INCIDENT_RESPONSE.md`
- `CHANGELOG.md`: this file
