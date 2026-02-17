import { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { getLeadDetail, unlockLead, unlockRestrictedLead, downloadSecure, generateLetter, type Lead, type UnlockResponse, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

function fmt(n: number | null | undefined): string {
  if (n == null) return "\u2014";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LeadDetail() {
  const { assetId } = useParams<{ assetId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [lead, setLead] = useState<Lead | null>(null);
  const [unlocked, setUnlocked] = useState<UnlockResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!assetId) return;
    getLeadDetail(assetId)
      .then(setLead)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [assetId]);

  async function handleUnlock() {
    if (!assetId) return;
    if (!user) {
      navigate("/login");
      return;
    }
    setUnlocking(true);
    setError("");
    try {
      const res = await unlockLead(assetId);
      setUnlocked(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unlock failed");
    } finally {
      setUnlocking(false);
    }
  }

  if (loading) {
    return (
      <div className="detail-page">
        <div className="center-content">
          <div className="loader-ring"></div>
          <p className="processing-text">LOADING ASSET...</p>
        </div>
      </div>
    );
  }

  if (error && !lead) {
    return (
      <div className="detail-page">
        <div className="center-content">
          <p className="auth-error">{error}</p>
          <Link to="/dashboard" className="btn-outline" style={{ marginTop: 20 }}>
            BACK TO DASHBOARD
          </Link>
        </div>
      </div>
    );
  }

  const isRestricted = lead?.restriction_status === "RESTRICTED";
  const isExpired = lead?.deadline_passed === true || lead?.restriction_status === ("EXPIRED" as any);

  return (
    <div className="detail-page">
      <header className="dash-header">
        <Link to="/dashboard" className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-status">
          <span className="blink-dot">●</span>
          ASSET DETAIL
        </div>
      </header>

      <div className="detail-container">
        <Link to="/dashboard" className="back-link">&larr; Back to Dashboard</Link>

        {lead && (
          <div className="detail-card">
            <div className="detail-header">
              <div>
                <span className="county-badge">{lead.county}</span>
                <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`} style={{ marginLeft: 8 }}>
                  {lead.data_grade}
                </span>
                {!lead.surplus_verified && (
                  <span className="unverified-badge" style={{ marginLeft: 8 }}>UNVERIFIED</span>
                )}
                {(lead as any).attorney_packet_ready === 1 && (
                  <span className="grade-badge grade-gold" style={{ marginLeft: 8 }}>
                    ATTORNEY READY
                  </span>
                )}
              </div>
              {isRestricted ? (
                <span className="restriction-badge">
                  RESTRICTED — {lead.days_until_actionable} DAYS
                </span>
              ) : lead.days_to_claim != null ? (
                <span className={`timer-badge ${lead.days_to_claim < 60 ? "urgent" : ""} ${lead.deadline_passed ? "expired" : ""}`}>
                  {lead.deadline_passed
                    ? "DEADLINE PASSED"
                    : `${lead.days_to_claim} DAYS TO CLAIM`}
                </span>
              ) : null}
            </div>

            <h2 className="detail-value">{fmt(lead.estimated_surplus)}</h2>
            <p className="detail-case">Case: {lead.case_number || lead.asset_id}</p>

            {/* C.R.S. § 38-38-111 RESTRICTION NOTICE */}
            {isRestricted && (
              <div className="restriction-banner">
                <strong>C.R.S. § 38-38-111 RESTRICTION ACTIVE</strong>
                <p>
                  Compensation agreements are <strong>VOID AND UNENFORCEABLE</strong> while
                  funds are held by the Public Trustee (first 6 months after sale).
                </p>
                <p>
                  Restriction lifts: <strong>{lead.restriction_end_date}</strong>
                  {lead.days_until_actionable != null && (
                    <span> ({lead.days_until_actionable} days remaining)</span>
                  )}
                </p>
                <p style={{ marginTop: 8, fontSize: "0.85em", opacity: 0.8 }}>
                  After restriction ends, funds transfer to the State Treasurer.
                  Finder fee blackout continues for 2 additional years (C.R.S. § 38-13-1304).
                  Attorney-client agreements are exempt per C.R.S. § 38-13-1302(5).
                </p>
              </div>
            )}

            {/* 180-DAY CLAIM DEADLINE */}
            {!isRestricted && lead.claim_deadline && (
              <div className={`deadline-banner ${lead.deadline_passed ? "passed" : lead.days_to_claim != null && lead.days_to_claim < 60 ? "urgent" : ""}`}>
                <strong>C.R.S. § 38-38-111 CLAIM DEADLINE:</strong>{" "}
                {lead.claim_deadline}
                {lead.days_to_claim != null && !lead.deadline_passed && (
                  <span> — {lead.days_to_claim} days remaining</span>
                )}
                {lead.deadline_passed && (
                  <span> — EXPIRED. Funds may have escheated to the state.</span>
                )}
              </div>
            )}

            <div className="detail-grid">
              <div className="detail-field">
                <label>Location</label>
                <span>{lead.address_hint || lead.county + ", CO"}</span>
              </div>
              <div className="detail-field">
                <label>Sale Date</label>
                <span>{lead.sale_date || "\u2014"}</span>
              </div>
              <div className="detail-field">
                <label>Restriction Status</label>
                <span style={{
                  color: isRestricted ? "#ef4444" : isExpired ? "#6b7280" : "#22c55e",
                  fontWeight: 600,
                }}>
                  {isRestricted ? "DATA ACCESS ONLY" : isExpired ? "EXPIRED" : "ESCROW ENDED"}
                </span>
              </div>
              <div className="detail-field">
                <label>Confidence</label>
                <span>{Math.round((lead.confidence_score || 0) * 100)}%</span>
              </div>
            </div>

            {/* Obfuscated Owner */}
            {!unlocked && (
              <div className="detail-locked">
                <h3>OWNER INTELLIGENCE — LOCKED</h3>
                {lead.owner_img ? (
                  <div className="owner-img-wrap lg">
                    <img src={lead.owner_img} alt="Owner (obfuscated)" />
                    <div className="blur-overlay"></div>
                  </div>
                ) : (
                  <div className="redacted-field">
                    CONFIDENTIAL OWNER DATA RESTRICTED
                  </div>
                )}

                <div className="unlock-actions">
                  <button
                    className="btn-outline"
                    onClick={() => downloadSecure(`/api/dossier/${lead.asset_id}`, `dossier_${lead.asset_id}.txt`)}
                  >
                    DOWNLOAD FREE DOSSIER
                  </button>
                  {isRestricted ? (
                    <button
                      className="decrypt-btn-sota"
                      style={{ background: "#f59e0b" }}
                      onClick={async () => {
                        if (!assetId || !user) {
                          navigate("/login");
                          return;
                        }
                        if (!user.bar_number) {
                          setError("Attorney verification required. Please update your bar number in your profile.");
                          return;
                        }
                        const confirmed = window.confirm(
                          "ATTORNEY ACCESS ONLY\n\n" +
                          "C.R.S. § 38-13-1302(5): This data is provided under the attorney-client exemption.\n\n" +
                          "By proceeding, you confirm a bona fide attorney-client relationship exists or will be established.\n\n" +
                          "Do you accept these terms?"
                        );
                        if (!confirmed) return;
                        setUnlocking(true);
                        setError("");
                        try {
                          const res = await unlockRestrictedLead(assetId, true);
                          setUnlocked(res);
                        } catch (err) {
                          setError(err instanceof ApiError ? err.message : "Unlock failed");
                        } finally {
                          setUnlocking(false);
                        }
                      }}
                      disabled={unlocking}
                    >
                      {unlocking ? "VERIFYING..." : "ATTORNEY ACCESS ONLY (1 CREDIT)"}
                    </button>
                  ) : (
                    <button
                      className="decrypt-btn-sota"
                      onClick={handleUnlock}
                      disabled={unlocking}
                    >
                      {unlocking ? "DECRYPTING..." : "UNLOCK FULL INTEL (1 CREDIT)"}
                    </button>
                  )}
                </div>

                {error && <p className="auth-error" style={{ marginTop: 12 }}>{error}</p>}
              </div>
            )}

            {/* Unlocked Data */}
            {unlocked && (
              <div className="detail-unlocked">
                <span className="success-badge">INTELLIGENCE DECRYPTED</span>
                <div className="detail-grid">
                  <div className="detail-field">
                    <label>Owner Name</label>
                    <span className="revealed">{unlocked.owner_name || "\u2014"}</span>
                  </div>
                  <div className="detail-field">
                    <label>Property Address</label>
                    <span className="revealed">{unlocked.property_address || "\u2014"}</span>
                  </div>
                  <div className="detail-field">
                    <label>Estimated Surplus</label>
                    <span className="revealed">{fmt(unlocked.estimated_surplus)}</span>
                  </div>
                  <div className="detail-field">
                    <label>Total Indebtedness</label>
                    <span>{unlocked.total_indebtedness ? fmt(unlocked.total_indebtedness) : "UNVERIFIED"}</span>
                  </div>
                  <div className="detail-field">
                    <label>Overbid Amount</label>
                    <span>{fmt(unlocked.overbid_amount)}</span>
                  </div>
                  <div className="detail-field">
                    <label>Recorder Link</label>
                    <span>
                      {unlocked.recorder_link ? (
                        <a href={unlocked.recorder_link} target="_blank" rel="noopener noreferrer">
                          View Record
                        </a>
                      ) : "\u2014"}
                    </span>
                  </div>
                </div>
                {unlocked.motion_pdf && (
                  <div className="motion-download">
                    <span className="success-badge">MOTION PDF GENERATED</span>
                    <p>Court-ready motion citing C.R.S. § 38-38-111 has been prepared.</p>
                  </div>
                )}

                {/* Attorney Tool Downloads */}
                <div style={{ marginTop: 20, display: "flex", gap: 12, flexWrap: "wrap" }}>
                  <button
                    className="btn-outline"
                    style={{ fontSize: "0.85em" }}
                    onClick={() => downloadSecure(`/api/dossier/${lead!.asset_id}/docx`, `dossier_${lead!.asset_id}.docx`)}
                  >
                    DOWNLOAD DOSSIER (.DOCX)
                  </button>
                  <button
                    className="btn-outline"
                    style={{ fontSize: "0.85em" }}
                    onClick={() => downloadSecure(`/api/dossier/${lead!.asset_id}/pdf`, `dossier_${lead!.asset_id}.pdf`)}
                  >
                    DOWNLOAD DOSSIER (.PDF)
                  </button>
                  {(lead!.data_grade === "GOLD" || lead!.data_grade === "SILVER") && (
                    <button
                      className="btn-outline"
                      style={{ fontSize: "0.85em" }}
                      onClick={() => downloadSecure(`/api/case-packet/${lead!.asset_id}`, `case_packet_${lead!.asset_id}.html`)}
                    >
                      CASE PACKET (HTML)
                    </button>
                  )}
                  {user?.bar_number && (
                    <button
                      className="btn-outline"
                      style={{ fontSize: "0.85em" }}
                      onClick={async () => {
                        try {
                          const blob = await generateLetter(lead!.asset_id);
                          const url = URL.createObjectURL(blob);
                          const a = document.createElement("a");
                          a.href = url;
                          a.download = `letter_${lead!.asset_id}.docx`;
                          a.click();
                          URL.revokeObjectURL(url);
                        } catch (err) {
                          setError(err instanceof ApiError ? err.message : "Letter generation failed");
                        }
                      }}
                    >
                      GENERATE RULE 7.3 LETTER
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        <div className="dash-disclaimer legal-shield">
          <strong>LEGAL NOTICE</strong>
          <p>
            This platform provides access to publicly available foreclosure sale data.
            It does not provide finder services, does not contact homeowners, and does not
            assist in recovery of surplus funds. No phone numbers, email addresses, or
            skip-tracing data are provided.
          </p>
          <p>
            C.R.S. § 38-38-111(2.5)(c): Compensation agreements are prohibited while
            overbid funds are held by the public trustee (first 6 months). C.R.S.
            § 38-13-1304: Finder agreements void for 2 years after transfer to State
            Treasurer. Attorney-client agreements exempt per § 38-13-1302(5).
          </p>
          <p>
            This is not legal advice. Consult a licensed Colorado attorney before
            filing any claim. Surplus amounts labeled "UNVERIFIED" lack independent
            indebtedness confirmation.
          </p>
        </div>
      </div>
    </div>
  );
}
