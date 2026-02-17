# Architecture V2 — Sprint 11.5 + Hardening PR

## System Overview

VeriFuse is a three-tier application: React SPA frontend, FastAPI backend, and SQLite database. The scraper pipeline runs as a separate process on a systemd timer.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Internet (HTTPS)                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Caddy 2 — TLS termination, reverse proxy, static serving   │
│  Port 443 → localhost:8000 (API)                             │
│  Port 443 → /static (React build)                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
    ┌──────────────────┼──────────────────────┐
    │                  │                      │
┌───▼──────────┐  ┌───▼───────────┐  ┌───────▼──────────┐
│  React SPA   │  │  FastAPI API  │  │  Scraper Runner  │
│  Vite + TS   │  │  api.py       │  │  runner.py       │
│  3 pages:    │  │  30+ routes   │  │  engine_v2.py    │
│  Landing     │  │  JWT auth     │  │  County parsers  │
│  Dashboard   │  │  Rate limiting│  │  Vertex AI OCR   │
│  LeadDetail  │  │  CORS         │  │  Pipeline events │
└──────────────┘  └───┬───────────┘  └───────┬──────────┘
                      │                      │
              ┌───────▼──────────────────────▼───────┐
              │           SQLite (WAL mode)          │
              │  Tables: leads, users, unlocks,      │
              │  pipeline_events, lead_provenance,   │
              │  vertex_usage, vertex_queue           │
              └─────────────────────────────────────┘
