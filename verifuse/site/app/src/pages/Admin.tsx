import React, { useEffect, useState, useCallback, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { API_BASE, ApiError } from "../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AdminUser {
  user_id: string;
  email: string;
  full_name: string;
  firm_name: string;
  bar_number?: string;
  bar_state?: string;
  tier: string;
  credits_remaining: number;
  attorney_status?: string;
  role?: string;
  is_admin?: number;
  is_active?: number;
  email_verified?: number;
  created_at?: string;
  last_login_at?: string;
}

interface AdminLead {
  id: string;
  county: string;
  case_number?: string;
  owner_name?: string;
  property_address?: string;
  estimated_surplus?: number;
  data_grade?: string;
  sale_date?: string;
  surplus_stream?: string;
  restriction_status?: string;
}

interface CoverageCounty {
  county: string;
  county_code?: string;
  platform_type?: string;
  platform?: string;
  leads_count?: number;
  last_scraped_at?: string;
  last_run?: string;
  active?: boolean;
  enabled?: boolean;
  ran_24h?: boolean;
  silent_24h?: boolean;
  found_zero_24h?: boolean;
  last_error?: string | null;
  last_ingestion_ts?: number | string | null;
  gold?: number;
  silver?: number;
  bronze?: number;
  cases_processed?: number;
}

interface PipelineCounty {
  county: string;
  total: number;
  gold: number;
  silver: number;
  bronze: number;
  reject: number;
  bronze_no_sale_date: number;
  bronze_no_overbid?: number;
  bronze_not_extracted?: number;
  bronze_zero_overbid?: number;
  has_snapshots: number;
  platform_type: string | null;
  last_verified_ts: number | null;
  last_ingestion_ts?: number | string | null;
  action_needed: string;
}

interface CountyHealth {
  county: string;
  platform_type: string;
  total: number;
  gold: number;
  silver: number;
  bronze: number;
  gold_pct: number;
  health_score: number;
  sale_date_coverage_pct: number;
  extraction_rate_pct: number;
  evidence_pct: number;
  last_run_age_days: number | null;
  last_run_status: string | null;
  browser_count: number;
  db_count: number;
  delta: number;
  parser_drift: boolean;
  alert: string | null;
}

interface CountyHealthSummary {
  healthy: number;
  warning: number;
  critical: number;
  total: number;
}

interface ScoreboardEntry {
  data_grade: string;
  lead_count: number;
  total_surplus: number;
}

interface AuditEntry {
  id: string;
  user_email: string;
  action: string;
  created_at: string;
  ip?: string;
  meta?: Record<string, unknown>;
}

interface UserCounts {
  total: number;
  verified_attorneys: number;
  pending_attorneys: number;
  sovereign_users: number;
  partner_users: number;
  associate_users: number;
}

interface SystemStats {
  db_path: string;
  db_size_mb: number;
  wal_pages: number;
  total_leads: number;
  scoreboard: ScoreboardEntry[];
  verified_pipeline_count: number;
  verified_pipeline_surplus: number;
  recent_audit: AuditEntry[];
  user_counts: UserCounts;
  stripe_configured: boolean;
  stripe_publishable_configured: boolean;
  stripe_mode: string;
  build_id: string;
  verifuse_env: string;
  api_key_configured: boolean;
}

interface RevenueMetrics {
  mrr_cents: number;
  arr_cents: number;
  active_subscriptions: number;
  by_tier: Record<string, { count: number; mrr_cents: number }>;
  new_subscribers_30d: number;
  churn_30d: number;
  credit_utilization_pct: number;
  total_credits_granted: number;
  total_credits_used: number;
  founding_spots_claimed: number;
  founding_spots_total: number;
}

// ── API helpers ───────────────────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function adminFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || body.error?.message || res.statusText || "Request failed");
  }
  return res.json();
}

function formatCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function relTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString();
}

// ── Design tokens ─────────────────────────────────────────────────────────────

const BG = "#0d1117";
const BG2 = "#111827";
const BG3 = "#1a2332";
const BORDER = "#1f2937";
const BORDER2 = "#374151";
const TEXT = "#e5e7eb";
const TEXT_DIM = "#9ca3af";
const TEXT_MUTED = "#6b7280";
const GREEN = "#22c55e";
const AMBER = "#f59e0b";
const RED = "#ef4444";
const BLUE = "#3b82f6";

const GRADE_COLORS: Record<string, string> = {
  GOLD: AMBER, SILVER: "#94a3b8", BRONZE: "#b45309", REJECT: RED,
};

// ── Shared Components ─────────────────────────────────────────────────────────

function SectionHeader({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, borderBottom: `1px solid ${BORDER}`, paddingBottom: 8 }}>
      <h4 style={{ margin: 0, fontSize: "0.72em", letterSpacing: "0.1em", opacity: 0.5, textTransform: "uppercase" }}>{children}</h4>
      {action}
    </div>
  );
}

function StatCard({ label, value, sub, color, mono, dot, accent }: {
  label: string; value: string; sub?: string; color?: string; mono?: boolean; dot?: boolean; accent?: boolean;
}) {
  return (
    <div style={{
      border: `1px solid ${accent ? (color || GREEN) + "44" : BORDER2}`,
      borderRadius: 8, padding: "12px 16px", background: BG,
    }}>
      <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: TEXT_MUTED, textTransform: "uppercase", marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {dot && <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color || GREEN, flexShrink: 0 }} />}
        <span style={{ fontSize: "1.25em", fontWeight: 700, color: color || TEXT, fontFamily: mono ? "monospace" : "inherit" }}>{value}</span>
      </div>
      {sub && <div style={{ fontSize: "0.75em", color: TEXT_MUTED, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function Badge({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span style={{
      display: "inline-block", fontSize: "0.7em", fontWeight: 700, letterSpacing: "0.06em",
      padding: "2px 7px", borderRadius: 4,
      background: (color || TEXT_MUTED) + "22", color: color || TEXT_MUTED,
      border: `1px solid ${(color || TEXT_MUTED) + "44"}`,
    }}>
      {children}
    </span>
  );
}

function ActionMsg({ msg, error }: { msg: string; error?: boolean }) {
  if (!msg) return null;
  return (
    <div style={{
      marginBottom: 12, padding: "8px 14px", borderRadius: 6, fontSize: "0.82em",
      background: error ? "#1f121522" : "#0f1e1022",
      border: `1px solid ${error ? RED + "44" : GREEN + "44"}`,
      color: error ? RED : GREEN,
    }}>
      {msg}
    </div>
  );
}

function ConfirmModal({ title, message, onConfirm, onCancel, confirmLabel = "Confirm", danger = false }: {
  title: string; message: string; onConfirm: () => void; onCancel: () => void;
  confirmLabel?: string; danger?: boolean;
}) {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center",
      background: "rgba(0,0,0,0.7)",
    }}
      onClick={onCancel}
    >
      <div style={{
        background: BG2, border: `1px solid ${BORDER2}`, borderRadius: 10, padding: "24px 28px",
        maxWidth: 420, width: "90%", boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
      }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: "0 0 10px", fontSize: "1em", color: danger ? RED : TEXT }}>{title}</h3>
        <p style={{ margin: "0 0 20px", fontSize: "0.88em", color: TEXT_DIM, lineHeight: 1.5 }}>{message}</p>
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onCancel} style={{
            background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM,
            borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.82em",
          }}>Cancel</button>
          <button onClick={onConfirm} style={{
            background: danger ? RED + "22" : GREEN + "22",
            border: `1px solid ${danger ? RED : GREEN}44`,
            color: danger ? RED : GREEN,
            borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.82em", fontWeight: 700,
          }}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Attorney Queue ────────────────────────────────────────────────────────

