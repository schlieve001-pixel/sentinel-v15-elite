import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPreviewLeads, getStats, type Stats } from "../lib/api";

// ── Demo pipeline data ──────────────────────────────────────────────────────
const DEMO_CASES = [
  {
    stage: "INVESTIGATING",
    county: "Arapahoe",
    surplus: "$54,200",
    grade: "GOLD",
    deadline: "10 days left",
    urgent: true,
    color: "#f59e0b",
    detail: "Case ID: ARA-0148-2023 · Sale date confirmed · Lien search complete",
  },
  {
    stage: "CONTACTED",
    county: "Jefferson",
    surplus: "$88,400",
    grade: "GOLD",
    deadline: "42 days left",
    urgent: false,
    color: "#10b981",
    detail: "Owner reached 3/10 · Retainer sent via DocuSign · Awaiting signature",
  },
  {
    stage: "FILED",
    county: "Denver",
    surplus: "$127,000",
    grade: "GOLD",
    deadline: "Hearing 3/28",
    urgent: false,
    color: "#22c55e",
    detail: "Motion for Surplus Release filed · Hearing set 3/28/2026 · $127K at stake",
  },
  {
    stage: "WON",
    county: "Adams",
    surplus: "$63,500",
    grade: "GOLD",
    deadline: "Closed 2/15",
    urgent: false,
    color: "#a78bfa",
    detail: "Disbursement received · Attorney fee: $6,350 (10%) · Client share: $57,150",
  },
];

const HOW_IT_WORKS = [
  {
    num: "01",
    title: "Signal Detection",
    body: "Scrapers monitor all Colorado county recorder offices daily. Every foreclosure sale, trustee deed, and surplus deposit is captured within 24 hours.",
    color: "#22c55e",
  },
  {
    num: "02",
    title: "Intelligence Grading",
    body: "Each lead is scored: surplus verified, statutory deadline calculated, evidence documents attached. Only GOLD-grade leads are ready to file.",
    color: "#f59e0b",
  },
  {
    num: "03",
    title: "Unlock + File",
    body: "1 credit reveals owner name, mailing address, and case number. 3 credits generates the full court filing packet — motion, notice, affidavit, exhibits.",
    color: "#a78bfa",
  },
];

const FEATURE_ROWS = [
  { feature: "GOLD/SILVER/BRONZE graded leads", investigator: true, partner: true, enterprise: true },
  { feature: "All 18+ Colorado counties", investigator: true, partner: true, enterprise: true },
  { feature: "Evidence document access", investigator: true, partner: true, enterprise: true },
  { feature: "Deadline alert emails", investigator: true, partner: true, enterprise: true },
  { feature: "Lead unlock (1 credit)", investigator: true, partner: true, enterprise: true },
  { feature: "Court Filing Packet (3 credits)", investigator: false, partner: true, enterprise: true },
  { feature: "Skip Trace add-on (1 credit)", investigator: false, partner: true, enterprise: true },
  { feature: "Bulk CSV export", investigator: false, partner: true, enterprise: true },
  { feature: "Premium Dossier (5 credits)", investigator: false, partner: true, enterprise: true },
  { feature: "Full REST API access", investigator: false, partner: false, enterprise: true },
  { feature: "White-label dossier exports", investigator: false, partner: false, enterprise: true },
  { feature: "10 Skip Traces/month included", investigator: false, partner: false, enterprise: true },
];

// ── Sub-components ──────────────────────────────────────────────────────────
function GradeBadge({ grade }: { grade: string }) {
  const colors: Record<string, string> = { GOLD: "#f59e0b", SILVER: "#94a3b8", BRONZE: "#92400e" };
  return (
    <span style={{
      background: colors[grade] || "#374151",
      color: grade === "GOLD" ? "#0a0f1a" : "#fff",
      padding: "2px 8px", borderRadius: 4, fontSize: "0.7em",
      fontWeight: 700, fontFamily: "monospace", letterSpacing: "0.06em",
    }}>{grade}</span>
  );
}

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
      <div style={{ marginTop: 8, fontSize: "0.68em", fontFamily: "monospace", color: c.urgent ? "#ef4444" : "#4b5563" }}>
        ⏱ {c.deadline}
      </div>
    </div>
  );
}

