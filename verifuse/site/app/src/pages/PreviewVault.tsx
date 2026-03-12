import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPreviewLeads, getStats, type Stats } from "../lib/api";

// ── Static demo data: sample attorney workspace pipeline ─────────────
const DEMO_CASES = [
  {
    stage: "INVESTIGATING",
    county: "Arapahoe",
    surplus: "$54,200",
    grade: "GOLD",
    deadline: "10 days",
    color: "#f59e0b",
    detail: "Case ID: ARA-0148-2023 · Sale date confirmed · Lien search complete",
  },
  {
    stage: "CONTACTED",
    county: "Jefferson",
    surplus: "$88,400",
    grade: "GOLD",
    deadline: "42 days",
    color: "#10b981",
    detail: "Owner reached 3/10 · Retainer sent via DocuSign · Awaiting signature",
  },
  {
    stage: "FILED",
    county: "Denver",
    surplus: "$127,000",
    grade: "GOLD",
    deadline: "Filed 3/1",
    color: "#22c55e",
    detail: "Motion for Surplus Release filed · Hearing set 3/28/2026 · $127K at stake",
  },
  {
    stage: "WON",
    county: "Adams",
    surplus: "$63,500",
    grade: "GOLD",
    deadline: "Closed 2/15",
    color: "#a78bfa",
    detail: "Disbursement received · Attorney fee: $6,350 (10%) · Client share: $57,150",
  },
];

const FEATURE_ROWS = [
  { feature: "GOLD/SILVER/BRONZE graded leads", investigator: true, partner: true, enterprise: true },
  { feature: "All 18+ Colorado counties", investigator: true, partner: true, enterprise: true },
  { feature: "Lead unlock (1 credit)", investigator: true, partner: true, enterprise: true },
  { feature: "Court Filing Packet (3 credits/case)", investigator: false, partner: true, enterprise: true },
  { feature: "Skip Trace add-on (1 credit)", investigator: false, partner: true, enterprise: true },
  { feature: "Bulk CSV export", investigator: false, partner: true, enterprise: true },
  { feature: "Premium Dossier (5 credits)", investigator: false, partner: true, enterprise: true },
  { feature: "Full REST API access", investigator: false, partner: false, enterprise: true },
  { feature: "White-label dossier exports", investigator: false, partner: false, enterprise: true },
  { feature: "10 Skip Traces/month included", investigator: false, partner: false, enterprise: true },
  { feature: "County coverage reports", investigator: false, partner: false, enterprise: true },
];

// ── Grade badge ────────────────────────────────────────────────────────
function GradeBadge({ grade }: { grade: string }) {
  const colors: Record<string, string> = { GOLD: "#f59e0b", SILVER: "#94a3b8", BRONZE: "#92400e" };
  return (
    <span style={{
      background: colors[grade] || "#374151", color: grade === "GOLD" ? "#0a0f1a" : "#fff",
      padding: "2px 8px", borderRadius: 4, fontSize: "0.7em", fontWeight: 700,
      fontFamily: "monospace", letterSpacing: "0.06em",
    }}>{grade}</span>
  );
}

// ── Blurred PII cell ────────────────────────────────────────────────────
function Locked({ width = 120 }: { width?: number }) {
  return (
    <span style={{
      display: "inline-block", width,
      background: "linear-gradient(90deg, #1f2937 0%, #374151 50%, #1f2937 100%)",
      borderRadius: 3, height: 14, verticalAlign: "middle",
      animation: "shimmer 1.8s ease-in-out infinite",
    }} />
  );
}

