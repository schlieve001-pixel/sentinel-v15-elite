import { useEffect } from "react";
import { Link } from "react-router-dom";

const EFFECTIVE_DATE = "June 4, 2025";
const LAST_UPDATED   = "March 11, 2026";
const COMPANY        = "VeriFuse Technologies LLC";
const LEGAL_EMAIL    = "support@verifuse.tech";
const PRIVACY_EMAIL  = "support@verifuse.tech";

export default function Terms() {
  useEffect(() => {
    document.title = "Terms of Service | VeriFuse";
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
          <Link to="/privacy" style={{ color: "#9ca3af", textDecoration: "none" }}>Privacy Policy</Link>
          <Link to="/login" style={{ color: "#9ca3af", textDecoration: "none" }}>Login</Link>
        </div>
      </nav>

      <div style={{ maxWidth: 820, margin: "0 auto", padding: "48px 32px 80px" }}>

        {/* Page identity */}
        <div style={{ marginBottom: 40 }}>
          <div style={{ fontSize: "0.72em", color: "#22c55e", letterSpacing: "0.12em", marginBottom: 12 }}>LEGAL</div>
          <h1 style={{ fontSize: "2em", fontWeight: 700, margin: "0 0 12px", lineHeight: 1.2 }}>
            Terms of Service
          </h1>
          <p style={{ color: "#6b7280", fontSize: "0.82em", margin: 0, lineHeight: 1.8 }}>
            <strong style={{ color: "#9ca3af" }}>Effective Date:</strong> {EFFECTIVE_DATE}
            &nbsp;&nbsp;·&nbsp;&nbsp;
            <strong style={{ color: "#9ca3af" }}>Last Updated:</strong> {LAST_UPDATED}
            &nbsp;&nbsp;·&nbsp;&nbsp;
            {COMPANY} · Denver, Colorado
          </p>
        </div>

        {/* Lead disclaimer callout */}
        <div style={{
          borderLeft: "3px solid #374151",
          paddingLeft: 20,
          marginBottom: 40,
          color: "#9ca3af",
          fontSize: "0.85em",
          lineHeight: 1.8,
        }}>
          <strong style={{ color: "#f59e0b" }}>IMPORTANT:</strong>{" "}
          VeriFuse is a software and data intelligence platform, not a law firm.
          Use of this Service does not create an attorney-client relationship and does not
          constitute legal advice. All legal actions must be taken by a licensed attorney
          acting in accordance with applicable law. Users are solely responsible for
          ensuring their activities comply with all applicable federal, state, and local laws.
        </div>

        <Section id="s1" title="1. Acceptance of Terms">
          <p>
            By accessing or using the VeriFuse platform ("Service"), you agree to be bound by
            these Terms of Service ("Terms") and our{" "}
            <Link to="/privacy" style={{ color: "#22c55e" }}>Privacy Policy</Link>, which is
            incorporated by reference. If you are using the Service on behalf of a law firm or
            other organization, you represent that you have the authority to bind that entity to
            these Terms. If you do not agree to these Terms, you must not use the Service.
          </p>
          <p>
            These Terms constitute a legally binding agreement between you and {COMPANY}.
          </p>
        </Section>

        <Section id="s2" title="2. Eligibility and Authorized Users">
          <p>
            You must be at least 18 years old to use the Service. The Service is intended for
            use by:
          </p>
          <ul>
            <li>Licensed attorneys and law firms</li>
            <li>Paralegals and authorized law firm staff</li>
            <li>Other approved business users operating under the supervision of a licensed attorney
            or with appropriate authorization</li>
          </ul>
          <p>
            By registering, you represent that you meet these eligibility requirements. VeriFuse
            reserves the right to verify credentials and to suspend or terminate accounts that
            do not qualify or that provide false or misleading information during registration.
          </p>
        </Section>

        <Section id="s3" title="3. Description of Service">
          <p>
            VeriFuse is a software and data intelligence platform. The Service aggregates and
            analyzes publicly available Colorado county records — including public trustee
            filings, assessor records, and court records — to help attorneys and authorized
            users identify and research potential surplus fund opportunities. The Service
            provides:
          </p>
          <ul>
            <li>Data retrieval, organization, and classification of publicly available county records</li>
            <li>Proprietary grading and confidence indicators based on automated analysis</li>
            <li>Document drafting aid tools (template-based motion forms, notices, and affidavits)</li>
            <li>County pipeline analytics and coverage data</li>
            <li>Case management and workflow tracking tools for attorneys</li>
          </ul>
          <p>
            <strong style={{ color: "#f3f4f6" }}>What VeriFuse is not and does not do:</strong>
          </p>
          <ul>
            <li>VeriFuse is not a law firm and does not provide legal advice or legal services.</li>
            <li>VeriFuse does not recover surplus funds on behalf of any person or entity.</li>
            <li>VeriFuse does not contact property owners, claimants, or any third party on behalf of users.</li>
            <li>VeriFuse does not guarantee the accuracy, completeness, or timeliness of any data.</li>
            <li>VeriFuse does not claim any legal or equitable interest in any surplus funds.</li>
          </ul>
        </Section>

        <Section id="s4" title="4. Accounts and Credentials">
          <p>
            You agree to provide accurate, current, and complete information when creating
            an account and to keep that information updated. You are responsible for:
          </p>
          <ul>
            <li>Maintaining the confidentiality of your login credentials</li>
            <li>All activity that occurs under your account</li>
            <li>Promptly notifying us at <a href={`mailto:${LEGAL_EMAIL}`} style={{ color: "#22c55e" }}>{LEGAL_EMAIL}</a> if
            you suspect unauthorized access to your account</li>
          </ul>
          <p>
            Account credentials are personal to the registered user. You may not share your
            account with any person not authorized under your subscription plan. VeriFuse
            reserves the right to terminate accounts that are shared in violation of these Terms.
          </p>
        </Section>

        <Section id="s5" title="5. Billing, Subscriptions, and Credits">
          <p>
            Access to lead details and premium features requires purchasing credits, available
            through monthly or annual subscription plans (Investigator, Partner, Enterprise) or
            one-time credit packs.
          </p>
          <ul>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Payment processing.</strong>{" "}
              All payments are processed by Stripe, Inc. VeriFuse does not store payment card
              numbers or full payment credentials. Payment data is handled by Stripe under their
              own privacy policy and security standards.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Recurring billing.</strong>{" "}
              By subscribing, you authorize VeriFuse to charge your payment method on a recurring
              basis (monthly or annual) until you cancel. Cancellation takes effect at the end of
              the current billing period; no partial refunds are issued for unused subscription time
              unless required by applicable law.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Credit rollover.</strong>{" "}
              Unused credits roll over within your plan's rollover window (varies by tier). Credits
              that exceed the maximum banked amount or that expire after the rollover window are
              forfeited.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Credit packs.</strong>{" "}
              One-time credit packs are non-refundable once delivered or used.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Failed payments.</strong>{" "}
              If a payment fails, VeriFuse may suspend or downgrade your account until payment
              is resolved. VeriFuse is not liable for any loss of access resulting from a
              failed payment.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Taxes.</strong>{" "}
              Stated prices exclude applicable taxes unless expressly noted. You are responsible
              for any taxes applicable to your purchase.
            </li>
            <li>
              <strong style={{ color: "#f3f4f6" }}>Founding and promotional pricing.</strong>{" "}
              Any founding member or promotional pricing is personal to the subscribing account,
              non-transferable, and contingent on maintaining an active subscription without
              a qualifying lapse. VeriFuse reserves the right to define what constitutes a
              qualifying lapse.
            </li>
          </ul>
        </Section>

        <Section id="s6" title="6. Permitted Use and Prohibited Conduct">
          <p>
            You may use the Service only for lawful purposes consistent with these Terms and
            applicable law. Without limiting the foregoing, you agree that you will not:
          </p>
          <ul>
            <li>Use automated bots, scrapers, crawlers, or similar tools to extract data from the Service</li>
            <li>Resell, sublicense, republish, or redistribute any data obtained through the Service</li>
            <li>Reverse engineer, decompile, disassemble, or attempt to access the source code
            or backend systems of the Service</li>
            <li>Use the Service to harass, deceive, defraud, or illegally contact any person</li>
            <li>Attempt to gain unauthorized access to any portion of the Service or any
            related systems</li>
            <li>Use the Service in any manner that violates applicable federal, state, or local law</li>
            <li>Impersonate any person or entity or misrepresent your affiliation with any person
            or entity</li>
            <li>Interfere with or disrupt the integrity or performance of the Service</li>
          </ul>
          <p>
            VeriFuse reserves the right to investigate suspected violations and to take any
            action it deems appropriate, including account suspension or termination.
          </p>
        </Section>

        <Section id="s7" title="7. No Legal Advice — No Attorney-Client Relationship">
          <p>
            <strong style={{ color: "#f59e0b" }}>
              Nothing in the Service constitutes legal advice, and no use of the Service
              creates an attorney-client relationship between you and VeriFuse Technologies LLC.
            </strong>
          </p>
          <p>
            VeriFuse is not a law firm. VeriFuse's officers, employees, and contractors are not
            acting as your attorneys. Data, grades, confidence indicators, and analytical outputs
            provided by the Service are informational tools only — they do not constitute legal
            opinions, legal conclusions, or legal strategy.
          </p>
          <p>
            You should consult a licensed attorney regarding any legal matter, including the
            interpretation or applicability of any statutes referenced in connection with the
            Service. You are solely responsible for all legal actions taken in reliance on
            information obtained through the Service.
          </p>
        </Section>

        <Section id="s8" title="8. Document Templates and Drafting Aids">
          <p>
            The Service may generate template documents, including draft motions, notices,
            affidavits, certificates of service, and related materials. These documents are
            drafting aids only.
          </p>
          <ul>
            <li>All generated documents must be independently reviewed, completed, and verified
            by a licensed attorney before filing or use in any legal proceeding.</li>
            <li>Generated documents may contain placeholder fields, default language, or
            incomplete information that requires attorney review and completion.</li>
            <li>VeriFuse makes no representation that any generated document is accurate,
            complete, legally sufficient, or appropriate for any specific jurisdiction, court,
            or proceeding.</li>
            <li>VeriFuse is not responsible for the outcome of any legal proceeding in which
            a generated document is used.</li>
          </ul>
        </Section>

        <Section id="s9" title="9. Public Records and Third-Party Data">
          <p>
            Lead data is derived from publicly available government sources, including Colorado
            public trustee filings, county assessor records, district court records, and related
            public databases. This data originates from third-party government sources and is
            subject to the following limitations:
          </p>
          <ul>
            <li>County and court records may be incomplete, delayed, unavailable, or inaccurate.</li>
            <li>Data may not reflect the most current status of any case or property.</li>
            <li>Third-party data providers and government sources may change their systems,
            formats, or availability without notice.</li>
            <li>VeriFuse cannot guarantee uninterrupted access to any county or court data source.</li>
          </ul>
          <p>
            You acknowledge these limitations and agree not to rely solely on VeriFuse data
            without independent verification from authoritative sources.
          </p>
        </Section>

        <Section id="s10" title="10. Data Accuracy and Confidence Indicators">
          <p>
            VeriFuse assigns proprietary confidence indicators and grades (including but not
            limited to designations such as GOLD, SILVER, BRONZE, or similar labels) to leads
            based on automated analysis of publicly available records.
          </p>
          <p>
            <strong style={{ color: "#f59e0b" }}>These designations are proprietary internal
            classifications only.</strong> They do not constitute:
          </p>
          <ul>
            <li>A guarantee of the accuracy or completeness of any underlying data</li>
            <li>A representation that any surplus funds exist or are collectible</li>
            <li>A legal opinion regarding the standing, viability, or outcome of any claim</li>
            <li>A certification by any government authority or court</li>
          </ul>
          <p>
            All data is provided for informational and research purposes only. Users are solely
            responsible for independently verifying any information before taking legal action.
          </p>
        </Section>

        <Section id="s11" title="11. Colorado Statutory References — Informational Only">
          <p>
            The Service may reference Colorado statutes, including C.R.S. § 38-38-111,
            C.R.S. § 38-13-1304, C.R.S. § 39-11-151, and related laws, as informational context
            to help users understand the general legal landscape of surplus fund recovery in
            Colorado. These references are provided for informational purposes only.
          </p>
          <p>
            VeriFuse does not interpret, summarize, or apply these statutes to any specific
            situation. Statutory language, interpretations, and applicability may change. Users
            are solely responsible for ensuring that their activities comply with all applicable
            federal, state, and local laws. Consult qualified legal counsel for advice specific
            to your circumstances.
          </p>
        </Section>

        <Section id="s12" title="12. Intellectual Property">
          <p>
            The VeriFuse platform, including its software, algorithms, scoring models, grading
            systems, user interface, and documentation, is the exclusive intellectual property
            of {COMPANY} and its licensors. You are granted a limited, non-exclusive,
            non-transferable, revocable license to access and use the Service during your
            active subscription period, solely in accordance with these Terms.
          </p>
          <p>
            Lead data derived from public county records is not copyrightable by VeriFuse;
            however, our selection, arrangement, enrichment, and presentation of that data
            constitutes protectable compilation under applicable copyright law. You may not
            extract, copy, or reproduce our compilations beyond individual permitted use.
          </p>
          <p>
            Nothing in these Terms grants you ownership of any intellectual property of
            {COMPANY}. All rights not expressly granted are reserved.
          </p>
        </Section>

        <Section id="s13" title="13. Suspension and Termination">
          <p>
            VeriFuse reserves the right to suspend or terminate your account at any time, with
            or without notice, for:
          </p>
          <ul>
            <li>Violation of these Terms or our Privacy Policy</li>
            <li>Suspected fraudulent activity, abuse, or unauthorized use of the platform</li>
            <li>Non-payment or failed billing</li>
            <li>Any reason VeriFuse determines in its reasonable discretion</li>
          </ul>
          <p>
            Upon termination, your right to access the Service ceases immediately. Unused
            credits are non-refundable upon termination for cause. VeriFuse is not liable to
            you or any third party for any consequences of account suspension or termination.
          </p>
        </Section>

        <Section id="s14" title="14. Disclaimer of Warranties">
          <p>
            THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTY OF ANY KIND.
            TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, {COMPANY.toUpperCase()} EXPRESSLY
            DISCLAIMS ALL WARRANTIES, WHETHER EXPRESS, IMPLIED, STATUTORY, OR OTHERWISE,
            INCLUDING ANY WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE,
            TITLE, AND NON-INFRINGEMENT.
          </p>
          <p>
            VERIFUSE DOES NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE,
            OR FREE OF VIRUSES OR OTHER HARMFUL COMPONENTS, OR THAT ANY DATA WILL BE ACCURATE,
            COMPLETE, OR CURRENT.
          </p>
        </Section>

        <Section id="s15" title="15. Limitation of Liability">
          <p>
            TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, {COMPANY.toUpperCase()} AND ITS
            OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, AND AFFILIATES SHALL NOT BE LIABLE FOR
            ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, PUNITIVE, OR EXEMPLARY DAMAGES,
            INCLUDING LOST PROFITS, LOST REVENUE, LOSS OF DATA, LOSS OF GOODWILL, OR BUSINESS
            INTERRUPTION, ARISING OUT OF OR RELATING TO YOUR USE OF OR INABILITY TO USE THE
            SERVICE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
          </p>
          <p>
            OUR TOTAL AGGREGATE LIABILITY TO YOU FOR ALL CLAIMS ARISING UNDER THESE TERMS
            SHALL NOT EXCEED THE TOTAL AMOUNT PAID BY YOU TO VERIFUSE IN THE THREE (3) MONTHS
            IMMEDIATELY PRECEDING THE CLAIM.
          </p>
          <p>
            Some jurisdictions do not allow the exclusion or limitation of certain damages.
            In such jurisdictions, our liability is limited to the maximum extent permitted by law.
          </p>
        </Section>

        <Section id="s16" title="16. Indemnification">
          <p>
            You agree to indemnify, defend, and hold harmless {COMPANY} and its officers,
            directors, employees, agents, and affiliates from and against any and all claims,
            liabilities, damages, judgments, losses, costs, and expenses (including reasonable
            attorneys' fees) arising out of or relating to:
          </p>
          <ul>
            <li>Your access to or use of the Service</li>
            <li>Your violation of these Terms</li>
            <li>Your violation of any applicable law or regulation</li>
            <li>Your interaction with any surplus fund claimant, property owner, or third party
            in connection with information obtained through the Service</li>
            <li>Any legal proceeding in which you use documents generated by the Service</li>
          </ul>
        </Section>

        <Section id="s17" title="17. Force Majeure">
          <p>
            VeriFuse shall not be liable for any failure or delay in performance caused by
            circumstances beyond its reasonable control, including but not limited to: acts of
            God, natural disasters, war, terrorism, civil unrest, government action, changes in
            law or regulation, labor disputes, internet or telecommunications outages, failure
            of third-party service providers, or cyberattacks. During such events, VeriFuse's
            obligations under these Terms are suspended to the extent reasonably necessary.
          </p>
        </Section>

        <Section id="s18" title="18. Assignment">
          <p>
            You may not assign or transfer your rights or obligations under these Terms,
            by operation of law or otherwise, without VeriFuse's prior written consent. Any
            attempted assignment without consent is void. VeriFuse may freely assign these
            Terms in connection with a merger, acquisition, corporate reorganization, or
            sale of all or substantially all of its assets.
          </p>
        </Section>

        <Section id="s19" title="19. Survival">
          <p>
            The following sections survive any expiration or termination of these Terms:
            Section 7 (No Legal Advice), Section 8 (Document Templates), Section 10 (Data
            Accuracy), Section 12 (Intellectual Property), Section 14 (Disclaimer of
            Warranties), Section 15 (Limitation of Liability), Section 16 (Indemnification),
            Section 20 (Governing Law), and any other provision that by its nature should
            survive termination.
          </p>
        </Section>

        <Section id="s20" title="20. Modifications to These Terms">
          <p>
            VeriFuse may update these Terms from time to time. If we make material changes, we
            will notify you by email or via an in-app notice at least 14 days before the changes
            take effect, unless changes are required by law on a shorter timeline. The "Last
            Updated" date at the top of this page reflects the most recent revision.
          </p>
          <p>
            Your continued use of the Service after the effective date of revised Terms
            constitutes your acceptance of those Terms. If you do not agree to revised Terms,
            you must stop using the Service before the effective date.
          </p>
        </Section>

        <Section id="s21" title="21. Governing Law and Venue">
          <p>
            These Terms are governed by and construed in accordance with the laws of the State
            of Colorado, without regard to its conflict-of-law principles. Any dispute arising
            out of or relating to these Terms or the Service shall be resolved exclusively in
            the state or federal courts located in Denver, Colorado.
          </p>
          <p>
            You irrevocably consent to personal jurisdiction and venue in such courts and waive
            any objection that such courts are an inconvenient forum.
          </p>
        </Section>

        <Section id="s22" title="22. Entire Agreement and Severability">
          <p>
            These Terms, together with our{" "}
            <Link to="/privacy" style={{ color: "#22c55e" }}>Privacy Policy</Link>, constitute
            the entire agreement between you and {COMPANY} regarding the Service and supersede
            all prior and contemporaneous agreements, representations, and understandings.
          </p>
          <p>
            If any provision of these Terms is found to be invalid or unenforceable, that
            provision shall be modified to the minimum extent necessary to make it enforceable,
            and the remaining provisions shall continue in full force and effect.
          </p>
        </Section>

        <Section id="s23" title="23. Contact">
          <p>
            Questions about these Terms? Contact us:
          </p>
          <p style={{ lineHeight: 2 }}>
            {COMPANY}<br />
            Denver, Colorado<br />
            <a href={`mailto:${LEGAL_EMAIL}`} style={{ color: "#22c55e" }}>{LEGAL_EMAIL}</a>
            {" "} (legal inquiries){" · "}
            <a href={`mailto:${PRIVACY_EMAIL}`} style={{ color: "#22c55e" }}>{PRIVACY_EMAIL}</a>
            {" "} (privacy inquiries)
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
