# API Reference

**Base URL:** `https://verifuse.tech`
**Engine:** FastAPI (Titanium API v4)
**Rate Limit:** 100 requests/minute per IP (default)
**Auth:** JWT Bearer token (most endpoints), API key header (admin endpoints)

---

## GET /health

Public health check endpoint.

**Rate Limit:** None
**Auth:** None

**Response 200:**
```json
{
    "status": "ok",
    "engine": "titanium_api_v4",
    "db": "/home/schlieve001/.../verifuse_v2.db",
    "wal_pages": 0,
    "total_leads": 185,
    "scoreboard": [
        {"data_grade": "GOLD", "lead_count": 15, "verified_surplus": 1234567.00},
        {"data_grade": "SILVER", "lead_count": 42, "verified_surplus": 567890.00}
    ],
    "quarantined": 23,
    "verified_total": 2148135.00,
    "legal_disclaimer": "Forensic information service only. Not a debt collection or asset recovery agency. Subscriber responsible for all legal compliance under C.R.S. SS 38-38-111."
}
```

---

## GET /api/leads

List leads with pagination and filters. Returns SafeAsset projections (no PII).

**Rate Limit:** 100/minute
**Auth:** None required (public listing)

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `county` | string | null | Filter by county name |
| `min_surplus` | float | 0.0 | Minimum surplus amount |
| `grade` | string | null | Filter by data grade (GOLD, SILVER, BRONZE) |
| `include_expired` | bool | false | Include expired leads |
| `limit` | int | 50 | Results per page (1-200) |
| `offset` | int | 0 | Pagination offset |

**Example Request:**
```bash
curl "https://verifuse.tech/api/leads?county=Denver&min_surplus=5000&grade=GOLD&limit=10"
```

**Response 200:**
```json
{
    "count": 3,
    "total": 15,
    "limit": 10,
    "offset": 0,
    "leads": [
        {
            "id": "denver_reg_a1b2c3d4e5f6",
            "county": "Denver",
            "case_number": "2025-001234",
            "status": "ACTIONABLE",
            "surplus_estimate": 125000.0,
            "data_grade": "GOLD",
            "confidence_score": 0.95,
            "sale_date": "2025-06-15",
            "claim_deadline": "2025-12-12",
            "days_remaining": 299,
            "city_hint": "DENVER, CO",
            "surplus_verified": true
        }
    ]
}
```

**SafeAsset fields (no PII):**
- `surplus_estimate` -- Rounded to nearest $100
- `city_hint` -- City derived from address, not full address
- `status` -- Dynamically computed: `RESTRICTED`, `ACTIONABLE`, or `EXPIRED`

---

## GET /api/lead/{lead_id}

Single lead detail. Returns extended SafeAsset for the frontend Lead interface.

**Rate Limit:** 100/minute
**Auth:** None required

**Response 200:**
```json
{
    "id": "denver_reg_a1b2c3d4e5f6",
    "county": "Denver",
    "case_number": "2025-001234",
    "status": "ACTIONABLE",
    "surplus_estimate": 125000.0,
    "data_grade": "GOLD",
    "confidence_score": 0.95,
    "sale_date": "2025-06-15",
    "claim_deadline": "2025-12-12",
    "days_remaining": 299,
    "city_hint": "DENVER, CO",
    "surplus_verified": true,
    "asset_id": "denver_reg_a1b2c3d4e5f6",
    "state": "CO",
    "asset_type": "Foreclosure Surplus",
    "estimated_surplus": 125431.50,
    "record_class": "GOLD",
    "restriction_status": "ACTIONABLE",
    "restriction_end_date": "2025-12-15",
    "blackout_end_date": "2025-12-15",
    "days_until_actionable": 0,
    "days_to_claim": 299,
    "deadline_passed": false,
    "address_hint": "DENVER, CO",
    "completeness_score": 0.95,
    "data_age_days": null
}
```

**Response 404:**
```json
{"detail": "Lead not found."}
```

---

## POST /api/leads/{lead_id}/unlock

