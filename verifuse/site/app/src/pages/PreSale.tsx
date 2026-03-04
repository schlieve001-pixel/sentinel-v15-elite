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

export default function PreSale() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [leads, setLeads] = useState<PreSaleLead[]>([]);
  const [breakdown, setBreakdown] = useState<CountyBreakdown[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [countyFilter, setCountyFilter] = useState<string>("");
  const [hasDataOnly, setHasDataOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const PAGE = 200;

  const load = useCallback((ac?: AbortController) => {
    setLoading(true);
    setError(null);
    getPreSaleLeads(
      { county: countyFilter || undefined, has_data: hasDataOnly || undefined, limit: PAGE, offset },
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
  }, [countyFilter, hasDataOnly, offset]);

  useEffect(() => {
    if (!user) {
      navigate("/login");
      return;
    }
    const ac = new AbortController();
    load(ac);
    return () => ac.abort();
  }, [user, navigate, load]);

  const totalPipeline = breakdown.reduce((s, c) => s + (c.pipeline_surplus ?? 0), 0);
  const countiesWithData = breakdown.filter(c => c.with_owner > 0 || c.with_surplus > 0).length;
  const leadsWithSurplus = breakdown.reduce((s, c) => s + c.with_surplus, 0);

  const counties = breakdown.map(c => c.county);

  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "monospace" }}>
      {/* Top Nav */}
      <div style={{
        borderBottom: "1px solid #1f2937",
        padding: "12px 24px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        background: "#111827",
      }}>
        <Link to="/dashboard" style={{ color: "#6b7280", fontSize: "0.85em", textDecoration: "none" }}>
          ← Dashboard
        </Link>
        <div style={{ fontWeight: 700, letterSpacing: "0.08em", fontSize: "0.9em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>// PRE-SALE PIPELINE</span>
        </div>
      </div>

      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "24px 20px" }}>
        {/* Page header */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ margin: 0, fontSize: "1.4em", fontWeight: 700, letterSpacing: "0.06em" }}>
            Pre-Sale Pipeline
          </h1>
          <p style={{ margin: "6px 0 0", color: "#6b7280", fontSize: "0.85em" }}>
            Upcoming Colorado foreclosure auctions being monitored for surplus potential.
            These leads become actionable after sale completion + 6-month restriction period.
          </p>
        </div>

        {/* Stats row */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 10,
          marginBottom: 24,
        }}>
          {[
            { label: "Total Monitored", value: total.toLocaleString(), color: "#22c55e" },
            { label: "Counties", value: breakdown.length, color: "#6366f1" },
            { label: "Counties with Data", value: countiesWithData, color: "#f59e0b" },
            { label: "With Surplus Est.", value: leadsWithSurplus, color: "#22c55e" },
            { label: "Pipeline Value", value: formatCurrency(totalPipeline), color: "#22c55e" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              background: "#111827", border: "1px solid #1f2937", borderRadius: 8,
              padding: "14px 18px",
            }}>
              <div style={{ fontSize: "0.7em", letterSpacing: "0.1em", opacity: 0.55, textTransform: "uppercase", marginBottom: 4 }}>
                {label}
              </div>
              <div style={{ fontSize: "1.5em", fontWeight: 700, color }}>{value}</div>
            </div>
          ))}
        </div>

        {/* County breakdown table */}
        {breakdown.length > 0 && (
          <div style={{ marginBottom: 24 }}>
            <div style={{
              fontSize: "0.75em", letterSpacing: "0.08em", opacity: 0.5,
              textTransform: "uppercase", marginBottom: 8,
            }}>County Breakdown</div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 8,
            }}>
              {breakdown.map(c => (
                <div
                  key={c.county}
                  onClick={() => setCountyFilter(countyFilter === c.county ? "" : c.county)}
                  style={{
                    background: countyFilter === c.county ? "#1f2937" : "#111827",
                    border: `1px solid ${countyFilter === c.county ? "#22c55e" : "#1f2937"}`,
                    borderRadius: 6, padding: "10px 14px", cursor: "pointer",
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: "0.9em", marginBottom: 4 }}>
                    {titleCase(c.county)}
                    <span style={{ fontSize: "0.75em", color: "#6b7280", fontWeight: 400, marginLeft: 8 }}>
                      {c.cnt.toLocaleString()} leads
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 12, fontSize: "0.78em", color: "#9ca3af" }}>
                    <span style={{ color: c.with_owner > 0 ? "#22c55e" : "#374151" }}>
                      {c.with_owner} with owner
                    </span>
                    <span style={{ color: c.with_surplus > 0 ? "#f59e0b" : "#374151" }}>
                      {c.with_surplus > 0 ? `${c.with_surplus} surplus` : "no surplus"}
                    </span>
                  </div>
                  {c.pipeline_surplus > 0 && (
                    <div style={{ fontSize: "0.8em", color: "#22c55e", marginTop: 2 }}>
                      {formatCurrency(c.pipeline_surplus)} pipeline
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        <div style={{
          display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
          marginBottom: 16, padding: "12px 16px",
          background: "#111827", border: "1px solid #1f2937", borderRadius: 8,
        }}>
          <select
            value={countyFilter}
            onChange={e => { setCountyFilter(e.target.value); setOffset(0); }}
            style={{
              background: "#0d1117", color: "#e5e7eb", border: "1px solid #374151",
              borderRadius: 4, padding: "6px 10px", fontSize: "0.85em", fontFamily: "monospace",
            }}
          >
            <option value="">All Counties</option>
            {counties.map(c => (
              <option key={c} value={c}>{titleCase(c)}</option>
            ))}
          </select>

          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85em", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={hasDataOnly}
              onChange={e => { setHasDataOnly(e.target.checked); setOffset(0); }}
              style={{ accentColor: "#22c55e" }}
            />
            Has owner or surplus data
          </label>

          {countyFilter && (
            <button
              onClick={() => setCountyFilter("")}
              style={{
                background: "none", border: "1px solid #374151", color: "#9ca3af",
                borderRadius: 4, padding: "4px 10px", fontSize: "0.8em", cursor: "pointer",
              }}
            >
              Clear filter
            </button>
          )}

          <div style={{ marginLeft: "auto", fontSize: "0.8em", color: "#6b7280" }}>
            {loading ? "Loading..." : `${leads.length} of ${total} leads`}
          </div>
        </div>

        {error && (
          <div style={{
            background: "#1f1215", border: "1px solid #7f1d1d", borderRadius: 6,
            padding: "12px 16px", color: "#fca5a5", marginBottom: 16, fontSize: "0.85em",
          }}>
            {error}
          </div>
        )}

        {/* Leads table */}
        {loading ? (
          <div style={{ color: "#6b7280", padding: 32, textAlign: "center" }}>Loading pre-sale pipeline...</div>
        ) : leads.length === 0 ? (
          <div style={{ color: "#6b7280", padding: 32, textAlign: "center" }}>
            No pre-sale leads match your filters.
          </div>
        ) : (
          <div>
            <div style={{
              display: "grid",
              gridTemplateColumns: "120px 140px 1fr 120px 100px 110px 90px",
              gap: 0,
              fontSize: "0.72em",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "#4b5563",
              borderBottom: "1px solid #1f2937",
              padding: "8px 12px",
            }}>
              <span>County</span>
              <span>Case #</span>
              <span>Owner / Address</span>
              <span>Scheduled Sale</span>
              <span>Opening Bid</span>
              <span>Surplus Est.</span>
              <span>Source</span>
            </div>

            {leads.map(lead => {
              const hasSurplus = lead.surplus_amount && lead.surplus_amount > 0;
              const hasOwner = lead.owner_name && lead.owner_name.trim() !== "";

              return (
                <Link
                  key={lead.id}
                  to={`/lead/${lead.id}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div style={{
                    display: "grid",
                    gridTemplateColumns: "120px 140px 1fr 120px 100px 110px 90px",
                    gap: 0,
                    padding: "10px 12px",
                    borderBottom: "1px solid #111827",
                    fontSize: "0.82em",
                    background: hasSurplus ? "rgba(34,197,94,0.03)" : "transparent",
                    cursor: "pointer",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = "#111827")}
                  onMouseLeave={e => (e.currentTarget.style.background = hasSurplus ? "rgba(34,197,94,0.03)" : "transparent")}
                  >
                    <span style={{ color: "#9ca3af", fontSize: "0.9em" }}>
                      {titleCase(lead.county)}
                    </span>
                    <span style={{ color: "#d1d5db", fontWeight: 600, fontSize: "0.9em" }}>
                      {lead.case_number ?? "—"}
                    </span>
                    <span style={{ color: hasOwner ? "#e5e7eb" : "#374151", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {hasOwner ? lead.owner_name : (lead.property_address ? lead.property_address : "—")}
                    </span>
                    <span style={{ color: lead.scheduled_sale_date ? "#f59e0b" : "#4b5563" }}>
                      {lead.scheduled_sale_date ?? (lead.sale_date ? lead.sale_date : "—")}
                    </span>
                    <span style={{ color: lead.opening_bid > 0 ? "#9ca3af" : "#374151" }}>
                      {lead.opening_bid > 0 ? formatCurrency(lead.opening_bid) : "—"}
                    </span>
                    <span style={{ color: hasSurplus ? "#22c55e" : "#374151", fontWeight: hasSurplus ? 700 : 400 }}>
                      {hasSurplus ? formatCurrency(lead.surplus_amount) : "—"}
                    </span>
                    <span style={{ color: "#4b5563", fontSize: "0.85em" }}>
                      {lead.ingestion_source === "govsoft" ? "GovSoft" : lead.ingestion_source ?? "—"}
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}

        {/* Pagination */}
        {total > PAGE && (
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 20 }}>
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
              style={{
                background: "#111827", border: "1px solid #374151", color: "#e5e7eb",
                borderRadius: 4, padding: "6px 16px", cursor: offset === 0 ? "not-allowed" : "pointer",
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
                borderRadius: 4, padding: "6px 16px", cursor: offset + PAGE >= total ? "not-allowed" : "pointer",
                opacity: offset + PAGE >= total ? 0.4 : 1, fontFamily: "monospace",
              }}
            >
              Next →
            </button>
          </div>
        )}

        {/* Informational note */}
        <div style={{
          marginTop: 32, padding: "16px 20px",
          background: "#0a0e17", border: "1px solid #1f2937", borderRadius: 8,
          fontSize: "0.8em", color: "#4b5563", lineHeight: 1.6,
        }}>
          <strong style={{ color: "#6b7280" }}>PRE-SALE PIPELINE NOTE:</strong>{" "}
          These leads are being monitored prior to their foreclosure auction. Surplus claims under C.R.S. § 38-38-111
          require the sale to complete and the 6-month restriction period (C.R.S. § 38-38-111(5)) to expire before
          attorney contact. Leads with surplus estimates are prioritized. Data completeness varies by county — leads
          without owner data will be enriched via assessor lookup after sale completion.
        </div>
      </div>
    </div>
  );
}
