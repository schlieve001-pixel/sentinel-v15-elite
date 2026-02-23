# Scraper Operations

## Runner CLI

The scraper runner is the main entry point for all county scraping operations. It reads `verifuse_v2/config/counties.yaml` and instantiates the correct platform adapter for each county.

```bash
# Show county coverage status
python -m verifuse_v2.scrapers.runner --status

# Run all enabled counties
python -m verifuse_v2.scrapers.runner --all

# Run a single county
python -m verifuse_v2.scrapers.runner --county denver

# Dry run (discover PDFs without downloading)
python -m verifuse_v2.scrapers.runner --all --dry-run

# Force-run a disabled county
python -m verifuse_v2.scrapers.runner --county teller --force

# Use alternate config file
python -m verifuse_v2.scrapers.runner --all --config /path/to/counties.yaml
```

### Runner Output

The runner prints a summary after each county:

```
==================================================
Running: Adams (adams via gts)
==================================================
INFO | Discovered 3 PDFs
INFO | Downloaded: adams_a1b2c3d4e5f6.pdf
INFO | HTML records: 12

Result: {
    county: "Adams",
    county_code: "adams",
    platform: "gts",
    pdfs_discovered: 3,
    pdfs_downloaded: 1,
    html_records: 12,
    errors: [],
    timestamp: "2026-02-16T08:00:00+00:00"
}
```

Every run is logged to the `pipeline_events` table as `SCRAPER_SUCCESS` or `SCRAPER_ERROR`.

---

## Automated Scheduling

Scrapers run daily at 2:00 AM via systemd timer with 15-minute jitter:

```bash
# Check timer status
systemctl list-timers | grep verifuse-scrapers

# View last run
journalctl -u verifuse-scrapers.service --since "yesterday"

# Manually trigger
sudo systemctl start verifuse-scrapers.service
```

---

## counties.yaml Format

Location: `verifuse_v2/config/counties.yaml`

This is the **single source of truth** for county configuration. The runner reads this file at startup.

```yaml
counties:
  - name: Denver                          # Display name
    code: denver                          # Internal code (lowercase, underscores)
    platform: county_page                 # Adapter: realforeclose | gts | county_page | govease | manual
    parser: DenverExcessParser            # Parser class name from registry.py
    public_trustee_url: https://...       # County public trustee URL
    base_url: https://...                 # Platform-specific base URL (for realforeclose/gts)
    pdf_patterns:                         # Glob patterns to match PDF links
      - "*excess*funds*"
      - "*surplus*"
      - "*foreclosure*sale*results*"
    scrape_interval_hours: 24             # How often to scrape (informational)
    enabled: true                         # Whether the runner processes this county
    population_tier: large                # large | medium | small | rural
```

### Platform Types

| Platform | Adapter Class | Counties |
|----------|--------------|----------|
| `realforeclose` | `RealForecloseAdapter` | El Paso, Larimer, Mesa, Summit, Eagle |
| `gts` | `GTSSearchAdapter` | Adams, Arapahoe, Boulder, Douglas, Weld, Garfield |
| `county_page` | `CountyPageAdapter` | Denver, Jefferson, Pueblo, Pitkin, Routt, + many others |
| `govease` | `GovEaseAdapter` | Teller, San Miguel (disabled by default) |
| `manual` | N/A | 15 rural counties (CORA request pipeline) |

### Population Tiers

| Tier | Population | Scrape Interval | Counties |
|------|-----------|----------------|----------|
| `large` | >100K | 24-48 hours | Denver, Adams, Arapahoe, Jefferson, El Paso, Douglas, Boulder, Larimer, Weld |
| `medium` | 25-100K | 48-168 hours | Mesa, Pueblo, Garfield, Broomfield, Fremont, La Plata, Montrose |
| `small` | 10-25K | 168 hours | Summit, Eagle, Morgan, Park, Delta, Elbert, Logan, Chaffee, and others |
| `rural` | <10K | 336-720 hours | Alamosa, Archuleta, Clear Creek, Gilpin, and 20+ others |

---

## Adding a New County

Quick version (see [Adding a County](../scrapers/adding-a-county.md) for full guide):

