import { useEffect, useState } from "react";
import { useParams, Link, useNavigate, useLocation } from "react-router-dom";
import { getLeadDetail, unlockLead, unlockRestrictedLead, downloadSecure, downloadSample, generateLetter, sendVerification, verifyEmail, getAssetEvidence, downloadEvidenceDoc, getLeadAudit, type Lead, type UnlockResponse, type EvidenceDoc, type LeadAuditTrail, ApiError } from "../lib/api";
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
  const [auditTrail, setAuditTrail] = useState<LeadAuditTrail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [showAudit, setShowAudit] = useState(false);

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
                <span
                  className={`grade-badge grade-${lead.data_grade?.toLowerCase()}`}
                  style={{ marginLeft: 8 }}
                  title={
                    lead.data_grade === "GOLD" ? "GOLD: Math-confirmed overbid with provenance document"
                    : lead.data_grade === "SILVER" ? "SILVER: Probable overbid, pending full validation"
                    : lead.data_grade === "BRONZE" ? "BRONZE: Pre-validation — math or provenance unconfirmed"
                    : lead.data_grade === "REJECT" ? "REJECT: Insufficient evidence or $0 overbid"
                    : "Grade pending"
                  }
                >
                  {lead.data_grade}
                </span>
                {!lead.surplus_verified && (
                  <span className="unverified-badge" style={{ marginLeft: 8 }}>PRELIMINARY</span>
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
              ) : lead.restriction_status === "UNKNOWN" ? (
                <span className="status-badge" style={{ background: "#374151", color: "#9ca3af" }}>
                  SALE DATE PENDING
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
                  Statutory restrictions under C.R.S. § 38-38-111 and § 38-13-1304 may apply
                  depending on sale date and fund status. Consult counsel.
                </p>
                <p>
                  Restriction lifts: <strong>{lead.restriction_end_date}</strong>
                  {lead.days_until_actionable != null && (
                    <span> ({lead.days_until_actionable} days remaining)</span>
                  )}
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
              {lead.sale_status && (
                <div className="detail-field">
                  <label>Sale Status</label>
                  <span style={{ fontSize: "0.85em", opacity: 0.8 }}>{lead.sale_status}</span>
                </div>
              )}
              {lead.data_age_days != null && lead.data_age_days > 30 && (
                <div className="detail-field">
                  <label>Data Age</label>
                  <span style={{ color: "#f59e0b", fontSize: "0.85em" }}>Data {lead.data_age_days}d old</span>
                </div>
              )}
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
                          <span style={{ opacity: 0.75, minWidth: 120, fontSize: "0.85em" }} title={doc.filename}>
                            {doc.doc_family_label || doc.doc_family} {doc.doc_family && doc.doc_family_label ? `(${doc.doc_family})` : ""}
                          </span>
                          <span style={{ flex: 1, opacity: 0.6, fontSize: "0.85em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.filename}</span>
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
                    <span>{unlocked.total_indebtedness ? fmt(unlocked.total_indebtedness) : "PRELIMINARY"}</span>
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
                  {(() => {
                    const hasEvidence = evidenceDocs.length > 0 || (unlocked?.source_doc_count ?? 0) > 0;
                    return hasEvidence ? (
                      <button className="btn-outline" style={{ fontSize: "0.85em" }}
                        onClick={() => downloadSecure(`/api/case-packet/${lead!.asset_id}`, `case_packet_${lead!.asset_id}.html`)}>
                        CASE PACKET (HTML)
                      </button>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        <span style={{ color: "#ef4444", fontWeight: 600, fontSize: "0.78em", letterSpacing: "0.06em" }}>
                          &#9888; INSUFFICIENT EVIDENCE: No source documents on file.
                        </span>
                        <button className="btn-outline" style={{ fontSize: "0.85em", opacity: 0.4, cursor: "not-allowed" }} disabled>
                          CASE PACKET (HTML)
                        </button>
                      </div>
                    );
                  })()}
                  {user?.bar_number && (
                    <button
                      className="btn-outline"
                      style={{ fontSize: "0.85em", opacity: lead!.ready_to_file === false ? 0.4 : 1, cursor: lead!.ready_to_file === false ? "not-allowed" : "pointer" }}
                      disabled={lead!.ready_to_file === false}
                      title={
                        lead!.ready_to_file === false
                          ? (lead!.grade_reasons?.join("; ") || "Complete all required fields first")
                          : "Generate Rule 7.3 attorney solicitation letter"
                      }
                      onClick={async () => {
                        if (lead!.ready_to_file === false) return;
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

                {/* Phase 4: Surplus Math Audit Panel
                    Rule: render if data_grade === 'GOLD' OR audit record explicitly exists.
                    Only visible to authenticated users viewing an unlocked lead. */}
                {(lead!.data_grade === "GOLD" || lead!.surplus_math_audit) && (
                  <div style={{ marginTop: 20, padding: "12px 16px", border: "1px solid #374151", borderRadius: 6, background: "rgba(17,24,39,0.6)" }}>
                    <h4 style={{ margin: "0 0 10px", fontSize: "0.78em", letterSpacing: "0.08em", opacity: 0.7 }}>
                      SURPLUS MATH AUDIT
                    </h4>
                    {lead!.surplus_math_audit ? (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "flex-start" }}>
                        {lead!.surplus_math_audit.html_overbid != null && (
                          <div>
                            <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>HTML OVERBID</div>
                            <div style={{ fontWeight: 600, fontSize: "0.92em" }}>{fmt(lead!.surplus_math_audit.html_overbid / 100)}</div>
                          </div>
                        )}
                        {lead!.surplus_math_audit.computed_surplus != null && (
                          <div>
                            <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>COMPUTED SURPLUS (BID – DEBT)</div>
                            <div style={{ fontWeight: 600, fontSize: "0.92em" }}>{fmt(lead!.surplus_math_audit.computed_surplus / 100)}</div>
                          </div>
                        )}
                        {lead!.surplus_math_audit.voucher_overbid != null && (
                          <div>
                            <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>VOUCHER AMOUNT</div>
                            <div style={{ fontWeight: 600, fontSize: "0.92em" }}>{fmt(lead!.surplus_math_audit.voucher_overbid / 100)}</div>
                          </div>
                        )}
                        <div>
                          <div style={{ fontSize: "0.68em", opacity: 0.6, letterSpacing: "0.05em", marginBottom: 2 }}>MATH MATCH STATUS</div>
                          <div style={{ fontWeight: 700, fontSize: "0.88em", color: lead!.surplus_math_audit.match_html_math === 1 ? "#22c55e" : lead!.surplus_math_audit.match_html_math === 0 ? "#ef4444" : "#94a3b8" }}>
                            {lead!.surplus_math_audit.match_html_math === 1 ? "CONFIRMED" : lead!.surplus_math_audit.match_html_math === 0 ? "MISMATCH" : "PENDING"}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <p style={{ margin: 0, opacity: 0.5, fontSize: "0.82em" }}>Math audit pending for this GOLD asset.</p>
                    )}
                  </div>
                )}

                {/* Phase 4: Provenance Citation
                    Displays equity_resolution.notes (snapshot_id / doc_id reference).
                    Only visible to authenticated users viewing an unlocked lead. */}
                {lead!.equity_resolution_notes && (
                  <div style={{ marginTop: 12, padding: "10px 16px", border: "1px solid #1f2937", borderRadius: 6, background: "rgba(17,24,39,0.4)" }}>
                    <h4 style={{ margin: "0 0 6px", fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.6 }}>
                      PROVENANCE CITATION
                    </h4>
                    <p style={{ margin: 0, fontSize: "0.82em", opacity: 0.8, whiteSpace: "pre-wrap" }}>
                      {lead!.equity_resolution_notes}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Admin: Case Audit Trail */}
        {user?.is_admin && assetId && (
          <div style={{ margin: "20px 0", padding: "14px 18px", border: "1px solid #1e3a2e", borderRadius: 8, background: "rgba(17,24,39,0.8)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: showAudit ? 16 : 0 }}>
              <h4 style={{ margin: 0, fontSize: "0.78em", letterSpacing: "0.1em", color: "#22c55e" }}>
                ⚑ ADMIN — CASE AUDIT TRAIL
              </h4>
              <button
                className="btn-outline-sm"
                style={{ fontSize: "0.75em" }}
                onClick={async () => {
                  if (!showAudit && !auditTrail) {
                    setAuditLoading(true);
                    try {
                      const data = await getLeadAudit(assetId!);
                      setAuditTrail(data);
                    } catch (e) {
                      console.error("Audit load failed", e);
                    } finally {
                      setAuditLoading(false);
                    }
                  }
                  setShowAudit((v) => !v);
                }}
              >
                {showAudit ? "HIDE" : "SHOW AUDIT"}
              </button>
              {auditLoading && <span style={{ fontSize: "0.75em", opacity: 0.5 }}>Loading...</span>}
            </div>

            {showAudit && auditTrail && (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

                {/* Raw Lead Fields */}
                <div>
                  <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>RAW DB RECORD</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.8em" }}>
                    {Object.entries(auditTrail.lead).filter(([k]) => !k.startsWith("_")).map(([k, v]) => (
                      <div key={k} style={{ display: "flex", gap: 6 }}>
                        <span style={{ opacity: 0.45, minWidth: 160, flexShrink: 0 }}>{k}:</span>
                        <span style={{ color: v == null ? "#6b7280" : "#e5e7eb", wordBreak: "break-all" }}>
                          {v == null ? "null" : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 8, fontSize: "0.78em" }}>
                    <span style={{ opacity: 0.5 }}>Computed status: </span>
                    <span style={{ color: "#f59e0b", fontWeight: 700 }}>{String(auditTrail.lead._computed_status || "—")}</span>
                    <span style={{ opacity: 0.5, marginLeft: 16 }}>Canonical ID: </span>
                    <span style={{ fontFamily: "monospace", color: "#94a3b8" }}>{String(auditTrail.lead._asset_id_canonical || "—")}</span>
                  </div>
                </div>

                {/* Math Audit */}
                {auditTrail.math_audit && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>SURPLUS MATH AUDIT</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.8em" }}>
                      {Object.entries(auditTrail.math_audit).map(([k, v]) => (
                        <div key={k} style={{ display: "flex", gap: 6 }}>
                          <span style={{ opacity: 0.45, minWidth: 160, flexShrink: 0 }}>{k}:</span>
                          <span style={{ color: v == null ? "#6b7280" : "#e5e7eb" }}>{v == null ? "null" : String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Equity Resolution */}
                {auditTrail.equity_resolution && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>EQUITY RESOLUTION</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 6, fontSize: "0.8em" }}>
                      {Object.entries(auditTrail.equity_resolution).map(([k, v]) => (
                        <div key={k} style={{ display: "flex", gap: 6 }}>
                          <span style={{ opacity: 0.45, minWidth: 160, flexShrink: 0 }}>{k}:</span>
                          <span style={{ color: v == null ? "#6b7280" : "#e5e7eb" }}>{v == null ? "null" : String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Evidence Documents */}
                {auditTrail.evidence_docs.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>
                      EVIDENCE DOCUMENTS ({auditTrail.evidence_docs.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {auditTrail.evidence_docs.map((d) => (
                        <div key={d.id} style={{ display: "flex", gap: 12, fontSize: "0.8em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                          <span style={{ opacity: 0.45, minWidth: 80 }}>{d.doc_family || "—"}</span>
                          <span style={{ flex: 1, fontFamily: "monospace" }}>{d.filename}</span>
                          <span style={{ opacity: 0.4 }}>{d.bytes ? `${Math.round(d.bytes / 1024)} KB` : ""}</span>
                          <span style={{ opacity: 0.4 }}>{d.retrieved_ts ? new Date(d.retrieved_ts * 1000).toLocaleDateString() : ""}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Field Evidence */}
                {auditTrail.field_evidence.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>
                      FIELD EVIDENCE ({auditTrail.field_evidence.length} extractions)
                    </div>
                    {auditTrail.field_evidence.map((fe, i) => (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 4, fontSize: "0.78em", padding: "6px 0", borderBottom: "1px solid #1f2937", marginBottom: 4 }}>
                        {Object.entries(fe).map(([k, v]) => (
                          <div key={k} style={{ display: "flex", gap: 4 }}>
                            <span style={{ opacity: 0.4, minWidth: 120, flexShrink: 0 }}>{k}:</span>
                            <span style={{ color: v == null ? "#6b7280" : "#e5e7eb", wordBreak: "break-all" }}>{v == null ? "null" : String(v)}</span>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}

                {/* Audit Log */}
                {auditTrail.audit_entries.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>
                      AUDIT LOG ({auditTrail.audit_entries.length} entries)
                    </div>
                    {auditTrail.audit_entries.map((e) => (
                      <div key={e.id} style={{ display: "flex", gap: 12, fontSize: "0.78em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                        <span style={{ opacity: 0.4, whiteSpace: "nowrap" }}>{e.created_at?.slice(0, 16).replace("T", " ")}</span>
                        <span style={{ opacity: 0.6, minWidth: 140 }}>{e.user_email || "system"}</span>
                        <span style={{ color: "#22c55e", fontFamily: "monospace" }}>{e.action}</span>
                        {e.ip && <span style={{ opacity: 0.3 }}>{e.ip}</span>}
                      </div>
                    ))}
                  </div>
                )}

                {/* Unlock History */}
                {auditTrail.unlock_history.length > 0 && (
                  <div>
                    <div style={{ fontSize: "0.72em", letterSpacing: "0.08em", opacity: 0.5, marginBottom: 8 }}>
                      UNLOCK HISTORY ({auditTrail.unlock_history.length} unlocks)
                    </div>
                    {auditTrail.unlock_history.map((u, i) => (
                      <div key={i} style={{ display: "flex", gap: 12, fontSize: "0.78em", padding: "4px 0", borderBottom: "1px solid #1f2937" }}>
                        <span style={{ opacity: 0.4 }}>{String(u["unlocked_at"] || "—")}</span>
                        <span style={{ opacity: 0.7 }}>{String(u["user_email"] || u["user_id"] || "—")}</span>
                        <span style={{ opacity: 0.5 }}>{String(u["tier_at_unlock"] || "—")}</span>
                        <span style={{ color: "#22c55e" }}>{String(u["credits_spent"] || 0)} credits</span>
                      </div>
                    ))}
                  </div>
                )}

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
            Statutory restrictions under C.R.S. § 38-38-111 and § 38-13-1304 may apply
            depending on sale date and fund status. Consult counsel.
          </p>
        </div>
      </div>
    </div>
  );
}
