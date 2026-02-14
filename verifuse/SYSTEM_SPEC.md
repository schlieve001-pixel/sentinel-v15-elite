# VeriFuse Surplus Engine — System Specification

**Version:** 1.0
**Date:** 2026-02-07
**Status:** LOCKED — All decisions final

---

## DELIVERABLE 1: Canonical Data Model

**Location:** `verifuse/core/schema.py`

### Tables

| Table | Purpose | Mutable? |
|-------|---------|----------|
| `assets` | Immutable facts (Tier 1-4 fields) | UPDATE only (COALESCE — never overwrite with NULL) |
| `pipeline_events` | Append-only audit log | INSERT only. No UPDATE. No DELETE. |
| `legal_status` | Current state per asset (one row each) | UPDATE by pipeline.py ONLY |
| `statute_authority` | Jurisdiction-specific legal rules | Manual updates by verified attorney |
| `scraper_registry` | Scraper coverage declarations | Updated by scrapers on run |
| `attorney_view` | SQL VIEW — derived, read-only | Never written to |
| `blacklist` | Address-level exclusions | INSERT/DELETE with reason |

### Record Classes (Exactly Four)

```
PIPELINE   → unverified, non-actionable
QUALIFIED  → verified, but not attorney-ready
ATTORNEY   → ready for legal action
CLOSED     → resolved / expired / disposed
```

### Field Tiers

- **Tier 1 (Identity):** asset_id, county, jurisdiction, case_number, asset_type
- **Tier 2 (Legal Actionability):** statute_window, days_remaining, owner_of_record, lien_type, sale_date, recorder_link
- **Tier 3 (Financial):** estimated_surplus, total_indebtedness, overbid_amount, fee_cap
- **Tier 4 (Intelligence — NEVER shown to attorneys):** completeness_score, confidence_score, risk_score, data_grade

**RULE:** If Tier 2 is incomplete → asset CANNOT enter ATTORNEY class. No exceptions.

---

## DELIVERABLE 2: Scraper Coverage Map

**Location:** `verifuse/scrapers/registry.py`

### What Exists vs. Missing

| Scraper | Jurisdiction | Confidence | Has Owner? | Has Sale Date? | Has Surplus? | Has Recorder Link? | Can Reach ATTORNEY? |
|---------|-------------|------------|------------|----------------|--------------|-------------------|-------------------|
| denver_foreclosure | Denver, CO | HIGH | Yes | Yes | Yes | Search URL | Yes (with lien_type default) |
| denver_tax | Denver, CO | HIGH | Yes | **No** | Yes | No | **No** (missing sale_date) |
| jefferson_foreclosure | Jefferson, CO | HIGH | Yes | Yes | Yes | Search URL | Yes (with lien_type default) |
| arapahoe_foreclosure | Arapahoe, CO | HIGH | Yes | Partial | Yes | No | **Partial** |
| douglas_foreclosure | Douglas, CO | MED | Yes | Mon-YY only | Yes | No | **No** (missing case_number) |
| douglas_tax | Douglas, CO | MED | Yes | Yes | Yes | No | **Partial** |
| mesa_foreclosure | Mesa, CO | HIGH | **No** | Yes | Yes | No | **No** (missing owner) |
| eagle_portal | Eagle, CO | MED | Yes | Yes | **No** | No | **No** (missing surplus) |
| teller_govease | Teller, CO | MED | Yes | Yes | Yes | No | **Partial** |
| summit_govease | Summit, CO | MED | Yes | Yes | **No** | No | **No** (missing surplus) |
| sanmiguel_portal | San Miguel, CO | MED | Yes | Yes | **No** | No | **No** (missing surplus) |
| pbc_foreclosure | Palm Beach, FL | HIGH | **No** | Yes | Yes | No | **No** (missing owner) |

### Critical Gaps

1. **lien_type**: No scraper provides this. **DECISION:** Default "Deed of Trust" for foreclosure, "Tax Lien" for tax. Known degradation. Documented.
2. **recorder_link**: Only Denver/Jefferson generate search URLs (not direct links). **DECISION:** Acceptable — attorneys understand search URLs.
3. **owner_of_record**: Missing from Mesa, PBC. **DECISION:** These assets are BLOCKED from ATTORNEY class until owner is manually supplied.
4. **estimated_surplus**: Missing from Eagle, Summit, San Miguel portals (they show debt only). **DECISION:** BLOCKED from ATTORNEY class.