1. Add entry to `verifuse_v2/config/counties.yaml`
2. Set `enabled: false` initially
3. Test with dry run: `python -m verifuse_v2.scrapers.runner --county <code> --force --dry-run`
4. Verify PDF discovery and download
5. Set `enabled: true`

---

## Troubleshooting

### No PDFs Discovered

```bash
# Check the public trustee URL manually
curl -s <public_trustee_url> | grep -i "pdf\|excess\|surplus"

# Run with force and check output
python -m verifuse_v2.scrapers.runner --county <code> --force --dry-run
```

Common causes:
- County redesigned their website (update `public_trustee_url`)
- PDF patterns don't match (update `pdf_patterns`)
- County removed excess fund lists (check manually)

### HTTP Errors

```bash
# Check recent scraper errors
sqlite3 $VERIFUSE_DB_PATH "
    SELECT created_at, reason, new_value
    FROM pipeline_events
    WHERE event_type = 'SCRAPER_ERROR'
    ORDER BY created_at DESC
    LIMIT 10;
"
```

Common HTTP errors:
- **403 Forbidden:** County site is blocking scrapers. Check `PoliteCrawler` rate limiting.
- **404 Not Found:** URL changed. Update `public_trustee_url` in counties.yaml.
- **500 Server Error:** County site is down. Will retry on next schedule.
- **SSL Error:** Certificate issue on county site. May need to set `verify=False` in adapter.

### Duplicate PDFs

The scraper deduplicates by SHA256 content hash. If you see the same data appearing multiple times:

```bash
# Check for duplicate records
sqlite3 $VERIFUSE_DB_PATH "
    SELECT case_number, COUNT(*) as cnt
    FROM leads
    WHERE county = '<county_name>'
    GROUP BY case_number
    HAVING cnt > 1;
"

# Run dedup
python -c "
from verifuse_v2.db.database import deduplicate_assets
result = deduplicate_assets()
print(result)
"
```

### Scraper Hangs

If a scraper appears to hang:

```bash
# Check if PoliteCrawler is rate-limiting (default: 2 requests/minute)
# The crawler sleeps between requests to avoid overloading county sites

# Force-kill and restart
sudo systemctl stop verifuse-scrapers.service
sudo systemctl start verifuse-scrapers.service
```

### Processing Downloaded PDFs

After scrapers download PDFs, they need to be processed by Engine V2:

```bash
# Run Engine V2 to parse all PDFs
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db
python -m verifuse_v2.scrapers.engine_v2

# Dry run with verbose output
python -m verifuse_v2.scrapers.engine_v2 --dry-run --verbose

# Check anomaly log
cat verifuse_v2/logs/engine_v2_anomalies.jsonl | python -m json.tool
```

---

## PoliteCrawler

All HTTP requests go through `verifuse_v2/utils/polite_crawler.py`, which enforces:

- **Rate limiting:** 2 requests per minute per domain (configurable)
- **Conditional GET:** Uses `If-Modified-Since` and `If-None-Match` headers to skip unchanged content (HTTP 304)
- **Retry logic:** Automatic retry with exponential backoff on transient failures
- **Respectful headers:** Identifies as a legitimate crawler, respects `robots.txt`
- **Session management:** Maintains cookies across requests for ASP.NET ViewState forms (GTS)

---

## Monitoring Scraper Health

```bash
# Last 10 scraper events
sqlite3 $VERIFUSE_DB_PATH "
    SELECT event_type, reason, new_value, created_at
    FROM pipeline_events
    WHERE event_type LIKE 'SCRAPER_%'
    ORDER BY created_at DESC
    LIMIT 10;
"

# Success rate by county
sqlite3 $VERIFUSE_DB_PATH "
    SELECT
        REPLACE(asset_id, 'SCRAPER:', '') as county,
        SUM(CASE WHEN event_type='SCRAPER_SUCCESS' THEN 1 ELSE 0 END) as success,
        SUM(CASE WHEN event_type='SCRAPER_ERROR' THEN 1 ELSE 0 END) as errors
    FROM pipeline_events
    WHERE event_type LIKE 'SCRAPER_%'
    GROUP BY county
    ORDER BY errors DESC;
"
```
