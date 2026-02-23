# Unit Economics

Subscription tier pricing, cost analysis, and break-even calculations for VeriFuse V2.

---

## Tier Pricing

| Tier | Monthly Price | Credits/Month | Price per Credit |
|------|--------------|---------------|-----------------|
| **Recon** | $199 | 5 | $39.80 |
| **Operator** | $399 | 25 | $15.96 |
| **Sovereign** | $699 | 100 | $6.99 |

Credits do not roll over. Each credit unlocks one lead (reveals PII).

---

## Cost Structure

### Fixed Costs (Monthly)

| Item | Cost | Notes |
|------|------|-------|
| VPS Hosting | ~$20-50/mo | Cloud VM (4 vCPU, 8 GB RAM) |
| Domain + DNS | ~$1/mo | verifuse.tech via Cloudflare |
| SSL/TLS | $0 | Caddy auto-provisions Let's Encrypt |
| Stripe Fees | 2.9% + $0.30 per transaction | Per-subscription charge |

### Variable Costs (Per Lead)

| Item | Cost | Notes |
|------|------|-------|
| Vertex AI (optional) | ~$0.01-0.05 per PDF | Only for non-standard formats; daily cap of 50 |
| Bandwidth | Negligible | PDFs are small, API responses are JSON |
| Storage | Negligible | SQLite + PDFs, < 1 GB total |

### Infrastructure Cost Estimate

| Scenario | Monthly Infra Cost |
|----------|--------------------|
| 0-50 subscribers | ~$50 |
| 50-200 subscribers | ~$100 (may need larger VM) |
| 200+ subscribers | ~$200 (dedicated DB server, CDN) |

---

## Revenue Scenarios

### Scenario A: Early Stage (10 Subscribers)

| Tier | Count | Monthly Revenue |
|------|-------|----------------|
| Recon | 5 | $995 |
| Operator | 3 | $1,197 |
| Sovereign | 2 | $1,398 |
| **Total** | **10** | **$3,590** |

Less Stripe fees (~3%): **$3,482**
Less infrastructure: **$3,432**
**Net: ~$3,432/mo**

### Scenario B: Growth (50 Subscribers)

| Tier | Count | Monthly Revenue |
|------|-------|----------------|
| Recon | 25 | $4,975 |
| Operator | 15 | $5,985 |
| Sovereign | 10 | $6,990 |
| **Total** | **50** | **$17,950** |

Less Stripe fees (~3%): **$17,412**
Less infrastructure: **$17,312**
**Net: ~$17,312/mo**

### Scenario C: Scale (200 Subscribers)

| Tier | Count | Monthly Revenue |
|------|-------|----------------|
| Recon | 100 | $19,900 |
| Operator | 60 | $23,940 |
| Sovereign | 40 | $27,960 |
| **Total** | **200** | **$71,800** |

Less Stripe fees (~3%): **$69,646**
Less infrastructure: **$69,446**
**Net: ~$69,446/mo**

> **PROJECTION -- TBD WITH CITATIONS**
> Subscriber counts and tier mix distribution are projections. Actual distribution depends on market testing and customer acquisition.

---

## Break-Even Analysis

### Monthly Fixed Costs

| Item | Cost |
|------|------|
| Hosting | $50 |
| Monitoring/tools | $20 |
| Domain | $1 |
| **Total Fixed** | **$71/mo** |

### Break-Even Point

| Scenario | Subscribers Needed |
|----------|-------------------|
| All Recon ($199) | 1 subscriber (revenue > fixed costs) |
| Mixed (avg $350/subscriber) | 1 subscriber |
| After including labor | Depends on founder salary expectations |

The platform has extremely low marginal costs per subscriber. Infrastructure costs scale slowly: the same VPS handles 1 or 100 subscribers with identical performance (SQLite handles millions of reads without issue).

---

## Credit Economics

### Value Per Credit to the Subscriber

An attorney recovering a surplus fund typically earns a contingency fee of 25-33% of the surplus amount.

| Lead Grade | Avg Surplus | Attorney Fee (30%) | Credit Cost (Recon) | ROI |
|------------|------------|-------------------|--------------------|----|
| GOLD | $50,000 | $15,000 | $39.80 | 377x |
| SILVER | $15,000 | $4,500 | $39.80 | 113x |
| BRONZE | $3,000 | $900 | $39.80 | 23x |

Even at the most expensive tier (Recon at $39.80/credit), a single GOLD lead unlock can generate $15,000+ in attorney fees, creating an extreme ROI for subscribers.

### Credit Utilization Assumption

> **PROJECTION -- TBD WITH CITATIONS**
>
> Assumptions about credit utilization rates (what % of credits subscribers actually use each month) require validation from subscriber usage data.

---

## Customer Acquisition Cost (CAC)

> **PROJECTION -- TBD WITH CITATIONS**
>
> CAC estimates require data from actual marketing campaigns. Potential channels:
> - Direct attorney outreach
> - Colorado Bar Association advertising
> - Legal industry conferences
> - Content marketing (surplus recovery guides)
> - Google Ads for "foreclosure surplus" keywords

---

## Lifetime Value (LTV)

> **PROJECTION -- TBD WITH CITATIONS**
>
> LTV depends on churn rate, which is unknown until the product has active subscribers.

Illustrative example (assuming 12-month average retention):

| Tier | Monthly | 12-Month LTV |
|------|---------|-------------|
| Recon | $199 | $2,388 |
| Operator | $399 | $4,788 |
| Sovereign | $699 | $8,388 |

---

## Pricing Rationale

### Why $199 for Recon?

- Entry-level price for solo practitioners and skip tracers
- 5 credits/month is enough to evaluate the platform
- Low enough to be expensed as a business tool
- High enough to deter tire-kickers and protect data exclusivity

### Why $399 for Operator?

- Sweet spot for small firms handling 10-30 surplus cases/year
- 25 credits provides meaningful monthly deal flow
- Unlocks RESTRICTED leads (with attorney verification)
- Price-per-credit drops to $15.96, incentivizing upgrade from Recon

### Why $699 for Sovereign?

- Enterprise-grade for firms specializing in surplus recovery
- 100 credits/month supports high-volume operations
- Price-per-credit drops to $6.99
- Priority support and maximum API access limits

---

## Expansion Revenue Opportunities

> **PROJECTION -- TBD WITH CITATIONS**
>
> These are potential future revenue streams, not current offerings:

1. **Multi-State Expansion:** Replicate the Colorado model in Texas, California, Florida
2. **Dossier Add-On:** Premium per-download fee for comprehensive case packets
3. **API Access Tier:** Machine-to-machine API for integration with law firm CRMs
4. **Data Licensing:** Bulk data exports for institutional buyers
5. **White-Label:** Licensed version for title companies and lenders