function AttorneyQueue() {
  const [pending, setPending] = useState<AdminUser[]>([]);
  const [verified, setVerified] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [isError, setIsError] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<AdminUser | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [viewSection, setViewSection] = useState<"pending" | "verified">("pending");

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      adminFetch<{ users: AdminUser[] }>("/api/admin/users?attorney_status=PENDING"),
      adminFetch<{ users: AdminUser[] }>("/api/admin/users?attorney_status=VERIFIED"),
    ])
      .then(([p, v]) => { setPending(p.users); setVerified(v.users); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function approve(u: AdminUser) {
    setMsg(""); setIsError(false);
    try {
      await adminFetch("/api/admin/attorney/approve", { method: "POST", body: JSON.stringify({ user_id: u.user_id }) });
      setMsg(`✓ Approved ${u.email}`);
      load();
    } catch (e: unknown) {
      setMsg(e instanceof ApiError ? e.message : "Approve failed"); setIsError(true);
    }
  }

  async function confirmReject() {
    if (!rejectTarget) return;
    const u = rejectTarget;
    setRejectTarget(null);
    setMsg(""); setIsError(false);
    try {
      await adminFetch("/api/admin/attorney/reject", {
        method: "POST",
        body: JSON.stringify({ user_id: u.user_id, reason: rejectReason.trim() || "Does not meet verification requirements" }),
      });
      setMsg(`Rejected ${u.email}`); setIsError(false);
      load();
    } catch (e: unknown) {
      setMsg(e instanceof ApiError ? e.message : "Reject failed"); setIsError(true);
    }
    setRejectReason("");
  }

  if (loading) return <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>Loading...</p>;
  if (error) return <p style={{ color: RED, fontSize: "0.85em" }}>{error}</p>;

  const list = viewSection === "pending" ? pending : verified;

  return (
    <div>
      {rejectTarget && (
        <ConfirmModal
          title={`Reject ${rejectTarget.email}?`}
          message={rejectReason || "Attorney verification will be denied. The user will be notified."}
          onConfirm={confirmReject}
          onCancel={() => { setRejectTarget(null); setRejectReason(""); }}
          confirmLabel="Reject Attorney"
          danger
        />
      )}

      {/* Section selector */}
      <div style={{ display: "flex", gap: 0, marginBottom: 20, borderBottom: `1px solid ${BORDER}` }}>
        {[
          { key: "pending" as const, label: "PENDING", count: pending.length, color: AMBER },
          { key: "verified" as const, label: "VERIFIED", count: verified.length, color: GREEN },
        ].map(({ key, label, count, color }) => (
          <button key={key} onClick={() => setViewSection(key)} style={{
            background: "none", border: "none",
            borderBottom: viewSection === key ? `2px solid ${color}` : "2px solid transparent",
            color: viewSection === key ? color : TEXT_MUTED,
            padding: "8px 16px", fontSize: "0.75em", letterSpacing: "0.08em",
            cursor: "pointer", fontFamily: "monospace",
          }}>
            {label}
            <span style={{
              marginLeft: 6, background: `${color}22`, border: `1px solid ${color}44`,
              color, borderRadius: 10, padding: "1px 7px", fontSize: "0.85em",
            }}>{count}</span>
          </button>
        ))}
      </div>

      <ActionMsg msg={msg} error={isError} />

      {list.length === 0 ? (
        <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>
          {viewSection === "pending" ? "No pending applications." : "No verified attorneys."}
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {list.map((u) => (
            <div key={u.user_id} style={{
              border: `1px solid ${BORDER}`,
              borderLeft: `3px solid ${viewSection === "pending" ? AMBER : GREEN}`,
              borderRadius: 6, padding: "14px 16px",
              background: BG2,
              display: "grid", gridTemplateColumns: "1fr auto", gap: 12, alignItems: "center",
            }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: "0.92em" }}>{u.email}</span>
                  {u.email_verified ? <Badge color={GREEN}>EMAIL VERIFIED</Badge> : <Badge color={AMBER}>EMAIL UNVERIFIED</Badge>}
                  <Badge color={BLUE}>{(u.tier || "scout").toUpperCase()}</Badge>
                </div>
                <div style={{ fontSize: "0.82em", color: TEXT_DIM }}>
                  {u.full_name || "—"} · {u.firm_name || "No firm"}
                </div>
                <div style={{ fontSize: "0.78em", color: TEXT_MUTED, marginTop: 3 }}>
                  Bar #{u.bar_number || "—"} ({u.bar_state || "CO"}) · Joined {u.created_at?.slice(0, 10) || "—"} · Last login {relTime(u.last_login_at)}
                </div>
              </div>
              {viewSection === "pending" && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => approve(u)} style={{
                    background: `${GREEN}18`, border: `1px solid ${GREEN}44`, color: GREEN,
                    borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace",
                    fontSize: "0.78em", fontWeight: 700,
                  }}>APPROVE</button>
                  <button onClick={() => { setRejectTarget(u); setRejectReason(""); }} style={{
                    background: `${RED}18`, border: `1px solid ${RED}44`, color: RED,
                    borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace",
                    fontSize: "0.78em", fontWeight: 700,
                  }}>REJECT</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Rejection reason input - shown below when rejectTarget set */}
      {rejectTarget && (
        <div style={{ marginTop: 10 }}>
          <input
            placeholder="Rejection reason (optional)..."
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            style={{
              background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
              borderRadius: 6, padding: "8px 14px", fontSize: "0.85em",
              fontFamily: "monospace", width: "100%", boxSizing: "border-box",
            }}
          />
        </div>
      )}
    </div>
  );
}

// ── Tab: Leads ─────────────────────────────────────────────────────────────────

function LeadsTab() {
  const [leads, setLeads] = useState<AdminLead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [grade, setGrade] = useState("");
  const [county, setCounty] = useState("");
  const [offset, setOffset] = useState(0);
  const [gradeOverride, setGradeOverride] = useState<{ lead: AdminLead; newGrade: string; reason: string } | null>(null);
  const [msg, setMsg] = useState("");
  const PAGE = 100;

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (grade) params.set("grade", grade);
    if (county) params.set("county", county);
    params.set("limit", String(PAGE));
    params.set("offset", String(offset));
    adminFetch<{ leads: AdminLead[]; count: number }>(`/api/admin/leads?${params}`)
      .then((r) => { setLeads(r.leads); setTotal(r.count); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [grade, county, offset]);

  useEffect(() => { load(); }, [load]);

  async function submitGradeOverride() {
    if (!gradeOverride) return;
    try {
      await adminFetch(`/api/admin/leads/${gradeOverride.lead.id}/set-grade`, {
        method: "POST",
        body: JSON.stringify({ grade: gradeOverride.newGrade, reason: gradeOverride.reason }),
      });
      setMsg(`✓ Grade updated: ${gradeOverride.lead.case_number || gradeOverride.lead.id.slice(0, 8)} → ${gradeOverride.newGrade}`);
      setGradeOverride(null);
      load();
    } catch (e: unknown) {
      setMsg(e instanceof ApiError ? e.message : "Override failed");
    }
  }

  return (
    <div>
      {gradeOverride && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 1000, background: "rgba(0,0,0,0.7)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }} onClick={() => setGradeOverride(null)}>
          <div style={{
            background: BG2, border: `1px solid ${BORDER2}`, borderRadius: 10, padding: "24px 28px",
            maxWidth: 420, width: "90%",
          }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: "0 0 4px", fontSize: "0.95em" }}>Override Grade</h3>
            <p style={{ margin: "0 0 16px", fontSize: "0.82em", color: TEXT_MUTED }}>
              {gradeOverride.lead.county} · {gradeOverride.lead.case_number}
            </p>
            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              {["GOLD", "SILVER", "BRONZE", "REJECT"].map((g) => (
                <button key={g} onClick={() => setGradeOverride({ ...gradeOverride, newGrade: g })} style={{
                  flex: 1, background: gradeOverride.newGrade === g ? `${GRADE_COLORS[g]}22` : BG,
                  border: `1px solid ${gradeOverride.newGrade === g ? GRADE_COLORS[g] : BORDER2}`,
                  color: GRADE_COLORS[g], borderRadius: 6, padding: "6px 0", cursor: "pointer",
                  fontFamily: "monospace", fontSize: "0.75em", fontWeight: 700,
                }}>{g}</button>
              ))}
            </div>
            <input
              placeholder="Reason for override..."
              value={gradeOverride.reason}
              onChange={(e) => setGradeOverride({ ...gradeOverride, reason: e.target.value })}
              style={{
                width: "100%", boxSizing: "border-box", background: BG, border: `1px solid ${BORDER2}`,
                color: TEXT, borderRadius: 6, padding: "8px 12px", fontSize: "0.82em",
                fontFamily: "monospace", marginBottom: 16,
              }}
            />
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={() => setGradeOverride(null)} style={{
                background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM,
                borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.82em",
              }}>Cancel</button>
              <button onClick={submitGradeOverride} disabled={!gradeOverride.reason.trim()} style={{
                background: `${GREEN}18`, border: `1px solid ${GREEN}44`, color: GREEN,
                borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace",
                fontSize: "0.82em", fontWeight: 700, opacity: gradeOverride.reason.trim() ? 1 : 0.4,
              }}>APPLY OVERRIDE</button>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        {["", "GOLD", "SILVER", "BRONZE", "REJECT"].map((g) => (
          <button key={g || "ALL"} onClick={() => { setGrade(g); setOffset(0); }} style={{
            background: grade === g ? `${g ? GRADE_COLORS[g] : GREEN}18` : "none",
            border: `1px solid ${grade === g ? (g ? GRADE_COLORS[g] : GREEN) : BORDER2}`,
            color: grade === g ? (g ? GRADE_COLORS[g] : GREEN) : TEXT_DIM,
            borderRadius: 5, padding: "5px 12px", cursor: "pointer", fontFamily: "monospace",
            fontSize: "0.75em", fontWeight: 600,
          }}>{g || "ALL"}</button>
        ))}
        <input
          type="text" placeholder="Filter county…" value={county}
          onChange={(e) => { setCounty(e.target.value); setOffset(0); }}
          style={{
            background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
            padding: "5px 12px", borderRadius: 5, fontSize: "0.82em", fontFamily: "monospace", width: 160,
          }}
        />
        <span style={{ marginLeft: "auto", fontSize: "0.78em", color: TEXT_MUTED }}>
          {loading ? "…" : `${total.toLocaleString()} leads`}
        </span>
      </div>

      {msg && <ActionMsg msg={msg} />}

      {loading ? (
        <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>Loading leads...</p>
      ) : error ? (
        <p style={{ color: RED, fontSize: "0.85em" }}>{error}</p>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${BORDER2}` }}>
                  {["COUNTY", "CASE #", "OWNER / ADDRESS", "SURPLUS", "CONFIDENCE", "SALE DATE", "ACTIONS"].map((h) => (
                    <th key={h} style={{
                      textAlign: h === "SURPLUS" ? "right" : "left",
                      padding: "7px 10px", color: TEXT_MUTED, fontWeight: 600, fontSize: "0.82em",
                      letterSpacing: "0.06em",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leads.map((l) => (
                  <tr key={l.id} style={{ borderBottom: `1px solid ${BORDER}` }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = BG2)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <td style={{ padding: "7px 10px", color: TEXT_DIM, fontSize: "0.9em" }}>{l.county}</td>
                    <td style={{ padding: "7px 10px", fontFamily: "monospace", fontSize: "0.88em" }}>
                      <Link to={`/lead/${l.id}`} style={{ color: BLUE, textDecoration: "none" }}>
                        {l.case_number || l.id.slice(0, 12)}
                      </Link>
                    </td>
                    <td style={{ padding: "7px 10px", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      <span style={{ color: l.owner_name ? TEXT : TEXT_MUTED, fontSize: "0.9em" }}>
                        {l.owner_name || l.property_address || "—"}
                      </span>
                    </td>
                    <td style={{ padding: "7px 10px", textAlign: "right", color: (l.estimated_surplus ?? 0) > 0 ? GREEN : TEXT_MUTED, fontWeight: 600 }}>
                      {formatCurrency(l.estimated_surplus)}
                    </td>
                    <td style={{ padding: "7px 10px" }}>
                      <span style={{
                        fontSize: "0.75em", fontWeight: 700, padding: "2px 7px", borderRadius: 4,
                        background: `${GRADE_COLORS[l.data_grade || ""] || TEXT_MUTED}22`,
                        color: GRADE_COLORS[l.data_grade || ""] || TEXT_MUTED,
                      }}>{l.data_grade || "—"}</span>
                    </td>
                    <td style={{ padding: "7px 10px", color: TEXT_MUTED, fontSize: "0.88em" }}>{l.sale_date || "—"}</td>
                    <td style={{ padding: "7px 10px" }}>
                      <div style={{ display: "flex", gap: 4 }}>
                        <button onClick={() => setGradeOverride({ lead: l, newGrade: l.data_grade || "BRONZE", reason: "" })}
                          style={{
                            background: "none", border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
                            borderRadius: 4, padding: "3px 9px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.72em",
                          }}>
                          GRADE ↕
                        </button>
                        {/* B3: RTF promote button */}
                        <button
                          onClick={async () => {
                            if (!confirm(`Promote lead ${l.id?.slice(0, 8)} to READY_TO_FILE? All RTF gates will be validated.`)) return;
                            try {
                              const res = await fetch(`${API_BASE}/api/admin/leads/${l.id}/promote-rtf`, {
                                method: "POST",
                                headers: { Authorization: `Bearer ${localStorage.getItem("vf_token") || ""}` }
                              });
                              const body = await res.json().catch(() => ({}));
                              if (res.ok) alert("Lead promoted to READY_TO_FILE");
                              else alert(body.detail || "RTF gate failed — check lead fields");
                            } catch { alert("Request failed"); }
                          }}
                          style={{
                            padding: "3px 7px", fontSize: "0.7em",
                            background: "#14532d", border: "1px solid #16a34a",
                            color: "#4ade80", borderRadius: "0.25rem",
                            cursor: "pointer", fontFamily: "monospace",
                          }}
                        >
                          RTF
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {leads.length === 0 && (
              <p style={{ color: TEXT_MUTED, fontSize: "0.85em", marginTop: 16 }}>No leads found.</p>
            )}
          </div>

          {/* Pagination */}
          {total > PAGE && (
            <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 16, alignItems: "center" }}>
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
                style={{
                  background: BG2, border: `1px solid ${BORDER2}`, color: TEXT_DIM,
                  borderRadius: 5, padding: "5px 14px", cursor: offset === 0 ? "not-allowed" : "pointer",
                  opacity: offset === 0 ? 0.4 : 1, fontFamily: "monospace", fontSize: "0.8em",
                }}>← Prev</button>
              <span style={{ color: TEXT_MUTED, fontSize: "0.78em" }}>
                {offset + 1}–{Math.min(offset + PAGE, total)} of {total.toLocaleString()}
              </span>
              <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}
                style={{
                  background: BG2, border: `1px solid ${BORDER2}`, color: TEXT_DIM,
                  borderRadius: 5, padding: "5px 14px", cursor: offset + PAGE >= total ? "not-allowed" : "pointer",
                  opacity: offset + PAGE >= total ? 0.4 : 1, fontFamily: "monospace", fontSize: "0.8em",
                }}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Tab: Users ─────────────────────────────────────────────────────────────────

function UserRow({ u, onAction }: { u: AdminUser; onAction: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [msg, setMsg] = useState("");
  const [isErr, setIsErr] = useState(false);
  const [creditDelta, setCreditDelta] = useState("");
  const [creditNote, setCreditNote] = useState("");
  const [deactivateConfirm, setDeactivateConfirm] = useState(false);
  const [newRole, setNewRole] = useState(u.role || "public");
  const [generatedApiKey, setGeneratedApiKey] = useState<string | null>(null);

  async function generateApiKey(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      const res = await adminFetch<{ api_key: string }>(`/api/admin/users/${u.user_id}/generate-api-key`, { method: "POST" });
      setGeneratedApiKey(res.api_key);
    } catch (err: unknown) {
      setMsg(err instanceof ApiError ? err.message : "Failed to generate API key");
      setIsErr(true);
    }
  }

  async function toggleActive() {
    const endpoint = u.is_active ? "deactivate" : "activate";
    try {
      await adminFetch(`/api/admin/users/${u.user_id}/${endpoint}`, { method: "POST" });
      setMsg(`✓ User ${endpoint}d`); setIsErr(false);
      setDeactivateConfirm(false);
      onAction();
    } catch (e: unknown) { setMsg(e instanceof ApiError ? e.message : "Failed"); setIsErr(true); }
  }

  async function adjustCredits() {
    const delta = parseInt(creditDelta);
    if (isNaN(delta) || delta === 0) { setMsg("Enter a non-zero number"); setIsErr(true); return; }
    try {
      const res = await adminFetch<{ new_balance: number }>(`/api/admin/users/${u.user_id}/adjust-credits`, {
        method: "POST",
        body: JSON.stringify({ delta, note: creditNote || "Admin adjustment" }),
      });
      setMsg(`✓ Credits adjusted: new balance ${res.new_balance}`); setIsErr(false);
      setCreditDelta(""); setCreditNote("");
      onAction();
    } catch (e: unknown) { setMsg(e instanceof ApiError ? e.message : "Failed"); setIsErr(true); }
  }

  async function setRole() {
    try {
      await adminFetch(`/api/admin/users/${u.user_id}/set-role`, {
        method: "POST", body: JSON.stringify({ role: newRole }),
      });
      setMsg(`✓ Role set to ${newRole}`); setIsErr(false);
      onAction();
    } catch (e: unknown) { setMsg(e instanceof ApiError ? e.message : "Failed"); setIsErr(true); }
  }

  const isActive = u.is_active !== 0;
  const attColor = u.attorney_status === "VERIFIED" ? GREEN : u.attorney_status === "PENDING" ? AMBER : u.attorney_status === "REJECTED" ? RED : TEXT_MUTED;

  return (
    <>
      {deactivateConfirm && (
        <ConfirmModal
          title={`Deactivate ${u.email}?`}
          message="This user will be unable to log in. Their data is preserved and the action is reversible."
          onConfirm={toggleActive}
          onCancel={() => setDeactivateConfirm(false)}
          confirmLabel="Deactivate User"
          danger
        />
      )}
      <tr
        style={{ borderBottom: `1px solid ${BORDER}`, cursor: "pointer", background: expanded ? BG2 : "transparent" }}
        onClick={() => setExpanded(!expanded)}
        onMouseEnter={(e) => { if (!expanded) e.currentTarget.style.background = BG2; }}
        onMouseLeave={(e) => { if (!expanded) e.currentTarget.style.background = "transparent"; }}
      >
        <td style={{ padding: "10px 12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%", flexShrink: 0, display: "inline-block",
              background: isActive ? GREEN : RED,
            }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: "0.88em" }}>{u.email}</div>
              {u.firm_name && <div style={{ fontSize: "0.76em", color: TEXT_MUTED }}>{u.firm_name}</div>}
            </div>
          </div>
        </td>
        <td style={{ padding: "10px 12px" }}>
          <span style={{
            fontSize: "0.72em", fontWeight: 700, padding: "2px 8px", borderRadius: 4,
            background: `${BLUE}22`, color: BLUE, border: `1px solid ${BLUE}44`,
          }}>{(u.tier || "free").toUpperCase()}</span>
        </td>
        <td style={{ padding: "10px 12px", textAlign: "right", fontWeight: 700, color: (u.credits_remaining || 0) > 0 ? GREEN : TEXT_MUTED }}>
          {u.credits_remaining ?? "—"}
        </td>
        <td style={{ padding: "10px 12px" }}>
          <span style={{ fontSize: "0.75em", fontWeight: 700, color: attColor }}>
            {u.attorney_status || "NONE"}
          </span>
        </td>
        <td style={{ padding: "10px 12px", color: TEXT_MUTED, fontSize: "0.82em" }}>
          {u.role || "public"}
        </td>
        <td style={{ padding: "10px 12px", color: TEXT_MUTED, fontSize: "0.8em" }}>
          {relTime(u.last_login_at)}
        </td>
        <td style={{ padding: "10px 12px" }} onClick={(e) => e.stopPropagation()}>
          <button onClick={generateApiKey} style={{
            fontSize: "0.72em", padding: "2px 8px", background: "none",
            border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
            borderRadius: 4, cursor: "pointer", fontFamily: "monospace",
          }}>Generate</button>
          {generatedApiKey && (
            <div style={{
              position: "fixed", inset: 0, zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center",
              background: "rgba(0,0,0,0.7)",
            }} onClick={() => setGeneratedApiKey(null)}>
              <div style={{
                background: BG2, border: `1px solid ${AMBER}`, borderRadius: 10, padding: "24px 28px",
                maxWidth: 480, width: "90%",
              }} onClick={(ev) => ev.stopPropagation()}>
                <h3 style={{ margin: "0 0 8px", fontSize: "0.95em", color: AMBER }}>API Key Generated</h3>
                <p style={{ margin: "0 0 12px", fontSize: "0.82em", color: RED }}>Copy this key now — it will not be shown again.</p>
                <div style={{
                  background: BG, border: `1px solid ${BORDER2}`, borderRadius: 6,
                  padding: "10px 14px", fontFamily: "monospace", fontSize: "0.82em",
                  wordBreak: "break-all", color: GREEN, marginBottom: 16,
                }}>{generatedApiKey}</div>
                <button onClick={() => setGeneratedApiKey(null)} style={{
                  background: `${GREEN}18`, border: `1px solid ${GREEN}44`, color: GREEN,
                  borderRadius: 6, padding: "7px 20px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.82em",
                }}>Done</button>
              </div>
            </div>
          )}
        </td>
        <td style={{ padding: "10px 12px", textAlign: "right" }}>
          <span style={{ color: TEXT_MUTED, fontSize: "0.75em" }}>{expanded ? "▲" : "▼"}</span>
        </td>
      </tr>

      {/* Expanded detail panel */}
      {expanded && (
        <tr style={{ background: BG3 }}>
          <td colSpan={8} style={{ padding: "16px 20px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20 }}>

              {/* Info */}
              <div>
                <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 8 }}>USER DETAILS</div>
                <div style={{ fontSize: "0.82em", display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px" }}>
                  {[
                    ["ID", u.user_id.slice(0, 16) + "…"],
                    ["Name", u.full_name || "—"],
                    ["Bar #", u.bar_number ? `${u.bar_number} (${u.bar_state || "CO"})` : "—"],
                    ["Joined", u.created_at?.slice(0, 10) || "—"],
                    ["Email verified", u.email_verified ? "Yes" : "No"],
                  ].map(([k, v]) => (
                    <React.Fragment key={k}><span style={{ color: TEXT_MUTED }}>{k}:</span><span style={{ color: TEXT }}>{v}</span></React.Fragment>
                  ))}
                </div>
              </div>

              {/* Credits */}
              <div>
                <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 8 }}>ADJUST CREDITS</div>
                <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  <input type="number" placeholder="±delta (e.g. 10, -5)" value={creditDelta}
                    onChange={(e) => setCreditDelta(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      flex: 1, background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
                      borderRadius: 5, padding: "6px 10px", fontFamily: "monospace", fontSize: "0.82em",
                    }}
                  />
                  <button onClick={(e) => { e.stopPropagation(); adjustCredits(); }} style={{
                    background: `${GREEN}18`, border: `1px solid ${GREEN}44`, color: GREEN,
                    borderRadius: 5, padding: "6px 14px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em", fontWeight: 700,
                  }}>APPLY</button>
                </div>
                <input type="text" placeholder="Note (optional)" value={creditNote}
                  onChange={(e) => setCreditNote(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    width: "100%", boxSizing: "border-box", background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
                    borderRadius: 5, padding: "5px 10px", fontFamily: "monospace", fontSize: "0.78em",
                  }}
                />
              </div>

              {/* Role + Status */}
              <div>
                <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 8 }}>ROLE + ACCOUNT</div>
                <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                  <select value={newRole} onChange={(e) => setNewRole(e.target.value)} onClick={(e) => e.stopPropagation()}
                    style={{
                      flex: 1, background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
                      borderRadius: 5, padding: "6px 10px", fontFamily: "monospace", fontSize: "0.82em",
                    }}>
                    <option value="public">public</option>
                    <option value="approved_attorney">approved_attorney</option>
                    <option value="admin">admin</option>
                  </select>
                  <button onClick={(e) => { e.stopPropagation(); setRole(); }} style={{
                    background: `${BLUE}18`, border: `1px solid ${BLUE}44`, color: BLUE,
                    borderRadius: 5, padding: "6px 14px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em", fontWeight: 700,
                  }}>SET</button>
                </div>
                {!u.is_admin && (
                  isActive ? (
                    <button onClick={(e) => { e.stopPropagation(); setDeactivateConfirm(true); }} style={{
                      background: `${RED}18`, border: `1px solid ${RED}44`, color: RED,
                      borderRadius: 5, padding: "6px 14px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em", fontWeight: 700, width: "100%",
                    }}>DEACTIVATE USER</button>
                  ) : (
                    <button onClick={(e) => { e.stopPropagation(); toggleActive(); }} style={{
                      background: `${GREEN}18`, border: `1px solid ${GREEN}44`, color: GREEN,
                      borderRadius: 5, padding: "6px 14px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em", fontWeight: 700, width: "100%",
                    }}>REACTIVATE USER</button>
                  )
                )}
              </div>
            </div>

            {msg && <ActionMsg msg={msg} error={isErr} />}
          </td>
        </tr>
      )}
    </>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    adminFetch<{ users: AdminUser[] }>("/api/admin/users")
      .then((r) => setUsers(r.users))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = users.filter((u) => {
    if (search && !u.email.includes(search) && !(u.full_name || "").toLowerCase().includes(search.toLowerCase())) return false;
    if (roleFilter && u.role !== roleFilter) return false;
    if (statusFilter === "active" && u.is_active === 0) return false;
    if (statusFilter === "inactive" && u.is_active !== 0) return false;
    if (statusFilter === "pending" && u.attorney_status !== "PENDING") return false;
    if (statusFilter === "verified" && u.attorney_status !== "VERIFIED") return false;
    return true;
  });

  if (loading) return <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>Loading users...</p>;
  if (error) return <p style={{ color: RED, fontSize: "0.85em" }}>{error}</p>;

  return (
    <div>
      {/* Search + filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text" placeholder="Search email or name…" value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
            padding: "6px 12px", borderRadius: 6, fontSize: "0.84em", fontFamily: "monospace", width: 220,
          }}
        />
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} style={{
          background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
          padding: "6px 10px", borderRadius: 6, fontSize: "0.82em", fontFamily: "monospace",
        }}>
          <option value="">All roles</option>
          <option value="public">public</option>
          <option value="approved_attorney">approved_attorney</option>
          <option value="admin">admin</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{
          background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
          padding: "6px 10px", borderRadius: 6, fontSize: "0.82em", fontFamily: "monospace",
        }}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
          <option value="pending">Atty Pending</option>
          <option value="verified">Atty Verified</option>
        </select>
        <span style={{ marginLeft: "auto", fontSize: "0.78em", color: TEXT_MUTED }}>
          {filtered.length} of {users.length} users
        </span>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84em" }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BORDER2}` }}>
              {["EMAIL / FIRM", "TIER", "CREDITS", "ATTY STATUS", "ROLE", "LAST LOGIN", "API KEY", ""].map((h) => (
                <th key={h} style={{
                  textAlign: h === "CREDITS" ? "right" : "left",
                  padding: "7px 12px", color: TEXT_MUTED, fontWeight: 600,
                  fontSize: "0.78em", letterSpacing: "0.06em",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <UserRow key={u.user_id} u={u} onAction={load} />
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <p style={{ color: TEXT_MUTED, fontSize: "0.85em", marginTop: 16 }}>No users match filters.</p>
        )}
      </div>
    </div>
  );
}

// ── Tab: System ────────────────────────────────────────────────────────────────

type SystemSubTab = "operations" | "engineering";

function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const PAGE = 50;

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (filter) params.set("action", filter);
    adminFetch<{ entries: AuditEntry[]; total: number }>(`/api/admin/audit-log?${params}`)
      .then((r) => setEntries(r.entries))
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [filter, offset]);

  useEffect(() => { load(); }, [load]);

  const FILTER_OPTIONS = ["all", "unlock", "login", "register", "dossier_generated"] as const;

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
        {FILTER_OPTIONS.map((opt) => (
          <button key={opt} onClick={() => { setFilter(opt === "all" ? "" : opt); setOffset(0); }} style={{
            background: (filter === opt || (opt === "all" && !filter)) ? `${GREEN}18` : "none",
            border: `1px solid ${(filter === opt || (opt === "all" && !filter)) ? GREEN : BORDER2}`,
            color: (filter === opt || (opt === "all" && !filter)) ? GREEN : TEXT_MUTED,
            borderRadius: 5, padding: "3px 10px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.72em", fontWeight: 600,
          }}>{opt.toUpperCase()}</button>
        ))}
        <input
          type="text" placeholder="Custom filter…" value={filter}
          onChange={(e) => { setFilter(e.target.value); setOffset(0); }}
          style={{
            background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
            padding: "4px 10px", borderRadius: 5, fontSize: "0.78em", fontFamily: "monospace", width: 160,
          }}
        />
        <button onClick={load} style={{
          background: "none", border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
          borderRadius: 5, padding: "5px 12px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em",
        }}>↻ Refresh</button>
      </div>

      {loading ? (
        <p style={{ color: TEXT_MUTED, fontSize: "0.82em" }}>Loading...</p>
      ) : entries.length === 0 ? (
        <p style={{ color: TEXT_MUTED, fontSize: "0.82em" }}>No entries.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78em" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${BORDER2}` }}>
                {["TIMESTAMP", "USER", "ACTION", "IP", "DETAILS"].map((h) => (
                  <th key={h} style={{ textAlign: "left", padding: "5px 10px", color: TEXT_MUTED, fontWeight: 600, fontSize: "0.85em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} style={{ borderBottom: `1px solid ${BORDER}` }}>
                  <td style={{ padding: "5px 10px", color: TEXT_MUTED, whiteSpace: "nowrap" }}>{e.created_at?.slice(0, 19).replace("T", " ")}</td>
                  <td style={{ padding: "5px 10px", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis" }}>{e.user_email}</td>
                  <td style={{ padding: "5px 10px" }}>
                    <span style={{
                      fontFamily: "monospace", fontSize: "0.88em",
                      color: e.action.includes("unlock") || e.action.includes("approv") ? GREEN
                        : e.action.includes("reject") || e.action.includes("fail") || e.action.includes("deactiv") ? RED
                        : e.action.includes("login") ? BLUE
                        : TEXT_DIM,
                    }}>{e.action}</span>
                  </td>
                  <td style={{ padding: "5px 10px", color: TEXT_MUTED }}>{e.ip || "—"}</td>
                  <td style={{ padding: "5px 10px", color: TEXT_MUTED, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", fontSize: "0.88em" }}>
                    {e.meta ? Object.entries(e.meta).slice(0, 3).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ") : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 10 }}>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
              style={{ background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM, borderRadius: 5, padding: "4px 12px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.75em", opacity: offset === 0 ? 0.4 : 1 }}>← Prev</button>
            <button disabled={entries.length < PAGE} onClick={() => setOffset(offset + PAGE)}
              style={{ background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM, borderRadius: 5, padding: "4px 12px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.75em", opacity: entries.length < PAGE ? 0.4 : 1 }}>Next →</button>
          </div>
        </div>
      )}
    </div>
  );
}

function SystemTab() {
  const [coverage, setCoverage] = useState<CoverageCounty[]>([]);
  const [pipeline, setPipeline] = useState<PipelineCounty[]>([]);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [rev, setRev] = useState<RevenueMetrics | null>(null);
  const [countyHealth, setCountyHealth] = useState<CountyHealth[] | null>(null);
  const [healthSummary, setHealthSummary] = useState<CountyHealthSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [subTab, setSubTab] = useState<SystemSubTab>("operations");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // A8: Override log state
  const [overrideLog, setOverrideLog] = useState<any[]>([]);

  const load = useCallback(() => {
    Promise.all([
      adminFetch<{ counties: CoverageCounty[] }>("/api/admin/coverage").then((r) => setCoverage(r.counties || [])).catch(() => setCoverage([])),
      adminFetch<{ pipeline: PipelineCounty[] }>("/api/admin/pipeline-status").then((r) => setPipeline(r.pipeline || [])).catch(() => setPipeline([])),
      adminFetch<SystemStats>("/api/admin/system-stats").then(setStats).catch((e) => setError(e.message)),
      adminFetch<RevenueMetrics>("/api/admin/revenue-metrics").then(setRev).catch(() => setRev(null)),
      adminFetch<{ counties: CountyHealth[]; summary: CountyHealthSummary }>("/api/admin/county-health")
        .then((r) => { setCountyHealth(r.counties || []); setHealthSummary(r.summary); })
        .catch(() => setCountyHealth(null)),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 60_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [load]);

  if (loading) return <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>Loading system status...</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

      {/* Sub-tab toggle */}
      <div style={{ display: "flex", gap: 0, borderBottom: `1px solid ${BORDER}` }}>
        {(["operations", "engineering"] as SystemSubTab[]).map((st) => (
          <button key={st} onClick={() => setSubTab(st)} style={{
            background: "none", border: "none",
            borderBottom: subTab === st ? `2px solid ${GREEN}` : "2px solid transparent",
            color: subTab === st ? GREEN : TEXT_MUTED,
            padding: "8px 18px", fontSize: "0.75em", letterSpacing: "0.08em",
            cursor: "pointer", fontFamily: "monospace", textTransform: "uppercase",
          }}>{st}</button>
        ))}
        <button onClick={load} style={{
          marginLeft: "auto", background: "none", border: "none", color: TEXT_MUTED,
          cursor: "pointer", fontSize: "0.75em", padding: "8px 12px", fontFamily: "monospace",
        }}>↻ refresh</button>
      </div>

      {/* ── OPERATIONS tab ── */}
      {subTab === "operations" && (
        <>
          <section>
            <SectionHeader>REVENUE</SectionHeader>
            {/* Stripe mode context banner */}
            {stats?.stripe_mode === "test" && (
              <div style={{
                marginBottom: 14, padding: "8px 14px", borderRadius: 6,
                background: "#1e1a0022", border: `1px solid ${AMBER}44`,
                fontSize: "0.78em", color: AMBER, display: "flex", alignItems: "center", gap: 8,
              }}>
                <span style={{ fontWeight: 700 }}>⚠ STRIPE TEST MODE</span>
                <span style={{ color: TEXT_MUTED }}>— No live charges. All subscriptions shown are from test data only. Switch STRIPE_MODE=live to process real payments.</span>
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 16 }}>
              <StatCard label="MRR" value={`$${((rev?.mrr_cents || 0) / 100).toLocaleString()}`} color={(rev?.mrr_cents ?? 0) > 0 ? GREEN : TEXT_MUTED} accent={(rev?.mrr_cents ?? 0) > 0} sub={stats?.stripe_mode === "test" ? "test mode" : undefined} />
              <StatCard label="ARR" value={`$${((rev?.arr_cents || 0) / 100).toLocaleString()}`} color={(rev?.arr_cents ?? 0) > 0 ? GREEN : TEXT_MUTED} />
              <StatCard label="Active Subs" value={String(rev?.active_subscriptions ?? 0)} color={(rev?.active_subscriptions ?? 0) > 0 ? BLUE : TEXT_MUTED} sub={(rev?.active_subscriptions ?? 0) === 0 ? "no paying subscribers yet" : undefined} />
              <StatCard label="New (30d)" value={String(rev?.new_subscribers_30d ?? 0)} color={BLUE} />
              <StatCard label="Churn (30d)" value={String(rev?.churn_30d ?? 0)} color={(rev?.churn_30d ?? 0) > 0 ? RED : GREEN} />
              <StatCard label="Credit Util" value={`${rev?.credit_utilization_pct ?? 0}%`} />
              <StatCard label="Founding Spots" value={`${rev?.founding_spots_claimed ?? 0} / ${rev?.founding_spots_total ?? 10}`} color={AMBER} sub={(rev?.founding_spots_claimed ?? 0) === 0 ? "none claimed yet" : `${(rev?.founding_spots_total ?? 10) - (rev?.founding_spots_claimed ?? 0)} remaining`} />
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {(["sovereign", "partner", "associate"] as const).map((tier) => {
                const tierData = rev?.by_tier?.[tier];
                const count = tierData?.count ?? 0;
                return (
                  <div key={tier} style={{ flex: 1, minWidth: 140, background: BG, border: `1px solid ${count > 0 ? BLUE + "44" : BORDER2}`, borderRadius: 8, padding: "12px 16px" }}>
                    <div style={{ color: TEXT_MUTED, fontSize: "0.7em", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{tier}</div>
                    <div style={{ fontWeight: 700, fontSize: "1.2em", color: count > 0 ? TEXT : TEXT_MUTED }}>{count} users</div>
                    <div style={{ color: count > 0 ? GREEN : TEXT_MUTED, fontSize: "0.82em" }}>${((tierData?.mrr_cents ?? 0) / 100).toLocaleString()}/mo</div>
                    <span style={{ fontSize: "0.7em", color: TEXT_MUTED }}>• Powered by Stripe</span>
                  </div>
                );
              })}
            </div>
          </section>

          <section>
            <SectionHeader>USERS + BILLING</SectionHeader>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
              <StatCard label="Total Users" value={stats?.user_counts?.total?.toString() || "—"} />
              <StatCard label="Verified Attorneys" value={stats?.user_counts?.verified_attorneys?.toString() || "—"} color={GREEN} />
              <StatCard label="Pending Attorneys" value={stats?.user_counts?.pending_attorneys?.toString() || "—"} color={AMBER} />
              <StatCard label="Pipeline Leads" value={stats?.verified_pipeline_count?.toString() || "—"} />
              <StatCard label="Pipeline Surplus" value={stats ? formatCurrency(stats.verified_pipeline_surplus) : "—"} color={GREEN} accent />
              <StatCard label="Stripe" value={stats?.stripe_configured ? `${(stats?.stripe_mode || "test").toUpperCase()} MODE` : "NOT SET"} color={stats?.stripe_configured ? stats?.stripe_mode === "live" ? GREEN : AMBER : RED} dot />
            </div>
          </section>

          {/* Data Intelligence */}
          <section>
            <SectionHeader>DATA INTELLIGENCE</SectionHeader>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
              <StatCard label="GOLD Leads" value={stats?.scoreboard?.find(s => s.data_grade === "GOLD")?.lead_count?.toString() || "0"} color={AMBER} accent sub={stats?.scoreboard?.find(s => s.data_grade === "GOLD") ? formatCurrency(stats?.scoreboard?.find(s => s.data_grade === "GOLD")?.total_surplus ?? 0) + " verified" : undefined} />
              <StatCard label="SILVER Leads" value={stats?.scoreboard?.find(s => s.data_grade === "SILVER")?.lead_count?.toString() || "0"} color="#94a3b8" sub={stats?.scoreboard?.find(s => s.data_grade === "SILVER") ? formatCurrency(stats?.scoreboard?.find(s => s.data_grade === "SILVER")?.total_surplus ?? 0) : undefined} />
              <StatCard label="BRONZE Leads" value={stats?.scoreboard?.find(s => s.data_grade === "BRONZE")?.lead_count?.toString() || "0"} color="#b45309" sub="pending Gate 4" />
              <StatCard label="CO Counties" value="64" color={BLUE} sub={`${pipeline.filter(p => p.total > 0).length} with data`} />
              <StatCard label="Coverage" value={`${Math.round(pipeline.filter(p => p.total > 0).length / 64 * 100)}%`} color={pipeline.filter(p => p.total > 0).length >= 20 ? GREEN : AMBER} sub="of 64 CO counties" />
            </div>
          </section>
        </>
      )}

      {/* ── ENGINEERING tab ── */}
      {subTab === "engineering" && (
        <>
          <section>
            <SectionHeader>API + DATABASE</SectionHeader>
            {error && <p style={{ color: RED, fontSize: "0.8em", marginBottom: 10 }}>{error}</p>}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
              <StatCard label="API Status" value="LIVE" color={GREEN} dot />
              <StatCard label="Env" value={(stats?.verifuse_env || "—").toUpperCase()} />
              <StatCard label="Build" value={stats?.build_id || "—"} mono />
              <StatCard label="DB Size" value={stats ? `${stats.db_size_mb} MB` : "—"} />
              <StatCard label="WAL Pages" value={stats?.wal_pages?.toString() || "—"} />
              <StatCard label="Total Leads" value={stats?.total_leads?.toLocaleString() || "—"} />
            </div>
          </section>

          {/* Scoreboard */}
          {stats?.scoreboard && stats.scoreboard.length > 0 && (
            <section>
              <SectionHeader>LEAD SCOREBOARD</SectionHeader>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                {stats.scoreboard.map((s) => (
                  <div key={s.data_grade} style={{
                    border: `1px solid ${(GRADE_COLORS[s.data_grade] || TEXT_MUTED) + "33"}`,
                    borderRadius: 6, padding: "10px 14px", background: BG,
                  }}>
                    <div style={{ fontSize: "0.7em", letterSpacing: "0.08em", color: TEXT_MUTED, marginBottom: 4 }}>{s.data_grade}</div>
                    <div style={{ fontSize: "1.4em", fontWeight: 700, color: GRADE_COLORS[s.data_grade] || TEXT }}>{s.lead_count.toLocaleString()}</div>
                    <div style={{ fontSize: "0.78em", color: TEXT_MUTED, marginTop: 2 }}>{formatCurrency(s.total_surplus)}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* County Pipeline Intelligence */}
          <section>
            <SectionHeader>COUNTY PIPELINE — ALL 64 COLORADO COUNTIES ({pipeline.length > 0 ? pipeline.length : coverage.length} configured)</SectionHeader>
            {pipeline.length === 0 && coverage.length === 0 ? (
              <p style={{ color: TEXT_MUTED, fontSize: "0.85em" }}>No coverage data.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78em" }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${BORDER2}` }}>
                      {[
                        { h: "COUNTY", right: false },
                        { h: "PLATFORM", right: false },
                        { h: "TOTAL", right: true },
                        { h: "GOLD", right: true },
                        { h: "SILVER", right: true },
                        { h: "BRONZE", right: true },
                        { h: "GOLD%", right: true },
                        { h: "HEALTH", right: true },
                        { h: "STATUS", right: false },
                        { h: "LAST RUN", right: false },
                      ].map(({ h, right }) => (
                        <th key={h} style={{
                          textAlign: right ? "right" : "left",
                          padding: "5px 10px", color: TEXT_MUTED, fontWeight: 600, fontSize: "0.85em",
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pipeline.length > 0 ? (
                      (() => {
                        const coverageByCounty: Record<string, CoverageCounty> = {};
                        coverage.forEach((c) => { coverageByCounty[(c.county_code || c.county || "").toLowerCase()] = c; });

                        function lastRunLabel(ts: number | string | null | undefined): { text: string; color: string } {
                          if (!ts) return { text: "NEVER", color: RED };
                          // ts may be a unix timestamp (integer seconds) or ISO string
                          const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
                          const daysAgo = Math.floor((Date.now() - d.getTime()) / 86400000);
                          if (daysAgo < 1) return { text: "TODAY", color: GREEN };
                          if (daysAgo <= 7) return { text: `${daysAgo}d ago`, color: GREEN };
                          if (daysAgo <= 30) return { text: `${daysAgo}d ago`, color: AMBER };
                          return { text: `${daysAgo}d ago`, color: RED };
                        }

                        return pipeline.map((p) => {
                          const cov = coverageByCounty[p.county.toLowerCase()] || {};
                          const actionColor = p.action_needed === "clean" || p.action_needed === "no_surplus" ? GREEN
                            : p.action_needed === "gate4_ready" ? AMBER
                            : p.action_needed === "sale_info_backfill_needed" ? "#f97316"
                            : p.action_needed === "captcha_blocked" ? RED
                            : p.total === 0 ? TEXT_MUTED
                            : TEXT_MUTED;
                          const actionTooltip = p.action_needed === "sale_info_backfill_needed"
                            ? `>50% of ${p.bronze} BRONZE leads are missing sale_date. Run: bin/vf gate4-run ${p.county}`
                            : p.action_needed === "gate4_ready" ? `${p.bronze_not_extracted} leads ready for Gate 4 extraction. Run: bin/vf gate4-run ${p.county}`
                            : p.action_needed === "captcha_blocked" ? "County website requires CAPTCHA — manual review needed"
                            : p.total === 0 ? "No leads ingested yet for this county"
                            : "";
                          const actionLabel = p.action_needed === "clean" ? "✓ CLEAN"
                            : p.action_needed === "no_surplus" ? "✓ $0 OVERBID"
                            : p.action_needed === "gate4_ready" ? "→ GATE 4"
                            : p.action_needed === "sale_info_backfill_needed" ? "⟳ NEEDS SALE DATE"
                            : p.action_needed === "captcha_blocked" ? "✗ CAPTCHA"
                            : p.total === 0 ? "— NO DATA"
                            : p.action_needed.replace(/_/g, " ").toUpperCase();
                          const goldPct = (p.gold + p.silver + p.bronze) > 0
                            ? Math.round(p.gold / (p.gold + p.silver + p.bronze) * 100)
                            : 0;
                          const goldPctColor = goldPct >= 30 ? GREEN : goldPct >= 10 ? AMBER : TEXT_MUTED;
                          const runInfo = lastRunLabel(p.last_ingestion_ts ?? cov.last_scraped_at ?? cov.last_run);
                          return (
                            <tr key={p.county} style={{ borderBottom: `1px solid ${BORDER}`, opacity: p.total === 0 ? 0.55 : 1 }}>
                              <td style={{ padding: "6px 10px", fontWeight: 600 }}>{p.county.replace(/_/g, " ").toUpperCase()}</td>
                              <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.75em" }}>
                                {(p.platform_type || cov.platform || "unknown").replace(/_/g, " ")}
                              </td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: p.total > 0 ? TEXT : TEXT_MUTED, fontSize: "0.85em" }}>{p.total || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: "#f59e0b", fontWeight: p.gold > 0 ? 700 : 400 }}>{p.gold || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: "#94a3b8", fontWeight: p.silver > 0 ? 700 : 400 }}>{p.silver || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>{p.bronze || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: goldPctColor, fontWeight: goldPct >= 10 ? 700 : 400, fontSize: "0.8em" }}>
                                {(p.gold + p.silver + p.bronze) > 0 ? `${goldPct}%` : "—"}
                              </td>
                              {/* E2: County Health Score */}
                              <td style={{ padding: "6px 10px", textAlign: "right" }}>
                                {(() => {
                                  const total = (p.gold || 0) + (p.silver || 0) + (p.bronze || 0) + (p.reject || 0);
                                  const gpct = total > 0 ? (p.gold || 0) / total : 0;
                                  const recency = p.last_verified_ts ? (Date.now()/1000 - p.last_verified_ts) < 86400 ? 1.0 : (Date.now()/1000 - p.last_verified_ts) < 259200 ? 0.5 : 0.0 : 0.0;
                                  const health = Math.round((gpct * 0.7 + recency * 0.3) * 100);
                                  const hColor = health >= 80 ? GREEN : health >= 50 ? AMBER : RED;
                                  return <span style={{ color: hColor, fontWeight: 600, fontSize: "0.8em" }}>{health}%</span>;
                                })()}
                              </td>
                              <td style={{ padding: "6px 10px" }}>
                                <span title={actionTooltip} style={{ color: actionColor, fontWeight: 700, fontSize: "0.8em", letterSpacing: "0.04em", cursor: actionTooltip ? "help" : "default" }}>{actionLabel}</span>
                              </td>
                              <td style={{ padding: "6px 10px" }}>
                                <span style={{ color: runInfo.color, fontWeight: 600, fontSize: "0.8em" }}>{runInfo.text}</span>
                              </td>
                            </tr>
                          );
                        });
                      })()
                    ) : (
                      // Fallback: coverage-only table
                      coverage.map((c) => (
                        <tr key={c.county_code || c.county} style={{ borderBottom: `1px solid ${BORDER}` }}>
                          <td style={{ padding: "6px 10px", fontWeight: 600 }}>{(c.county || c.county_code || "—").toUpperCase()}</td>
                          <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.75em" }}>{c.platform_type || c.platform || "—"}</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>—</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: "#f59e0b" }}>{c.gold || "—"}</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: "#94a3b8" }}>{c.silver || "—"}</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>{c.bronze || "—"}</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>—</td>
                          <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>—</td>
                          <td style={{ padding: "6px 10px" }}>—</td>
                          <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.8em" }}>
                            {(c.last_scraped_at || c.last_run)?.slice(0, 10) || "NEVER"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Audit log */}
          <section>
            <SectionHeader>AUDIT LOG</SectionHeader>
            <AuditLog />
          </section>

          {/* A8: Admin Override Log */}
          <section>
            <SectionHeader
              action={
                <button
                  onClick={() => {
                    adminFetch<{ entries: any[] }>("/api/admin/override-log")
                      .then((d) => setOverrideLog(d.entries || []))
                      .catch(() => {});
                  }}
                  style={{ padding: "0.25rem 0.625rem", fontSize: "0.75rem", background: BG2, border: `1px solid ${BORDER2}`, color: TEXT, borderRadius: "0.25rem", cursor: "pointer", fontFamily: "monospace" }}
                >
                  LOAD
                </button>
              }
            >
              ADMIN OVERRIDE LOG
            </SectionHeader>
            {overrideLog.length > 0 ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${BORDER2}`, color: TEXT_MUTED }}>
                    <th style={{ textAlign: "left", padding: "0.375rem" }}>ACTION</th>
                    <th style={{ textAlign: "left", padding: "0.375rem" }}>LEAD</th>
                    <th style={{ textAlign: "left", padding: "0.375rem" }}>REASON</th>
                    <th style={{ textAlign: "left", padding: "0.375rem" }}>TIMESTAMP</th>
                  </tr>
                </thead>
                <tbody>
                  {overrideLog.map((entry: any, i: number) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${BORDER}` }}>
                      <td style={{ padding: "0.375rem", color: entry.action === "admin_force_unlock" ? RED : AMBER }}>
                        {entry.action}
                      </td>
                      <td style={{ padding: "0.375rem" }}>{entry.target_lead_id || "—"}</td>
                      <td style={{ padding: "0.375rem", color: TEXT_MUTED }}>{entry.reason_code || "—"}</td>
                      <td style={{ padding: "0.375rem", color: TEXT_MUTED, fontSize: "0.73rem" }}>
                        {entry.created_ts ? new Date(entry.created_ts * 1000).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{ color: TEXT_MUTED, fontSize: "0.8rem" }}>Click LOAD to view override log entries.</p>
            )}
          </section>

          {/* Scraper Health (2G) */}
          <section>
            <SectionHeader>SCRAPER HEALTH</SectionHeader>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", fontSize: "0.8em", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ color: TEXT_MUTED, textAlign: "left" }}>
                    <th style={{ padding: "0.375rem 0.5rem" }}>COUNTY</th>
                    <th style={{ padding: "0.375rem 0.5rem" }}>PLATFORM</th>
                    <th style={{ padding: "0.375rem 0.5rem" }}>LAST RUN</th>
                    <th style={{ padding: "0.375rem 0.5rem" }}>CASES</th>
                    <th style={{ padding: "0.375rem 0.5rem" }}>HEALTH</th>
                  </tr>
                </thead>
                <tbody>
                  {(pipeline || []).filter(p => p.platform_type === "govsoft" || p.total > 0).map((p: PipelineCounty) => {
                    const ts = p.last_ingestion_ts;
                    let daysAgo: number | null = null;
                    if (ts) {
                      const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
                      daysAgo = Math.floor((Date.now() - d.getTime()) / 86400000);
                    }
                    const status = daysAgo == null ? "NEVER RUN" : daysAgo === 0 ? "OK" : daysAgo <= 7 ? "WARN" : "STALE";
                    const statusColor = status === "OK" ? GREEN : status === "WARN" ? AMBER : RED;
                    return (
                      <tr key={p.county} style={{ borderBottom: `1px solid ${BORDER}` }}>
                        <td style={{ padding: "0.375rem 0.5rem", fontWeight: 600 }}>{p.county?.replace(/_/g, " ").toUpperCase()}</td>
                        <td style={{ padding: "0.375rem 0.5rem", color: TEXT_MUTED, fontSize: "0.85em" }}>
                          {p.platform_type || "unknown"}
                        </td>
                        <td style={{ padding: "0.375rem 0.5rem", color: TEXT_MUTED }}>
                          {daysAgo != null ? `${daysAgo}d ago` : "Never"}
                        </td>
                        <td style={{ padding: "0.375rem 0.5rem", color: TEXT_MUTED }}>{p.total > 0 ? p.total.toLocaleString() : "—"}</td>
                        <td style={{ padding: "0.375rem 0.5rem", color: statusColor, fontWeight: 700, fontSize: "0.78em" }}>
                          {status}
                        </td>
                      </tr>
                    );
                  })}
                  {pipeline.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: "0.75rem 0.5rem", color: TEXT_MUTED }}>No scraper data available.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* County Intelligence (Layer 6) */}
          <section>
            <SectionHeader>COUNTY INTELLIGENCE</SectionHeader>
            {countyHealth === null ? (
              <p style={{ color: TEXT_MUTED, fontSize: "0.82em" }}>Loading health data...</p>
            ) : (
              <>
                {/* Summary bar */}
                {healthSummary && (
                  <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
                    {([
                      { label: "HEALTHY", value: healthSummary.healthy, color: GREEN },
                      { label: "WARNING", value: healthSummary.warning, color: AMBER },
                      { label: "CRITICAL", value: healthSummary.critical, color: RED },
                      { label: "TOTAL", value: healthSummary.total, color: TEXT_DIM },
                    ] as { label: string; value: number; color: string }[]).map(({ label, value, color }) => (
                      <div key={label} style={{ flex: 1, minWidth: 100, background: BG, border: `1px solid ${color}33`, borderRadius: 8, padding: "10px 14px" }}>
                        <div style={{ fontSize: "0.65em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 4 }}>{label}</div>
                        <div style={{ fontSize: "1.4em", fontWeight: 700, color }}>{value}</div>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.78em", borderCollapse: "collapse", minWidth: 700 }}>
                    <thead>
                      <tr style={{ color: TEXT_MUTED, textAlign: "left", borderBottom: `1px solid ${BORDER2}` }}>
                        <th style={{ padding: "4px 8px" }}>COUNTY</th>
                        <th style={{ padding: "4px 8px" }}>HEALTH</th>
                        <th style={{ padding: "4px 8px", textAlign: "right" }}>SALE DATE COV</th>
                        <th style={{ padding: "4px 8px", textAlign: "right" }}>EXTRACTION</th>
                        <th style={{ padding: "4px 8px", textAlign: "right" }}>EVIDENCE</th>
                        <th style={{ padding: "4px 8px", textAlign: "right" }}>BROWSER/DB</th>
                        <th style={{ padding: "4px 8px", textAlign: "right" }}>LAST RUN</th>
                        <th style={{ padding: "4px 8px" }}>ALERT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {countyHealth.filter(c => c.total > 0).map((c) => {
                        const hColor = c.health_score >= 70 ? GREEN : c.health_score >= 40 ? AMBER : RED;
                        const alertColor = c.alert === "NO_DATA" || c.alert === "STALE_30D" || c.alert === "PARSER_DRIFT" ? RED
                          : c.alert === "STALE_7D" || c.alert === "ALL_BRONZE" ? AMBER : TEXT_MUTED;
                        return (
                          <tr key={c.county} style={{ borderBottom: `1px solid ${BORDER}` }}>
                            <td style={{ padding: "5px 8px", fontWeight: 600 }}>
                              {c.county.replace(/_/g, " ").toUpperCase()}
                              <span style={{ marginLeft: 6, fontSize: "0.85em", color: TEXT_MUTED, fontWeight: 400 }}>{c.platform_type}</span>
                            </td>
                            <td style={{ padding: "5px 8px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <div style={{ width: 56, height: 5, background: BORDER2, borderRadius: 3, flexShrink: 0 }}>
                                  <div style={{ width: `${c.health_score}%`, height: "100%", background: hColor, borderRadius: 3 }} />
                                </div>
                                <span style={{ color: hColor, fontWeight: 700, minWidth: 24 }}>{c.health_score}</span>
                              </div>
                            </td>
                            <td style={{ padding: "5px 8px", textAlign: "right", color: c.sale_date_coverage_pct >= 80 ? GREEN : c.sale_date_coverage_pct >= 50 ? AMBER : RED }}>
                              {c.sale_date_coverage_pct}%
                            </td>
                            <td style={{ padding: "5px 8px", textAlign: "right", color: c.extraction_rate_pct >= 60 ? GREEN : c.extraction_rate_pct >= 30 ? AMBER : RED }}>
                              {c.extraction_rate_pct}%
                            </td>
                            <td style={{ padding: "5px 8px", textAlign: "right", color: c.evidence_pct >= 50 ? GREEN : c.evidence_pct >= 20 ? AMBER : TEXT_MUTED }}>
                              {c.evidence_pct}%
                            </td>
                            <td style={{ padding: "5px 8px", textAlign: "right", color: c.browser_count > 0 && Math.abs(c.delta) > c.browser_count * 0.1 ? AMBER : TEXT_DIM }}>
                              {c.browser_count > 0 ? `${c.browser_count}/${c.db_count}` : "—"}
                            </td>
                            <td style={{ padding: "5px 8px", textAlign: "right", color: c.last_run_age_days == null ? RED : c.last_run_age_days > 7 ? AMBER : TEXT_DIM }}>
                              {c.last_run_age_days != null ? `${c.last_run_age_days}d ago` : "Never"}
                            </td>
                            <td style={{ padding: "5px 8px" }}>
                              {c.alert ? (
                                <Badge color={alertColor}>{c.alert}</Badge>
                              ) : (
                                <span style={{ color: GREEN, fontSize: "0.85em" }}>✓ OK</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {countyHealth.filter(c => c.total > 0).length === 0 && (
                        <tr>
                          <td colSpan={8} style={{ padding: "12px 8px", color: TEXT_MUTED }}>No counties with data yet.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {countyHealth.filter(c => c.total === 0).length > 0 && (
                  <p style={{ fontSize: "0.72em", color: TEXT_MUTED, marginTop: 8 }}>
                    {countyHealth.filter(c => c.total === 0).length} counties with no data not shown.
                  </p>
                )}
              </>
            )}
          </section>

          {/* Quick actions */}
          <section>
            <SectionHeader>QUICK ACTIONS</SectionHeader>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {[
                { label: "↗ Admin Health", href: "/api/admin/health" },
                { label: "⬇ Coverage JSON", href: "/api/admin/coverage" },
                { label: "⬇ Audit Log JSON", href: "/api/admin/audit-log?limit=200" },
              ].map(({ label, href }) => (
                <a key={label} href={href} target="_blank" rel="noreferrer" style={{
                  background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM,
                  borderRadius: 5, padding: "7px 16px", textDecoration: "none", fontSize: "0.78em",
                  fontFamily: "monospace", display: "inline-block",
                }}>{label}</a>
              ))}
              <button onClick={load} style={{
                background: "none", border: `1px solid ${BORDER2}`, color: TEXT_DIM,
                borderRadius: 5, padding: "7px 16px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.78em",
              }}>↻ Refresh All</button>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

// ── Tab: Ops Center ───────────────────────────────────────────────────────────

interface OpsJob {
  id: string;
  command: string;
  args_json?: string;
  status: "QUEUED" | "RUNNING" | "SUCCESS" | "FAILED" | "CANCELLED";
  triggered_by?: string;
  triggered_at: number;
  started_at?: number;
  finished_at?: number;
  output?: string;
  output_tail?: string;
  exit_code?: number;
  county?: string;
  duration_s?: number;
}

interface PipelineSummary {
  grade_distribution: Record<string, number>;
  status_distribution: Record<string, number>;
  pre_sale_leads: number;
  pre_sale_promotion_candidates: number;
  gate4_ready: number;
  snapshot_counts: Record<string, number>;
  recent_jobs: OpsJob[];
  runs_24h: { mode: string; status: string; cnt: number }[];
}

const COUNTY_SLUGS = [
  "adams","arapahoe","archuleta","boulder","broomfield","clear_creek",
  "delta","douglas","eagle","el_paso","elbert","fremont","garfield",
  "gilpin","gunnison","jefferson","la_plata","larimer","mesa",
  "routt","san_miguel","teller","weld",
];

const PIPELINE_COMMANDS: {
  id: string; label: string; desc: string; hint: string; needsCounty?: boolean;
  danger?: boolean; color?: string; eta?: string; group?: string;
}[] = [
  // ── Pre-Sale ──────────────────────────────────────────────────────
  { id: "pending-sales",       label: "▶ PRE-SALE SCAN",       desc: "Scrape Active/Pending cases from GovSoft (pre-sale pipeline)", hint: "Use weekly to capture upcoming trustee sales before they occur. Results appear in PRE-SALE pipeline.", needsCounty: true, color: "#22c55e", eta: "2–5 min", group: "PRE-SALE" },
  // ── Post-Sale Scraper ─────────────────────────────────────────────
  { id: "scraper-run-window",  label: "▶ DATE-WINDOW SCRAPE",  desc: "Scrape post-sale Sold cases for a county (last 90 days)", hint: "Run after new sales occur to ingest fresh post-sale leads. Use when LAST RUN shows stale data.", needsCounty: true, eta: "5–15 min", group: "SCRAPER" },
  { id: "scraper-enum",        label: "▶ SEQUENTIAL ENUM",     desc: "Enumerate sequential case numbers for a county to find hidden cases", hint: "Use when date-window scraper misses cases. Iterates J250 0001-9999 style case numbers.", needsCounty: true, eta: "15–45 min", group: "SCRAPER" },
  { id: "sale-info-backfill",  label: "▶ SALE-INFO BACKFILL",  desc: "Re-scrape BRONZE leads missing SALE_INFO tab data", hint: "Required before Gate 4. Run when Admin → Pipeline shows NEEDS SALE DATE action for a county.", needsCounty: true, eta: "10–30 min", group: "SCRAPER" },
  { id: "denver-scrape",       label: "▶ DENVER SCRAPE",       desc: "Denver Public Trustee PDF scraper (special non-GovSoft path)", hint: "Denver uses a separate PDF-based system. Run separately from GovSoft counties.", eta: "5–15 min", group: "SCRAPER" },
  // ── Gate 4 ────────────────────────────────────────────────────────
  { id: "extract-batch",       label: "▶ GATE 4 EXTRACT",      desc: "Extract overbid amount from SALE_INFO HTML snapshots → promote to GOLD/SILVER", hint: "Core pipeline step. Run after Sale-Info Backfill. Turns BRONZE leads with snapshots into GOLD/SILVER.", needsCounty: true, eta: "5–20 min", group: "GATE 4" },
  { id: "gate4-run-all",       label: "▶ GATE 4 ALL COUNTIES", desc: "Full Gate 4 pipeline across all configured counties (slow)", hint: "Runs Gate 4 extraction for every county in sequence. Use for full refresh. Takes 30+ min.", color: "#f59e0b", eta: "30–90 min", group: "GATE 4" },
  // ── AI Verification ───────────────────────────────────────────────
  { id: "verify-sota",         label: "▶ SOTA VERIFY ALL",     desc: "Run triple-verification (Document AI + Gemini) on all GOLD leads with vault PDFs", hint: "Uses GCP Document AI + Gemini vision to confirm overbid amounts. Upgrades pool_source to TRIPLE_VERIFIED or AI_VERIFIED.", color: "#a78bfa", eta: "10–40 min", group: "VERIFY" },
  { id: "evidence-audit",      label: "▶ EVIDENCE AUDIT",      desc: "List all GOLD leads with zero evidence documents (flags gaps)", hint: "Identifies GOLD/ATTORNEY_READY leads that are missing html_snapshots or evidence_documents. Run before client demos.", color: "#a78bfa", eta: "< 1 min", group: "VERIFY" },
  // ── Promotion ─────────────────────────────────────────────────────
  { id: "promote-eligible",    label: "▶ PROMOTE ELIGIBLE",    desc: "Promote SILVER → GOLD when 6-month restriction expires", hint: "Run daily or weekly. Checks if any SILVER leads have passed the § 38-38-111(5) restriction window.", eta: "< 1 min", group: "PROMOTE" },
  // ── Owner Intelligence ────────────────────────────────────────────
  { id: "assessor-lookup",     label: "▶ ASSESSOR LOOKUP",     desc: "Pull owner mailing address from county assessor (8 counties)", hint: "Free assessor API. Populates owner_mailing_address on GOLD leads. Run after scraping new county.", eta: "5–20 min", group: "INTEL" },
  { id: "enrich-owners",       label: "▶ ENRICH OWNERS",       desc: "Run full owner enrichment pipeline (assessor + SOS + USPS)", hint: "Combines assessor, CO Secretary of State, and USPS validation to produce owner_contact_json. Best run weekly.", eta: "10–30 min", group: "INTEL" },
  { id: "unclaimed-crossref",  label: "▶ UNCLAIMED CROSSREF",  desc: "Print expired-window leads that may have transferred to CO Treasurer", hint: "Identifies leads with sale_date ≤ 2025-09-01 (past 6-month window) as unclaimed property candidates.", eta: "< 1 min", group: "INTEL" },
  // ── Alternative Streams ───────────────────────────────────────────
  { id: "tax-lien-run",           label: "▶ TAX LIEN RUN",        desc: "Tax lien surplus pipeline (C.R.S. § 39-11-151)", hint: "Populates TAX_LIEN surplus stream. Run monthly to capture county tax sale overages.", eta: "5–10 min", group: "STREAMS" },
  { id: "unclaimed-property-run", label: "▶ UNCLAIMED PROPERTY",  desc: "CO State Treasurer unclaimed property scraper (§ 38-13-101)", hint: "Populates UNCLAIMED_PROPERTY stream. Queries the CO State Treasurer's unclaimed property database.", eta: "5–15 min", group: "STREAMS" },
  // ── DB / System ───────────────────────────────────────────────────
  { id: "coverage-report",     label: "▶ COVERAGE REPORT",     desc: "Print full county coverage report (active/inactive/leads/GOLD per county)", hint: "Diagnostic report. Useful for identifying counties with stale data or zero leads.", eta: "< 1 min", group: "SYSTEM" },
  { id: "backup-db",           label: "⬇ BACKUP DB",           desc: "SQLite online backup → timestamped .bak file", hint: "Safe to run anytime — does not lock the DB. Creates a point-in-time snapshot.", eta: "< 1 min", group: "SYSTEM" },
  { id: "migrate",             label: "⬆ RUN MIGRATIONS",      desc: "Apply all pending DB migrations (idempotent — safe to re-run)", hint: "Run after deploying new code. Idempotent — will not re-apply already-applied migrations.", eta: "< 1 min", group: "SYSTEM" },
];

function jobStatusColor(status: string) {
  if (status === "SUCCESS") return GREEN;
  if (status === "RUNNING") return "#3b82f6";
  if (status === "QUEUED")  return AMBER;
  if (status === "FAILED")  return RED;
  return TEXT_MUTED;
}

function fmtDuration(s?: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function OpsCenter() {
  const [summary, setSummary]               = useState<PipelineSummary | null>(null);
  const [jobs, setJobs]                     = useState<OpsJob[]>([]);
  const [selectedJob, setSelectedJob]       = useState<OpsJob | null>(null);
  const [liveOutput, setLiveOutput]         = useState<string>("");
  const [loading, setLoading]               = useState(true);
  const [runningCmd, setRunningCmd]         = useState<string | null>(null);
  const [selectedCounty, setSelectedCounty] = useState<string>("");
  const [triggerMsg, setTriggerMsg]         = useState<string>("");
  const [triggerErr, setTriggerErr]         = useState(false);
  const [promoting, setPromoting]           = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadSummary = useCallback(() => {
    Promise.all([
      adminFetch<PipelineSummary>("/api/admin/ops/pipeline-summary"),
      adminFetch<{ jobs: OpsJob[] }>("/api/admin/ops/jobs?limit=30"),
    ]).then(([s, j]) => {
      setSummary(s);
      setJobs(j.jobs);
    }).catch(() => null).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSummary();
    const id = setInterval(loadSummary, 8000);
    return () => clearInterval(id);
  }, [loadSummary]);

  // Poll selected job for live output
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (!selectedJob) return;

    const poll = () => {
      adminFetch<OpsJob>(`/api/admin/ops/jobs/${selectedJob.id}`)
        .then((j) => {
          setSelectedJob(j);
          setLiveOutput(j.output || "");
          if (j.status !== "RUNNING" && j.status !== "QUEUED") {
            if (pollRef.current) clearInterval(pollRef.current);
          }
        })
        .catch(() => null);
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedJob?.id]); // eslint-disable-line

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [liveOutput]);

  const triggerJob = async (command: string, county?: string) => {
    setRunningCmd(command);
    setTriggerMsg("");
    setTriggerErr(false);
    try {
      const res = await adminFetch<{ job_id: string; status: string }>("/api/admin/ops/run", {
        method: "POST",
        body: JSON.stringify({ command, county: county || null, extra_args: [] }),
      });
      setTriggerMsg(`Job queued: ${res.job_id.slice(0, 8)}... — refresh jobs list to track`);
      // Auto-select the new job for live tail
      setTimeout(() => {
        adminFetch<OpsJob>(`/api/admin/ops/jobs/${res.job_id}`).then(setSelectedJob).catch(() => null);
        loadSummary();
      }, 800);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setTriggerMsg(msg);
      setTriggerErr(true);
    } finally {
      setRunningCmd(null);
    }
  };

  const promotePresale = async () => {
    setPromoting(true);
    try {
      const res = await adminFetch<{ promoted: number; total_pre_sale: number; message: string }>(
        "/api/admin/ops/promote-presale", { method: "POST" },
      );
      setTriggerMsg(res.message);
      setTriggerErr(false);
      loadSummary();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setTriggerMsg(msg);
      setTriggerErr(true);
    } finally {
      setPromoting(false);
    }
  };

  if (loading) return (
    <div style={{ padding: 40, textAlign: "center", color: TEXT_MUTED }}>LOADING PIPELINE STATUS...</div>
  );

  const grades = summary?.grade_distribution || {};
  const statuses = summary?.status_distribution || {};
  const runningJobs = jobs.filter(j => j.status === "RUNNING" || j.status === "QUEUED");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* ── Header KPIs ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
        {[
          { label: "GOLD", value: grades["GOLD"] ?? 0,   color: AMBER },
          { label: "SILVER", value: grades["SILVER"] ?? 0, color: "#94a3b8" },
          { label: "BRONZE", value: grades["BRONZE"] ?? 0, color: "#b45309" },
          { label: "REJECT", value: grades["REJECT"] ?? 0, color: RED },
          { label: "PRE-SALE", value: summary?.pre_sale_leads ?? 0, color: "#22c55e", accent: true },
          { label: "GATE4 READY", value: summary?.gate4_ready ?? 0, color: BLUE },
          { label: "PROMO CANDS", value: summary?.pre_sale_promotion_candidates ?? 0, color: "#a78bfa" },
          { label: "ACTIVE JOBS", value: runningJobs.length, color: runningJobs.length > 0 ? BLUE : TEXT_MUTED },
        ].map((k) => (
          <StatCard key={k.label} label={k.label} value={String(k.value)}
            color={k.color} dot accent={!!(k as { accent?: boolean }).accent} />
        ))}
      </div>

      {/* ── Snapshot counts + 24h runs ── */}
      {summary && (Object.keys(summary.snapshot_counts).length > 0 || summary.runs_24h.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {/* Snapshot inventory */}
          {Object.keys(summary.snapshot_counts).length > 0 && (
            <div style={{ background: BG2, border: `1px solid ${BORDER2}`, borderRadius: 8, padding: "12px 16px" }}>
              <div style={{ fontSize: "0.65em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 10 }}>HTML SNAPSHOT INVENTORY</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {Object.entries(summary.snapshot_counts).map(([type, cnt]) => (
                  <div key={type} style={{ background: BG3, border: `1px solid ${BORDER}`, borderRadius: 5, padding: "4px 10px", fontSize: "0.72em" }}>
                    <span style={{ color: TEXT_MUTED }}>{type}</span>
                    <span style={{ color: BLUE, fontWeight: 700, marginLeft: 8 }}>{cnt.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* 24h ingestion runs */}
          {summary.runs_24h.length > 0 && (
            <div style={{ background: BG2, border: `1px solid ${BORDER2}`, borderRadius: 8, padding: "12px 16px" }}>
              <div style={{ fontSize: "0.65em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 10 }}>INGESTION RUNS (LAST 24H)</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {summary.runs_24h.map((r, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72em" }}>
                    <span style={{ color: TEXT_MUTED }}>{r.mode}</span>
                    <div style={{ display: "flex", gap: 10 }}>
                      <Badge color={r.status === "SUCCESS" ? GREEN : r.status === "RUNNING" ? BLUE : RED}>{r.status}</Badge>
                      <span style={{ color: TEXT }}>{r.cnt}×</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Quick Actions ── */}
      <div style={{ background: BG2, border: `1px solid ${BORDER2}`, borderRadius: 8, padding: "12px 16px" }}>
        <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: TEXT_MUTED, marginBottom: 10 }}>QUICK ACTIONS</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[
            { label: "▶ PRE-SALE SCAN ALL", cmd: "pending-sales", needsCounty: false, color: "#22c55e", hint: "Runs pre-sale scan on all counties" },
            { label: "▶ GATE 4 ALL",        cmd: "gate4-run-all",  needsCounty: false, color: "#f59e0b", hint: "Full Gate 4 extraction (30+ min)" },
            { label: "⬇ BACKUP NOW",         cmd: "backup-db",      needsCounty: false, color: BLUE,      hint: "Safe DB backup (< 1 min)" },
            { label: "▶ PROMOTE ELIGIBLE",  cmd: "promote-eligible", needsCounty: false, color: "#a78bfa", hint: "SILVER → GOLD promotion check" },
          ].map(qa => (
            <button
              key={qa.cmd}
              title={qa.hint}
              onClick={() => triggerJob(qa.cmd)}
              disabled={!!runningCmd}
              style={{
                background: qa.color + "18", border: `1px solid ${qa.color + "55"}`, color: qa.color,
                borderRadius: 5, padding: "6px 14px", fontFamily: "monospace", fontSize: "0.73em",
                fontWeight: 700, cursor: runningCmd ? "not-allowed" : "pointer", letterSpacing: "0.04em",
                opacity: runningCmd ? 0.5 : 1,
              }}
            >
              {runningCmd === qa.cmd ? "QUEUING..." : qa.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Trigger messages ── */}
      {triggerMsg && <ActionMsg msg={triggerMsg} error={triggerErr} />}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

        {/* ── Left: Command Panel ── */}
        <div>
          <SectionHeader>PIPELINE CONTROLS</SectionHeader>

          {/* County selector */}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: "0.72em", color: TEXT_MUTED, display: "block", marginBottom: 6, letterSpacing: "0.08em" }}>
              COUNTY (for county-specific commands)
            </label>
            <select
              value={selectedCounty}
              onChange={(e) => setSelectedCounty(e.target.value)}
              style={{
                width: "100%", background: BG3, border: `1px solid ${BORDER2}`,
                color: TEXT, padding: "8px 12px", borderRadius: 6,
                fontFamily: "monospace", fontSize: "0.85em", cursor: "pointer",
              }}
            >
              <option value="">— all counties —</option>
              {COUNTY_SLUGS.map(c => <option key={c} value={c}>{c.replace(/_/g, " ").toUpperCase()}</option>)}
            </select>
          </div>

          {/* Command buttons — grouped */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(() => {
              const rendered: React.ReactNode[] = [];
              let lastGroup = "";
              PIPELINE_COMMANDS.forEach((cmd) => {
                if (cmd.group && cmd.group !== lastGroup) {
                  lastGroup = cmd.group;
                  rendered.push(
                    <div key={`g-${cmd.group}`} style={{
                      fontSize: "0.62em", letterSpacing: "0.12em", color: "#4b5563",
                      borderBottom: `1px solid ${BORDER}`, paddingBottom: 3, marginTop: 8,
                    }}>{cmd.group}</div>
                  );
                }
                const isRunning = runningCmd === cmd.id;
                const countyRequired = !!(cmd.needsCounty && !selectedCounty);
                rendered.push(
                  <div key={cmd.id} style={{
                    border: `1px solid ${(cmd.color || BORDER2) + "44"}`,
                    borderRadius: 8, padding: "10px 14px", background: BG,
                    display: "flex", alignItems: "flex-start", gap: 10,
                  }}>
                    <button
                      onClick={() => triggerJob(cmd.id, cmd.needsCounty ? (selectedCounty || undefined) : undefined)}
                      disabled={isRunning || !!runningCmd || countyRequired}
                      title={cmd.hint}
                      style={{
                        background: (cmd.color || BLUE) + "22",
                        border: `1px solid ${(cmd.color || BLUE) + "55"}`,
                        color: countyRequired ? TEXT_MUTED : (cmd.color || BLUE),
                        borderRadius: 5, padding: "5px 14px",
                        fontFamily: "monospace", fontSize: "0.75em", fontWeight: 700,
                        cursor: (isRunning || !!runningCmd || countyRequired) ? "not-allowed" : "pointer",
                        letterSpacing: "0.04em", flexShrink: 0,
                        opacity: (isRunning || !!runningCmd) ? 0.6 : 1,
                        marginTop: 2,
                      }}
                    >
                      {isRunning ? "QUEUING..." : cmd.label}
                    </button>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontSize: "0.78em", color: TEXT, fontWeight: 600 }}>{cmd.id}</span>
                        {cmd.needsCounty && <span style={{ fontSize: "0.65em", color: countyRequired ? "#f59e0b" : TEXT_MUTED, border: `1px solid ${countyRequired ? "#f59e0b44" : BORDER}`, padding: "1px 5px", borderRadius: 3 }}>COUNTY</span>}
                        {cmd.eta && <span style={{ fontSize: "0.65em", color: TEXT_MUTED, marginLeft: "auto" }}>~{cmd.eta}</span>}
                      </div>
                      <div style={{ fontSize: "0.7em", color: TEXT_MUTED, marginTop: 3, lineHeight: 1.4 }}>
                        {countyRequired ? "⚠ SELECT A COUNTY ABOVE FIRST" : cmd.desc}
                      </div>
                      {!countyRequired && cmd.hint && (
                        <div style={{ fontSize: "0.68em", color: "#4b5563", marginTop: 3, lineHeight: 1.35, fontStyle: "italic" }}>
                          {cmd.hint}
                        </div>
                      )}
                    </div>
                  </div>
                );
              });
              return rendered;
            })()}

            {/* PRE-SALE PROMOTE special button */}
            <div style={{
              border: `1px solid #a78bfa44`, borderRadius: 8, padding: "10px 14px",
              background: BG, display: "flex", alignItems: "center", gap: 10,
            }}>
              <button
                onClick={promotePresale}
                disabled={promoting}
                style={{
                  background: "#a78bfa22", border: "1px solid #a78bfa55",
                  color: "#a78bfa", borderRadius: 5, padding: "5px 14px",
                  fontFamily: "monospace", fontSize: "0.75em", fontWeight: 700,
                  cursor: promoting ? "not-allowed" : "pointer", letterSpacing: "0.04em",
                  flexShrink: 0, opacity: promoting ? 0.6 : 1,
                }}
              >
                {promoting ? "PROMOTING..." : "▶ PROMOTE PRE-SALE"}
              </button>
              <div>
                <div style={{ fontSize: "0.78em", color: TEXT, fontWeight: 600 }}>promote-presale</div>
                <div style={{ fontSize: "0.7em", color: TEXT_MUTED, marginTop: 2 }}>
                  Scan existing leads with future sale_date → set PRE_SALE status ({summary?.pre_sale_promotion_candidates ?? 0} candidates)
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Right: Job List ── */}
        <div>
          <SectionHeader action={
            <button onClick={loadSummary} style={{
              background: "none", border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
              borderRadius: 4, padding: "3px 10px", fontSize: "0.7em", cursor: "pointer", fontFamily: "monospace",
            }}>↻ REFRESH</button>
          }>RECENT JOBS</SectionHeader>

          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 420, overflowY: "auto" }}>
            {jobs.length === 0 && (
              <div style={{ color: TEXT_MUTED, fontSize: "0.82em", padding: "12px 0" }}>No jobs yet.</div>
            )}
            {jobs.map((job) => (
              <div
                key={job.id}
                onClick={() => setSelectedJob(job)}
                style={{
                  border: `1px solid ${selectedJob?.id === job.id ? jobStatusColor(job.status) + "77" : BORDER}`,
                  borderRadius: 7, padding: "8px 12px", cursor: "pointer", background: BG,
                  display: "flex", alignItems: "center", gap: 10,
                  transition: "border-color 0.15s",
                }}
              >
                <span style={{
                  width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
                  background: jobStatusColor(job.status),
                  boxShadow: job.status === "RUNNING" ? `0 0 6px ${jobStatusColor(job.status)}` : "none",
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.8em", fontWeight: 700, color: TEXT, display: "flex", gap: 8 }}>
                    <span>{job.command}</span>
                    {job.county && <Badge color={TEXT_MUTED}>{job.county}</Badge>}
                  </div>
                  <div style={{ fontSize: "0.68em", color: TEXT_MUTED, marginTop: 2 }}>
                    {new Date(job.triggered_at * 1000).toLocaleTimeString()} ·{" "}
                    {job.triggered_by || "admin"} ·{" "}
                    {fmtDuration(job.finished_at && job.started_at ? job.finished_at - job.started_at : null)}
                  </div>
                </div>
                <Badge color={jobStatusColor(job.status)}>{job.status}</Badge>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Job Log Viewer ── */}
      {selectedJob && (
        <div>
          <SectionHeader action={
            <button onClick={() => setSelectedJob(null)} style={{
              background: "none", border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
              borderRadius: 4, padding: "3px 10px", fontSize: "0.7em", cursor: "pointer", fontFamily: "monospace",
            }}>✕ CLOSE</button>
          }>
            JOB LOG — {selectedJob.command}{selectedJob.county ? ` [${selectedJob.county}]` : ""}{" "}
            <Badge color={jobStatusColor(selectedJob.status)}>{selectedJob.status}</Badge>
          </SectionHeader>

          <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
            {[
              { label: "JOB ID",    value: selectedJob.id.slice(0, 12) + "...", mono: true },
              { label: "STATUS",    value: selectedJob.status, color: jobStatusColor(selectedJob.status) },
              { label: "DURATION",  value: fmtDuration(selectedJob.duration_s) },
              { label: "EXIT CODE", value: selectedJob.exit_code != null ? String(selectedJob.exit_code) : "—",
                color: selectedJob.exit_code === 0 ? GREEN : (selectedJob.exit_code != null ? RED : TEXT_MUTED) },
            ].map((s) => (
              <StatCard key={s.label} label={s.label} value={s.value}
                color={(s as { color?: string }).color} mono={!!(s as { mono?: boolean }).mono} />
            ))}
          </div>

          <pre
            ref={logRef}
            style={{
              background: "#0a0f16", border: `1px solid ${BORDER}`, borderRadius: 8,
              padding: "14px 16px", fontSize: "0.72em", color: "#86efac",
              maxHeight: 380, overflowY: "auto", overflowX: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-all", fontFamily: "monospace",
              lineHeight: 1.5,
            }}
          >
            {liveOutput || (selectedJob.status === "QUEUED" ? "Waiting to start...\n" : "No output yet.\n")}
            {selectedJob.status === "RUNNING" && (
              <span style={{ animation: "pulse 1s infinite", color: BLUE }}>▌</span>
            )}
          </pre>
        </div>
      )}

      {/* ── Snapshot + Run Stats ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        <div>
          <SectionHeader>SNAPSHOT INVENTORY</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {Object.entries(summary?.snapshot_counts || {}).map(([type, cnt]) => (
              <div key={type} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82em", padding: "4px 0", borderBottom: `1px solid ${BORDER}` }}>
                <span style={{ color: TEXT_MUTED }}>{type}</span>
                <span style={{ color: TEXT, fontWeight: 700 }}>{cnt.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <SectionHeader>RUNS LAST 24H</SectionHeader>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {(summary?.runs_24h || []).length === 0 && (
              <div style={{ color: TEXT_MUTED, fontSize: "0.82em" }}>No runs in last 24h.</div>
            )}
            {(summary?.runs_24h || []).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.82em", padding: "4px 0", borderBottom: `1px solid ${BORDER}` }}>
                <span style={{ color: TEXT_MUTED }}>{r.mode} / <span style={{ color: r.status === "SUCCESS" ? GREEN : r.status === "FAILED" ? RED : AMBER }}>{r.status}</span></span>
                <span style={{ color: TEXT, fontWeight: 700 }}>{r.cnt}×</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Processing Status Breakdown ── */}
      <div>
        <SectionHeader>PROCESSING STATUS BREAKDOWN</SectionHeader>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 8 }}>
          {Object.entries(statuses).sort((a, b) => b[1] - a[1]).map(([st, cnt]) => (
            <StatCard key={st} label={st} value={cnt.toLocaleString()}
              color={st === "VALIDATED" ? GREEN : st === "PRE_SALE" ? "#22c55e" : st === "NEEDS_REVIEW" ? AMBER : TEXT_MUTED} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main Admin Component ───────────────────────────────────────────────────────

type TabKey = "attorneys" | "leads" | "users" | "system" | "ops";

export default function Admin() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>("ops");
  const [pendingCount, setPendingCount] = useState<number | null>(null);

  useEffect(() => {
    if (!authLoading && !user?.is_admin) {
      navigate("/dashboard", { replace: true });
    }
  }, [authLoading, user, navigate]);

  // Poll pending attorney count for badge
  useEffect(() => {
    if (!user?.is_admin) return;
    const poll = () =>
      adminFetch<{ users: AdminUser[] }>("/api/admin/users?attorney_status=PENDING")
        .then((r) => setPendingCount(r.users.length))
        .catch(() => null);
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, [user]);

  if (authLoading || !user?.is_admin) {
    return (
      <div style={{ minHeight: "100vh", background: BG, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: TEXT_MUTED, fontFamily: "monospace", fontSize: "0.9em" }}>LOADING...</div>
      </div>
    );
  }

  const TABS: { key: TabKey; label: string; badge?: number | null }[] = [
    { key: "ops",       label: "⚡ OPS CENTER" },
    { key: "attorneys", label: "ATTORNEY QUEUE", badge: pendingCount },
    { key: "leads",     label: "LEADS" },
    { key: "users",     label: "USERS" },
    { key: "system",    label: "SYSTEM" },
  ];

  return (
    <div style={{ minHeight: "100vh", background: BG, color: TEXT, fontFamily: "monospace" }}>

      {/* Header */}
      <header style={{
        borderBottom: `1px solid ${BORDER}`, background: BG2,
        padding: "12px 24px", display: "flex", alignItems: "center", gap: 16,
      }}>
        <Link to="/dashboard" style={{ color: TEXT_MUTED, fontSize: "0.82em", textDecoration: "none" }}>← Dashboard</Link>
        <div style={{ fontWeight: 700, letterSpacing: "0.08em", fontSize: "0.9em" }}>
          VERIFUSE <span style={{ color: RED }}>// ADMIN</span>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{
            display: "flex", alignItems: "center", gap: 6, fontSize: "0.75em", color: GREEN,
          }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: GREEN, display: "inline-block" }} />
            {user.email}
          </span>
          <span style={{
            background: `${RED}22`, border: `1px solid ${RED}44`, color: RED,
            fontSize: "0.68em", fontWeight: 700, padding: "2px 8px", borderRadius: 4, letterSpacing: "0.06em",
          }}>RESTRICTED</span>
        </div>
      </header>

      {/* Tab bar */}
      <div style={{
        borderBottom: `1px solid ${BORDER}`, background: BG2,
        padding: "0 24px", display: "flex", gap: 0,
      }}>
        {TABS.map((tab) => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{
            background: "none", border: "none",
            borderBottom: activeTab === tab.key ? `2px solid ${GREEN}` : "2px solid transparent",
            color: activeTab === tab.key ? GREEN : TEXT_MUTED,
            padding: "12px 20px", fontSize: "0.75em", letterSpacing: "0.08em",
            cursor: "pointer", fontFamily: "monospace", display: "flex", alignItems: "center", gap: 8,
          }}>
            {tab.label}
            {tab.badge != null && tab.badge > 0 && (
              <span style={{
                background: `${AMBER}22`, border: `1px solid ${AMBER}44`, color: AMBER,
                borderRadius: 10, padding: "1px 7px", fontSize: "0.85em", fontWeight: 700,
              }}>{tab.badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "28px 24px" }}>
        {activeTab === "ops"       && <OpsCenter />}
        {activeTab === "attorneys" && <AttorneyQueue />}
        {activeTab === "leads"     && <LeadsTab />}
        {activeTab === "users"     && <UsersTab />}
        {activeTab === "system"    && <SystemTab />}
      </div>
    </div>
  );
}
