# VeriFuse — Colorado Surplus Foreclosure Intelligence

Legal intelligence platform for Colorado attorneys recovering surplus funds from foreclosure sales under C.R.S. § 38-38-111.

VeriFuse monitors 64 Colorado county Public Trustee offices, extracts foreclosure sale financials, and delivers verified, attorney-ready leads through a secure SaaS platform with wallet-based credit unlocking and dynamic pricing.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USERS (Attorneys)                        │
│                   Landing → Preview → Dashboard                 │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
┌────────────────────────────▼────────────────────────────────────┐
│                     Caddy (TLS + Reverse Proxy)                 │
│                     verifuse.tech → localhost:8000               │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
┌────────▼────────┐  ┌──────▼──────┐  ┌─────────▼────────┐
│  React Frontend │  │  FastAPI    │  │  Scraper Runner  │
│  (Vite + TS)    │  │  (api.py)   │  │  (runner.py)     │
│  React 19       │  │  40+ routes │  │  engine_v2.py    │
└─────────────────┘  └──────┬──────┘  └────────┬─────────┘
                             │                   │
                     ┌───────▼───────────────────▼───────┐
                     │      SQLite (WAL + FK + busy)     │
                     │         verifuse_v2.db             │
                     │   wallet, transactions, audit_log  │
                     └───────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- SQLite 3.35+

### Backend Setup

```bash
# Clone and enter project
git clone <repo-url> continuity_lab
cd continuity_lab

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r verifuse_v2/requirements.txt

# Set required environment variables
export VERIFUSE_DB_PATH=$PWD/verifuse_v2/data/verifuse_v2.db
export VERIFUSE_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
export PREVIEW_HMAC_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')

# Run database migrations (safe, idempotent)
python3 verifuse_v2/migrations/run_migrations.py

# Start API server
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd verifuse/site/app
npm ci                   # Install dependencies (clean)
npm run dev              # Development server (port 5173)
npm run build            # Production build → dist/
```

### Run Scrapers

```bash
python3 -m verifuse_v2.scrapers.runner          # Full pipeline run
python3 -m verifuse_v2.scripts.coverage_report  # Coverage summary
python3 -m verifuse_v2.scripts.data_audit       # Data quality audit
```

### Run Tests

```bash
# Full Gauntlet (DB + HTTP tests)
python3 verifuse_v2/tests/smoke_gauntlet.py

# DB-only tests (CI-safe, no running server needed)
python3 verifuse_v2/tests/smoke_gauntlet.py --dry-run

# Legacy smoke test
bash verifuse_v2/scripts/smoke_11_5.sh
```

### Operations Control

```bash
./verifuse_v2/scripts/verifuse-ctl.sh status           # Service + DB status
./verifuse_v2/scripts/verifuse-ctl.sh logs              # API server logs
./verifuse_v2/scripts/verifuse-ctl.sh restart            # Restart API
./verifuse_v2/scripts/verifuse-ctl.sh proofs             # Production proofs
./verifuse_v2/scripts/verifuse-ctl.sh inventory          # Lead inventory report
./verifuse_v2/scripts/verifuse-ctl.sh stripe-reconcile   # Stripe event stats
```

## Project Structure

