import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { API_BASE } from "../lib/api";

// ── Canonical pricing (mirrors verifuse_v2/server/pricing.py) ─────────────────

const TIERS = [
  {
    key: "associate",
    name: "Investigator",
    price: 199,
    credits: 30,
    rollover: "30-day rollover (max 45 banked)",
    features: [
      "30 unlocks/month",
      "Foreclosure surplus (§ 38-38-111)",
      "Tax Deed surplus (§ 39-12-111)",
      "GOLD/SILVER/BRONZE grades",
      "Lead unlock (1 credit each)",
      "Evidence document + dossier access",
      "Deadline alert emails",
      "Unlimited devices · 30-day credit rollover",
    ],
    cta: "Start Investigator",
    highlight: false,
  },
  {
    key: "partner",
    name: "Partner",
    price: 399,
    credits: 75,
    rollover: "60-day rollover (max 113 banked)",
    features: [
      "75 unlocks/month",
      "All 4 surplus streams",
      "Foreclosure · Tax Deed · Tax Lien · Unclaimed Property",
      "Court Filing Packet (3 credits/case)",
      "Bulk CSV export",
      "Priority data updates · unlimited devices",
      "60-day credit rollover",
    ],
    cta: "Start Partner",
    highlight: true,
  },
  {
    key: "sovereign",
    name: "Enterprise",
    price: 899,
    credits: 200,
    rollover: "90-day rollover (max 300 banked)",
    features: [
      "200 unlocks/month",
      "All 4 surplus streams + estate cases",
      "Full REST API access",
      "White-label dossier exports",
      "Skip Trace included (10/mo)",
      "County coverage reports · unlimited devices",
      "90-day credit rollover",
    ],
    cta: "Start Enterprise",
    highlight: false,
  },
];

const ONE_TIME = [
  {
    key: "starter",
    name: "Lead Unlock Bundle",
    price: 49,
    credits: 10,
    expiry: "90 days",
    description: "10 lead unlocks — no subscription required. Ideal for a single investigation or trial run.",
    endpoint: "/api/billing/starter",
  },
  {
    key: "investigation",
    name: "Investigation Pack",
    price: 99,
    credits: 25,
    expiry: "90 days",
    description: "25 unlocks — deep research across multiple cases without a monthly commitment.",
    endpoint: "/api/billing/one-time",
  },
  {
    key: "skip_trace",
    name: "Skip Trace",
    price: 29,
    credits: 1,
    expiry: "per record",
    description: "Current owner address + phone lookup via multi-source cross-reference. One record per purchase.",
    endpoint: "/api/billing/one-time",
  },
  {
    key: "filing_pack",
    name: "Court Filing Packet",
    price: 149,
    credits: 3,
    expiry: "per case",
    description: "Complete court-ready document set: Motion for Surplus Release + Notice to Lienholders + Affidavit of Ownership + Proof of Claim.",
    endpoint: "/api/billing/one-time",
  },
  {
    key: "premium_dossier",
    name: "Premium Dossier",
    price: 79,
    credits: 5,
    expiry: "per case",
    description: "Filing Packet + heir notification letter template + title stack analysis (§ 38-38-111 compliant).",
    endpoint: "/api/billing/one-time",
  },
];

const FEATURE_MATRIX = [
  { feature: "Unlocks per month",         associate: "30",    partner: "75",    sovereign: "200" },
  { feature: "GOLD leads access",         associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "PRE-SALE pipeline",         associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "Foreclosure overbid",       associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "Tax Deed surplus",          associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "Tax Lien surplus",          associate: "—",     partner: "✓",     sovereign: "✓" },
  { feature: "Unclaimed Property",        associate: "—",     partner: "✓",     sovereign: "✓" },
  { feature: "Evidence documents",        associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "Deadline alert emails",     associate: "✓",     partner: "✓",     sovereign: "✓" },
  { feature: "Court Filing Packet",       associate: "3 CR",  partner: "3 CR",  sovereign: "3 CR" },
  { feature: "Bulk CSV export",           associate: "—",     partner: "✓",     sovereign: "✓" },
  { feature: "Priority data updates",     associate: "—",     partner: "✓",     sovereign: "✓" },
  { feature: "Skip Trace (per record)",   associate: "$29",   partner: "$29",   sovereign: "10/mo" },
  { feature: "Full REST API access",      associate: "—",     partner: "—",     sovereign: "✓" },
  { feature: "White-label dossiers",      associate: "—",     partner: "—",     sovereign: "✓" },
  { feature: "Heir notification letters", associate: "—",     partner: "—",     sovereign: "✓" },
  { feature: "County coverage reports",   associate: "—",     partner: "—",     sovereign: "✓" },
  { feature: "Devices",                   associate: "Unlimited", partner: "Unlimited", sovereign: "Unlimited" },
];