function RoiCalculator() {
  const [cases, setCases] = useState(5);
  const [surplus, setSurplus] = useState(50000);
  const monthly = Math.round(cases * surplus * 0.10);
  const roi = monthly > 0 ? Math.round(monthly / 199) : 0;
  return (
    <div style={{
      background: "#0d1117", border: "1px solid #374151", borderRadius: 10,
      padding: "28px 32px", maxWidth: 580, margin: "0 auto",
    }}>
      <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.12em", marginBottom: 16 }}>
        CALCULATE YOUR ROI
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82em", marginBottom: 6, color: "#94a3b8" }}>
            <span>Cases per month</span>
            <span style={{ color: "#22c55e", fontWeight: 700, fontFamily: "monospace" }}>{cases}</span>
          </div>
          <input type="range" min={1} max={20} value={cases}
            onChange={(e) => setCases(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#22c55e" }} />
        </div>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.82em", marginBottom: 6, color: "#94a3b8" }}>
            <span>Average surplus per case</span>
            <span style={{ color: "#22c55e", fontWeight: 700, fontFamily: "monospace" }}>${surplus.toLocaleString()}</span>
          </div>
          <input type="range" min={5000} max={500000} step={5000} value={surplus}
            onChange={(e) => setSurplus(Number(e.target.value))}
            style={{ width: "100%", accentColor: "#22c55e" }} />
        </div>
      </div>
      <div style={{ marginTop: 24, padding: "20px", background: "#111827", borderRadius: 8 }}>
        <div style={{ fontSize: "0.72em", color: "#4b5563", letterSpacing: "0.1em", marginBottom: 6 }}>ESTIMATED MONTHLY REVENUE (10% CAP)</div>
        <div style={{ fontSize: "2.2em", fontWeight: 700, color: "#22c55e", fontFamily: "monospace" }}>
          ${monthly.toLocaleString()}<span style={{ fontSize: "0.45em", color: "#4b5563" }}>/mo</span>
        </div>
        <div style={{ fontSize: "0.8em", color: "#6b7280", marginTop: 4 }}>
          {cases} cases × ${surplus.toLocaleString()} avg surplus × 10% (HB25-1224)
        </div>
        {roi > 0 && (
          <div style={{ marginTop: 12, padding: "8px 12px", background: "rgba(34,197,94,0.08)", borderRadius: 6, border: "1px solid rgba(34,197,94,0.2)" }}>
            <span style={{ fontSize: "0.85em", color: "#22c55e", fontWeight: 700, fontFamily: "monospace" }}>
              VeriFuse Investigator ($199/mo) = {roi}× ROI
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────
export default function Landing() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [previewLeads, setPreviewLeads] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [foundingSlots, setFoundingSlots] = useState<{ slots_claimed: number; slots_total: number; is_open: boolean } | null>(null);

  useEffect(() => {
    document.title = "VeriFuse Intelligence — Colorado Foreclosure Surplus Platform";
    Promise.all([
      getStats().catch(() => null),
      getPreviewLeads({ limit: 20 }).catch(() => ({ leads: [], count: 0 })),
      fetch("/api/founding/status").then((r) => r.json()).catch(() => null),
    ]).then(([s, p, f]) => {
      setStats(s);
      setPreviewLeads((p as any)?.leads ?? []);
      setFoundingSlots(f);
      setLoading(false);
    });
  }, []);

  const goldLeads = previewLeads.filter((l) => l.data_grade === "GOLD").slice(0, 10);
  const silverLeads = previewLeads.filter((l) => l.data_grade === "SILVER").slice(0, 4);
  const displayLeads = [...goldLeads, ...silverLeads];

  const slotsLeft = foundingSlots ? foundingSlots.slots_total - foundingSlots.slots_claimed : null;

  return (
    <div style={{
      minHeight: "100vh", background: "#0a0f1a", color: "#e5e7eb",
      fontFamily: "'JetBrains Mono', 'Fira Mono', monospace",
    }}>

      <style>{`
        @keyframes shimmer {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.8; }
        }
        @keyframes pulse-ring {
          0% { box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
          70% { box-shadow: 0 0 0 12px rgba(34,197,94,0); }
          100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
        }
        @keyframes ticker {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .pulse-cta { animation: pulse-ring 2.2s ease-out infinite; }
        .preview-table th { font-size: 0.68em; color: #4b5563; letter-spacing: 0.1em; padding: 10px 14px; border-bottom: 1px solid #1f2937; text-align: left; }
        .preview-table td { padding: 11px 14px; border-bottom: 1px solid #111827; font-size: 0.8em; }
        .preview-table tr:hover td { background: rgba(34,197,94,0.03); }
        .landing-section-inner { max-width: 1100px; margin: 0 auto; padding: 0 32px; }
        @media (max-width: 768px) {
          .kanban-grid { grid-template-columns: 1fr 1fr !important; }
          .stats-grid { grid-template-columns: 1fr 1fr !important; }
          .vault-3col { grid-template-columns: 1fr !important; }
          .hero-h1 { font-size: 2rem !important; }
          .landing-section-inner { padding: 0 16px; }
          .filing-2col { flex-direction: column !important; }
        }
        @media (max-width: 480px) {
          .kanban-grid { grid-template-columns: 1fr !important; }
          .stats-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* ── Top Nav ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "16px 32px", borderBottom: "1px solid #1f2937",
        background: "#0a0f1a", position: "sticky", top: 0, zIndex: 100,
      }}>
        <span style={{ fontSize: "0.9em", fontWeight: 700, letterSpacing: "0.06em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// INTELLIGENCE</span>
        </span>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <Link to="/preview" style={{ color: "#94a3b8", textDecoration: "none", fontSize: "0.78em" }}>Live Vault</Link>
          <Link to="/pricing" style={{ color: "#94a3b8", textDecoration: "none", fontSize: "0.78em" }}>Pricing</Link>
          <Link to="/login" style={{ color: "#94a3b8", textDecoration: "none", fontSize: "0.78em" }}>Login</Link>
          <Link to="/register" className="pulse-cta" style={{
            background: "#22c55e", color: "#0a0f1a", padding: "8px 18px",
            borderRadius: 6, textDecoration: "none", fontSize: "0.78em", fontWeight: 700,
            letterSpacing: "0.06em",
          }}>
            START FREE TRIAL →
          </Link>
        </div>
      </div>

      {/* ── Urgency Ticker ── */}
      {stats && stats.attorney_ready > 0 && (
        <div style={{
          background: "rgba(239,68,68,0.08)", borderBottom: "1px solid rgba(239,68,68,0.2)",
          overflow: "hidden", padding: "8px 0",
        }}>
          <div style={{
            display: "inline-flex", gap: "60px", whiteSpace: "nowrap",
            animation: "ticker 30s linear infinite",
            fontSize: "0.7em", color: "#fca5a5", fontFamily: "monospace",
          }}>
            {Array.from({ length: 4 }).map((_, i) => (
              <span key={i}>
                🔴 {stats.attorney_ready} attorney-ready leads active &nbsp;·&nbsp;
                ⏳ Claim windows close on a rolling 30-month basis &nbsp;·&nbsp;
                💰 ${(stats.total_claimable_surplus / 1_000_000).toFixed(1)}M+ verified surplus in the vault &nbsp;·&nbsp;
                ⚠️ Missed deadlines are unrecoverable — file first
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Hero ── */}
      <section style={{ padding: "72px 32px 56px", textAlign: "center", maxWidth: 960, margin: "0 auto" }}>
        <div style={{ fontSize: "0.68em", letterSpacing: "0.2em", color: "#22c55e", marginBottom: 16 }}>
          COLORADO FORECLOSURE SURPLUS INTELLIGENCE PLATFORM
        </div>
        <h1 className="hero-h1" style={{ fontSize: "2.8rem", fontWeight: 700, margin: "0 0 20px", lineHeight: 1.12 }}>
          Every month, Colorado attorneys miss<br />
          <span style={{ color: "#22c55e" }}>millions in unclaimed surplus.</span>
          <br />
          <span style={{ fontSize: "0.65em", color: "#94a3b8" }}>VeriFuse finds them, grades them, and hands you the filing packet.</span>
        </h1>
        <p style={{ color: "#6b7280", fontSize: "0.92em", lineHeight: 1.7, maxWidth: 620, margin: "0 auto 36px" }}>
          Real-time scraping of all 18+ Colorado counties. Every GOLD lead has a verified surplus amount,
          confirmed sale date, and a 30-month statutory window. Unlock owner data with 1 credit.
          Generate the complete court filing packet with 3.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap", marginBottom: 16 }}>
          <Link to="/register" className="pulse-cta" style={{
            background: "#22c55e", color: "#0a0f1a", padding: "14px 32px",
            borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.9em",
            letterSpacing: "0.06em",
          }}>
            CLAIM FOUNDING ATTORNEY STATUS →
          </Link>
          <Link to="/preview" style={{
            border: "1px solid #374151", color: "#94a3b8", padding: "14px 28px",
            borderRadius: 6, textDecoration: "none", fontSize: "0.88em",
          }}>
            View Live Vault
          </Link>
        </div>
        {slotsLeft !== null && slotsLeft > 0 && (
          <div style={{ fontSize: "0.75em", color: "#f59e0b", fontFamily: "monospace" }}>
            ★ {slotsLeft} of {foundingSlots?.slots_total} founding spots remaining — lock in $199/$399/$899 forever
          </div>
        )}
      </section>

      {/* ── Live Stats ── */}
      {stats && (
        <div className="landing-section-inner" style={{ marginBottom: 56 }}>
          <div className="stats-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
            {[
              { label: "Active Pipeline", value: (stats.total_leads ?? stats.total_assets)?.toLocaleString(), color: "#e5e7eb", sub: "Monitored cases" },
              { label: "GOLD Grade", value: stats.gold_grade?.toLocaleString(), color: "#f59e0b", sub: "Verified leads" },
              { label: "Attorney-Ready", value: stats.attorney_ready?.toLocaleString(), color: "#22c55e", sub: "File now" },
              {
                label: "Verified Surplus",
                value: `$${((stats as any).verified_surplus ? ((stats as any).verified_surplus / 1_000_000).toFixed(1) : (stats.total_claimable_surplus / 1_000_000).toFixed(1))}M`,
                color: "#10b981",
                sub: "GOLD+SILVER only"
              },
            ].map((s) => (
              <div key={s.label} style={{
                background: "#0d1117", border: "1px solid #1f2937", borderRadius: 8,
                padding: "22px 20px", textAlign: "center",
              }}>
                <div style={{ fontSize: "2em", fontWeight: 700, color: s.color, fontFamily: "monospace", lineHeight: 1 }}>{s.value}</div>
                <div style={{ fontSize: "0.72em", color: "#e5e7eb", letterSpacing: "0.08em", marginTop: 6 }}>{s.label}</div>
                <div style={{ fontSize: "0.62em", color: "#4b5563", marginTop: 3 }}>{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Live Vault Table ── */}
      <section style={{ marginBottom: 72 }}>
        <div className="landing-section-inner">
          <div style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
            <div>
              <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 6 }}>LIVE SURPLUS VAULT</div>
              <h2 style={{ margin: 0, fontSize: "1.4em", fontWeight: 700 }}>Real leads. Real counties. Real money.</h2>
            </div>
            <div style={{ fontSize: "0.75em", color: "#4b5563" }}>
              {loading ? "Loading vault..." : `${displayLeads.length} leads · owner data locked until unlock`}
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
                          <td key={j}><Locked width={j === 3 ? 70 : 100} /></td>
                        ))}
                      </tr>
                    ))
                  ) : displayLeads.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", color: "#4b5563", padding: 40 }}>
                        Vault loading — check back shortly
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
                            <Locked width={100} />
                            <span style={{ fontSize: "0.65em", color: "#374151" }}>🔒</span>
                          </span>
                        </td>
                        <td><Locked width={130} /></td>
                        <td><Locked width={90} /></td>
                        <td>
                          <Link to="/register" style={{
                            background: lead.data_grade === "GOLD" ? "#22c55e" : "transparent",
                            color: lead.data_grade === "GOLD" ? "#0a0f1a" : "#22c55e",
                            border: lead.data_grade === "GOLD" ? "none" : "1px solid #374151",
                            padding: "5px 12px", borderRadius: 4, textDecoration: "none",
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
          <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <div style={{ fontSize: "0.72em", color: "#4b5563" }}>
              Surplus band shown free · Full lead requires 1 credit to unlock
            </div>
            <Link to="/preview" style={{ fontSize: "0.72em", color: "#22c55e", textDecoration: "none" }}>
              View full vault preview →
            </Link>
          </div>
        </div>
      </section>

      {/* ── Attorney Workspace ── */}
      <section style={{ marginBottom: 72, background: "rgba(13,17,23,0.6)", borderTop: "1px solid #1f2937", borderBottom: "1px solid #1f2937", padding: "56px 0" }}>
        <div className="landing-section-inner">
          <div style={{ textAlign: "center", marginBottom: 36 }}>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>ATTORNEY WORKSPACE</div>
            <h2 style={{ margin: "0 0 12px", fontSize: "1.6em" }}>Your Pipeline. Your Cases. Your ROI.</h2>
            <p style={{ color: "#94a3b8", fontSize: "0.88em", maxWidth: 560, margin: "0 auto", lineHeight: 1.7 }}>
              Every lead you unlock drops into a professional case management pipeline.
              Track owner contact, retainer status, filing dates, and recovered funds.
            </p>
          </div>

          {/* ROI snapshot */}
          <div style={{
            background: "linear-gradient(135deg, rgba(34,197,94,0.08), rgba(16,185,129,0.04))",
            border: "1px solid rgba(34,197,94,0.2)", borderRadius: 10,
            padding: "20px 28px", marginBottom: 24,
            display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16,
          }}>
            <div>
              <div style={{ fontSize: "0.65em", color: "#22c55e", letterSpacing: "0.1em", marginBottom: 10 }}>DEMO PORTFOLIO · 4 ACTIVE CASES</div>
              <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
                {[
                  { label: "Cases Won", value: "1" },
                  { label: "Total Recovered", value: "$63,500" },
                  { label: "Attorney Fee (10%)", value: "$6,350" },
                  { label: "ROI on Credits", value: "32×" },
                ].map((s) => (
                  <div key={s.label}>
                    <div style={{ fontSize: "1.4em", fontWeight: 700, color: "#22c55e", fontFamily: "monospace" }}>{s.value}</div>
                    <div style={{ fontSize: "0.65em", color: "#6b7280" }}>{s.label}</div>
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

          {/* Kanban */}
          <div className="kanban-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
            {["INVESTIGATING", "CONTACTED", "FILED", "WON"].map((stage) => {
              const cases = DEMO_CASES.filter((c) => c.stage === stage);
              const color = cases[0]?.color || "#374151";
              return (
                <div key={stage}>
                  <div style={{
                    fontSize: "0.65em", color, letterSpacing: "0.12em",
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
        </div>
      </section>

      {/* ── How It Works ── */}
      <section style={{ marginBottom: 72 }}>
        <div className="landing-section-inner">
          <div style={{ textAlign: "center", marginBottom: 40 }}>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>THE SYSTEM</div>
            <h2 style={{ margin: 0, fontSize: "1.6em" }}>How VeriFuse Works</h2>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24 }}>
            {HOW_IT_WORKS.map((step) => (
              <div key={step.num} style={{
                background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, padding: "28px 24px",
              }}>
                <div style={{ fontSize: "2em", fontWeight: 700, color: step.color, fontFamily: "monospace", marginBottom: 12, lineHeight: 1 }}>
                  {step.num}
                </div>
                <h3 style={{ margin: "0 0 10px", fontSize: "1em", fontWeight: 700 }}>{step.title}</h3>
                <p style={{ margin: 0, fontSize: "0.83em", color: "#6b7280", lineHeight: 1.6 }}>{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Court Filing Packet ── */}
      <section style={{ marginBottom: 72, background: "rgba(13,17,23,0.6)", borderTop: "1px solid #1f2937", borderBottom: "1px solid #1f2937", padding: "56px 0" }}>
        <div className="landing-section-inner">
          <div className="filing-2col" style={{ display: "flex", gap: 40, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 400px" }}>
              <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 10 }}>COURT FILING PACKET</div>
              <h2 style={{ margin: "0 0 16px", fontSize: "1.5em" }}>One click. Court-ready documents.</h2>
              <p style={{ color: "#94a3b8", fontSize: "0.88em", lineHeight: 1.7, marginBottom: 28 }}>
                When a lead reaches READY TO FILE status, generate the complete filing packet
                for 3 credits. Every document formatted for Colorado district courts.
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {[
                  { doc: "Motion for Surplus Release", note: "C.R.S. § 38-38-111 compliant" },
                  { doc: "Notice to Lienholders", note: "Mandatory lien holder notification" },
                  { doc: "Affidavit of Representation", note: "Attorney representation on behalf of owner" },
                  { doc: "Certificate of Service", note: "Proof of document service" },
                  { doc: "Evidence Exhibit Package", note: "Sale records + surplus calculation hash" },
                  { doc: "Property Record Exhibit", note: "Assessor data + full ownership chain" },
                ].map((d) => (
                  <div key={d.doc} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                    <span style={{ color: "#22c55e", flexShrink: 0, marginTop: 2 }}>✓</span>
                    <div>
                      <div style={{ fontSize: "0.85em", fontWeight: 600, color: "#e5e7eb" }}>{d.doc}</div>
                      <div style={{ fontSize: "0.72em", color: "#4b5563" }}>{d.note}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ flex: "1 1 300px" }}>
              <div style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, padding: "24px" }}>
                <div style={{ fontSize: "0.65em", color: "#4b5563", letterSpacing: "0.1em", marginBottom: 14 }}>
                  CASE: ARA-0148-2023 · STATUS: READY TO FILE ✓
                </div>
                <div style={{ borderBottom: "1px solid #1f2937", paddingBottom: 14, marginBottom: 14 }}>
                  <div style={{ fontSize: "0.7em", color: "#6b7280", marginBottom: 4 }}>VERIFIED SURPLUS</div>
                  <div style={{ fontSize: "2.2em", fontWeight: 700, color: "#22c55e", fontFamily: "monospace" }}>$54,200</div>
                  <div style={{ fontSize: "0.68em", color: "#6b7280" }}>Source: TRUSTEE LEDGER · Verified ✓</div>
                </div>
                <div style={{ fontSize: "0.76em", color: "#94a3b8", marginBottom: 18, lineHeight: 1.8 }}>
                  <div>County: <span style={{ color: "#e5e7eb" }}>Arapahoe</span></div>
                  <div>Sale Date: <span style={{ color: "#e5e7eb" }}>2023-06-14</span></div>
                  <div>Claim Deadline: <span style={{ color: "#ef4444", fontWeight: 700 }}>2026-03-20 — 10 DAYS</span></div>
                  <div>Max Fee (10%): <span style={{ color: "#22c55e", fontWeight: 700 }}>$5,420</span></div>
                </div>
                <Link to="/register" style={{
                  display: "block", width: "100%", background: "#22c55e", color: "#0a0f1a",
                  border: "none", padding: "12px 0", borderRadius: 6, textAlign: "center",
                  fontWeight: 700, fontSize: "0.82em", letterSpacing: "0.06em",
                  textDecoration: "none",
                }}>
                  GENERATE FILING PACKET — 3 CREDITS
                </Link>
                <div style={{ marginTop: 8, fontSize: "0.65em", color: "#4b5563", textAlign: "center" }}>
                  ZIP download · All 6 documents · Calculation hash included
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── ROI Calculator ── */}
      <section style={{ marginBottom: 72 }}>
        <div className="landing-section-inner">
          <div style={{ textAlign: "center", marginBottom: 36 }}>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>YOUR NUMBERS</div>
            <h2 style={{ margin: "0 0 10px", fontSize: "1.6em" }}>Calculate Your ROI</h2>
            <p style={{ color: "#6b7280", fontSize: "0.88em", maxWidth: 480, margin: "0 auto" }}>
              HB25-1224 caps finder fees at 10% of surplus. Move the sliders.
            </p>
          </div>
          <RoiCalculator />
        </div>
      </section>

      {/* ── Pricing ── */}
      <section style={{ marginBottom: 72, background: "rgba(13,17,23,0.6)", borderTop: "1px solid #1f2937", borderBottom: "1px solid #1f2937", padding: "56px 0" }}>
        <div className="landing-section-inner">
          <div style={{ textAlign: "center", marginBottom: 36 }}>
            <div style={{ fontSize: "0.68em", color: "#22c55e", letterSpacing: "0.15em", marginBottom: 8 }}>INTELLIGENCE PLANS</div>
            <h2 style={{ margin: "0 0 10px", fontSize: "1.6em" }}>Pay for results, not software</h2>
            <p style={{ color: "#6b7280", fontSize: "0.88em", maxWidth: 440, margin: "0 auto" }}>
              One credit = one fully unlocked case with all evidence documents. Credits roll over.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 20, marginBottom: 28 }}>
            {[
              {
                name: "INVESTIGATOR", price: "$199", credits: 30, highlight: false,
                color: "#22c55e",
                features: ["30 credits/month · 30-day rollover", "All 18+ counties", "GOLD/SILVER/BRONZE grades", "Evidence documents", "Deadline alerts", "Unlimited devices"],
              },
              {
                name: "PARTNER", price: "$399", credits: 75, highlight: true,
                color: "#22c55e",
                features: ["75 credits/month · 60-day rollover", "All 4 surplus streams", "Court Filing Packets (3 cr)", "Skip Trace add-on (1 cr)", "Bulk CSV export", "Unlimited devices"],
              },
              {
                name: "ENTERPRISE", price: "$899", credits: 200, highlight: false,
                color: "#a78bfa",
                features: ["200 credits/month · 90-day rollover", "All streams + estate cases", "Full REST API", "White-label dossiers", "10 Skip Traces/mo included", "Unlimited devices"],
              },
            ].map((tier) => (
              <div key={tier.name} style={{
                background: tier.highlight ? "rgba(34,197,94,0.04)" : "#0d1117",
                border: `1px solid ${tier.highlight ? "#22c55e" : "#1f2937"}`,
                borderRadius: 10, padding: "28px 24px",
                position: "relative", display: "flex", flexDirection: "column",
              }}>
                {tier.highlight && (
                  <div style={{
                    position: "absolute", top: -12, left: "50%", transform: "translateX(-50%)",
                    background: "#22c55e", color: "#0a0f1a", fontSize: "0.65em",
                    fontWeight: 700, padding: "3px 14px", borderRadius: 20,
                    letterSpacing: "0.1em", whiteSpace: "nowrap",
                  }}>MOST POPULAR</div>
                )}
                <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", color: "#4b5563", marginBottom: 8 }}>{tier.name}</div>
                <div style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: "2.4em", fontWeight: 700 }}>{tier.price}</span>
                  <span style={{ opacity: 0.4, fontSize: "0.85em" }}>/mo</span>
                </div>
                <div style={{ color: tier.color, fontSize: "0.78em", marginBottom: "1.25rem" }}>{tier.credits} credits/month</div>
                <ul style={{ margin: "0 0 1.5rem", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
                  {tier.features.map((f) => (
                    <li key={f} style={{ fontSize: "0.82em", display: "flex", gap: 8, alignItems: "flex-start", color: "#d1d5db" }}>
                      <span style={{ color: tier.color, flexShrink: 0, marginTop: 1 }}>✓</span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link to="/register" style={{
                  display: "block", textAlign: "center", padding: "10px 0", borderRadius: 6,
                  background: tier.highlight ? "#22c55e" : "transparent",
                  color: tier.highlight ? "#0a0f1a" : tier.color,
                  border: tier.highlight ? "none" : `1px solid ${tier.color}`,
                  textDecoration: "none", fontSize: "0.82em", fontWeight: 700, letterSpacing: "0.06em",
                }}>
                  GET STARTED
                </Link>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", justifyContent: "center", gap: "2rem", flexWrap: "wrap", color: "#4b5563", fontSize: "0.78em" }}>
            <span>No contracts · cancel anytime</span>
            <span>Annual billing saves 10%</span>
            <span>🔒 Stripe-secured</span>
            <Link to="/pricing" style={{ color: "#22c55e", textDecoration: "none" }}>Full pricing details →</Link>
          </div>
        </div>
      </section>

      {/* ── Feature Comparison ── */}
      <section style={{ marginBottom: 72 }}>
        <div className="landing-section-inner">
          <div style={{ textAlign: "center", marginBottom: 28 }}>
            <h2 style={{ margin: "0 0 8px", fontSize: "1.4em" }}>Everything included at each tier</h2>
          </div>
          <div style={{ background: "#0d1117", border: "1px solid #1f2937", borderRadius: 10, overflow: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ padding: "14px 20px", textAlign: "left", fontSize: "0.7em", color: "#4b5563", borderBottom: "1px solid #1f2937", width: "50%" }}>FEATURE</th>
                  {[{ n: "INVESTIGATOR", c: "#22c55e", p: "$199" }, { n: "PARTNER", c: "#22c55e", p: "$399" }, { n: "ENTERPRISE", c: "#a78bfa", p: "$899" }].map((t) => (
                    <th key={t.n} style={{ padding: "14px 16px", textAlign: "center", fontSize: "0.7em", color: t.c, borderBottom: "1px solid #1f2937", letterSpacing: "0.08em" }}>
                      {t.n}<br /><span style={{ color: "#4b5563", fontWeight: 400 }}>{t.p}/mo</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURE_ROWS.map((row) => (
                  <tr key={row.feature} style={{ borderBottom: "1px solid #111827" }}>
                    <td style={{ padding: "10px 20px", fontSize: "0.82em", color: "#94a3b8" }}>{row.feature}</td>
                    {[row.investigator, row.partner, row.enterprise].map((has, i) => (
                      <td key={i} style={{ padding: "10px 16px", textAlign: "center" }}>
                        {has ? <span style={{ color: "#22c55e" }}>✓</span> : <span style={{ color: "#1f2937" }}>—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── Founding Attorney CTA ── */}
      <section style={{ marginBottom: 72 }}>
        <div className="landing-section-inner">
          <div style={{
            background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.3)",
            borderRadius: 12, padding: "44px 40px", textAlign: "center",
          }}>
            <div style={{ fontSize: "0.68em", color: "#f59e0b", letterSpacing: "0.15em", marginBottom: 14 }}>
              ★ FOUNDING ATTORNEY PROGRAM
            </div>
            <h2 style={{ margin: "0 0 14px", fontSize: "1.7em" }}>Lock in current pricing. Forever.</h2>
            <p style={{ color: "#94a3b8", fontSize: "0.9em", maxWidth: 520, margin: "0 auto 28px", lineHeight: 1.7 }}>
              First 10 attorneys lock in $199/$399/$899 pricing permanently + receive <strong style={{ color: "#f59e0b" }}>5 bonus credits</strong> on signup.
              After founding slots fill, prices increase 30%.
            </p>
            {slotsLeft !== null && (
              <div style={{
                display: "inline-block", background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.3)",
                borderRadius: 6, padding: "6px 16px", marginBottom: 20, fontSize: "0.82em", color: "#f59e0b", fontFamily: "monospace",
              }}>
                {slotsLeft > 0
                  ? `${slotsLeft} of ${foundingSlots?.slots_total} founding spots remaining`
                  : "Founding spots filled — regular pricing now in effect"}
              </div>
            )}
            <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
              <Link to="/register" className="pulse-cta" style={{
                background: "#f59e0b", color: "#0a0f1a", padding: "14px 36px",
                borderRadius: 6, textDecoration: "none", fontWeight: 700, fontSize: "0.9em",
                letterSpacing: "0.06em",
              }}>
                CLAIM FOUNDING ATTORNEY STATUS →
              </Link>
            </div>
            <div style={{ marginTop: 14, fontSize: "0.72em", color: "#78350f" }}>
              After first 10 attorneys: $259 / $519 / $1,169 per month · Current members locked in forever
            </div>
          </div>
        </div>
      </section>

      {/* ── Legal Disclaimer ── */}
      <section style={{ borderTop: "1px solid #1f2937", padding: "32px", maxWidth: 900, margin: "0 auto" }}>
        <p style={{ fontSize: "0.72em", color: "#374151", lineHeight: 1.7, textAlign: "center" }}>
          <strong style={{ color: "#4b5563" }}>LEGAL NOTICE:</strong> VeriFuse is a data intelligence platform providing publicly available county record data for research purposes.
          VeriFuse does not provide legal advice, does not act as a finder under C.R.S. § 38-13-1301, and claims no interest in surplus funds.
          Users are responsible for compliance with C.R.S. § 38-38-111(5) (6-month contact restriction), the 30-month claim window under C.R.S. § 38-38-111,
          and the 10% maximum finder fee cap under HB25-1224 (eff. June 4, 2025).{" "}
          <Link to="/terms" style={{ color: "#22c55e" }}>Terms</Link> ·{" "}
          <Link to="/privacy" style={{ color: "#22c55e" }}>Privacy</Link>
        </p>
      </section>

      {/* ── Footer ── */}
      <footer style={{
        borderTop: "1px solid #1f2937", padding: "24px 32px",
        display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12,
      }}>
        <div style={{ fontSize: "0.78em", fontWeight: 700, letterSpacing: "0.06em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// INTELLIGENCE</span>
        </div>
        <div style={{ display: "flex", gap: 20, fontSize: "0.75em", color: "#4b5563" }}>
          <Link to="/preview" style={{ color: "#4b5563", textDecoration: "none" }}>Live Vault</Link>
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
