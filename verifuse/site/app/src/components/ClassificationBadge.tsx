/**
 * ClassificationBadge — Equity resolution classification display.
 *
 * Gate 7: Attorney UI integration showing equity classification from
 * the equity_resolution_engine. 5 possible classifications:
 *
 *   OWNER_ELIGIBLE              — green  (net owner equity > 0)
 *   LIEN_ABSORBED               — red    (liens ≥ gross surplus)
 *   TREASURER_TRANSFERRED       — amber  (explicit transfer evidence found)
 *   RESOLUTION_PENDING          — gray   (no surplus data or < 30 months)
 *   NEEDS_REVIEW_TREASURER_WINDOW — orange (> 30 months, no explicit transfer)
 */

interface ClassificationBadgeProps {
  classification: string | null | undefined;
}

interface ClassificationInfo {
  label: string;
  color: string;
  bg: string;
  border: string;
  description: string;
}

function getClassificationInfo(classification: string | null | undefined): ClassificationInfo {
  switch (classification) {
    case "OWNER_ELIGIBLE":
      return {
        label: "POTENTIAL OWNER CLAIM",
        color: "#22c55e",
        bg: "rgba(34,197,94,0.1)",
        border: "rgba(34,197,94,0.3)",
        description: "Net owner equity confirmed after lien deduction",
      };
    case "LIEN_ABSORBED":
      return {
        label: "LIEN ABSORBED",
        color: "#ef4444",
        bg: "rgba(239,68,68,0.1)",
        border: "rgba(239,68,68,0.3)",
        description: "Junior liens equal or exceed gross surplus",
      };
    case "TREASURER_TRANSFERRED":
      return {
        label: "TREASURER TRANSFERRED",
        color: "#f59e0b",
        bg: "rgba(245,158,11,0.1)",
        border: "rgba(245,158,11,0.3)",
        description: "Explicit transfer evidence confirmed",
      };
    case "NEEDS_REVIEW_TREASURER_WINDOW":
      return {
        label: "NEEDS REVIEW",
        color: "#f97316",
        bg: "rgba(249,115,22,0.1)",
        border: "rgba(249,115,22,0.3)",
        description: "Over 30 months since sale — treasurer window review required",
      };
    case "RESOLUTION_PENDING":
    default:
      return {
        label: "RESOLUTION PENDING",
        color: "#6b7280",
        bg: "rgba(107,114,128,0.1)",
        border: "rgba(107,114,128,0.3)",
        description: "Awaiting equity classification",
      };
  }
}

export default function ClassificationBadge({ classification }: ClassificationBadgeProps) {
  if (!classification) return null;
  const info = getClassificationInfo(classification);
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 4,
        fontSize: "0.72em",
        fontWeight: 700,
        letterSpacing: "0.06em",
        color: info.color,
        background: info.bg,
        border: `1px solid ${info.border}`,
        whiteSpace: "nowrap",
        cursor: "default",
      }}
      title={info.description}
    >
      {info.label}
    </span>
  );
}
