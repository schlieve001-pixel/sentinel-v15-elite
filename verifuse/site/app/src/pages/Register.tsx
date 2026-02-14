import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";

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
      setError(err instanceof ApiError ? err.message : "Registration failed");
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
          <p className="auth-sub">Start with 5 free credits on the Recon tier.</p>
        </div>

        {error && <div className="auth-error">{error}</div>}

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
              placeholder="Min 8 characters"
              required
              minLength={8}
            />
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
