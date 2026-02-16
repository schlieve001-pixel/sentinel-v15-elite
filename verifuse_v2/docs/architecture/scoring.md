# Scoring Engine

VeriFuse uses a multi-layer deterministic scoring system. There is no machine learning -- all scores are computed from explicit formulas applied to structured data extracted from county PDFs.

---

## Layer 1: Confidence Function C (Parser Level)

Defined in `verifuse_v2/scrapers/registry.py` on the `CountyParser` base class.

### Formula

```
C = 0.25 * I(bid > 0)
  + 0.25 * I(debt > 0)
  + 0.15 * I(sale_date exists)
  + 0.15 * I(address length > 5)
  + 0.10 * I(owner name length > 2)
  + 0.10 * V(delta)
```

Where:
- `I(condition)` is an indicator function: 1.0 if true, 0.0 if false
- `V(delta)` is the **variance check** (see below)
- `C` is clamped to `[0.0, 1.0]`

### Variance Check V(delta)

The variance check compares the stated surplus against the computed surplus (`bid - debt`):

```
delta = |surplus_amount - max(0, winning_bid - total_debt)|

V(delta) =
    1.0   if delta <= $5.00     (exact match)
    0.5   if delta <= $50.00    (minor discrepancy)
    0.0   otherwise             (anomalous variance)
```

If `bid > 0` and `debt > 0`, the full variance check applies. If there is a surplus but no bid/debt data to cross-check (common for Denver excess fund lists where the county verifies the amount directly), a partial score of `0.05` is awarded.

### County-Specific Overrides

Some parsers override the base `score()` method:

**AdamsParser:** Adds a +0.05 bonus when the explicit `overbid_amount` matches `bid - debt` within $5.00. Adams County PDFs include a separate overbid field, providing an extra verification signal.

**DenverExcessParser:** Uses a completely different formula because Denver excess fund lists are county-verified (the county itself publishes the available amount):

```
C_denver = 0.40 * I(surplus > 0)    # County-verified amount
         + 0.20 * I(sale_date)
         + 0.20 * I(address length > 5)
         + 0.15 * I(owner name length > 2)
         + 0.05 * I(case_number exists)
```

---

## Layer 2: Engine V2 Threshold Routing

Defined in `verifuse_v2/scrapers/engine_v2.py`. After a parser computes the confidence score, Engine V2 routes the record based on threshold:

| Confidence Range | Status | Action |
|-----------------|--------|--------|
| `C > 0.8` | `ENRICHED` | Write to `leads` table |
| `0.5 < C <= 0.8` | `REVIEW_REQUIRED` | Write to `leads` table, flagged for review |
| `C <= 0.5` | `ANOMALY` | Log to `engine_v2_anomalies.jsonl`, skip DB write |

---

## Layer 3: Data Grade (Parser Level)

Defined in the `grade()` method on `CountyParser`:

| Grade | Criteria | Meaning |
|-------|----------|---------|
| **GOLD** | `surplus >= $10,000` AND `confidence >= 0.8` | High-value, high-confidence. Attorney-ready. |
| **SILVER** | `surplus >= $5,000` AND `confidence >= 0.6` | Medium value, decent data quality. |
| **BRONZE** | `surplus > $0` | Has some surplus but incomplete data. |
| **IRON** | `surplus <= $0` | No surplus detected. |

---

## Layer 4: Pipeline Re-Grading

Defined in `verifuse_v2/core/pipeline.py`. Runs as a batch job over all leads in the database. Uses additional signals not available at parse time.

### Completeness Score

Percentage of Tier 2 fields that have real (non-placeholder) values:

```
Tier 2 fields: owner_name, property_address, sale_date,
               claim_deadline, case_number, county

completeness = (count of non-empty Tier 2 fields) / 6

Placeholder values (treated as empty):
  "", "unknown", "n/a", "na", "none", "tbd", "check records",
  "check county site", "not available", "pending", "see file"
```

### Pipeline Confidence Score

```
trust = existing confidence_score (or 0.5 if missing)
age_penalty = max(0, (data_age_days - 7) / 7) * 0.05
confidence = max(0.0, trust - age_penalty)
```