// ── Kanban column ──────────────────────────────────────────────────────
function KanbanCard({ c }: { c: typeof DEMO_CASES[0] }) {
  return (
    <div style={{
      background: "#0d1117", border: `1px solid ${c.color}33`,
      borderRadius: 8, padding: "14px 16px", marginBottom: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontFamily: "monospace", fontSize: "0.75em", color: c.color, fontWeight: 700 }}>{c.county}</span>
        <GradeBadge grade={c.grade} />
      </div>
      <div style={{ fontSize: "1.2em", fontWeight: 700, fontFamily: "monospace", color: "#e5e7eb", marginBottom: 4 }}>
        {c.surplus}
      </div>
      <div style={{ fontSize: "0.7em", color: "#6b7280", lineHeight: 1.4 }}>{c.detail}</div>
      <div style={{ marginTop: 8, fontSize: "0.68em", fontFamily: "monospace", color: c.deadline.includes("days") ? "#f59e0b" : "#4b5563" }}>
        ⏱ {c.deadline}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────
export default function PreviewVault() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [previewLeads, setPreviewLeads] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    document.title = "Preview Vault | VeriFuse Intelligence";
    Promise.all([
      getStats().catch(() => null),
      getPreviewLeads({ limit: 20 }).catch(() => ({ leads: [], count: 0 })),
    ]).then(([s, p]) => {
      setStats(s);
      setPreviewLeads((p as any)?.leads ?? []);
      setLoading(false);
    });
  }, []);

  const goldLeads = previewLeads.filter((l) => l.data_grade === "GOLD").slice(0, 12);
  const silverLeads = previewLeads.filter((l) => l.data_grade === "SILVER").slice(0, 4);
  const displayLeads = [...goldLeads, ...silverLeads];

  return (
    <div style={{ minHeight: "100vh", background: "#0a0f1a", color: "#e5e7eb", fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}>

      {/* ── Global shimmer animation ── */}
      <style>{`
        @keyframes shimmer {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.8; }
        }
        @keyframes pulse-ring {
          0% { box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
          70% { box-shadow: 0 0 0 10px rgba(34,197,94,0); }
          100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
        }
        .pulse-btn { animation: pulse-ring 2s ease-out infinite; }
        .preview-table th { font-size: 0.7em; color: #4b5563; letter-spacing: 0.1em; padding: 8px 12px; border-bottom: 1px solid #1f2937; text-align: left; }
        .preview-table td { padding: 10px 12px; border-bottom: 1px solid #111827; font-size: 0.8em; }
        .preview-table tr:hover td { background: rgba(34,197,94,0.03); }
        @media (max-width: 768px) {
          .vault-grid { grid-template-columns: 1fr !important; }
          .kanban-grid { grid-template-columns: 1fr 1fr !important; }
          .feature-grid { overflow-x: auto; }
          .stats-banner { grid-template-columns: 1fr 1fr !important; }
        }
        @media (max-width: 480px) {
          .kanban-grid { grid-template-columns: 1fr !important; }
          .stats-banner { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* ── Top Nav ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "16px 32px", borderBottom: "1px solid #1f2937",
        background: "#0a0f1a", position: "sticky", top: 0, zIndex: 100,
      }}>
        <Link to="/" style={{ textDecoration: "none", fontSize: "0.9em", fontWeight: 700, letterSpacing: "0.06em", color: "#e5e7eb" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// INTELLIGENCE</span>
        </Link>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <Link to="/pricing" style={{ color: "#94a3b8", textDecoration: "none", fontSize: "0.78em" }}>Pricing</Link>
          <Link to="/login" style={{ color: "#94a3b8", textDecoration: "none", fontSize: "0.78em" }}>Login</Link>
          <Link to="/register" className="pulse-btn" style={{
            background: "#22c55e", color: "#0a0f1a", padding: "8px 18px",
            borderRadius: 6, textDecoration: "none", fontSize: "0.78em", fontWeight: 700,
            letterSpacing: "0.06em",
          }}>
            START FREE TRIAL →
          </Link>
        </div>
      </div>

      {/* ── Hero ── */}
      <section style={{ padding: "64px 32px 48px", textAlign: "center", maxWidth: 900, margin: "0 auto" }}>
        <div style={{ fontSize: "0.68em", letterSpacing: "0.2em", color: "#22c55e", marginBottom: 16 }}>
          LIVE VAULT PREVIEW — REAL COLORADO SURPLUS DATA
        </div>
        <h1 style={{ fontSize: "2.6rem", fontWeight: 700, margin: "0 0 16px", lineHeight: 1.15 }}>
          The Attorney's Unfair Advantage<br />
          <span style={{ color: "#22c55e" }}>in Colorado Foreclosure Surplus.</span>
        </h1>
        <p style={{ color: "#94a3b8", fontSize: "0.95em", lineHeight: 1.7, maxWidth: 640, margin: "0 auto 32px" }}>
          Real-time GOLD-graded surplus leads. One-click court filing packets.
          An attorney workspace built to close cases — not just find them.
          Below is live data from our vault. Owner information is unlocked with a single credit.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <Link to="/register" style={{
            background: "#22c55e", color: "#0a0f1a", padding: "12px 28px",
            borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.88em", letterSpacing: "0.06em",
          }}>
            CLAIM YOUR FREE TRIAL
          </Link>
          <Link to="/pricing" style={{
            border: "1px solid #374151", color: "#94a3b8", padding: "12px 28px",
            borderRadius: 6, textDecoration: "none", fontSize: "0.88em",
          }}>
            View Pricing
          </Link>
        </div>
      </section>

      {/* ── Live Stats Banner ── */}
      {stats && (
        <div style={{ maxWidth: 900, margin: "0 auto 48px", padding: "0 32px" }}>
          <div className="stats-banner" style={{
            display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16,
          }}>
            {[
              { label: "Active Pipeline", value: stats.total_leads ?? stats.total_assets, color: "#e5e7eb" },
              { label: "GOLD Grade Leads", value: stats.gold_grade, color: "#f59e0b" },
              { label: "Attorney-Ready", value: stats.attorney_ready, color: "#22c55e" },
              { label: "Verified Surplus", value: `$${(stats.total_claimable_surplus / 1_000_000).toFixed(1)}M`, color: "#10b981" },
            ].map((s) => (
              <div key={s.label} style={{
                background: "#0d1117", border: "1px solid #1f2937", borderRadius: 8,
                padding: "20px 24px", textAlign: "center",
              }}>
                <div style={{ fontSize: "1.8em", fontWeight: 700, color: s.color, fontFamily: "monospace" }}>{s.value}</div>
                <div style={{ fontSize: "0.7em", color: "#4b5563", letterSpacing: "0.1em", marginTop: 4 }}>{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Live Vault Table ── */}
      <section style={{ maxWidth: 1100, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 6 }}>LIVE SURPLUS VAULT</div>
            <h2 style={{ margin: 0, fontSize: "1.4em", fontWeight: 700 }}>Real leads. Real counties. Real money.</h2>
          </div>
          <div style={{ fontSize: "0.75em", color: "#4b5563" }}>
            {loading ? "Loading..." : `${displayLeads.length} leads shown · Owner data requires unlock`}
          </div>
        </div>

        <div style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ overflowX: "auto" }}>
            <table className="preview-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th>GRADE</th>
                  <th>COUNTY</th>
                  <th>SALE DATE</th>
                  <th>SURPLUS BAND</th>
                  <th>OWNER NAME</th>
                  <th>PROPERTY</th>
                  <th>CASE NO.</th>
                  <th>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  Array.from({ length: 8 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 8 }).map((_, j) => (
                        <td key={j}><Locked width={j === 3 ? 80 : 100} /></td>
                      ))}
                    </tr>
                  ))
                ) : displayLeads.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ textAlign: "center", color: "#4b5563", padding: 32 }}>
                      No preview leads available
                    </td>
                  </tr>
                ) : (
                  displayLeads.map((lead, i) => (
                    <tr key={i}>
                      <td><GradeBadge grade={lead.data_grade} /></td>
                      <td style={{ color: "#e5e7eb", fontWeight: 600 }}>
                        {(lead.county || "").replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())}
                      </td>
                      <td style={{ color: "#94a3b8" }}>{lead.sale_month || "—"}</td>
                      <td style={{ color: "#22c55e", fontWeight: 700 }}>
                        {lead.surplus_band || <Locked width={70} />}
                      </td>
                      <td>
                        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <Locked width={110} />
                          <span style={{ fontSize: "0.65em", color: "#374151", fontFamily: "monospace" }}>🔒 1 credit</span>
                        </span>
                      </td>
                      <td><Locked width={130} /></td>
                      <td><Locked width={90} /></td>
                      <td>
                        <Link to="/register" style={{
                          background: lead.data_grade === "GOLD" ? "#22c55e" : "transparent",
                          color: lead.data_grade === "GOLD" ? "#0a0f1a" : "#22c55e",
                          border: lead.data_grade === "GOLD" ? "none" : "1px solid #374151",
                          padding: "4px 12px", borderRadius: 4, textDecoration: "none",
                          fontSize: "0.7em", fontWeight: 700, letterSpacing: "0.04em", whiteSpace: "nowrap",
                        }}>
                          UNLOCK →
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div style={{ marginTop: 12, fontSize: "0.72em", color: "#4b5563", textAlign: "center" }}>
          Surplus band shown free · Owner name, property address, case number, and evidence documents require 1 credit to unlock
        </div>
      </section>

      {/* ── Attorney Workspace Demo ── */}
      <section style={{ maxWidth: 1100, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>ATTORNEY WORKSPACE</div>
          <h2 style={{ margin: "0 0 12px", fontSize: "1.6em" }}>Your Pipeline. Your Cases. Your ROI.</h2>
          <p style={{ color: "#94a3b8", fontSize: "0.88em", maxWidth: 560, margin: "0 auto" }}>
            Every lead you unlock goes directly into a professional case management workspace.
            Track owner contact, retainer status, filing dates, and recovered funds — all in one place.
          </p>
        </div>

        {/* ROI Banner */}
        <div style={{
          background: "linear-gradient(135deg, rgba(34,197,94,0.08) 0%, rgba(16,185,129,0.04) 100%)",
          border: "1px solid rgba(34,197,94,0.2)",
          borderRadius: 10, padding: "20px 28px", marginBottom: 24,
          display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16,
        }}>
          <div>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.1em", marginBottom: 6 }}>SAMPLE PORTFOLIO · 4 ACTIVE CASES</div>
            <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
              {[
                { label: "Cases Won", value: "1" },
                { label: "Total Recovered", value: "$63,500" },
                { label: "Attorney Fees (10%)", value: "$6,350" },
                { label: "ROI on Credits Used", value: "32×" },
              ].map((s) => (
                <div key={s.label}>
                  <div style={{ fontSize: "1.3em", fontWeight: 700, color: "#22c55e", fontFamily: "monospace" }}>{s.value}</div>
                  <div style={{ fontSize: "0.68em", color: "#6b7280" }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>
          <Link to="/register" style={{
            background: "#22c55e", color: "#0a0f1a", padding: "10px 22px",
            borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.8em",
            letterSpacing: "0.06em", whiteSpace: "nowrap",
          }}>
            BUILD YOUR PIPELINE →
          </Link>
        </div>

        {/* Kanban Columns */}
        <div className="kanban-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          {["INVESTIGATING", "CONTACTED", "FILED", "WON"].map((stage) => {
            const cases = DEMO_CASES.filter((c) => c.stage === stage);
            const color = cases[0]?.color || "#374151";
            return (
              <div key={stage}>
                <div style={{
                  fontSize: "0.68em", color, letterSpacing: "0.12em",
                  fontWeight: 700, marginBottom: 10, paddingBottom: 8,
                  borderBottom: `2px solid ${color}40`,
                }}>
                  {stage} ({cases.length})
                </div>
                {cases.map((c, i) => <KanbanCard key={i} c={c} />)}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Filing Packet Demo ── */}
      <section style={{ maxWidth: 1100, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{ display: "flex", gap: 32, flexWrap: "wrap", alignItems: "flex-start" }}>
          <div style={{ flex: "1 1 420px" }}>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>COURT FILING PACKET</div>
            <h2 style={{ margin: "0 0 16px", fontSize: "1.5em" }}>One click. Court-ready documents.</h2>
            <p style={{ color: "#94a3b8", fontSize: "0.88em", lineHeight: 1.7, marginBottom: 24 }}>
              When a lead is READY TO FILE, generate the complete court filing packet in 3 credits.
              Includes everything your firm needs — formatted for Colorado district courts.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                { doc: "Motion for Surplus Release", note: "C.R.S. § 38-38-111 compliant" },
                { doc: "Notice to Lienholders", note: "Mandatory lien holder notification" },
                { doc: "Affidavit of Representation", note: "Attorney representation on behalf of owner" },
                { doc: "Certificate of Service", note: "Proof of document service" },
                { doc: "Evidence Exhibit Package", note: "Sale records + surplus calculation" },
                { doc: "Property Record Exhibit", note: "Assessor data + ownership chain" },
              ].map((d) => (
                <div key={d.doc} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                  <span style={{ color: "#22c55e", flexShrink: 0, marginTop: 1 }}>✓</span>
                  <div>
                    <div style={{ fontSize: "0.83em", color: "#e5e7eb", fontWeight: 600 }}>{d.doc}</div>
                    <div style={{ fontSize: "0.72em", color: "#4b5563" }}>{d.note}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div style={{ flex: "1 1 340px" }}>
            <div style={{
              background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, padding: "24px",
              fontFamily: "monospace",
            }}>
              <div style={{ fontSize: "0.68em", color: "#4b5563", marginBottom: 12, letterSpacing: "0.1em" }}>
                CASE: ARA-0148-2023 · STATUS: READY TO FILE ✓
              </div>
              <div style={{ borderBottom: "1px solid #1f2937", paddingBottom: 12, marginBottom: 12 }}>
                <div style={{ fontSize: "0.72em", color: "#6b7280", marginBottom: 4 }}>VERIFIED SURPLUS</div>
                <div style={{ fontSize: "2em", fontWeight: 700, color: "#22c55e" }}>$54,200</div>
                <div style={{ fontSize: "0.7em", color: "#6b7280" }}>Source: TRUSTEE LEDGER · Verified ✓</div>
              </div>
              <div style={{ fontSize: "0.75em", color: "#94a3b8", marginBottom: 16, lineHeight: 1.6 }}>
                <div>County: <span style={{ color: "#e5e7eb" }}>Arapahoe</span></div>
                <div>Sale Date: <span style={{ color: "#e5e7eb" }}>2023-06-14</span></div>
                <div>Claim Deadline: <span style={{ color: "#f59e0b" }}>2026-03-20 (10 days)</span></div>
                <div>Max Fee (10%): <span style={{ color: "#22c55e", fontWeight: 700 }}>$5,420</span></div>
              </div>
              <button style={{
                width: "100%", background: "#22c55e", color: "#0a0f1a",
                border: "none", padding: "12px 0", borderRadius: 6,
                fontWeight: 700, fontSize: "0.82em", letterSpacing: "0.06em",
                cursor: "pointer", fontFamily: "monospace",
              }}>
                GENERATE FILING PACKET — 3 CREDITS
              </button>
              <div style={{ marginTop: 8, fontSize: "0.68em", color: "#4b5563", textAlign: "center" }}>
                ZIP download · Includes all 6 documents above
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Enterprise Plan Spotlight ── */}
      <section style={{ maxWidth: 1100, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div style={{ fontSize: "0.68em", color: "#a78bfa", letterSpacing: "0.15em", marginBottom: 8 }}>ENTERPRISE TIER</div>
          <h2 style={{ margin: "0 0 12px", fontSize: "1.6em" }}>Built for high-volume practices.</h2>
          <p style={{ color: "#94a3b8", fontSize: "0.88em", maxWidth: 520, margin: "0 auto" }}>
            200 credits/month with 90-day rollover, full REST API, white-label exports,
            and 10 included Skip Traces. The only tool your firm will need.
          </p>
        </div>

        <div style={{
          background: "linear-gradient(135deg, rgba(167,139,250,0.05) 0%, rgba(109,40,217,0.05) 100%)",
          border: "1px solid rgba(167,139,250,0.3)",
          borderRadius: 12, padding: "32px",
        }}>
          <div className="vault-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 24, marginBottom: 28 }}>
            {[
              { label: "Monthly Credits", value: "200", sub: "90-day rollover — bank up to 300" },
              { label: "Skip Traces Included", value: "10/mo", sub: "Multi-source owner location" },
              { label: "Max Monthly Fee Revenue", value: "$90K+", sub: "At 10% on max case volume" },
            ].map((s) => (
              <div key={s.label} style={{ textAlign: "center", padding: "20px", background: "rgba(167,139,250,0.05)", borderRadius: 8 }}>
                <div style={{ fontSize: "2em", fontWeight: 700, color: "#a78bfa", fontFamily: "monospace" }}>{s.value}</div>
                <div style={{ fontSize: "0.7em", color: "#4b5563", letterSpacing: "0.08em", marginTop: 4 }}>{s.label}</div>
                <div style={{ fontSize: "0.68em", color: "#6b7280", marginTop: 4 }}>{s.sub}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link to="/register?tier=sovereign" style={{
              background: "#a78bfa", color: "#0a0f1a", padding: "12px 28px",
              borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.85em",
              letterSpacing: "0.06em",
            }}>
              START ENTERPRISE — $899/MO
            </Link>
            <Link to="/pricing" style={{
              border: "1px solid #4b5563", color: "#94a3b8", padding: "12px 28px",
              borderRadius: 6, textDecoration: "none", fontSize: "0.85em",
            }}>
              Compare All Plans
            </Link>
          </div>
        </div>
      </section>

      {/* ── Feature Comparison ── */}
      <section style={{ maxWidth: 1100, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <h2 style={{ margin: "0 0 8px", fontSize: "1.4em" }}>What's included at each tier</h2>
        </div>
        <div className="feature-grid" style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ padding: "14px 20px", textAlign: "left", fontSize: "0.72em", color: "#4b5563", borderBottom: "1px solid #1f2937", width: "50%" }}>
                  FEATURE
                </th>
                {[
                  { name: "INVESTIGATOR", price: "$199/mo", color: "#22c55e" },
                  { name: "PARTNER", price: "$399/mo", color: "#22c55e" },
                  { name: "ENTERPRISE", price: "$899/mo", color: "#a78bfa" },
                ].map((t) => (
                  <th key={t.name} style={{ padding: "14px 20px", textAlign: "center", fontSize: "0.72em", color: t.color, borderBottom: "1px solid #1f2937", letterSpacing: "0.08em" }}>
                    {t.name}<br />
                    <span style={{ color: "#4b5563", fontWeight: 400 }}>{t.price}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FEATURE_ROWS.map((row) => (
                <tr key={row.feature} style={{ borderBottom: "1px solid #111827" }}>
                  <td style={{ padding: "10px 20px", fontSize: "0.82em", color: "#94a3b8" }}>{row.feature}</td>
                  {[row.investigator, row.partner, row.enterprise].map((has, i) => (
                    <td key={i} style={{ padding: "10px 20px", textAlign: "center" }}>
                      {has
                        ? <span style={{ color: "#22c55e", fontSize: "1em" }}>✓</span>
                        : <span style={{ color: "#1f2937", fontSize: "0.9em" }}>—</span>
                      }
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Founding Attorney CTA ── */}
      <section style={{ maxWidth: 900, margin: "0 auto 64px", padding: "0 32px" }}>
        <div style={{
          background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.3)",
          borderRadius: 12, padding: "36px 40px", textAlign: "center",
        }}>
          <div style={{ fontSize: "0.68em", color: "#f59e0b", letterSpacing: "0.15em", marginBottom: 12 }}>
            ★ FOUNDING ATTORNEY PROGRAM — LIMITED SPOTS
          </div>
          <h2 style={{ margin: "0 0 12px", fontSize: "1.6em" }}>Lock in current pricing. Forever.</h2>
          <p style={{ color: "#94a3b8", fontSize: "0.88em", maxWidth: 520, margin: "0 auto 24px", lineHeight: 1.7 }}>
            First 10 attorneys lock in $199/$399/$899 pricing permanently — plus 5 bonus credits on signup.
            Founding members save <strong style={{ color: "#f59e0b" }}>$1,200–$3,600/year forever</strong> vs standard pricing.
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link to="/register" style={{
              background: "#f59e0b", color: "#0a0f1a", padding: "14px 32px",
              borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.88em",
              letterSpacing: "0.06em",
            }}>
              CLAIM FOUNDING ATTORNEY STATUS →
            </Link>
          </div>
          <div style={{ marginTop: 12, fontSize: "0.72em", color: "#78350f" }}>
            After founding cohort: $299 / $599 / $1,199 per month · Founding members locked in forever
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer style={{
        borderTop: "1px solid #1f2937", padding: "24px 32px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// INTELLIGENCE</span>
        </div>
        <div style={{ display: "flex", gap: 20, fontSize: "0.75em", color: "#4b5563" }}>
          <Link to="/pricing" style={{ color: "#4b5563", textDecoration: "none" }}>Pricing</Link>
          <Link to="/login" style={{ color: "#4b5563", textDecoration: "none" }}>Login</Link>
          <Link to="/register" style={{ color: "#22c55e", textDecoration: "none" }}>Register</Link>
          <Link to="/terms" style={{ color: "#4b5563", textDecoration: "none" }}>Terms</Link>
          <Link to="/privacy" style={{ color: "#4b5563", textDecoration: "none" }}>Privacy</Link>
        </div>
        <div style={{ fontSize: "0.7em", color: "#374151" }}>
          © {new Date().getFullYear()} VeriFuse Technologies LLC · Denver, CO
        </div>
      </footer>
    </div>
  );
}
