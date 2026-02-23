# Adding a County

Step-by-step guide to onboard a new Colorado county into the VeriFuse scraper framework.

---

## Prerequisites

Before you begin:
1. Identify the county's Public Trustee website URL
2. Determine which platform the county uses (or if it is a custom county page)
3. Check if the county publishes excess/surplus fund lists as PDF or HTML

---

## Step 1: Research the County

Visit the county's Public Trustee website and determine:

| Question | How to Find |
|----------|------------|
| Does the county post excess/surplus fund lists? | Look for "Excess Funds", "Surplus Funds", "Unclaimed Funds" links |
| What format? PDF, HTML table, or both? | Click links and check |
| Which auction platform? | Check for realforeclose.com, GTS-style search, GovEase, or a static page |
| What URL patterns do the PDFs use? | Right-click PDF links, copy URL, note patterns |
| Population tier? | Check Census data: large (>100K), medium (25-100K), small (10-25K), rural (<10K) |

---

## Step 2: Add YAML Entry

Edit `verifuse_v2/config/counties.yaml`. Add a new entry under the appropriate phase section:

```yaml
  - name: Larimer                          # Display name
    code: larimer                          # Lowercase, underscores for spaces
    platform: realforeclose                # realforeclose | gts | county_page | govease | manual
    parser: GenericExcessFundsParser       # Start with Generic, create custom if needed
    base_url: https://larimer.realforeclose.com  # For realforeclose/gts platforms
    public_trustee_url: https://www.larimer.org/public-trustee  # County website
    pdf_patterns:                          # Glob patterns to match PDF links
      - "*excess*"
      - "*surplus*"
    scrape_interval_hours: 48             # How often to scrape
    enabled: false                        # Start disabled for testing
    population_tier: large                # large | medium | small | rural
```

### Platform Selection Guide

| County Website Type | Platform Value | Adapter |
|--------------------|---------------|---------|
| Uses `{county}.realforeclose.com` | `realforeclose` | `RealForecloseAdapter` |
| Uses GTS/ASP.NET foreclosure search | `gts` | `GTSSearchAdapter` |
| Static county page with PDF links | `county_page` | `CountyPageAdapter` |
| Uses GovEase auction platform | `govease` | `GovEaseAdapter` |
| No web presence / CORA request only | `manual` | None (manual ingestion) |

### PDF Pattern Tips

Patterns are case-insensitive glob patterns matched against PDF link URLs and anchor text:

```yaml
pdf_patterns:
  - "*excess*funds*"        # Matches "Excess_Funds_2025.pdf"
  - "*surplus*"             # Matches "surplus-report.pdf"
  - "*overbid*"             # Matches "overbid_amounts.pdf"
  - "*foreclosure*sale*"    # Matches "foreclosure_sale_results.pdf"
  - "*POST*SALE*"           # Matches "POST_SALE_LIST.pdf"
```

---

## Step 3: Test Discovery (Dry Run)

Test that the scraper can find PDFs on the county website:

```bash
export VERIFUSE_DB_PATH=/home/schlieve001/origin/continuity_lab/verifuse_v2/data/verifuse_v2.db

# Force-run the disabled county in dry-run mode
python -m verifuse_v2.scrapers.runner --county <code> --force --dry-run
```

Expected output:
```
==================================================
Running: Larimer (larimer via realforeclose)
==================================================
INFO | Discovered 3 PDFs
[DRY RUN] Larimer: 3 PDFs discovered
```

If 0 PDFs discovered:
- Check the `public_trustee_url` is correct
- Check `pdf_patterns` match the actual PDF links
- Try visiting the URL manually and inspecting link text
- Check if the adapter handles the site's HTML structure

---

## Step 4: Test Download

Run without `--dry-run` to download the PDFs:

```bash
python -m verifuse_v2.scrapers.runner --county <code> --force
```

Check that PDFs were saved:

```bash
ls -la verifuse_v2/data/raw_pdfs/<code>/
```

Each PDF is named `{county_code}_{sha256[:12]}.pdf` and deduplicated by content hash.

---

## Step 5: Test Parsing

Run Engine V2 to parse the downloaded PDFs:

```bash
python -m verifuse_v2.scrapers.engine_v2 --verbose
```

Look for your county's PDFs in the output:

```
  [GenericExcessFundsParser] larimer/larimer_a1b2c3d4e5f6.pdf: 5 records
    ENRICHED: case=2025-001234 bid=$285,000.00 debt=$210,000.00 surplus=$75,000.00 conf=0.95 grade=GOLD
```

If the Generic parser does not extract records correctly, you may need to write a custom parser (see [Parser Development](parser-development.md)).

---

## Step 6: Verify in Database

```bash
sqlite3 $VERIFUSE_DB_PATH "
    SELECT id, case_number, surplus_amount, confidence_score, data_grade
    FROM leads
    WHERE county = '<County Name>'
    ORDER BY surplus_amount DESC;
"
```

---

## Step 7: Enable the County

Edit `counties.yaml` and set `enabled: true`:

```yaml
  - name: Larimer
    code: larimer
    ...
    enabled: true    # <-- Enable
```

The county will now be included in the daily 2 AM scraper run.

---

## Step 8: Verify in Runner Status

```bash
python -m verifuse_v2.scrapers.runner --status
```

The county should appear with `YES` in the Enabled column.

---

## Custom Parser (If Needed)

If the county's PDF format is not handled by `GenericExcessFundsParser`, create a custom parser:

1. Add a new class in `verifuse_v2/scrapers/registry.py`
2. Implement `detect()`, `extract()`, and optionally override `score()`
3. Add the parser to `PARSER_REGISTRY` (before `GenericExcessFundsParser`)
4. Update the county's `parser` field in `counties.yaml`

See [Parser Development](parser-development.md) for the full guide.

---

## Checklist

- [ ] County Public Trustee URL confirmed
- [ ] Platform type identified
- [ ] YAML entry added with `enabled: false`
- [ ] Dry run: PDFs discovered
- [ ] Download: PDFs saved to `raw_pdfs/<code>/`
- [ ] Engine V2: records extracted and scored
- [ ] Database: leads present with correct county name
- [ ] Confidence scores reasonable (> 0.5 for most records)
- [ ] `enabled: true` set in counties.yaml
- [ ] Appears in `--status` output
