import { useEffect, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getPreSaleLeads, type PreSaleLead, type CountyBreakdown } from "../lib/api";
import { useAuth } from "../lib/auth";

function formatCurrency(n: number | null | undefined): string {
  if (!n || n <= 0) return "—";
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function getDataTier(lead: PreSaleLead): string {
  if (lead.data_tier) return lead.data_tier;
  const score = lead.data_completeness ?? 0;
  if (score >= 70) return "ENRICHED";
  if (score >= 40) return "PARTIAL";
  return "MONITORING";
}

function getCompletenessScore(lead: PreSaleLead): number {
  if (typeof lead.data_completeness === "number") return lead.data_completeness;
  // Fallback: derive from available fields
  let score = 0;
  if (lead.owner_name) score += 25;
  if (lead.property_address) score += 20;
  if (lead.scheduled_sale_date || lead.sale_date) score += 25;
  if (lead.surplus_amount && lead.surplus_amount > 0) score += 20;
  if (lead.opening_bid > 0) score += 10;
  return score;
}

function CompletenessRing({ score, size = 40 }: { score: number; size?: number }) {
  const color = score >= 70 ? "#22c55e" : score >= 40 ? "#f59e0b" : "#4b5563";
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = (score / 100) * circumference;

  return (
    <div style={{
      position: "relative", width: size, height: size,
      display: "flex", alignItems: "center", justifyContent: "center",
      flexShrink: 0,
    }}>
      <svg width={size} height={size} style={{ position: "absolute", top: 0, left: 0, transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#1f2937" strokeWidth={3} />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={3}
          strokeDasharray={`${filled} ${circumference - filled}`}
          strokeLinecap="round"
        />
      </svg>
      <span style={{ fontSize: size * 0.22, fontWeight: 700, color, fontFamily: "monospace", lineHeight: 1 }}>
        {score}
      </span>
    </div>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const cfg =
    tier === "ENRICHED"   ? { bg: "rgba(34,197,94,0.12)", color: "#22c55e", border: "rgba(34,197,94,0.3)" } :
    tier === "PARTIAL"    ? { bg: "rgba(245,158,11,0.12)", color: "#f59e0b", border: "rgba(245,158,11,0.3)" } :
                            { bg: "rgba(107,114,128,0.12)", color: "#6b7280", border: "rgba(107,114,128,0.3)" };
  return (
    <span style={{
      fontSize: "0.68em", padding: "2px 7px", borderRadius: 4,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
      fontWeight: 700, letterSpacing: "0.06em", fontFamily: "monospace",
    }}>
      {tier}
    </span>
  );
}

function CompletenessBar({ score }: { score: number }) {
  const color = score >= 70 ? "#22c55e" : score >= 40 ? "#f59e0b" : "#4b5563";
  return (
    <div style={{ marginTop: 4, height: 4, borderRadius: 2, background: "#1f2937", width: "100%" }}>
      <div style={{
        height: "100%", borderRadius: 2,
        width: `${score}%`,
        background: color,
        transition: "width 0.3s ease",
      }} />
    </div>
  );
}

function LeadHorizontalCard({ lead }: { lead: PreSaleLead }) {
  const score = getCompletenessScore(lead);
  const tier = getDataTier(lead);
  const hasOwner = lead.owner_name && lead.owner_name.trim() !== "";
  const hasAddress = lead.property_address && lead.property_address.trim() !== "";
  const saleDate = lead.scheduled_sale_date || lead.sale_date;
  const actionDate = lead.expected_action_date ?? (saleDate ? (() => {
    try {
      const d = new Date(saleDate);
      d.setMonth(d.getMonth() + 6);
      return d.toISOString().slice(0, 10);
    } catch { return null; }
  })() : null);
  const hasSurplus = lead.surplus_amount && lead.surplus_amount > 0;

  const borderColor = tier === "ENRICHED" ? "#166534"
    : tier === "PARTIAL" ? "#92400e"
    : "#374151";

  return (
    <Link to={`/lead/${lead.id}`} style={{ textDecoration: "none", color: "inherit" }}>
      <div style={{
        display: "flex", gap: 16, alignItems: "flex-start",
        background: "#111827",
        border: `1px solid ${borderColor}`,
        borderRadius: 8, padding: "14px 18px",
        marginBottom: 6, cursor: "pointer",
        transition: "border-color 0.15s, background 0.15s",
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = "#1a2332"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = "#111827"; }}
      >
        {/* Left: completeness ring */}
        <CompletenessRing score={score} size={52} />

        {/* Center: lead info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 700, fontSize: "0.95em", color: "#e5e7eb" }}>
              {lead.case_number ?? "—"}
            </span>
            <span style={{
              fontSize: "0.72em", padding: "2px 7px", borderRadius: 4,
              background: "#1e3a5f", color: "#93c5fd", letterSpacing: "0.06em",
            }}>
              {titleCase(lead.county)}
            </span>
            <TierBadge tier={tier} />
          </div>

          <div style={{ fontSize: "0.82em", color: hasOwner ? "#d1d5db" : "#4b5563", marginBottom: 2 }}>
            {hasOwner ? `Owner: ${lead.owner_name}` : "Owner: Pending Enrichment"}
          </div>
          <div style={{ fontSize: "0.8em", color: hasAddress ? "#9ca3af" : "#4b5563", marginBottom: 6 }}>
            {hasAddress ? `Addr: ${lead.property_address}` : "Addr: Not Yet Retrieved"}
          </div>

          {/* Progress bar + label */}
          <CompletenessBar score={score} />
          <div style={{ fontSize: "0.7em", color: "#6b7280", marginTop: 3, letterSpacing: "0.05em" }}>
            {score}% COMPLETE
          </div>
        </div>

        {/* Right: value + timeline */}
        <div style={{ flexShrink: 0, textAlign: "right", minWidth: 140 }}>
          <div style={{
            fontSize: "1.1em", fontWeight: 700,
            color: hasSurplus ? "#22c55e" : "#4b5563",
            marginBottom: 2,
          }}>
            {hasSurplus ? formatCurrency(lead.surplus_amount) + " est." : "—"}
          </div>
          <div style={{ fontSize: "0.78em", color: saleDate ? "#f59e0b" : "#4b5563", marginBottom: 2 }}>
            Sale: {saleDate ?? "Unknown"}
          </div>
          <div style={{ fontSize: "0.78em", color: actionDate ? "#6366f1" : "#4b5563" }}>
            Action: {actionDate ?? "—"}
          </div>
          {lead.opening_bid > 0 && (
            <div style={{ fontSize: "0.75em", color: "#6b7280", marginTop: 2 }}>
              Opening: {formatCurrency(lead.opening_bid)}
            </div>
          )}
        </div>

        {/* View arrow */}
        <div style={{
          flexShrink: 0, display: "flex", alignItems: "center",
          color: "#374151", fontSize: "1.1em", paddingLeft: 4,
        }}>
          →
        </div>
      </div>
    </Link>
  );
}

interface TierGroup {
  tier: string;
  leads: PreSaleLead[];
  label: string;
  description: string;
}

export default function PreSale() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [leads, setLeads] = useState<PreSaleLead[]>([]);
  const [breakdown, setBreakdown] = useState<CountyBreakdown[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [countyFilter, setCountyFilter] = useState<string>("");
  const [dataTierFilter, setDataTierFilter] = useState<string>("");
  const [sortBy, setSortBy] = useState<"completeness" | "surplus" | "sale_date">("completeness");
  const [completeOnly, setCompleteOnly] = useState(false);
  const [monitoringExpanded, setMonitoringExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const PAGE = 200;

  const load = useCallback((ac?: AbortController) => {
    setLoading(true);
    setError(null);
    getPreSaleLeads(
      {
        county: countyFilter || undefined,
        data_tier: dataTierFilter || undefined,
        has_data: completeOnly || undefined,
        limit: PAGE,
        offset,
      },
      ac?.signal
    )
      .then(res => {
        setLeads(res.leads);
        setTotal(res.total);
        setBreakdown(res.county_breakdown);
        setLoading(false);
      })
      .catch(e => {
        if (e?.name === "AbortError") return;
        setError(e?.message ?? "Load failed");
        setLoading(false);
      });
  }, [countyFilter, dataTierFilter, completeOnly, offset]);

  useEffect(() => {
    if (!user) {
      navigate("/login");
      return;
    }
    const ac = new AbortController();
    load(ac);
    return () => ac.abort();
  }, [user, navigate, load]);

  // Aggregate tier counts from breakdown
  const totalPipeline = breakdown.reduce((s, c) => s + (c.pipeline_surplus ?? 0), 0);
  const totalWithSaleDate = breakdown.reduce((s, c) => s + (c.with_sale_date ?? 0), 0);
  const totalFullyEnriched = breakdown.reduce((s, c) => s + (c.fully_enriched ?? 0), 0);

  // Count tiers from loaded leads
  const enrichedCount = leads.filter(l => getDataTier(l) === "ENRICHED").length;
  const partialCount = leads.filter(l => getDataTier(l) === "PARTIAL").length;
  const monitoringCount = leads.filter(l => getDataTier(l) === "MONITORING").length;

  // Sort leads
  function sortLeads(arr: PreSaleLead[]): PreSaleLead[] {
    return [...arr].sort((a, b) => {
      if (sortBy === "completeness") return getCompletenessScore(b) - getCompletenessScore(a);
      if (sortBy === "surplus") return (b.surplus_amount ?? 0) - (a.surplus_amount ?? 0);
      if (sortBy === "sale_date") {
        const da = a.scheduled_sale_date || a.sale_date || "9999";
        const db = b.scheduled_sale_date || b.sale_date || "9999";
        return da.localeCompare(db);
      }
      return 0;
    });
  }

  // Group by tier when no tier filter
  const enrichedLeads = sortLeads(leads.filter(l => getDataTier(l) === "ENRICHED"));
  const partialLeads  = sortLeads(leads.filter(l => getDataTier(l) === "PARTIAL"));
  const monitoringLeads = sortLeads(leads.filter(l => getDataTier(l) === "MONITORING"));
  const filteredSingleTier = dataTierFilter ? sortLeads(leads) : null;

  const tierGroups: TierGroup[] = [
    {
      tier: "ENRICHED",
      leads: enrichedLeads,
      label: "ENRICHED LEADS",
      description: "Full owner, address, sale date + surplus estimate — ready for intake tracking",
    },
    {
      tier: "PARTIAL",
      leads: partialLeads,
      label: "PARTIAL DATA",
      description: "Owner or sale date known — enrichment in progress",
    },
  ];

  const counties = breakdown.map(c => c.county);

  const TIER_BUTTONS = [
    { value: "", label: "ALL PIPELINE", count: total },
    { value: "ENRICHED", label: "ENRICHED", count: null },
    { value: "PARTIAL", label: "PARTIAL", count: null },
    { value: "MONITORING", label: "MONITORING", count: null },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "monospace" }}>

      {/* ── Top Nav ── */}
      <div style={{
        borderBottom: "1px solid #1f2937",
        padding: "12px 24px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        background: "#0a0e17",
      }}>
        <Link to="/dashboard" style={{ color: "#6b7280", fontSize: "0.82em", textDecoration: "none" }}>
          ← Dashboard
        </Link>
        <div style={{ width: 1, height: 16, background: "#374151" }} />
        <div style={{ fontWeight: 700, letterSpacing: "0.10em", fontSize: "0.88em", color: "#e5e7eb" }}>
          PRE-SALE PIPELINE INTELLIGENCE
        </div>
        <div style={{ marginLeft: "auto", fontSize: "0.75em", color: "#4b5563" }}>
          C.R.S. § 38-38-111 · 6-Month Restriction Monitor
        </div>
      </div>

      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 20px" }}>

        {/* ── Pipeline Funnel ── */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: "0.7em", letterSpacing: "0.12em", color: "#4b5563", textTransform: "uppercase", marginBottom: 12 }}>
            Pipeline Intelligence · Data Quality Funnel
          </div>
          <div style={{ display: "flex", gap: 0, alignItems: "stretch", marginBottom: 16 }}>
            {[
              { tier: "ENRICHED", count: totalFullyEnriched || enrichedCount, color: "#22c55e", border: "#166534", desc: "Full owner + sale + surplus data" },
              { tier: "PARTIAL",  count: leads.length > 0 ? partialCount : "—", color: "#f59e0b", border: "#92400e", desc: "Partial data — enrichment active" },
              { tier: "MONITORING", count: leads.length > 0 ? monitoringCount : "—", color: "#6b7280", border: "#374151", desc: "Minimal data — under surveillance" },
            ].map((item, idx) => (
              <div
                key={item.tier}
                onClick={() => { setDataTierFilter(dataTierFilter === item.tier ? "" : item.tier); setOffset(0); }}
                style={{
                  flex: 1,
                  background: dataTierFilter === item.tier ? "#111827" : "#0a0e17",
                  border: `1px solid ${dataTierFilter === item.tier ? item.border : "#1f2937"}`,
                  borderLeft: idx > 0 ? "none" : undefined,
                  borderRadius: idx === 0 ? "8px 0 0 8px" : idx === 2 ? "0 8px 8px 0" : "0",
                  padding: "16px 20px",
                  cursor: "pointer",
                  transition: "background 0.15s, border-color 0.15s",
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span style={{ fontSize: "1.8em", fontWeight: 700, color: item.color }}>{item.count}</span>
                  <span style={{ fontSize: "0.72em", color: item.color, letterSpacing: "0.1em" }}>{item.tier}</span>
                </div>
                <div style={{ fontSize: "0.72em", color: "#6b7280", marginTop: 2 }}>{item.desc}</div>
              </div>
            ))}
          </div>

          {/* Stats Row */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 10,
          }}>
            {[
              { label: "Total Monitored", value: total.toLocaleString(), color: "#e5e7eb" },
              { label: "Counties", value: breakdown.length, color: "#6366f1" },
              { label: "Pipeline Value", value: formatCurrency(totalPipeline), color: "#22c55e" },
              { label: "Fully Enriched", value: totalFullyEnriched || enrichedCount, color: "#22c55e" },
              { label: "With Sale Date", value: totalWithSaleDate || leads.filter(l => l.scheduled_sale_date || l.sale_date).length, color: "#f59e0b" },
            ].map(({ label, value, color }) => (
              <div key={label} style={{
                background: "#111827", border: "1px solid #1f2937", borderRadius: 8,
                padding: "12px 16px",
              }}>
                <div style={{ fontSize: "0.68em", letterSpacing: "0.1em", opacity: 0.5, textTransform: "uppercase", marginBottom: 3 }}>
                  {label}
                </div>
                <div style={{ fontSize: "1.3em", fontWeight: 700, color }}>{value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── County Intelligence Grid ── */}
        {breakdown.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <div style={{
              fontSize: "0.7em", letterSpacing: "0.10em", color: "#4b5563",
              textTransform: "uppercase", marginBottom: 10,
            }}>
              County Intelligence Grid · Click to Filter
            </div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: 8,
            }}>
              {breakdown.map(c => {
                const fullyEnriched = c.fully_enriched ?? 0;
                const withSaleDate = c.with_sale_date ?? 0;
                const enrichPct = c.cnt > 0 ? Math.round((fullyEnriched / c.cnt) * 100) : 0;
                const isSelected = countyFilter === c.county;
                const borderCol = fullyEnriched > 0 ? "#166534"
                  : c.with_surplus > 0 ? "#92400e"
                  : "#1f2937";

                return (
                  <div
                    key={c.county}
                    onClick={() => { setCountyFilter(isSelected ? "" : c.county); setOffset(0); }}
                    style={{
                      background: isSelected ? "#111827" : "#0a0e17",
                      border: `1px solid ${isSelected ? "#22c55e" : borderCol}`,
                      borderRadius: 8, padding: "12px 14px", cursor: "pointer",
                      transition: "border-color 0.15s, background 0.15s",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                      <span style={{ fontWeight: 700, fontSize: "0.88em" }}>{titleCase(c.county)}</span>
                      <span style={{ fontSize: "0.72em", color: "#6b7280" }}>{c.cnt.toLocaleString()} leads</span>
                    </div>

                    {/* Enrichment bar */}
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68em", color: "#6b7280", marginBottom: 2 }}>
                        <span>Enrichment</span>
                        <span style={{ color: enrichPct > 0 ? "#22c55e" : "#4b5563" }}>{enrichPct}%</span>
                      </div>
                      <div style={{ height: 4, borderRadius: 2, background: "#1f2937" }}>
                        <div style={{
                          height: "100%", borderRadius: 2,
                          width: `${enrichPct}%`,
                          background: enrichPct >= 50 ? "#22c55e" : enrichPct > 0 ? "#f59e0b" : "#374151",
                        }} />
                      </div>
                    </div>

                    <div style={{ display: "flex", gap: 10, fontSize: "0.72em", color: "#6b7280", flexWrap: "wrap" }}>
                      <span style={{ color: c.with_owner > 0 ? "#22c55e" : "#374151" }}>
                        {c.with_owner} with owner
                      </span>
                      <span style={{ color: withSaleDate > 0 ? "#f59e0b" : "#374151" }}>
                        {withSaleDate} with sale date
                      </span>
                      <span style={{ color: c.with_surplus > 0 ? "#22c55e" : "#374151" }}>
                        {c.with_surplus > 0 ? `${c.with_surplus} w/ surplus` : "no surplus"}
                      </span>
                    </div>

                    {c.pipeline_surplus > 0 && (
                      <div style={{ fontSize: "0.78em", color: "#22c55e", marginTop: 4, fontWeight: 600 }}>
                        {formatCurrency(c.pipeline_surplus)} pipeline
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── Filter Row ── */}
        <div style={{
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
          marginBottom: 20, padding: "12px 16px",
          background: "#0a0e17", border: "1px solid #1f2937", borderRadius: 8,
        }}>
          {/* Tier filter tabs */}
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {TIER_BUTTONS.map(btn => (
              <button
                key={btn.value}
                onClick={() => { setDataTierFilter(btn.value); setOffset(0); }}
                style={{
                  background: dataTierFilter === btn.value ? "#1f2937" : "none",
                  border: `1px solid ${dataTierFilter === btn.value ? "#374151" : "#1f2937"}`,
                  color: dataTierFilter === btn.value ? "#e5e7eb" : "#6b7280",
                  borderRadius: 6, padding: "5px 12px", fontSize: "0.78em",
                  cursor: "pointer", fontFamily: "monospace", letterSpacing: "0.05em",
                  transition: "background 0.1s, color 0.1s",
                }}
              >
                {btn.label}
                {btn.count !== null && <span style={{ marginLeft: 6, opacity: 0.6 }}>— {btn.count.toLocaleString()}</span>}
              </button>
            ))}
          </div>

          <div style={{ width: 1, height: 20, background: "#1f2937" }} />

          {/* County dropdown */}
          <select
            value={countyFilter}
            onChange={e => { setCountyFilter(e.target.value); setOffset(0); }}
            style={{
              background: "#111827", color: "#e5e7eb", border: "1px solid #374151",
              borderRadius: 4, padding: "5px 10px", fontSize: "0.82em", fontFamily: "monospace",
            }}
          >
            <option value="">All Counties</option>
            {counties.map(c => (
              <option key={c} value={c}>{titleCase(c)}</option>
            ))}
          </select>

          {/* Sort */}
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as typeof sortBy)}
            style={{
              background: "#111827", color: "#e5e7eb", border: "1px solid #374151",
              borderRadius: 4, padding: "5px 10px", fontSize: "0.82em", fontFamily: "monospace",
            }}
          >
            <option value="completeness">Sort: By Completeness</option>
            <option value="surplus">Sort: By Surplus</option>
            <option value="sale_date">Sort: By Sale Date</option>
          </select>

          {/* Complete only toggle */}
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.82em", cursor: "pointer", color: "#9ca3af" }}>
            <input
              type="checkbox"
              checked={completeOnly}
              onChange={e => { setCompleteOnly(e.target.checked); setOffset(0); }}
              style={{ accentColor: "#22c55e" }}
            />
            Complete Data Only
          </label>

          {(countyFilter || dataTierFilter) && (
            <button
              onClick={() => { setCountyFilter(""); setDataTierFilter(""); setOffset(0); }}
              style={{
                background: "none", border: "1px solid #374151", color: "#9ca3af",
                borderRadius: 4, padding: "4px 10px", fontSize: "0.78em", cursor: "pointer",
                fontFamily: "monospace",
              }}
            >
              Clear Filters
            </button>
          )}

          <div style={{ marginLeft: "auto", fontSize: "0.78em", color: "#6b7280" }}>
            {loading ? "Loading..." : `${leads.length} of ${total} leads`}
          </div>
        </div>

        {/* ── Error ── */}
        {error && (
          <div style={{
            background: "#1f1215", border: "1px solid #7f1d1d", borderRadius: 6,
            padding: "12px 16px", color: "#fca5a5", marginBottom: 16, fontSize: "0.85em",
          }}>
            {error}
          </div>
        )}

        {/* ── Lead List ── */}
        {loading ? (
          <div style={{ color: "#6b7280", padding: 48, textAlign: "center" }}>
            Loading pre-sale pipeline intelligence...
          </div>
        ) : leads.length === 0 ? (
          <div style={{ color: "#6b7280", padding: 48, textAlign: "center" }}>
            No pre-sale leads match your filters.
          </div>
        ) : dataTierFilter ? (
          /* Single tier filter — flat list */
          <div>
            <div style={{
              fontSize: "0.7em", letterSpacing: "0.1em", color: "#4b5563",
              textTransform: "uppercase", marginBottom: 12,
            }}>
              {dataTierFilter} Leads · {filteredSingleTier!.length} shown
            </div>
            {filteredSingleTier!.map(lead => (
              <LeadHorizontalCard key={lead.id} lead={lead} />
            ))}
          </div>
        ) : (
          /* All tiers — grouped with MONITORING collapsed */
          <div>
            {tierGroups.map(group => group.leads.length > 0 && (
              <div key={group.tier} style={{ marginBottom: 32 }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 12, marginBottom: 12,
                  paddingBottom: 8, borderBottom: "1px solid #1f2937",
                }}>
                  <TierBadge tier={group.tier} />
                  <span style={{ fontWeight: 700, fontSize: "0.88em", letterSpacing: "0.06em", color: "#e5e7eb" }}>
                    {group.label}
                  </span>
                  <span style={{ fontSize: "0.72em", color: "#6b7280" }}>
                    {group.leads.length} leads
                  </span>
                  <span style={{ fontSize: "0.72em", color: "#4b5563", marginLeft: 4 }}>
                    · {group.description}
                  </span>
                </div>
                {group.leads.map(lead => (
                  <LeadHorizontalCard key={lead.id} lead={lead} />
                ))}
              </div>
            ))}

            {/* Monitoring section — collapsed by default */}
            {monitoringLeads.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <button
                  onClick={() => setMonitoringExpanded(x => !x)}
                  style={{
                    display: "flex", alignItems: "center", gap: 12, width: "100%",
                    background: "#0a0e17", border: "1px solid #1f2937", borderRadius: 8,
                    padding: "12px 16px", cursor: "pointer", color: "#6b7280",
                    fontFamily: "monospace", fontSize: "0.82em", textAlign: "left",
                    transition: "background 0.15s",
                    marginBottom: monitoringExpanded ? 12 : 0,
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "#111827"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "#0a0e17"; }}
                >
                  <TierBadge tier="MONITORING" />
                  <span style={{ fontWeight: 700, letterSpacing: "0.06em" }}>
                    {monitoringExpanded ? "▲" : "▼"} SHOW {monitoringLeads.length} MONITORING-ONLY LEADS
                  </span>
                  <span style={{ fontSize: "0.9em", opacity: 0.6, marginLeft: 4 }}>
                    · Minimal data — pending initial enrichment
                  </span>
                  <span style={{ marginLeft: "auto", fontSize: "0.8em" }}>
                    {monitoringExpanded ? "Collapse" : "Expand"}
                  </span>
                </button>

                {monitoringExpanded && (
                  <div>
                    {monitoringLeads.map(lead => (
                      <LeadHorizontalCard key={lead.id} lead={lead} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── Pagination ── */}
        {total > PAGE && (
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 24 }}>
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
              style={{
                background: "#111827", border: "1px solid #374151", color: "#e5e7eb",
                borderRadius: 4, padding: "6px 16px",
                cursor: offset === 0 ? "not-allowed" : "pointer",
                opacity: offset === 0 ? 0.4 : 1, fontFamily: "monospace",
              }}
            >
              ← Prev
            </button>
            <span style={{ color: "#6b7280", fontSize: "0.85em", padding: "6px 0" }}>
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <button
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
              style={{
                background: "#111827", border: "1px solid #374151", color: "#e5e7eb",
                borderRadius: 4, padding: "6px 16px",
                cursor: offset + PAGE >= total ? "not-allowed" : "pointer",
                opacity: offset + PAGE >= total ? 0.4 : 1, fontFamily: "monospace",
              }}
            >
              Next →
            </button>
          </div>
        )}

        {/* ── Legal Note ── */}
        <div style={{
          marginTop: 36, padding: "16px 20px",
          background: "#0a0e17", border: "1px solid #1f2937", borderRadius: 8,
          fontSize: "0.78em", color: "#4b5563", lineHeight: 1.7,
        }}>
          <strong style={{ color: "#6b7280" }}>PRE-SALE PIPELINE NOTE:</strong>{" "}
          These leads are being monitored prior to their foreclosure auction. Surplus claims under C.R.S. § 38-38-111
          require the sale to complete and the 6-month restriction period (C.R.S. § 38-38-111(5)) to expire before
          attorney contact. The <strong style={{ color: "#9ca3af" }}>Expected Action Date</strong> is automatically computed
          as sale date + 6 months. Data completeness scores reflect known fields: owner name (25 pts), property address
          (20 pts), confirmed sale date (25 pts), surplus estimate (20 pts), opening bid (10 pts).
          ENRICHED ≥ 70 · PARTIAL 40–69 · MONITORING &lt; 40.
        </div>
      </div>
    </div>
  );
}
