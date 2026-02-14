# VeriFuse Surplus Engine — Master System Cartography

**Date:** 2026-02-07
**Mode:** Systems Architect + Data Cartographer + Reliability Engineer
**Constraint:** No modifications to verifuse.tech or existing subdomains. Isolated build.

---

## SECTION 1: SYSTEM INVENTORY

### 1.1 ACTIVE Components (Currently Running or Runnable)

| # | Component | Path | Purpose (Actual) | Inputs | Outputs | Authority | Status |
|---|-----------|------|-------------------|--------|---------|-----------|--------|
| 1 | schema.py | verifuse/core/schema.py | Canonical DDL, enums, statute seeding | None | SQLite schema, statute_authority rows | AUTHORITATIVE | ACTIVE |
| 2 | pipeline.py | verifuse/core/pipeline.py | State machine, scoring, ingestion, evaluation | assets table, statute_authority, scraper_registry | legal_status transitions, pipeline_events, score updates | AUTHORITATIVE | ACTIVE |
| 3 | registry.py | verifuse/scrapers/registry.py | 12 scraper coverage declarations, gap matrix | None (static declarations) | scraper_registry rows | AUTHORITATIVE | ACTIVE |
| 4 | ui_spec.py | verifuse/attorney/ui_spec.py | Attorney dashboard column contract, query logic | attorney_view (SQL VIEW) | Filtered dicts for rendering | AUTHORITATIVE | ACTIVE |
| 5 | case_packet.py | verifuse/attorney/case_packet.py | PDF case packet generator (7 sections) | assets + statute_authority + legal_status | HTML for WeasyPrint PDF | AUTHORITATIVE | ACTIVE |
| 6 | migrate_from_legacy.py | verifuse/migrations/migrate_from_legacy.py | Legacy vault.db migration | _ARCHIVE/data/verifuse_vault.db | verifuse/data/verifuse.db | ONE-TIME | ACTIVE |
| 7 | verifuse.db | verifuse/data/verifuse.db | Canonical database (679 assets, 1441 events) | pipeline.py writes | All reads | AUTHORITATIVE | ACTIVE |
| 8 | fusion_engine.py | _ARCHIVE/fusion_engine.py | Legacy CSV/PDF ingestion to SQLite | data/input_files/*.csv | data/verifuse_vault.db | SUPERSEDED by pipeline.py | ACTIVE (legacy) |
| 9 | airtable_sync.py | _ARCHIVE/airtable_sync.py | Legacy Airtable CRUD sync | verifuse_vault.db | Airtable API (ASSETS table) | DERIVATIVE | ACTIVE (legacy) |
| 10 | fetch_master.py | _ARCHIVE/fetch_master.py | Playwright scraper: Mesa + Jefferson | realforeclose.com, Jefferson site | data/input_files/*.csv | SOURCE | ACTIVE |
| 11 | verifuse_server_safe.py | _ARCHIVE/verifuse_server_safe.py | CO Treasury unclaimed property search | colorado.findyourunclaimedproperty.com | SERVER_SAFE_HITS.csv | SOURCE | ACTIVE |
| 12 | verifuse_treasury_sniper.py | _ARCHIVE/verifuse_treasury_sniper.py | Targeted CO Treasury search by city | colorado.findyourunclaimedproperty.com | COLORADO_STATE_TREASURY_HITS.csv | SOURCE | ACTIVE |
| 13 | verifuse_vault.db | _ARCHIVE/data/verifuse_vault.db | Legacy database (32 leads, 653 pipeline) | fusion_engine.py | airtable_sync.py, migration | SUPERSEDED | ACTIVE (legacy) |
| 14 | input_files/ | _ARCHIVE/data/input_files/ | 16 raw CSV files from scrapers | Scrapers | fusion_engine.py | SOURCE | ACTIVE |

### 1.2 GHOST Components (Code Exists, Not in Production Use)

| # | Component | Path | Purpose | Why Ghost |
|---|-----------|------|---------|-----------|
| 15 | hunter.py | _ARCHIVE/surplus_engine_pbc/hunter.py | PBC Selenium scraper | Outputs not persisted |
| 16 | hunter_elite.py | _ARCHIVE/surplus_engine_pbc/hunter_elite.py | CO Treasury search | Prototype only |
| 17 | hunter_selenium.py | _ARCHIVE/surplus_engine_pbc/hunter_selenium.py | PBC variant | Duplicate of #15 |
| 18 | hunter_time_machine.py | _ARCHIVE/surplus_engine_pbc/hunter_time_machine.py | JS date forcing | Specialized variant |
| 19 | hunter_rewind.py | _ARCHIVE/surplus_engine_pbc/hunter_rewind.py | Previous button nav | Specialized variant |
| 20 | hunter_god_mode.py | _ARCHIVE/surplus_engine_pbc/hunter_god_mode.py | 45-day full scan | undetected_chromedriver |
| 21 | hunter_full_auto.py | _ARCHIVE/surplus_engine_pbc/hunter_full_auto.py | Full auto variant | Similar to #20 |
| 22 | verifuse_elite_search.py | _ARCHIVE/verifuse_elite_search.py | Treasury XPath search | Prototype |
| 23 | verifuse_debug.py | _ARCHIVE/verifuse_debug.py | Debug variant | Debug only |
| 24 | verifuse_final.py | _ARCHIVE/verifuse_final.py | ENTER key variant | Superseded |
| 25 | verifuse_time_traveler.py | _ARCHIVE/verifuse_time_traveler.py | 2018-2026 deep search | Incomplete |
| 26 | verifuse_auto_parties.py | _ARCHIVE/surplus_engine_pbc/verifuse_auto_parties.py | Lien/party risk audit | Incomplete |
| 27 | verifuse_parties_v2.py | _ARCHIVE/surplus_engine_pbc/verifuse_parties_v2.py | Party risk v2 | Incomplete |

### 1.3 DEAD Components (Unreachable or Unrelated)

| # | Component | Path | Why Dead |
|---|-----------|------|----------|
| 28 | inspector.py | _ARCHIVE/surplus_engine_pbc/inspector.py | Pure debug, no output |
| 29 | verifuse_parties.py | _ARCHIVE/surplus_engine_pbc/verifuse_parties.py | Placeholder (pass only) |
| 30 | fetch_squad.py | _ARCHIVE/fetch_squad.py | Stock prices (yfinance), wrong domain |
| 31 | fetch_wallstreet.py | _ARCHIVE/fetch_wallstreet.py | BTC prices, wrong domain |
| 32 | fetch_all_prices.py | _ARCHIVE/fetch_all_prices.py | Multi-ticker, wrong domain |
| 33 | forensic_fetcher.py | _ARCHIVE/forensic_fetcher.py | BTC 1-min, wrong domain |

### 1.4 SEPARATE SYSTEM (Not Part of Surplus Engine)

The `renaissance_lab/` directory is an **entirely separate trading physics system** (SENTINEL). It has:
- 11 Python files (dashboards, market data pump, HMM brain, tape recorder)
- Zero imports from verifuse package
- Zero references to surplus/legal/county data
- Shares only the verifuse.tech domain infrastructure (Caddyfile)

**Verdict:** renaissance_lab has NO connection to the surplus engine. It is architecturally isolated.

### 1.5 DATA STORES

| Store | Path | Type | Rows | Writer(s) | Reader(s) | Authoritative? | Stale? |
|-------|------|------|------|-----------|-----------|----------------|--------|
| verifuse.db | verifuse/data/ | SQLite | 679 assets | pipeline.py | ui_spec.py, case_packet.py | YES | No |
| verifuse_vault.db | _ARCHIVE/data/ | SQLite | 685 total | fusion_engine.py | airtable_sync.py, migration | SUPERSEDED | Yes (Jan 27) |
| Airtable ASSETS | Cloud | Airtable API | ~699 | airtable_sync.py | Attorneys (legacy) | DERIVATIVE | Yes |
| input_files/*.csv | _ARCHIVE/data/ | CSV | 16 files | fetch_master.py, manual | fusion_engine.py | SOURCE | Yes (Jan 27) |
| MASTER_LEADS.csv | _ARCHIVE/surplus_engine_pbc/ | CSV | 84 rows | hunter scripts | Manual review | DERIVATIVE | Yes (Jan 20) |
| VERIFIED_PARTIES.csv | _ARCHIVE/surplus_engine_pbc/ | CSV | 84 rows | verifuse_auto_parties.py | Manual review | DERIVATIVE | Yes (Jan 20) |

---

## SECTION 2: CANONICAL DATA FLOW

```
EXTERNAL SOURCES
 │
 ├─ County Clerk/Recorder Sites ──────────┐
 │   Denver, Jefferson, Arapahoe           │
 │                                         │
 ├─ RealForeclose.com ────────────────────┤
 │   Mesa, Palm Beach                      │
 │                                         │
 ├─ GovEase Platform ─────────────────────┤
 │   Teller, Summit, San Miguel            │
 │                                         │
 ├─ County Portal Sites ──────────────────┤
 │   Eagle, San Miguel                     │
 │                                         │
 ├─ CO Treasury Unclaimed Property ───────┤
 │   colorado.findyourunclaimedproperty.com│
 │                                         │
 └─ Manual PDF/CSV Upload ────────────────┘
                    │
                    ▼
            ┌───────────────┐
            │   SCRAPERS    │  12 registered (verifuse/scrapers/registry.py)
            │               │  Produce: raw dicts with county, case, owner, surplus, etc.
            │  TRANSFORMS:  │  clean_money(), normalize_address(), parse_date()
            │  DATA LOSS:   │  Douglas: month-only dates → assume 1st
            │               │  Mesa/PBC: missing owner → blocked from ATTORNEY
            │  FAILURE:     │  Site changed → scraper returns 0 records
            │               │  Rate limited → partial results
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │  NORMALIZER   │  ingest_asset() in pipeline.py
            │               │  Generates: asset_id = {county}_{type}_{hash8}
            │  TRANSFORMS:  │  Dedup by record_hash (SHA-256)
            │               │  COALESCE update (never overwrites with NULL)
            │  DATA LOSS:   │  None (additive only)
            │  FAILURE:     │  Duplicate hash → skip (no-op)
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │  VALIDATOR    │  evaluate_asset() in pipeline.py
            │               │  Computes: completeness, confidence, risk, grade, days_remaining
            │  TRANSFORMS:  │  Tier 2 fields derived: statute_window, days_remaining
            │               │  Scores written to assets table (INTERNAL ONLY)
            │  DATA LOSS:   │  None
            │  FAILURE:     │  Unparseable sale_date → days_remaining=NULL → cannot_verify kill
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │    GATES      │  Gate conditions checked in evaluate_asset()
            │               │
            │  KILL SWITCHES:│
            │   days ≤ 0    │→ CLOSED (statute_expired)
            │   conf < 0.3  │→ CLOSED (data_grade_reject)
            │   no statute  │→ CLOSED (no_statute_authority)
            │               │
            │  PROMOTIONS:  │
            │   T1 + T2≥50% │→ PIPELINE → QUALIFIED
            │   T2=100%     │→ QUALIFIED → ATTORNEY
            │   + GOLD/SILVER│
            │   + days > 0  │
            │   + statute   │
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │ STATE TRANS.  │  _transition() in pipeline.py
            │               │  ALL transitions logged to pipeline_events
            │               │  Actor, reason, metadata, timestamp recorded
            │               │  CLOSED is terminal (no reverse)
            │  DATA LOSS:   │  None (append-only log)
            │  FAILURE:     │  SQLite write failure → exception (no silent fail)
            └───────┬───────┘
                    │
                    ▼
            ┌───────────────┐
            │ DERIVED VIEWS │  attorney_view (SQL VIEW)
            │               │  Filters: record_class=ATTORNEY, days>0, grade∈{GOLD,SILVER}
            │               │  Excludes: ALL Tier 4 fields (scores, grades)
            │               │  Sorted: days_remaining ASC (urgency first)
            │  DATA LOSS:   │  Intentional: scores, internal fields stripped
            │  FAILURE:     │  View query returns 0 rows → empty dashboard
            └───────────────┘
```

---

## SECTION 3: MAPS LAYER SPECIFICATION

### Map A: Data Origin Map

| Field | Origin Source | Jurisdiction | Update Cadence | Legal Trust | Blocking? | Degradation |
|-------|-------------|-------------|----------------|-------------|-----------|-------------|
| asset_id | Generated (hash) | All | On ingest | N/A | YES (Tier 1) | Cannot exist without |
| county | Scraper filename/data | All | On ingest | HIGH | YES (Tier 1) | Cannot exist without |
| jurisdiction | Derived: county+state | All | On ingest | HIGH | YES (Tier 1) | Cannot exist without |
| case_number | County records | All except Douglas foreclosure | 7-14 days | HIGH | YES (Tier 1) | Douglas blocked |
| asset_type | Scraper registration | All | Static | HIGH | YES (Tier 1) | Cannot exist without |
| statute_window | Computed: statute_authority table | All with statute entry | On evaluation | HIGH (statute text) | YES (Tier 2) | Missing → cannot_verify kill |
| days_remaining | Computed: sale_date + statute_years | All with sale_date | On evaluation | Depends on sale_date | YES (Tier 2) | NULL → cannot_verify kill |
| owner_of_record | County records | All except Mesa, PBC | 7-14 days | HIGH (CO), HIGH (FL) | YES (Tier 2) | Missing → blocked from ATTORNEY |
| lien_type | NONE (defaulted) | All | N/A | LOW (inferred) | YES (Tier 2) | Default: Deed of Trust/Tax Lien |
| sale_date | County records | All except Denver tax, Douglas foreclosure | 7-14 days | HIGH (varies) | YES (Tier 2) | Missing → cannot compute days |
| recorder_link | Generated search URL | Denver, Jefferson, Arapahoe | On ingest | MED (search, not direct) | YES (Tier 2) | Missing for 9/12 scrapers |
| estimated_surplus | bid-judgment or official posting | Denver, Jefferson, Arapahoe, Douglas, Mesa, Teller, PBC | 7 days | HIGH | NO (Tier 3) | Missing for Eagle, Summit, San Miguel |
| total_indebtedness | County records | Jefferson, Eagle, Teller, Summit, San Miguel, PBC | 7 days | HIGH | NO (Tier 3) | Missing for Denver, Douglas, Mesa |
| overbid_amount | Auction records | Denver, Jefferson, Arapahoe, PBC | 7 days | HIGH | NO (Tier 3) | Missing for 8/12 scrapers |
| completeness_score | Computed | All | On evaluation | N/A (internal) | NO (Tier 4) | N/A |
| confidence_score | Computed | All | On evaluation | N/A (internal) | NO (Tier 4) | N/A |
| risk_score | Computed | All | On evaluation | N/A (internal) | NO (Tier 4) | N/A |

### Map B: Pipeline Flow Map (Directed Graph)

```
[SCRAPER_OUTPUT] ──(ingest_asset)──→ [PIPELINE]
                                        │
                    ┌───────────────────┤
                    │                   │
            (Tier1 + partial T2)  (kill_switch)
                    │                   │
                    ▼                   ▼
              [QUALIFIED]          [CLOSED:reject]
                    │
        ┌───────────┤
        │           │
  (full T2 +     (kill_switch
   GOLD/SILVER     or stale)
   + days > 0)      │
        │           ▼
        ▼      [CLOSED:kill]
   [ATTORNEY]
        │
   (expiry or
    action)
        │
        ▼
   [CLOSED:resolved]

LOSSY STEPS:
  1. Scraper → Normalizer: Douglas date precision lost (month → day-1 assumed)
  2. Normalizer → Validator: lien_type inferred (not scraped)
  3. Validator → Attorney View: Tier 4 fields intentionally stripped

EXPLICIT FAILURE STATES:
  - CLOSED:statute_expired (days ≤ 0)
  - CLOSED:data_grade_reject (confidence < 0.3)
  - CLOSED:no_statute_authority (unknown jurisdiction)
  - CLOSED:cannot_verify (unparseable sale_date)
  - EVALUATION_ERROR (logged, asset stays in current class)
```

### Map C: Coverage Heat Map

```
COUNTY × FIELD COVERAGE MATRIX
─────────────────────────────────────────────────────────────────────────────
County         case# owner sale_dt lien  surplus  debt  overbid recorder TOTAL
─────────────────────────────────────────────────────────────────────────────
Denver FC      ███   ███   ███     ░░░   ███      ░░░   ███     ██░      6/8
Denver TX      ███   ███   ░░░     ░░░   ███      ░░░   ░░░     ░░░      3/8
Jefferson      ███   ███   ███     ░░░   ███      ███   ███     ██░      7/8
Arapahoe       ███   ███   ██░     ░░░   ███      ░░░   ███     ███      6/8
Douglas FC     ░░░   ███   ██░     ░░░   ███      ░░░   ░░░     ░░░      3/8
Douglas TX     ███   ███   ███     ░░░   ███      ░░░   ░░░     ░░░      4/8
Mesa           ███   ░░░   ███     ░░░   ███      ░░░   ░░░     ░░░      3/8
Eagle          ███   ███   ███     ░░░   ░░░      ███   ░░░     ░░░      4/8
Teller         ███   ███   ███     ░░░   ███      ███   ░░░     ░░░      5/8
Summit         ███   ███   ███     ░░░   ░░░      ███   ░░░     ░░░      4/8
San Miguel     ███   ███   ███     ░░░   ░░░      ███   ░░░     ░░░      4/8
Palm Beach     ███   ░░░   ███     ░░░   ███      ███   ███     ░░░      5/8
─────────────────────────────────────────────────────────────────────────────
KEY: ███ = present   ██░ = partial   ░░░ = missing

CAN REACH ATTORNEY CLASS:
  Jefferson ✓, Arapahoe ✓ (with recorder), Teller ✓ (needs recorder)
  Douglas TX ✓ (needs recorder)
  ALL OTHERS: BLOCKED (missing owner, surplus, or recorder)

BLIND SPOTS:
  1. lien_type: BLIND everywhere (0/12 scrapers provide it)
  2. recorder_link: 9/12 scrapers have NO recorder link
  3. redemption_date: BLIND everywhere (0/12 scrapers)
  4. fee_cap: BLIND everywhere (not scraped; only in statute_authority)
```

### Map D: Confidence Degradation Map

| Degradation Point | Where | Why | Recoverable? | Consequence |
|-------------------|-------|-----|-------------|-------------|
| Douglas date precision | Scraper | Month-only format (Mon-YY) | YES: County records office has exact dates | Statute window could be off by up to 30 days. Worst case assumed. |
| lien_type inference | Normalizer | No scraper provides lien_type | YES: Manual review of case filing | Default used. Known degradation. |
| recorder_link as search URL | Migration | Not a direct document link | PARTIAL: Could be upgraded to direct link with case-specific scraping | Attorney understands difference. |
| Stale source data | Scraper | last_run > 2x update_frequency | YES: Re-run scraper | If detected, asset should be demoted. Currently NOT auto-detected (gap). |
| Portal debt-only records | Eagle/Summit/San Miguel scrapers | Portal shows debt, not surplus | NO: Surplus only exists after sale | Permanently blocked from ATTORNEY class until post-sale data available. |
| Missing owner (Mesa/PBC) | Scraper | Source site doesn't publish owner | YES: Cross-reference with county clerk | Must be manually supplied or supplemental scraper built. |
| data_age_days = 0 | pipeline.py:239 | TODO placeholder | YES: Compute from source file modification time | Currently confidence never penalized for age. BUG. |

### Map E: Jurisdiction Fracture Map

| Jurisdiction | Statute | Known Fractures | Safe to Automate? | Notes |
|-------------|---------|-----------------|-------------------|-------|
| Denver, CO | C.R.S. 38-38-111 (5yr FC), C.R.S. 39-11-151 (3yr tax) | None identified | YES | Best data quality |
| Jefferson, CO | C.R.S. 38-38-111 (5yr) | None identified | YES | Good data, need recorder direct links |
| Arapahoe, CO | C.R.S. 38-38-111 (5yr) | sale_date sometimes missing | YES with caveat | Partial sale_date coverage |
| Douglas, CO | C.R.S. 38-38-111 (5yr), C.R.S. 39-11-151 (3yr) | Month-only dates, case_number missing for FC | PARTIAL | Treasurer format unpredictable |
| Mesa, CO | C.R.S. 38-38-111 (5yr) | Missing owner | PARTIAL | Blocked until owner resolved |
| Eagle, CO | C.R.S. 38-38-111 (5yr) | No surplus data (debt-only portal) | NO for ATTORNEY | Pipeline only until post-sale |
| Teller, CO | C.R.S. 38-38-111 (5yr) | GovEase intermediary (not direct county) | YES with MED confidence | Third-party data source |
| Summit, CO | C.R.S. 38-38-111 (5yr) | No surplus data, GovEase intermediary | NO for ATTORNEY | Pipeline only |
| San Miguel, CO | C.R.S. 38-38-111 (5yr) | No surplus data, portal data | NO for ATTORNEY | Pipeline only |
| Palm Beach, FL | Fla. Stat. 45.032 (1yr) | 1-year window is critically short, missing owner | PARTIAL | FL statute is 80% shorter than CO |
| Adams, CO | C.R.S. 38-38-111 (5yr) | No scraper exists | NO | Statute entry exists, no data source |

**Counties Requiring Manual Review:**
- Douglas (all FC records): Date ambiguity
- Palm Beach: 1-year window means near-zero margin for error

**Counties Unsafe to Fully Automate:**
- Eagle, Summit, San Miguel: No surplus figure → cannot determine attorney value
- Mesa: No owner → cannot file claim

---

## SECTION 4: DATA ACQUISITION EXPANSION PLAN

### Critical Missing Fields

| Missing Field | Public? | Scrapeable? | Legal? | Viable? | Action |
|--------------|---------|------------|--------|---------|--------|
| **lien_type** | YES (case filing) | PARTIAL (requires case-specific lookup) | YES | LOW ROI (can be inferred from sale_type) | DEFAULT with documented degradation. Manual override when available. |
| **recorder_link (direct)** | YES | YES (county recorder sites) | YES | MED (each county has different site) | ADD: Build per-county recorder URL generator using case_number. Priority: Denver, Jefferson, Arapahoe. |
| **owner_of_record (Mesa)** | YES (county assessor) | YES | YES | HIGH | ADD: Build Mesa County assessor scraper using parcel number. |
| **owner_of_record (PBC)** | YES (FL clerk of court) | YES | YES | HIGH | ADD: Build Palm Beach clerk scraper using case number. |
| **estimated_surplus (Eagle/Summit/San Miguel)** | CONDITIONAL (post-sale only) | YES (after auction completes) | YES | MED (timing-dependent) | GATE: Monitor for post-sale surplus postings. Do not estimate. |
| **redemption_date** | YES (case filing) | PARTIAL | YES | LOW (rarely needed for CO surplus) | PERMANENTLY ABANDON for CO. ADD for FL (FL has right of redemption). |
| **fee_cap** | YES (statute text) | NO (requires legal interpretation) | YES | LOW (static per jurisdiction) | GATE: Human review. Already in statute_authority table. |
| **Adams County data** | YES | YES (county site) | YES | MED | ADD: Build Adams County scraper. Statute entry already exists. |
| **data_age_days computation** | N/A (internal) | N/A | N/A | HIGH (simple fix) | ADD: Compute from source_file modification time in evaluate_asset(). |

### Acquisition Priority

1. **FIX NOW:** data_age_days computation (pipeline.py bug)
2. **HIGH PRIORITY:** Mesa owner scraper, PBC owner scraper, recorder link generator
3. **MEDIUM:** Adams County scraper, post-sale surplus monitoring for Eagle/Summit/San Miguel
4. **LOW:** Direct recorder links (vs search URLs), lien_type from case filings
5. **ABANDON:** redemption_date for CO (not material), fee_cap scraping (manual is fine)

---

## SECTION 5: MAINTENANCE & WATCHDOG PROTOCOL

### System Integrity Watchdog

```python
# Conceptual — to be implemented as verifuse/core/watchdog.py

WATCHDOG_CHECKS = {
    # DAILY
    "scraper_freshness": {
        "check": "last_run_at < NOW - (2 * update_frequency_days)",
        "threshold": "any scraper exceeds 2x cadence",
        "auto_action": "downgrade all assets from that scraper to QUALIFIED",
        "escalation": "log MANUAL_REVIEW event + alert ops",
    },
    "null_rate_inflation": {
        "check": "% of NULL Tier 2 fields increased > 5% since last check",
        "threshold": "any Tier 2 field",
        "auto_action": "pause scraper, log KILL_SWITCH event",
        "escalation": "alert ops: 'scraper {name} producing degraded data'",
    },
    "statute_expiry_sweep": {
        "check": "any ATTORNEY asset has days_remaining <= 0",
        "threshold": "any asset",
        "auto_action": "transition to CLOSED (statute_expired)",
        "escalation": "none (fully automated)",
    },
    "attorney_view_integrity": {
        "check": "SELECT * FROM attorney_view WHERE completeness_score < 1.0",
        "threshold": "any row",
        "auto_action": "IMPOSSIBLE by SQL VIEW construction (sanity check)",
        "escalation": "CRITICAL: schema corruption detected",
    },

    # WEEKLY
    "event_log_growth": {
        "check": "pipeline_events row count delta",
        "threshold": "< 10 events in 7 days = system stagnant",
        "auto_action": "none",
        "escalation": "ops review: scrapers may be broken or no new data",
    },
    "class_distribution_drift": {
        "check": "% of assets in each class vs previous week",
        "threshold": "> 20% shift in any class",
        "auto_action": "none",
        "escalation": "ops review: bulk promotion or kill may indicate bug",
    },

    # MONTHLY
    "statute_authority_review": {
        "check": "verified_date older than 365 days",
        "threshold": "any jurisdiction",
        "auto_action": "none",
        "escalation": "MANDATORY human sign-off: re-verify statute text",
    },
    "scraper_registry_audit": {
        "check": "all enabled scrapers have been run in past 30 days",
        "threshold": "any enabled scraper with no run",
        "auto_action": "disable scraper with reason 'no_run_30_days'",
        "escalation": "ops: scraper may be broken or obsolete",
    },
}
```

### Detection Thresholds

| Signal | Threshold | Auto Response | Human Escalation |
|--------|-----------|---------------|-----------------|
| Scraper returns 0 records | 1 occurrence | Log warning | After 2 consecutive failures: disable |
| Scraper returns < 50% of previous count | 1 occurrence | Log warning, keep data | After 3 occurrences: pause scraper |
| Tier 2 null rate increases > 5% | Per scraper run | Pause that scraper | Alert ops |
| ATTORNEY asset expires | Per evaluation cycle | Auto-close | None (normal operation) |
| > 50% of assets killed in single run | Per evaluation cycle | Halt evaluation | CRITICAL: review kill logic |
| Schema mismatch (scraper output changed) | Per scraper run | Reject batch, keep old data | Alert: site may have changed |

### Scheduled Operations

| Cadence | Operation | Owner |
|---------|-----------|-------|
| Every 3 hours | evaluate_all() — re-score and transition assets | Cron/system |
| Daily 02:00 UTC | Scraper freshness check | Watchdog |
| Daily 02:00 UTC | Statute expiry sweep | Watchdog |
| Daily 02:00 UTC | Null rate analysis | Watchdog |
| Weekly Monday 06:00 | Event log growth report | Watchdog |
| Weekly Monday 06:00 | Class distribution report | Watchdog |
| Monthly 1st 06:00 | Statute authority freshness check | Watchdog → human |
| Monthly 1st 06:00 | Scraper registry audit | Watchdog → human |
| Quarterly | Full system inventory re-run | Human (this document) |

### Manual Sign-offs Required

| Item | Frequency | Who | What They Verify |
|------|-----------|-----|-----------------|
| Statute authority entries | Annually | Licensed attorney | Citation still valid, window unchanged, fee cap unchanged |
| New jurisdiction onboarding | Per addition | Licensed attorney | Statute text reviewed, triggering event confirmed |
| Scraper re-enablement after disable | Per occurrence | Ops engineer | Root cause identified, fix verified |
| Bulk data import (> 100 records) | Per import | Ops + data engineer | Source verified, field mapping correct |

---

## SECTION 6: REFACTOR ROADMAP

**Ordered by risk reduction. No feature expansion. No rewrites unless necessary.**

| Priority | Refactor | Risk Reduced | Effort | Files Touched |
|----------|----------|-------------|--------|---------------|
| 1 | **Fix data_age_days TODO** in pipeline.py | Confidence scores never penalize stale data | 15 min | pipeline.py |
| 2 | **Build watchdog.py** with daily checks | Silent degradation undetected | 2 hr | New: core/watchdog.py |
| 3 | **Add recorder_link generator** for all CO counties | 9/12 scrapers missing Tier 2 field → blocked | 1 hr | New: core/recorder_links.py, pipeline.py |
| 4 | **Wrap legacy scrapers** (fetch_master.py, verifuse_server_safe.py) to output canonical ingest format | Legacy scrapers produce non-standard output | 2 hr | New adapter wrappers |
| 5 | **Consolidate PBC hunter variants** into single canonical scraper | 8 ghost variants create confusion | 2 hr | New: scrapers/pbc_foreclosure.py, delete ghosts |
| 6 | **Build Airtable sync adapter** that reads from canonical DB | Legacy airtable_sync.py reads from superseded vault.db | 1 hr | New: sync/airtable.py |
| 7 | **Build Mesa owner supplemental scraper** | Mesa blocked from ATTORNEY (missing owner) | 2 hr | New: scrapers/mesa_assessor.py |
| 8 | **Build PBC owner supplemental scraper** | PBC blocked from ATTORNEY (missing owner) | 2 hr | New: scrapers/pbc_clerk.py |

**Explicit non-goals:**
- Do NOT rewrite fusion_engine.py (superseded, used only for historical reference)
- Do NOT build new UI (attorney UI spec exists, rendering is deployment concern)
- Do NOT add new jurisdictions until existing ones reach ATTORNEY class

---

## SECTION 7: EXPLICIT REFUSALS

| # | Refused To | Why It Protects The System |
|---|-----------|---------------------------|
| 1 | **Automate lien_type detection** | Would require parsing full case filings per asset. False positive (wrong lien type) could mislead attorney. Default + documented degradation is safer than unreliable inference. |
| 2 | **Infer surplus from debt-only portals** | Eagle/Summit/San Miguel show total_indebtedness but not surplus. Surplus = bid - judgment, and bid only exists post-auction. Estimating surplus from debt is speculation, not evidence. |
| 3 | **Scrape owner from property tax records** without verification | Property tax records show assessed owner, not necessarily the foreclosure defendant. Wrong owner = wrong claimant = legal malpractice risk for attorney. |
| 4 | **Auto-generate recorder links as "official" links** | Generated search URLs are not direct document links. Labeling them "official" would be deceptive. They are explicitly labeled as search URLs. |
| 5 | **Auto-extend statute windows** | If our days_remaining calculation shows 0, the conservative action is CLOSE, not assume we miscalculated. An attorney relying on an incorrectly extended window faces malpractice exposure. |
| 6 | **Merge renaissance_lab data with surplus engine** | renaissance_lab is a separate trading physics system. Its data (BTC prices, Reynolds numbers) has zero relevance to surplus funds. Merging would pollute both systems. |
| 7 | **Scrape competing legal service providers** | Monitoring competitor lead lists or attorney claim filings is legally and ethically hazardous. We collect only public county/court records. |
| 8 | **Auto-submit claims on behalf of attorneys** | Legal practice. We provide intelligence, not legal services. Auto-submission would constitute unauthorized practice of law. |
| 9 | **Bulk export attorney-visible data as CSV** | Would enable downstream skip-tracing, spam, or resale. The system serves individual case packets, not data dumps. |
| 10 | **Predict future surplus amounts** | Surplus is determined by auction outcome. Predicting it requires modeling bidder behavior, which is speculative. We report what happened, not what might happen. |
| 11 | **Touch verifuse.tech root domain or existing subdomains** | Constraint violation. This project is isolated. No shared state, no shared auth, no domain modifications. |
| 12 | **Auto-disable scrapers without logging** | Silent disablement hides data gaps. Every disable must have a reason in scraper_registry.disabled_reason and an ops alert. |

---

## SECTION 8: DUPLICATE LOGIC REGISTER

Legacy code that duplicates canonical implementations:

| Legacy File | Duplicated By | Canonical Location | Action |
|------------|--------------|-------------------|--------|
| fusion_engine.py:identify_columns() | Field mapping | pipeline.py:ingest_asset() | SUPERSEDED — do not use |
| fusion_engine.py:detect_county() | County detection | Derived from scraper source_name | SUPERSEDED |
| fusion_engine.py:calculate_quants() | Scoring | pipeline.py:compute_* functions | SUPERSEDED |
| fusion_engine.py:get_recorder_link() | Link generation | migrations/migrate_from_legacy.py | SUPERSEDED |
| airtable_sync.py:row_to_fields() | Field export | Should read from canonical DB | NEEDS ADAPTER |
| 8x hunter_*.py | PBC scraping | None (needs canonical scraper) | CONSOLIDATE to 1 |
| 5x verifuse_*.py | Treasury search | None (needs canonical scraper) | CONSOLIDATE to 1 |

---

## SECTION 9: CURRENT SYSTEM STATE SUMMARY

```
ASSETS:           679 total
  ATTORNEY:        77  (11.3%) — visible to attorneys
  CLOSED:         602  (88.7%) — killed by data quality gates
  PIPELINE:         0  (0.0%)  — all evaluated
  QUALIFIED:        0  (0.0%)  — all promoted or killed

ATTORNEY BY COUNTY:
  Jefferson:       63  ($1,826,675 surplus)
  Arapahoe:        12  ($1,426,297 surplus)
  Mesa:             1  ($40,000 surplus)
  Douglas:          1  ($4,798 surplus)

AUDIT TRAIL:     1,441 events
STATUTE RULES:      11 jurisdiction entries
SCRAPERS:           12 registered (0 have run against canonical DB)
CLOSE REASONS:     601 data_grade_reject, 1 statute_expired

CRITICAL PATH:
  88.5% of assets have NULL sale_date → NULL days_remaining → killed
  This is correct behavior: portal records (Eagle/Summit/San Miguel)
  have no sale_date because no sale has occurred yet.
  They will re-enter the pipeline when post-sale data becomes available.
```
