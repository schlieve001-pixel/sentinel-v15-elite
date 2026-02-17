# Local Development Setup

How to set up a VeriFuse V2 development environment from scratch.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend build |
| npm | 9+ | Frontend package management |
| SQLite 3 | 3.35+ | Database CLI (comes with most OS) |
| Git | 2.x | Version control |

---

## Step 1: Clone the Repository

```bash
git clone <repo-url> continuity_lab
cd continuity_lab
```

The VeriFuse V2 code lives in `verifuse_v2/` within the `continuity_lab` monorepo. The React frontend lives in `verifuse/site/app/`.

---

## Step 2: Python Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate    # Linux/Mac
# .venv\Scripts\activate     # Windows

# Install dependencies
pip install -r verifuse_v2/requirements.txt
```

### Key Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | API server |
| `pydantic` | Data validation |
| `bcrypt` | Password hashing |
| `PyJWT` | JWT tokens |
| `slowapi` | Rate limiting |
| `pdfplumber` | PDF text extraction |
| `requests` + `beautifulsoup4` | Web scraping |
| `PyYAML` | Config parsing |
| `stripe` | Billing integration |
| `python-dateutil` | Calendar month arithmetic |
| `python-docx` | Word document generation |
| `fpdf2` | PDF generation |
| `Pillow` | Image processing |
| `google-cloud-aiplatform` | Vertex AI (optional) |

---

## Step 3: Environment Variables

Create a local env file (do not commit):

```bash
# verifuse_v2/.env.local (not in version control)
export VERIFUSE_DB_PATH=/absolute/path/to/continuity_lab/verifuse_v2/data/verifuse_v2.db
export VERIFUSE_JWT_SECRET=dev-secret-do-not-use-in-production
export VERIFUSE_API_KEY=dev-api-key
```

Source it:

```bash
source verifuse_v2/.env.local
```

For the Stripe integration (optional for local dev):

```bash
export STRIPE_SECRET_KEY=sk_test_...       # Use Stripe test mode key
export STRIPE_WEBHOOK_SECRET=whsec_...
export STRIPE_PRICE_RECON=price_test_...
export STRIPE_PRICE_OPERATOR=price_test_...
export STRIPE_PRICE_SOVEREIGN=price_test_...
```

---

## Step 4: Initialize the Database

```bash
# Create data directory
mkdir -p verifuse_v2/data

# Run migrations
python -m verifuse_v2.db.migrate
python -m verifuse_v2.db.migrate_titanium
python -m verifuse_v2.db.migrate_master
python -m verifuse_v2.db.migrate_sprint11

# Verify tables exist
sqlite3 $VERIFUSE_DB_PATH ".tables"
```

You should see: `leads users lead_unlocks leads_quarantine pipeline_events vertex_usage vertex_queue download_audit lead_provenance`

---

## Step 5: Start the API Server

```bash
source .venv/bin/activate
uvicorn verifuse_v2.server.api:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag enables auto-restart on code changes (development only).

Verify:

```bash
curl http://localhost:8000/health
```

---

## Step 6: Create a Test User

```bash
# Register via API
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "dev@test.com",
    "password": "testpassword123",
    "full_name": "Dev User",
    "tier": "sovereign"
  }'

# Save the token from the response
export TOKEN="eyJ..."

# Promote to admin
python -c "
from verifuse_v2.db.database import upgrade_to_admin
upgrade_to_admin('dev@test.com')
print('Admin created')
"
```

---

## Step 7: Seed Test Data

### Option A: Run Scrapers

```bash
# Discover PDFs from Denver (dry run)
python -m verifuse_v2.scrapers.runner --county denver --dry-run

# Actually download and process
python -m verifuse_v2.scrapers.runner --county denver
python -m verifuse_v2.scrapers.engine_v2 --verbose
```

### Option B: Manual Seed

Place sample PDFs in `verifuse_v2/data/raw_pdfs/denver/` and run Engine V2:

```bash
python -m verifuse_v2.scrapers.engine_v2 --verbose
```

### Option C: Direct SQL Insert

```bash
sqlite3 $VERIFUSE_DB_PATH "
INSERT INTO leads (id, case_number, county, owner_name, property_address,
    surplus_amount, winning_bid, total_debt, confidence_score, data_grade,
    sale_date, claim_deadline, status, updated_at)
VALUES ('test_lead_001', '2025-TEST-001', 'Denver', 'TEST OWNER',
    '123 Test St, Denver, CO 80202', 50000.00, 260000.00, 210000.00,
    0.95, 'GOLD', '2025-06-15', '2025-12-12', 'ENRICHED',
    datetime('now'));
"
```

---

## Step 8: Frontend Setup (Optional)

```bash
cd verifuse/site/app
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` and proxies API calls to `http://localhost:8000`.

To build for production:

```bash
npm run build
# Output: dist/ directory
```

---

## Development Workflow

### Running Tests

```bash
python -m verifuse_v2.server.test_server
```

### Code Changes

1. Edit code
2. API server auto-reloads (if started with `--reload`)
3. Test with `curl` or the React frontend
4. Check logs in terminal

### Common Development Commands

```bash
# Morning report (check system health)
python -m verifuse_v2.scripts.morning_report

# Re-score all leads
python -m verifuse_v2.core.pipeline --evaluate-all

# Run quarantine
python -m verifuse_v2.db.quarantine

# Check scraper status
python -m verifuse_v2.scrapers.runner --status

# Engine V2 dry run
python -m verifuse_v2.scrapers.engine_v2 --dry-run --verbose

# Verify system integrity
python -m verifuse_v2.verify_system
```

### Database Queries

```bash
# Interactive SQLite shell
sqlite3 $VERIFUSE_DB_PATH

# Quick queries
sqlite3 $VERIFUSE_DB_PATH "SELECT COUNT(*) FROM leads;"
sqlite3 $VERIFUSE_DB_PATH "SELECT data_grade, COUNT(*) FROM leads GROUP BY data_grade;"
```

---

## Project Structure

```
continuity_lab/
  verifuse_v2/               # Backend (Python)
    server/                   #   API layer
    scrapers/                 #   Scraper framework
      adapters/               #     Platform adapters
    db/                       #   Database layer
    core/                     #   Pipeline/scoring
    attorney/                 #   Attorney tools
    legal/                    #   Legal document gen
    scripts/                  #   CLI utilities
    config/                   #   counties.yaml
    utils/                    #   Shared utilities
    data/                     #   Database + PDFs (not in git)
    deploy/                   #   systemd + Caddy configs
    docs/                     #   Documentation (you are here)
  verifuse/                   # Frontend
    site/
      app/                    #   React + Vite app
        src/
          components/         #     UI components
          pages/              #     Route pages
          lib/                #     API client, utilities
```

---

## Troubleshooting

### "FATAL: VERIFUSE_DB_PATH not set"

```bash
export VERIFUSE_DB_PATH=/absolute/path/to/verifuse_v2/data/verifuse_v2.db
```

Must be an absolute path.

### "Table leads does not exist"

Run migrations:
```bash
python -m verifuse_v2.db.migrate
python -m verifuse_v2.db.migrate_titanium
python -m verifuse_v2.db.migrate_master
python -m verifuse_v2.db.migrate_sprint11
```

### Import errors

Make sure you are running from the `continuity_lab/` root directory and the virtual environment is activated:

```bash
cd /path/to/continuity_lab
source .venv/bin/activate
```

### Port 8000 already in use

```bash
# Find and kill the process
lsof -i :8000
kill <PID>
```

### Frontend API calls failing

Check that the API is running on port 8000 and the frontend proxy is configured in `vite.config.ts`.
