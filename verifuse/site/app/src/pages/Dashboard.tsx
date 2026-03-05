import React, { useEffect, useState, useRef, useCallback } from "react";
import { Link, useSearchParams, useLocation, useNavigate } from "react-router-dom";
import { TrendingUp, DollarSign, MapPin, Clock, Star } from "lucide-react";
import {
  getLeads, getStats, downloadSecure, downloadSample, getPreviewLeads,
  sendVerification, verifyEmail, API_BASE,
  type Lead, type Stats, type PreviewLead,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { toast } from "../components/Toast";
import { Tooltip } from "../components/Tooltip";

const POLL_INTERVAL_MS = 30_000;

// HB25-1224: 10% statutory fee cap (C.R.S. § 38-13-1304, eff. June 4 2025)
const ATTORNEY_FEE_CAP = 0.10;

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCurrencyShort(n: number): string {
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

function maxAttorneyFee(surplus: number): string {
  return formatCurrencyShort(surplus * ATTORNEY_FEE_CAP);
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
  href?: string;
  icon?: React.ElementType;
  tooltip?: string;
}

function KpiCard({ label, value, sub, accent, grade, href, icon: Icon, tooltip }: KpiProps) {
  const borderColor = grade === "gold" ? "#f59e0b"
    : grade === "silver" ? "#94a3b8"
    : grade === "bronze" ? "#b45309"
    : accent ? "#22c55e"
    : "#374151";

  const valueColor = grade === "gold" ? "#f59e0b"
    : grade === "silver" ? "#94a3b8"
    : grade === "bronze" ? "#b45309"
    : accent ? "#22c55e"
    : "#e5e7eb";

  const inner = (
    <>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {Icon && <Icon size={16} style={{ color: valueColor, opacity: 0.8 }} />}
          <div style={{ fontSize: "0.72em", letterSpacing: "0.1em", opacity: 0.55, textTransform: "uppercase" }}>
            {label}
          </div>
        </div>
        {tooltip && (
          <Tooltip content={tooltip} position="top">
            <span style={{
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              width: 14, height: 14, borderRadius: "50%", background: "#1e293b",
              color: "#64748b", fontSize: "0.65em", fontWeight: 700, cursor: "default",
              flexShrink: 0, marginTop: 1,
            }}>?</span>
          </Tooltip>
        )}
      </div>
      <div style={{
        fontSize: "1.6em",
        fontWeight: 700,
        color: valueColor,
        lineHeight: 1.2,
        marginTop: 4,
      }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.78em", opacity: 0.5 }}>{sub}</div>
      )}
    </>
  );

  const cardStyle: React.CSSProperties = {
    background: "#111827",
    border: `1px solid ${borderColor}`,
    borderRadius: 8,
    padding: "16px 20px",
    display: "flex",
    flexDirection: "column",
    gap: 4,
    minWidth: 0,
    textDecoration: "none",
    color: "inherit",
    cursor: href ? "pointer" : "default",
  };

  if (href) {
    return <Link to={href} style={cardStyle}>{inner}</Link>;
  }
  return <div style={cardStyle}>{inner}</div>;
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
  const isOwned = lead.unlocked_by_me === true;
  const streamLabel = lead.surplus_stream === "TAX_LIEN" ? "Tax Lien"
    : lead.surplus_stream === "TAX_DEED" ? "Tax Deed"
    : lead.surplus_stream === "HOA" ? "HOA"
    : lead.surplus_stream === "UNCLAIMED_PROPERTY" ? "Unclaimed"
    : null;

  return (
    <div className={`lead-card ${isRestricted ? "restricted" : ""} ${isOwned ? "owned" : ""}`}>
      <div className="card-header">
        <span className="county-badge">{lead.county?.replace(/_/g, " ").toUpperCase()}</span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {isOwned && (
            <Tooltip content="You have unlocked this lead. Full PII and documents are available." position="top">
              <span className="owned-badge" style={{ cursor: "default" }}>● OWNED</span>
            </Tooltip>
          )}
          {isRestricted ? (
            <Tooltip content={`C.R.S. § 38-38-111 restriction period active. ${lead.days_until_actionable} days until fee agreements are permitted. You may view — but not solicit — the owner during this window.`} position="top">
              <span className="restriction-badge" style={{ cursor: "default" }}>
                RESTRICTED — {lead.days_until_actionable} DAYS
              </span>
            </Tooltip>
          ) : lead.days_to_claim != null ? (
            <Tooltip
              content={
                lead.deadline_passed
                  ? "Claim window closed. Surplus may have escheated to county treasurer. Verify current status before proceeding."
                  : lead.days_to_claim < 30
                  ? `CRITICAL: Only ${lead.days_to_claim} days left. File immediately.`
                  : lead.days_to_claim < 60
                  ? `URGENT: ${lead.days_to_claim} days until claim deadline. Expedite client outreach.`
                  : `${lead.days_to_claim} days until claim deadline under C.R.S. § 38-38-111.`
              }
              position="top"
            >
              <span className={`timer-badge ${lead.days_to_claim < 60 ? "urgent" : ""} ${lead.deadline_passed ? "expired" : ""}`} style={{ cursor: "default" }}>
                {lead.deadline_passed ? "DEADLINE PASSED" : `${lead.days_to_claim} DAYS TO CLAIM`}
              </span>
            </Tooltip>
          ) : null}
        </div>
      </div>

      <Tooltip
        content={
          lead.surplus_verified
            ? "Overbid amount math-confirmed from official county records"
            : "Preliminary estimate — pending Gate 4 validation from sale documents"
        }
        position="top"
      >
        <div className="card-value" style={{ cursor: "default" }}>
          {formatCurrency(lead.estimated_surplus)}
          {!lead.surplus_verified && (
            <span className="unverified-badge">PRELIMINARY</span>
          )}
        </div>
      </Tooltip>

      {/* Attorney fee estimate (HB25-1224: 10% statutory cap) */}
      {lead.estimated_surplus > 0 && (
        <Tooltip content="Max attorney fee under HB25-1224 (C.R.S. § 38-13-1304) — 10% statutory cap, effective June 4, 2025" position="top">
          <div style={{ fontSize: "0.72em", color: "#22c55e", opacity: 0.75, marginBottom: 2, cursor: "default", letterSpacing: "0.04em" }}>
            MAX FEE: {maxAttorneyFee(lead.estimated_surplus)}
          </div>
        </Tooltip>
      )}

      <div className="card-id">CASE: {lead.case_number || lead.registry_asset_id?.split(":")[3] || lead.asset_id?.substring(0, 12)}</div>

      {isRestricted && (
        <Tooltip content="C.R.S. § 38-38-111 prohibits fee agreements with property owners during the 6-month post-sale redemption period. WATCH-ONLY until this date." position="bottom">
          <div className="restriction-row" style={{ cursor: "default" }}>
            C.R.S. § 38-38-111: Compensation agreements prohibited until {lead.restriction_end_date}
          </div>
        </Tooltip>
      )}

      {!isRestricted && lead.claim_deadline && (
        <Tooltip
          content={
            lead.deadline_passed
              ? "Statutory claim window has closed. Surplus may have escheated to the county treasurer. Verify current status."
              : lead.days_to_claim != null && lead.days_to_claim < 60
              ? "URGENT: Fewer than 60 days remain. File claim immediately to preserve claimant rights under C.R.S. § 38-38-111."
              : "Claim deadline under C.R.S. § 38-38-111. File before this date to recover overbid funds."
          }
          position="bottom"
        >
          <div className={`deadline-row ${lead.deadline_passed ? "passed" : lead.days_to_claim != null && lead.days_to_claim < 60 ? "urgent" : ""}`} style={{ cursor: "default" }}>
            CLAIM DEADLINE: {lead.claim_deadline}
            {lead.days_to_claim != null && !lead.deadline_passed && (
              <span> ({lead.days_to_claim} days)</span>
            )}
          </div>
        </Tooltip>
      )}

      <div className="card-meta">
        <Tooltip
          content={
            lead.data_grade === "GOLD"
              ? "GOLD: Sale amount math confirmed + official provenance document on file. Highest confidence."
              : lead.data_grade === "SILVER"
              ? "SILVER: Probable overbid detected, pending 6-month restriction window or secondary validation."
              : lead.data_grade === "BRONZE"
              ? "BRONZE: Pre-validation. Overbid likely but sale documents or math not yet confirmed by Gate 4."
              : "Grade pending validation."
          }
          position="top"
        >
          <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`} style={{ cursor: "default" }}>
            {lead.data_grade}
          </span>
        </Tooltip>
        {lead.days_to_claim != null && !lead.deadline_passed && (
          <Tooltip content={`${lead.days_to_claim} days until claim deadline. ${lead.days_to_claim < 30 ? "FILE IMMEDIATELY." : lead.days_to_claim < 60 ? "Expedite filing." : "Monitor timeline."}`} position="top">
            <span className={`days-pill ${lead.days_to_claim < 60 ? "urgent" : ""}`} style={{ cursor: "default" }}>
              {lead.days_to_claim}d
            </span>
          </Tooltip>
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

      {lead.data_age_days != null && lead.data_age_days > 30 && (
        <div style={{ fontSize: "0.68em", color: lead.data_age_days > 90 ? "#ef4444" : "#f59e0b", letterSpacing: "0.05em", marginBottom: 2 }}
             title={`Last updated ${lead.data_age_days} days ago — figures may be stale`}>
          {lead.data_age_days > 90 ? "⚠ " : ""}STALE DATA — {lead.data_age_days}d
        </div>
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
        <button
          className="decrypt-btn-sota"
          onClick={() => onNavigate(lead.asset_id!)}
          style={isOwned ? { background: "transparent", border: "1px solid var(--green)", color: "var(--green)" } : undefined}
        >
          {isRestricted ? "VIEW DETAILS" : isOwned ? "OPEN INTEL →" : "UNLOCK INTEL"}
        </button>
        {isOwned ? (
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
  const [viewMode, setViewMode] = useState<"actionable" | "watchlist" | "my_leads">("actionable");
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
  const myLeads = sortLeads(leads.filter((l) => l.unlocked_by_me === true));

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
              <Link to="/pricing" className="btn-outline-sm">PRICING</Link>
              {user.is_admin && (
                <Link to="/admin" className="btn-outline-sm">ADMIN</Link>
              )}
              <button className="btn-outline-sm" onClick={logout}>LOGOUT</button>
            </>
          ) : (
            <>
              <Link to="/pricing" className="btn-outline-sm">PRICING</Link>
              <Link to="/login" className="btn-outline-sm">LOGIN</Link>
            </>
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
                try {
                  await verifyEmail(verifyCode);
                  toast("Email verified ✓", "success");
                  setVerifyMsg("Email verified!");
                  window.location.reload();
                }
                catch { setVerifyMsg("Invalid code. Try again."); }
                finally { setVerifySending(false); }
              }}>VERIFY</button>
            <button className="btn-outline-sm" disabled={verifySending}
              onClick={async () => {
                setVerifySending(true); setVerifyMsg("");
                try {
                  const res = await sendVerification();
                  if (res.dev_code) {
                    setVerifyCode(res.dev_code);
                    setVerifyMsg(`Code: ${res.dev_code} (email not configured — pre-filled)`);
                  } else {
                    setVerifyMsg("Verification email sent!");
                  }
                }
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
                icon={Star}
                tooltip="GOLD: Math-confirmed overbid with official provenance document on file. Highest confidence — ready for immediate attorney outreach."
              />
              <KpiCard
                label="SILVER Leads"
                value={silverCount}
                grade="silver"
                tooltip="SILVER: Probable overbid detected. Restriction window active (C.R.S. § 38-38-111) or secondary doc validation pending. Monitor for GOLD promotion."
              />
              <KpiCard
                label="BRONZE Leads"
                value={bronzeCount}
                grade="bronze"
                tooltip="BRONZE: Pre-validation stage. Overbid likely but sale documents or math not yet confirmed. Gate 4 extraction running."
              />
              <KpiCard
                label="Total Pipeline Value"
                value={formatCurrencyShort(stats.verified_pipeline_surplus ?? stats.total_claimable_surplus)}
                sub={`${stats.verified_pipeline ?? stats.total_assets} verified leads`}
                accent={true}
                icon={DollarSign}
                tooltip="Combined overbid surplus across all GOLD + SILVER + BRONZE leads with confirmed values > $100. Represents the total claimable estate across your pipeline."
              />
              <KpiCard
                label="Attorney-Ready"
                value={stats.attorney_ready}
                sub="surplus > $1K, all verified grades"
                icon={TrendingUp}
                tooltip="Leads with confirmed surplus over $1,000 across GOLD, SILVER, and BRONZE grades. These have cleared basic validation and represent actionable opportunities under C.R.S. § 38-38-111."
              />
              <KpiCard
                label="Pre-Sale Pipeline"
                value={stats.pre_sale_count ?? 0}
                sub="upcoming auctions — click to explore"
                grade="bronze"
                href="/pre-sale"
                icon={Clock}
                tooltip="Upcoming foreclosure auctions with opening bids filed. Track these before sale date to identify overbid opportunities the moment the gavel falls."
              />
              <KpiCard
                label="Total Leads in DB"
                value={stats.total_leads ?? stats.total_raw_volume ?? 0}
                icon={TrendingUp}
                tooltip="All leads ingested across all counties and surplus streams, including pre-validation BRONZE and REJECT grades. Reflects raw pipeline volume."
              />
              <KpiCard
                label="Counties Covered"
                value={countyOptions.length || stats.counties.length}
                sub="Colorado"
                icon={MapPin}
                tooltip="Active Colorado counties with live GovSoft scraper coverage. New counties are added quarterly. Mesa and Eagle are CAPTCHA-blocked (manual review only)."
              />
              <KpiCard
                label="Last Refreshed"
                value={lastUpdated ? lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                sub={secondsAgo > 0 ? `${secondsAgo}s ago` : "just now"}
                tooltip="Dashboard stats refresh every 30 seconds automatically. Click any filter to force an immediate refresh."
              />
            </>
          ) : null}
        </div>
      )}

      {/* Credits progress bar (user-facing, not admin-mode) */}
      {user && !isPreview && simMode !== "user" && !user.is_admin && (
        <div style={{ padding: "12px 20px 0" }}>
          {(() => {
            const pct = user.credits_pct_remaining ?? (user.monthly_grant ? Math.round(user.credits_remaining / user.monthly_grant * 100) : 100);
            const barColor = pct > 50 ? "#22c55e" : pct > 20 ? "#f59e0b" : "#ef4444";
            const nextTier = user.tier === "associate" ? "Partner" : user.tier === "partner" ? "Sovereign" : null;
            return (
              <div style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 8, padding: "12px 16px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78em", marginBottom: 6 }}>
                  <span style={{ opacity: 0.5 }}>CREDITS REMAINING</span>
                  <span style={{ color: barColor, fontWeight: 700 }}>{user.credits_remaining} / {user.monthly_grant ?? "—"}</span>
                </div>
                <div style={{ background: "#1f2937", borderRadius: 4, height: 6, overflow: "hidden" }}>
                  <div style={{ background: barColor, width: `${Math.min(pct, 100)}%`, height: "100%", transition: "width 0.3s" }} />
                </div>
                {user.upgrade_recommended && nextTier && (
                  <div style={{ marginTop: 8, fontSize: "0.75em", color: "#f59e0b" }}>
                    Running low — <a href="/pricing" style={{ color: "#22c55e", textDecoration: "underline" }}>upgrade to {nextTier}</a> for more credits
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {/* Admin-only county coverage table + revenue streams */}
      {user?.is_admin && simMode !== "user" && stats && (
        <div style={{ padding: "0 20px" }}>
          {/* Revenue Streams — Live */}
          {stats.stream_breakdown && stats.stream_breakdown.length > 0 && (
            <div style={{ marginTop: 20 }}>
              <h4 style={{ fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8 }}>
                REVENUE STREAMS — LIVE
              </h4>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {stats.stream_breakdown.map((s) => {
                  const label = s.stream === "FORECLOSURE_OVERBID" ? "Foreclosure Overbid (§ 38-38-111)"
                    : s.stream === "TAX_LIEN" ? "Tax Lien (§ 39-11-151)"
                    : s.stream === "TAX_DEED" ? "Tax Deed (§ 39-12-111)"
                    : s.stream === "HOA" ? "HOA (§ 38-33.3-316)"
                    : s.stream === "UNCLAIMED_PROPERTY" ? "Unclaimed Property (§ 38-13-1304)"
                    : s.stream;
                  const tooltipText = s.stream === "FORECLOSURE_OVERBID"
                    ? "Post-foreclosure overbid surplus. GovSoft scraper active across 12+ CO counties. Primary revenue stream."
                    : s.stream === "TAX_LIEN"
                    ? "Tax lien surplus under C.R.S. § 39-11-151. 5-year escheatment window. CSV import active."
                    : s.stream;
                  return (
                    <Tooltip key={s.stream} content={tooltipText} position="top">
                      <div style={{
                        background: "#111827", border: "1px solid #374151", borderRadius: 8,
                        padding: "12px 16px", minWidth: 200, cursor: "default",
                      }}>
                        <div style={{ fontSize: "0.7em", opacity: 0.5, marginBottom: 4 }}>{label}</div>
                        <div style={{ fontWeight: 700, color: "#22c55e" }}>{formatCurrencyShort(s.total)}</div>
                        <div style={{ fontSize: "0.78em", opacity: 0.5 }}>{s.cnt} leads</div>
                      </div>
                    </Tooltip>
                  );
                })}
              </div>

              {/* Coming Soon Streams */}
              <h4 style={{ fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.5, marginBottom: 8, marginTop: 20 }}>
                REVENUE STREAMS — COMING SOON
              </h4>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {[
                  {
                    key: "TAX_DEED",
                    label: "Tax Deed Surplus (§ 39-12-111)",
                    est: "$2–4M est. CO market",
                    desc: "Proceeds from county tax deed sales in excess of back taxes owed. 3-year claim window. Target: 15 CO counties with active treasurer auctions.",
                    eta: "Q2 2026",
                  },
                  {
                    key: "HOA",
                    label: "HOA Foreclosure Surplus (§ 38-33.3-316)",
                    est: "$800K–1.5M est. CO market",
                    desc: "Overbid proceeds from HOA lien foreclosure sales. High unit value per case. Target: Denver Metro HOA-dense subdivisions.",
                    eta: "Q3 2026",
                  },
                  {
                    key: "UNCLAIMED_PROPERTY",
                    label: "Unclaimed Property (§ 38-13-1304)",
                    est: "$180M+ CO state pool",
                    desc: "Colorado Great Unclaimed Property program. HB25-1224 caps attorney fees at 10%. Massive addressable pool — lowest competition of any stream.",
                    eta: "Q2 2026",
                  },
                ].map((s) => (
                  <Tooltip key={s.key} content={s.desc} position="top" maxWidth={300}>
                    <div style={{
                      background: "#0a0f1a", border: "1px dashed #374151", borderRadius: 8,
                      padding: "12px 16px", minWidth: 200, cursor: "default", opacity: 0.8,
                    }}>
                      <div style={{ fontSize: "0.7em", opacity: 0.4, marginBottom: 4 }}>{s.label}</div>
                      <div style={{ fontWeight: 700, color: "#4b5563", fontSize: "0.85em" }}>{s.est}</div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, alignItems: "center" }}>
                        <span style={{ fontSize: "0.65em", background: "#1e293b", color: "#64748b", padding: "2px 8px", borderRadius: 4, letterSpacing: "0.06em" }}>COMING {s.eta}</span>
                      </div>
                    </div>
                  </Tooltip>
                ))}
              </div>
            </div>
          )}
          <CountyCoverageTable counties={stats.counties} />
        </div>
      )}

      {/* View Mode Tabs (authenticated, non-preview) */}
      {!isPreview && user && (
        <div className="view-tabs">
          <button
            className={`view-tab ${viewMode === "actionable" ? "active" : ""}`}
            onClick={() => setViewMode("actionable")}
          >
            ACTIONABLE ({actionable.length})
          </button>
          <button
            className={`view-tab ${viewMode === "watchlist" ? "active" : ""}`}
            onClick={() => setViewMode("watchlist")}
          >
            WATCHLIST ({watchlist.length})
          </button>
          <button
            className={`view-tab ${viewMode === "my_leads" ? "active" : ""}`}
            onClick={() => setViewMode("my_leads")}
          >
            MY LEADS ({myLeads.length})
          </button>
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
            <option key={c} value={c.toLowerCase().replace(/ /g, "_")}>{c.replace(/_/g, " ").toUpperCase()}</option>
          ))}
        </select>

        <span className="grade-filter-label">GRADE</span>
        <div className="grade-filters">
          {[
            { value: "",       label: `ALL`,                tip: "Show all validated leads regardless of confidence grade" },
            { value: "GOLD",   label: `GOLD (${goldCount})`,   tip: "Math-confirmed overbid + provenance doc. Highest confidence. Ready for immediate attorney action." },
            { value: "SILVER", label: `SILVER (${silverCount})`, tip: "Probable overbid. Restriction window active or secondary validation pending. Monitor for promotion." },
            { value: "BRONZE", label: `BRONZE (${bronzeCount})`, tip: "Pre-validation. Gate 4 extraction in progress. Overbid likely but not yet confirmed by sale documents." },
          ].map((g) => (
            <Tooltip key={g.value || "ALL"} content={g.tip} position="top">
              <button
                className={`grade-filter-btn ${grade === g.value ? "active" : ""}`}
                onClick={() => { setGrade(g.value); setLoading(true); }}
              >
                {g.label}
              </button>
            </Tooltip>
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
          {/* MY LEADS view */}
          {viewMode === "my_leads" && (
            <div className="bucket-section">
              <div className="bucket-header actionable">
                <h2>MY LEADS — UNLOCKED INTEL</h2>
                <span className="bucket-count">{myLeads.length} leads</span>
                <p className="bucket-desc">
                  Leads you have unlocked. Full owner data and case details are available.
                </p>
              </div>
              {myLeads.length === 0 ? (
                <div className="center-content" style={{ paddingTop: 40 }}>
                  <p style={{ color: "#64748b" }}>No leads unlocked yet — browse the intelligence below</p>
                </div>
              ) : (
                <div className="vault-grid">
                  {myLeads.map((lead) => (
                    <LeadCard key={lead.asset_id} lead={lead} onNavigate={navigateToLead} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ACTIONABLE view */}
          {viewMode === "actionable" && actionable.length > 0 && (
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

          {/* WATCHLIST view */}
          {viewMode === "watchlist" && watchlist.length > 0 && (
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

          {/* Old dual-section view for preview/no-tabs */}
          {!user && actionable.length > 0 && (
            <div className="bucket-section">
              <div className="bucket-header actionable">
                <h2>ESCROW ENDED — ACTIONABLE</h2>
                <span className="bucket-count">{actionable.length} leads</span>
              </div>
              <div className="vault-grid">
                {actionable.map((lead) => (
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
