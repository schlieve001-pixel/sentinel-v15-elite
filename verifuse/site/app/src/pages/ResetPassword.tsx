import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { API_BASE } from "../lib/api";

function getPasswordStrength(p: string): { score: number; label: string; color: string } {
  let score = 0;
  if (p.length >= 8) score++;
  if (/[A-Z]/.test(p)) score++;
  if (/[0-9]/.test(p)) score++;
  if (/[^a-zA-Z0-9]/.test(p)) score++;
  const labels = ["", "Weak", "Fair", "Strong", "Very Strong"];
  const colors = ["", "#ef4444", "#f59e0b", "#22c55e", "#10b981"];
  return { score, label: labels[score] || "", color: colors[score] || "#374151" };
}

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const strength = getPasswordStrength(password);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.detail || data?.error?.message || "Reset failed.");
        return;
      }
      setDone(true);
      setTimeout(() => navigate("/login"), 2500);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-error">Invalid reset link. Please request a new one.</div>
          <p className="auth-switch"><Link to="/forgot-password">Request new link</Link></p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <Link to="/" className="auth-logo">
            VERIFUSE <span className="text-green">// INTELLIGENCE</span>
          </Link>
          <span className="security-badge">SET NEW PASSWORD</span>
          <h2>Reset Password</h2>
        </div>

        {done ? (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ color: "var(--green)", fontSize: "1.1em", fontWeight: 700, marginBottom: 12 }}>
              ✓ Password Updated
            </div>
            <p style={{ color: "#94a3b8", fontSize: "0.9em" }}>
              Redirecting to login…
            </p>
          </div>
        ) : (
          <>
            {error && <div className="auth-error">{error}</div>}
            <form onSubmit={handleSubmit}>
              <div className="input-group">
                <label>NEW PASSWORD</label>
                <input
                  type="password"
                  className="forensic-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 8 chars, uppercase, number, symbol"
                  required
                  autoFocus
                />
                {password.length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ display: "flex", gap: 4, marginBottom: 4 }}>
                      {[1, 2, 3, 4].map((i) => (
                        <div key={i} style={{
                          flex: 1, height: 4, borderRadius: 2,
                          background: i <= strength.score ? strength.color : "#1f2937",
                          transition: "background 0.2s",
                        }} />
                      ))}
                    </div>
                    <div style={{ fontSize: "0.75em", color: strength.color, letterSpacing: "0.05em" }}>
                      {strength.label}
                    </div>
                  </div>
                )}
              </div>
              <div className="input-group">
                <label>CONFIRM PASSWORD</label>
                <input
                  type="password"
                  className="forensic-input"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="Repeat new password"
                  required
                />
              </div>
              <button type="submit" className="action-btn" disabled={loading || strength.score < 4}>
                {loading ? "UPDATING..." : "SET NEW PASSWORD"}
              </button>
            </form>
            <p className="auth-switch">
              <Link to="/login">← Back to Login</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
