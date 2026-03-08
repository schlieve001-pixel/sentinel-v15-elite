import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../lib/api";

interface CountyCoverage {
  county_slug: string;
  county_name: string;
  status: "active" | "partial" | "configured" | "no_data";
  gold_count: number;
  silver_count: number;
  bronze_count: number;
  total_leads: number;
  last_scraped_at?: string;
  access_method: string;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function Coverage() {
  const [counties, setCounties] = useState<CountyCoverage[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<CountyCoverage | null>(null);

  useEffect(() => {
    const base = API_BASE || "";
    fetch(`${base}/api/coverage-map`, { headers: authHeaders() })
      .then((r) => r.ok ? r.json() : Promise.resolve([]))
      .then((data) => setCounties(data || []))
      .catch(() => setCounties([]))
      .finally(() => setLoading(false));
  }, []);

  const statusColor = (s: string) => ({
    active: "#16a34a",
    partial: "#d97706",
    configured: "#3b82f6",
    no_data: "#64748b",
  }[s] || "#64748b");

  const statusLabel = (s: string) => ({
    active: "ACTIVE (GOLD/SILVER leads)",
    partial: "PARTIAL (BRONZE leads only)",
    configured: "CONFIGURED (no leads yet)",
    no_data: "NO DATA",
  }[s] || s.toUpperCase());

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#e2e8f0", padding: "2rem" }}>
      <div style={{ maxWidth: "1200px", margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem" }}>
          <div>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem" }}>Colorado County Coverage</h1>
            <p style={{ color: "#64748b", fontSize: "0.9rem" }}>64-county foreclosure surplus intelligence network</p>
          </div>
          <Link to="/dashboard" style={{ color: "#3b82f6", textDecoration: "none", fontSize: "0.9rem" }}>← Back to Dashboard</Link>
        </div>

        {/* Legend */}
        <div style={{ display: "flex", gap: "1.5rem", marginBottom: "2rem", flexWrap: "wrap" }}>
          {[
            ["active", "#16a34a", "Active"],
            ["partial", "#d97706", "Partial"],
            ["configured", "#3b82f6", "Configured"],
            ["no_data", "#64748b", "No Data"],
          ].map(([s, c, l]) => (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.8rem" }}>
              <div style={{ width: "12px", height: "12px", borderRadius: "2px", background: c }} />
              <span>{l}</span>
            </div>
          ))}
        </div>

        {loading && (
          <div style={{ textAlign: "center", padding: "3rem", color: "#64748b" }}>Loading coverage data...</div>
        )}

        {/* County Grid */}
        {!loading && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.75rem" }}>
            {counties.map((c) => (
              <div
                key={c.county_slug}
                onClick={() => setSelected(selected?.county_slug === c.county_slug ? null : c)}
                style={{
                  padding: "0.875rem",
                  borderRadius: "0.5rem",
                  border: `2px solid ${selected?.county_slug === c.county_slug ? statusColor(c.status) : "#334155"}`,
                  background: selected?.county_slug === c.county_slug ? `${statusColor(c.status)}11` : "#1e293b",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  if (!selected) e.currentTarget.style.borderColor = statusColor(c.status);
                }}
                onMouseLeave={(e) => {
                  if (!selected) e.currentTarget.style.borderColor = "#334155";
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.375rem" }}>
                  <span style={{ fontWeight: 600, fontSize: "0.85rem" }}>{c.county_name.replace(" County", "")}</span>
                  <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: statusColor(c.status), marginTop: "3px" }} />
                </div>
                {c.total_leads > 0 && (
                  <div style={{ fontSize: "0.75rem", color: "#64748b", display: "flex", gap: "0.5rem" }}>
                    {c.gold_count > 0 && <span style={{ color: "#eab308" }}>●{c.gold_count}G</span>}
                    {c.silver_count > 0 && <span style={{ color: "#94a3b8" }}>●{c.silver_count}S</span>}
                    {c.bronze_count > 0 && <span>●{c.bronze_count}B</span>}
                  </div>
                )}
                {c.total_leads === 0 && (
                  <span style={{ fontSize: "0.7rem", color: "#64748b" }}>No leads</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Selected county panel */}
        {selected && (
          <div style={{
            marginTop: "2rem", padding: "1.5rem",
            background: "#1e293b",
            border: `1px solid ${statusColor(selected.status)}`,
            borderRadius: "0.75rem",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <h2 style={{ fontSize: "1.2rem", fontWeight: 700, marginBottom: "0.25rem" }}>{selected.county_name}</h2>
                <p style={{ color: statusColor(selected.status), fontSize: "0.85rem", fontWeight: 600, margin: 0 }}>
                  {statusLabel(selected.status)}
                </p>
              </div>
              <button
                onClick={() => setSelected(null)}
                style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "1.2rem" }}
              >✕</button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1rem", marginTop: "1rem" }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#eab308" }}>{selected.gold_count}</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>GOLD</div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "1.5rem", fontWeight: 700, color: "#94a3b8" }}>{selected.silver_count}</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>SILVER</div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{selected.bronze_count}</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>BRONZE</div>
              </div>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{selected.total_leads}</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>TOTAL</div>
              </div>
            </div>
            <div style={{ marginTop: "1rem", fontSize: "0.8rem", color: "#64748b", display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
              <span>Access: <strong style={{ color: "#e2e8f0" }}>{selected.access_method}</strong></span>
              {selected.last_scraped_at && (
                <span>Last scraped: <strong style={{ color: "#e2e8f0" }}>{new Date(selected.last_scraped_at).toLocaleDateString()}</strong></span>
              )}
            </div>
            {selected.status === "active" && (
              <Link
                to="/dashboard"
                style={{
                  display: "inline-block", marginTop: "1rem", padding: "0.5rem 1rem",
                  background: "#3b82f6", color: "white", borderRadius: "0.375rem",
                  textDecoration: "none", fontSize: "0.85rem",
                }}
              >
                View {selected.county_name} Leads →
              </Link>
            )}
          </div>
        )}

        {/* Summary stats */}
        {!loading && counties.length > 0 && (
          <div style={{ marginTop: "2rem", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "1rem" }}>
            {[
              ["Active Counties", counties.filter((c) => c.status === "active").length],
              ["Partial Coverage", counties.filter((c) => c.status === "partial").length],
              ["Total GOLD Leads", counties.reduce((s, c) => s + c.gold_count, 0)],
              ["Total SILVER Leads", counties.reduce((s, c) => s + c.silver_count, 0)],
            ].map(([label, val]) => (
              <div key={label as string} style={{ padding: "1rem", background: "#1e293b", borderRadius: "0.5rem", textAlign: "center" }}>
                <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{val}</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>{label}</div>
              </div>
            ))}
          </div>
        )}

        {!loading && counties.length === 0 && (
          <div style={{ textAlign: "center", padding: "3rem", color: "#64748b" }}>
            <p>No coverage data available. The /api/coverage-map endpoint may not be implemented yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}
