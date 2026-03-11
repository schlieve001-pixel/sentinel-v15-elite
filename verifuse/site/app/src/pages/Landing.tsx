import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats, type Stats } from "../lib/api";

function RoiCalculator() {
  const [cases, setCases] = useState(5);
  const [surplus, setSurplus] = useState(50000);
  const monthly = Math.round(cases * surplus * 0.10);
  const roi = monthly > 0 ? Math.round(monthly / 199) : 0;
  return (
    <div style={{
      background: "#0d1117", border: "1px solid #374151", borderRadius: 10,
      padding: "28px 32px", maxWidth: 580, margin: "0 auto",
    }}>
      <h3 style={{ fontSize: "1em", fontWeight: 700, marginTop: 0, marginBottom: 20, letterSpacing: "0.06em" }}>
        CALCULATE YOUR ROI
      </h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82em", marginBottom: 6, opacity: 0.7 }}>
            <span>Cases per month</span>
            <span style={{ color: "#22c55e", fontWeight: 700 }}>{cases}</span>
          </div>
          <input type="range" min={1} max={20} value={cases}
            onChange={(e) => setCases(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#22c55e" }} />
        </div>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82em", marginBottom: 6, opacity: 0.7 }}>
            <span>Average surplus per case</span>
            <span style={{ color: "#22c55e", fontWeight: 700 }}>${surplus.toLocaleString()}</span>
          </div>
          <input type="range" min={5000} max={500000} step={5000} value={surplus}
            onChange={(e) => setSurplus(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#22c55e" }} />
        </div>
      </div>
      <div style={{ marginTop: 24, padding: "16px", background: "#111827", borderRadius: 8 }}>
        <div style={{ fontSize: "0.78em", opacity: 0.5, marginBottom: 4 }}>ESTIMATED MONTHLY REVENUE</div>
        <div style={{ fontSize: "2em", fontWeight: 700, color: "#22c55e" }}>
          ${monthly.toLocaleString()}/mo
        </div>
        <div style={{ fontSize: "0.82em", opacity: 0.6, marginTop: 4 }}>
          {cases} cases × ${surplus.toLocaleString()} × 10% fee cap (HB25-1224)
        </div>
        {roi > 0 && (
          <div style={{ marginTop: 8, fontSize: "0.85em", color: "#f59e0b", fontWeight: 600 }}>
            VeriFuse Investigator ($199/mo) = {roi}× ROI
          </div>
        )}
      </div>
    </div>
  );
}

const TIERS = [
  {
    name: "Investigator",
    key: "associate",
    price: "$199",
    credits: 30,
    highlight: false,
    features: [
      "30 unlocks/month · 30-day rollover",
      "All 18+ Colorado counties",
      "GOLD/SILVER/BRONZE graded leads",
      "Evidence document access",
      "Deadline alert emails",
      "Foreclosure + Tax Deed streams",
      "Unlimited devices",
    ],
  },
  {
    name: "Partner",
    key: "partner",
    price: "$399",
    credits: 75,
    highlight: true,
    features: [
      "75 unlocks/month · 60-day rollover",
      "All 4 surplus streams",
      "Court Filing Packet (3 credits)",
      "Bulk CSV export",
      "Priority data updates",
      "Skip Trace add-on ($29/record)",
      "Unlimited devices",
    ],
  },
  {
    name: "Enterprise",
    key: "sovereign",
    price: "$899",
    credits: 200,
    highlight: false,
    features: [
      "200 unlocks/month · 90-day rollover",
      "All 4 streams + estate cases",
      "Full REST API access",
      "White-label dossier exports",
      "10 Skip Traces/month included",
      "County coverage reports",
      "Unlimited devices",
    ],
  },
];

export default function Landing() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div className="landing">
      {/* Top Nav */}
      <div className="landing-topnav">
        <span className="topnav-brand">VERIFUSE <span className="text-green">// INTELLIGENCE</span></span>
        <Link to="/login" className="btn-outline-sm">LOGIN</Link>
      </div>

      {/* Hero */}
      <section className="landing-hero">
        <div className="hero-badge">COLORADO FORECLOSURE SURPLUS INTELLIGENCE</div>
        <h1>
          Attorneys miss millions in overbid claims every month.
          <br />
          <span className="text-green">VeriFuse finds them.</span>
        </h1>
        <p className="hero-sub">
          VeriFuse validates them, and hands you the filing package.
          <br />
          Monitors all Colorado county records in real-time — so you file first.
        </p>
        <div className="hero-actions">
          <Link to="/register" className="btn-primary">
            START FREE TRIAL
          </Link>
          <Link to="/preview" className="btn-outline">
            Preview the Vault
          </Link>
          <Link to="/pricing" className="btn-outline">
            View Pricing
          </Link>
        </div>

        {stats && (
          <div className="hero-stats-grid">
            <div className="hero-stat-card">
              <span className="stat-value">{stats.total_leads ?? stats.total_assets}</span>
              <span className="stat-label">Active Pipeline</span>
            </div>
            <div className="hero-stat-card">
              <span className="stat-value">{stats.attorney_ready}</span>
              <span className="stat-label">Attorney-Ready</span>
            </div>
            <div className="hero-stat-card">
              <span className="stat-value" style={{ color: "#f59e0b" }}>{stats.gold_grade}</span>
              <span className="stat-label">GOLD Grade</span>
            </div>
            <div className="hero-stat-card">
              <span className="stat-value" style={{ color: "#10b981" }}>
                ${(stats.total_claimable_surplus / 1_000_000).toFixed(1)}M
              </span>
              <span className="stat-label">Claimable Surplus</span>
            </div>
          </div>
        )}
      </section>

      {/* What You Get */}
      <section className="landing-section landing-value-props">
        <h2>What You Get</h2>
        <div className="steps-grid">
          <div className="step-card">
            <h3>Verified surplus amounts with full source documentation</h3>
          </div>
          <div className="step-card">
            <h3>County, sale date, grade — free to preview</h3>
          </div>
          <div className="step-card">
            <h3>Owner name, address, case number — unlock with 1 credit</h3>
          </div>
          <div className="step-card">
            <h3>Court-ready dossiers, case packets, Rule 7.3 letters</h3>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="landing-section">
        <h2>How It Works</h2>
        <div className="steps-grid">
          <div className="step-card">
            <div className="step-num">01</div>
            <h3>Signal Detection</h3>
            <p>
              Our scrapers monitor Colorado county recorder offices for
              foreclosure filings, trustee sales, and surplus fund deposits.
            </p>
          </div>
          <div className="step-card">
            <div className="step-num">02</div>
            <h3>Intelligence Grading</h3>
            <p>
              Each asset is scored on completeness, surplus amount,
              and statutory deadline. Only GOLD-grade leads reach you.
            </p>
          </div>
          <div className="step-card">
            <div className="step-num">03</div>
            <h3>Unlock + File</h3>
            <p>
              Use a credit to reveal full owner data, download a forensic
              evidence packet with source documents and audit trail, and file
              before the deadline.
            </p>
          </div>
        </div>
      </section>

      {/* ROI Calculator */}
      <section className="landing-section">
        <h2>Calculate Your ROI</h2>
        <p style={{ textAlign: "center", color: "#94a3b8", marginBottom: "2rem" }}>
          Under HB25-1224, Colorado attorneys earn up to 10% on surplus claims.
        </p>
        <RoiCalculator />
      </section>

      {/* Pricing */}
      <section className="landing-section" id="pricing" style={{ paddingBottom: "3rem" }}>
        <div style={{ textAlign: "center", marginBottom: "2.5rem" }}>
          <div style={{ fontSize: "0.72rem", letterSpacing: "0.15em", color: "#22c55e", marginBottom: "0.75rem" }}>
            INTELLIGENCE PLANS
          </div>
          <h2 style={{ margin: "0 0 0.75rem", fontSize: "1.8rem" }}>Pay for results, not software</h2>
          <p style={{ color: "#94a3b8", margin: "0 auto", maxWidth: 480, fontSize: "0.9rem", lineHeight: 1.6 }}>
            One credit = one fully unlocked case with all evidence documents.
            No per-document fees. Credits roll over. Cancel anytime.
          </p>
        </div>

        {/* Tier cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem", marginBottom: "2rem" }}>
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              style={{
                background: tier.highlight ? "rgba(34,197,94,0.04)" : "#0d1117",
                border: `1px solid ${tier.highlight ? "#22c55e" : "#1f2937"}`,
                borderRadius: 10,
                padding: "28px 24px",
                position: "relative",
                display: "flex",
                flexDirection: "column",
              }}
            >
              {tier.highlight && (
                <div style={{
                  position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)",
                  background: "#22c55e", color: "#0a0f1a", fontSize: "0.68rem", fontWeight: 700,
                  padding: "3px 14px", borderRadius: 20, letterSpacing: "0.1em", whiteSpace: "nowrap",
                  fontFamily: "monospace",
                }}>
                  MOST POPULAR
                </div>
              )}
              <div style={{ fontSize: "0.72rem", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8, fontFamily: "monospace" }}>
                {tier.name.toUpperCase()}
              </div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontSize: "2.4rem", fontWeight: 700, fontFamily: "monospace" }}>{tier.price}</span>
                <span style={{ opacity: 0.45, fontSize: "0.85rem", fontFamily: "monospace" }}>/mo</span>
              </div>
              <div style={{ color: "#22c55e", fontSize: "0.78rem", marginBottom: "1.25rem", fontFamily: "monospace" }}>
                {tier.credits} credits/month
              </div>
              <ul style={{ margin: "0 0 1.5rem", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
                {tier.features.map((f) => (
                  <li key={f} style={{ fontSize: "0.82rem", display: "flex", gap: 8, alignItems: "flex-start", color: "#d1d5db" }}>
                    <span style={{ color: "#22c55e", flexShrink: 0, marginTop: 1 }}>✓</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Link
                to="/register"
                style={{
                  display: "block", textAlign: "center",
                  padding: "10px 0", borderRadius: 6,
                  background: tier.highlight ? "#22c55e" : "transparent",
                  color: tier.highlight ? "#0a0f1a" : "#22c55e",
                  border: tier.highlight ? "none" : "1px solid #22c55e",
                  textDecoration: "none", fontSize: "0.82rem", fontWeight: 700,
                  letterSpacing: "0.06em", fontFamily: "monospace",
                }}
              >
                GET STARTED
              </Link>
            </div>
          ))}
        </div>

        {/* Founding attorney callout */}
        <div style={{
          background: "rgba(245,158,11,0.05)", border: "1px solid #78350f",
          borderRadius: 8, padding: "18px 24px", display: "flex",
          alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16,
          marginBottom: "1.5rem",
        }}>
          <div>
            <div style={{ fontSize: "0.68rem", color: "#f59e0b", letterSpacing: "0.1em", fontFamily: "monospace", marginBottom: 4 }}>
              ★ FOUNDING ATTORNEY PROGRAM — LIMITED SPOTS
            </div>
            <div style={{ fontSize: "0.88rem", color: "#e5e7eb" }}>
              First 10 attorneys lock in current pricing forever + 5 bonus credits.
              After that, prices increase 30%.
            </div>
          </div>
          <Link to="/register" style={{
            display: "inline-block", padding: "9px 20px",
            background: "#f59e0b", color: "#0a0f1a",
            textDecoration: "none", borderRadius: 6,
            fontSize: "0.78rem", fontWeight: 700, letterSpacing: "0.06em",
            fontFamily: "monospace", whiteSpace: "nowrap",
          }}>
            CLAIM FOUNDING SPOT →
          </Link>
        </div>

        {/* Bottom trust strip */}
        <div style={{
          display: "flex", justifyContent: "center", gap: "2rem",
          flexWrap: "wrap", color: "#4b5563", fontSize: "0.8rem",
          fontFamily: "monospace",
        }}>
          <span>No contracts · cancel anytime</span>
          <span>Annual billing saves 10%</span>
          <span>🔒 Stripe-secured payments</span>
          <Link to="/pricing" style={{ color: "#22c55e", textDecoration: "none" }}>Full pricing details →</Link>
        </div>
      </section>

      {/* Legal Disclaimer */}
      <section className="landing-disclaimer">
        <h4>IMPORTANT LEGAL NOTICE</h4>
        <p>
          VeriFuse is a data intelligence platform. We provide publicly available
          county record data organized for research purposes. VeriFuse does not
          provide legal advice, does not act as a finder under C.R.S. §
          38-13-1301, and does not claim any interest in surplus funds. Users are
          responsible for ensuring compliance with all applicable state and
          federal regulations, including: the 6-month post-sale contact
          restriction under C.R.S. § 38-38-111(5); the 30-month claim window under C.R.S. § 38-38-111 on
          finder agreements after transfer to the State Treasurer under C.R.S. §
          38-13-1304; and the 10% maximum finder fee cap under C.R.S. §
          38-13-1304(1)(b)(IV) as amended by HB25-1224 (eff. June 4, 2025).
          Use of this platform constitutes acceptance of our{" "}
          <Link to="/terms" style={{ color: "#22c55e" }}>Terms of Service</Link> and{" "}
          <Link to="/privacy" style={{ color: "#22c55e" }}>Privacy Policy</Link>.
        </p>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div>VERIFUSE <span className="text-green">// INTELLIGENCE</span></div>
        <div className="footer-links">
          <Link to="/preview">Preview Vault</Link>
          <Link to="/pricing">Pricing</Link>
          <Link to="/login">Login</Link>
          <Link to="/terms">Terms</Link>
          <Link to="/privacy">Privacy</Link>
        </div>
        <div className="footer-copy">
          © {new Date().getFullYear()} VeriFuse Technologies LLC. All rights reserved.
          Data sourced from public county records.
        </div>
      </footer>
    </div>
  );
}