```
continuity_lab/
├── README.md                         # This file
├── verifuse_v2/                      # Backend (Python / FastAPI)
│   ├── server/
│   │   ├── api.py                    # FastAPI endpoints (40+ routes)
│   │   ├── auth.py                   # JWT authentication + admin
│   │   ├── billing.py                # Stripe subscription + tier config
│   │   ├── dossier_gen.py            # PDF/DOCX dossier generator
│   │   ├── motion_gen.py             # Court motion PDF generator
│   │   └── obfuscator.py             # PII obfuscation (text → PNG)
│   ├── core/
│   │   └── scoring.py                # 3-Score Intelligence Engine
│   ├── scrapers/
│   │   ├── engine_v2.py              # Core parsing engine
│   │   ├── runner.py                 # Pipeline orchestrator
│   │   └── ...                       # County-specific parsers
│   ├── migrations/
│   │   ├── run_migrations.py         # Safe migration runner (file-locked)
│   │   └── 002_omega_hardening.sql   # Omega v4.7 schema
│   ├── data/
│   │   ├── verifuse_v2.db            # Production database (gitignored)
│   │   └── schema_intelligence.sql   # Intelligence schema (review only)
│   ├── tests/
│   │   └── smoke_gauntlet.py         # Gauntlet smoke test suite
│   ├── scripts/
│   │   ├── verifuse-ctl.sh           # Operations control CLI
│   │   ├── coverage_report.py        # Pipeline coverage report
│   │   ├── data_audit.py             # Data quality audit
│   │   └── smoke_11_5.sh             # Legacy smoke test
│   └── docs/
│       ├── STRATEGY_DUAL_TRACK.md    # Business strategy bible
│       ├── OPERATIONS.md             # Operations & deploy guide
│       └── OPERATIONS_AUDIT.md       # System audit results
│
├── verifuse/site/app/                # Frontend (React 19 + TypeScript + Vite)
│   ├── src/
│   │   ├── App.tsx                   # Routes + ErrorBoundary
│   │   ├── App.css                   # Dark theme (WCAG AA)
│   │   ├── pages/
│   │   │   ├── Landing.tsx           # Landing page + pricing
│   │   │   ├── Dashboard.tsx         # Lead vault + preview mode
│   │   │   ├── LeadDetail.tsx        # Asset detail + unlock flow
│   │   │   ├── Login.tsx             # Login form
│   │   │   └── Register.tsx          # Registration form
│   │   ├── components/
│   │   │   ├── PricingTiers.tsx      # Subscription tier cards
│   │   │   ├── ScoreBadge.tsx        # 3-Score Intelligence badges
│   │   │   └── ErrorBoundary.tsx     # React error boundary
│   │   └── lib/
│   │       ├── api.ts                # API client + auth headers
│   │       └── auth.tsx              # JWT auth context
│   └── .env                          # API URL config
│
└── /etc/verifuse/verifuse.env        # Production secrets (mode 600)
```

## Subscription Tiers

| Tier | Price | Credits | Per Credit | Daily Views | Sessions |
|------|-------|---------|------------|-------------|----------|
| Scout | $49/mo | 25 | $1.96 | 100 | 1 |
| Operator | $149/mo | 100 | $1.49 | 500 | 2 |
| Sovereign | $499/mo | 500 | $0.99 | Unlimited | 5 |
| Starter Pack | $19 (one-time) | 10 | $1.90 | — | — |

**Dynamic Pricing**: Lead unlock cost depends on intelligence score:
- Standard (0-69): 1 credit
- Verified (70-84): 2 credits
- Elite (85+): 3 credits

## Financial Engine (Omega v4.7)

### Wallet System
- Dual-credit wallet: `subscription_credits` (monthly) + `purchased_credits` (one-time)
- Spend order: subscription credits first, then purchased
- CHECK constraints prevent negative balances
- Atomic unlock with `BEGIN IMMEDIATE` (SQLite)

### Stripe Integration
- Mode-aware keys: `STRIPE_MODE=test|live` selects key set
- Subscription checkout (recurring) + Starter Pack checkout (one-time)
- Webhook handler with idempotency (stripe_events dedup)
- Invoice validation: customer matching, subscription matching, line-item extraction
- Billing reason branching: `subscription_create/cycle` = credit, `subscription_update` = tier sync only

### Founders Cap
- Race-safe founders pricing (100 slots, BEGIN IMMEDIATE)
- First 100 subscribers get rates locked for 12 months

## 3-Score Intelligence Index

