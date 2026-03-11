import { Link } from "react-router-dom";

const EFFECTIVE_DATE = "June 4, 2025";
const COMPANY = "VeriFuse Technologies LLC";
const CONTACT_EMAIL = "legal@verifuse.tech";

export default function Terms() {
  return (
    <div style={{ minHeight: "100vh", background: "#0d1117", color: "#e5e7eb", fontFamily: "'JetBrains Mono', 'Fira Mono', monospace" }}>
      {/* Nav */}
      <nav style={{ borderBottom: "1px solid #1f2937", padding: "14px 32px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Link to="/" style={{ color: "#e5e7eb", textDecoration: "none", fontWeight: 700, fontSize: "0.9em", letterSpacing: "0.08em" }}>
          VERIFUSE <span style={{ color: "#22c55e" }}>//</span> INTELLIGENCE
        </Link>
        <div style={{ display: "flex", gap: 24, fontSize: "0.8em" }}>
          <Link to="/privacy" style={{ color: "#9ca3af", textDecoration: "none" }}>Privacy Policy</Link>
          <Link to="/login" style={{ color: "#9ca3af", textDecoration: "none" }}>Login</Link>
        </div>
      </nav>

      <div style={{ maxWidth: 820, margin: "0 auto", padding: "48px 32px 80px" }}>
        <div style={{ marginBottom: 40 }}>
          <div style={{ fontSize: "0.75em", color: "#22c55e", letterSpacing: "0.1em", marginBottom: 12 }}>LEGAL</div>
          <h1 style={{ fontSize: "2em", fontWeight: 700, margin: "0 0 12px", lineHeight: 1.2 }}>Terms of Service</h1>
          <p style={{ color: "#6b7280", fontSize: "0.85em", margin: 0 }}>
            Effective: {EFFECTIVE_DATE} &nbsp;·&nbsp; {COMPANY}
          </p>
        </div>

        <div style={{ borderLeft: "3px solid #1f2937", paddingLeft: 20, marginBottom: 40, color: "#9ca3af", fontSize: "0.85em", lineHeight: 1.7 }}>
          <strong style={{ color: "#f59e0b" }}>IMPORTANT:</strong> VeriFuse is a data intelligence platform, not a law firm. Nothing on this platform
          constitutes legal advice. All surplus fund recovery actions must be taken by a licensed attorney acting in
          compliance with C.R.S. § 38-38-111, § 38-13-1304, and HB25-1224.
        </div>

        <Section title="1. Acceptance of Terms">
          <p>By accessing or using the VeriFuse platform ("Service"), you agree to be bound by these Terms of Service ("Terms").
          If you are using the Service on behalf of a law firm or other organization, you represent that you have authority to
          bind that entity to these Terms. If you do not agree, do not use the Service.</p>
        </Section>

        <Section title="2. Description of Service">
          <p>VeriFuse aggregates and analyzes publicly available Colorado county foreclosure records to identify potential
          surplus funds that may be owed to former property owners after a public trustee sale. The Service provides:</p>
          <ul>
            <li>Automated identification and grading of surplus fund leads</li>
            <li>Mathematical verification of overbid amounts from public trustee records</li>
            <li>Document generation tools (motion templates, notices, affidavits)</li>
            <li>County coverage data and pipeline analytics</li>
            <li>Case management tools for attorneys</li>
          </ul>
          <p>VeriFuse does not recover funds, does not contact property owners on your behalf, and does not claim any legal
          or equitable interest in any surplus funds.</p>
        </Section>

        <Section title="3. Eligibility and Account Registration">
          <p>You must be at least 18 years old and a licensed legal professional (attorney, paralegal, or law firm employee)
          to access paid features. You agree to provide accurate information when creating an account, including your Colorado
          Bar number if applicable. VeriFuse reserves the right to verify credentials and terminate accounts that provide
          false information.</p>
          <p>You are responsible for maintaining the confidentiality of your login credentials and for all activity
          conducted under your account.</p>
        </Section>

        <Section title="4. Credits, Billing, and Refunds">
          <p>Access to lead details requires purchasing credits. Credits are sold in subscription tiers (Investigator,
          Partner, Enterprise) and as one-time packs. Unused credits roll over for 30 days from the billing date up to
          a maximum bank of 3× your monthly allotment.</p>
          <ul>
            <li><strong>Subscriptions</strong> are billed monthly or annually through Stripe. Cancellation takes effect
            at the end of the current billing period; no partial refunds are issued for unused time.</li>
            <li><strong>Credit packs</strong> are non-refundable once purchased.</li>
            <li><strong>Founding member pricing</strong> is locked as long as your subscription remains active without
            a lapse of more than 30 days.</li>
          </ul>
          <p>All billing is handled by Stripe. VeriFuse does not store payment card information.</p>
        </Section>

        <Section title="5. Authorized Use">
          <p>You may use the Service only for lawful purposes and in accordance with these Terms. You agree that you will:</p>
          <ul>
            <li>Use lead data exclusively in connection with legitimate legal representation of surplus fund claimants</li>
            <li>Comply with C.R.S. § 38-38-111(5) — the 6-month post-sale contact restriction</li>
            <li>Comply with the 10% maximum finder fee cap under C.R.S. § 38-13-1304(1)(b)(IV) as amended by HB25-1224
            (effective June 4, 2025)</li>
            <li>Not share, resell, republish, or sublicense any data obtained through the Service</li>
            <li>Not use automated tools (bots, scrapers, crawlers) to extract data from the Service</li>
            <li>Not attempt to reverse-engineer, decompile, or access backend systems</li>
            <li>Not use the Service to harass, deceive, or fraudulently contact property owners</li>
          </ul>
        </Section>

        <Section title="6. Colorado Legal Compliance">
          <p>You acknowledge that Colorado law governs the recovery of surplus funds from foreclosure sales. Key statutes include:</p>
          <ul>
            <li><strong>C.R.S. § 38-38-111</strong> — Governs overbid surplus distribution from public trustee sales.
            A 6-month holding period applies after the sale date before a finder agreement can be lawfully executed.</li>
            <li><strong>C.R.S. § 38-13-1304 (HB25-1224)</strong> — Caps finder fees at 10% of the amount recovered.
            Effective June 4, 2025.</li>
            <li><strong>C.R.S. § 38-13-101 et seq.</strong> — Governs unclaimed property turnover to the Colorado
            State Treasurer.</li>
          </ul>
          <p>VeriFuse provides statutory references as informational context only. You are solely responsible for
          ensuring your activities comply with all applicable laws. Consult a licensed Colorado attorney for legal guidance.</p>
        </Section>

        <Section title="7. Data Accuracy Disclaimer">
          <p>Lead data is sourced from public county records and is provided for informational and research purposes only.
          VeriFuse makes no warranty that any data is complete, accurate, or current. Surplus amounts shown are estimates
          derived from publicly available records and may differ from actual court-determined amounts.</p>
          <p>A "GOLD" grade or "TRIPLE VERIFIED" status indicates a high degree of mathematical confidence based on
          automated analysis — it is not a guarantee of collectability, legal standing, or case outcome.</p>
        </Section>

        <Section title="8. Intellectual Property">
          <p>The VeriFuse platform, including its software, algorithms, scoring models, verification engines, and
          user interface, is the exclusive intellectual property of {COMPANY}. You are granted a limited,
          non-exclusive, non-transferable license to use the Service during your subscription period.</p>
          <p>Lead data derived from public county records is not copyrightable by VeriFuse; however, our selection,
          arrangement, enrichment, and presentation of that data constitutes protectable compilation under 17 U.S.C. § 101.</p>
        </Section>

        <Section title="9. Limitation of Liability">
          <p>TO THE MAXIMUM EXTENT PERMITTED BY LAW, VERIFUSE AND ITS OFFICERS, EMPLOYEES, AND AFFILIATES SHALL NOT
          BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOST PROFITS,
          ARISING OUT OF OR IN CONNECTION WITH YOUR USE OF THE SERVICE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.</p>
          <p>OUR TOTAL LIABILITY FOR ANY CLAIM ARISING UNDER THESE TERMS SHALL NOT EXCEED THE AMOUNT PAID BY YOU TO
          VERIFUSE IN THE THREE MONTHS PRECEDING THE CLAIM.</p>
        </Section>

        <Section title="10. Indemnification">
          <p>You agree to indemnify, defend, and hold harmless {COMPANY} and its officers, directors, employees, and
          agents from any claims, liabilities, damages, judgments, costs, or expenses (including reasonable attorneys'
          fees) arising out of or relating to: (a) your use of the Service; (b) your violation of these Terms;
          (c) your violation of any applicable law; or (d) your interaction with any surplus fund claimant or
          property owner.</p>
        </Section>

        <Section title="11. Termination">
          <p>VeriFuse reserves the right to suspend or terminate your account, with or without notice, for any violation
          of these Terms, suspected fraudulent activity, or abuse of the platform. Upon termination, your right to access
          the Service ceases immediately. Unused credits are non-refundable upon termination for cause.</p>
        </Section>

        <Section title="12. Modifications to Terms">
          <p>We may update these Terms periodically. If we make material changes, we will notify you by email or via an
          in-app notice at least 14 days before the changes take effect. Your continued use of the Service after the
          effective date constitutes acceptance of the revised Terms.</p>
        </Section>

        <Section title="13. Governing Law and Dispute Resolution">
          <p>These Terms are governed by the laws of the State of Colorado, without regard to conflict-of-law principles.
          Any dispute arising under these Terms shall be resolved exclusively in the state or federal courts located in
          Denver, Colorado. You waive any objection to personal jurisdiction or venue in such courts.</p>
        </Section>

        <Section title="14. Entire Agreement">
          <p>These Terms, together with our <Link to="/privacy" style={{ color: "#22c55e" }}>Privacy Policy</Link>,
          constitute the entire agreement between you and {COMPANY} regarding the Service and supersede all prior
          agreements or understandings.</p>
        </Section>

        <Section title="15. Contact">
          <p>Questions about these Terms? Contact us at <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#22c55e" }}>{CONTACT_EMAIL}</a>.</p>
          <p style={{ color: "#6b7280", fontSize: "0.85em" }}>{COMPANY} · Denver, Colorado</p>
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