---

## DELIVERABLE 3: State Machine Diagram

**Location:** `verifuse/core/pipeline.py`

```
                    ┌──────────────────────────────────────────┐
                    │              KILL SWITCHES               │
                    │  • days_remaining <= 0                   │
                    │  • data_grade == REJECT                  │
                    │  • no statute_authority entry             │
                    │  • confidence < 0.3                      │
                    └──────────┬───────────────────────────────┘
                               │ (any state → CLOSED)
                               ▼
┌──────────┐   Tier 1 OK    ┌───────────┐   Full Tier 2     ┌──────────┐
│ PIPELINE │──────────────▶│ QUALIFIED │────────────────▶│ ATTORNEY │
│          │  + partial T2  │           │  GOLD/SILVER      │          │
│ (entry)  │                │           │  days > 0         │ (visible)│
└──────────┘                └───────────┘  statute exists    └────┬─────┘
     ▲                                                           │
     │                                                           │ expiry / action
     │ ingest_asset()                                            ▼
     │                                                      ┌──────────┐
     └──────────────────────────────────────────────────────│  CLOSED  │
                              (terminal — no reverse)       └──────────┘
```

### Transition Rules

| From | To | Gate Conditions | Logged As |
|------|----|----------------|-----------|
| (new) | PIPELINE | Asset ingested from scraper | CREATED |
| PIPELINE | QUALIFIED | Tier 1 complete + completeness >= 0.5 | CLASS_CHANGE: promotion:tier1_complete_partial_tier2 |
| QUALIFIED | ATTORNEY | completeness == 1.0, grade ∈ {GOLD, SILVER}, days > 0, statute exists | CLASS_CHANGE: promotion:full_tier2_grade_eligible |
| ATTORNEY | CLOSED | days <= 0 OR attorney action OR kill-switch | CLASS_CHANGE: kill_switch:* or attorney_action |
| ANY | CLOSED | Kill-switch triggered | CLASS_CHANGE: kill_switch:* |

**Reverse transitions are FORBIDDEN.** CLOSED is terminal.

---

## DELIVERABLE 4: Attorney UX Contract

**Location:** `verifuse/attorney/ui_spec.py`

### What They See (attorney.verifuse.tech)

| Column | Why |
|--------|-----|
| County | Jurisdiction |
| Jurisdiction | County + State |
| Asset ID | Reference |
| Asset Type | Context |
| Est. Surplus | Incentive |
| Days Remaining | Urgency |
| Statute Window | Legal reality |
| Recorder Link | Proof |
| Status | Can I act? |
| Owner of Record | Party ID |
| Property Address | Location |
| Sale Date | Timeline |
| Case Number | Court ref |

### Buttons (exactly three)

1. **Download Case Packet** → PDF with Sections 1-7
2. **Mark Interested** → Logs event, updates work_status
3. **Archive** → Removes from their view (does not delete)

### What They NEVER See

- Completeness Score, Confidence Score, Risk Score
- Data Grade, Record Class transitions, Pipeline events
- Source scraper names, Source file hashes
- Internal priority, Tier 4 fields, Airtable anything
- Scoring formulas, Automation logic, "Kill switch" terminology

---

## DELIVERABLE 5: Automation Rules

| Trigger | Action | Audit |
|---------|--------|-------|
| New scraper output | `ingest_asset()` → PIPELINE | CREATED event logged |
| Scheduled evaluation | `evaluate_all()` runs gates | CLASS_CHANGE events logged |
| Tier 1 complete + partial Tier 2 | PIPELINE → QUALIFIED | Reason + scores in metadata |
| Full Tier 2 + GOLD/SILVER + days > 0 | QUALIFIED → ATTORNEY | Reason + gate values logged |
| days_remaining <= 0 | ANY → CLOSED | kill_switch:statute_expired |
| confidence < 0.3 | ANY → CLOSED | kill_switch:data_grade_reject |
| No statute_authority entry | Block ATTORNEY promotion | kill_switch:no_statute_authority |
| Scraper last_run > 2x frequency | Flag for review | Logged, asset stays in class |
| Attorney clicks "Mark Interested" | work_status = INTERESTED | ATTORNEY_INTEREST event |
| Attorney clicks "Archive" | work_status = ARCHIVED | ARCHIVED event |
| Attorney clicks "Download Packet" | PDF generated | CASE_PACKET_GENERATED event |