| Score | Range | Purpose |
|-------|-------|---------|
| Opportunity | 0-100 | Value potential (surplus vs median, equity ratio) |
| Confidence | 0-100 | Data quality (grade 40%, raw confidence 30%, freshness 20%, verification 10%) |
| Velocity | 0-100 | Market heat (county unlock counts, last 90 days) |

Freshness decay: `decay = max(0.0, 1.0 - (days_old / 365.0))`

## API Endpoints

### Public (No Auth)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health + DB stats |
| GET | `/api/public-config` | Stripe mode, publishable key, build ID |
| GET | `/api/preview/leads` | Preview leads (no PII) |
| GET | `/api/stats` | Pipeline statistics |
| GET | `/api/counties` | County breakdown |
| GET | `/api/inventory_health` | Lead inventory health |
| GET | `/api/dossier/sample/{key}` | Sample dossier PDF (no auth) |

### Auth Required
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Register (creates wallet + founders check) |
| POST | `/api/auth/login` | Login (ensures wallet exists) |
| GET | `/api/auth/me` | User profile + wallet balances |
| POST | `/api/auth/send-verification` | Send email verification code |
| POST | `/api/auth/verify-email` | Verify email with 6-digit code |
| GET | `/api/leads` | Browse leads (filterable, with `unlocked_by_me`) |
| GET | `/api/lead/{id}` | Lead detail (view-limited per tier) |
| POST | `/api/leads/{id}/unlock` | Unlock lead (wallet deduction) |
| POST | `/api/unlock/{id}` | Unlock (compat route) |
| POST | `/api/unlock-restricted/{id}` | Unlock restricted (attorney gate) |
| GET | `/api/dossier/{id}` | Download dossier (text) |
| GET | `/api/dossier/{id}/docx` | Download dossier (DOCX) |
| GET | `/api/dossier/{id}/pdf` | Download dossier (PDF) |
| GET | `/api/case-packet/{id}` | Case packet (HTML) |
| POST | `/api/letter/{id}` | Generate Rule 7.3 letter |
| POST | `/api/attorney/verify` | Submit attorney verification |

### Billing
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/billing/checkout` | Create subscription checkout |
| POST | `/api/billing/starter` | Create starter pack checkout ($19) |
| POST | `/api/billing/upgrade` | Tier upgrade + credit refill |
| POST | `/api/webhook` | Stripe webhook (idempotent) |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/leads` | All leads (raw data) |
| GET | `/api/admin/users` | All users |
| GET | `/api/admin/quarantine` | Quarantined leads |
| GET | `/api/admin/coverage` | Scraper coverage report |
| POST | `/api/admin/attorney/approve` | Approve attorney verification |

## Data Pipeline

| Engine | Source | Output |
|--------|--------|--------|
| Signal | Denver Public Trustee | Foreclosure signals |
| Outcome | Denver sale results | Sale outcomes |
| Entity | Property records | Owner enrichment |
| Vertex AI | PDF bid sheets | OCR extraction |
| El Paso | Pre-sale PDFs | Indebtedness (verified) |
| Adams | Post-sale PDFs | Full financials (verified) |

## Legal Compliance

- **C.R.S. § 38-38-111**: 180-day claim window enforcement
- **C.R.S. § 38-38-111(2.5)(c)**: 6-month restriction period tracking
- **C.R.S. § 38-13-1302(5)**: Attorney-client exemption for restricted access
- **C.R.S. § 38-13-1304**: 2-year finder fee blackout period