Unlock a lead to reveal PII (owner name, full address, financial details). Deducts one credit.

**Rate Limit:** 10/minute
**Auth:** JWT Bearer token required

**Headers:**
```
Authorization: Bearer <jwt_token>
```

**Gate Logic:**

| Lead Status | Requirements |
|-------------|-------------|
| `RESTRICTED` | Verified attorney + OPERATOR or SOVEREIGN tier |
| `ACTIONABLE` | Any paid user with credits >= 1 |
| `EXPIRED` | Cannot unlock (HTTP 410) |

**Response 200 (FullAsset):**
```json
{
    "id": "denver_reg_a1b2c3d4e5f6",
    "county": "Denver",
    "case_number": "2025-001234",
    "status": "ACTIONABLE",
    "surplus_estimate": 125000.0,
    "data_grade": "GOLD",
    "confidence_score": 0.95,
    "owner_name": "SMITH, JOHN AND JANE",
    "property_address": "1234 Main St, Denver, CO 80202",
    "winning_bid": 285000.00,
    "total_debt": 159568.50,
    "surplus_amount": 125431.50,
    "overbid_amount": 125431.50
}
```

**Response 401:** `{"detail": "Authentication required."}`
**Response 402:** `{"detail": "Insufficient credits. Upgrade your plan."}`
**Response 403:** `{"detail": "RESTRICTED lead requires verified attorney status."}`
**Response 410:** `{"detail": "This lead has expired. Claim deadline has passed."}`

**Notes:**
- Credit deduction is atomic (`BEGIN IMMEDIATE` transaction)
- Re-unlocking an already-unlocked lead returns the data without deducting a credit
- Admin users bypass all gates

---

## POST /api/unlock/{lead_id}

Frontend-compatible alias for `POST /api/leads/{lead_id}/unlock`. Same behavior.

---

## POST /api/unlock-restricted/{lead_id}

Unlock a RESTRICTED lead with explicit disclaimer acceptance.

**Auth:** JWT Bearer token required
**Body:**
```json
{
    "disclaimer_accepted": true
}
```

**Additional Requirements:**
- User must have `attorney_status = "VERIFIED"`
- User must be on OPERATOR or SOVEREIGN tier

**Response 200:** Same as unlock, plus:
```json
{
    "disclaimer_accepted": true,
    "attorney_exemption": "C.R.S. SS 38-13-1302(5)"
}
```

**Response 400:** `{"detail": "You must accept the legal disclaimer: ..."}`

---

## GET /api/stats

Public dashboard statistics.

**Auth:** None

**Response 200:**
```json
{
    "total_leads": 185,
    "total_assets": 185,
    "attorney_ready": 42,
    "with_surplus": 42,
    "gold_grade": 15,
    "total_claimable_surplus": 2148135.00,
    "counties": [
        {"county": "Denver", "cnt": 45, "total": 890123.00},
        {"county": "Adams", "cnt": 32, "total": 567890.00}
    ]
}
```

---

## GET /api/counties

County-level breakdown of leads and surplus.

**Auth:** None

**Response 200:**
```json
{
    "count": 12,
    "counties": [
        {
            "county": "Denver",
            "lead_count": 45,
            "total_surplus": 890123.00,
            "avg_surplus": 19780.51,
            "max_surplus": 245000.00
        }
    ]
}
```

---

## GET /api/leads/attorney-ready

List leads where `attorney_packet_ready = 1`.

**Rate Limit:** 100/minute
**Auth:** None (listing is public; PII still requires unlock)

**Query Parameters:** `limit` (default 50), `offset` (default 0)

**Response 200:** Same structure as `GET /api/leads`

---

## POST /api/leads/{lead_id}/attorney-ready

Mark a lead as attorney-packet-ready. Requires provenance and data completeness.

**Auth:** API key (x-verifuse-api-key header)

**Validation Requirements:**
- `county` must be populated
- `case_number` must be populated
- `owner_name` must be populated
- `sale_date` must be populated
- `estimated_surplus` must be > 0
- At least one row in `lead_provenance` table (SHA256 provenance)

