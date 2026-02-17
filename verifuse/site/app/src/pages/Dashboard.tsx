import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getLeads, getStats, downloadSecure, getPreviewLeads, sendVerification, verifyEmail, type Lead, type Stats, type PreviewLead } from "../lib/api";
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
        <button
          className="btn-outline-sm full-width"
          onClick={() => downloadSecure(`/api/dossier/${lead.asset_id}`, `dossier_${lead.asset_id}.txt`)}
        >
          FREE DOSSIER
        </button>
      </div>
    </div>
  );
}

function PreviewCard({ lead }: { lead: PreviewLead }) {
  return (
    <div className="lead-card preview-card">
      <div className="card-header">
        <span className="county-badge">{lead.county}</span>
        {lead.restriction_status === "RESTRICTED" && lead.days_until_actionable != null && (
          <span className="restriction-badge">
            RESTRICTED — {lead.days_until_actionable} DAYS
          </span>
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
        {lead.sale_date && (
          <span className="sale-date-pill">Sale: {lead.sale_date}</span>
        )}
      </div>
      <div className="card-actions stacked">
        <Link to="/register" className="decrypt-btn-sota">
          Sign Up to Unlock
        </Link>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user, logout } = useAuth();
  const [searchParams] = useSearchParams();
  const isPreview = searchParams.get("preview") === "1" && !user;
  const [leads, setLeads] = useState<Lead[]>([]);
  const [previewLeads, setPreviewLeads] = useState<PreviewLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [county, setCounty] = useState("");
  const [grade, setGrade] = useState("");
  const [sortBy, setSortBy] = useState<"surplus" | "newest" | "grade">("surplus");
  const [loading, setLoading] = useState(true);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifySending, setVerifySending] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState("");

  useEffect(() => {
    if (isPreview) {
      getPreviewLeads({ county: county || undefined, limit: 100 })
        .then((res) => setPreviewLeads(res.leads))
        .catch(() => {})
        .finally(() => setLoading(false));
      return;
    }
    Promise.all([
      getLeads({ county: county || undefined, grade: grade || undefined, limit: 100 }),
      getStats(),
    ])
      .then(([leadsRes, statsRes]) => {
        setLeads(leadsRes.leads);
        setStats(statsRes);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [county, grade, isPreview]);

  // Client-side sorting
  const gradeOrder: Record<string, number> = { GOLD: 0, SILVER: 1, BRONZE: 2 };
  function sortLeads(arr: Lead[]): Lead[] {
    return [...arr].sort((a, b) => {
      if (sortBy === "surplus") return b.estimated_surplus - a.estimated_surplus;
      if (sortBy === "newest") return (b.sale_date || "").localeCompare(a.sale_date || "");
      return (gradeOrder[a.data_grade] ?? 9) - (gradeOrder[b.data_grade] ?? 9);
    });
  }

  // Split leads into buckets
  const actionable = sortLeads(leads.filter(
    (l) => l.restriction_status !== "RESTRICTED"
  ));
  const watchlist = sortLeads(leads.filter(
    (l) => l.restriction_status === "RESTRICTED"
  ));

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

      {/* Email Verification Banner */}
      {user && !user.email_verified && (
        <div className="verify-banner">
          <strong>Verify your email to unlock leads</strong>
          <div className="verify-row">
            <input
              type="text"
              placeholder="Enter verification code"
              value={verifyCode}
              onChange={(e) => setVerifyCode(e.target.value)}
              className="verify-input"
            />
            <button
              className="btn-outline-sm"
              disabled={!verifyCode || verifySending}
              onClick={async () => {
                setVerifySending(true);
                setVerifyMsg("");
                try {
                  await verifyEmail(verifyCode);
                  setVerifyMsg("Email verified!");
                  window.location.reload();
                } catch {
                  setVerifyMsg("Invalid code. Try again.");
                } finally {
                  setVerifySending(false);
                }
              }}
            >
              VERIFY
            </button>
            <button
              className="btn-outline-sm"
              disabled={verifySending}
              onClick={async () => {
                setVerifySending(true);
                setVerifyMsg("");
                try {
                  await sendVerification();
                  setVerifyMsg("Verification email sent!");
                } catch {
                  setVerifyMsg("Failed to send. Try again.");
                } finally {
                  setVerifySending(false);
                }
              }}
            >
              RESEND CODE
            </button>
          </div>
          {verifyMsg && <p className="verify-msg">{verifyMsg}</p>}
        </div>
      )}

      {/* Stats Row */}
      {stats && !isPreview && (
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

        <div className="grade-filters">
          {["", "GOLD", "SILVER", "BRONZE"].map((g) => (
            <button
              key={g || "ALL"}
              className={`grade-filter-btn ${grade === g ? "active" : ""}`}
              onClick={() => { setGrade(g); setLoading(true); }}
            >
              {g || "ALL"}
            </button>
          ))}
        </div>

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as "surplus" | "newest" | "grade")}
          className="filter-select"
        >
          <option value="surplus">Highest Surplus</option>
          <option value="newest">Newest Sale</option>
          <option value="grade">Best Grade</option>
        </select>
      </div>

      {/* Preview Banner */}
      {isPreview && (
        <div className="preview-banner">
          Viewing Preview — <Link to="/register">Sign Up for Full Access</Link>
        </div>
      )}

      {loading ? (
        <div className="center-content">
          <div className="loader-ring"></div>
          <p className="processing-text">LOADING INTELLIGENCE...</p>
        </div>
      ) : isPreview ? (
        previewLeads.length === 0 ? (
          <div className="center-content">
            <p style={{ color: "#64748b" }}>No preview leads available.</p>
          </div>
        ) : (
          <div className="bucket-section">
            <div className="bucket-header actionable">
              <h2>PREVIEW — SURPLUS ASSETS</h2>
              <span className="bucket-count">{previewLeads.length} leads</span>
            </div>
            <div className="vault-grid">
              {previewLeads.map((lead) => (
                <PreviewCard key={lead.preview_key} lead={lead} />
              ))}
            </div>
          </div>
        )
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