---

## DELIVERABLE 6: Case Packet Structure

**Location:** `verifuse/attorney/case_packet.py`

| Section | Contents | Source |
|---------|----------|--------|
| 1. Cover Page | Asset ID, Jurisdiction, Date, Warning | Generated |
| 2. Asset Summary | All Tier 1 + Tier 2 fields | assets table |
| 3. Financial Summary | Surplus, Debt, Overbid, Fee Cap | assets + statute_authority |
| 4. Statute Information | Window, Citation, Days, Court req | statute_authority |
| 5. Recorder Reference | County recorder link + instructions | assets |
| 6. Provenance | Source, collection date, hashes | assets metadata |
| 7. Disclaimer | Legal disclaimer | Static text |

**Gate:** Only ATTORNEY-class assets with GOLD/SILVER grade can generate packets.

---

## DELIVERABLE 7: Legal Risk Register

| Risk | Severity | Mitigation | Residual |
|------|----------|------------|----------|
| Surplus estimate is wrong | HIGH | Recorder link provided for attorney verification. Disclaimer on packet. Estimate labeled "estimated." | Attorney verifies independently. |
| Expired statute shown to attorney | CRITICAL | Kill switch: days_remaining <= 0 removes from attorney_view automatically. | Near-zero if sale_date is correct. |
| County publishes incorrect data | HIGH | statute_authority.known_issues documents per-county. Legal confidence downgrades to MED. | Attorney warned via known_issues in packet. |
| Owner name is wrong | MEDIUM | Owner from public record only. Recorder link for verification. | Attorney verifies independently. |
| Asset shown to wrong jurisdiction attorney | LOW | attorney_view filters by jurisdiction. Subscriber sees only their jurisdictions. | Misconfigured subscription = wrong filter (ops risk). |
| Competing claims exist | HIGH | Not detectable by our system. Disclaimer states "may not reflect competing claims." | Attorney's responsibility to check. |
| System used as marketing/spam tool | MEDIUM | No bulk export. No lead lists. Case packets only. Rate limiting on downloads. | Product design prevents misuse. |
| Regulator subpoena for classification logic | LOW | pipeline_events table provides complete audit trail with timestamps, actors, and reasons for every transition. | Full defensibility via event log. |
| Hostile attorney audits system | LOW | attorney_view excludes all internal logic. Case packet shows provenance. Events log proves process. | Transparent by design. |

---

## DELIVERABLE 8: Explicit Rejection Criteria

### What We Refused to Build

| Feature | Why Rejected |
|---------|-------------|
| AI-generated surplus estimates | Ambiguous "AI judgment" replaces legal facts. Surplus must come from public record math (bid - judgment) or official posting. |
| Lead scoring visible to attorneys | Scores exist to route, not to sell. Exposing them implies reliability guarantees we cannot make. |
| Bulk lead export / CSV download | Would enable spam/skip-trace farming. Violates "we sell opportunities, not leads" principle. |
| Automated outreach to attorneys | Marketing tool behavior. Attorneys subscribe and pull. We do not push. |
| Airtable as attorney-facing UI | Exposes internal infrastructure. Violates separation of concerns. |
| Predictive modeling for surplus amounts | Speculation. We report what public records say, not what we think they mean. |
| Multi-tenant shared attorney views | Competitive intelligence risk. Each subscriber sees only their jurisdictions. |
| Automated court filing | Legal practice. We provide intelligence, not legal services. |
| "AI confidence" badges on assets | Implies machine endorsement of legal opportunities. Rejected. |
| Reverse transitions (CLOSED → ATTORNEY) | Once closed, stay closed. If conditions change, a new asset is created. Prevents resurrection of stale data. |

