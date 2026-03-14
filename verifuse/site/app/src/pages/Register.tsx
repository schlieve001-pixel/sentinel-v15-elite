import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";

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

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    firm_name: "",
    bar_number: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const strength = getPasswordStrength(form.password);

  function update(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register(form);
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Account already exists. Please log in.");
      } else {
        setError(err instanceof ApiError ? err.message : "Registration failed");
      }
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
          <span className="security-badge">NEW ACCOUNT</span>
          <h2>Create Your Account</h2>
          <p className="auth-sub">3 free credits on signup — unlock 3 real leads, see the actual data. No card required.</p>
        </div>

        {error && (
          <div className="auth-error">
            {error}
            {error.includes("already exists") && (
              <> <Link to="/login" style={{ color: "var(--green)" }}>Log in here</Link></>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="input-group">
            <label>FULL NAME</label>
            <input
              type="text"
              className="forensic-input"
              value={form.full_name}
              onChange={(e) => update("full_name", e.target.value)}
              placeholder="Jane Smith"
              required
              autoFocus
            />
          </div>
          <div className="input-group">
            <label>EMAIL</label>
            <input
              type="email"
              className="forensic-input"
              value={form.email}
              onChange={(e) => update("email", e.target.value)}
              placeholder="attorney@firm.com"
              required
            />
          </div>
          <div className="input-group">
            <label>PASSWORD</label>
            <input
              type="password"
              className="forensic-input"
              value={form.password}
              onChange={(e) => update("password", e.target.value)}
              placeholder="8+ chars, uppercase, number, symbol"
              required
            />
            {form.password.length > 0 && (
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
          <div className="input-row">
            <div className="input-group">
              <label>FIRM NAME</label>
              <input
                type="text"
                className="forensic-input"
                value={form.firm_name}
                onChange={(e) => update("firm_name", e.target.value)}
                placeholder="Smith & Associates"
              />
            </div>
            <div className="input-group">
              <label>BAR NUMBER</label>
              <input
                type="text"
                className="forensic-input"
                value={form.bar_number}
                onChange={(e) => update("bar_number", e.target.value)}
                placeholder="55-90210"
              />
            </div>
          </div>
          <button type="submit" className="action-btn" disabled={loading}>
            {loading ? "CREATING ACCOUNT..." : "CREATE ACCOUNT"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Login here</Link>
        </p>

        <p className="auth-disclaimer">
          By registering you agree to our Terms of Service. VeriFuse provides
          public record data for research purposes only and does not constitute
          legal advice.
        </p>
      </div>
    </div>
  );
}
