import { useEffect } from "react";
import { Link } from "react-router-dom";

const EFFECTIVE_DATE   = "June 4, 2025";
const LAST_UPDATED     = "March 11, 2026";
const COMPANY          = "VeriFuse Technologies LLC";
const PRIVACY_EMAIL    = "privacy@verifuse.tech";
const SECURITY_EMAIL   = "security@verifuse.tech";
const LEGAL_EMAIL      = "legal@verifuse.tech";

export default function Privacy() {
  useEffect(() => {
    document.title = "Privacy Policy | VeriFuse";
  }, []);

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0d1117",
      color: "#e5e7eb",
      fontFamily: "'JetBrains Mono', 'Fira Mono', monospace",
    }}>
      {/* Nav */}
      <nav style={{
        borderBottom: "1px solid #1f2937",
        padding: "14px 32px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <Link to="/" style={{ color: "#e5e7eb", textDecoration: "none", fontWeight: 700, fontSize: "0.9em", letterSpacing: "0.08em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>//</span> INTELLIGENCE
        </Link>
        <div style={{ display: "flex", gap: 24, fontSize: "0.8em" }}>
          <Link to="/" style={{ color: "#9ca3af", textDecoration: "none" }}>Home</Link>
          <Link to="/terms" style={{ color: "#9ca3af", textDecoration: "none" }}>Terms of Service</Link>
          <Link to="/login" style={{ color: "#9ca3af", textDecoration: "none" }}>Login</Link>
        </div>
      </nav>

      <div style={{ maxWidth: 820, margin: "0 auto", padding: "48px 32px 80px" }}>

        {/* Page identity */}
        <div style={{ marginBottom: 40 }}>
          <div style={{ fontSize: "0.72em", color: "#22c55e", letterSpacing: "0.12em", marginBottom: 12 }}>LEGAL</div>
          <h1 style={{ fontSize: "2em", fontWeight: 700, margin: "0 0 12px", lineHeight: 1.2 }}>
            Privacy Policy
          </h1>
          <p style={{ color: "#6b7280", fontSize: "0.82em", margin: 0, lineHeight: 1.8 }}>
            <strong style={{ color: "#9ca3af" }}>Effective Date:</strong> {EFFECTIVE_DATE}
            &nbsp;&nbsp;·&nbsp;&nbsp;
            <strong style={{ color: "#9ca3af" }}>Last Updated:</strong> {LAST_UPDATED}
            &nbsp;&nbsp;·&nbsp;&nbsp;
            {COMPANY} · Denver, Colorado
          </p>
        </div>

        {/* Lead summary */}
        <div style={{
          borderLeft: "3px solid #374151",
          paddingLeft: 20,
          marginBottom: 40,
          color: "#9ca3af",
          fontSize: "0.85em",
          lineHeight: 1.8,
        }}>
          {COMPANY} takes data privacy seriously. This policy explains what information we
          collect, how we use it, and your rights regarding it. We do not sell your personal
          information for advertising or marketing purposes, and we do not share it with
          data brokers.
        </div>

        <Section id="p1" title="1. Who This Policy Applies To">
          <p>
            This Privacy Policy applies to all users of the VeriFuse software and data
            intelligence platform ("Service"), including attorneys, law firm staff, authorized
            business users, and anyone else who creates an account or otherwise interacts with
            the Service. By using the Service, you agree to the collection and use of
            information as described in this policy.
          </p>
        </Section>

        <Section id="p2" title="2. Information We Collect">
          <p><strong style={{ color: "#f3f4f6" }}>Account Information</strong></p>
          <ul>
            <li>Name and email address</li>
            <li>Password (stored using a one-way cryptographic hash — never in plaintext)</li>
            <li>Law firm name, bar number, bar state, and firm address (optional — used for
            document generation features)</li>
            <li>Phone number and firm website (optional)</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Billing and Payment Identifiers</strong></p>
          <ul>
            <li>Stripe customer identifier and subscription status</li>
            <li>Subscription tier, billing period, and credit balance</li>
            <li>We do not store payment card numbers, card verification codes, or full
            payment credentials. All payment data is processed and stored by Stripe, Inc.
            under their own{" "}
            <a href="https://stripe.com/privacy" target="_blank" rel="noreferrer" style={{ color: "#22c55e" }}>
              Privacy Policy
            </a>.</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Usage and Log Data</strong></p>
          <ul>
            <li>Actions taken within the platform (leads unlocked, credits consumed, searches performed, documents generated)</li>
            <li>IP address (used for rate limiting, fraud detection, and abuse prevention)</li>
            <li>Browser type and operating system</li>
            <li>API request logs (request method, path, response time, status code)</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>Support and Communications</strong></p>
          <ul>
            <li>Emails or messages you send to us for support, billing, or legal inquiries</li>
          </ul>

          <p><strong style={{ color: "#f3f4f6" }}>User-Generated Case Data</strong></p>
          <ul>
            <li>Case management records, notes, and case outcomes you voluntarily create
            in the attorney workspace</li>
          </ul>
        </Section>

        <Section id="p3" title="3. Public Record Data">
          <p>
            The Service aggregates and analyzes publicly available government records,
            including Colorado public trustee filings, county assessor records, district court
            records, and other public databases. This data does not originate from you — it
            exists in public government sources that VeriFuse accesses as part of the Service.
          </p>
          <p>
            Public record data — including property owner names, property addresses, case
            numbers, and related information — may appear on the platform as part of lead
            records. VeriFuse applies access controls (such as restricting full owner name
            display to authenticated, authorized users) to reduce the risk of misuse.
          </p>
          <p>
            This publicly sourced data is maintained separately from your personal account
            information and is subject to the public-record deletion carve-out described in
            Section 12.
          </p>
        </Section>

        <Section id="p4" title="4. How We Use Your Information">
          <p>We use the information we collect for the following purposes:</p>
          <ul>
            <li><strong>Account administration</strong> — Creating and managing your account, authenticating sessions, and processing credential changes</li>
            <li><strong>Service delivery</strong> — Providing lead data, processing credit transactions, generating documents, and enabling platform features</li>
            <li><strong>Billing</strong> — Processing payments, managing subscriptions, and maintaining billing records</li>
            <li><strong>Security and fraud prevention</strong> — Detecting abuse, enforcing rate limits, maintaining audit logs, and investigating unauthorized activity</li>
            <li><strong>Support</strong> — Responding to your support, billing, and legal inquiries</li>
            <li><strong>Legal compliance</strong> — Complying with lawful subpoenas, court orders, regulatory requests, and our legal obligations</li>
            <li><strong>Product improvement</strong> — Analyzing de-identified and aggregated usage data to improve platform coverage, accuracy, and performance</li>
            <li><strong>Communications</strong> — Sending transactional emails such as email verification, billing receipts, and lead alerts you have opted into</li>
          </ul>
          <p>
            We do not use your data for advertising. We do not share your personal information
            with data brokers or advertising networks.
          </p>
        </Section>

        <Section id="p5" title="5. Service Providers and Subprocessors">
          <p>
            We share personal information with the following categories of service providers
            only as necessary to operate the Service:
          </p>
          <ul>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Stripe, Inc.</strong> — Payment processing.
              Receives billing identifiers, email, and transaction data.
              Governed by Stripe's privacy policy.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Email provider (Twilio SendGrid)</strong> — Transactional email delivery.
              Receives email address and name for email sending. Governed by SendGrid's
              privacy policy.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Cloud infrastructure and hosting providers</strong> — Server
              infrastructure, storage, and networking. Processing may occur in the United States
              or other jurisdictions where providers operate.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Document processing and AI services
              (including Google Cloud Platform)</strong> — Document analysis, optical character
              recognition, and related processing. Document files, excerpts, or metadata
              necessary for processing are transmitted to these providers and may include
              personal or case-related information contained in the documents. Processing is
              governed by our service agreements with each provider and their applicable
              privacy terms.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Logging, monitoring, and security providers</strong> — Operational
              monitoring, error tracking, and security incident detection as applicable.
            </li>
          </ul>
          <p>
            We do not authorize service providers to use your personal information for their
            own marketing or commercial purposes beyond what is necessary to provide services
            to us.
          </p>
        </Section>

        <Section id="p6" title="6. Data Sharing Limitations">
          <p>
            We do not sell, rent, or share your personal information for marketing or
            data-broker purposes. We share personal information outside of service providers
            only in these limited circumstances:
          </p>
          <ul>
            <li>
              <strong>Legal process.</strong>{" "}
              If required to do so by valid court order, subpoena, law enforcement request,
              or other applicable legal obligation.
            </li>
            <li>
              <strong>Protection of rights.</strong>{" "}
              When we reasonably believe disclosure is necessary to protect the rights, property,
              or safety of {COMPANY}, our users, or the public.
            </li>
            <li>
              <strong>Business transfer.</strong>{" "}
              In the event of a merger, acquisition, corporate reorganization, or sale of all or
              substantially all of our assets, your data may be transferred as part of that
              transaction. We will provide notice by email or prominent in-app notice before
              your personal information is transferred and becomes subject to a materially
              different privacy policy.
            </li>
            <li>
              <strong>With your consent.</strong>{" "}
              In any other circumstance with your prior, explicit consent.
            </li>
          </ul>
        </Section>

        <Section id="p7" title="7. Data Retention">
          <ul>
            <li>
              <strong>Active account data</strong> — Retained while your account is active.
              Upon account closure and a written deletion request, personal account data will
              be deleted within 90 days, subject to the exceptions below.
            </li>
            <li>
              <strong>Billing and tax records</strong> — Retained for a minimum of 7 years
              as required by applicable accounting and tax laws.
            </li>
            <li>
              <strong>Audit and security logs</strong> — Retained for up to 2 years for
              security, fraud prevention, and legal compliance purposes.
            </li>
            <li>
              <strong>Request and access logs</strong> — Operational logs are retained for
              30 days and then purged on a rolling basis, unless preserved for an ongoing
              investigation or legal hold.
            </li>
            <li>
              <strong>Retention exceptions.</strong>{" "}
              We may retain personal information beyond the above periods where necessary for:
              legal obligations, fraud prevention, dispute resolution, backup and recovery
              purposes, public-record data integrity, or ongoing security investigations.
            </li>
          </ul>
        </Section>

        <Section id="p8" title="8. Security">
          <p>
            VeriFuse implements commercially reasonable administrative, technical, and physical
            safeguards designed to protect your personal information from unauthorized access,
            disclosure, alteration, and destruction. These safeguards include encryption in
            transit and at rest, access controls based on principle of least privilege,
            role-based access control (RBAC), rate limiting, audit logging, and account
            lockout protections.
          </p>
          <p>
            No security system is impenetrable. We cannot guarantee absolute security of
            information you transmit to us or that we store. In the event of a security
            incident involving your personal information, we will investigate and provide
            notices as required by applicable law.
          </p>
          <p>
            If you discover a potential security vulnerability, please report it responsibly to{" "}
            <a href={`mailto:${SECURITY_EMAIL}`} style={{ color: "#22c55e" }}>{SECURITY_EMAIL}</a>.
          </p>
        </Section>

        <Section id="p9" title="9. Cookies, Local Storage, and Tracking Technologies">
          <p>VeriFuse uses:</p>
          <ul>
            <li>
              <strong>Browser localStorage</strong> — For storing your authentication session
              token after login. This is essential for the Service to function.
            </li>
            <li>
              <strong>Session cookies</strong> — As needed for authentication flow and
              security operations.
            </li>
          </ul>
          <p>
            We do not use third-party advertising trackers, ad pixels, or behavioral profiling
            cookies. We do not sell your browsing data. We do not build advertising profiles
            from your usage of the Service.
          </p>
          <p>
            Our platform may include links to third-party services (such as Stripe's checkout
            flow). Those services operate under their own privacy and cookie policies, which
            we encourage you to review.
          </p>
        </Section>

        <Section id="p10" title="10. Your Rights">
          <p>
            Depending on your jurisdiction and applicable law, you may have the following rights
            regarding your personal information:
          </p>
          <ul>
            <li><strong>Access</strong> — Request a copy of the personal data we hold about you</li>
            <li><strong>Correction</strong> — Update inaccurate or incomplete account information via your Account settings or by contacting us</li>
            <li><strong>Deletion</strong> — Request deletion of your personal data, subject to retention requirements and the public-record carve-out in Section 12</li>
            <li><strong>Portability</strong> — Request your account data in a structured, commonly used format</li>
            <li><strong>Objection</strong> — Object to certain processing activities under applicable law</li>
            <li><strong>De-identified and aggregated data</strong> — We may retain and use de-identified or aggregated data derived from your account after deletion, provided it cannot be reasonably re-identified</li>
          </ul>
          <p>
            To exercise any of these rights, contact us at{" "}
            <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#22c55e" }}>{PRIVACY_EMAIL}</a>.
            We will acknowledge your request within 10 business days and respond within
            30 days, or as required by applicable law.
          </p>
        </Section>

        <Section id="p11" title="11. Public-Record Data — Deletion Carve-Out">
          <p>
            Deletion requests for your personal account data do not require us to remove
            public-record information lawfully obtained from public government sources
            (such as county foreclosure records, assessor records, or court filings) that is
            maintained as part of our platform's data intelligence layer.
          </p>
          <p>
            Such public-record data exists independently of your account and is not personal
            information that you provided to us. It may be retained, processed, and displayed
            as part of the platform's core service, except where removal is required by
            applicable law.
          </p>
        </Section>

        <Section id="p12" title="12. Business Accounts and Firm Controls">
          <p>
            If your account was created or is administered by a law firm or organization
            ("Firm Account"), the firm administrator may have access to account usage data,
            billing data, and platform activity associated with accounts under their
            organization.
          </p>
          <p>
            If you are an individual user accessing the Service through an organization, your
            firm administrator may control your account access and associated data, including
            the ability to modify or remove access. Questions about firm account data
            management should be directed to your firm administrator and to us at{" "}
            <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#22c55e" }}>{PRIVACY_EMAIL}</a>.
          </p>
        </Section>

        <Section id="p13" title="13. International and Cross-Border Processing">
          <p>
            {COMPANY} is based in the United States. Your information may be processed and
            stored in the United States or in other jurisdictions where our service providers
            operate. By using the Service, you consent to the transfer and processing of
            your information in those jurisdictions, which may have different data protection
            laws than your home country.
          </p>
        </Section>

        <Section id="p14" title="14. Children's Privacy">
          <p>
            The Service is not directed to individuals under the age of 18, and we do not
            knowingly collect personal information from minors. If we become aware that we
            have collected personal information from a person under 18 without appropriate
            consent, we will take steps to delete it promptly. If you believe a minor has
            provided personal information, contact us at{" "}
            <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#22c55e" }}>{PRIVACY_EMAIL}</a>.
          </p>
        </Section>

        <Section id="p15" title="15. Changes to This Policy">
          <p>
            We may update this Privacy Policy from time to time to reflect changes in our
            practices, the Service, or applicable law. If we make material changes, we will
            notify you by email or via an in-app notice at least 14 days before those changes
            take effect, unless a shorter timeframe is required by law. The "Last Updated"
            date at the top of this page reflects the most recent revision.
          </p>
          <p>
            Your continued use of the Service after the effective date of the revised policy
            constitutes your acceptance of it. If you do not agree, you must stop using the
            Service.
          </p>
        </Section>

        <Section id="p16" title="16. Contact — Privacy Officer">
          <p>
            For privacy inquiries, data requests, or concerns about this policy:
          </p>
          <p style={{ lineHeight: 2 }}>
            Privacy Officer · {COMPANY}<br />
            Denver, Colorado<br />
            <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#22c55e" }}>{PRIVACY_EMAIL}</a>
            {" "} (privacy and data rights){" · "}
            <a href={`mailto:${SECURITY_EMAIL}`} style={{ color: "#22c55e" }}>{SECURITY_EMAIL}</a>
            {" "} (security disclosures){" · "}
            <a href={`mailto:${LEGAL_EMAIL}`} style={{ color: "#22c55e" }}>{LEGAL_EMAIL}</a>
            {" "} (legal)
          </p>
        </Section>

      </div>

      {/* Footer */}
      <footer style={{
        borderTop: "1px solid #1f2937",
        padding: "24px 32px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 12,
        fontSize: "0.78em",
        color: "#6b7280",
      }}>
        <span>© {new Date().getFullYear()} {COMPANY}. All rights reserved. · Denver, Colorado</span>
        <div style={{ display: "flex", gap: 24 }}>
          <Link to="/terms" style={{ color: "#6b7280", textDecoration: "none" }}>Terms</Link>
          <Link to="/privacy" style={{ color: "#6b7280", textDecoration: "none" }}>Privacy</Link>
          <Link to="/" style={{ color: "#6b7280", textDecoration: "none" }}>Home</Link>
          <Link to="/login" style={{ color: "#6b7280", textDecoration: "none" }}>Login</Link>
        </div>
      </footer>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <div id={id} style={{ marginBottom: 40, scrollMarginTop: 24 }}>
      <h2 style={{
        fontSize: "0.9em",
        fontWeight: 700,
        color: "#f3f4f6",
        letterSpacing: "0.04em",
        marginBottom: 14,
        marginTop: 0,
        borderBottom: "1px solid #1f2937",
        paddingBottom: 10,
      }}>
        {title}
      </h2>
      <div style={{ color: "#9ca3af", fontSize: "0.85em", lineHeight: 1.9 }}>
        {children}
      </div>
    </div>
  );
}
