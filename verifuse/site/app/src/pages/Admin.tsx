import React, { useEffect, useState, useCallback } from "react";
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
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

// ── Tab: Attorney Queue ────────────────────────────────────────────────────────

function AttorneyQueue() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    adminFetch<{ users: AdminUser[] }>("/api/admin/users?attorney_status=PENDING")
      .then((r) => setUsers(r.users))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function approve(user_id: string) {
    setActionMsg("");
    try {
      await adminFetch("/api/admin/attorney/approve", {
        method: "POST",
        body: JSON.stringify({ user_id }),
      });
      setActionMsg(`Approved ${user_id}`);
      load();
    } catch (e: unknown) {
      setActionMsg(e instanceof ApiError ? e.message : "Approve failed");
    }
  }

  async function reject(user_id: string) {
    setActionMsg("");
    const reason = window.prompt("Rejection reason (required):", "Does not meet verification requirements");
    if (reason === null) return; // cancelled
    try {
      await adminFetch("/api/admin/attorney/reject", {
        method: "POST",
        body: JSON.stringify({ user_id, reason: reason.trim() || "Admin review" }),
      });
      setActionMsg(`Rejected ${user_id}`);
      load();
    } catch (e: unknown) {
      setActionMsg(e instanceof ApiError ? e.message : "Reject failed");
    }
  }

  if (loading) return <p className="processing-text">Loading attorney queue...</p>;
  if (error) return <p className="auth-error">{error}</p>;

  return (
    <div>
      <h3 style={{ marginBottom: 12, fontSize: "0.9em", letterSpacing: "0.08em" }}>
        PENDING ATTORNEY VERIFICATIONS ({users.length})
      </h3>
      {actionMsg && (
        <p style={{ color: "#22c55e", fontSize: "0.85em", marginBottom: 12 }}>{actionMsg}</p>
      )}
      {users.length === 0 ? (
        <p style={{ opacity: 0.5, fontSize: "0.85em" }}>No pending applications.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {users.map((u) => (
            <div key={u.user_id} style={{
              border: "1px solid #374151", borderRadius: 6, padding: "10px 14px",
              display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap",
            }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontWeight: 600, fontSize: "0.9em" }}>{u.email}</div>
                <div style={{ fontSize: "0.8em", opacity: 0.7 }}>
                  {u.full_name || "—"} · {u.firm_name || "No firm"}
                </div>
                <div style={{ fontSize: "0.78em", opacity: 0.6, marginTop: 2 }}>
                  Bar: {u.bar_number || "—"} ({u.bar_state || "CO"}) · Tier: {u.tier}
                </div>
                <div style={{ fontSize: "0.75em", opacity: 0.5, marginTop: 2 }}>
                  Joined: {u.created_at?.slice(0, 10) || "—"}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="decrypt-btn-sota"
                  style={{ fontSize: "0.78em", padding: "6px 14px" }}
                  onClick={() => approve(u.user_id)}>
                  APPROVE
                </button>
                <button className="btn-outline"
                  style={{ fontSize: "0.78em", padding: "6px 14px", borderColor: "#ef4444", color: "#ef4444" }}
                  onClick={() => reject(u.user_id)}>
                  REJECT
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab: Leads ─────────────────────────────────────────────────────────────────

function LeadsTab() {
  const [leads, setLeads] = useState<AdminLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [grade, setGrade] = useState("");
  const [county, setCounty] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (grade) params.set("grade", grade);
    if (county) params.set("county", county);
    params.set("limit", "200");
    adminFetch<{ leads: AdminLead[]; count: number }>(`/api/admin/leads?${params}`)
      .then((r) => setLeads(r.leads))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [grade, county]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: "0.8em", opacity: 0.6 }}>GRADE</span>
        {["", "GOLD", "SILVER", "BRONZE", "REJECT"].map((g) => (
          <button key={g || "ALL"} className={`grade-filter-btn ${grade === g ? "active" : ""}`}
            onClick={() => setGrade(g)}>
            {g || "ALL"}
          </button>
        ))}
        <input
          type="text" placeholder="Filter county…" value={county}
          onChange={(e) => setCounty(e.target.value)}
          style={{ background: "#111827", border: "1px solid #374151", color: "#e5e7eb", padding: "4px 10px", borderRadius: 4, fontSize: "0.82em" }}
        />
      </div>

      {loading ? (
        <p className="processing-text">Loading leads...</p>
      ) : error ? (
        <p className="auth-error">{error}</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #374151", opacity: 0.6 }}>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>COUNTY</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>CASE</th>
                <th style={{ textAlign: "right", padding: "6px 10px" }}>SURPLUS</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>GRADE</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>SALE DATE</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>STREAM</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((l) => (
                <tr key={l.id} style={{ borderBottom: "1px solid #1f2937" }}>
                  <td style={{ padding: "6px 10px" }}>{l.county}</td>
                  <td style={{ padding: "6px 10px", fontFamily: "monospace", fontSize: "0.9em" }}>
                    <Link to={`/lead/${l.id}`} style={{ color: "#22c55e" }}>
                      {l.case_number || l.id.slice(0, 16)}
                    </Link>
                  </td>
                  <td style={{ padding: "6px 10px", textAlign: "right" }}>
                    {formatCurrency(l.estimated_surplus)}
                  </td>
                  <td style={{ padding: "6px 10px" }}>
                    <span className={`grade-badge grade-${(l.data_grade || "").toLowerCase()}`}>
                      {l.data_grade || "—"}
                    </span>
                  </td>
                  <td style={{ padding: "6px 10px" }}>{l.sale_date || "—"}</td>
                  <td style={{ padding: "6px 10px", opacity: 0.6 }}>
                    {l.surplus_stream || "FORECLOSURE_OVERBID"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {leads.length === 0 && (
            <p style={{ opacity: 0.5, fontSize: "0.85em", marginTop: 12 }}>No leads found.</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Tab: Users ─────────────────────────────────────────────────────────────────

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    adminFetch<{ users: AdminUser[] }>("/api/admin/users")
      .then((r) => setUsers(r.users))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="processing-text">Loading users...</p>;
  if (error) return <p className="auth-error">{error}</p>;

  return (
    <div style={{ overflowX: "auto" }}>
      <p style={{ fontSize: "0.8em", opacity: 0.5, marginBottom: 10 }}>{users.length} users total</p>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #374151", opacity: 0.6 }}>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>EMAIL</th>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>TIER</th>
            <th style={{ textAlign: "right", padding: "6px 10px" }}>CREDITS</th>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>STATUS</th>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>ROLE</th>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>LAST LOGIN</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id} style={{ borderBottom: "1px solid #1f2937" }}>
              <td style={{ padding: "6px 10px" }}>
                <div>{u.email}</div>
                {u.firm_name && <div style={{ fontSize: "0.85em", opacity: 0.5 }}>{u.firm_name}</div>}
              </td>
              <td style={{ padding: "6px 10px" }}>{u.tier}</td>
              <td style={{ padding: "6px 10px", textAlign: "right" }}>{u.credits_remaining}</td>
              <td style={{ padding: "6px 10px" }}>
                <span style={{
                  fontSize: "0.78em",
                  color: u.attorney_status === "VERIFIED" ? "#22c55e"
                    : u.attorney_status === "PENDING" ? "#f59e0b"
                    : u.attorney_status === "REJECTED" ? "#ef4444"
                    : "#6b7280",
                }}>
                  {u.attorney_status || "NONE"}
                </span>
              </td>
              <td style={{ padding: "6px 10px", opacity: 0.7 }}>{u.role || "public"}</td>
              <td style={{ padding: "6px 10px", opacity: 0.5, fontSize: "0.85em" }}>
                {u.last_login_at?.slice(0, 10) || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Tab: System ────────────────────────────────────────────────────────────────

const GRADE_COLORS: Record<string, string> = {
  GOLD: "#f59e0b", SILVER: "#94a3b8", BRONZE: "#b45309", REJECT: "#ef4444", UNGRADED: "#6b7280",
};

type SystemSubTab = "operations" | "engineering";

function SystemTab() {
  const [coverage, setCoverage] = useState<CoverageCounty[]>([]);
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [rev, setRev] = useState<RevenueMetrics | null>(null);
  const [auditFilter, setAuditFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [subTab, setSubTab] = useState<SystemSubTab>("operations");

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      adminFetch<{ counties: CoverageCounty[] }>("/api/admin/coverage")
        .then((r) => setCoverage(r.counties || []))
        .catch(() => setCoverage([])),
      adminFetch<SystemStats>("/api/admin/system-stats")
        .then(setStats)
        .catch((e) => setError(e.message)),
      adminFetch<RevenueMetrics>("/api/admin/revenue-metrics")
        .then(setRev)
        .catch(() => setRev(null)),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="processing-text">Loading system status...</p>;

  const isLive = stats !== null;
  const filteredAudit = (stats?.recent_audit || []).filter((e) =>
    !auditFilter || e.action.includes(auditFilter) || e.user_email.includes(auditFilter)
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

      {/* ── Sub-tab toggle: OPERATIONS | ENGINEERING ── */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid #374151" }}>
        {(["operations", "engineering"] as SystemSubTab[]).map((st) => (
          <button key={st} onClick={() => setSubTab(st)} style={{
            background: "none", border: "none",
            borderBottom: subTab === st ? "2px solid #22c55e" : "2px solid transparent",
            color: subTab === st ? "#22c55e" : "#9ca3af",
            padding: "8px 16px", fontSize: "0.75em", letterSpacing: "0.08em",
            cursor: "pointer", fontFamily: "inherit", textTransform: "uppercase",
          }}>{st}</button>
        ))}
      </div>

      {subTab === "operations" && <>

      {/* ── Section 0: Revenue Metrics ── */}
      <section>
        <SectionHeader>REVENUE METRICS</SectionHeader>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 16 }}>
          <StatCard label="MRR" value={`$${((rev?.mrr_cents || 0) / 100).toLocaleString()}`} color="#22c55e" />
          <StatCard label="ARR" value={`$${((rev?.arr_cents || 0) / 100).toLocaleString()}`} color="#22c55e" />
          <StatCard label="ACTIVE SUBS" value={String(rev?.active_subscriptions ?? 0)} />
          <StatCard label="NEW (30D)" value={String(rev?.new_subscribers_30d ?? 0)} color="#3b82f6" />
          <StatCard label="CHURN (30D)" value={String(rev?.churn_30d ?? 0)} color={(rev?.churn_30d ?? 0) > 0 ? "#ef4444" : "#22c55e"} />
          <StatCard label="CREDIT UTIL" value={`${rev?.credit_utilization_pct ?? 0}%`} />
          <StatCard label="FOUNDING SPOTS" value={`${rev?.founding_spots_claimed ?? 0} / ${rev?.founding_spots_total ?? 10}`} color="#f59e0b" />
        </div>
        {/* Per-tier breakdown */}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {(["sovereign", "partner", "associate"] as const).map((tier) => (
            <div key={tier} style={{ flex: 1, minWidth: 150, background: "#0d1117", border: "1px solid #374151", borderRadius: 8, padding: "12px 16px" }}>
              <div style={{ color: "#6b7280", fontSize: "0.72em", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>{tier}</div>
              <div style={{ color: "#e5e7eb", fontSize: "1.3em", fontWeight: 700 }}>{rev?.by_tier?.[tier]?.count ?? 0} users</div>
              <div style={{ color: "#22c55e", fontSize: "0.85em" }}>${((rev?.by_tier?.[tier]?.mrr_cents ?? 0) / 100).toLocaleString()}/mo</div>
            </div>
          ))}
        </div>
      </section>

      </>} {/* end operations sub-tab */}

      {/* ── Section 1: Health + DB (Engineering) ── */}
      {subTab === "engineering" && <section>
        <SectionHeader>API + DATABASE</SectionHeader>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
          <StatCard
            label="API STATUS"
            value={isLive ? "LIVE" : "ERROR"}
            color={isLive ? "#22c55e" : "#ef4444"}
            dot
          />
          <StatCard label="ENV" value={(stats?.verifuse_env || "—").toUpperCase()} />
          <StatCard label="BUILD" value={stats?.build_id || "—"} mono />
          <StatCard label="DB SIZE" value={stats ? `${stats.db_size_mb} MB` : "—"} />
          <StatCard label="WAL PAGES" value={stats?.wal_pages?.toString() || "—"} />
          <StatCard label="TOTAL LEADS" value={stats?.total_leads?.toLocaleString() || "—"} />
          <StatCard label="VERIFIED PIPELINE" value={stats?.verified_pipeline_count?.toString() || "—"} />
          <StatCard
            label="PIPELINE SURPLUS"
            value={stats ? formatCurrency(stats.verified_pipeline_surplus) : "—"}
            color="#22c55e"
          />
        </div>
        {error && <p style={{ color: "#ef4444", fontSize: "0.8em", marginTop: 8 }}>{error}</p>}
      </section>}

      {/* ── Section 2: Lead Scoreboard (Engineering) ── */}
      {subTab === "engineering" && stats?.scoreboard && stats.scoreboard.length > 0 && (
        <section>
          <SectionHeader>LEAD SCOREBOARD</SectionHeader>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
            {stats.scoreboard.map((s) => (
              <div key={s.data_grade} style={{
                border: `1px solid ${GRADE_COLORS[s.data_grade] || "#374151"}33`,
                borderRadius: 6, padding: "10px 14px",
                background: "#0d1117",
              }}>
                <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.6, marginBottom: 4 }}>
                  {s.data_grade}
                </div>
                <div style={{
                  fontSize: "1.4em", fontWeight: 700,
                  color: GRADE_COLORS[s.data_grade] || "#e5e7eb",
                }}>
                  {s.lead_count.toLocaleString()}
                </div>
                <div style={{ fontSize: "0.8em", opacity: 0.5, marginTop: 2 }}>
                  {formatCurrency(s.total_surplus)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Section 3: Users + Stripe (Operations) ── */}
      {subTab === "operations" && <section>
        <SectionHeader>USERS + BILLING</SectionHeader>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          <StatCard label="TOTAL USERS" value={stats?.user_counts?.total?.toString() || "—"} />
          <StatCard label="VERIFIED ATTORNEYS" value={stats?.user_counts?.verified_attorneys?.toString() || "—"} color="#22c55e" />
          <StatCard label="PENDING ATTORNEYS" value={stats?.user_counts?.pending_attorneys?.toString() || "—"} color="#f59e0b" />
          <StatCard label="SOVEREIGN TIER" value={stats?.user_counts?.sovereign_users?.toString() || "—"} />
          <StatCard label="PARTNER TIER" value={stats?.user_counts?.partner_users?.toString() || "—"} />
          <StatCard
            label="STRIPE"
            value={stats?.stripe_configured ? `${(stats?.stripe_mode || "test").toUpperCase()} MODE` : "NOT CONFIGURED"}
            color={stats?.stripe_configured ? "#22c55e" : "#ef4444"}
          />
          <StatCard
            label="PUB KEY"
            value={stats?.stripe_publishable_configured ? "SET" : "MISSING"}
            color={stats?.stripe_publishable_configured ? "#22c55e" : "#6b7280"}
          />
          <StatCard
            label="API KEY"
            value={stats?.api_key_configured ? "SET" : "NOT SET"}
            color={stats?.api_key_configured ? "#22c55e" : "#6b7280"}
          />
        </div>
      </section>}

      {/* ── Section 4: County Coverage (Engineering) ── */}
      {subTab === "engineering" && <section>
        <SectionHeader>COUNTY COVERAGE ({coverage.length} counties)</SectionHeader>
        {coverage.length === 0 ? (
          <p style={{ opacity: 0.5, fontSize: "0.85em" }}>No coverage data.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8em" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #374151" }}>
                  {["COUNTY", "PLATFORM", "LEADS", "24H STATUS", "LAST RUN", "ERROR"].map((h) => (
                    <th key={h} style={{
                      textAlign: h === "LEADS" ? "right" : "left",
                      padding: "5px 10px", opacity: 0.5, fontWeight: 600, fontSize: "0.85em",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {coverage.map((c) => {
                  const countyName = c.county || c.county_code || "—";
                  const platform = c.platform_type || c.platform || "—";
                  const lastRun = c.last_scraped_at || c.last_run;
                  const status24h = c.ran_24h
                    ? (c.found_zero_24h ? "EMPTY" : "RAN OK")
                    : c.silent_24h ? "SILENT" : "—";
                  const statusColor = c.ran_24h
                    ? (c.found_zero_24h ? "#f59e0b" : "#22c55e")
                    : c.silent_24h ? "#ef4444" : "#6b7280";
                  return (
                    <tr key={c.county_code || countyName} style={{ borderBottom: "1px solid #1f2937" }}>
                      <td style={{ padding: "6px 10px", fontWeight: 500 }}>
                        {countyName.toUpperCase()}
                        {c.active === false && (
                          <span style={{ fontSize: "0.75em", opacity: 0.4, marginLeft: 6 }}>disabled</span>
                        )}
                      </td>
                      <td style={{ padding: "6px 10px", opacity: 0.6 }}>{platform}</td>
                      <td style={{ padding: "6px 10px", textAlign: "right", fontWeight: 600 }}>
                        {c.leads_count ?? 0}
                      </td>
                      <td style={{ padding: "6px 10px" }}>
                        <span style={{ color: statusColor, fontSize: "0.85em" }}>{status24h}</span>
                      </td>
                      <td style={{ padding: "6px 10px", opacity: 0.5, fontSize: "0.85em" }}>
                        {lastRun ? lastRun.slice(0, 16).replace("T", " ") : "—"}
                      </td>
                      <td style={{ padding: "6px 10px", color: "#ef4444", fontSize: "0.8em", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {c.last_error || ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {/* ── Section 5: Recent Activity (Audit Log) (Engineering) ── */}
      {subTab === "engineering" && <section>
        <SectionHeader>RECENT ACTIVITY</SectionHeader>
        <div style={{ marginBottom: 10 }}>
          <input
            type="text"
            placeholder="Filter by action or email…"
            value={auditFilter}
            onChange={(e) => setAuditFilter(e.target.value)}
            style={{
              background: "#111827", border: "1px solid #374151", color: "#e5e7eb",
              padding: "5px 12px", borderRadius: 4, fontSize: "0.82em", width: 280,
            }}
          />
        </div>
        {filteredAudit.length === 0 ? (
          <p style={{ opacity: 0.5, fontSize: "0.85em" }}>No audit entries.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8em" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #374151" }}>
                  {["TIMESTAMP", "USER", "ACTION", "IP", "DETAILS"].map((h) => (
                    <th key={h} style={{
                      textAlign: "left", padding: "5px 10px", opacity: 0.5,
                      fontWeight: 600, fontSize: "0.85em",
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredAudit.map((e) => (
                  <tr key={e.id} style={{ borderBottom: "1px solid #1f2937" }}>
                    <td style={{ padding: "5px 10px", opacity: 0.5, whiteSpace: "nowrap", fontSize: "0.9em" }}>
                      {e.created_at?.slice(0, 19).replace("T", " ") || "—"}
                    </td>
                    <td style={{ padding: "5px 10px", fontSize: "0.9em" }}>{e.user_email}</td>
                    <td style={{ padding: "5px 10px" }}>
                      <span style={{
                        color: e.action.includes("unlock") ? "#22c55e"
                          : e.action.includes("reject") || e.action.includes("fail") ? "#ef4444"
                          : e.action.includes("approve") ? "#22c55e"
                          : "#9ca3af",
                        fontSize: "0.85em", fontFamily: "monospace",
                      }}>{e.action}</span>
                    </td>
                    <td style={{ padding: "5px 10px", opacity: 0.4, fontSize: "0.85em" }}>{e.ip || "—"}</td>
                    <td style={{ padding: "5px 10px", opacity: 0.5, fontSize: "0.8em", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                      {e.meta ? Object.entries(e.meta).slice(0, 3).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ") : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {/* ── Section 6: Admin Actions (Engineering) ── */}
      {subTab === "engineering" && <section>
        <SectionHeader>ADMIN ACTIONS</SectionHeader>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn-outline" style={{ fontSize: "0.8em", padding: "7px 16px" }}
            onClick={() => load()}>
            ↻ REFRESH
          </button>
          <a
            href="/api/admin/coverage"
            target="_blank"
            className="btn-outline"
            style={{ fontSize: "0.8em", padding: "7px 16px", textDecoration: "none", display: "inline-block" }}
          >
            ⬇ COVERAGE JSON
          </a>
          <a
            href="/api/admin/health"
            target="_blank"
            className="btn-outline"
            style={{ fontSize: "0.8em", padding: "7px 16px", textDecoration: "none", display: "inline-block" }}
          >
            ↗ HEALTH CHECK
          </a>
        </div>
      </section>}

    </div>
  );
}

// ── Helper: Section Header ─────────────────────────────────────────────────────

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h4 style={{
      fontSize: "0.75em", letterSpacing: "0.1em", opacity: 0.5,
      marginBottom: 12, marginTop: 0, borderBottom: "1px solid #1f2937", paddingBottom: 6,
    }}>
      {children}
    </h4>
  );
}

// ── Helper: Stat Card ──────────────────────────────────────────────────────────

function StatCard({
  label, value, color, mono, dot,
}: {
  label: string;
  value: string;
  color?: string;
  mono?: boolean;
  dot?: boolean;
}) {
  return (
    <div style={{
      border: "1px solid #374151", borderRadius: 6, padding: "10px 14px", background: "#0d1117",
    }}>
      <div style={{ fontSize: "0.7em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {dot && (
          <span style={{
            display: "inline-block", width: 8, height: 8, borderRadius: "50%",
            background: color || "#22c55e", flexShrink: 0,
          }} />
        )}
        <span style={{
          fontSize: "1.1em", fontWeight: 700,
          color: color || "#e5e7eb",
          fontFamily: mono ? "monospace" : "inherit",
        }}>
          {value}
        </span>
      </div>
    </div>
  );
}

// ── Main Admin Component ───────────────────────────────────────────────────────

type TabKey = "attorneys" | "leads" | "users" | "system";

const TABS: { key: TabKey; label: string }[] = [
  { key: "attorneys", label: "ATTORNEY QUEUE" },
  { key: "leads",     label: "LEADS" },
  { key: "users",     label: "USERS" },
  { key: "system",    label: "SYSTEM" },
];

export default function Admin() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>("attorneys");

  useEffect(() => {
    if (!authLoading && !user?.is_admin) {
      navigate("/dashboard", { replace: true });
    }
  }, [authLoading, user, navigate]);

  if (authLoading || !user?.is_admin) {
    return (
      <div className="detail-page">
        <div className="center-content">
          <div className="loader-ring" />
          <p className="processing-text">LOADING...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">
      <header className="dash-header">
        <Link to="/dashboard" className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-status">
          <span className="blink-dot">●</span>
          ADMIN PANEL
        </div>
        <div className="dash-user">
          <span className="tier-badge">ADMIN</span>
          <Link to="/dashboard" className="btn-outline-sm">← DASHBOARD</Link>
        </div>
      </header>

      <div className="admin-banner">ADMIN MODE — RESTRICTED ACCESS</div>

      {/* Tab navigation */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid #374151", margin: "0 20px" }}>
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === tab.key ? "2px solid #22c55e" : "2px solid transparent",
              color: activeTab === tab.key ? "#22c55e" : "#9ca3af",
              padding: "10px 18px",
              fontSize: "0.78em",
              letterSpacing: "0.08em",
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ padding: "20px 20px" }}>
        {activeTab === "attorneys" && <AttorneyQueue />}
        {activeTab === "leads"     && <LeadsTab />}
        {activeTab === "users"     && <UsersTab />}
        {activeTab === "system"    && <SystemTab />}
      </div>
    </div>
  );
}