Data aging: leads lose 5% confidence for every week past the first week since their last update.

### Pipeline Grade Assignment

| Grade | Criteria |
|-------|----------|
| **GOLD** | `completeness == 1.0` AND `confidence >= 0.7` AND `surplus > 0` AND `days_remaining > 30` |
| **SILVER** | `completeness >= 0.8` AND `confidence >= 0.5` AND `surplus > 0` |
| **BRONZE** | Does not meet SILVER criteria |
| **REJECT** | `days_remaining <= 0` OR `confidence < 0.2` OR `surplus <= 0` |

---

## Layer 5: BS Detector

Defined in `verifuse_v2/core/pipeline.py`. Flags suspicious records that pass confidence thresholds but exhibit known anomaly patterns.

### Rules

**WHALE_CAP:** Surplus exceeds $1,000,000. Extremely rare in Colorado foreclosure surplus; likely a data extraction error.

```python
if surplus > 1_000_000:
    flag("WHALE_CAP")
```

**DATE_GLITCH:** Surplus amount looks like a misparse date (e.g., `12152024` parsed as `$12,152,024`).

```python
if surplus matches pattern /^[01]?\d[0-3]\d20[12]\d$/
    flag("DATE_GLITCH")
```

**RATIO_TEST:** Surplus exceeds 50% of total debt. While possible, this ratio is unusual and warrants manual review.

```python
if debt > 0 and surplus > (debt * 0.50):
    flag("RATIO_TEST")
```

BS flags do not automatically quarantine leads. They are logged and counted in the pipeline evaluation report for manual review.

---

## Quarantine Criteria

Defined in `verifuse_v2/db/quarantine.py`. Leads meeting these criteria are moved from `leads` to `leads_quarantine`:

| Reason | Criteria |
|--------|----------|
| `VERTEX_GHOST_ZERO_VALUE` | `confidence_score <= 0.15` AND `surplus_amount = 0` AND `source_name LIKE '%post%sale%continuance%'` |
| `PORTAL_DEBT_ONLY_NO_SURPLUS` | County is Eagle or San Miguel AND surplus = 0 |

Additionally, Jefferson County false-GOLD leads (GOLD grade but `winning_bid IS NULL` and `surplus_amount = 0`) are demoted to `PIPELINE_STAGING` (not quarantined, just re-graded).

---

## Score Examples

### Example 1: Adams County GOLD Lead

```
winning_bid:    $285,000.00
total_debt:     $210,000.00
surplus_amount: $75,000.00
overbid_amount: $75,000.00
sale_date:      2025-08-15
property_addr:  1234 Main St, Brighton, CO 80601
owner_name:     SMITH, JOHN AND JANE

C = 0.25 (bid>0) + 0.25 (debt>0) + 0.15 (date) + 0.15 (addr)
  + 0.10 (owner) + 0.10 (V=1.0, delta=$0.00)
  + 0.05 (Adams overbid bonus, overbid matches bid-debt)
C = 1.00 (clamped)

Grade: GOLD ($75K >= $10K, 1.0 >= 0.8)
Status: ENRICHED (1.0 > 0.8)
```

### Example 2: Denver Excess Funds Lead

```
surplus_amount: $45,231.50
sale_date:      2025-06-01
property_addr:  5678 Oak Ave, Denver, CO 80202
owner_name:     DOE, JANE
case_number:    2025-001234

C_denver = 0.40 (surplus>0) + 0.20 (date) + 0.20 (addr)
         + 0.15 (owner) + 0.05 (case_number)
C_denver = 1.00

Grade: GOLD ($45K >= $10K, 1.0 >= 0.8)
```

### Example 3: Generic Excess Funds (Partial Data)

```
surplus_amount: $3,200.00
sale_date:      null
property_addr:  ""
owner_name:     "JONES"

C = 0.00 (no bid) + 0.00 (no debt) + 0.00 (no date) + 0.00 (no addr)
  + 0.10 (owner) + 0.05 (surplus but no cross-check)
C = 0.15

Grade: N/A -- ANOMALY (0.15 <= 0.5, skipped)
Status: Logged to engine_v2_anomalies.jsonl
```
