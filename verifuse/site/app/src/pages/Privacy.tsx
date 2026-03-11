import { Link } from "react-router-dom";

const EFFECTIVE_DATE = "June 4, 2025";
const COMPANY = "VeriFuse Technologies LLC";
const CONTACT_EMAIL = "privacy@verifuse.tech";

export default function Privacy() {
  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}>
      {/* Nav */}
      <nav style={{ borderBottom: "1px solid #1f2937", padding: "14px 32px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Link to="/" style={{ color: "#e5e7eb", textDecoration: "none", fontWeight: 700, fontSize: "0.9em", letterSpacing: "0.08em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>//</span> INTELLIGENCE
        </Link>
        <div style={{ display: "flex", gap: 24, fontSize: "0.8em" }}>
          <Link to="/terms" style={{ color: "#9ca3af", textDecoration: "none" }}>Terms of Service</Link>
          <Link to="/login" style={{ color: "#9ca3af", textDecoration: "none" }}>Login</Link>
        </div>
      </nav>

      <div style={{ maxWidth: 820, margin: "0 auto", padding: "48px 32px 80px" }}>
        <div style={{ marginBottom: 40 }}>
          <div style={{ fontSize: "0.75em", color: "#22c55e", letterSpacing: "0.1em", marginBottom: 12 }}>LEGAL</div>
          <h1 style={{ fontSize: "2em", fontWeight: 700, margin: "0 0 12px", lineHeight: 1.2 }}>Privacy Policy</h1>
          <p style={{ color: "#6b7280", fontSize: "0.85em", margin: 0 }}>
            Effective: {EFFECTIVE_DATE} &nbsp;·&nbsp; {COMPANY}
          </p>
        </div>

        <div style={{ borderLeft: "3px solid #1f2937", paddingLeft: 20, marginBottom: 40, color: "#9ca3af", fontSize: "0.85em", lineHeight: 1.7 }}>
          VeriFuse takes data privacy seriously. This policy explains what we collect, why, and how you can control it.
          We do not sell your personal information to third parties.
        </div>

        <Section title="1. Information We Collect">
          <p><strong style={{ color: "#f3f4f6" }}>Account Information</strong></p>
          <ul>
            <li>Name, email address, and password (hashed with bcrypt — never stored in plaintext)</li>
            <li>Law firm name, bar number, bar state, firm address (optional — for document generation)</li>
            <li>Phone number and website (optional)</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Billing Information</strong></p>
          <ul>
            <li>Stripe customer ID and subscription status</li>
            <li>We do not store payment card numbers. All payment data is handled by Stripe, Inc.
            under their own <a href="https://stripe.com/privacy" target="_blank" rel="noreferrer" style={{ color: "#22c55e" }}>Privacy Policy</a>.</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Usage Data</strong></p>
          <ul>
            <li>Leads unlocked, credits used, case actions taken</li>
            <li>IP address (for rate limiting and abuse prevention), browser type, operating system</li>
            <li>Request logs (method, path, response time) — retained for 30 days</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Lead / Case Data</strong></p>
          <ul>
            <li>Case management records you create in the attorney workspace</li>
            <li>Notes and case outcomes you record voluntarily</li>
          </ul>
        </Section>

        <Section title="2. How We Use Your Information">
          <ul>
            <li><strong>Service delivery</strong> — Authenticate your account, process credits, serve lead data</li>
            <li><strong>Communications</strong> — Send transactional emails (verification, billing receipts, lead alerts you opt into)</li>
            <li><strong>Security</strong> — Detect fraud, prevent abuse, enforce rate limits, and maintain audit logs</li>
            <li><strong>Product improvement</strong> — Aggregate, anonymized usage analytics to improve coverage and accuracy</li>
            <li><strong>Legal compliance</strong> — Respond to lawful subpoenas, court orders, or regulatory requests</li>
          </ul>
          <p>We do not use your data for advertising or sell it to data brokers.</p>
        </Section>

        <Section title="3. Public Record Data">
          <p>Lead data on the VeriFuse platform is derived from publicly available county foreclosure records
          (Colorado public trustee filings, assessor records, court records). This data does not originate from
          you — it exists in public government databases. We aggregate, enrich, and analyze it to create the
          intelligence layer of our Service.</p>
          <p>Property owner names, addresses, and case details shown on leads are public record. We mask
          full owner names for unauthenticated users and non-attorney tiers to prevent misuse.</p>
        </Section>

        <Section title="4. Data Sharing">
          <p>We share personal information only in these limited circumstances:</p>
          <ul>
            <li><strong>Stripe</strong> — Payment processing (name, email, billing amount). Governed by Stripe's privacy policy.</li>
            <li><strong>SendGrid</strong> — Transactional email delivery (email address, name). Governed by Twilio SendGrid's privacy policy.</li>
            <li><strong>Google Cloud Platform</strong> — Document AI and Gemini APIs for document verification (PDF bytes only, no personal data). GCP processes data under our service agreement.</li>
            <li><strong>Law enforcement / legal process</strong> — If required by valid court order, subpoena, or applicable law.</li>
            <li><strong>Business transfer</strong> — In the event of a merger, acquisition, or asset sale, your data may be transferred as part of the transaction. We will notify you via email before such a transfer.</li>
          </ul>
          <p>We never sell, rent, or share personal information for marketing purposes.</p>
        </Section>

        <Section title="5. Data Retention">
          <ul>
            <li><strong>Account data</strong> — Retained while your account is active. Deleted within 90 days of account closure upon request.</li>
            <li><strong>Audit logs</strong> — Retained for 2 years for legal compliance purposes.</li>
            <li><strong>Request logs</strong> — Retained for 30 days, then auto-purged.</li>
            <li><strong>Billing records</strong> — Retained for 7 years per tax/accounting requirements.</li>
          </ul>
        </Section>

        <Section title="6. Security">
          <p>We implement industry-standard security measures including:</p>
          <ul>
            <li>TLS 1.3 in transit (HSTS enforced)</li>
            <li>bcrypt password hashing (work factor 12)</li>
            <li>JWT tokens with short expiration and server-side revocation</li>
            <li>Rate limiting and IP-based abuse detection</li>
            <li>RBAC (role-based access control) with principle of least privilege</li>
            <li>Audit logging of all sensitive data access</li>
          </ul>
          <p>No system is perfectly secure. If you discover a security vulnerability, please report it to
          <a href="mailto:security@verifuse.tech" style={{ color: "#22c55e" }}> security@verifuse.tech</a>.</p>
        </Section>

        <Section title="7. Cookies and Tracking">
          <p>VeriFuse uses:</p>
          <ul>
            <li><strong>localStorage</strong> — JWT auth tokens for session management</li>
            <li><strong>No third-party tracking cookies</strong> — We do not use Google Analytics, Facebook Pixel, or any ad tracking</li>
            <li><strong>No fingerprinting</strong> — We do not build device fingerprints</li>
          </ul>
          <p>Our robots.txt instructs all crawlers to stay off the platform. We use X-Robots-Tag headers to prevent
          indexing of any user data.</p>
        </Section>

        <Section title="8. Your Rights">
          <p>You have the right to:</p>
          <ul>
            <li><strong>Access</strong> — Request a copy of the personal data we hold about you</li>
            <li><strong>Correction</strong> — Update inaccurate account information via your Account settings</li>
            <li><strong>Deletion</strong> — Request deletion of your personal data (subject to legal retention requirements)</li>
            <li><strong>Portability</strong> — Request your data in a machine-readable format</li>
            <li><strong>Objection</strong> — Object to certain processing activities</li>
          </ul>
          <p>To exercise any of these rights, email <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#22c55e" }}>{CONTACT_EMAIL}</a>.
          We will respond within 30 days.</p>
        </Section>

        <Section title="9. Children's Privacy">
          <p>The VeriFuse Service is not directed to individuals under the age of 18. We do not knowingly
          collect personal information from minors. If we become aware that a minor has provided personal
          information, we will delete it promptly.</p>
        </Section>

        <Section title="10. Changes to This Policy">
          <p>We may update this Privacy Policy periodically. Material changes will be communicated by email
          or in-app notice at least 14 days before taking effect. The "Effective" date at the top of this
          page reflects the most recent revision.</p>
        </Section>

        <Section title="11. Contact">
          <p>
            Privacy Officer · {COMPANY}<br />
            <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#22c55e" }}>{CONTACT_EMAIL}</a><br />
            Denver, Colorado
          </p>
        </Section>
      </div>

      <footer style={{ borderTop: "1px solid #1f2937", padding: "24px 32px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.8em", color: "#6b7280" }}>
        <span>© {new Date().getFullYear()} {COMPANY}. All rights reserved.</span>
        <div style={{ display: "flex", gap: 24 }}>
          <Link to="/terms" style={{ color: "#6b7280", textDecoration: "none" }}>Terms</Link>
          <Link to="/privacy" style={{ color: "#6b7280", textDecoration: "none" }}>Privacy</Link>
          <Link to="/" style={{ color: "#6b7280", textDecoration: "none" }}>Home</Link>
        </div>
      </footer>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 36 }}>
      <h2 style={{ fontSize: "0.95em", fontWeight: 700, color: "#f3f4f6", letterSpacing: "0.04em", marginBottom: 14, marginTop: 0 }}>
        {title}
      </h2>
      <div style={{ color: "#9ca3af", fontSize: "0.85em", lineHeight: 1.8 }}>
        {children}
      </div>
    </div>
  );
}
