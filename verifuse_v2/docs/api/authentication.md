# Authentication

VeriFuse V2 uses three authentication mechanisms for different access levels.

---

## 1. JWT Bearer Tokens (User Auth)

Used for all subscriber-facing endpoints (leads, unlocks, billing, attorney tools).

### How It Works

1. User registers via `POST /api/auth/register` or logs in via `POST /api/auth/login`
2. Server returns a JWT signed with `VERIFUSE_JWT_SECRET`
3. Client includes the token in the `Authorization` header for subsequent requests

### Token Format

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### JWT Payload

```json
{
    "sub": "user-uuid-here",
    "email": "user@example.com",
    "tier": "recon",
    "iat": 1708099200,
    "exp": 1708358400
}
```

### Configuration

| Setting | Value | Location |
|---------|-------|----------|
| Algorithm | HS256 | `verifuse_v2/server/auth.py` |
| Secret | `VERIFUSE_JWT_SECRET` env var | `secrets.env` |
| Expiry | 72 hours (3 days) | `JWT_EXPIRY_HOURS = 72` in `auth.py` |

**Dev mode secret:** `vf2-dev-secret-change-in-production` (hardcoded fallback -- never use in production).

### Password Hashing

Passwords are hashed with bcrypt before storage:

```python
import bcrypt
hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
```

Verification:
```python
bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
```

### Token Verification Flow

```
Client Request
     │
     ▼
Authorization: Bearer <token>
     │
     ▼
jwt.decode(token, VERIFUSE_JWT_SECRET, algorithms=["HS256"])
     │
     ├── ExpiredSignatureError → 401 "Token expired"
     ├── InvalidTokenError → 401 "Invalid token"
     │
     ▼
Lookup user by payload["sub"] in users table
     │
     ├── User not found → 401 "User not found"
     ├── is_active = 0 → 403 "Account deactivated"
     │
     ▼
Return user dict
```

---

## 2. API Key (Machine-to-Machine Auth)

Used for admin endpoints and scraper-to-API communication.

### How It Works

Set the `VERIFUSE_API_KEY` environment variable. Admin endpoints check the `x-verifuse-api-key` header.

```bash
curl -H "x-verifuse-api-key: your-key-here" https://verifuse.tech/api/admin/leads
```

### Protected Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/admin/leads` | Raw lead data (no obfuscation) |
| `GET /api/admin/quarantine` | Quarantined leads |
| `GET /api/admin/users` | All user accounts |
| `POST /api/leads/{id}/attorney-ready` | Mark lead as attorney-ready |

### Dev Mode

If `VERIFUSE_API_KEY` is empty (not set), API key validation is skipped entirely. This allows development without configuring a key, but must never be used in production.

---

## 3. Attorney Verification

A higher-trust level required for accessing RESTRICTED leads and generating legal documents.

### Verification Statuses

| Status | Description |
|--------|-------------|
| `NONE` | Default. No attorney verification attempted. |
| `PENDING` | Verification submitted, awaiting manual review. |
| `VERIFIED` | Bar number confirmed. Full access to RESTRICTED leads and attorney tools. |

### What Attorney Verification Unlocks

| Feature | Required Status |
|---------|----------------|
| Unlock RESTRICTED leads | `VERIFIED` + OPERATOR/SOVEREIGN tier |
| Generate Rule 7.3 letters | `VERIFIED` + firm_name + bar_number + firm_address |
| Download case packets | `VERIFIED` |
| Access restricted unlock endpoint | `VERIFIED` |

### Verification Process

1. User registers with `bar_number` field populated
2. Admin runs the onboard script:
   ```bash
   python -m verifuse_v2.scripts.onboard_attorney
   ```
3. Script verifies the bar number against Colorado Attorney Registration records
4. On approval, updates the user record:
   ```sql
   UPDATE users SET attorney_status = 'VERIFIED', verified_attorney = 1
   WHERE user_id = ?;
   ```

### RESTRICTED Lead Double Gate

When a lead's status is `RESTRICTED` (within 6 calendar months of sale per C.R.S. SS 38-38-111), unlocking requires passing both gates:

```
Gate 1: Attorney Verification
    attorney_status = "VERIFIED"
    │
    ▼
Gate 2: Tier Check
    tier IN ("operator", "sovereign")
    │
    ▼
Gate 3: Credit Deduction
    credits_remaining >= 1
    Atomic deduction via BEGIN IMMEDIATE
    │
    ▼
FullAsset returned with PII
```

If either gate fails, the request returns HTTP 403 with a specific error message indicating which requirement is not met.

---

## Access Control Matrix

| Endpoint | Public | Recon | Operator | Sovereign | Verified Atty | Admin |
|----------|--------|-------|----------|-----------|---------------|-------|
| GET /health | X | X | X | X | X | X |
| GET /api/leads | X | X | X | X | X | X |
| GET /api/lead/{id} | X | X | X | X | X | X |
| GET /api/stats | X | X | X | X | X | X |
| GET /api/counties | X | X | X | X | X | X |
| POST /api/auth/register | X | | | | | |
| POST /api/auth/login | X | | | | | |
| GET /api/auth/me | | X | X | X | X | X |
| POST /api/leads/{id}/unlock | | X | X | X | | X |
| POST /api/unlock-restricted/{id} | | | X* | X* | Required | X |
| GET /api/dossier/{id} | | X | X | X | | X |
| GET /api/dossier/{id}/docx | | X | X | X | | X |
| POST /api/letter/{id} | | | | | Required | X |
| GET /api/case-packet/{id} | | | | | Required | X |
| POST /api/billing/upgrade | | X | X | X | | X |
| POST /api/billing/checkout | | X | X | X | | X |
| GET /api/admin/* | | | | | | API key |

*Restricted unlock requires both verified attorney status AND operator/sovereign tier.

---

## Security Notes

1. **JWT secret rotation:** To rotate the JWT secret, update `VERIFUSE_JWT_SECRET` in `secrets.env` and restart the API. All existing tokens will become invalid.

2. **Rate limiting:** The API uses `slowapi` for per-IP rate limiting. Default: 100 requests/minute. Unlock endpoints are limited to 10/minute.

3. **CORS:** Only `verifuse.tech` and `www.verifuse.tech` are allowed origins. Adjust in `api.py` if deploying to a different domain.

4. **Password requirements:** Minimum 8 characters. No complexity rules enforced by the API (should be enforced on the frontend).

5. **IP logging:** All unlock operations log the client IP address (from `X-Forwarded-For` header) to `lead_unlocks` and `pipeline_events` for audit compliance.