---

## Economic Moat Analysis

### What Cannot Be Cheaply Copied

1. **Statute authority table**: Requires attorney-verified research per jurisdiction. Each entry needs citation, triggering event, fee cap, and known issues. This is legal research, not data scraping.

2. **Pipeline event history**: The audit trail of every asset transition creates forensic defensibility that new entrants cannot retroactively generate.

3. **County-specific scraper maintenance**: Each county changes their website structure periodically. Maintaining 12+ scrapers with known_gaps documentation is ongoing operational cost.

### What Degrades If Scraped Naively

1. **Douglas County Mon-YY dates**: Naive parsing gives wrong statute expiry. Our system assumes 1st-of-month (worst case).

2. **Surplus calculation from PBC**: Selenium scraping of realforeclose.com catches nested HTML elements. Naive scraping double-counts.

3. **Portal records vs. surplus records**: Eagle/Summit/San Miguel portals show debt, not surplus. Naive ingestion would show zeros or negatives.

### What Requires Legal Reasoning

1. **Statute window calculation**: Varies by asset type and jurisdiction. C.R.S. 38-38-111 vs 39-11-151. Florida is 1 year, not 5.

2. **Fee cap determination**: Some jurisdictions cap attorney fees. Must be per-statute, not guessed.

3. **"Can I act?" determination**: Requires all of: statute not expired, data verified, owner identified, lien type known. This is a legal judgment gate, not a data completeness check.

### Where Human Review Is Strategically Irreplaceable

1. **Statute authority verification**: Must be verified by someone who can read statute text. Cannot be automated.

2. **Owner ambiguity resolution**: "ESTATE OF JOHN DOE ET AL" requires human judgment on who the rightful claimant is.

3. **Known issues documentation**: "County publishes incorrect sale dates" is discovered through operational experience, not scraping.

---

## Jurisdictional Fracture Handling

### Statute Authority Table

`verifuse/core/schema.py` → `statute_authority` table

Every jurisdiction that we serve MUST have an entry. If it doesn't:
- Assets from that jurisdiction CANNOT enter ATTORNEY class
- The system logs `kill_switch:no_statute_authority`
- The asset remains in QUALIFIED with a clear reason

### Conflict Resolution Rule

When county data conflicts with our statute interpretation:
1. Log the conflict as a PIPELINE_EVENT with type MANUAL_REVIEW
2. Downgrade data_grade to BRONZE (blocks ATTORNEY promotion)
3. Flag for human review
4. Asset stays in QUALIFIED until conflict is resolved

### "Cannot Verify" Kill State

Triggered when:
- sale_date is NULL or unparseable → days_remaining = NULL → cannot compute statute
- No statute_authority entry for jurisdiction
- confidence_score < 0.3

Result: Asset enters CLOSED with reason `kill_switch:cannot_verify`

**No silent assumptions allowed.** If we can't verify it, we kill it.

---

## Domain & Deployment

| Subdomain | Purpose | Auth |
|-----------|---------|------|
| internal.verifuse.tech | Admin / ops dashboard | Internal SSO |
| attorney.verifuse.tech | Subscriber UI (attorney_view only) | Separate auth, subscription-gated |
| api.verifuse.tech | Data access (future) | API keys, rate-limited |

No root-domain apps. No shared auth between roles.

---

## File Structure

```
verifuse/
├── SYSTEM_SPEC.md              ← This document
├── core/
│   ├── __init__.py
│   ├── schema.py               ← Canonical data model (DDL + enums)
│   └── pipeline.py             ← State machine + scoring + ingestion
├── scrapers/
│   ├── __init__.py
│   └── registry.py             ← Scraper coverage map + declarations
├── attorney/
│   ├── __init__.py
│   ├── ui_spec.py              ← Dashboard columns + query logic
│   └── case_packet.py          ← PDF case packet generator
├── migrations/
│   ├── __init__.py
│   └── migrate_from_legacy.py  ← Legacy vault.db → canonical migration
└── data/
    └── verifuse.db             ← Generated by schema.py init
```
