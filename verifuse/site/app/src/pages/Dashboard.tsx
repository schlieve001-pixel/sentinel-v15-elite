import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getLeads, getStats, getDossierUrl, type Lead, type Stats } from "../lib/api";
import { useAuth } from "../lib/auth";

const COUNTIES = ["", "Denver", "Jefferson", "Arapahoe", "Adams", "El Paso", "Douglas"];

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function LeadCard({ lead }: { lead: Lead }) {
  const isRestricted = lead.restriction_status === "RESTRICTED";

  return (
    <div className={`lead-card ${isRestricted ? "restricted" : ""}`}>
      <div className="card-header">
        <span className="county-badge">{lead.county}</span>
        {isRestricted ? (
          <span className="restriction-badge">
            RESTRICTED — {lead.days_until_actionable} DAYS
          </span>
        ) : lead.days_to_claim != null ? (
          <span className={`timer-badge ${lead.days_to_claim < 60 ? "urgent" : ""} ${lead.deadline_passed ? "expired" : ""}`}>
            {lead.deadline_passed ? "DEADLINE PASSED" : `${lead.days_to_claim} DAYS TO CLAIM`}
          </span>
        ) : null}
      </div>

      <div className="card-value">
        {formatCurrency(lead.estimated_surplus)}
        {!lead.surplus_verified && (
          <span className="unverified-badge">UNVERIFIED</span>
        )}
      </div>
      <div className="card-id">CASE: {lead.case_number || lead.asset_id}</div>

      {/* Restriction notice for < 6 month leads */}
      {isRestricted && (
        <div className="restriction-row">
          C.R.S. § 38-38-111: Compensation agreements prohibited until {lead.restriction_end_date}
        </div>
      )}

      {/* Claim deadline for actionable leads */}
      {!isRestricted && lead.claim_deadline && (
        <div className={`deadline-row ${lead.deadline_passed ? "passed" : lead.days_to_claim != null && lead.days_to_claim < 60 ? "urgent" : ""}`}>
          CLAIM DEADLINE: {lead.claim_deadline}
          {lead.days_to_claim != null && !lead.deadline_passed && (
            <span> ({lead.days_to_claim} days)</span>
          )}
        </div>
      )}

      {/* Data pills row */}
      <div className="card-meta">
        <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`}>
          {lead.data_grade}
        </span>
        <span className="confidence-pill">
          {Math.round((lead.confidence_score || 0) * 100)}%
        </span>
        {lead.days_to_claim != null && !lead.deadline_passed && (
          <span className={`days-pill ${lead.days_to_claim < 60 ? "urgent" : ""}`}>
            {lead.days_to_claim}d
          </span>
        )}
      </div>

      {lead.address_hint && (
        <div className="address-hint">{lead.address_hint}</div>
      )}

      {lead.owner_img ? (
        <div className="owner-img-wrap">
          <span className="owner-label">OWNER</span>
          <img src={lead.owner_img} alt="Owner (obfuscated)" />
        </div>
      ) : (
        <div className="redacted-field">OWNER DATA RESTRICTED</div>
      )}

      <div className="card-actions stacked">
        <Link to={`/lead/${lead.asset_id}`} className="decrypt-btn-sota">
          {isRestricted ? "VIEW DETAILS" : "UNLOCK INTEL"}
        </Link>
        <a
          href={getDossierUrl(lead.asset_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="btn-outline-sm full-width"
        >
          FREE DOSSIER
        </a>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [county, setCounty] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getLeads({ county: county || undefined, limit: 100 }),
      getStats(),
    ])
      .then(([leadsRes, statsRes]) => {
        setLeads(leadsRes.leads);
        setStats(statsRes);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [county]);

  // Split leads into buckets
  const actionable = leads.filter(
    (l) => l.restriction_status !== "RESTRICTED"
  );
  const watchlist = leads.filter(
    (l) => l.restriction_status === "RESTRICTED"
  );

  return (
    <div className="dashboard">
      {/* Top Bar */}
      <header className="dash-header">
        <Link to="/" className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-status">
          <span className="blink-dot">●</span>
          SYSTEM LIVE
        </div>
        <div className="dash-user">
          {user ? (
            <>
              <span className="tier-badge">{user.tier.toUpperCase()}</span>
              <span className="credits-badge">{user.credits_remaining} credits</span>
              <button className="btn-outline-sm" onClick={logout}>LOGOUT</button>
            </>
          ) : (
            <Link to="/login" className="btn-outline-sm">LOGIN</Link>
          )}
        </div>
      </header>

      {/* Stats Row */}
      {stats && (
        <div className="stats-row">
          <div className="stat-pill">
            <span className="stat-value">{stats.total_assets}</span>
            <span className="stat-label">Verified Assets</span>
          </div>
          <div className="stat-pill">
            <span className="stat-value">{stats.gold_grade}</span>
            <span className="stat-label">GOLD Grade</span>
          </div>
          <div className="stat-pill accent">
            <span className="stat-value">
              {formatCurrency(stats.total_claimable_surplus)}
            </span>
            <span className="stat-label">Claimable Surplus</span>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="filters-row">
        <select
          value={county}
          onChange={(e) => { setCounty(e.target.value); setLoading(true); }}
          className="filter-select"
        >
          <option value="">ALL COUNTIES</option>
          {COUNTIES.filter(Boolean).map((c) => (
            <option key={c} value={c}>{c.toUpperCase()}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="center-content">
          <div className="loader-ring"></div>
          <p className="processing-text">LOADING INTELLIGENCE...</p>
        </div>
      ) : leads.length === 0 ? (
        <div className="center-content">
          <p style={{ color: "#64748b" }}>No leads found for selected filters.</p>
        </div>
      ) : (
        <>
          {/* ── ACTIONABLE NOW ── */}
          {actionable.length > 0 && (
            <div className="bucket-section">
              <div className="bucket-header actionable">
                <h2>ESCROW ENDED — ACTIONABLE</h2>
                <span className="bucket-count">{actionable.length} leads</span>
                <p className="bucket-desc">
                  Sold &gt; 6 months ago. C.R.S. § 38-38-111 restriction period has passed.
                  Attorney-client agreements are permitted.
                </p>
              </div>
              <div className="vault-grid">
                {actionable.map((lead) => (
                  <LeadCard key={lead.asset_id} lead={lead} />
                ))}
              </div>
            </div>
          )}

          {/* ── WATCHLIST ── */}
          {watchlist.length > 0 && (
            <div className="bucket-section">
              <div className="bucket-header watchlist">
                <h2>DATA ACCESS ONLY — RESTRICTION PERIOD</h2>
                <span className="bucket-count">{watchlist.length} leads</span>
                <p className="bucket-desc">
                  Sold &lt; 6 months ago. C.R.S. § 38-38-111(2.5)(c): Compensation agreements
                  are void and unenforceable while funds are held by the Public Trustee.
                </p>
              </div>
              <div className="vault-grid">
                {watchlist.map((lead) => (
                  <LeadCard key={lead.asset_id} lead={lead} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Legal Shield Disclaimer */}
      <div className="dash-disclaimer legal-shield">
        <strong>LEGAL NOTICE</strong>
        <p>
          This platform provides access to publicly available foreclosure sale data compiled
          from county public records. This platform does not provide finder services, does not
          contact homeowners, and does not assist in the recovery of overbid or surplus funds.
        </p>
        <p>
          Colorado law (C.R.S. § 38-38-111) prohibits agreements to pay compensation to recover
          or assist in recovering overbid amounts from the public trustee. Colorado law (C.R.S.
          § 38-13-1304) restricts agreements to recover unclaimed overbids held by the State
          Treasurer for at least two years after transfer, and caps compensation at 20-30%.
        </p>
        <p>
          Subscribers acknowledge that inducing or attempting to induce a person to enter into a
          compensation agreement that violates C.R.S. § 38-38-111 or § 38-13-1304 is a class 2
          misdemeanor and a deceptive trade practice under the Colorado Consumer Protection Act.
        </p>
        <p>
          This data subscription does not constitute legal advice. Surplus amounts marked
          "UNVERIFIED" have not been independently confirmed against county indebtedness records.
          No phone numbers, email addresses, or skip-tracing data are provided by this platform.
        </p>
      </div>
    </div>
  );
}
