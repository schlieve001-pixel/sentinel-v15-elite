import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_BASE } from "../lib/api";

const STAGES = ["LEADS", "CONTACTED", "RETAINER_SIGNED", "FILED", "FUNDS_RELEASED"] as const;
type Stage = typeof STAGES[number];

interface AttorneyCase {
  id: string;
  asset_id: string;
  stage: Stage;
  notes?: string;
  outcome_type?: string;
  created_at: string;
  updated_at: string;
  case_number: string;
  county: string;
  data_grade: string;
  overbid_amount?: number;
  property_address?: string;
  sale_date?: string;
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("vf_token");
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

export default function MyCases() {
  const [cases, setCases] = useState<AttorneyCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const loadCases = () => {
    setLoading(true);
    const base = API_BASE || "";
    fetch(`${base}/api/my-cases`, { headers: authHeaders() })
      .then((r) => {
        if (r.status === 401) { window.location.replace("/login"); throw new Error("Unauthorized"); }
        if (!r.ok) return r.json().then((b) => { throw new Error(b.detail || "Failed to load cases"); });
        return r.json();
      })
      .then((data) => setCases(data || []))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadCases(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const updateStage = async (caseId: string, stage: Stage) => {
    try {
      const base = API_BASE || "";
      const res = await fetch(`${base}/api/my-cases/${caseId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ stage }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.detail || "Failed to update stage");
        return;
      }
      setCases((prev) => prev.map((c) => c.id === caseId ? { ...c, stage } : c));
    } catch {
      alert("Failed to update stage");
    }
  };

  const removeCase = async (caseId: string) => {
    if (!confirm("Remove this case from your pipeline?")) return;
    try {
      const base = API_BASE || "";
      const res = await fetch(`${base}/api/my-cases/${caseId}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(body.detail || "Failed to remove");
        return;
      }
      setCases((prev) => prev.filter((c) => c.id !== caseId));
    } catch {
      alert("Failed to remove");
    }
  };

  const casesByStage = (stage: Stage) => cases.filter((c) => c.stage === stage);

  const stageLabel = (s: string) => s.replace(/_/g, " ");

  const gradeColor = (g: string): string => ({
    GOLD: "#eab308",
    SILVER: "#94a3b8",
    BRONZE: "#b45309",
  }[g] || "#64748b");

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "#0f172a", display: "flex", alignItems: "center", justifyContent: "center", color: "#e2e8f0" }}>
        Loading your pipeline...
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: "#0f172a", color: "#e2e8f0", padding: "2rem", fontFamily: "monospace" }}>
      <div style={{ maxWidth: "1400px", margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem" }}>
          <div>
            <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.25rem" }}>My Case Pipeline</h1>
            <p style={{ color: "#64748b", fontSize: "0.9rem", maxWidth: 600 }}>
              Your personal attorney case tracker. Leads you've added via "ADD TO MY PIPELINE" on any Lead Detail page appear here.
              Drag cases through stages: LEADS → CONTACTED → RETAINER SIGNED → FILED → FUNDS RELEASED.
            </p>
            <p style={{ color: "#64748b", fontSize: "0.8rem", marginTop: 4 }}>
              {cases.length} active case{cases.length !== 1 ? "s" : ""} · Private to your account
            </p>
          </div>
          <Link to="/dashboard" style={{ color: "#3b82f6", textDecoration: "none", fontSize: "0.9rem" }}>
            ← Back to Dashboard
          </Link>
        </div>

        {error && (
          <div style={{ padding: "1rem", background: "#dc262622", borderRadius: "0.5rem", color: "#dc2626", marginBottom: "1rem" }}>
            {error}
          </div>
        )}

        {cases.length === 0 && !error && (
          <div style={{ textAlign: "center", padding: "4rem", color: "#64748b" }}>
            <p style={{ fontSize: "1.1rem", marginBottom: "1rem" }}>Your pipeline is empty.</p>
            <Link to="/dashboard" style={{ color: "#3b82f6", textDecoration: "none" }}>
              Browse leads and add them to your pipeline →
            </Link>
          </div>
        )}

        {/* Kanban Board */}
        {cases.length > 0 && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "1rem", overflowX: "auto" }}>
            {STAGES.map((stage) => {
              const stageCases = casesByStage(stage);
              return (
                <div key={stage} style={{ minWidth: "220px" }}>
                  <div style={{
                    padding: "0.625rem 0.75rem",
                    background: "#1e293b",
                    borderRadius: "0.5rem 0.5rem 0 0",
                    borderBottom: "2px solid #3b82f6",
                    marginBottom: "0.5rem",
                  }}>
                    <span style={{ fontSize: "0.75rem", fontWeight: 700 }}>{stageLabel(stage)}</span>
                    <span style={{ marginLeft: "0.5rem", fontSize: "0.7rem", color: "#64748b" }}>
                      ({stageCases.length})
                    </span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", minHeight: "100px" }}>
                    {stageCases.map((c) => (
                      <div key={c.id} style={{
                        padding: "0.75rem",
                        background: "#1e293b",
                        border: "1px solid #334155",
                        borderRadius: "0.5rem",
                        fontSize: "0.8rem",
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.375rem" }}>
                          <button
                            onClick={() => navigate(`/lead/${c.asset_id}`)}
                            style={{ color: "#3b82f6", background: "none", border: "none", cursor: "pointer", fontWeight: 600, fontSize: "0.8rem", fontFamily: "monospace", padding: 0 }}
                          >
                            {c.case_number}
                          </button>
                          <span style={{ color: gradeColor(c.data_grade), fontSize: "0.7rem", fontWeight: 600 }}>
                            {c.data_grade}
                          </span>
                        </div>
                        <div style={{ color: "#64748b", marginBottom: "0.375rem" }}>
                          {c.county?.replace(/_/g, " ")}
                        </div>
                        {c.overbid_amount && (
                          <div style={{ fontWeight: 600, color: "#16a34a", marginBottom: "0.375rem" }}>
                            ${c.overbid_amount.toLocaleString()}
                          </div>
                        )}
                        {c.property_address && (
                          <div style={{ color: "#64748b", fontSize: "0.75rem", marginBottom: "0.5rem", lineHeight: 1.3 }}>
                            {c.property_address}
                          </div>
                        )}
                        {/* Stage selector */}
                        <select
                          value={c.stage}
                          onChange={(e) => updateStage(c.id, e.target.value as Stage)}
                          style={{
                            width: "100%", padding: "0.25rem", fontSize: "0.75rem",
                            border: "1px solid #334155", borderRadius: "0.25rem",
                            background: "#0f172a", color: "#e2e8f0", marginBottom: "0.375rem",
                            fontFamily: "monospace",
                          }}
                        >
                          {STAGES.map((s) => (
                            <option key={s} value={s}>{stageLabel(s)}</option>
                          ))}
                        </select>
                        <button
                          onClick={() => removeCase(c.id)}
                          style={{
                            width: "100%", padding: "0.2rem", fontSize: "0.7rem",
                            background: "none", border: "1px solid #dc262644", color: "#dc2626",
                            borderRadius: "0.25rem", cursor: "pointer", fontFamily: "monospace",
                          }}
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
