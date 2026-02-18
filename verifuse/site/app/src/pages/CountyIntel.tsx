/**
 * CountyIntel — SEO Landing Page (Draft)
 *
 * URL pattern: /county/:countyName
 * Purpose: Capture organic search intent for "surplus funds [county]" queries.
 * Each county gets a unique, crawlable page with live stats.
 *
 * Components:
 *   - SurplusTicker: Scrolling list of recent high-value drops
 *   - MarketHeatmap: Placeholder for future visualization
 *   - CTA: "Unlock [County] Report"
 */

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getPreviewLeads, getStats, API_BASE, type PreviewLead, type Stats } from "../lib/api";

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

// ── SurplusTicker ───────────────────────────────────────────────────

function SurplusTicker({ leads }: { leads: PreviewLead[] }) {
  if (leads.length === 0) return null;

  return (
    <div className="surplus-ticker">
      <div className="ticker-label">RECENT SURPLUS DROPS</div>
      <div className="ticker-track">
        {leads.map((lead, i) => (
          <span key={lead.preview_key} className="ticker-item">
            <span className="ticker-grade">{lead.data_grade}</span>
            <span className="ticker-amount">{formatCurrency(lead.estimated_surplus)}</span>
            {lead.sale_date && <span className="ticker-date">{lead.sale_date}</span>}
            {i < leads.length - 1 && <span className="ticker-sep" />}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── MarketHeatmap (Placeholder) ─────────────────────────────────────

function MarketHeatmap({ county }: { county: string }) {
  return (
    <div className="market-heatmap-placeholder">
      <div className="heatmap-label">MARKET ACTIVITY — {county.toUpperCase()}</div>
      <div className="heatmap-grid">
        {/* Placeholder: future D3/Mapbox visualization */}
        <div className="heatmap-cell hot" />
        <div className="heatmap-cell warm" />
        <div className="heatmap-cell cool" />
        <div className="heatmap-cell warm" />
        <div className="heatmap-cell hot" />
        <div className="heatmap-cell cool" />
        <div className="heatmap-cell warm" />
        <div className="heatmap-cell cool" />
        <div className="heatmap-cell hot" />
      </div>
      <p className="heatmap-note">
        Heatmap visualization coming soon. Data updates daily.
      </p>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export default function CountyIntel() {
  const { countyName } = useParams<{ countyName: string }>();
  const county = countyName || "Denver";
  const displayName = county.charAt(0).toUpperCase() + county.slice(1);

  const [leads, setLeads] = useState<PreviewLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getPreviewLeads({ county: displayName, limit: 20 }),
      getStats(),
    ])
      .then(([previewRes, statsRes]) => {
        setLeads(previewRes.leads);
        setStats(statsRes);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [displayName]);

  const countyStats = stats?.counties.find(
    (c) => c.county.toLowerCase() === county.toLowerCase()
  );

  return (
    <div className="county-intel">
      {/* SEO Header */}
      <header className="county-header">
        <Link to="/" className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
      </header>

      {/* Hero */}
      <section className="county-hero">
        <h1>
          Top Surplus Opportunities in{" "}
          <span className="text-green">{displayName} County</span>
        </h1>
        <p className="county-hero-sub">
          Real-time foreclosure surplus intelligence for {displayName} County, Colorado.
          Updated daily from county public trustee records.
        </p>

        {countyStats && (
          <div className="county-stats-row">
            <div className="stat-pill">
              <span className="stat-value">{countyStats.cnt}</span>
              <span className="stat-label">Active Leads</span>
            </div>
            <div className="stat-pill accent">
              <span className="stat-value">{formatCurrency(countyStats.total)}</span>
              <span className="stat-label">Total Surplus</span>
            </div>
          </div>
        )}
      </section>

      {/* Ticker */}
      <SurplusTicker leads={leads.slice(0, 10)} />

      {/* Heatmap */}
      <MarketHeatmap county={displayName} />

      {/* Lead Cards */}
      <section className="county-leads">
        <h2>{displayName} County Surplus Leads</h2>

        {loading ? (
          <div className="center-content">
            <div className="loader-ring" />
            <p className="processing-text">SCANNING {displayName.toUpperCase()} COUNTY...</p>
          </div>
        ) : leads.length === 0 ? (
          <p style={{ color: "#64748b", textAlign: "center", padding: "2rem" }}>
            No surplus leads currently available for {displayName} County.
          </p>
        ) : (
          <div className="vault-grid">
            {leads.map((lead) => (
              <div key={lead.preview_key} className="lead-card preview-card">
                <div className="card-header">
                  <span className="county-badge">{lead.county}</span>
                  {lead.restriction_status === "RESTRICTED" && (
                    <span className="restriction-badge">RESTRICTED</span>
                  )}
                </div>
                <div className="card-value">
                  {formatCurrency(lead.estimated_surplus)}
                </div>
                <div className="card-meta">
                  <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`}>
                    {lead.data_grade}
                  </span>
                  <span className="confidence-pill">
                    {Math.round((lead.confidence_score || 0) * 100)}%
                  </span>
                </div>
                <div className="card-actions stacked">
                  <Link to="/register" className="decrypt-btn-sota">
                    Unlock Full Intel
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* CTA */}
      <section className="county-cta">
        <h2>Unlock the {displayName} County Report</h2>
        <p>
          Get full owner names, property addresses, case numbers, and
          court-ready dossiers for every surplus lead in {displayName} County.
        </p>
        <Link to="/register" className="btn-primary">
          START FREE TRIAL
        </Link>
      </section>

      {/* SEO Footer */}
      <footer className="county-footer">
        <p>
          VeriFuse provides publicly available foreclosure surplus data for
          {" "}{displayName} County, Colorado. This is not legal advice.
          C.R.S. 38-38-111 restrictions apply. Consult a licensed attorney.
        </p>
        <div className="footer-links">
          <Link to="/preview">Preview Vault</Link>
          <a href="/#pricing">Pricing</a>
          <Link to="/login">Login</Link>
        </div>
      </footer>
    </div>
  );
}
