import { useEffect, useState } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import { getLeadDetail, unlockLead, unlockRestrictedLead, downloadSecure, downloadSample, generateLetter, sendVerification, verifyEmail, getAssetEvidence, downloadEvidenceDoc, type Lead, type UnlockResponse, type EvidenceDoc, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import ClassificationBadge from "../components/ClassificationBadge";

function isVerifyEmailError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 &&
    /verify/i.test(err.message) && /email/i.test(err.message);
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "\u2014";
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LeadDetail() {
  const { assetId } = useParams<{ assetId: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Smart back navigation
  const backUrl = (location.state as { from?: string })?.from
    || sessionStorage.getItem("lastLeadsUrl")
    || (user ? "/dashboard" : "/preview");

  function goBack() {
    navigate(backUrl, { replace: true });
  }
  const [lead, setLead] = useState<Lead | null>(null);
  const [unlocked, setUnlocked] = useState<UnlockResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [unlocking, setUnlocking] = useState(false);
  const [error, setError] = useState("");
  const [showVerifyPrompt, setShowVerifyPrompt] = useState(false);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifySending, setVerifySending] = useState(false);
  const [verifyMsg, setVerifyMsg] = useState("");
  const [evidenceDocs, setEvidenceDocs] = useState<EvidenceDoc[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");

  useEffect(() => {
    if (!assetId) return;
    const ac = new AbortController();
    getLeadDetail(assetId, ac.signal)
      .then(setLead)
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Failed to load");
      })
      .finally(() => setLoading(false));
    return () => ac.abort();
  }, [assetId]);

  // Auto-load evidence docs for attorneys/admins when registry_asset_id is available
  useEffect(() => {
    const isAttorney = user?.is_admin || user?.role === "approved_attorney" || user?.role === "admin";
    if (!lead?.registry_asset_id || !isAttorney) return;
    const ac = new AbortController();
    setEvidenceLoading(true);
    getAssetEvidence(lead.registry_asset_id, ac.signal)
      .then(setEvidenceDocs)
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setEvidenceError(err instanceof ApiError ? err.message : "Failed to load evidence");
      })
      .finally(() => setEvidenceLoading(false));
    return () => ac.abort();
  }, [lead?.registry_asset_id, user]);

  function handleUnlockError(err: unknown) {
    if (isVerifyEmailError(err)) {
      setShowVerifyPrompt(true);
      setError("");
    } else {
      setError(err instanceof ApiError ? err.message : "Unlock failed");
    }
  }

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
      handleUnlockError(err);
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
          <button className="btn-outline" style={{ marginTop: 20 }} onClick={goBack}>
            BACK TO VAULT
          </button>
        </div>
      </div>
    );
  }

  const isRestricted = lead?.restriction_status === "RESTRICTED";
  const isExpired = lead?.deadline_passed === true || lead?.restriction_status === ("EXPIRED" as any);

  return (
    <div className="detail-page">
      <header className="dash-header">
        <Link to={user ? "/dashboard" : "/preview"} className="dash-logo">
          VERIFUSE <span className="text-green">// INTELLIGENCE</span>
        </Link>
        <div className="dash-status">
          <span className="blink-dot">●</span>
          ASSET DETAIL
        </div>
      </header>

      <div className="detail-container">
        <button className="back-link" onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>&larr; Back to Vault</button>

        {lead && (
          <div className="detail-card">
            <div className="detail-header">
              <div>
                <span className="county-badge">{lead.county}</span>
                <span className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`} style={{ marginLeft: 8 }}>
                  {lead.data_grade}
                </span>
                {!lead.surplus_verified && (
                  <span className="unverified-badge" style={{ marginLeft: 8 }}>DETECTED</span>
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
            <p className="detail-case">Case: {lead.case_number || lead.registry_asset_id?.split(":")[3] || lead.asset_id?.substring(0, 12)}</p>

            {/* Gate 7: Equity Resolution Panel */}
            {lead.net_owner_equity_cents != null && (
              <div style={{
                margin: "12px 0",
                padding: "10px 16px",
                border: "1px solid #374151",
                borderRadius: 6,
                background: "rgba(17,24,39,0.6)",
                display: "flex",
                gap: 24,
                alignItems: "center",
                flexWrap: "wrap",
              }}>
                {lead.gross_surplus_cents != null && (
                  <div>
                    <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>GROSS SURPLUS</div>
                    <div style={{ fontWeight: 600, fontSize: "0.95em" }}>
                      {fmt(lead.gross_surplus_cents / 100)}
                    </div>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>NET OWNER EQUITY</div>
                  <div style={{ fontWeight: 600, fontSize: "0.95em" }}>
                    {fmt(lead.net_owner_equity_cents / 100)}
                  </div>
                </div>
                {lead.classification && (
                  <ClassificationBadge classification={lead.classification} />
                )}
              </div>
            )}

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
                  C.R.S. § 38-38-111 and § 38-13-1304 restrictions apply. Consult counsel.
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
                  {lead.preview_key ? (
                    <button
                      className="btn-outline"
                      onClick={() => downloadSample(lead.preview_key!)}
                    >
                      SAMPLE DOSSIER
                    </button>
                  ) : (
                    <button
                      className="btn-outline"
                      onClick={() => downloadSecure(`/api/dossier/${lead.asset_id}`, `dossier_${lead.asset_id}.pdf`)}
                    >
                      DOWNLOAD DOSSIER
                    </button>
                  )}
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
                          "ATTORNEY ACCESS ONLY\n\n" +
                          "C.R.S. § 38-38-111 and § 38-13-1304 restrictions apply. Consult counsel before proceeding.\n\n" +
                          "Do you confirm you are a licensed Colorado attorney and accept these terms?"
                        );
                        if (!confirmed) return;
                        setUnlocking(true);
                        setError("");
                        try {
                          const res = await unlockRestrictedLead(assetId, true);
                          setUnlocked(res);
                        } catch (err) {
                          handleUnlockError(err);
                        } finally {
                          setUnlocking(false);
                        }
                      }}
                      disabled={unlocking || (user ? !user.email_verified : false)}
                    >
                      {unlocking ? "VERIFYING..." : "ATTORNEY ACCESS ONLY (1 CREDIT)"}
                    </button>
                  ) : (
                    <div className="unlock-cta-expanded">
                      <button
                        className="decrypt-btn-sota decrypt-btn-lg"
                        onClick={handleUnlock}
                        disabled={unlocking || (user ? !user.email_verified : false)}
                      >
                        {unlocking ? "DECRYPTING..." : "UNLOCK FULL INTEL (1 CREDIT)"}
                      </button>
                      <p className="unlock-cta-details">
                        You'll get: Owner name, full address, recorder link, court-ready dossier
                      </p>
                    </div>
                  )}
                </div>

                {error && <p className="auth-error" style={{ marginTop: 12 }}>{error}</p>}

                {/* Email Verification Prompt */}
                {(showVerifyPrompt || (user && !user.email_verified)) && (
                  <div className="verify-banner" style={{ marginTop: 16 }}>
                    <strong>Verify your email to unlock leads</strong>
                    <div className="verify-row">
                      <input
                        type="text"
                        placeholder="Enter verification code"
                        value={verifyCode}
                        onChange={(e) => setVerifyCode(e.target.value)}
                        className="verify-input"
                      />
                      <button
                        className="btn-outline-sm"
                        disabled={!verifyCode || verifySending}
                        onClick={async () => {
                          setVerifySending(true);
                          setVerifyMsg("");
                          try {
                            await verifyEmail(verifyCode);
                            setVerifyMsg("Email verified!");
                            window.location.reload();
                          } catch {
                            setVerifyMsg("Invalid code. Try again.");
                          } finally {
                            setVerifySending(false);
                          }
                        }}
                      >
                        VERIFY
                      </button>
                      <button
                        className="btn-outline-sm"
                        disabled={verifySending}
                        onClick={async () => {
                          setVerifySending(true);
                          setVerifyMsg("");
                          try {
                            await sendVerification();
                            setVerifyMsg("Verification email sent!");
                          } catch {
                            setVerifyMsg("Failed to send. Try again.");
                          } finally {
                            setVerifySending(false);
                          }
                        }}
                      >
                        RESEND CODE
                      </button>
                    </div>
                    {verifyMsg && <p className="verify-msg">{verifyMsg}</p>}
                  </div>
                )}
              </div>
            )}

            {/* Gate 7: Evidence Documents (attorney/admin only) */}
            {lead.registry_asset_id && (() => {
              const isAttorney = user?.is_admin || user?.role === "approved_attorney" || user?.role === "admin";
              if (!isAttorney) {
                return (
                  <div style={{ margin: "16px 0", padding: "10px 16px", border: "1px solid #374151", borderRadius: 6, opacity: 0.6, fontSize: "0.85em" }}>
                    Attorney verification required to access evidence documents.
                  </div>
                );
              }
              return (
                <div style={{ margin: "16px 0" }}>
                  <h4 style={{ margin: "0 0 8px", fontSize: "0.8em", letterSpacing: "0.08em", opacity: 0.7 }}>
                    EVIDENCE DOCUMENTS
                  </h4>
                  {evidenceLoading && <p style={{ opacity: 0.6, fontSize: "0.85em" }}>Loading evidence…</p>}
                  {evidenceError && <p className="auth-error" style={{ fontSize: "0.85em" }}>{evidenceError}</p>}
                  {!evidenceLoading && evidenceDocs.length === 0 && !evidenceError && (
                    <p style={{ opacity: 0.5, fontSize: "0.82em" }}>No evidence documents on file for this asset.</p>
                  )}
                  {evidenceDocs.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {evidenceDocs.map((doc) => (
                        <div key={doc.id} style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "6px 10px",
                          border: "1px solid #374151",
                          borderRadius: 4,
                          fontSize: "0.82em",
                        }}>
                          <span style={{ opacity: 0.5, minWidth: 40, fontSize: "0.9em" }}>{doc.doc_family}</span>
                          <span style={{ flex: 1, opacity: 0.85 }}>{doc.filename}</span>
                          <span style={{ opacity: 0.45, fontSize: "0.85em" }}>
                            {doc.bytes > 0 ? `${Math.round(doc.bytes / 1024)} KB` : ""}
                          </span>
                          <button
                            className="btn-outline-sm"
                            style={{ fontSize: "0.78em" }}
                            onClick={async () => {
                              try {
                                const blob = await downloadEvidenceDoc(doc.id);
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement("a");
                                a.href = url;
                                a.download = doc.filename;
                                a.click();
                                URL.revokeObjectURL(url);
                              } catch (err) {
                                setError(err instanceof ApiError ? err.message : "Download failed");
                              }
                            }}
                          >
                            DOWNLOAD
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}

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
                    <span>{unlocked.total_indebtedness ? fmt(unlocked.total_indebtedness) : "DETECTED"}</span>
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
                    DOSSIER (.DOCX)
                  </button>
                  <button
                    className="btn-outline"
                    style={{ fontSize: "0.85em" }}
                    onClick={() => downloadSecure(`/api/dossier/${lead!.asset_id}/pdf`, `dossier_${lead!.asset_id}.pdf`)}
                  >
                    DOSSIER (.PDF)
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
            C.R.S. § 38-38-111 and § 38-13-1304 restrictions apply. Consult counsel.
          </p>
          <p>
            This is not legal advice. Consult a licensed Colorado attorney before
            filing any claim. Surplus amounts labeled "DETECTED" lack independent
            indebtedness confirmation.
          </p>
        </div>
      </div>
    </div>
  );
}
