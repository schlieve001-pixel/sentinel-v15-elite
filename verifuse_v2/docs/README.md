# VeriFuse V2 Documentation

**Colorado Foreclosure Surplus Intelligence Platform**

VeriFuse V2 is a data intelligence platform that identifies, scores, and serves foreclosure surplus fund leads across all 64 Colorado counties. It combines automated scraping of county public trustee websites, deterministic PDF parsing, confidence-based scoring, and a tiered subscription API for attorneys and recovery specialists.

- **Production URL:** https://verifuse.tech
- **API Base:** https://verifuse.tech/api
- **Stack:** FastAPI + React + SQLite (WAL mode) + Caddy reverse proxy

---

## Quick Reference

### Daily Operations

```bash
# Morning health check (FIRST command every day)
python -m verifuse_v2.scripts.morning_report

# Check API health
curl https://verifuse.tech/health

# View scraper status
python -m verifuse_v2.scrapers.runner --status

# Run all scrapers manually
python -m verifuse_v2.scrapers.runner --all

# Re-score all leads
python -m verifuse_v2.core.pipeline --evaluate-all

# Run quarantine (clean ghost leads)
python -m verifuse_v2.db.quarantine
```

### Service Management

```bash
sudo systemctl status verifuse-api
sudo systemctl restart verifuse-api
sudo systemctl list-timers | grep verifuse
journalctl -u verifuse-api --since "1 hour ago"
```

---

## Documentation Index

### Architecture
| Document | Description |
|----------|-------------|
| [System Overview](architecture/overview.md) | Component diagram, tech stack, module map |
| [Data Flow](architecture/data-flow.md) | PDF to Parser to Score to DB to API to UI pipeline |
| [Database Schema](architecture/schema.md) | All tables: leads, users, lead_unlocks, quarantine, etc. |
| [Scoring Engine](architecture/scoring.md) | Confidence Function C formula, grading rules, variance check |

### Operations
| Document | Description |
|----------|-------------|
| [Quick Start](operations/quick-start.md) | Boot the system from scratch |
| [Deploy Guide](operations/deploy-guide.md) | systemd, Caddy, SSL, environment variables |
| [Scraper Operations](operations/scraper-ops.md) | Run scrapers, add counties, troubleshoot |
| [Monitoring](operations/monitoring.md) | Health checks, logs, pipeline_events, morning report |
| [Database Operations](operations/database-ops.md) | Backup, WAL, quarantine, migrations, audit queries |

### API
| Document | Description |
|----------|-------------|
| [API Reference](api/api-reference.md) | All FastAPI endpoints with request/response examples |
| [Authentication](api/authentication.md) | JWT, API keys, attorney verification |
| [Billing](api/billing.md) | Stripe tiers, credits, webhooks |

### Scrapers
| Document | Description |
|----------|-------------|
| [Adding a County](scrapers/adding-a-county.md) | Step-by-step guide to onboard a new county |
| [Platform Guide](scrapers/platform-guide.md) | RealForeclose, GTS, CountyPage, GovEase adapters |
| [Parser Development](scrapers/parser-development.md) | Writing a CountyParser subclass |
| [County Map](scrapers/county-map.md) | All 64 counties: status, platform, URL, tier |

### Business
| Document | Description |
|----------|-------------|
| [Pitch Deck](business/pitch-deck.md) | Architecture, market, moat, revenue model |
| [Unit Economics](business/unit-economics.md) | Tier pricing math, break-even analysis |
| [Compliance](business/compliance.md) | C.R.S. statutes, CORA, ethical scraping |

### Developer Handoff
| Document | Description |
|----------|-------------|
| [Codebase Map](dev-handoff/codebase-map.md) | File-by-file guide to the repository |
| [Local Setup](dev-handoff/local-setup.md) | Dev environment setup instructions |
| [Roadmap](dev-handoff/roadmap.md) | Multi-state expansion, Supabase migration, mobile app |

---

## Key Legal Constraint

All operations are governed by **C.R.S. SS 38-38-111**, which imposes a **six calendar month holding period** after a foreclosure sale during which compensation agreements with former owners are void. VeriFuse enforces this as a hard gate in the API: leads within the restriction window are marked `RESTRICTED` and require verified attorney status plus OPERATOR or SOVEREIGN tier to unlock.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VERIFUSE_DB_PATH` | Yes | Absolute path to SQLite database |
| `VERIFUSE_JWT_SECRET` | Yes (prod) | JWT signing secret |
| `VERIFUSE_API_KEY` | Yes (prod) | API key for admin/scraper endpoints |
| `STRIPE_SECRET_KEY` | For billing | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | Stripe webhook verification secret |
| `STRIPE_PRICE_RECON` | For billing | Stripe price ID for Recon tier |
| `STRIPE_PRICE_OPERATOR` | For billing | Stripe price ID for Operator tier |
| `STRIPE_PRICE_SOVEREIGN` | For billing | Stripe price ID for Sovereign tier |
| `VERIFUSE_BASE_URL` | Optional | Base URL (default: https://verifuse.tech) |
