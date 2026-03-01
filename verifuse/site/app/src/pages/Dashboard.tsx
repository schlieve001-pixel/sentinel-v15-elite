import { useEffect, useState, useRef, useCallback } from "react";
import { Link, useSearchParams, useLocation, useNavigate } from "react-router-dom";
import {
  getLeads, getStats, downloadSecure, downloadSample, getPreviewLeads,
  sendVerification, verifyEmail, API_BASE,
  type Lead, type Stats, type PreviewLead,
} from "../lib/api";
import { useAuth } from "../lib/auth";

const POLL_INTERVAL_MS = 30_000;

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCurrencyShort(n: number): string {
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

function useHealth() {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    const base = API_BASE || "";
    const check = () => fetch(`${base}/health`)
      .then(r => setOk(r.ok))
      .catch(() => setOk(false));
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);
  return ok;
}

// ── KPI Card ───────────────────────────────────────────────────────

interface KpiProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: boolean;
  grade?: "gold" | "silver" | "bronze";
}

function KpiCard({ label, value, sub, accent, grade }: KpiProps) {
  const borderColor = grade === "gold" ? "#f59e0b"
    : grade === "silver" ? "#94a3b8"
    : grade === "bronze" ? "#b45309"
    : accent ? "#22c55e"
    : "#374151";

  return (
    <div style={{
      background: "#111827",
      border: `1px solid ${borderColor}`,
      borderRadius: 8,
      padding: "16px 20px",
      display: "flex",
      flexDirection: "column",
      gap: 4,
      minWidth: 0,
    }}>
      <div style={{ fontSize: "0.72em", letterSpacing: "0.1em", opacity: 0.55, textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{
        fontSize: "1.6em",
        fontWeight: 700,
        color: grade === "gold" ? "#f59e0b"
          : grade === "silver" ? "#94a3b8"
          : grade === "bronze" ? "#b45309"
          : accent ? "#22c55e"
          : "#e5e7eb",
        lineHeight: 1.2,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.78em", opacity: 0.5 }}>{sub}</div>
      )}
    </div>
  );
}

// ── Skeleton Card ──────────────────────────────────────────────────

function SkeletonKpi() {
  return (
    <div style={{
      background: "#111827", border: "1px solid #1f2937",
      borderRadius: 8, padding: "16px 20px", minWidth: 0,
    }}>
      <div style={{ background: "#1f2937", borderRadius: 4, height: 10, width: "60%", marginBottom: 10 }} />
      <div style={{ background: "#1f2937", borderRadius: 4, height: 22, width: "40%", marginBottom: 8 }} />
      <div style={{ background: "#1f2937", borderRadius: 4, height: 9, width: "50%" }} />
    </div>
  );
}

// ── Lead Card ─────────────────────────────────────────────────────

function LeadCard({ lead, onNavigate }: { lead: Lead; onNavigate: (id: string) => void }) {
  const isRestricted = lead.restriction_status === "RESTRICTED";
  const streamLabel = lead.surplus_stream === "TAX_LIEN" ? "Tax Lien"
    : lead.surplus_stream === "TAX_DEED" ? "Tax Deed"
    : lead.surplus_stream === "HOA" ? "HOA"
    : lead.surplus_stream === "UNCLAIMED_PROPERTY" ? "Unclaimed"
    : null;

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
          <span className="unverified-badge">PRELIMINARY</span>
        )}
      </div>
      <div className="card-id">CASE: {lead.case_number || lead.registry_asset_id?.split(":")[3] || lead.asset_id?.substring(0, 12)}</div>

      {isRestricted && (
        <div className="restriction-row">
          C.R.S. § 38-38-111: Compensation agreements prohibited until {lead.restriction_end_date}
        </div>
      )}

      {!isRestricted && lead.claim_deadline && (
        <div className={`deadline-row ${lead.deadline_passed ? "passed" : lead.days_to_claim != null && lead.days_to_claim < 60 ? "urgent" : ""}`}>
          CLAIM DEADLINE: {lead.claim_deadline}
          {lead.days_to_claim != null && !lead.deadline_passed && (
            <span> ({lead.days_to_claim} days)</span>
          )}
        </div>
      )}

      <div className="card-meta">
        <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`}>
          {lead.data_grade}
        </span>
        {lead.days_to_claim != null && !lead.deadline_passed && (
          <span className={`days-pill ${lead.days_to_claim < 60 ? "urgent" : ""}`}>
            {lead.days_to_claim}d
          </span>
        )}
        {streamLabel && (
          <span style={{
            fontSize: "0.7em", padding: "2px 7px", borderRadius: 4,
            background: "#1e3a5f", color: "#93c5fd", letterSpacing: "0.04em",
          }}>
            {streamLabel}
          </span>
        )}
        {lead.has_deceased_indicator ? (
          <span style={{
            fontSize: "0.7em", padding: "2px 7px", borderRadius: 4,
            background: "#1f2937", color: "#a78bfa", letterSpacing: "0.04em",
          }}>
            ESTATE CASE
          </span>
        ) : null}
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
        <button className="decrypt-btn-sota" onClick={() => onNavigate(lead.asset_id!)}>
          {isRestricted ? "VIEW DETAILS" : "UNLOCK INTEL"}
        </button>
        {lead.unlocked_by_me ? (
          <button
            className="btn-outline-sm full-width"
            onClick={() => downloadSecure(`/api/dossier/${lead.asset_id}`, `dossier_${lead.asset_id}.pdf`)}
          >
            DOWNLOAD DOSSIER
          </button>
        ) : lead.preview_key ? (
          <button
            className="btn-outline-sm full-width"
            onClick={() => downloadSample(lead.preview_key!)}
          >
            SAMPLE DOSSIER
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ── Preview Card ───────────────────────────────────────────────────

function PreviewCard({ lead }: { lead: PreviewLead }) {
  return (
    <div className="lead-card preview-card">
      <div className="card-header">
        <span className="county-badge">{lead.county}</span>
      </div>
      <div className="card-value surplus-band-display">
        {lead.surplus_band ?? "—"}
      </div>
      <div className="card-meta">
        <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`}>
          {lead.data_grade}
        </span>
        {lead.sale_month && (
          <span className="sale-date-pill">Sale: {lead.sale_month}</span>
        )}
      </div>
      <div className="card-actions stacked">
        <Link to="/register" className="decrypt-btn-sota">
          Sign Up to Unlock
        </Link>
        {lead.preview_key && (
          <button className="btn-outline-sm full-width"
            onClick={() => downloadSample(lead.preview_key)}>
            SAMPLE DOSSIER
          </button>
        )}
      </div>
    </div>
  );
}