All data sourced exclusively from public records. No skip-tracing, no homeowner contact.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VERIFUSE_DB_PATH` | Yes | Path to SQLite database |
| `VERIFUSE_JWT_SECRET` | Yes | JWT signing secret (64+ chars) |
| `PREVIEW_HMAC_SECRET` | Yes | Preview key HMAC secret |
| `STRIPE_MODE` | No | `test` or `live` (default: test) |
| `STRIPE_TEST_SECRET_KEY` | No | Stripe test secret key |
| `STRIPE_TEST_PUBLISHABLE_KEY` | No | Stripe test publishable key |
| `STRIPE_TEST_WEBHOOK_SECRET` | No | Stripe test webhook secret |
| `STRIPE_TEST_PRICE_SCOUT` | No | Stripe price ID for Scout tier |
| `STRIPE_TEST_PRICE_OPERATOR` | No | Stripe price ID for Operator tier |
| `STRIPE_TEST_PRICE_SOVEREIGN` | No | Stripe price ID for Sovereign tier |
| `STRIPE_TEST_PRICE_STARTER` | No | Stripe price ID for Starter Pack |
| `SMTP_HOST` | No | SMTP server (empty = dev mode logging) |
| `SMTP_PORT` | No | SMTP port (default: 587) |
| `SMTP_USER` | No | SMTP username |
| `SMTP_PASS` | No | SMTP password |
| `SMTP_FROM` | No | From address (default: noreply@verifuse.tech) |
| `FOUNDERS_MAX_SLOTS` | No | Founders pricing cap (default: 100) |
| `VERIFUSE_API_KEY` | No | API key for admin/scraper endpoints |

Production secrets stored in `/etc/verifuse/verifuse.env` (mode 600), loaded via systemd `EnvironmentFile`.

## Production Deployment

### Initial Setup

```bash
# Create secrets file
sudo mkdir -p /etc/verifuse
sudo nano /etc/verifuse/verifuse.env    # Paste env vars
sudo chmod 600 /etc/verifuse/verifuse.env

# Run migrations
python3 verifuse_v2/migrations/run_migrations.py

# Build frontend
cd verifuse/site/app && npm ci && npm run build && cd -

# Start service
sudo systemctl daemon-reload
sudo systemctl enable verifuse-api
sudo systemctl start verifuse-api
```

### Deploy Updates

```bash
git pull origin main
python3 verifuse_v2/migrations/run_migrations.py    # Safe, idempotent
cd verifuse/site/app && npm ci && npm run build && cd -
sudo systemctl restart verifuse-api
```

### Verify Deployment

```bash
./verifuse_v2/scripts/verifuse-ctl.sh proofs          # Quick health check
python3 verifuse_v2/tests/smoke_gauntlet.py            # Full Gauntlet (30 tests)
```

### Rollback

```bash
sudo systemctl stop verifuse-api
cp verifuse_v2/data/backup_omega_final_<ts>.db verifuse_v2/data/verifuse_v2.db
git checkout <last-known-good-sha>
cd verifuse/site/app && npm run build && cd -
sudo systemctl start verifuse-api
```

## Git Workflow

```bash
# Feature development
git checkout main && git pull
git checkout -b feature/my-feature
# ... make changes ...
git add <files>
git commit -m "feat: description"
git push -u origin feature/my-feature
gh pr create --title "feat: description" --body "..."

# Hotfix
git checkout main && git pull
git checkout -b hotfix/description
# ... fix ...
git commit -m "fix: description"
git push -u origin hotfix/description
```

### Branch Naming

| Prefix | Purpose |
|--------|---------|
| `feature/` | New features |
| `hotfix/` | Production fixes |
| `ops-*` | Operations/infrastructure |
| `omega-*` | Major sprints |

## Security

- JWT tokens expire after 24 hours
- Passwords hashed with bcrypt
- HMAC-SHA256 preview keys (stable, id-only salt)
- CORS restricted to configured origins
- Rate limiting via slowapi (per-endpoint)
- Daily unique view limits per tier
- Admin simulation header (`X-Verifuse-Simulate: user`)
- Stripe webhook signature verification
- Event idempotency (stripe_events dedup table)
- Audit log for all financial operations
- SQLite hardening: WAL + FK + busy_timeout on every connection
- No PII in preview/sample dossier endpoints

## License

Proprietary. All rights reserved.
