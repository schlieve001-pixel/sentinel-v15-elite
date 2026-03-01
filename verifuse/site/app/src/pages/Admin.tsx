import { useEffect, useState, useCallback } from "react";
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
  platform_type?: string;
  leads_count?: number;
  last_scraped_at?: string;
  active?: boolean;
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
    try {
      await adminFetch("/api/admin/attorney/reject", {
        method: "POST",
        body: JSON.stringify({ user_id, reason: "Admin review" }),
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

function SystemTab() {
  const [coverage, setCoverage] = useState<CoverageCounty[]>([]);
  const [health, setHealth] = useState<{ status: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      adminFetch<{ counties: CoverageCounty[] }>("/api/admin/coverage")
        .then((r) => setCoverage(r.counties || []))
        .catch(() => setCoverage([])),
      fetch(`${API_BASE}/health`)
        .then((r) => r.json())
        .then(setHealth)
        .catch(() => setHealth({ status: "error" })),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="processing-text">Loading system status...</p>;

  const healthOk = health?.status === "ok";

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h4 style={{ fontSize: "0.8em", letterSpacing: "0.08em", opacity: 0.6, marginBottom: 8 }}>
          API HEALTH
        </h4>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            display: "inline-block", width: 10, height: 10, borderRadius: "50%",
            background: healthOk ? "#22c55e" : "#ef4444",
          }} />
          <span style={{ fontSize: "0.9em", fontWeight: 600 }}>
            {healthOk ? "SYSTEM LIVE" : "SYSTEM ERROR"}
          </span>
        </div>
      </div>

      <h4 style={{ fontSize: "0.8em", letterSpacing: "0.08em", opacity: 0.6, marginBottom: 10 }}>
        COUNTY COVERAGE ({coverage.length} counties)
      </h4>
      {coverage.length === 0 ? (
        <p style={{ opacity: 0.5, fontSize: "0.85em" }}>No coverage data available.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #374151", opacity: 0.6 }}>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>COUNTY</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>PLATFORM</th>
                <th style={{ textAlign: "right", padding: "6px 10px" }}>LEADS</th>
                <th style={{ textAlign: "left", padding: "6px 10px" }}>LAST SCRAPED</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((c) => (
                <tr key={c.county} style={{ borderBottom: "1px solid #1f2937" }}>
                  <td style={{ padding: "6px 10px" }}>{c.county}</td>
                  <td style={{ padding: "6px 10px", opacity: 0.6 }}>{c.platform_type || "—"}</td>
                  <td style={{ padding: "6px 10px", textAlign: "right" }}>{c.leads_count ?? "—"}</td>
                  <td style={{ padding: "6px 10px", opacity: 0.5, fontSize: "0.85em" }}>
                    {c.last_scraped_at?.slice(0, 10) || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
