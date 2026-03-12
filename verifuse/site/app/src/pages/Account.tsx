import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth";
import {
  getBillingStatus, getBillingPortalUrl, getInvoices, updateAccount,
  generateApiKey, getApiKeyStatus, revokeApiKey,
  type BillingStatus, type Invoice,
} from "../lib/api";
import { toast } from "../components/Toast";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(ts: number | string | null): string {
  if (!ts) return "—";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function fmtAmount(cents: number, currency: string): string {
  return (cents / 100).toLocaleString("en-US", { style: "currency", currency: currency.toUpperCase() });
}

const TIER_LABELS: Record<string, string> = {
  recon:      "FREE",
  associate:  "INVESTIGATOR",
  partner:    "PARTNER",
  sovereign:  "ENTERPRISE",
};

const SECTION: React.CSSProperties = {
  background: "#111827", border: "1px solid #1f2937", borderRadius: 8,
  padding: "24px 28px", marginBottom: 16,
};

const LABEL: React.CSSProperties = {
  fontSize: "0.68em", opacity: 0.45, letterSpacing: "0.1em",
  textTransform: "uppercase" as const, marginBottom: 4, display: "block",
};

const INPUT: React.CSSProperties = {
  background: "#0d1117", border: "1px solid #374151", borderRadius: 6,
  padding: "9px 13px", color: "#e5e7eb", fontFamily: "monospace",
  fontSize: "0.9em", width: "100%", boxSizing: "border-box" as const,
};

const SH2: React.CSSProperties = {
  fontSize: "0.8em", letterSpacing: "0.12em", opacity: 0.45,
  marginBottom: 20, fontWeight: 700, textTransform: "uppercase" as const,
};

// ── Section: Subscription ────────────────────────────────────────────────────

function SubscriptionSection({ user, billing, billingLoading, portalLoading, onManage }: any) {
  const tierLabel = TIER_LABELS[user?.tier] || user?.tier?.toUpperCase();
  const pct = user?.monthly_grant ? Math.round((user.credits_remaining / user.monthly_grant) * 100) : 100;
  const barColor = pct > 50 ? "#22c55e" : pct > 20 ? "#f59e0b" : "#ef4444";

  return (
    <section style={SECTION}>
      <h2 style={SH2}>Subscription & Billing</h2>
      {billingLoading ? (
        <div style={{ opacity: 0.4, fontSize: "0.85em", marginBottom: 20 }}>Loading billing info...</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 16, marginBottom: 20 }}>
          <div>
            <span style={LABEL}>Plan</span>
            <div style={{ fontWeight: 700, color: "#22c55e", fontSize: "1.1em" }}>{tierLabel}</div>
          </div>
          <div>
            <span style={LABEL}>Credits Remaining</span>
            <div style={{ fontWeight: 700 }}>{user?.credits_remaining} / {user?.monthly_grant ?? "—"}</div>
            <div style={{ background: "#1f2937", borderRadius: 3, height: 4, marginTop: 6, overflow: "hidden" }}>
              <div style={{ background: barColor, width: `${Math.min(pct, 100)}%`, height: "100%", transition: "width 0.3s" }} />
            </div>
          </div>
          <div>
            <span style={LABEL}>Status</span>
            <div style={{ fontWeight: 700, color: billing?.subscription_status === "active" ? "#22c55e" : "#f59e0b" }}>
              {billing?.subscription_status?.toUpperCase() || (!billing?.stripe_customer_id ? "FREE TIER" : "—")}
            </div>
          </div>
          {(billing as any)?.billing_period && (
            <div>
              <span style={LABEL}>Billing</span>
              <div style={{ fontWeight: 700, color: (billing as any).billing_period === "annual" ? "#22c55e" : "#e5e7eb" }}>
                {(billing as any).billing_period === "annual" ? "ANNUAL PLAN" : "MONTHLY PLAN"}
              </div>
            </div>
          )}
          {billing?.current_period_end && (
            <div>
              <span style={LABEL}>Renews</span>
              <div style={{ fontWeight: 700 }}>{fmtDate(billing.current_period_end)}</div>
            </div>
          )}
          {(billing as any)?.subscribed_since && (
            <div>
              <span style={LABEL}>Member Since</span>
              <div style={{ fontWeight: 700 }}>{fmtDate((billing as any).subscribed_since)}</div>
            </div>
          )}
          {billing?.founders_pricing && (
            <div>
              <span style={LABEL}>Pricing</span>
              <div style={{ fontWeight: 700, color: "#f59e0b" }}>FOUNDING ATTORNEY ✓</div>
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        {billing?.stripe_customer_id ? (
          <button
            className="decrypt-btn-sota"
            onClick={onManage}
            disabled={portalLoading}
            style={{ fontSize: "0.82em", padding: "9px 22px" }}
          >
            {portalLoading ? "OPENING PORTAL..." : "MANAGE / CANCEL PLAN"}
          </button>
        ) : (
          <Link to="/pricing" className="decrypt-btn-sota" style={{ fontSize: "0.82em", padding: "9px 22px" }}>
            UPGRADE PLAN
          </Link>
        )}
        <Link to="/pricing" className="btn-outline-sm">VIEW ALL PLANS</Link>
      </div>
      {billing?.stripe_customer_id && (
        <p style={{ fontSize: "0.72em", opacity: 0.35 }}>
          Click "MANAGE / CANCEL PLAN" to cancel, change plan, or update payment via Stripe secure portal.
        </p>
      )}
    </section>
  );
}

// ── Section: Profile ─────────────────────────────────────────────────────────

function ProfileSection({ user }: { user: any }) {
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [firmName, setFirmName] = useState(user?.firm_name || "");
  const [barNumber, setBarNumber] = useState(user?.bar_number || "");
  const [barState, setBarState] = useState(user?.bar_state || "CO");
  const [firmAddress, setFirmAddress] = useState(user?.firm_address || "");
  const [firmPhone, setFirmPhone] = useState(user?.firm_phone || "");
  const [firmWebsite, setFirmWebsite] = useState(user?.firm_website || "");
  const [saving, setSaving] = useState(false);

  // Bar number is locked once set — requires admin to change (fraud prevention)
  const barLocked = Boolean(user?.bar_number?.trim());
  const barVerified = barLocked;

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await updateAccount({ full_name: fullName, firm_name: firmName, bar_number: barNumber, bar_state: barState, firm_address: firmAddress });
      toast("Profile updated", "success");
    } catch (err: any) {
      toast(err?.message || "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section style={SECTION}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <h2 style={{ ...SH2, marginBottom: 0 }}>Firm Profile</h2>
        {/* Bar verification badge */}
        <span style={{
          fontSize: "0.72em", padding: "4px 12px", borderRadius: 4, letterSpacing: "0.06em", fontWeight: 700,
          background: barVerified ? "rgba(34,197,94,0.1)" : "rgba(245,158,11,0.1)",
          color: barVerified ? "#22c55e" : "#f59e0b",
          border: `1px solid ${barVerified ? "rgba(34,197,94,0.3)" : "rgba(245,158,11,0.3)"}`,
        }}>
          {barVerified ? "BAR ✓ VERIFIED" : "BAR — UNVERIFIED"}
        </span>
      </div>

      <form onSubmit={handleSave}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 14 }}>
          <label>
            <span style={LABEL}>Full Name (Attorney)</span>
            <input style={INPUT} type="text" value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Jane Smith, Esq." />
          </label>
          <label>
            <span style={LABEL}>Firm Name</span>
            <input style={INPUT} type="text" value={firmName} onChange={e => setFirmName(e.target.value)} placeholder="Smith & Associates LLC" />
          </label>
          <label>
            <span style={LABEL}>Bar Number {barLocked && <span style={{ color: "#f59e0b", fontWeight: 700, marginLeft: 4 }}>🔒</span>}</span>
            <input
              style={{ ...INPUT, opacity: barLocked ? 0.6 : 1, cursor: barLocked ? "not-allowed" : "text" }}
              type="text"
              value={barNumber}
              onChange={e => !barLocked && setBarNumber(e.target.value)}
              readOnly={barLocked}
              placeholder="CO12345"
              title={barLocked ? "Bar number is locked once set. Contact support to update." : "Enter your Colorado bar number"}
            />
            {barLocked && (
              <div style={{ fontSize: "0.7em", color: "#94a3b8", marginTop: 3 }}>
                Locked — contact <a href="mailto:support@verifuse.tech" style={{ color: "#22c55e" }}>support@verifuse.tech</a> to update
              </div>
            )}
          </label>
          <label>
            <span style={LABEL}>Bar State</span>
            <select style={{ ...INPUT }} value={barState} onChange={e => setBarState(e.target.value)}>
              {["CO","AZ","TX","CA","FL","NY","WA","OR","NV","UT","ID","MT","WY","NM"].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            <span style={LABEL}>Firm Address (used in court filings)</span>
            <input style={INPUT} type="text" value={firmAddress} onChange={e => setFirmAddress(e.target.value)} placeholder="123 Main St, Denver CO 80202" />
          </label>
          <label>
            <span style={LABEL}>Firm Phone</span>
            <input style={INPUT} type="tel" value={firmPhone} onChange={e => setFirmPhone(e.target.value)} placeholder="(720) 555-0100" />
          </label>
          <label>
            <span style={LABEL}>Firm Website</span>
            <input style={INPUT} type="url" value={firmWebsite} onChange={e => setFirmWebsite(e.target.value)} placeholder="https://smithlaw.com" />
          </label>
        </div>

        <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
          <button type="submit" className="decrypt-btn-sota" disabled={saving}
            style={{ fontSize: "0.82em", padding: "9px 22px" }}>
            {saving ? "SAVING..." : "SAVE PROFILE"}
          </button>
          <div style={{ fontSize: "0.75em", opacity: 0.35 }}>EMAIL: {user?.email}</div>
        </div>
      </form>

      {!barVerified && (
        <div style={{ marginTop: 14, padding: "10px 14px", background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 6, fontSize: "0.78em", color: "#f59e0b" }}>
          Add your bar number above to unlock attorney-gated features including restricted lead access and court filing generation.
        </div>
      )}
    </section>
  );
}

// ── Section: API Key ─────────────────────────────────────────────────────────

function ApiKeySection({ user }: { user: any }) {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [keyCreatedAt, setKeyCreatedAt] = useState<string | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getApiKeyStatus(user.user_id).then(d => {
      setHasKey(d.has_key);
      setKeyCreatedAt(d.created_at || null);
    }).catch(() => setHasKey(false));
  }, [user.user_id]);

  async function handleGenerate() {
    setLoading(true);
    try {
      const d = await generateApiKey(user.user_id);
      setNewKey(d.api_key);
      setHasKey(true);
      setKeyCreatedAt(new Date().toISOString());
      toast("API key generated — copy it now, it won't be shown again", "success");
    } catch (err: any) {
      toast(err?.message || "Failed to generate key", "error");
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke() {
    if (!confirm("Revoke API key? All integrations using this key will stop working immediately.")) return;
    setLoading(true);
    try {
      await revokeApiKey(user.user_id);
      setHasKey(false);
      setNewKey(null);
      setKeyCreatedAt(null);
      toast("API key revoked", "success");
    } catch (err: any) {
      toast(err?.message || "Failed to revoke", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section style={SECTION}>
      <h2 style={SH2}>API Key — Programmatic Access</h2>
      <p style={{ fontSize: "0.8em", opacity: 0.5, marginBottom: 8 }}>
        Authenticate automated requests from your case management system, custom dashboard, or data pipeline.
        Send alongside your <code style={{ background: "#1f2937", padding: "1px 6px", borderRadius: 3 }}>Authorization: Bearer</code> JWT token:
      </p>
      <div style={{ fontFamily: "monospace", background: "#0a0f1a", border: "1px solid #1f2937", borderRadius: 6, padding: "8px 14px", fontSize: "0.78em", color: "#6b7280", marginBottom: 14 }}>
        curl -H <span style={{ color: "#22c55e" }}>"Authorization: Bearer &lt;your-jwt&gt;"</span> \<br />
        &nbsp;&nbsp;&nbsp;&nbsp; -H <span style={{ color: "#22c55e" }}>"x-verifuse-api-key: vf_..."</span> \<br />
        &nbsp;&nbsp;&nbsp;&nbsp; https://verifuse.tech/api/leads
      </div>
      <p style={{ fontSize: "0.75em", opacity: 0.4, marginBottom: 16 }}>
        The API key bypasses rate limiting for legitimate integrations. Both headers are required — the JWT authenticates <em>who</em> you are, the API key signals automated access.
        Enterprise tier includes full REST API access.
      </p>

      {hasKey === null && <div style={{ opacity: 0.4, fontSize: "0.85em" }}>Loading...</div>}

      {hasKey === false && !newKey && (
        <button className="btn-outline-sm" onClick={handleGenerate} disabled={loading}>
          {loading ? "GENERATING..." : "GENERATE API KEY"}
        </button>
      )}

      {(hasKey === true || newKey) && !newKey && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ fontFamily: "monospace", background: "#0d1117", border: "1px solid #374151", borderRadius: 6, padding: "8px 14px", fontSize: "0.85em", color: "#22c55e" }}>
            vf_••••••••••••••••••••••  {keyCreatedAt ? `(created ${fmtDate(keyCreatedAt)})` : ""}
          </div>
          <button className="btn-outline-sm" onClick={handleGenerate} disabled={loading}>ROTATE KEY</button>
          <button className="btn-outline-sm" onClick={handleRevoke} disabled={loading}
            style={{ borderColor: "#ef4444", color: "#ef4444" }}>REVOKE</button>
        </div>
      )}

      {newKey && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: "0.75em", color: "#f59e0b", marginBottom: 6 }}>
            COPY THIS KEY NOW — it will not be shown again:
          </div>
          <div style={{
            fontFamily: "monospace", background: "#0d1117", border: "1px solid #22c55e",
            borderRadius: 6, padding: "10px 16px", fontSize: "0.9em", color: "#22c55e",
            letterSpacing: "0.05em", wordBreak: "break-all",
            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12,
          }}>
            <span>{newKey}</span>
            <button className="btn-outline-sm" style={{ flexShrink: 0 }}
              onClick={() => { navigator.clipboard.writeText(newKey); toast("Copied!", "success"); }}>
              COPY
            </button>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button className="btn-outline-sm" onClick={handleRevoke} disabled={loading}
              style={{ borderColor: "#ef4444", color: "#ef4444" }}>REVOKE</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ── Section: Security ────────────────────────────────────────────────────────

function SecuritySection({ user }: { user: any }) {
  return (
    <section style={SECTION}>
      <h2 style={SH2}>Security</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 14, marginBottom: 16 }}>
        <div style={{ padding: "12px 16px", background: "#0d1117", borderRadius: 6, border: "1px solid #1f2937" }}>
          <span style={LABEL}>Email</span>
          <div style={{ fontWeight: 600, wordBreak: "break-all" }}>{user?.email}</div>
          <div style={{ fontSize: "0.72em", opacity: 0.4, marginTop: 4 }}>
            {user?.email_verified ? "✓ Verified" : "⚠ Not verified"}
          </div>
        </div>
        <div style={{ padding: "12px 16px", background: "#0d1117", borderRadius: 6, border: "1px solid #1f2937" }}>
          <span style={LABEL}>Account Lockout</span>
          <div style={{ fontWeight: 600, color: "#22c55e" }}>Active</div>
          <div style={{ fontSize: "0.72em", opacity: 0.4, marginTop: 4 }}>5 failed attempts → 15min lock</div>
        </div>
        <div style={{ padding: "12px 16px", background: "#0d1117", borderRadius: 6, border: "1px solid #1f2937" }}>
          <span style={LABEL}>Session Tokens</span>
          <div style={{ fontWeight: 600 }}>72-hour JWT</div>
          <div style={{ fontSize: "0.72em", opacity: 0.4, marginTop: 4 }}>Auto-revoke on password change</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Link to="/forgot-password" className="btn-outline-sm">CHANGE PASSWORD</Link>
      </div>
      <p style={{ fontSize: "0.72em", opacity: 0.35, marginTop: 10 }}>
        Password reset link will be sent to {user?.email}.
        All active sessions are revoked when password changes.
      </p>
    </section>
  );
}

