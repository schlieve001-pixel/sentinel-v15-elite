# VeriFuse Ingestion Guide

## Overview

The ingestion pipeline captures GovSoft public trustee foreclosure data using Playwright, then extracts and validates overbid amounts via pdfplumber and Document AI.

## Required Environment Variables

```bash
# Database
VERIFUSE_DB_PATH=/path/to/verifuse_v2.db

# GovSoft county base URLs (no default — must be configured)
GOVSOFT_JEFFERSON_URL=https://...
GOVSOFT_ARAPAHOE_URL=https://...

# Vault storage root
VAULT_ROOT=/var/lib/verifuse/vault/govsoft

# Playwright display (0=headless, 1=visible for CAPTCHA debugging)
GOVSOFT_HEADLESS=1

# Google Document AI (optional — graceful degradation if absent)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GOOGLE_CLOUD_PROJECT=your-project-id
DOCAI_FORM_PARSER_ID=your-processor-id
DOCAI_LOCATION=us
```

Store these in `/etc/verifuse/verifuse.env` (referenced by systemd `EnvironmentFile`).

## Running Single-Case Ingest

```bash
bin/vf scraper-run-single --county jefferson --case-number J2400300
```

This:
1. Opens Jefferson County GovSoft (from `county_profiles.base_url`)
2. Navigates to case J2400300
3. Saves HTML snapshots for CASE_DETAIL, SALE_INFO, LIENOR_TAB, DOCS_TAB
4. Downloads all evidence documents to vault
5. Upserts lead into `leads` table (available immediately via `/api/leads`)
6. Runs equity resolution

## Running Date-Window Ingest

```bash
# Last 3 days (nightly default)
bin/vf scraper-run-window --county jefferson --days 3

# Explicit date range
bin/vf scraper-run-window --county jefferson --start 01/01/2025 --end 03/31/2025
```

The nightly timer (02:00 daily) runs with `--days 3` automatically.

## county_profiles Setup

Each county must have a row in `county_profiles`:

```sql
INSERT INTO county_profiles (
  county, platform_type, captcha_mode, requires_accept_terms,
  base_url, search_path, detail_path
) VALUES (
  'jefferson', 'govsoft', 'none', 1,
  'https://your-govsoft-url.example', '/SearchDetails.aspx', '/CaseDetails.aspx'
);
```

Or set `GOVSOFT_JEFFERSON_URL` in env and re-run `bin/vf migrate` (seeds placeholder).

## CAPTCHA HITL Procedure

When `captcha_mode='entry'` or `'detail'`, the scraper pauses and writes a sentinel file:

```
[HITL] CAPTCHA at jefferson/J2400300. Solve then delete: /var/lib/verifuse/vault/.paused/jefferson_J2400300
```

1. Set `GOVSOFT_HEADLESS=0` to see the browser
2. Solve the CAPTCHA in the browser window
3. Delete the sentinel file: `rm /var/lib/verifuse/vault/.paused/jefferson_J2400300`
4. Scraper resumes within 5 seconds

**Timeout:** 20 minutes. If sentinel not deleted within 20 minutes, case is marked `CAPTCHA_BLOCKED` in `asset_registry.processing_status` and ingestion continues to the next case.

## Vault Layout

```
/var/lib/verifuse/vault/govsoft/
  jefferson/
    J2400300/
      original/
        J2400300_BID.pdf        ← evidence_documents.file_path
        J2400300_COP.pdf
        J2400300_NED.pdf
        ...
  arapahoe/
    ...
  .paused/                      ← HITL sentinel files (auto-cleaned)
```

Filenames are sanitized for disk safety: `re.sub(r'[^\w.\-]', '_', name)[:120]`.
The original raw filename is stored in `evidence_documents.filename`.

## Ingestion Run Observability

```bash
bin/vf db-shell
sqlite> SELECT run_id, county, status, cases_processed, cases_failed,
               datetime(start_ts, 'unixepoch') as started
        FROM ingestion_runs ORDER BY start_ts DESC LIMIT 10;
```

## Processing Status Flow

```
PENDING           ← raw capture started
  → EXTRACTED     ← HTML fields parsed successfully
    → VALIDATED   ← overbid math confirmed (GOLD)
    → NEEDS_REVIEW ← math mismatch (BRONZE)
  → CAPTCHA_BLOCKED ← HITL timeout (20 min)
```

All transitions are deterministic and stored on `asset_registry.processing_status`.

## OCR Strategy

1. **pdfplumber** (primary): reads text layer from PDF. Confidence = 0.95 for text-layer pages.
2. **Document AI** (fallback): used when pdfplumber returns 0 words (TIFF scans) or confidence < 0.8.
   - Requires `GOOGLE_CLOUD_PROJECT`, `DOCAI_FORM_PARSER_ID`, `GOOGLE_APPLICATION_CREDENTIALS`.
   - If not configured: logs warning, returns empty results (no crash — fail-closed).

**Jefferson County note:** All financial documents (BID, COP, CERTQH, ckreq) are TIFF-scanned image-only PDFs. Document AI is required for field extraction from these documents.