```

## Backend (FastAPI)

### API Layer (`verifuse_v2/server/api.py`)

The API serves 30+ routes organized into groups:

| Group | Routes | Auth |
|-------|--------|------|
| Health | `/health` | None |
| Preview | `/api/preview/leads` | None (HMAC-signed keys) |
| Sample Dossier | `/api/dossier/sample/{preview_key}` | None (O(1) lookup, rate-limited) |
| Leads | `/api/leads`, `/api/lead/{id}`, `/api/counties` | None (public listing) |
| Stats | `/api/stats` | None |
| Auth | `/api/auth/register`, `/api/auth/login`, `/api/auth/me` | JWT |
| Email Verification | `/api/auth/send-verification`, `/api/auth/verify-email` | JWT |
| Unlock | `/api/unlock/{id}`, `/api/unlock-restricted/{id}` | JWT + credits |
| Dossier | `/api/dossier/{id}`, `/api/dossier/{id}/docx`, `/api/dossier/{id}/pdf` | JWT |
| Attorney Tools | `/api/letter/{id}`, `/api/case-packet/{id}` | JWT + attorney |
| Billing | `/api/billing/checkout`, `/api/billing/upgrade` | JWT |
| Admin | `/api/admin/*` | API key |

### Preview Endpoint

The preview endpoint returns leads with HMAC-signed `preview_key` values (24 hex chars, id-salted). No PII is exposed — specifically excludes `asset_id`, `case_number`, `owner_name`, `property_address`, and `owner_img`.

HMAC key stability: Uses ONLY `leads.id` + secret. No mutable fields (surplus, grade). Re-grading does not change keys. Eligibility gate: `is_preview_eligible()` — single source of truth used at startup, in `_row_to_safe`, and at request-time in the sample dossier endpoint.

### Sample Dossier

`GET /api/dossier/sample/{preview_key}` returns a non-PII PDF dossier. No auth required. O(1) lookup via `_PREVIEW_LOOKUP` dict (built at startup). Request-time re-check via `is_preview_eligible()` ensures stale entries are rejected. Unified 404 (security oracle — does not reveal which lookup step failed). Rate-limited to 30/minute.

### Admin Simulation

Admins can send `X-Verifuse-Simulate: user` header to strip admin privileges. `_effective_admin(user, request)` replaces `_is_admin(user)` in all gate functions. Frontend only injects the header if `vf_is_admin === "1"` in localStorage.

### Vary Header

Middleware appends `Authorization` and `X-Verifuse-Simulate` to the `Vary` header on all responses, with deduplication to prevent repeated tokens.

### Authentication Flow

1. User registers/logs in → receives JWT token
2. Token stored in `localStorage` as `vf_token`
3. All authenticated requests include `Authorization: Bearer <token>`
4. Email verification: optional but required for unlock operations (403 gate)

### Unlock Gate Logic

| Lead Status | Requirements |
|-------------|-------------|
| RESTRICTED | Verified attorney + OPERATOR/SOVEREIGN tier + email verified |
| ACTIONABLE | Any paid user with credits >= 1 + email verified |
| EXPIRED | Cannot unlock (HTTP 410) |

Credit deduction is atomic via `BEGIN IMMEDIATE` transaction. Re-unlocking returns cached data without deducting.

### Download Headers

All file download endpoints return:
- `Content-Disposition: attachment; filename="..."` — triggers download on mobile
- `Cache-Control: no-store` — prevents sensitive document caching
- `X-Content-Type-Options: nosniff` — prevents MIME type sniffing
- `Access-Control-Expose-Headers: Content-Disposition` — allows JS blob pattern

## Frontend (React + TypeScript + Vite)

### Pages

| Page | Route | Description |
|------|-------|-------------|
| Landing | `/` | Hero stats, value props, pricing, login link |
| Dashboard | `/dashboard` | Lead vault with filters, sort, preview mode |
| LeadDetail | `/lead/:assetId` | Full lead detail, unlock flow, downloads |

### Preview Mode

When `?preview=1` is in the URL and user is not authenticated:
- Calls `/api/preview/leads` instead of `/api/leads`
- Renders `PreviewCard` components (no PII fields)
- Shows "Sign Up to Unlock" CTAs
- Hides stats row
- Shows "Viewing Preview" banner

### Error Boundary

React `ErrorBoundary` class component wraps Dashboard and LeadDetail routes. Catches runtime render errors and displays "SYSTEM ERROR" banner instead of white screen. Includes retry button.

### Download Patterns

**`downloadSecure(path, fallbackFilename)`** — Authenticated downloads:
1. Fetch with auth headers (includes sim header if admin)
2. 401 check → clear localStorage + redirect to /login
3. Read response as blob
4. Extract filename from `Content-Disposition` header
5. Create temporary `<a>` element with `blob:` URL
6. Trigger click + revoke object URL

**`downloadSample(previewKey)`** — Unauthenticated sample PDF:
1. Fetch `/api/dossier/sample/{previewKey}` (no auth)
2. Read response as blob
3. Trigger download as `sample_dossier_{key}.pdf`

### Auth Hardening

- 401 handler in `request()` and `downloadSecure()`: clears `vf_token`, `vf_simulate`, `vf_is_admin` and redirects via `window.location.replace("/login")` (prevents Back-button into cached protected views)
- `authHeaders()`: only injects `X-Verifuse-Simulate` if `vf_is_admin === "1"`
- `logout()`: clears all localStorage keys + redirect
- `handleAuth()`: sets `vf_is_admin` on login, auto-clears `vf_simulate` for non-admins

### Health Monitoring

`useHealth()` hook polls `/health` every 30 seconds. Defaults to `false` (fail closed). Empty `API_BASE` = relative `/health` (production same-origin). Dashboard shows green dot when healthy, red dot when error.

### Email Verification UI

- Dashboard: non-blocking warning banner with code input + resend button
- LeadDetail: unlock buttons disabled when `!user.email_verified`
- Both pages: catch 403 responses containing "verify" + "email" and show verification prompt

## Database

SQLite in WAL mode. Key tables:

| Table | Purpose |
|-------|---------|
| `leads` | All lead data (200+ columns after enrichment) |
| `users` | User accounts with hashed passwords |
| `unlocks` | Track which users unlocked which leads |
| `pipeline_events` | Append-only audit log |
| `lead_provenance` | SHA256 source document hashes |
| `vertex_usage` | Vertex AI API usage tracking |
| `vertex_queue` | Vertex AI processing queue |

## Scraper Pipeline

The pipeline runs via `runner.py` which orchestrates county-specific parsers through `engine_v2.py`. Each scrape run emits `COUNTY_SCRAPE_RESULT` or `COUNTY_SCRAPE_ERROR` pipeline events with stats:
- `parsed_records`: total records parsed
- `leads_inserted`: new leads added
- `rejects`: records that failed validation

## Deployment

Blue/green deployment via symlink swap:

```
~/verifuse_titanium_prod/
├── releases/v11.5.0/     # New release
├── current -> releases/v11.5.0  # Atomic swap
├── data/                  # Persistent (never touched)
└── secrets.env            # JWT + API keys
```

Deploy script: WAL checkpoint → copy code → swap symlink → restart services.