**Response 200:**
```json
{"status": "ok", "lead_id": "...", "attorney_packet_ready": true}
```

**Response 400:** `{"detail": "Lead not attorney-ready: missing county, missing sale_date"}`

---

## Authentication Endpoints

### POST /api/auth/register

**Rate Limit:** 5/minute
**Body:**
```json
{
    "email": "attorney@lawfirm.com",
    "password": "SecurePassword123",
    "full_name": "Jane Doe",
    "firm_name": "Doe & Associates",
    "bar_number": "CO12345",
    "tier": "recon"
}
```

**Response 200:**
```json
{
    "token": "eyJ...",
    "user": {
        "user_id": "uuid-...",
        "email": "attorney@lawfirm.com",
        "tier": "recon",
        "credits_remaining": 5
    }
}
```

### POST /api/auth/login

**Rate Limit:** 10/minute
**Body:**
```json
{
    "email": "attorney@lawfirm.com",
    "password": "SecurePassword123"
}
```

**Response 200:** Same as register

### GET /api/auth/me

**Auth:** JWT Bearer token

**Response 200:**
```json
{
    "user_id": "uuid-...",
    "email": "attorney@lawfirm.com",
    "full_name": "Jane Doe",
    "firm_name": "Doe & Associates",
    "tier": "recon",
    "credits_remaining": 4,
    "attorney_status": "VERIFIED",
    "is_admin": false
}
```

---

## Billing Endpoints

### POST /api/billing/upgrade

Direct tier upgrade (bypasses Stripe for admin use).

**Auth:** JWT Bearer token
**Body:**
```json
{"tier": "operator"}
```

**Response 200:**
```json
{
    "status": "ok",
    "user_id": "uuid-...",
    "tier": "operator",
    "credits_remaining": 25
}
```

### POST /api/billing/checkout

Create a Stripe checkout session.

**Auth:** JWT Bearer token
**Body:**
```json
{"tier": "sovereign"}
```

**Response 200:**
```json
{"checkout_url": "https://checkout.stripe.com/..."}
```

---

## Attorney Tool Endpoints

### GET /api/dossier/{lead_id}

Download a text dossier for an unlocked lead.

**Auth:** JWT Bearer token (must have unlocked the lead)
**Response:** File download (text/plain)

### GET /api/dossier/{lead_id}/docx

Download a Word document dossier.

**Auth:** JWT Bearer token (must have unlocked the lead)
**Response:** File download (application/vnd.openxmlformats-officedocument.wordprocessingml.document)

### POST /api/letter/{lead_id}

Generate a Rule 7.3 compliant solicitation letter.

**Auth:** JWT Bearer token + verified attorney + firm_name + bar_number + firm_address
**Response:** File download (.docx)

### GET /api/case-packet/{lead_id}

Generate an HTML case packet for GOLD/SILVER leads.

**Auth:** JWT Bearer token + verified attorney
**Response:** HTML content

---

## Admin Endpoints

All admin endpoints require the `x-verifuse-api-key` header.

```bash
curl -H "x-verifuse-api-key: <your-key>" https://verifuse.tech/api/admin/leads
```

### GET /api/admin/leads

Raw lead data (no obfuscation). Query param: `limit` (default 100, max 1000).

### GET /api/admin/quarantine

All quarantined leads.

### GET /api/admin/users

All user accounts (no password hashes).

---

## CORS

Allowed origins:
- `https://verifuse.tech`
- `https://www.verifuse.tech`

Allowed methods: `GET`, `POST`, `OPTIONS`
Allowed headers: `Authorization`, `Content-Type`, `x-verifuse-api-key`

---

## Error Codes

| Code | Meaning |
|------|---------|
| 400 | Bad request (invalid parameters or body) |
| 401 | Authentication required or token invalid/expired |
| 402 | Insufficient credits |
| 403 | Forbidden (wrong tier, not verified attorney, invalid API key) |
| 404 | Resource not found |
| 410 | Lead expired (claim deadline passed) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service unavailable (e.g., Stripe not configured) |
