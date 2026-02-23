# VeriFuse Security

## RBAC Levels

| Role | Access |
|---|---|
| `public` | Preview leads (no PII), sample dossier |
| Authenticated user | Full lead list (case numbers masked until unlock), unlock with credits |
| `approved_attorney` | Restricted lead access (with disclaimer), evidence documents, equity data |
| `admin` | All of the above + simulate header, admin endpoints |

Role is stored in `users.role` and checked on every protected endpoint. Role is NOT in the JWT — it is always read fresh from the database to ensure revocation takes effect immediately.

## BFCache Hardening

All authenticated API routes return:
```
Cache-Control: no-store, no-cache, must-revalidate, proxy-revalidate
Pragma: no-cache
Expires: 0
```

Routes in scope: `/api/auth/*`, `/api/leads`, `/api/leads/*`, `/api/lead/*`, `/api/dossier/*`, `/api/assets/*`, `/api/evidence/*`.

Routes explicitly excluded: `/api/health`, `/api/public-config`, `/api/webhooks/*`.

Frontend: logout clears `localStorage` (`vf_token`, `vf_is_admin`, `vf_simulate`) and `sessionStorage`, navigates with `replace: true`. `pageshow` listener revalidates auth on BFCache restore.

## Evidence Download Path Hardening

Vault files are served only if:
1. User is authenticated + has `approved_attorney` or `admin` role
2. `evidence_documents.file_path` is fetched from DB (not user-supplied)
3. Resolved path is inside `VAULT_ROOT` via `os.path.commonpath()` check (NOT `startswith()` alone)
4. File exists on disk before streaming

```python
resolved = Path(row["file_path"]).resolve()
vault_resolved = VAULT_ROOT.resolve()
is_safe = (os.path.commonpath([str(resolved), str(vault_resolved)]) == str(vault_resolved))
```

## Stripe Downgrade Guard

Webhook `subscription_update` events are guarded by a tier rank check:

```
TIER_RANK = {"scout": 0, "operator": 1, "sovereign": 2}
```

A Stripe event cannot downgrade a user's tier — only upgrades are applied. Attempted downgrades are logged to `audit_log` and silently blocked.

## Webhook Integrity

All Stripe webhooks are verified with `stripe.Webhook.construct_event()` using `STRIPE_WEBHOOK_SECRET`. Events without a valid signature return 400 without processing.

## Secrets Management

Required secrets (never committed to source):
- `VERIFUSE_JWT_SECRET` — JWT signing key
- `STRIPE_SECRET_KEY` — Stripe API key
- `STRIPE_WEBHOOK_SECRET` — Stripe webhook signature secret
- `GOOGLE_APPLICATION_CREDENTIALS` — Path to GCP service account JSON
- `GOVSOFT_*_URL` — GovSoft county base URLs

Store in `/etc/verifuse/verifuse.env` (mode 0600, owned by `verifuse` service user).

## Rate Limiting

Endpoints use `slowapi` limiter with per-IP limits:
- Evidence list: 60/minute
- Evidence download: 30/minute
- Unlock: enforced separately via credit debit
