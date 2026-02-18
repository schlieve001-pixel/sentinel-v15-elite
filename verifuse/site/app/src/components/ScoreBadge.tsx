/**
 * ScoreBadge — Visual badge for the 3-Score Intelligence Index.
 *
 * Displays opportunity score with tier label:
 *   85+ → "Elite Opportunity" (green, 3 credits)
 *   70-84 → "Verified Lead" (blue, 2 credits)
 *   0-69 → "Standard" (gray, 1 credit)
 *
 * Optional: show confidence and velocity scores inline.
 */

interface ScoreBadgeProps {
  opportunity: number;
  confidence?: number;
  velocity?: number;
  showDetails?: boolean;
}

function getTierInfo(score: number) {
  if (score >= 85) {
    return {
      label: "ELITE",
      className: "score-elite",
      credits: 3,
    };
  }
  if (score >= 70) {
    return {
      label: "VERIFIED",
      className: "score-verified",
      credits: 2,
    };
  }
  return {
    label: "STANDARD",
    className: "score-standard",
    credits: 1,
  };
}

export default function ScoreBadge({
  opportunity,
  confidence,
  velocity,
  showDetails = false,
}: ScoreBadgeProps) {
  const tier = getTierInfo(opportunity);

  return (
    <div className={`score-badge ${tier.className}`}>
      <div className="score-primary">
        <span className="score-value">{opportunity}</span>
        <span className="score-label">{tier.label}</span>
      </div>

      {showDetails && (confidence != null || velocity != null) && (
        <div className="score-details">
          {confidence != null && (
            <span className="score-detail" title="Data confidence">
              <span className="score-detail-label">CONF</span>
              <span className="score-detail-value">{confidence}</span>
            </span>
          )}
          {velocity != null && (
            <span className="score-detail" title="Market velocity">
              <span className="score-detail-label">VEL</span>
              <span className="score-detail-value">{velocity}</span>
            </span>
          )}
        </div>
      )}

      <div className="score-cost">
        {tier.credits} {tier.credits === 1 ? "CREDIT" : "CREDITS"}
      </div>
    </div>
  );
}

/**
 * Compact inline badge for list views.
 * Shows just the score number + tier color.
 */
export function ScorePill({ score }: { score: number }) {
  const tier = getTierInfo(score);
  return (
    <span className={`score-pill ${tier.className}`} title={`${tier.label} (${tier.credits} credits)`}>
      {score}
    </span>
  );
}