// ── Section: Invoice History ─────────────────────────────────────────────────

function InvoiceSection({ invoices }: { invoices: Invoice[] }) {
  if (invoices.length === 0) return null;
  return (
    <section style={SECTION}>
      <h2 style={SH2}>Invoice History</h2>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #374151" }}>
              {["Date", "Description", "Amount", "Status", "PDF"].map(h => (
                <th key={h} style={{ textAlign: h === "Amount" ? "right" : h === "Status" || h === "PDF" ? "center" : "left", padding: "6px 10px", opacity: 0.4, fontSize: "0.85em", letterSpacing: "0.08em" }}>
                  {h.toUpperCase()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {invoices.map(inv => (
              <tr key={inv.id} style={{ borderBottom: "1px solid #1f2937" }}>
                <td style={{ padding: "9px 10px", color: "#94a3b8" }}>{fmtDate(inv.created)}</td>
                <td style={{ padding: "9px 10px" }}>{inv.description || `Invoice ${inv.number || inv.id.slice(0, 8)}`}</td>
                <td style={{ padding: "9px 10px", textAlign: "right", color: "#22c55e", fontWeight: 700 }}>
                  {fmtAmount(inv.amount_paid, inv.currency)}
                </td>
                <td style={{ padding: "9px 10px", textAlign: "center" }}>
                  <span style={{
                    fontSize: "0.73em", padding: "2px 8px", borderRadius: 4, letterSpacing: "0.05em", fontWeight: 700,
                    background: inv.status === "paid" ? "rgba(34,197,94,0.12)" : "rgba(245,158,11,0.12)",
                    color: inv.status === "paid" ? "#22c55e" : "#f59e0b",
                  }}>
                    {inv.status.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: "9px 10px", textAlign: "center" }}>
                  {inv.invoice_pdf ? (
                    <a href={inv.invoice_pdf} target="_blank" rel="noopener noreferrer"
                      style={{ color: "#22c55e", fontSize: "0.85em", textDecoration: "underline" }}>
                      PDF ↗
                    </a>
                  ) : <span style={{ opacity: 0.25 }}>—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Main Account Page ─────────────────────────────────────────────────────────

export default function Account() {
  const { user, loading: authLoading, logout } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [billingLoading, setBillingLoading] = useState(true);
  const [portalLoading, setPortalLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"subscription" | "profile" | "security" | "api" | "invoices">("subscription");

  // Success banners from Stripe redirects
  const justSubscribed = searchParams.get("subscribed") === "1";
  const justCredited = searchParams.get("credits") === "1";

  useEffect(() => {
    if (!authLoading && !user) navigate("/login");
  }, [authLoading, user, navigate]);

  useEffect(() => {
    if (!user) return;
    setBillingLoading(true);
    Promise.all([getBillingStatus(), getInvoices()])
      .then(([b, inv]) => { setBilling(b); setInvoices(inv.invoices || []); })
      .catch(() => {})
      .finally(() => setBillingLoading(false));
  }, [user]);

  async function handleManageBilling() {
    setPortalLoading(true);
    try {
      const { portal_url } = await getBillingPortalUrl();
      window.location.href = portal_url;
    } catch (err: any) {
      toast(err?.message || "Could not open billing portal", "error");
    } finally {
      setPortalLoading(false);
    }
  }

  if (authLoading || !user) {
    return (
      <div className="dashboard" style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div className="loader-ring" />
      </div>
    );
  }

  const tierLabel = TIER_LABELS[user.tier] || user.tier?.toUpperCase();

  const TABS: { id: typeof activeTab; label: string }[] = [
    { id: "subscription", label: "SUBSCRIPTION" },
    { id: "profile",      label: "FIRM PROFILE" },
    { id: "security",     label: "SECURITY" },
    { id: "api",          label: "API KEY" },
    ...(invoices.length > 0 ? [{ id: "invoices" as const, label: `INVOICES (${invoices.length})` }] : []),
  ];

  return (
    <div className="dashboard">
      {/* Stripe success banners */}
      {justSubscribed && (
        <div style={{ background: "rgba(34,197,94,0.12)", borderBottom: "1px solid rgba(34,197,94,0.3)", padding: "14px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ color: "#22c55e", fontWeight: 700 }}>✓ Subscription activated! Your credits have been added.</span>
          <button onClick={() => setSearchParams(p => { p.delete("subscribed"); p.delete("session_id"); return p; })} style={{ background: "none", border: "none", color: "#94a3b8", cursor: "pointer", fontSize: "1.1em" }}>×</button>
        </div>
      )}
      {justCredited && !justSubscribed && (
        <div style={{ background: "rgba(34,197,94,0.12)", borderBottom: "1px solid rgba(34,197,94,0.3)", padding: "14px 24px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ color: "#22c55e", fontWeight: 700 }}>✓ Credits added to your account. They're ready to use now.</span>
          <button onClick={() => setSearchParams(p => { p.delete("credits"); return p; })} style={{ background: "none", border: "none", color: "#94a3b8", cursor: "pointer", fontSize: "1.1em" }}>×</button>
        </div>
      )}
      {/* Header */}
      <header className="dash-header">
        <Link to="/dashboard" className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-user">
          <span className="tier-badge">{tierLabel}</span>
          <span className="credits-badge">{user.credits_remaining} credits</span>
          <Link to="/dashboard" className="btn-outline-sm">DASHBOARD</Link>
          <Link to="/my-cases" className="btn-outline-sm">MY PIPELINE</Link>
          <Link to="/pricing" className="btn-outline-sm">PRICING</Link>
          {user.is_admin && <Link to="/admin" className="btn-outline-sm">ADMIN</Link>}
          <button className="btn-outline-sm" onClick={logout}>LOGOUT</button>
        </div>
      </header>

      <div style={{ maxWidth: 860, margin: "0 auto", padding: "28px 20px" }}>

        {/* Page title */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: "1.2em", letterSpacing: "0.12em", fontWeight: 700, marginBottom: 4 }}>
            ACCOUNT <span className="text-green">// SETTINGS</span>
          </h1>
          <div style={{ fontSize: "0.78em", opacity: 0.35 }}>{user.email} · {user.firm_name || "No firm set"}</div>
        </div>

        {/* Tab nav */}
        <div style={{ display: "flex", gap: 4, marginBottom: 20, borderBottom: "1px solid #1f2937", paddingBottom: 0 }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                background: "none", border: "none", padding: "8px 16px 10px",
                cursor: "pointer", fontFamily: "monospace", fontSize: "0.75em",
                letterSpacing: "0.08em", fontWeight: activeTab === tab.id ? 700 : 400,
                color: activeTab === tab.id ? "#22c55e" : "#64748b",
                borderBottom: activeTab === tab.id ? "2px solid #22c55e" : "2px solid transparent",
                marginBottom: -1,
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === "subscription" && (
          <SubscriptionSection
            user={user} billing={billing} billingLoading={billingLoading}
            portalLoading={portalLoading} onManage={handleManageBilling}
          />
        )}

        {activeTab === "profile" && <ProfileSection user={user} />}

        {activeTab === "security" && <SecuritySection user={user} />}

        {activeTab === "api" && <ApiKeySection user={user} />}

        {activeTab === "invoices" && <InvoiceSection invoices={invoices} />}

        {/* Account footer */}
        <section style={{ ...SECTION, borderColor: "#1f2937", marginTop: 8 }}>
          <h2 style={{ ...SH2, marginBottom: 12 }}>Account</h2>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button className="btn-outline-sm" onClick={logout}
              style={{ borderColor: "#ef4444", color: "#ef4444" }}>
              LOGOUT
            </button>
          </div>
          <p style={{ fontSize: "0.72em", opacity: 0.3, marginTop: 12 }}>
            To delete your account or export your data, contact support: support@verifuse.tech
          </p>
        </section>
      </div>
    </div>
  );
}
