# VeriFuse -- Pitch Deck

**Colorado Foreclosure Surplus Intelligence Platform**

---

## The Problem

When a Colorado property is foreclosed and sold at auction for more than the outstanding debt, the excess funds (the "surplus") legally belong to the former homeowner. Under C.R.S. SS 38-38-111, this surplus is held by the county Public Trustee for up to six months.

The problem: **former homeowners rarely know this money exists.** Surplus fund data is scattered across 64 county websites in inconsistent formats -- PDFs, HTML tables, scanned documents, and sometimes paper-only records.

Attorneys and recovery specialists who help homeowners claim these funds face a massive data collection challenge: manually visiting dozens of county websites, downloading PDFs, extracting structured data, and identifying viable cases.

---

## The Solution

VeriFuse automates the entire data pipeline:

1. **Scrape** 64 Colorado county Public Trustee websites daily
2. **Parse** PDFs and HTML using deterministic, auditable regex parsers
3. **Score** each lead with a mathematical confidence function
4. **Grade** leads as GOLD, SILVER, or BRONZE based on data completeness and surplus amount
5. **Serve** leads through a subscription API with tiered access

### How It Works

```
County Websites (64) → Scrapers → PDF Parser → Scoring Engine → API → Attorneys
```

Attorneys subscribe, browse anonymized leads, and spend credits to unlock PII (owner name, address, financial details). They can then contact the former homeowner and assist with the surplus recovery claim.

---

## Architecture

- **Backend:** FastAPI (Python) serving a REST API
- **Frontend:** React SPA at verifuse.tech
- **Database:** SQLite with WAL mode (designed for Supabase migration)
- **Scrapers:** 4 platform adapters covering all county website types
- **Scoring:** Deterministic Confidence Function C with variance checking
- **Legal Compliance:** Hard-coded 6-month restriction period gate

### Key Technical Differentiators

| Feature | Description |
|---------|-------------|
| **64 County Coverage** | Every Colorado county configured (automated or CORA pipeline) |
| **Deterministic Scoring** | No ML black boxes -- every confidence score traceable to field presence and variance |
| **Provenance Chain** | SHA256 hash trail from source PDF to lead record |
| **Attorney Gating** | RESTRICTED leads require verified bar number + paid tier |
| **Atomic Credits** | SQLite `BEGIN IMMEDIATE` prevents double-spend race conditions |

---

## Market

> **PROJECTION -- TBD WITH CITATIONS**
>
> All market size figures below are preliminary projections and require independent verification with cited sources before use in any external materials.

### Total Addressable Market (TAM)

> **PROJECTION -- TBD WITH CITATIONS**
>
> The total value of foreclosure surplus funds generated annually across all US states. Requires citation from ATTOM Data Solutions, CoreLogic, or similar foreclosure tracking provider.

### Serviceable Addressable Market (SAM)

> **PROJECTION -- TBD WITH CITATIONS**
>
> Colorado-specific foreclosure surplus volume. Based on the number of foreclosure sales per year across 64 counties and the average surplus per sale. Requires citation from Colorado Division of Real Estate or county-level data aggregation.

### Serviceable Obtainable Market (SOM)

> **PROJECTION -- TBD WITH CITATIONS**
>
> Estimated number of Colorado attorneys and recovery firms who would subscribe to a surplus intelligence service. Requires survey data or comparable market analysis.

---

## Revenue Model

Three subscription tiers:

| Tier | Price | Credits | Target |
|------|-------|---------|--------|
| Recon | $199/mo | 5 unlocks | Solo researchers |
| Operator | $399/mo | 25 unlocks | Small firms |
| Sovereign | $699/mo | 100 unlocks | Enterprise operations |

Revenue is purely subscription-based. VeriFuse does not take a percentage of recovered surplus and does not directly contact homeowners.

### Revenue Projections

> **PROJECTION -- TBD WITH CITATIONS**
>
> Revenue projections based on subscriber count and tier mix. Actual subscriber acquisition rates must be validated with market testing data.

---

## Competitive Moat

| Moat | Description |
|------|-------------|
| **Data Pipeline** | 64 counties configured with 4 platform adapters. Months of work to replicate. |
| **Parser Library** | County-specific parsers for Adams, Denver, El Paso with per-county scoring overrides. |
| **Legal Compliance** | 6-month restriction period enforcement baked into the API. Attorney verification workflow. |
| **Provenance Chain** | SHA256 trail from source PDF to lead -- required for attorney-ready designation. |
| **First Mover** | No known automated surplus intelligence platform covering all Colorado counties. |

---

## Go-to-Market

### Phase 1: Colorado Launch (Current)
- 64 counties configured, scrapers running daily
- Direct outreach to Colorado foreclosure attorneys
- Content marketing: "How to claim foreclosure surplus in Colorado"

### Phase 2: Market Validation

> **PROJECTION -- TBD WITH CITATIONS**
>
> Subscriber growth targets and conversion rate assumptions require market testing validation.

### Phase 3: Multi-State Expansion

> **PROJECTION -- TBD WITH CITATIONS**
>
> Expansion to additional states (Texas, California, Florida) requires analysis of each state's foreclosure surplus statutes and county data accessibility.

---

## Team

To be completed with team bios and relevant experience.

---

## Financial Summary

> **PROJECTION -- TBD WITH CITATIONS**
>
> All financial projections (CAC, LTV, break-even, runway) are preliminary and require validation against actual subscriber data and operating costs. See [Unit Economics](unit-economics.md) for detailed tier math.

---

## Ask

To be completed based on funding strategy.

---

*Note: All market size claims, revenue projections, and growth estimates in this document are labeled as projections requiring independent verification and citations. They should not be presented as validated figures in external communications.*
