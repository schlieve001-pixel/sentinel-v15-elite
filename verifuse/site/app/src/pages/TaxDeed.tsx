import { useEffect, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getTaxDeedLeads, type Lead } from "../lib/api";
import { useAuth } from "../lib/auth";

function fmt(n: number | null | undefined): string {
  if (n == null || n <= 0) return "—";
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toFixed(0);
}

const GRADE_COLORS: Record<string, string> = {
  GOLD: "#f59e0b", SILVER: "#94a3b8", BRONZE: "#b45309", REJECT: "#ef4444",
};

export default function TaxDeed() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [countyFilter, setCountyFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const PAGE = 100;

  const load = useCallback((ac?: AbortController) => {
    setLoading(true);
    setError(null);
    getTaxDeedLeads({ county: countyFilter || undefined, limit: PAGE, offset }, ac?.signal)
      .then(res => { setLeads(res.leads); setTotal(res.count); setLoading(false); })
      .catch(e => { if (e?.name !== "AbortError") { setError(e?.message ?? "Load failed"); setLoading(false); } });
  }, [countyFilter, offset]);

  useEffect(() => {
    if (!user) { navigate("/login"); return; }
    const ac = new AbortController();
    load(ac);
    return () => ac.abort();
  }, [user, navigate, load]);

  const totalSurplus = leads.reduce((s, l) => s + (l.estimated_surplus ?? 0), 0);

  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "monospace" }}>
      {/* Nav */}
      <div style={{ borderBottom: "1px solid #1f2937", padding: "12px 24px", display: "flex", alignItems: "center", gap: 16, background: "#111827" }}>
        <Link to="/dashboard" style={{ color: "#6b7280", fontSize: "0.85em", textDecoration: "none" }}>← Dashboard</Link>
        <span style={{ color: "#f59e0b", fontWeight: 700, letterSpacing: "0.08em" }}>TAX DEED SURPLUS</span>
        <span style={{ fontSize: "0.75em", color: "#6b7280" }}>C.R.S. § 39-12-111</span>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px" }}>

        {/* Header KPIs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 24 }}>
          {[
            { label: "TOTAL LEADS", value: String(total), color: "#e5e7eb" },
            { label: "PIPELINE VALUE", value: fmt(totalSurplus), color: "#22c55e" },
            { label: "GOLD GRADE", value: String(leads.filter(l => l.data_grade === "GOLD").length), color: "#f59e0b" },
          ].map(k => (
            <div key={k.label} style={{ border: "1px solid #374151", borderRadius: 8, padding: "12px 16px", background: "#0d1117" }}>
              <div style={{ fontSize: "0.65em", letterSpacing: "0.1em", color: "#6b7280", marginBottom: 4 }}>{k.label}</div>
              <div style={{ fontSize: "1.3em", fontWeight: 700, color: k.color }}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Statute context */}
        <div style={{ background: "#0d1117", border: "1px solid #374151", borderRadius: 8, padding: "14px 18px", marginBottom: 20, fontSize: "0.8em", color: "#9ca3af" }}>
          <strong style={{ color: "#f59e0b" }}>Tax Deed Surplus</strong> — When a county sells property for unpaid taxes and the sale price exceeds the tax debt,
          the surplus belongs to the prior owner (C.R.S. § 39-12-111). No 6-month restriction applies — these cases are immediately actionable.
        </div>

        {/* Filter bar */}
        <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center" }}>
          <input
            type="text"
            placeholder="Filter by county..."
            value={countyFilter}
            onChange={e => { setCountyFilter(e.target.value); setOffset(0); }}
            style={{ background: "#111827", border: "1px solid #374151", color: "#e5e7eb", padding: "7px 12px", borderRadius: 6, fontSize: "0.85em", fontFamily: "monospace", width: 220 }}
          />
          <span style={{ fontSize: "0.78em", color: "#6b7280" }}>{total} leads</span>
        </div>

        {/* Table */}
        {loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#6b7280" }}>LOADING...</div>
        ) : error ? (
          <div style={{ padding: 20, color: "#ef4444", fontSize: "0.85em" }}>{error}</div>
        ) : leads.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "#6b7280" }}>
            No tax deed surplus leads yet. Run <code style={{ background: "#1f2937", padding: "2px 6px", borderRadius: 3 }}>bin/vf tax-lien-run</code> to populate.
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82em" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #374151", color: "#6b7280", fontSize: "0.85em" }}>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}>COUNTY</th>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}>CASE</th>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}>OWNER</th>
                  <th style={{ textAlign: "right", padding: "6px 10px" }}>SURPLUS</th>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}>GRADE</th>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}>SALE DATE</th>
                  <th style={{ textAlign: "left", padding: "6px 10px" }}></th>
                </tr>
              </thead>
              <tbody>
                {leads.map(lead => (
                  <tr key={lead.asset_id} style={{ borderBottom: "1px solid #1f2937" }}>
                    <td style={{ padding: "7px 10px", color: "#9ca3af" }}>{lead.county?.replace(/_/g, " ").toUpperCase() || "—"}</td>
                    <td style={{ padding: "7px 10px", fontFamily: "monospace", fontSize: "0.9em", color: "#9ca3af" }}>{lead.case_number || "—"}</td>
                    <td style={{ padding: "7px 10px" }}>{lead.owner_name || <span style={{ color: "#4b5563" }}>locked</span>}</td>
                    <td style={{ padding: "7px 10px", textAlign: "right", color: "#22c55e", fontWeight: 700 }}>{fmt(lead.estimated_surplus)}</td>
                    <td style={{ padding: "7px 10px" }}>
                      <span style={{ color: GRADE_COLORS[lead.data_grade] || "#6b7280", fontWeight: 700, fontSize: "0.85em" }}>{lead.data_grade}</span>
                    </td>
                    <td style={{ padding: "7px 10px", color: "#9ca3af", fontSize: "0.9em" }}>{lead.sale_date?.slice(0, 10) || "—"}</td>
                    <td style={{ padding: "7px 10px" }}>
                      <Link to={`/lead/${lead.asset_id}`} style={{ color: "#22c55e", textDecoration: "none", fontSize: "0.8em" }}>VIEW →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {total > PAGE && (
          <div style={{ display: "flex", gap: 10, marginTop: 16, justifyContent: "center" }}>
            <button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}
              style={{ background: "none", border: "1px solid #374151", color: "#9ca3af", padding: "6px 16px", borderRadius: 5, cursor: offset === 0 ? "not-allowed" : "pointer", fontFamily: "monospace", fontSize: "0.8em" }}>
              ← PREV
            </button>
            <span style={{ color: "#6b7280", fontSize: "0.8em", alignSelf: "center" }}>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= total}
              style={{ background: "none", border: "1px solid #374151", color: "#9ca3af", padding: "6px 16px", borderRadius: 5, cursor: offset + PAGE >= total ? "not-allowed" : "pointer", fontFamily: "monospace", fontSize: "0.8em" }}>
              NEXT →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