const CREDIT_COSTS = [
  {
    action: "Lead Unlock",
    credits: 1,
    badge: "STANDARD",
    badgeColor: "#22c55e",
    description: "Full case details: owner name, mailing address, property address, case number, surplus math, and all evidence documents",
    value: "Everything you need to contact the owner and assess the case",
  },
  {
    action: "Tax Lien Report",
    credits: 2,
    badge: "STREAM",
    badgeColor: "#3b82f6",
    description: "Full tax lien surplus feed for 1 county under C.R.S. § 39-11-151 — including owner data and claim deadlines",
    value: "Separate stream from foreclosure overbids",
  },
  {
    action: "Court Filing Packet",
    credits: 3,
    badge: "PREMIUM",
    badgeColor: "#f59e0b",
    description: "Generate the complete 6-document court packet: Motion for Surplus Release, Notice to Lienholders, Affidavit, Certificate of Service, Property Exhibit, Evidence Exhibit",
    value: "Court-ready ZIP — Colorado district court format",
  },
  {
    action: "READY TO FILE Unlock",
    credits: 3,
    badge: "RTF",
    badgeColor: "#22c55e",
    description: "Unlock a fully verified READY_TO_FILE lead. Includes all owner data + court filing packet in one step — these leads have lien search complete and surplus confirmed.",
    value: "All-in-one: owner data + complete filing packet",
  },
  {
    action: "Premium Dossier",
    credits: 5,
    badge: "ELITE",
    badgeColor: "#a78bfa",
    description: "Court Filing Packet + full title stack analysis + heir notification letter template (for estate cases)",
    value: "Highest-yield cases with complex ownership chains",
  },
];

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── Main component ─────────────────────────────────────────────────────────────

// ── Founding Attorney Section ─────────────────────────────────────────────────

