import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getStats, type Stats } from "../lib/api";

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
        <div className="hero-badge">COLORADO SURPLUS INTELLIGENCE</div>
        <h1>
          <span className="text-green">$
            {stats
              ? (stats.total_claimable_surplus / 1_000_000).toFixed(1) + "M"
              : "..."}
          </span>{" "}
          in verified surplus.
          <br />
          Your competitors don't know it exists.
        </h1>
        <p className="hero-sub">
          VeriFuse monitors Colorado county records in real-time, identifies
          foreclosure surplus assets, and delivers attorney-ready intelligence
          packets — so you can file first.
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
              <span className="stat-value">{stats.total_assets}</span>
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

      {/* Pricing */}
      <section className="landing-section" id="pricing">
        <h2>Founding Member Pricing</h2>
        <p style={{ textAlign: "center", color: "#94a3b8", marginBottom: "0.5rem" }}>
          Lock in introductory rates. Cancel anytime. No contract.
        </p>
        <p style={{ textAlign: "center", color: "#10b981", fontSize: "0.9rem", marginBottom: "2rem" }}>
          First 100 subscribers get these rates locked for 12 months.
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
          federal regulations, including the 6-month post-sale contact
          restriction under C.R.S. § 38-38-111(5). Use of this platform
          constitutes acceptance of our Terms of Service.
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
