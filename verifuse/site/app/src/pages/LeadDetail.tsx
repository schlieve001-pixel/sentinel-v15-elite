import { useEffect, useState } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import { getLeadDetail, unlockLead, unlockRestrictedLead, downloadSecure, downloadSample, generateLetter, sendVerification, verifyEmail, getAssetEvidence, downloadEvidenceDoc, getLeadAudit, API_BASE, type Lead, type UnlockResponse, type EvidenceDoc, type LeadAuditTrail, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { toast } from "../components/Toast";

function SkipTracePanel({ assetId, userTier, autoRun }: { assetId: string; userTier: string; autoRun?: boolean }) {
  const [contact, setContact] = useState<Record<string, string | null> | null>(null);
  const [loading, setLoading] = useState(false);
  const [ran, setRan] = useState(false);
  const [buyLoading, setBuyLoading] = useState(false);
  const [autoRunMsg, setAutoRunMsg] = useState("");

  const _apiBase = () => API_BASE;
  const _token = () => localStorage.getItem("vf_token") || "";

  // Enterprise users get 10 skip traces/month included
  const isEnterprise = userTier === "sovereign";

  // Auto-run after returning from Stripe skip trace purchase (allow time for webhook)
  useEffect(() => {
    if (!autoRun || ran) return;
    setAutoRunMsg("Processing payment — running skip trace...");
    const t = setTimeout(async () => {
      setAutoRunMsg("");
      await runSkipTrace();
    }, 4000);
    return () => clearTimeout(t);
  }, [autoRun]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runSkipTrace() {
    setLoading(true);
    try {
      const res = await fetch(`${_apiBase()}/api/lead/${assetId}/owner-contact`, {
        headers: { Authorization: `Bearer ${_token()}` },
      });
      if (res.ok) {
        const data = await res.json();
        setContact(data);
        setRan(true);
      } else if (res.status === 402) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Skip trace requires a $29 purchase.", "error");
      } else if (res.status === 429) {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Monthly skip trace limit reached.", "error");
      } else {
        toast("Contact data not yet available for this lead.", "error");
      }
    } catch { toast("Failed to fetch contact intel", "error"); }
    finally { setLoading(false); }
  }

  async function buyAndRun() {
    setBuyLoading(true);
    try {
      const res = await fetch(`${_apiBase()}/api/billing/one-time`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${_token()}` },
        body: JSON.stringify({ sku: "skip_trace", lead_id: assetId, return_path: window.location.pathname + "?ran=1" }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.checkout_url) window.location.href = data.checkout_url;
        else toast("Checkout unavailable", "error");
      } else {
        const err = await res.json().catch(() => ({}));
        toast(err.detail || "Checkout failed", "error");
      }
    } catch { toast("Failed to start checkout", "error"); }
    finally { setBuyLoading(false); }
  }

  if (ran && contact) {
    return (
      <div style={{ fontSize: "0.8em", lineHeight: 1.8 }}>
        {contact.mailing_address && (
          <div><span style={{ color: "#6b7280" }}>MAILING ADDRESS: </span><span style={{ color: "#e5e7eb", fontWeight: 700 }}>{contact.mailing_address}</span></div>
        )}
        {contact.forwarding_address && (
          <div><span style={{ color: "#6b7280" }}>FORWARDING: </span><span style={{ color: "#22c55e", fontWeight: 700 }}>{contact.forwarding_address}</span></div>
        )}
        {contact.address_source && (
          <div style={{ fontSize: "0.85em", color: "#4b5563", marginTop: 4 }}>
            Source: {contact.address_source} · Confidence: {contact.address_confidence || "—"}
            {contact.last_verified && ` · Verified: ${contact.last_verified}`}
          </div>
        )}
        {contact.note && (
          <div style={{ marginTop: 6, padding: "6px 10px", background: "#1a2332", border: "1px solid #3b82f6", borderRadius: 4, fontSize: "0.82em", color: "#93c5fd" }}>
            {contact.note}
          </div>
        )}
      </div>
    );
  }

  if (autoRunMsg) {
    return <div style={{ fontSize: "0.75em", color: "#6b7280", fontStyle: "italic" }}>{autoRunMsg}</div>;
  }

  if (isEnterprise) {
    return (
      <div>
        <button
          onClick={runSkipTrace}
          disabled={loading}
          style={{ background: loading ? "#1f2937" : "#14532d", border: "1px solid #22c55e", borderRadius: 4, color: "#4ade80", cursor: loading ? "default" : "pointer", fontSize: "0.78em", fontWeight: 700, fontFamily: "inherit", padding: "7px 16px" }}
        >
          {loading ? "RUNNING..." : "RUN SKIP TRACE (INCLUDED)"}
        </button>
        <div style={{ marginTop: 4, fontSize: "0.7em", color: "#4b5563" }}>
          Enterprise · 10 skip traces/month included · Resets monthly
        </div>
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={buyAndRun}
        disabled={buyLoading}
        style={{ background: buyLoading ? "#1f2937" : "#1c1f2e", border: "1px solid #3b82f6", borderRadius: 4, color: "#93c5fd", cursor: buyLoading ? "default" : "pointer", fontSize: "0.78em", fontWeight: 700, fontFamily: "inherit", padding: "7px 16px" }}
      >
        {buyLoading ? "REDIRECTING TO CHECKOUT..." : "SKIP TRACE — $29"}
      </button>
      <div style={{ marginTop: 6, fontSize: "0.68em", color: "#4b5563" }}>
        $29 one-time · Result appears here after payment ·{" "}
        <a href="/pricing" style={{ color: "#a78bfa", textDecoration: "none" }}>Enterprise includes 10/month →</a>
      </div>
    </div>
  );
}

function isVerifyEmailError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 &&
    /verify/i.test(err.message) && /email/i.test(err.message);
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "\u2014";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LeadDetail() {
  const { assetId } = useParams<{ assetId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Smart back navigation
  const backUrl = (location.state as { from?: string })?.from
    || sessionStorage.getItem("lastLeadsUrl")
    || (user ? "/dashboard" : "/preview");

  function goBack() {
    navigate(backUrl, { replace: true });
  }
  const [lead, setLead] = useState<Lead | null>(null);
  const [unlocked, setUnlocked] = useState<UnlockResponse | null>(null);
  const [autoUnlocking, setAutoUnlocking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState("");
  const [showVerifyPrompt, setShowVerifyPrompt] = useState(false);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifySending, setVerifySending] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState("");
  const [evidenceDocs, setEvidenceDocs] = useState<EvidenceDoc[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [auditTrail, setAuditTrail] = useState<LeadAuditTrail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [showAudit, setShowAudit] = useState(false);

  // C6: Evidence preview (visible regardless of lock status)
  const [evidencePreview, setEvidencePreview] = useState<any[]>([]);

  // Court filing loading
  const [filingLoading, setFilingLoading] = useState(false);

  // Case timeline (2C)
  const [showTimeline, setShowTimeline] = useState(false);
  const [timeline, setTimeline] = useState<any[]>([]);

  // Title stack (4C)
  const [showTitleStack, setShowTitleStack] = useState(false);
  const [titleStack, setTitleStack] = useState<any>(null);

  // Add to pipeline (4A)
  const [showPipelineModal, setShowPipelineModal] = useState(false);

  function _apiBase(): string { return API_BASE || ""; }
  function _token(): string { return localStorage.getItem("vf_token") || ""; }

  async function loadTimeline() {
    if (!showTimeline) {
      try {
        const res = await fetch(`${_apiBase()}/api/lead/${assetId}/timeline`, { headers: { Authorization: `Bearer ${_token()}` } });
        if (res.ok) setTimeline(await res.json() || []);
        else setTimeline([]);
      } catch { setTimeline([]); }
      setShowTimeline(true);
    } else {
      setShowTimeline(false);
    }
  }

  async function loadTitleStack() {
    if (!showTitleStack) {
      try {
        const res = await fetch(`${_apiBase()}/api/lead/${assetId}/title-stack`, { headers: { Authorization: `Bearer ${_token()}` } });
        if (res.ok) setTitleStack(await res.json());
        else setTitleStack(null);
      } catch { setTitleStack(null); }
      setShowTitleStack(true);
    } else {
      setShowTitleStack(false);
    }
  }

  async function addToPipeline(stage: string) {
    try {
      const res = await fetch(`${_apiBase()}/api/my-cases`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${_token()}` },
        body: JSON.stringify({ asset_id: assetId, stage }),
      });
      if (res.ok) {
        toast(`Added to your pipeline as ${stage.replace(/_/g, " ")}`, "success");
        setShowPipelineModal(false);
      } else {
        const body = await res.json().catch(() => ({}));
        toast(body.detail || "Failed to add to pipeline", "error");
      }
    } catch {
      toast("Failed to add to pipeline", "error");
    }
  }

  useEffect(() => {
    if (!assetId) return;
    const ac = new AbortController();
    getLeadDetail(assetId, ac.signal)
      .then(setLead)
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Failed to load");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [assetId]);

  // Auto-unlock when lead was already purchased by this user (no credit charge — INSERT OR IGNORE)
  useEffect(() => {
    if (!lead?.unlocked_by_me || !assetId || unlocked) return;
    setAutoUnlocking(true);
    unlockLead(assetId).then(setUnlocked).catch(() => {}).finally(() => setAutoUnlocking(false));
  }, [lead?.unlocked_by_me, assetId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-load evidence docs for attorneys/admins when registry_asset_id is available
  useEffect(() => {
    const isAttorney = user?.is_admin || user?.role === "approved_attorney" || user?.role === "admin";
    if (!lead?.registry_asset_id || !isAttorney) return;
    const ac = new AbortController();
    setEvidenceLoading(true);
    getAssetEvidence(lead.registry_asset_id, ac.signal)
      .then(setEvidenceDocs)
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setEvidenceError(err instanceof ApiError ? err.message : "Failed to load evidence");
      })
      .finally(() => setEvidenceLoading(false));
    return () => ac.abort();
  }, [lead?.registry_asset_id, user]);

  // C6: Evidence preview — fetch metadata regardless of lock status
  useEffect(() => {
    if (!assetId) return;
    const token = localStorage.getItem("vf_token") || "";
    fetch(`${API_BASE}/api/lead/${assetId}/evidence-preview`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : { docs: [] })
      .then(d => setEvidencePreview(d.docs || []))
      .catch(() => {});
  }, [assetId]);

  function handleUnlockError(err: unknown) {
    if (isVerifyEmailError(err)) {
      setShowVerifyPrompt(true);
      setError("");
    } else {
      setError(err instanceof ApiError ? err.message : "Unlock failed");
    }
  }

  async function handleUnlock() {
    if (!assetId) return;
    if (!user) {
      navigate("/login");
      return;
    }
    setUnlocking(true);
    setError("");
    try {
      const res = await unlockLead(assetId);
      setUnlocked(res);
      const spent = res.credits_spent ?? 1;
      const remaining = res.credits_remaining;
      toast(
        remaining != null
          ? `Lead unlocked · ${spent} credit${spent !== 1 ? "s" : ""} used · ${remaining} remaining`
          : "Lead unlocked — intel is now available",
        "success"
      );
    } catch (err) {
      handleUnlockError(err);
    } finally {
      setUnlocking(false);
    }
  }


  const isRestricted = lead?.restriction_status === "RESTRICTED";
  const _isExpired = lead?.deadline_passed === true || lead?.restriction_status === ("EXPIRED" as any); void _isExpired;

  // Derived display values
  const gradeColor = lead?.data_grade === "GOLD" ? "#f59e0b"
    : lead?.data_grade === "SILVER" ? "#94a3b8"
    : lead?.data_grade === "BRONZE" ? "#b45309"
    : "#6b7280";
  const oppScore = (lead as any)?.opportunity_score;
  const oppGrade = oppScore >= 90 ? "A+" : oppScore >= 80 ? "A" : oppScore >= 70 ? "B" : oppScore >= 60 ? "C" : "D";
  const oppColor = oppScore >= 80 ? "#22c55e" : oppScore >= 60 ? "#f59e0b" : "#94a3b8";
  const verTier = (lead as any)?.verification_tier || ((lead?.pool_source as any) === "TRIPLE_VERIFIED" ? "TRIPLE_VERIFIED" : (lead?.pool_source as any) === "AI_VERIFIED" ? "AI_VERIFIED" : lead?.pool_source === "HTML_MATH" ? "HTML_MATH" : null);
  const tierColor = verTier === "TRIPLE_VERIFIED" ? "#22c55e" : verTier === "AI_VERIFIED" ? "#818cf8" : verTier === "HTML_MATH" ? "#f59e0b" : "#64748b";

  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "'JetBrains Mono','Fira Mono',monospace" }}>

      {/* ── Command Bar ── */}
      <header style={{ background: "#0d1117", borderBottom: "1px solid #1f2937", padding: "0 24px", height: 52, display: "flex", alignItems: "center", justifyContent: "space-between", position: "sticky", top: 0, zIndex: 50 }}>
        <Link to={user ? "/dashboard" : "/preview"} style={{ color: "#e5e7eb", textDecoration: "none", fontWeight: 700, fontSize: "0.88em", letterSpacing: "0.08em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>//</span> INTELLIGENCE
        </Link>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <span style={{ fontSize: "0.7em", color: "#22c55e", letterSpacing: "0.06em" }}>
            <span style={{ display: "inline-block", width: 6, height: 6, borderRadius: "50%", background: "#22c55e", marginRight: 6, boxShadow: "0 0 4px #22c55e" }} />
            LIVE DATA
          </span>
          {user && <Link to="/account" style={{ fontSize: "0.75em", color: "#64748b", textDecoration: "none" }}>{user.email}</Link>}
        </div>
      </header>

      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "20px 24px 60px" }}>

        {/* ── Breadcrumb ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <button onClick={goBack} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontFamily: "inherit", fontSize: "0.78em", padding: 0, display: "flex", alignItems: "center", gap: 6 }}>
            ← BACK TO VAULT
          </button>
          <span style={{ color: "#1f2937" }}>·</span>
          <span style={{ fontSize: "0.72em", color: "#374151", letterSpacing: "0.1em" }}>
            {lead?.county?.toUpperCase().replace(/_/g, " ")} COUNTY
          </span>
          <span style={{ color: "#1f2937" }}>·</span>
          <span style={{ fontSize: "0.72em", color: "#374151" }}>CASE DOSSIER</span>
        </div>

        {loading && (
          <div style={{ padding: 60, textAlign: "center", color: "#374151", fontSize: "0.85em", letterSpacing: "0.1em" }}>LOADING INTELLIGENCE...</div>
        )}
        {error && !lead && (
          <div style={{ padding: 40, textAlign: "center", color: "#ef4444", fontSize: "0.85em" }}>{error}</div>
        )}

        {lead && (
          <>

          {/* ══════════════════════════════════════════════════════════
              HERO SECTION — Grade + Surplus + Claim Window
              ══════════════════════════════════════════════════════════ */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 20, marginBottom: 20, background: "#111827", border: "1px solid #1f2937", borderRadius: 10, overflow: "hidden" }}>

            {/* LEFT: Main intelligence */}
            <div style={{ padding: "28px 32px" }}>
              {/* Badge row */}
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
                <span style={{ background: gradeColor + "22", border: `1px solid ${gradeColor}55`, color: gradeColor, padding: "3px 10px", borderRadius: 4, fontSize: "0.72em", fontWeight: 700, letterSpacing: "0.1em" }}>
                  {lead.data_grade}
                </span>
                {verTier && (
                  <span style={{ background: tierColor + "18", border: `1px solid ${tierColor}44`, color: tierColor, padding: "3px 10px", borderRadius: 4, fontSize: "0.68em", fontWeight: 700, letterSpacing: "0.08em" }}>
                    {verTier.replace(/_/g, " ")}
                  </span>
                )}
                {(lead as any).verification_state === "READY_TO_FILE" && (
                  <span style={{ background: "#14532d", border: "1px solid #16a34a", color: "#4ade80", padding: "3px 10px", borderRadius: 4, fontSize: "0.68em", fontWeight: 700, letterSpacing: "0.08em" }}>
                    ✓ READY TO FILE
                  </span>
                )}
                {(lead as any).attorney_packet_ready === 1 && (
                  <span style={{ background: "#1e3a2e", border: "1px solid #22c55e44", color: "#22c55e", padding: "3px 10px", borderRadius: 4, fontSize: "0.68em", letterSpacing: "0.06em" }}>
                    ATTORNEY READY
                  </span>
                )}
                {(lead as any).processing_status === "PRE_SALE" && (
                  <span style={{ background: "#0c4a6e22", border: "1px solid #0284c744", color: "#38bdf8", padding: "3px 10px", borderRadius: 4, fontSize: "0.68em", letterSpacing: "0.06em" }}>
                    PRE-SALE MONITORING
                  </span>
                )}
                {lead.unlocked_by_me && (
                  <span style={{ background: "#14532d22", border: "1px solid #22c55e44", color: "#4ade80", padding: "3px 10px", borderRadius: 4, fontSize: "0.68em", letterSpacing: "0.06em" }}>
                    ✓ UNLOCKED
                  </span>
                )}
              </div>

              {/* Surplus — the big number */}
              <div style={{ fontSize: "0.65em", letterSpacing: "0.12em", color: lead.display_tier === "VERIFIED" ? "#10b981" : "#f59e0b", marginBottom: 6 }}>
                {lead.net_to_owner_label || (lead.display_tier === "VERIFIED" ? "VERIFIED NET TO OWNER" : "OVERBID POOL — POTENTIAL SURPLUS")}
              </div>
              <div style={{ fontSize: "3.2em", fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1, marginBottom: 8, color: lead.estimated_surplus == null ? "#374151" : lead.estimated_surplus > 10000 ? "#f0fdf4" : "#e5e7eb" }}>
                {lead.estimated_surplus == null ? (
                  <span style={{ color: "#374151", fontSize: "0.5em", fontStyle: "italic", letterSpacing: "0.05em" }}>SURPLUS NOT AVAILABLE</span>
                ) : fmt(lead.estimated_surplus)}
              </div>

              {/* Case identifier + county */}
              <div style={{ display: "flex", gap: 16, alignItems: "baseline", flexWrap: "wrap" }}>
                <div style={{ fontFamily: "monospace", fontSize: "0.85em", color: "#94a3b8", letterSpacing: "0.06em" }}>
                  CASE {lead.case_number || lead.registry_asset_id?.split(":")[3] || lead.asset_id?.substring(0, 12)}
                </div>
                <div style={{ fontSize: "0.72em", color: "#4b5563", letterSpacing: "0.06em" }}>
                  {lead.county?.toUpperCase().replace(/_/g, " ")} COUNTY, CO
                </div>
                {lead.sale_date && (
                  <div style={{ fontSize: "0.72em", color: "#4b5563" }}>
                    SOLD {lead.sale_date}
                  </div>
                )}
              </div>
            </div>

            {/* RIGHT: Opportunity score + status */}
            <div style={{ background: "#0d1117", borderLeft: "1px solid #1f2937", padding: "28px 28px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20, minWidth: 200 }}>
              {oppScore != null ? (
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#4b5563", marginBottom: 8 }}>OPP SCORE</div>
                  <div style={{ fontSize: "3.5em", fontWeight: 700, color: oppColor, lineHeight: 1 }}>{oppGrade}</div>
                  <div style={{ fontSize: "0.72em", color: "#374151", marginTop: 4 }}>{oppScore}/100</div>
                </div>
              ) : (
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 8 }}>OPP SCORE</div>
                  <div style={{ fontSize: "2em", fontWeight: 700, color: "#374151" }}>—</div>
                </div>
              )}
              {/* Window status pill */}
              <div style={{ textAlign: "center" }}>
                {isRestricted ? (
                  <div style={{ background: "#7f1d1d22", border: "1px solid #ef444444", borderRadius: 6, padding: "8px 12px" }}>
                    <div style={{ fontSize: "0.65em", color: "#ef4444", fontWeight: 700, letterSpacing: "0.08em" }}>WINDOW LOCKED</div>
                    <div style={{ fontSize: "0.72em", color: "#9ca3af", marginTop: 2 }}>{lead.days_until_actionable}d remaining</div>
                  </div>
                ) : lead.deadline_passed ? (
                  <div style={{ background: "#1f293722", border: "1px solid #374151", borderRadius: 6, padding: "8px 12px" }}>
                    <div style={{ fontSize: "0.65em", color: "#6b7280", fontWeight: 700, letterSpacing: "0.08em" }}>WINDOW CLOSED</div>
                  </div>
                ) : lead.days_to_claim != null ? (
                  <div style={{ background: lead.days_to_claim < 60 ? "#7f1d1d22" : "#14532d22", border: `1px solid ${lead.days_to_claim < 60 ? "#ef444444" : "#22c55e44"}`, borderRadius: 6, padding: "8px 12px" }}>
                    <div style={{ fontSize: "0.65em", color: lead.days_to_claim < 60 ? "#ef4444" : "#22c55e", fontWeight: 700, letterSpacing: "0.08em" }}>CLAIM WINDOW</div>
                    <div style={{ fontSize: "1.3em", fontWeight: 700, color: lead.days_to_claim < 60 ? "#ef4444" : "#22c55e", marginTop: 2 }}>{lead.days_to_claim}d</div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {/* F1: Ready To File Banner */}
          {(lead as any).verification_state === 'READY_TO_FILE' && (
            <div style={{ margin: "16px 0", padding: "14px 20px", background: "rgba(34,197,94,0.08)", border: "1px solid #22c55e", borderRadius: 8, display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ color: "#22c55e", fontWeight: 700, fontSize: "1.1em" }}>✓ READY TO FILE</span>
              <span style={{ fontSize: "0.82em", color: "#6b7280" }}>
                All required fields confirmed · Expected recovery: {lead.estimated_surplus != null && lead.estimated_surplus > 0 ? `$${lead.estimated_surplus.toLocaleString()}` : "see details"} · Filing packet: 3 credits
              </span>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════════
              TWO-COLUMN INTELLIGENCE GRID
              ══════════════════════════════════════════════════════════ */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16, marginBottom: 16 }}>

            {/* LEFT COLUMN — Case Intel */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

              {/* Case data table */}
              <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px" }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>CASE INTELLIGENCE</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 24px" }}>
                  {[
                    { label: "PROPERTY", value: lead.address_hint || lead.property_address || `${lead.county?.toUpperCase()} COUNTY, CO` },
                    { label: "CASE NUMBER", value: lead.case_number || "—" },
                    { label: "COUNTY", value: lead.county?.replace(/_/g, " ").toUpperCase() + ", CO" },
                    { label: "SALE DATE", value: lead.sale_date || "PENDING" },
                    { label: "SURPLUS STREAM", value: lead.surplus_stream?.replace(/_/g, " ") || "FORECLOSURE OVERBID" },
                    { label: "POOL SOURCE", value: lead.pool_source || "UNVERIFIED" },
                    { label: "FILING STATUS", value: isRestricted ? "WINDOW NOT YET OPEN" : lead.deadline_passed ? "WINDOW CLOSED" : "OPEN FOR FILING" },
                    { label: "DATA AGE", value: lead.data_age_days != null ? `${lead.data_age_days} days` : "—" },
                  ].map(({ label, value }) => (
                    <div key={label}>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>{label}</div>
                      <div style={{ fontSize: "0.82em", color: "#e5e7eb", fontWeight: 600 }}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Financial analysis */}
              <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px" }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>FINANCIAL ANALYSIS</div>
                {/* C1: Unverified overbid pool warning */}
                {(lead as any).winning_bid && !((lead as any).total_debt) && lead.pool_source === "UNVERIFIED" && (
                  <div style={{ marginBottom: 12, padding: "8px 12px", background: "#1c1005", border: "1px solid #78350f44", borderRadius: 4, fontSize: "0.78em", color: "#f59e0b" }}>
                    OVERBID POOL: {fmt((lead as any).winning_bid)} (Unverified — total debt not extracted)
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 24px" }}>
                  <div>
                    <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>OVERBID AMOUNT</div>
                    <div style={{ fontSize: "1.1em", color: "#f59e0b", fontWeight: 700 }}>{fmt(lead.overbid_amount)}</div>
                  </div>
                  {lead.gross_surplus_cents != null && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>GROSS SURPLUS</div>
                      <div style={{ fontSize: "1.1em", color: "#e5e7eb", fontWeight: 700 }}>{fmt(lead.gross_surplus_cents / 100)}</div>
                    </div>
                  )}
                  {/* C1: Net Owner Equity only when math_verified or audit_grade A/B */}
                  {lead.net_owner_equity_cents != null && ((lead as any).math_verified === true || (lead as any).audit_grade === "A" || (lead as any).audit_grade === "B") && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>NET OWNER EQUITY</div>
                      <div style={{ fontSize: "1.1em", color: "#22c55e", fontWeight: 700 }}>{fmt(lead.net_owner_equity_cents / 100)}</div>
                    </div>
                  )}
                  {/* C1: Potential Surplus Recovery Opportunity only when math_verified or audit_grade A/B */}
                  {lead.estimated_surplus != null && lead.estimated_surplus > 0 && ((lead as any).math_verified === true || (lead as any).audit_grade === "A" || (lead as any).audit_grade === "B") && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>POTENTIAL SURPLUS RECOVERY OPPORTUNITY</div>
                      <div style={{ fontSize: "1.1em", color: "#22c55e", fontWeight: 700 }}>{fmt(lead.estimated_surplus)}</div>
                    </div>
                  )}
                  {/* C1: estimated_surplus for MAX FEE only when pool_source !== UNVERIFIED */}
                  {lead.estimated_surplus != null && lead.estimated_surplus > 0 && lead.pool_source !== "UNVERIFIED" && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>MAX FEE CAP (10%)</div>
                      <div style={{ fontSize: "1.1em", color: "#94a3b8", fontWeight: 700 }}>{fmt(lead.estimated_surplus * 0.1)}</div>
                    </div>
                  )}
                  <div>
                    <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>VERIFICATION</div>
                    <div style={{ fontSize: "0.82em", color: tierColor, fontWeight: 700 }}>{verTier?.replace(/_/g, " ") || "UNVERIFIED"}</div>
                  </div>
                  {(lead as any).verification_confidence != null && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>CONFIDENCE</div>
                      <div style={{ fontSize: "0.82em", color: "#e5e7eb", fontWeight: 700 }}>{Math.round((lead as any).verification_confidence * 100)}%</div>
                    </div>
                  )}
                </div>
              </div>

              {/* Data gaps */}
              {lead.grade_reasons && lead.grade_reasons.length > 0 && (
                <div style={{ background: "#1c0a0022", border: "1px solid #78350f44", borderRadius: 8, padding: "12px 16px" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#f59e0b", marginBottom: 10 }}>DATA GAPS — ACTION REQUIRED</div>
                  <ul style={{ margin: 0, padding: "0 0 0 14px", listStyle: "disc" }}>
                    {lead.grade_reasons.map((r, i) => (
                      <li key={i} style={{ fontSize: "0.78em", color: "#fbbf24", marginBottom: 4, lineHeight: 1.4 }}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}

            </div>{/* end left column */}

            {/* ── RIGHT COLUMN — Action Panel ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

              {/* Unlock / Already Unlocked */}
              <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px" }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>INTELLIGENCE ACCESS</div>

                {(lead.unlocked_by_me || !!unlocked) ? (
                  <div style={{ background: "#14532d22", border: "1px solid #22c55e44", borderRadius: 6, padding: "10px 14px", marginBottom: 12, fontSize: "0.78em", color: "#4ade80", fontWeight: 700, letterSpacing: "0.06em" }}>
                    ✓ UNLOCKED
                  </div>
                ) : (
                  <>
                    {isRestricted ? (
                      <button
                        style={{ width: "100%", background: "#78350f22", border: "1px solid #f59e0b88", color: "#f59e0b", borderRadius: 6, padding: "12px 16px", fontSize: "0.8em", fontWeight: 700, letterSpacing: "0.06em", cursor: unlocking || (user ? !user.email_verified : false) ? "not-allowed" : "pointer", fontFamily: "inherit", marginBottom: 8, opacity: unlocking || (user ? !user.email_verified : false) ? 0.5 : 1 }}
                        disabled={unlocking || (user ? !user.email_verified : false)}
                        onClick={async () => {
                          if (!assetId || !user) { navigate("/login"); return; }
                          if (!user.is_admin && !user.bar_number) { setError("Attorney bar number required for restricted access."); return; }
                          const confirmed = window.confirm("ATTORNEY ACCESS ONLY\n\nC.R.S. § 38-38-111 and § 38-13-1304 restrictions apply. Consult counsel before proceeding.\n\nDo you confirm you are a licensed Colorado attorney and accept these terms?");
                          if (!confirmed) return;
                          setUnlocking(true); setError("");
                          try { const res = await unlockRestrictedLead(assetId, true); setUnlocked(res); }
                          catch (err) { handleUnlockError(err); }
                          finally { setUnlocking(false); }
                        }}
                      >
                        {unlocking ? "VERIFYING..." : "ATTORNEY ACCESS (1 CREDIT)"}
                      </button>
                    ) : (
                      <button
                        style={{ width: "100%", background: "#14532d", border: "1px solid #22c55e", color: "#4ade80", borderRadius: 6, padding: "12px 16px", fontSize: "0.8em", fontWeight: 700, letterSpacing: "0.06em", cursor: unlocking || (user ? !user.email_verified : false) ? "not-allowed" : "pointer", fontFamily: "inherit", marginBottom: 8, opacity: unlocking || (user ? !user.email_verified : false) ? 0.5 : 1 }}
                        disabled={unlocking || (user ? !user.email_verified : false)}
                        onClick={handleUnlock}
                      >
                        {unlocking ? "DECRYPTING..." : "UNLOCK FULL INTEL (1 CREDIT)"}
                      </button>
                    )}
                    <div style={{ fontSize: "0.68em", color: "#4b5563", lineHeight: 1.4 }}>
                      Owner name · full address · recorder link · court-ready dossier
                    </div>
                  </>
                )}

                {error && (
                  <div style={{ marginTop: 10, fontSize: "0.75em", color: "#ef4444", background: "#7f1d1d22", border: "1px solid #ef444444", borderRadius: 4, padding: "6px 10px" }}>{error}</div>
                )}

                {/* Email verification prompt */}
                {(showVerifyPrompt || (user && !user.email_verified)) && (
                  <div style={{ marginTop: 12, background: "#0c4a6e22", border: "1px solid #0284c744", borderRadius: 6, padding: "10px 12px" }}>
                    <div style={{ fontSize: "0.72em", color: "#38bdf8", fontWeight: 700, marginBottom: 8 }}>VERIFY EMAIL TO UNLOCK</div>
                    <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                      <input
                        type="text"
                        placeholder="Verification code"
                        value={verifyCode}
                        onChange={(e) => setVerifyCode(e.target.value)}
                        style={{ flex: 1, background: "#0d1117", border: "1px solid #374151", borderRadius: 4, color: "#e5e7eb", padding: "4px 8px", fontFamily: "inherit", fontSize: "0.85em" }}
                      />
                      <button
                        disabled={!verifyCode || verifySending}
                        onClick={async () => {
                          setVerifySending(true); setVerifyMsg("");
                          try { await verifyEmail(verifyCode); setVerifyMsg("Verified!"); window.location.reload(); }
                          catch { setVerifyMsg("Invalid code."); }
                          finally { setVerifySending(false); }
                        }}
                        style={{ background: "#1e3a5f", border: "1px solid #3b82f6", color: "#93c5fd", borderRadius: 4, padding: "4px 10px", fontFamily: "inherit", fontSize: "0.78em", cursor: "pointer", fontWeight: 700 }}
                      >VERIFY</button>
                    </div>
                    <button
                      disabled={verifySending}
                      onClick={async () => {
                        setVerifySending(true); setVerifyMsg("");
                        try {
                          const res = await sendVerification();
                          if (res.dev_code) { setVerifyCode(res.dev_code); setVerifyMsg(`Code: ${res.dev_code} (pre-filled)`); }
                          else setVerifyMsg("Verification email sent!");
                        } catch { setVerifyMsg("Failed to send."); }
                        finally { setVerifySending(false); }
                      }}
                      style={{ background: "none", border: "1px solid #374151", color: "#64748b", borderRadius: 4, padding: "3px 8px", fontFamily: "inherit", fontSize: "0.72em", cursor: "pointer" }}
                    >RESEND CODE</button>
                    {verifyMsg && <div style={{ marginTop: 6, fontSize: "0.72em", color: "#94a3b8" }}>{verifyMsg}</div>}
                  </div>
                )}
              </div>

              {/* Case dossier + court filing — visible after unlock */}
              {unlocked && (
                <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>CASE DOCUMENTS</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <button
                      style={{ background: "#0d1117", border: "1px solid #374151", color: "#e5e7eb", borderRadius: 6, padding: "9px 14px", fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}
                      onClick={() => downloadSecure(`/api/dossier/${lead.asset_id}`, `dossier_${lead.asset_id}.txt`)}
                    >
                      CASE DOSSIER ↓
                    </button>
                    {(() => {
                      const hasEvidence = evidenceDocs.length > 0 || (unlocked?.source_doc_count ?? 0) > 0;
                      return hasEvidence ? (
                        <button
                          style={{ background: "#0d1117", border: "1px solid #374151", color: "#e5e7eb", borderRadius: 6, padding: "9px 14px", fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}
                          onClick={() => downloadSecure(`/api/case-packet/${lead.asset_id}`, `case_packet_${lead.asset_id}.html`)}
                        >
                          CASE PACKET (HTML) ↓
                        </button>
                      ) : (
                        <button disabled style={{ background: "#0d1117", border: "1px solid #1f2937", color: "#4b5563", borderRadius: 6, padding: "9px 14px", fontSize: "0.78em", letterSpacing: "0.06em", cursor: "not-allowed", fontFamily: "inherit", textAlign: "left", opacity: 0.4 }}>
                          CASE PACKET — NO DOCS ON FILE
                        </button>
                      );
                    })()}
                    <button
                      style={{ background: filingLoading ? "#1f2937" : "#1c0a0022", border: "1px solid #f59e0b66", color: filingLoading ? "#6b7280" : "#f59e0b", borderRadius: 6, padding: "9px 14px", fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em", cursor: filingLoading ? "not-allowed" : "pointer", fontFamily: "inherit", textAlign: "left", opacity: filingLoading ? 0.6 : 1 }}
                      title="Court Filing Packet — 3 credits · Motion + Notice + Affidavit + Certificate + Exhibits"
                      disabled={filingLoading}
                      onClick={async () => {
                        setFilingLoading(true);
                        try {
                          await downloadSecure(`/api/lead/${lead.asset_id}/court-filing`, `court_filing_${lead.asset_id}.zip`);
                        } catch (err) {
                          toast(err instanceof ApiError ? err.message : "Court filing failed", "error");
                        } finally {
                          setFilingLoading(false);
                        }
                      }}
                    >
                      {filingLoading ? "GENERATING..." : "COURT FILING PACKET (3 CR) ↓"}
                    </button>
                    {(user?.bar_number || user?.is_admin) && (
                      <button
                        disabled={lead.ready_to_file === false}
                        title={lead.ready_to_file === false ? (lead.grade_reasons?.join("; ") || "Complete required fields first") : "Generate Rule 7.3 attorney solicitation letter"}
                        style={{ background: "#0d1117", border: "1px solid #374151", color: lead.ready_to_file === false ? "#4b5563" : "#e5e7eb", borderRadius: 6, padding: "9px 14px", fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em", cursor: lead.ready_to_file === false ? "not-allowed" : "pointer", fontFamily: "inherit", textAlign: "left", opacity: lead.ready_to_file === false ? 0.4 : 1 }}
                        onClick={async () => {
                          if (lead.ready_to_file === false) return;
                          try {
                            const blob = await generateLetter(lead.asset_id);
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url; a.download = `letter_${lead.asset_id}.docx`; a.click();
                            URL.revokeObjectURL(url);
                          } catch (err) { setError(err instanceof ApiError ? err.message : "Letter generation failed"); }
                        }}
                      >
                        RULE 7.3 LETTER ↓
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Add to pipeline */}
              {user && (
                <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>PIPELINE</div>
                  <button
                    onClick={() => setShowPipelineModal(true)}
                    style={{ width: "100%", background: "#0d1117", border: "1px solid #374151", color: "#9ca3af", borderRadius: 6, padding: "10px 14px", fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em", cursor: "pointer", fontFamily: "inherit" }}
                  >
                    + ADD TO MY PIPELINE
                  </button>
                </div>
              )}

              {/* Restriction warning (compact) */}
              {isRestricted && (
                <div style={{ background: "#7f1d1d22", border: "1px solid #ef444455", borderRadius: 8, padding: "12px 16px" }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#ef4444", marginBottom: 8, fontWeight: 700 }}>C.R.S. § 38-38-111 ACTIVE</div>
                  <div style={{ fontSize: "0.75em", color: "#fca5a5", lineHeight: 1.5 }}>
                    Restriction lifts: <strong>{lead.restriction_end_date || "—"}</strong>
                    {lead.days_until_actionable != null && (
                      <span style={{ display: "block", marginTop: 2, color: "#f87171" }}>{lead.days_until_actionable} days remaining</span>
                    )}
                  </div>
                </div>
              )}

              {/* Compact claim window */}
              {!isRestricted && lead.claim_deadline && (() => {
                const days = lead.days_to_claim;
                const passed = lead.deadline_passed;
                const urgencyColor = passed ? "#ef4444" : days != null && days <= 180 ? "#ef4444" : days != null && days <= 365 ? "#f59e0b" : "#22c55e";
                return (
                  <div style={{ background: "#111827", border: `1px solid ${urgencyColor}44`, borderRadius: 8, padding: "12px 16px" }}>
                    <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: urgencyColor, marginBottom: 6, fontWeight: 700 }}>
                      {passed ? "CLAIM WINDOW EXPIRED" : "CLAIM WINDOW"}
                    </div>
                    {!passed && days != null && (
                      <div style={{ fontSize: "1.8em", fontWeight: 700, color: urgencyColor, lineHeight: 1 }}>{days}<span style={{ fontSize: "0.45em", marginLeft: 4, color: "#4b5563" }}>DAYS</span></div>
                    )}
                    <div style={{ fontSize: "0.72em", color: "#4b5563", marginTop: 4 }}>Deadline: {lead.claim_deadline}</div>
                  </div>
                );
              })()}

            </div>{/* end right column */}

          </div>{/* end two-column grid */}

          {/* ══════════════════════════════════════════════════════════
              FULL-WIDTH SECTIONS BELOW THE GRID
              ══════════════════════════════════════════════════════════ */}

          {/* Restriction Banner */}
          {isRestricted && (
            <div style={{ background: "#7f1d1d22", border: "1px solid #ef444455", borderRadius: 8, padding: "14px 20px", marginBottom: 12 }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#ef4444", fontWeight: 700, marginBottom: 8 }}>C.R.S. § 38-38-111 RESTRICTION ACTIVE</div>
              <div style={{ fontSize: "0.82em", color: "#fca5a5", lineHeight: 1.6 }}>
                Statutory restrictions under C.R.S. § 38-38-111 and § 38-13-1304 apply. Filing window has not yet opened.
                Restriction lifts: <strong>{lead.restriction_end_date || "—"}</strong>
                {lead.days_until_actionable != null && <span> ({lead.days_until_actionable} days remaining)</span>}
              </div>
            </div>
          )}

          {/* Full Claim Window Bar */}
          {!isRestricted && lead.claim_deadline && (() => {
            const days = lead.days_to_claim;
            const passed = lead.deadline_passed;
            const urgencyColor = passed ? "#ef4444" : days != null && days <= 180 ? "#ef4444" : days != null && days <= 365 ? "#f59e0b" : "#22c55e";
            const urgencyLabel = passed ? "EXPIRED — FILE IMMEDIATELY" : days != null && days <= 180 ? "URGENT — ACT NOW" : days != null && days <= 365 ? "PLAN AHEAD" : "AMPLE TIME";
            const totalDays = 912;
            const elapsed = passed ? totalDays : Math.max(0, totalDays - (days ?? totalDays));
            const pct = Math.min(100, Math.round(elapsed / totalDays * 100));
            return (
              <div style={{ background: "#111827", border: `1px solid ${urgencyColor}44`, borderRadius: 8, padding: "14px 20px", marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                  <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151" }}>C.R.S. § 38-38-111 CLAIM WINDOW</div>
                  <div style={{ fontSize: "0.72em", fontWeight: 700, color: urgencyColor, letterSpacing: "0.06em" }}>{urgencyLabel}</div>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                  <div style={{ fontSize: "0.82em", color: "#e5e7eb" }}>Deadline: <strong>{lead.claim_deadline}</strong></div>
                  {!passed && days != null && <div style={{ fontSize: "1.1em", fontWeight: 700, color: urgencyColor }}>{days} days remaining</div>}
                </div>
                <div style={{ background: "#1f2937", borderRadius: 4, height: 6, overflow: "hidden" }}>
                  <div style={{ width: `${pct}%`, height: "100%", borderRadius: 4, background: urgencyColor, transition: "width 0.3s" }} />
                </div>
                <div style={{ fontSize: "0.68em", color: "#4b5563", marginTop: 4 }}>
                  {pct}% of 30-month window elapsed{passed && " — Funds may have escheated to the state."}
                </div>
                {passed && lead.owner_name && (
                  <div style={{ marginTop: 8 }}>
                    <a
                      href={`https://unclaimedproperty.colorado.gov/app/claim-search?lastName=${encodeURIComponent(lead.owner_name.split(" ")[0] || lead.owner_name)}`}
                      target="_blank" rel="noopener noreferrer"
                      style={{ display: "inline-block", background: "#1e3a5f", color: "#60a5fa", border: "1px solid #3b82f6", padding: "4px 12px", borderRadius: 4, fontWeight: 700, fontSize: "0.78em", textDecoration: "none", letterSpacing: "0.05em" }}
                    >
                      CHECK CO TREASURER FOR UNCLAIMED FUNDS →
                    </a>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Surplus Stream Context */}
          {lead.surplus_stream && lead.surplus_stream !== "FORECLOSURE_OVERBID" && (
            <div style={{
              background: lead.surplus_stream === "UNCLAIMED_PROPERTY" ? "#0369a122" : lead.surplus_stream === "TAX_DEED_SURPLUS" ? "#78350f22" : "#0f2f1a",
              border: `1px solid ${lead.surplus_stream === "UNCLAIMED_PROPERTY" ? "#0369a144" : lead.surplus_stream === "TAX_DEED_SURPLUS" ? "#f59e0b44" : "#22c55e44"}`,
              borderRadius: 8, padding: "14px 20px", marginBottom: 12,
            }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", fontWeight: 700, marginBottom: 8, color: lead.surplus_stream === "UNCLAIMED_PROPERTY" ? "#38bdf8" : lead.surplus_stream === "TAX_DEED_SURPLUS" ? "#f59e0b" : "#22c55e" }}>
                {lead.surplus_stream === "UNCLAIMED_PROPERTY" && "UNCLAIMED PROPERTY — C.R.S. § 38-13-1304"}
                {lead.surplus_stream === "TAX_DEED_SURPLUS" && "TAX DEED SURPLUS — C.R.S. § 39-12-111"}
                {lead.surplus_stream === "TAX_LIEN" && "TAX LIEN SURPLUS — C.R.S. § 39-11-151"}
              </div>
              <div style={{ color: "#9ca3af", lineHeight: 1.6, fontSize: "0.82em" }}>
                {lead.surplus_stream === "UNCLAIMED_PROPERTY" && (
                  <>
                    Surplus transferred to the Colorado State Treasurer. 10% attorney fee cap under HB25-1224. 30-month claim window from transfer date.
                    {lead.owner_name && (
                      <div style={{ marginTop: 8 }}>
                        <a href={`https://unclaimedproperty.colorado.gov/app/claim-search?lastName=${encodeURIComponent(lead.owner_name.split(" ")[0] || lead.owner_name)}`} target="_blank" rel="noopener noreferrer" style={{ display: "inline-block", background: "#0369a1", color: "#fff", padding: "4px 12px", borderRadius: 4, fontWeight: 700, fontSize: "0.85em", textDecoration: "none", letterSpacing: "0.05em" }}>
                          VERIFY ON CO TREASURER →
                        </a>
                      </div>
                    )}
                  </>
                )}
                {lead.surplus_stream === "TAX_DEED_SURPLUS" && "Tax deed sale overbid — no 6-month restriction applies. Immediately actionable. File promptly to secure prior owner's claim."}
                {lead.surplus_stream === "TAX_LIEN" && "Tax lien certificate sale surplus. County-specific filing requirements. Verify redemption period before filing."}
              </div>
            </div>
          )}

          {/* Owner Section — locked / unlocked */}
          {!unlocked ? (
            <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 12, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>OWNER INTELLIGENCE</div>
              {lead.unlocked_by_me ? (
                <div style={{ fontSize: "0.82em", color: autoUnlocking ? "#6b7280" : "#4ade80", fontWeight: 700 }}>
                  {autoUnlocking ? "LOADING INTEL..." : "✓ UNLOCKED — INTEL LOADING ABOVE"}
                </div>
              ) : (
                <>
                  <div style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 6, padding: "14px 16px", marginBottom: 8, textAlign: "center", fontSize: "0.82em", color: "#374151", letterSpacing: "0.1em" }}>
                    CONFIDENTIAL OWNER DATA RESTRICTED
                  </div>
                  {lead.preview_key && (
                    <button style={{ background: "none", border: "1px solid #374151", color: "#64748b", borderRadius: 4, padding: "6px 12px", fontSize: "0.75em", cursor: "pointer", fontFamily: "inherit" }} onClick={() => downloadSample(lead.preview_key!)}>
                      DOWNLOAD SAMPLE DOSSIER
                    </button>
                  )}
                </>
              )}
            </div>
          ) : (
            <div style={{ background: "#111827", border: "1px solid #22c55e44", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#22c55e", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>INTELLIGENCE DECRYPTED</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 24px", marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>OWNER NAME</div>
                  <div style={{ fontSize: "0.9em", color: "#4ade80", fontWeight: 700 }}>{unlocked.owner_name || "—"}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>PROPERTY ADDRESS</div>
                  <div style={{ fontSize: "0.9em", color: "#e5e7eb", fontWeight: 600 }}>{unlocked.property_address || "—"}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>ESTIMATED SURPLUS</div>
                  <div style={{ fontSize: "0.9em", color: "#f59e0b", fontWeight: 700 }}>{fmt(unlocked.estimated_surplus)}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>OVERBID AMOUNT</div>
                  <div style={{ fontSize: "0.9em", color: "#e5e7eb", fontWeight: 600 }}>{fmt(unlocked.overbid_amount)}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>TOTAL INDEBTEDNESS</div>
                  <div style={{ fontSize: "0.9em", color: "#e5e7eb", fontWeight: 600 }}>{unlocked.total_indebtedness ? fmt(unlocked.total_indebtedness) : "PRELIMINARY"}</div>
                </div>
                <div>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>RECORDER LINK</div>
                  <div style={{ fontSize: "0.9em" }}>
                    {unlocked.recorder_link ? <a href={unlocked.recorder_link} target="_blank" rel="noopener noreferrer" style={{ color: "#3b82f6", textDecoration: "none" }}>VIEW RECORD →</a> : "—"}
                  </div>
                </div>
              </div>

              {/* Owner Contact Intel — Skip Trace */}
              <div style={{ borderTop: "1px solid #1f2937", paddingTop: 14, marginTop: 4 }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#6ee7b7", marginBottom: 10 }}>OWNER CONTACT INTEL — SKIP TRACE</div>
                {assetId && <SkipTracePanel assetId={assetId} userTier={user?.tier ?? ""} autoRun={new URLSearchParams(location.search).get("ran") === "1"} />}</div>
            </div>
          )}

          {/* Evidence Documents */}
          {lead.registry_asset_id && (() => {
            const isAttorney = user?.is_admin || user?.role === "approved_attorney" || user?.role === "admin" || (user as any)?.attorney_status === "VERIFIED";
            return (
              <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>EVIDENCE DOCUMENTS</div>
                {/* C3: GOLD Evidence Gap Warning */}
                {lead.data_grade === 'GOLD' && (!(lead as any).evidence_docs || (lead as any).evidence_docs.length === 0) && (
                  <div style={{ margin: "12px 0", padding: "10px 14px", background: "rgba(245,158,11,0.08)", border: "1px solid #78350f", borderRadius: 6, fontSize: "0.8em", color: "#f59e0b" }}>
                    ⚠ EVIDENCE GAP — Marked GOLD but no source documents on file. Re-verification needed.
                  </div>
                )}
                {!isAttorney ? (
                  /* C6: Show document metadata even for locked/non-attorney users */
                  <div>
                    {evidencePreview.length === 0 ? (
                      <div style={{ fontSize: "0.78em", color: "#4b5563" }}>No evidence documents on file for this asset.</div>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {evidencePreview.map((doc: any, i: number) => (
                          <div key={doc.id || i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", border: "1px solid #1f2937", borderRadius: 4 }}>
                            <span style={{ opacity: 0.75, minWidth: 120, fontSize: "0.75em" }}>{doc.doc_family_label || doc.doc_family || "—"}</span>
                            <span style={{ flex: 1, opacity: 0.6, fontSize: "0.75em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.filename || doc.title || "—"}</span>
                            {doc.recording_number && <span style={{ fontSize: "0.68em", color: "#4b5563" }}>Rec# {doc.recording_number}</span>}
                            {doc.date && <span style={{ fontSize: "0.68em", color: "#4b5563" }}>{doc.date}</span>}
                            <span style={{ fontSize: "0.68em", color: "#4b5563", fontStyle: "italic" }}>(download requires unlock)</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div style={{ marginTop: 8, fontSize: "0.72em", color: "#374151" }}>Attorney verification required to download evidence documents.</div>
                  </div>
                ) : (
                  <>
                    {evidenceLoading && <div style={{ fontSize: "0.78em", color: "#4b5563" }}>Loading evidence...</div>}
                    {evidenceError && <div style={{ fontSize: "0.78em", color: "#ef4444" }}>{evidenceError}</div>}
                    {!evidenceLoading && evidenceDocs.length === 0 && !evidenceError && (
                      <div style={{ fontSize: "0.78em", color: "#4b5563" }}>No evidence documents on file for this asset.</div>
                    )}
                    {evidenceDocs.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {evidenceDocs.map((doc) => (
                          <div key={doc.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", border: "1px solid #1f2937", borderRadius: 4 }}>
                            <span style={{ opacity: 0.75, minWidth: 120, fontSize: "0.75em" }} title={doc.filename}>{doc.doc_family_label || doc.doc_family}</span>
                            <span style={{ flex: 1, opacity: 0.6, fontSize: "0.75em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.filename}</span>
                            <span style={{ opacity: 0.45, fontSize: "0.72em" }}>{doc.bytes > 0 ? `${Math.round(doc.bytes / 1024)} KB` : ""}</span>
                            <button
                              style={{ background: "#0d1117", border: "1px solid #374151", color: "#9ca3af", borderRadius: 4, padding: "3px 8px", fontSize: "0.72em", cursor: "pointer", fontFamily: "inherit" }}
                              onClick={async () => {
                                try {
                                  const blob = await downloadEvidenceDoc(doc.id);
                                  const url = URL.createObjectURL(blob);
                                  const a = document.createElement("a");
                                  a.href = url; a.download = doc.filename; a.click();
                                  URL.revokeObjectURL(url);
                                } catch (err) { setError(err instanceof ApiError ? err.message : "Download failed"); }
                              }}
                            >DOWNLOAD</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })()}

          {/* Case Timeline */}
          <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, marginBottom: 12, overflow: "hidden" }}>
            <div onClick={loadTimeline} style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: showTimeline ? "1px solid #1f2937" : "none" }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151" }}>CASE TIMELINE</div>
              <span style={{ color: "#374151", fontSize: "0.85em" }}>{showTimeline ? "▲" : "▼"}</span>
            </div>
            {showTimeline && (
              <div style={{ padding: "14px 20px" }}>
                {timeline.length === 0 ? (
                  <div style={{ fontSize: "0.78em", color: "#4b5563" }}>No timeline events recorded.</div>
                ) : timeline.map((ev: any, i: number) => (
                  <div key={i} style={{ display: "flex", gap: 16, padding: "8px 0", borderBottom: "1px solid #1f2937" }}>
                    <span style={{ fontSize: "0.72em", color: "#4b5563", minWidth: 100 }}>{ev.ts ? new Date(ev.ts).toLocaleDateString() : "—"}</span>
                    <span style={{ fontSize: "0.78em", fontWeight: 700, minWidth: 140, color: "#22c55e" }}>{ev.event_type}</span>
                    <span style={{ fontSize: "0.78em", color: "#9ca3af" }}>{ev.notes}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Title Stack */}
          <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, marginBottom: 12, overflow: "hidden" }}>
            <div onClick={loadTitleStack} style={{ cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 20px", borderBottom: showTitleStack ? "1px solid #1f2937" : "none" }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151" }}>TITLE STACK</div>
              <span style={{ color: "#374151", fontSize: "0.85em" }}>{showTitleStack ? "▲" : "▼"}</span>
            </div>
            {showTitleStack && (
              <div style={{ padding: "14px 20px" }}>
                {!titleStack ? (
                  <div style={{ fontSize: "0.78em", color: "#4b5563" }}>No title stack data available for this asset.</div>
                ) : (
                  <>
                    <div style={{ display: "flex", gap: 20, marginBottom: 12, flexWrap: "wrap" }}>
                      <div style={{ fontSize: "0.78em" }}>Risk: <strong style={{ color: titleStack.risk_score === "LOW" ? "#22c55e" : titleStack.risk_score === "HIGH" ? "#ef4444" : "#f59e0b" }}>{titleStack.risk_score}</strong></div>
                      <div style={{ fontSize: "0.78em" }}>
                        Open liens:{" "}
                        {(lead as any).lien_search_performed === false ? (
                          <strong style={{ color: "#f59e0b" }}>UNKNOWN</strong>
                        ) : (titleStack.liens?.filter((l: any) => l.is_open).length || 0) === 0 ? (
                          <strong style={{ color: "#22c55e" }}>NONE FOUND ✓</strong>
                        ) : (
                          <strong style={{ color: "#ef4444" }}>{titleStack.liens?.filter((l: any) => l.is_open).length}</strong>
                        )}
                      </div>
                      <div style={{ fontSize: "0.78em" }}>Total open: <strong>${((titleStack.total_open_cents || 0) / 100).toLocaleString()}</strong></div>
                    </div>
                    {(titleStack.liens || []).map((lien: any, i: number) => (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "40px 1fr 1fr 80px", gap: 8, padding: "6px 0", borderBottom: "1px solid #1f2937", fontSize: "0.78em" }}>
                        <span style={{ color: "#4b5563" }}>#{lien.priority}</span>
                        <span style={{ color: "#e5e7eb" }}>{lien.lienholder_name || lien.lien_type}</span>
                        <span style={{ color: "#9ca3af" }}>${((lien.amount_cents || 0) / 100).toLocaleString()}</span>
                        <span style={{ color: lien.is_open ? "#ef4444" : "#22c55e", fontWeight: 700 }}>{lien.is_open ? "OPEN" : "SATISFIED"}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>

          {/* Surplus Math Audit */}
          {unlocked && (lead.data_grade === "GOLD" || lead.surplus_math_audit) && (
            <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>SURPLUS MATH AUDIT</div>
              {lead.surplus_math_audit ? (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
                  {lead.surplus_math_audit.html_overbid != null && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>HTML OVERBID</div>
                      <div style={{ fontSize: "0.9em", fontWeight: 700, color: "#e5e7eb" }}>{fmt(lead.surplus_math_audit.html_overbid / 100)}</div>
                    </div>
                  )}
                  {lead.surplus_math_audit.computed_surplus != null && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>COMPUTED SURPLUS</div>
                      <div style={{ fontSize: "0.9em", fontWeight: 700, color: "#e5e7eb" }}>{fmt(lead.surplus_math_audit.computed_surplus / 100)}</div>
                    </div>
                  )}
                  {lead.surplus_math_audit.voucher_overbid != null && (
                    <div>
                      <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>VOUCHER AMOUNT</div>
                      <div style={{ fontSize: "0.9em", fontWeight: 700, color: "#e5e7eb" }}>{fmt(lead.surplus_math_audit.voucher_overbid / 100)}</div>
                    </div>
                  )}
                  <div>
                    <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 2 }}>MATH MATCH</div>
                    <div style={{ fontSize: "0.9em", fontWeight: 700, color: lead.surplus_math_audit.match_html_math === 1 ? "#22c55e" : lead.surplus_math_audit.match_html_math === 0 ? "#ef4444" : "#94a3b8" }}>
                      {lead.surplus_math_audit.match_html_math === 1 ? "CONFIRMED" : lead.surplus_math_audit.match_html_math === 0 ? "MISMATCH" : "PENDING"}
                    </div>
                  </div>
                </div>
              ) : (
                <div style={{ fontSize: "0.78em", color: "#4b5563" }}>Math audit pending for this GOLD asset.</div>
              )}
              {lead.equity_resolution_notes && (
                <div style={{ marginTop: 14, borderTop: "1px solid #1f2937", paddingTop: 12 }}>
                  <div style={{ fontSize: "0.58em", letterSpacing: "0.1em", color: "#374151", marginBottom: 4 }}>PROVENANCE CITATION</div>
                  <div style={{ fontSize: "0.78em", color: "#9ca3af", whiteSpace: "pre-wrap" }}>{lead.equity_resolution_notes}</div>
                </div>
              )}
            </div>
          )}

          {/* Junior Liens */}
          {unlocked && lead.junior_liens && lead.junior_liens.length > 0 && (
            <div style={{ background: "#111827", border: "1px solid #1f2937", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#374151", marginBottom: 14, borderBottom: "1px solid #1f2937", paddingBottom: 8 }}>JUNIOR LIENS & ENCUMBRANCES</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {lead.junior_liens.map((lien, i) => {
                  const amt = lien.amount_cents > 0 ? "$" + (lien.amount_cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "Amount unknown";
                  const isOpen = lien.is_open === 1;
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: "0.8em", padding: "6px 0", borderBottom: "1px solid #1f2937" }}>
                      <span style={{ minWidth: 80, fontWeight: 700, color: isOpen ? "#ef4444" : "#6b7280" }}>{lien.lien_type}</span>
                      <span style={{ flex: 1, color: "#9ca3af" }}>{lien.lienholder_name || "Lienholder unknown"}</span>
                      <span style={{ fontWeight: 600, color: isOpen ? "#f59e0b" : "#6b7280" }}>{amt}</span>
                      <span style={{ fontSize: "0.78em", padding: "2px 6px", borderRadius: 3, background: isOpen ? "rgba(239,68,68,0.15)" : "rgba(107,114,128,0.2)", color: isOpen ? "#fca5a5" : "#9ca3af" }}>
                        {isOpen ? "OPEN" : "RELEASED"}
                      </span>
                      {lien.priority != null && <span style={{ fontSize: "0.72em", color: "#4b5563" }}>P{lien.priority}</span>}
                    </div>
                  );
                })}
              </div>
              <div style={{ marginTop: 8, fontSize: "0.68em", color: "#4b5563" }}>Open liens reduce net owner equity. Verify with county records before filing.</div>
            </div>
          )}

          {/* Admin Audit Trail */}
          {user?.is_admin && assetId && (
            <div style={{ background: "#111827", border: "1px solid #1e3a2e", borderRadius: 8, padding: "16px 20px", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: showAudit ? 16 : 0 }}>
                <div style={{ fontSize: "0.62em", letterSpacing: "0.12em", color: "#22c55e", fontWeight: 700 }}>ADMIN — CASE AUDIT TRAIL</div>
                <button
                  style={{ background: "none", border: "1px solid #374151", color: "#64748b", borderRadius: 4, padding: "3px 10px", fontSize: "0.72em", cursor: "pointer", fontFamily: "inherit" }}
                  onClick={async () => {
                    if (!showAudit && !auditTrail) {
                      setAuditLoading(true);
                      try { const data = await getLeadAudit(assetId!); setAuditTrail(data); }
                      catch (e) { console.error("Audit load failed", e); }
                      finally { setAuditLoading(false); }
                    }
                    setShowAudit((v) => !v);
                  }}
                >{showAudit ? "HIDE" : "SHOW AUDIT"}</button>
                {auditLoading && <span style={{ fontSize: "0.72em", color: "#4b5563" }}>Loading...</span>}
              </div>

              {showAudit && auditTrail && (
                <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                  <div>
                    <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>RAW DB RECORD</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.78em" }}>
                      {Object.entries(auditTrail.lead).filter(([k]) => !k.startsWith("_")).map(([k, v]) => (
                        <div key={k} style={{ display: "flex", gap: 6 }}>
                          <span style={{ color: "#374151", minWidth: 160, flexShrink: 0 }}>{k}:</span>
                          <span style={{ color: v == null ? "#4b5563" : "#e5e7eb", wordBreak: "break-all" }}>{v == null ? "null" : String(v)}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: 8, fontSize: "0.75em" }}>
                      <span style={{ color: "#374151" }}>Computed status: </span>
                      <span style={{ color: "#f59e0b", fontWeight: 700 }}>{String(auditTrail.lead._computed_status || "—")}</span>
                      <span style={{ color: "#374151", marginLeft: 16 }}>Canonical ID: </span>
                      <span style={{ color: "#94a3b8" }}>{String(auditTrail.lead._asset_id_canonical || "—")}</span>
                    </div>
                  </div>

                  {auditTrail.math_audit && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>SURPLUS MATH AUDIT</div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.78em" }}>
                        {Object.entries(auditTrail.math_audit).map(([k, v]) => (
                          <div key={k} style={{ display: "flex", gap: 6 }}>
                            <span style={{ color: "#374151", minWidth: 160, flexShrink: 0 }}>{k}:</span>
                            <span style={{ color: v == null ? "#4b5563" : "#e5e7eb" }}>{v == null ? "null" : String(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {auditTrail.equity_resolution && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>EQUITY RESOLUTION</div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.78em" }}>
                        {Object.entries(auditTrail.equity_resolution).map(([k, v]) => (
                          <div key={k} style={{ display: "flex", gap: 6 }}>
                            <span style={{ color: "#374151", minWidth: 160, flexShrink: 0 }}>{k}:</span>
                            <span style={{ color: v == null ? "#4b5563" : "#e5e7eb" }}>{v == null ? "null" : String(v)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {auditTrail.evidence_docs.length > 0 && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>EVIDENCE DOCUMENTS ({auditTrail.evidence_docs.length})</div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {auditTrail.evidence_docs.map((d) => (
                          <div key={d.id} style={{ display: "flex", gap: 12, fontSize: "0.78em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                            <span style={{ color: "#374151", minWidth: 80 }}>{d.doc_family || "—"}</span>
                            <span style={{ flex: 1, color: "#9ca3af" }}>{d.filename}</span>
                            <span style={{ color: "#4b5563" }}>{d.bytes ? `${Math.round(d.bytes / 1024)} KB` : ""}</span>
                            <span style={{ color: "#4b5563" }}>{d.retrieved_ts ? new Date(d.retrieved_ts * 1000).toLocaleDateString() : ""}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {auditTrail.field_evidence.length > 0 && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>FIELD EVIDENCE ({auditTrail.field_evidence.length} extractions)</div>
                      {auditTrail.field_evidence.map((fe, i) => (
                        <div key={i} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 4, fontSize: "0.75em", padding: "6px 0", borderBottom: "1px solid #1f2937", marginBottom: 4 }}>
                          {Object.entries(fe).map(([k, v]) => (
                            <div key={k} style={{ display: "flex", gap: 4 }}>
                              <span style={{ color: "#374151", minWidth: 120, flexShrink: 0 }}>{k}:</span>
                              <span style={{ color: v == null ? "#4b5563" : "#e5e7eb", wordBreak: "break-all" }}>{v == null ? "null" : String(v)}</span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}

                  {auditTrail.audit_entries.length > 0 && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>AUDIT LOG ({auditTrail.audit_entries.length} entries)</div>
                      {auditTrail.audit_entries.map((e) => (
                        <div key={e.id} style={{ display: "flex", gap: 12, fontSize: "0.75em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                          <span style={{ color: "#374151", whiteSpace: "nowrap" }}>{e.created_at?.slice(0, 16).replace("T", " ")}</span>
                          <span style={{ color: "#9ca3af", minWidth: 140 }}>{e.user_email || "system"}</span>
                          <span style={{ color: "#22c55e" }}>{e.action}</span>
                          {e.ip && <span style={{ color: "#374151" }}>{e.ip}</span>}
                        </div>
                      ))}
                    </div>
                  )}

                  {auditTrail.unlock_history.length > 0 && (
                    <div>
                      <div style={{ fontSize: "0.62em", letterSpacing: "0.1em", color: "#374151", marginBottom: 8 }}>UNLOCK HISTORY ({auditTrail.unlock_history.length} unlocks)</div>
                      {auditTrail.unlock_history.map((u, i) => (
                        <div key={i} style={{ display: "flex", gap: 12, fontSize: "0.75em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                          <span style={{ color: "#374151" }}>{String(u["unlocked_at"] || "—")}</span>
                          <span style={{ color: "#9ca3af" }}>{String(u["user_email"] || u["user_id"] || "—")}</span>
                          <span style={{ color: "#4b5563" }}>{String(u["tier_at_unlock"] || "—")}</span>
                          <span style={{ color: "#22c55e" }}>{String(u["credits_spent"] || 0)} credits</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Footer Legal Notice */}
          <div style={{ marginTop: 32, padding: "16px 20px", borderTop: "1px solid #1f2937", fontSize: "0.68em", color: "#374151", lineHeight: 1.7 }}>
            <div style={{ fontWeight: 700, color: "#4b5563", marginBottom: 6, letterSpacing: "0.08em" }}>LEGAL NOTICE</div>
            <p style={{ margin: "0 0 6px" }}>VeriFuse Technologies LLC provides access to publicly available foreclosure sale data compiled from county public records, including verified surplus amounts, owner contact intelligence (via Skip Trace), and court-ready document packages. VeriFuse Technologies LLC is a data intelligence platform — attorneys perform all legal actions. This data does not constitute legal advice.</p>
            <p style={{ margin: 0 }}>C.R.S. § 38-38-111 and § 38-13-1304 restrictions apply. Statutory fee cap of 10% under HB25-1224 (eff. June 4, 2025). Consult counsel before filing.</p>
          </div>

          </>
        )}

      </div>

      {/* Pipeline Modal */}
      {showPipelineModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200 }}>
          <div style={{ background: "#111827", padding: "28px 32px", borderRadius: 10, minWidth: 300, border: "1px solid #1f2937" }}>
            <div style={{ fontSize: "0.75em", letterSpacing: "0.12em", color: "#374151", marginBottom: 16 }}>ADD TO PIPELINE</div>
            {["LEADS", "CONTACTED", "RETAINER_SIGNED", "FILED", "FUNDS_RELEASED"].map((stage) => (
              <button key={stage} onClick={() => addToPipeline(stage)} style={{ display: "block", width: "100%", marginBottom: 8, padding: "10px 16px", background: "#0d1117", border: "1px solid #1f2937", color: "#e5e7eb", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: "0.8em", textAlign: "left", letterSpacing: "0.06em" }}>
                {stage.replace(/_/g, " ")}
              </button>
            ))}
            <button onClick={() => setShowPipelineModal(false)} style={{ display: "block", width: "100%", marginTop: 4, padding: "10px 16px", background: "none", border: "1px solid #1f2937", color: "#4b5563", borderRadius: 6, cursor: "pointer", fontFamily: "inherit", fontSize: "0.78em" }}>Cancel</button>
          </div>
        </div>
      )}

    </div>
  );
}