function FoundingAttorneySection() {
  const [status, setStatus] = useState<{ slots_claimed: number; slots_total: number; is_open: boolean } | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/founding/status`)
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setStatus(d))
      .catch(() => {});
  }, []);

  const claimed = status?.slots_claimed ?? 0;
  const total = status?.slots_total ?? 10;
  const isOpen = status?.is_open !== false;
  const remaining = total - claimed;

  return (
    <div style={{ background: "rgba(245,158,11,0.06)", border: "1px solid #78350f", borderRadius: 10, padding: "28px 32px", marginBottom: 48 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 8 }}>
        <div style={{ fontSize: "0.72em", letterSpacing: "0.1em", color: "#f59e0b" }}>
          FOUNDING ATTORNEY PROGRAM — {isOpen ? `${remaining} OF ${total} SPOTS REMAINING` : "ALL SPOTS CLAIMED"}
        </div>
        {status && (
          <div style={{ display: "flex", gap: 4 }}>
            {Array.from({ length: total }).map((_, i) => (
              <div key={i} style={{
                width: 12, height: 12, borderRadius: 2,
                background: i < claimed ? "#f59e0b" : "#374151",
              }} />
            ))}
          </div>
        )}
      </div>
      <h3 style={{ margin: "0 0 10px", fontSize: "1.1em" }}>
        {isOpen ? "Lock In Founder Pricing — Forever" : "Founding Program Closed — Prices Have Increased"}
      </h3>
      <ul style={{ margin: "0 0 16px", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
        <li style={{ fontSize: "0.85em", display: "flex", gap: 8 }}>
          <span style={{ color: "#f59e0b" }}>★</span>
          <span>"Founding Attorney" badge — current prices ($199/$399/$899) locked forever</span>
        </li>
        <li style={{ fontSize: "0.85em", display: "flex", gap: 8 }}>
          <span style={{ color: "#f59e0b" }}>★</span>
          <span>5 bonus credits added to your account upon registration</span>
        </li>
        <li style={{ fontSize: "0.85em", display: "flex", gap: 8 }}>
          <span style={{ color: "#f59e0b" }}>★</span>
          <span>After first {total} attorneys, prices increase 30% — to $259/$519/$1,169/mo</span>
        </li>
      </ul>
      {isOpen ? (
        <>
          <Link to="/register" style={{
            display: "inline-block", padding: "10px 24px", background: "#f59e0b",
            color: "#0a0f1a", textDecoration: "none", borderRadius: 6, fontSize: "0.85em",
            fontWeight: 700, letterSpacing: "0.06em", fontFamily: "inherit",
          }}>
            CLAIM FOUNDING ATTORNEY STATUS — LOCK IN $199/$399/$899 FOREVER →
          </Link>
          <div style={{ marginTop: 10, fontSize: "0.75em", opacity: 0.5 }}>
            After first {total} attorneys, pricing increases to $259/$519/$1,169. Current members locked in.
          </div>
        </>
      ) : (
        <div style={{ fontSize: "0.85em", color: "#f59e0b", opacity: 0.7 }}>
          Founding spots filled. Subscribe above to access all surplus intelligence features.
        </div>
      )}
    </div>
  );
}

// Annual pricing: ~10% discount vs monthly (2 months free)
const ANNUAL_PRICES: Record<string, { price: number; savings: number }> = {
  associate: { price: 2149, savings: 239 },   // Investigator annual ($199×12 - 10%)
  partner:   { price: 4309, savings: 479 },   // Partner annual ($399×12 - 10%)
  sovereign: { price: 9709, savings: 1079 },  // Enterprise annual ($899×12 - 10%)
};

export default function Pricing() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [billing, setBilling] = useState<"monthly" | "annual">("monthly");
  const [stripeReady, setStripeReady] = useState(true); // optimistic — only disable if API says unconfigured
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/public-config`)
      .then((r) => r.json())
      .then((d) => {
        if (d.stripe_configured === false && !d.stripe_publishable_key) setStripeReady(false);
      })
      .catch(() => { /* keep optimistic true — don't block buttons on network error */ });
  }, []);

  async function startCheckout(tier: string) {
    if (!user) {
      navigate("/register");
      return;
    }
    if (!stripeReady) {
      setCheckoutError("Billing is being configured. Contact us at support@verifuse.tech.");
      return;
    }
    setCheckoutLoading(tier);
    setCheckoutError("");
    try {
      const res = await fetch(`${API_BASE}/api/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ tier, billing_period: billing }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Checkout failed");
      window.location.href = data.checkout_url;
    } catch (e: unknown) {
      setCheckoutError(e instanceof Error ? e.message : "Checkout failed");
      setCheckoutLoading(null);
    }
  }

  async function startOneTime(key: string, endpoint: string) {
    if (!user) {
      navigate("/register");
      return;
    }
    if (!stripeReady) {
      setCheckoutError("Billing is being configured. Contact us at support@verifuse.tech.");
      return;
    }
    setCheckoutLoading(key);
    setCheckoutError("");
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ sku: key }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Checkout failed");
      window.location.href = data.checkout_url;
    } catch (e: unknown) {
      setCheckoutError(e instanceof Error ? e.message : "Checkout failed");
      setCheckoutLoading(null);
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0a0f1a", color: "#e5e7eb", fontFamily: "var(--font-mono, monospace)" }}>
      {/* Header */}
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 32px", borderBottom: "1px solid #1f2937", position: "sticky", top: 0, background: "#0a0f1a", zIndex: 100 }}>
        <Link to="/" style={{ textDecoration: "none", color: "#e5e7eb", fontSize: "1em", fontWeight: 700, letterSpacing: "0.08em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// INTELLIGENCE</span>
        </Link>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {user ? (
            <Link to="/dashboard" style={{ color: "#22c55e", textDecoration: "none", fontSize: "0.85em" }}>
              → DASHBOARD
            </Link>
          ) : (
            <>
              <Link to="/login" style={{ color: "#9ca3af", textDecoration: "none", fontSize: "0.85em" }}>SIGN IN</Link>
              <Link to="/register" style={{
                color: "#0a0f1a", background: "#22c55e", textDecoration: "none",
                fontSize: "0.85em", padding: "7px 16px", borderRadius: 4, fontWeight: 700,
              }}>START TRIAL</Link>
            </>
          )}
        </div>
      </header>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "48px 24px" }}>

        {/* Hero */}
        <div style={{ textAlign: "center", marginBottom: 60 }}>
          <div style={{ fontSize: "0.75em", letterSpacing: "0.15em", color: "#22c55e", marginBottom: 12 }}>
            COLORADO § 38-38-111 INTELLIGENCE PLATFORM
          </div>
          <h1 style={{ fontSize: "2.2em", fontWeight: 700, margin: "0 0 16px", letterSpacing: "-0.02em" }}>
            Pricing for Attorneys
          </h1>
          <p style={{ fontSize: "0.95em", opacity: 0.6, maxWidth: 560, margin: "0 auto 24px" }}>
            Credits never expire within your rollover window.
            One unlock = one full lead + all evidence documents.
            No per-document fees. No hidden costs.
          </p>
          {!stripeReady && (
            <div style={{ display: "inline-block", background: "#1c2534", border: "1px solid #374151", borderRadius: 6, padding: "8px 18px", fontSize: "0.8em", color: "#f59e0b" }}>
              ⚠ Billing configuration in progress — contact support@verifuse.tech to subscribe
            </div>
          )}

          {/* Billing toggle */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 12, marginTop: 20 }}>
            <button
              onClick={() => setBilling("monthly")}
              style={{
                padding: "7px 20px", borderRadius: 6, cursor: "pointer", fontSize: "0.85em", fontWeight: 600,
                background: billing === "monthly" ? "#22c55e" : "transparent",
                color: billing === "monthly" ? "#0a0f1a" : "#9ca3af",
                border: billing === "monthly" ? "none" : "1px solid #374151",
                fontFamily: "inherit",
              }}>
              MONTHLY
            </button>
            <button
              onClick={() => setBilling("annual")}
              style={{
                padding: "7px 20px", borderRadius: 6, cursor: "pointer", fontSize: "0.85em", fontWeight: 600,
                background: billing === "annual" ? "#22c55e" : "transparent",
                color: billing === "annual" ? "#0a0f1a" : "#9ca3af",
                border: billing === "annual" ? "none" : "1px solid #374151",
                fontFamily: "inherit",
                position: "relative",
              }}>
              ANNUAL
              <span style={{
                position: "absolute", top: -10, right: -10,
                background: "#f59e0b", color: "#0a0f1a", fontSize: "0.65em",
                padding: "2px 6px", borderRadius: 10, fontWeight: 700, whiteSpace: "nowrap",
              }}>SAVE 10%</span>
            </button>
          </div>
        </div>

        {/* Subscription Tiers */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 20, marginBottom: 60 }}>
          {TIERS.map((tier) => (
            <div key={tier.key} style={{
              border: `1px solid ${tier.highlight ? "#22c55e" : "#374151"}`,
              borderRadius: 10,
              padding: "28px 24px",
              background: tier.highlight ? "rgba(34,197,94,0.04)" : "#0d1117",
              position: "relative",
            }}>
              {tier.highlight && (
                <div style={{
                  position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)",
                  background: "#22c55e", color: "#0a0f1a", fontSize: "0.7em", fontWeight: 700,
                  padding: "3px 14px", borderRadius: 20, letterSpacing: "0.1em", whiteSpace: "nowrap",
                }}>
                  MOST POPULAR
                </div>
              )}
              <div style={{ fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.6, marginBottom: 8 }}>
                {tier.name.toUpperCase()}
              </div>
              <div style={{ marginBottom: 4 }}>
                {billing === "annual" && ANNUAL_PRICES[tier.key] ? (
                  <>
                    <span style={{ fontSize: "2.2em", fontWeight: 700 }}>${ANNUAL_PRICES[tier.key].price.toLocaleString()}</span>
                    <span style={{ opacity: 0.5, fontSize: "0.85em" }}>/year</span>
                    <span style={{ marginLeft: 10, fontSize: "0.78em", color: "#f59e0b", fontWeight: 600 }}>
                      save ${ANNUAL_PRICES[tier.key].savings}
                    </span>
                  </>
                ) : (
                  <>
                    <span style={{ fontSize: "2.2em", fontWeight: 700 }}>${tier.price}</span>
                    <span style={{ opacity: 0.5, fontSize: "0.85em" }}>/month</span>
                  </>
                )}
              </div>
              <div style={{ fontSize: "0.8em", color: "#22c55e", marginBottom: 20 }}>
                {tier.credits} credits/month · {tier.rollover}
              </div>
              <ul style={{ margin: "0 0 24px", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
                {tier.features.map((f) => (
                  <li key={f} style={{ fontSize: "0.82em", display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <span style={{ color: "#22c55e", flexShrink: 0, marginTop: 1 }}>✓</span>
                    <span style={{ opacity: 0.8 }}>{f}</span>
                  </li>
                ))}
              </ul>
              <button
                onClick={() => startCheckout(tier.key)}
                disabled={checkoutLoading === tier.key}
                style={{
                  width: "100%", padding: "11px 0", borderRadius: 6, cursor: "pointer",
                  background: tier.highlight ? "#22c55e" : "transparent",
                  color: tier.highlight ? "#0a0f1a" : "#22c55e",
                  border: tier.highlight ? "none" : "1px solid #22c55e",
                  fontSize: "0.85em", fontWeight: 700, letterSpacing: "0.06em",
                  fontFamily: "inherit",
                  opacity: checkoutLoading && checkoutLoading !== tier.key ? 0.5 : 1,
                } as React.CSSProperties}
              >
                {checkoutLoading === tier.key ? "REDIRECTING..." : tier.cta.toUpperCase()}
              </button>
            </div>
          ))}
        </div>

        {checkoutError && (
          <p style={{ color: "#ef4444", textAlign: "center", fontSize: "0.85em", marginBottom: 32 }}>
            {checkoutError}
          </p>
        )}

        {/* Credit Cost Table */}
        <div style={{ marginBottom: 60 }}>
          <div style={{ textAlign: "center", marginBottom: 28 }}>
            <div style={{ fontSize: "0.68em", letterSpacing: "0.15em", color: "#22c55e", marginBottom: 8 }}>THE CREDIT ECONOMY</div>
            <h2 style={{ margin: "0 0 10px", fontSize: "1.3em", fontWeight: 700 }}>One credit, one action.</h2>
            <p style={{ color: "#94a3b8", fontSize: "0.85em", maxWidth: 500, margin: "0 auto" }}>
              Credits are the currency for lead unlocks and filing packets.
              Skip Trace is a separate $29 add-on (Enterprise gets 10/month included).
              Credits roll over within your tier's window. Cancel anytime.
            </p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
            {CREDIT_COSTS.map((c) => (
              <div key={c.action} style={{
                background: "#0d1117",
                border: `1px solid ${(c as any).badgeColor}22`,
                borderLeft: `3px solid ${(c as any).badgeColor}`,
                borderRadius: 8, padding: "16px 18px",
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      background: (c as any).badgeColor, color: "#0a0f1a",
                      width: 36, height: 36, borderRadius: 6,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontWeight: 700, fontSize: "1.1em", fontFamily: "monospace", flexShrink: 0,
                    }}>
                      {c.credits}
                    </div>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: "0.85em", color: "#e5e7eb" }}>{c.action}</div>
                      <div style={{ fontSize: "0.65em", color: "#4b5563" }}>{c.credits === 1 ? "1 credit" : `${c.credits} credits`}</div>
                    </div>
                  </div>
                  <span style={{
                    background: `${(c as any).badgeColor}18`, color: (c as any).badgeColor,
                    padding: "2px 8px", borderRadius: 4, fontSize: "0.62em", fontWeight: 700,
                    letterSpacing: "0.08em", fontFamily: "monospace",
                  }}>
                    {(c as any).badge}
                  </span>
                </div>
                <p style={{ margin: "0 0 6px", fontSize: "0.78em", color: "#6b7280", lineHeight: 1.45 }}>{c.description}</p>
                <div style={{ fontSize: "0.72em", color: (c as any).badgeColor, display: "flex", gap: 5, alignItems: "center" }}>
                  <span style={{ opacity: 0.6 }}>→</span>
                  <span>{(c as any).value}</span>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, textAlign: "center", fontSize: "0.78em", color: "#4b5563" }}>
            Credits roll over · Investigator: 30-day rollover · Partner: 60-day · Enterprise: 90-day
          </div>
        </div>

        {/* Feature Comparison Matrix */}
        <div style={{ background: "#0d1117", border: "1px solid #374151", borderRadius: 10, padding: "24px", marginBottom: 60 }}>
          <h3 style={{ fontSize: "0.8em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 16, marginTop: 0 }}>
            FEATURE COMPARISON
          </h3>
          <table className="feature-matrix" style={{ fontFamily: "inherit" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", minWidth: 200 }}>FEATURE</th>
                <th style={{ textAlign: "center" }}>INVESTIGATOR</th>
                <th style={{ textAlign: "center" }}>PARTNER</th>
                <th className="col-sovereign" style={{ textAlign: "center" }}>ENTERPRISE</th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_MATRIX.map((row) => (
                <tr key={row.feature}>
                  <td>{row.feature}</td>
                  <td style={{ textAlign: "center", opacity: row.associate === "—" ? 0.3 : 1 }}>{row.associate}</td>
                  <td style={{ textAlign: "center", opacity: row.partner === "—" ? 0.3 : 1 }}>{row.partner}</td>
                  <td className="col-sovereign" style={{ textAlign: "center" }}>{row.sovereign}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* One-Time Packs */}
        <div style={{ marginBottom: 60 }}>
          <div style={{ textAlign: "center", marginBottom: 28 }}>
            <h2 style={{ fontSize: "1.2em", fontWeight: 700, margin: "0 0 8px" }}>One-Time Packs</h2>
            <p style={{ opacity: 0.5, fontSize: "0.85em", margin: 0 }}>
              No subscription required. Credits expire as noted.
            </p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 16 }}>
            {ONE_TIME.map((p) => (
              <div key={p.key} style={{ border: "1px solid #374151", borderRadius: 8, padding: "20px", background: "#0d1117" }}>
                <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 6 }}>
                  {p.expiry.toUpperCase()}
                </div>
                <div style={{ fontWeight: 700, fontSize: "1.05em", marginBottom: 4 }}>{p.name}</div>
                <div style={{ color: "#22c55e", fontWeight: 700, fontSize: "1.3em", marginBottom: 8 }}>
                  ${p.price}
                  {p.credits <= 10 ? <span style={{ fontSize: "0.65em", opacity: 0.6, marginLeft: 4, color: "#e5e7eb" }}>{p.credits} cr</span> : null}
                </div>
                <p style={{ margin: "0 0 16px", fontSize: "0.8em", opacity: 0.6, lineHeight: 1.5 }}>{p.description}</p>
                <button
                  onClick={() => startOneTime(p.key, p.endpoint)}
                  disabled={!!checkoutLoading}
                  style={{
                    width: "100%", padding: "8px 0", borderRadius: 5, cursor: "pointer",
                    background: "transparent", border: "1px solid #374151",
                    color: "#e5e7eb", fontSize: "0.8em", fontFamily: "inherit",
                    opacity: checkoutLoading ? 0.5 : 1,
                  } as React.CSSProperties}
                >
                  {checkoutLoading === p.key ? "REDIRECTING..." : `BUY ${p.name.toUpperCase()}`}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Enterprise */}
        <div style={{ background: "#0d1117", border: "1px solid #374151", borderRadius: 10, padding: "28px 32px", marginBottom: 60 }}>
          <div style={{ display: "flex", gap: 32, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: "0.72em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8 }}>ENTERPRISE / WHITE-LABEL</div>
              <h3 style={{ margin: "0 0 8px", fontSize: "1.1em" }}>Firm License — $1,999/mo</h3>
              <p style={{ margin: "0 0 8px", fontSize: "0.82em", opacity: 0.6 }}>
                500 credits · Full REST API · Co-branded dossiers · Unlimited seats · All 4 surplus streams · Priority support
              </p>
              <p style={{ margin: 0, fontSize: "0.8em", opacity: 0.5 }}>
                County Raw Feed add-on: $499/mo/county — raw scraped data via API
              </p>
            </div>
            <a
              href="mailto:support@verifuse.tech?subject=Enterprise Inquiry"
              style={{
                display: "inline-block", padding: "11px 24px", border: "1px solid #22c55e",
                color: "#22c55e", textDecoration: "none", borderRadius: 6, fontSize: "0.85em",
                fontFamily: "inherit", fontWeight: 700, letterSpacing: "0.06em", whiteSpace: "nowrap",
              }}
            >
              CONTACT US
            </a>
          </div>
        </div>

        {/* Founding Attorney Program */}
        <FoundingAttorneySection />

        {/* FAQ Strip */}
        <div style={{ textAlign: "center", fontSize: "0.82em", opacity: 0.5, lineHeight: 2 }}>
          <p style={{ margin: 0 }}>
            Credits roll over within your rollover window. No contracts. Cancel anytime.
          </p>
          <p style={{ margin: 0 }}>
            All surplus data covers Colorado counties (C.R.S. § 38-38-111, § 38-13-1304, § 39-11-151).
            HB25-1224 compliant — 10% attorney fee cap tracked.
          </p>
          <p style={{ margin: 0 }}>
            Questions? <a href="mailto:support@verifuse.tech" style={{ color: "#22c55e" }}>support@verifuse.tech</a>
          </p>
        </div>

      </div>
    </div>
  );
}
