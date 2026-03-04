import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats, type Stats } from "../lib/api";

function RoiCalculator() {
  const [cases, setCases] = useState(5);
  const [surplus, setSurplus] = useState(50000);
  const monthly = Math.round(cases * surplus * 0.10);
  const roi = monthly > 0 ? Math.round(monthly / 149) : 0;
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
            VeriFuse Associate ($149/mo) = {roi}× ROI
          </div>
        )}
      </div>
    </div>
  );
}

const TIERS = [
  {
    name: "Starter Pack",
    price: "$49",
    credits: 10,
    perCredit: "$4.90",
    oneTime: true,
    features: [
      "10 lead unlocks (one-time)",
      "All Colorado counties",
      "Forensic evidence packet (source documents + audit trail)",
      "C.R.S. § 38-38-111 restriction period tracking",
      "Fail-closed GOLD certification (4-gate verified)",
    ],
  },
  {
    name: "Associate",
    price: "$149",
    credits: 30,
    perCredit: "$4.97",
    features: [
      "30 lead unlocks / month",
      "All Colorado counties",
      "Dossier PDF downloads",
      "Forensic evidence packet (source documents + audit trail)",
      "C.R.S. § 38-38-111 restriction period tracking",
      "Fail-closed GOLD certification (4-gate verified)",
      "Single-session access",
    ],
  },
  {
    name: "Partner",
    price: "$399",
    credits: 100,
    perCredit: "$3.99",
    popular: true,
    features: [
      "100 lead unlocks / month",
      "All Colorado counties",
      "Priority new-lead alerts",
      "Forensic evidence packet (source documents + audit trail)",
      "C.R.S. § 38-38-111 restriction period tracking",
      "Fail-closed GOLD certification (4-gate verified)",
      "2 concurrent sessions",
    ],
  },
  {
    name: "Sovereign",
    price: "$899",
    credits: 350,
    perCredit: "$2.57",
    bestValue: true,
    features: [
      "350 lead unlocks / month",
      "Unlimited lead views",
      "API access",
      "Forensic evidence packet (source documents + audit trail)",
      "C.R.S. § 38-38-111 restriction period tracking",
      "Fail-closed GOLD certification (4-gate verified)",
      "5 concurrent sessions + white-glove data",
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
        </div>

        {stats && (
          <div className="hero-stats">
            <div className="stat-block">
              <span className="stat-value">{stats.total_leads ?? stats.total_assets}</span>
              <span className="stat-label">Active Pipeline</span>
            </div>
            <div className="stat-block">
              <span className="stat-value">{stats.attorney_ready}</span>
              <span className="stat-label">Attorney-Ready Leads</span>
            </div>
            <div className="stat-block">
              <span className="stat-value">{stats.gold_grade}</span>
              <span className="stat-label">GOLD Grade</span>
            </div>
            <div className="stat-block">
              <span className="stat-value">
                ${(stats.total_claimable_surplus).toLocaleString("en-US", {
                  maximumFractionDigits: 0,
                })}
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
            <h3>Exact surplus amounts — down to the penny</h3>
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
      <section className="landing-section" id="pricing">
        <h2>Founding Member Pricing</h2>
        <p style={{ textAlign: "center", color: "#94a3b8", marginBottom: "0.5rem" }}>
          Lock in introductory rates. Cancel anytime. No contract.
        </p>
        <p style={{ textAlign: "center", color: "#10b981", fontSize: "0.9rem", marginBottom: "2rem" }}>
          First 10 Founding Attorneys get these rates locked in permanently.
        </p>
        <div className="pricing-grid">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`plan-card ${tier.popular ? "sovereign" : ""}`}
            >
              {tier.popular && <div className="best-value">MOST POPULAR</div>}
              {tier.bestValue && <div className="best-value" style={{ background: "#0ea5e9" }}>BEST VALUE</div>}
              <h3>{tier.name}</h3>
              <div className="price">
                {tier.price}
                <span>{(tier as any).oneTime ? " one-time" : "/mo"}</span>
              </div>
              <div style={{ color: "#10b981", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                {tier.perCredit} per credit
              </div>
              <div style={{ color: "#64748b", fontSize: "0.8rem", marginBottom: "1rem" }}>
                {tier.credits} credits {(tier as any).oneTime ? "(pay-as-you-go)" : "included"}
              </div>
              <ul>
                {tier.features.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <Link to="/register" className={`plan-btn ${tier.popular ? "glow" : ""}`}>
                GET STARTED
              </Link>
            </div>
          ))}
        </div>
        <div style={{
          display: "flex", justifyContent: "center", gap: "2rem",
          marginTop: "2rem", flexWrap: "wrap", color: "#94a3b8", fontSize: "0.85rem"
        }}>
          <span>Cancel anytime — no contract</span>
          <span>Unused credits roll over 30 days</span>
          <span>Founding member rates locked in</span>
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
          restriction under C.R.S. § 38-38-111(5); the 24-month lockout on
          finder agreements after transfer to the State Treasurer under C.R.S. §
          38-13-1304; and the 10% maximum finder fee cap under C.R.S. §
          38-13-1304(1)(b)(IV) as amended by HB25-1224 (eff. June 4, 2025).
          Use of this platform constitutes acceptance of our Terms of Service.
        </p>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div>VERIFUSE <span className="text-green">// INTELLIGENCE</span></div>
        <div className="footer-links">
          <Link to="/preview">Preview Vault</Link>
          <a href="#pricing">Pricing</a>
          <Link to="/login">Login</Link>
        </div>
        <div className="footer-copy">
          © {new Date().getFullYear()} VeriFuse LLC. All rights reserved.
          Data sourced from public county records.
        </div>
      </footer>
    </div>
  );
}