// ── Admin County Coverage Table ────────────────────────────────────

function CountyCoverageTable({ counties }: { counties: Stats["counties"] }) {
  if (!counties || counties.length === 0) return null;
  return (
    <div style={{ marginTop: 24, overflowX: "auto" }}>
      <h4 style={{ fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8 }}>
        COUNTY PIPELINE BREAKDOWN
      </h4>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #374151", opacity: 0.6 }}>
            <th style={{ textAlign: "left", padding: "5px 10px" }}>COUNTY</th>
            <th style={{ textAlign: "right", padding: "5px 10px" }}>LEADS</th>
            <th style={{ textAlign: "right", padding: "5px 10px" }}>SURPLUS</th>
          </tr>
        </thead>
        <tbody>
          {counties.map((c) => (
            <tr key={c.county} style={{ borderBottom: "1px solid #1f2937" }}>
              <td style={{ padding: "5px 10px" }}>{c.county}</td>
              <td style={{ padding: "5px 10px", textAlign: "right" }}>{c.cnt}</td>
              <td style={{ padding: "5px 10px", textAlign: "right" }}>{formatCurrencyShort(c.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────

export default function Dashboard() {
  const { user, loading: authLoading, logout } = useAuth();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const isPreviewRoute = location.pathname === "/preview";
  const [simMode, setSimMode] = useState<string | null>(
    () => localStorage.getItem("vf_simulate")
  );
  const isPreview = isPreviewRoute || (searchParams.get("preview") === "1" && !user) || simMode === "user";

  useEffect(() => {
    if (!authLoading && !user && !isPreviewRoute && location.pathname === "/dashboard") {
      navigate("/preview", { replace: true });
    }
  }, [authLoading, user, isPreviewRoute, location.pathname, navigate]);

  const [leads, setLeads] = useState<Lead[]>([]);
  const [previewLeads, setPreviewLeads] = useState<PreviewLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [county, setCounty] = useState("");
  const [grade, setGrade] = useState("");
  const [sortBy, setSortBy] = useState<"surplus" | "newest" | "grade">("surplus");
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [fetchError, setFetchError] = useState("");
  const [verifyCode, setVerifyCode] = useState("");
  const [verifySending, setVerifySending] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState("");
  const [legalOpen, setLegalOpen] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const healthOk = useHealth();

  // Scroll preservation
  useEffect(() => {
    const y = Number(sessionStorage.getItem("leadsScrollY") || 0);
    if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
    return () => { sessionStorage.setItem("leadsScrollY", String(window.scrollY)); };
  }, []);

  // Seconds-ago counter
  useEffect(() => {
    const id = setInterval(() => {
      if (lastUpdated) {
        setSecondsAgo(Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [lastUpdated]);

  function navigateToLead(id: string) {
    const fromUrl = location.pathname + location.search;
    sessionStorage.setItem("lastLeadsUrl", fromUrl);
    sessionStorage.setItem("leadsScrollY", String(window.scrollY));
    navigate(`/lead/${id}`, { state: { from: fromUrl } });
  }

  function toggleSimMode() {
    if (simMode === "user") {
      localStorage.removeItem("vf_simulate");
      setSimMode(null);
    } else {
      localStorage.setItem("vf_simulate", "user");
      setSimMode("user");
    }
    window.location.reload();
  }

  // Stats polling
  const fetchStatsOnly = useCallback(() => {
    if (isPreview) return;
    getStats()
      .then((s) => {
        setStats(s);
        setLastUpdated(new Date());
        setSecondsAgo(0);
      })
      .catch(() => {/* non-critical, swallow */});
  }, [isPreview]);

  useEffect(() => {
    if (!isPreview) {
      setStatsLoading(true);
      getStats()
        .then((s) => {
          setStats(s);
          setLastUpdated(new Date());
          setSecondsAgo(0);
        })
        .finally(() => setStatsLoading(false));
    }
  }, [isPreview]);

  useEffect(() => {
    if (isPreview) return;
    pollRef.current = setInterval(fetchStatsOnly, POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isPreview, fetchStatsOnly]);

  // Leads fetch (on filter change)
  useEffect(() => {
    setFetchError("");
    const ac = new AbortController();
    if (isPreview) {
      setLoading(true);
      getPreviewLeads({ county: county || undefined, limit: 50 }, ac.signal)
        .then((res) => setPreviewLeads(res.leads))
        .catch((err) => {
          if (err instanceof Error && err.name === "AbortError") return;
          setFetchError(err instanceof Error ? err.message : "Failed to load preview");
        })
        .finally(() => setLoading(false));
      return () => ac.abort();
    }
    setLoading(true);
    getLeads({ county: county || undefined, grade: grade || undefined, limit: 50 }, ac.signal)
      .then((r) => setLeads(r.leads))
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setFetchError(err instanceof Error ? err.message : "Failed to load leads");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [county, grade, isPreview]);

  // Dynamic county list from stats API (falls back to leads-based counties)
  const countyOptions: string[] = stats?.county_list?.length
    ? stats.county_list
    : (stats?.counties || []).map((c) => c.county);

  // Client-side sorting
  const gradeOrder: Record<string, number> = { GOLD: 0, SILVER: 1, BRONZE: 2 };
  function sortLeads(arr: Lead[]): Lead[] {
    return [...arr].sort((a, b) => {
      if (sortBy === "surplus") return b.estimated_surplus - a.estimated_surplus;
      if (sortBy === "newest") return (b.sale_date || "").localeCompare(a.sale_date || "");
      return (gradeOrder[a.data_grade] ?? 9) - (gradeOrder[b.data_grade] ?? 9);
    });
  }

  const actionable = sortLeads(leads.filter((l) => l.restriction_status !== "RESTRICTED"));
  const watchlist = sortLeads(leads.filter((l) => l.restriction_status === "RESTRICTED"));

  // Grade counts for badges
  const goldCount = stats?.gold_grade ?? 0;
  const silverCount = stats?.silver_grade ?? 0;
  const bronzeCount = stats?.bronze_grade ?? 0;

  return (
    <div className="dashboard">
      {/* Top Bar */}
      <header className="dash-header">
        <Link to={user ? "/dashboard" : "/preview"} className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-status">
          <span className={`blink-dot ${healthOk ? "health-ok" : "health-err"}`}>●</span>
          <span>{healthOk ? "SYSTEM LIVE" : "SYSTEM ERROR"}</span>
          {!isPreview && lastUpdated && (
            <span style={{ fontSize: "0.75em", opacity: 0.5, marginLeft: 8 }}>
              · updated {secondsAgo}s ago
            </span>
          )}
        </div>
        <div className="dash-user">
          {user ? (
            <>
              <span className="tier-badge">{user.tier.toUpperCase()}</span>
              <span className="credits-badge">{user.credits_remaining} credits</span>
              {user.is_admin && (
                <button className={`btn-outline-sm ${simMode === "user" ? "sim-active" : ""}`}
                  onClick={toggleSimMode}>
                  {simMode === "user" ? "VIEW: USER" : "VIEW: ADMIN"}
                </button>
              )}
              {user.is_admin && (
                <Link to="/admin" className="btn-outline-sm">ADMIN</Link>
              )}
              <button className="btn-outline-sm" onClick={logout}>LOGOUT</button>
            </>
          ) : (
            <Link to="/login" className="btn-outline-sm">LOGIN</Link>
          )}
        </div>
      </header>

      {/* Admin / Simulation banners */}
      {user?.is_admin && simMode !== "user" && (
        <div className="admin-banner">ADMIN MODE</div>
      )}
      {user?.is_admin && simMode === "user" && (
        <div className="sim-banner">SIMULATING USER VIEW (READ ONLY)</div>
      )}

      {/* Email Verification Banner */}
      {user && !user.email_verified && (
        <div className="verify-banner">
          <strong>Verify your email to unlock leads</strong>
          <div className="verify-row">
            <input
              type="text" placeholder="Enter verification code"
              value={verifyCode} onChange={(e) => setVerifyCode(e.target.value)}
              className="verify-input"
            />
            <button className="btn-outline-sm" disabled={!verifyCode || verifySending}
              onClick={async () => {
                setVerifySending(true); setVerifyMsg("");
                try { await verifyEmail(verifyCode); setVerifyMsg("Email verified!"); window.location.reload(); }
                catch { setVerifyMsg("Invalid code. Try again."); }
                finally { setVerifySending(false); }
              }}>VERIFY</button>
            <button className="btn-outline-sm" disabled={verifySending}
              onClick={async () => {
                setVerifySending(true); setVerifyMsg("");
                try { await sendVerification(); setVerifyMsg("Verification email sent!"); }
                catch { setVerifyMsg("Failed to send. Try again."); }
                finally { setVerifySending(false); }
              }}>RESEND CODE</button>
          </div>
          {verifyMsg && <p className="verify-msg">{verifyMsg}</p>}
        </div>
      )}

      {/* ── KPI Grid ── */}
      {!isPreview && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 10,
          padding: "16px 20px 0",
        }}>
          {statsLoading ? (
            Array.from({ length: 8 }).map((_, i) => <SkeletonKpi key={i} />)
          ) : stats ? (
            <>
              <KpiCard
                label="GOLD Leads"
                value={goldCount}
                sub={stats.total_claimable_surplus > 0 ? formatCurrencyShort(stats.total_claimable_surplus) + " total" : undefined}
                grade="gold"
              />
              <KpiCard
                label="SILVER Leads"
                value={silverCount}
                grade="silver"
              />
              <KpiCard
                label="BRONZE Leads"
                value={bronzeCount}
                grade="bronze"
              />
              <KpiCard
                label="Total Pipeline Value"
                value={formatCurrencyShort(stats.verified_pipeline_surplus ?? stats.total_claimable_surplus)}
                sub={`${stats.verified_pipeline ?? stats.total_assets} verified leads`}
                accent={true}
              />
              <KpiCard
                label="Attorney-Ready"
                value={stats.attorney_ready}
                sub="GOLD+SILVER+BRONZE, surplus > $1K"
              />
              <KpiCard
                label="Total Leads in DB"
                value={stats.total_leads ?? stats.total_raw_volume ?? 0}
              />
              <KpiCard
                label="Counties Covered"
                value={countyOptions.length || stats.counties.length}
                sub="Colorado"
              />
              <KpiCard
                label="Last Refreshed"
                value={lastUpdated ? lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                sub={secondsAgo > 0 ? `${secondsAgo}s ago` : "just now"}
              />
            </>
          ) : null}
        </div>
      )}

      {/* Admin-only county coverage table + revenue streams */}
      {user?.is_admin && simMode !== "user" && stats && (
        <div style={{ padding: "0 20px" }}>
          {/* Revenue Streams */}
          {stats.stream_breakdown && stats.stream_breakdown.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <h4 style={{ fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8 }}>
                REVENUE STREAMS
              </h4>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {stats.stream_breakdown.map((s) => {
                  const label = s.stream === "FORECLOSURE_OVERBID" ? "Foreclosure Overbid (§ 38-38-111)"
                    : s.stream === "TAX_LIEN" ? "Tax Lien (§ 39-11-151)"
                    : s.stream === "TAX_DEED" ? "Tax Deed (§ 39-12-111)"
                    : s.stream === "HOA" ? "HOA (§ 38-33.3-316)"
                    : s.stream === "UNCLAIMED_PROPERTY" ? "Unclaimed Property (§ 38-13-1304)"
                    : s.stream;
                  return (
                    <div key={s.stream} style={{
                      background: "#111827", border: "1px solid #374151", borderRadius: 8,
                      padding: "12px 16px", minWidth: 200,
                    }}>
                      <div style={{ fontSize: "0.7em", opacity: 0.5, marginBottom: 4 }}>{label}</div>
                      <div style={{ fontWeight: 700, color: "#22c55e" }}>{formatCurrencyShort(s.total)}</div>
                      <div style={{ fontSize: "0.78em", opacity: 0.5 }}>{s.cnt} leads</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <CountyCoverageTable counties={stats.counties} />
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
          {countyOptions.map((c) => (
            <option key={c} value={c}>{c.replace(/_/g, " ").toUpperCase()}</option>
          ))}
        </select>

        <span className="grade-filter-label">GRADE</span>
        <div className="grade-filters">
          {[
            { value: "",       label: `ALL` },
            { value: "GOLD",   label: `GOLD (${goldCount})` },
            { value: "SILVER", label: `SILVER (${silverCount})` },
            { value: "BRONZE", label: `BRONZE (${bronzeCount})` },
          ].map((g) => (
            <button
              key={g.value || "ALL"}
              className={`grade-filter-btn ${grade === g.value ? "active" : ""}`}
              onClick={() => { setGrade(g.value); setLoading(true); }}
            >
              {g.label}
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

      {/* Error Banner */}
      {fetchError && (
        <div className="auth-error" style={{ margin: "12px 20px" }}>
          {fetchError}
        </div>
      )}

      {/* Lead list */}
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
                  <LeadCard key={lead.asset_id} lead={lead} onNavigate={navigateToLead} />
                ))}
              </div>
            </div>
          )}

          {watchlist.length > 0 && (
            <div className="bucket-section">
              <div className="bucket-header watchlist">
                <h2>DATA ACCESS ONLY — RESTRICTION PERIOD</h2>
                <span className="bucket-count">{watchlist.length} leads</span>
                <p className="bucket-desc">
                  Sold &lt; 6 months ago. Statutory restrictions under C.R.S. § 38-38-111 and
                  § 38-13-1304 may apply depending on sale date and fund status. Consult counsel.
                </p>
              </div>
              <div className="vault-grid">
                {watchlist.map((lead) => (
                  <LeadCard key={lead.asset_id} lead={lead} onNavigate={navigateToLead} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Legal Shield Disclaimer (Collapsible) */}
      <div className="dash-disclaimer legal-shield">
        <strong onClick={() => setLegalOpen(!legalOpen)} style={{ cursor: "pointer" }}>
          LEGAL NOTICE {legalOpen ? "\u25B4" : "\u25BE"}
        </strong>
        {legalOpen && (<>
          <p>
            This platform provides access to publicly available foreclosure sale data compiled
            from county public records. This platform does not provide finder services, does not
            contact homeowners, and does not assist in the recovery of overbid or surplus funds.
          </p>
          <p>
            Statutory restrictions under C.R.S. § 38-38-111 and § 38-13-1304 may apply
            depending on sale date and fund status. Consult counsel.
          </p>
          <p>
            This data subscription does not constitute legal advice.
            No phone numbers, email addresses, or skip-tracing data are provided by this platform.
          </p>
        </>)}
      </div>
    </div>
  );
}
