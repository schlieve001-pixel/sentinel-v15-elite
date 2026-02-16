# Compliance

Legal and regulatory framework governing VeriFuse V2 operations in Colorado.

---

## Primary Statute: C.R.S. SS 38-38-111

**Title:** Disposition of Excess Proceeds from Foreclosure Sales

This is the foundational statute for surplus fund recovery in Colorado. Key provisions:

### Six-Month Holding Period

After a foreclosure sale, the Public Trustee holds the surplus funds for **six calendar months**. During this period:

- The former owner may file a claim directly with the Public Trustee
- **Compensation agreements signed during the holding period are VOID** (SS 38-38-111(4))
- This means: no attorney or recovery specialist may enter into a fee agreement with the former owner during the first six months after the sale

### VeriFuse Enforcement

The six-month restriction is enforced at the API level:

```
Status: RESTRICTED
Applies when: today < sale_date + 6 calendar months
Effect: Lead requires verified attorney + OPERATOR/SOVEREIGN tier to unlock
Legal basis: C.R.S. SS 38-38-111(4)
```

The system uses `dateutil.relativedelta(months=6)` for legally precise calendar month arithmetic (not a flat 180-day approximation).

### After the Holding Period

Once six months have passed:
- Lead status changes to `ACTIONABLE`
- Any paid subscriber with credits can unlock the lead
- Attorney may enter into a compensation agreement with the former owner
- If the surplus is unclaimed, it eventually escheats to the county

### Claim Deadline

If the former owner does not claim the surplus within the statutory period, the funds are forfeited. Leads past their claim deadline are marked `EXPIRED` and cannot be unlocked (HTTP 410).

---

## C.R.S. SS 38-13-1302 -- Attorney Exemption

Attorneys licensed in Colorado may engage in surplus fund recovery as part of their legal practice, provided they comply with all ethical rules. Section 38-13-1302(5) provides specific guidance on attorney conduct in connection with excess funds.

VeriFuse references this statute in the RESTRICTED lead unlock response:

```json
{
    "attorney_exemption": "C.R.S. SS 38-13-1302(5)"
}
```

---

## Colorado Rule of Professional Conduct 7.3

**Solicitation of Clients**

Colorado RPC 7.3 governs direct solicitation of prospective clients by attorneys. VeriFuse's letter generation feature (`POST /api/letter/{lead_id}`) produces Rule 7.3 compliant solicitation letters that:

- Clearly identify the communication as an attorney solicitation
- Include the attorney's name, firm, bar number, and address
- Do not make misleading claims about guaranteed recovery amounts
- Comply with required disclaimers

**Requirements to generate a letter:**
1. User must have `attorney_status = "VERIFIED"`
2. User must have `firm_name` populated
3. User must have `bar_number` populated
4. User must have `firm_address` populated
5. User must have unlocked the lead (paid credit)

---

## Colorado Open Records Act (CORA)

**C.R.S. SS 24-72-201 et seq.**

Foreclosure sale records, excess fund reports, and public trustee filings are public records under CORA. VeriFuse scrapes publicly available data from county websites and may submit CORA requests for records not published online.

### CORA Compliance for Scrapers

- All data scraped is from publicly accessible county websites
- No authentication bypass or restricted-area access
- Rate-limited requests (PoliteCrawler: 2 requests/minute) to avoid burdening county servers
- No scraping of data behind login walls

### CORA Requests for Rural Counties

For the approximately 15 rural counties using the `manual` platform, data is obtained through formal CORA requests:

1. Submit a written CORA request to the county Public Trustee
2. Request: "All excess/surplus fund records from foreclosure sales for the past 24 months"
3. Pay any applicable copy fees
4. Receive records and manually ingest into the system

---

## Ethical Scraping Rules

VeriFuse follows strict ethical scraping practices:

### Rate Limiting

All HTTP requests go through `PoliteCrawler` which enforces:
- Maximum 2 requests per minute per domain (configurable)
- Exponential backoff on errors
- Conditional GET (If-Modified-Since) to skip unchanged content
- Respectful User-Agent header

### robots.txt

The scraper framework respects `robots.txt` directives. If a county explicitly blocks the scraper via `robots.txt`, that county must use the manual/CORA pipeline.

### Data Minimization

VeriFuse only collects data necessary for surplus fund identification:
- Case numbers
- Sale dates and amounts
- Property addresses (for owner identification)
- Owner names (from public sale records)

No SSNs, financial account numbers, or other sensitive personal data is collected or stored.

### No Impersonation

Scrapers do not impersonate users, submit forms as real people, or bypass CAPTCHAs.

---

## Data Handling

### PII Protection

PII (owner name, full property address) is:
- Stored in the SQLite database with filesystem-level access control
- **Not revealed** in the public API (SafeAsset projection uses city hints and rounded surplus)
- Only revealed on unlock (FullAsset) after authentication, tier verification, and credit deduction
- Logged in `lead_unlocks` with IP address for audit compliance

### Disclaimer Requirements

Every API response includes the legal disclaimer:

> "Forensic information service only. Not a debt collection or asset recovery agency. Subscriber responsible for all legal compliance under C.R.S. SS 38-38-111."

The unlock endpoint for RESTRICTED leads requires explicit disclaimer acceptance:

> "I certify I am a licensed legal professional and understand C.R.S. SS 38-38-111 restrictions on inducing compensation agreements during the six calendar month holding period."

### Download Audit Trail

Every document download (dossiers, letters, case packets) is logged to the `download_audit` table:
- User ID
- Lead ID
- Document type
- Whether access was granted or denied
- Client IP address
- Timestamp

---

## Anti-Competition Safeguards

VeriFuse takes measures to prevent misuse of its data:

### Credit System

Lead PII is behind a paywall (credits). This prevents mass data extraction.

### Per-Tier API Limits

| Tier | Daily Lead Views | Concurrent Sessions |
|------|-----------------|---------------------|
| Recon | 50 | 1 |
| Operator | 200 | 2 |
| Sovereign | 500 | 3 |

### Rate Limiting

100 requests per minute per IP address for the leads endpoint. 10 requests per minute for unlock endpoints.

---

## Compliance Checklist

- [x] Six-month restriction period enforced in API (RESTRICTED status gate)
- [x] Calendar month arithmetic (not 180-day approximation)
- [x] Verified attorney requirement for RESTRICTED leads
- [x] Legal disclaimer on every response
- [x] Unlock disclaimer acceptance for RESTRICTED leads
- [x] Rule 7.3 compliant letter generation
- [x] CORA-sourced data for rural counties
- [x] Ethical scraping with rate limiting
- [x] PII protected behind credit-gated unlock
- [x] Audit trail for all unlocks and document downloads
- [x] No direct contact with former homeowners (VeriFuse is an information service)
