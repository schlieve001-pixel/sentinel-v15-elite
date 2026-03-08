import { useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      setSubmitted(true);
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <Link to="/" className="auth-logo">
            VERIFUSE <span className="text-green">// INTELLIGENCE</span>
          </Link>
          <span className="security-badge">PASSWORD RESET</span>
          <h2>Forgot Password</h2>
        </div>

        {submitted ? (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ color: "var(--green)", fontSize: "1.1em", fontWeight: 700, marginBottom: 12 }}>
              ✓ Check Your Email
            </div>
            <p style={{ color: "#94a3b8", fontSize: "0.9em", lineHeight: 1.6 }}>
              If that email is registered, we've sent reset instructions. Check your inbox.
            </p>
            <p style={{ marginTop: 16 }}>
              <Link to="/login" style={{ color: "var(--green)" }}>← Back to Login</Link>
            </p>
          </div>
        ) : (
          <>
            {error && <div className="auth-error">{error}</div>}
            <form onSubmit={handleSubmit}>
              <div className="input-group">
                <label>EMAIL ADDRESS</label>
                <input
                  type="email"
                  className="forensic-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="attorney@firm.com"
                  required
                  autoFocus
                />
              </div>
              <button type="submit" className="action-btn" disabled={loading}>
                {loading ? "SENDING..." : "SEND RESET LINK"}
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
