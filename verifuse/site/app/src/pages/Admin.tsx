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
  bronze_no_overbid: number;
  has_snapshots: number;
  platform_type: string | null;
  last_verified_ts: number | null;
  action_needed: string;
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
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || "Request failed");
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
                  {["COUNTY", "CASE #", "OWNER / ADDRESS", "SURPLUS", "GRADE", "SALE DATE", "ACTIONS"].map((h) => (
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
                      <button onClick={() => setGradeOverride({ lead: l, newGrade: l.data_grade || "BRONZE", reason: "" })}
                        style={{
                          background: "none", border: `1px solid ${BORDER2}`, color: TEXT_MUTED,
                          borderRadius: 4, padding: "3px 9px", cursor: "pointer", fontFamily: "monospace", fontSize: "0.72em",
                        }}>
                        GRADE ↕
                      </button>
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
        <td style={{ padding: "10px 12px", textAlign: "right" }}>
          <span style={{ color: TEXT_MUTED, fontSize: "0.75em" }}>{expanded ? "▲" : "▼"}</span>
        </td>
      </tr>

      {/* Expanded detail panel */}
      {expanded && (
        <tr style={{ background: BG3 }}>
          <td colSpan={7} style={{ padding: "16px 20px" }}>
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
              {["EMAIL / FIRM", "TIER", "CREDITS", "ATTY STATUS", "ROLE", "LAST LOGIN", ""].map((h) => (
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

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
        <input
          type="text" placeholder="Filter by action…" value={filter}
          onChange={(e) => { setFilter(e.target.value); setOffset(0); }}
          style={{
            background: BG, border: `1px solid ${BORDER2}`, color: TEXT,
            padding: "5px 12px", borderRadius: 5, fontSize: "0.82em", fontFamily: "monospace", width: 220,
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [subTab, setSubTab] = useState<SystemSubTab>("operations");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    Promise.all([
      adminFetch<{ counties: CoverageCounty[] }>("/api/admin/coverage").then((r) => setCoverage(r.counties || [])).catch(() => setCoverage([])),
      adminFetch<{ pipeline: PipelineCounty[] }>("/api/admin/pipeline-status").then((r) => setPipeline(r.pipeline || [])).catch(() => setPipeline([])),
      adminFetch<SystemStats>("/api/admin/system-stats").then(setStats).catch((e) => setError(e.message)),
      adminFetch<RevenueMetrics>("/api/admin/revenue-metrics").then(setRev).catch(() => setRev(null)),
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginBottom: 16 }}>
              <StatCard label="MRR" value={`$${((rev?.mrr_cents || 0) / 100).toLocaleString()}`} color={GREEN} accent />
              <StatCard label="ARR" value={`$${((rev?.arr_cents || 0) / 100).toLocaleString()}`} color={GREEN} />
              <StatCard label="Active Subs" value={String(rev?.active_subscriptions ?? 0)} color={BLUE} />
              <StatCard label="New (30d)" value={String(rev?.new_subscribers_30d ?? 0)} color={BLUE} />
              <StatCard label="Churn (30d)" value={String(rev?.churn_30d ?? 0)} color={(rev?.churn_30d ?? 0) > 0 ? RED : GREEN} />
              <StatCard label="Credit Util" value={`${rev?.credit_utilization_pct ?? 0}%`} />
              <StatCard label="Founding Spots" value={`${rev?.founding_spots_claimed ?? 0} / ${rev?.founding_spots_total ?? 10}`} color={AMBER} />
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {(["sovereign", "partner", "associate"] as const).map((tier) => (
                <div key={tier} style={{ flex: 1, minWidth: 140, background: BG, border: `1px solid ${BORDER2}`, borderRadius: 8, padding: "12px 16px" }}>
                  <div style={{ color: TEXT_MUTED, fontSize: "0.7em", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{tier}</div>
                  <div style={{ fontWeight: 700, fontSize: "1.2em" }}>{rev?.by_tier?.[tier]?.count ?? 0} users</div>
                  <div style={{ color: GREEN, fontSize: "0.82em" }}>${((rev?.by_tier?.[tier]?.mrr_cents ?? 0) / 100).toLocaleString()}/mo</div>
                </div>
              ))}
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
              <StatCard label="Stripe" value={stats?.stripe_configured ? `${(stats?.stripe_mode || "test").toUpperCase()} MODE` : "NOT SET"} color={stats?.stripe_configured ? GREEN : RED} dot />
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
            <SectionHeader>COUNTY PIPELINE — GATE 4 STATUS ({pipeline.length > 0 ? pipeline.length : coverage.length} counties)</SectionHeader>
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
                        { h: "GOLD", right: true },
                        { h: "SILVER", right: true },
                        { h: "BRONZE", right: true },
                        { h: "ACTION", right: false },
                        { h: "24H", right: false },
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
                        // Merge pipeline data with coverage data for 24h status + last run
                        const coverageByCounty: Record<string, CoverageCounty> = {};
                        coverage.forEach((c) => { coverageByCounty[(c.county_code || c.county || "").toLowerCase()] = c; });
                        return pipeline.map((p) => {
                          const cov = coverageByCounty[p.county.toLowerCase()] || {};
                          const status24h = cov.ran_24h ? (cov.found_zero_24h ? "EMPTY" : "OK") : cov.silent_24h ? "NEEDS RUN" : "—";
                          const status24hColor = cov.ran_24h ? (cov.found_zero_24h ? AMBER : GREEN) : cov.silent_24h ? AMBER : TEXT_MUTED;
                          const actionColor = p.action_needed === "clean" ? GREEN
                            : p.action_needed === "gate4_ready" ? AMBER
                            : p.action_needed === "sale_info_backfill_needed" ? "#f97316"
                            : p.action_needed === "captcha_blocked" ? RED
                            : TEXT_MUTED;
                          const actionLabel = p.action_needed === "clean" ? "✓ CLEAN"
                            : p.action_needed === "gate4_ready" ? "→ GATE 4"
                            : p.action_needed === "sale_info_backfill_needed" ? "⟳ BACKFILL"
                            : p.action_needed === "captcha_blocked" ? "✗ CAPTCHA"
                            : p.action_needed.replace(/_/g, " ").toUpperCase();
                          return (
                            <tr key={p.county} style={{ borderBottom: `1px solid ${BORDER}` }}>
                              <td style={{ padding: "6px 10px", fontWeight: 600 }}>{p.county.replace(/_/g, " ").toUpperCase()}</td>
                              <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.75em" }}>{p.platform_type || cov.platform || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: "#f59e0b", fontWeight: p.gold > 0 ? 700 : 400 }}>{p.gold || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: "#94a3b8", fontWeight: p.silver > 0 ? 700 : 400 }}>{p.silver || "—"}</td>
                              <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>{p.bronze || "—"}</td>
                              <td style={{ padding: "6px 10px" }}>
                                <span style={{ color: actionColor, fontWeight: 700, fontSize: "0.8em", letterSpacing: "0.04em" }}>{actionLabel}</span>
                              </td>
                              <td style={{ padding: "6px 10px" }}>
                                <span style={{ color: status24hColor, fontWeight: 600, fontSize: "0.8em" }}>{status24h}</span>
                              </td>
                              <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.8em" }}>
                                {(cov.last_scraped_at || cov.last_run)?.slice(0, 10) || "—"}
                              </td>
                            </tr>
                          );
                        });
                      })()
                    ) : (
                      // Fallback: coverage-only table
                      coverage.map((c) => {
                        const status24h = c.ran_24h ? (c.found_zero_24h ? "EMPTY" : "OK") : c.silent_24h ? "NEEDS RUN" : "—";
                        const statusColor = c.ran_24h ? (c.found_zero_24h ? AMBER : GREEN) : c.silent_24h ? AMBER : TEXT_MUTED;
                        return (
                          <tr key={c.county_code || c.county} style={{ borderBottom: `1px solid ${BORDER}` }}>
                            <td style={{ padding: "6px 10px", fontWeight: 600 }}>{(c.county || c.county_code || "—").toUpperCase()}</td>
                            <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.75em" }}>{c.platform_type || c.platform || "—"}</td>
                            <td style={{ padding: "6px 10px", textAlign: "right", color: "#f59e0b" }}>{c.gold || "—"}</td>
                            <td style={{ padding: "6px 10px", textAlign: "right", color: "#94a3b8" }}>{c.silver || "—"}</td>
                            <td style={{ padding: "6px 10px", textAlign: "right", color: TEXT_MUTED }}>{c.bronze || "—"}</td>
                            <td style={{ padding: "6px 10px" }}>—</td>
                            <td style={{ padding: "6px 10px" }}><span style={{ color: statusColor, fontWeight: 600, fontSize: "0.8em" }}>{status24h}</span></td>
                            <td style={{ padding: "6px 10px", color: TEXT_MUTED, fontSize: "0.8em" }}>
                              {(c.last_scraped_at || c.last_run)?.slice(0, 10) || "—"}
                            </td>
                          </tr>
                        );
                      })
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

// ── Main Admin Component ───────────────────────────────────────────────────────

type TabKey = "attorneys" | "leads" | "users" | "system";

export default function Admin() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>("attorneys");
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
        {activeTab === "attorneys" && <AttorneyQueue />}
        {activeTab === "leads"     && <LeadsTab />}
        {activeTab === "users"     && <UsersTab />}
        {activeTab === "system"    && <SystemTab />}
      </div>
    </div>
  );
}
