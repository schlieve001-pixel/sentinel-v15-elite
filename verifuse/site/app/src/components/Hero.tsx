import { type Stats } from "../lib/api";

interface HeroProps {
  stats: Stats | null;
  loading: boolean;
}

export default function Hero({ stats, loading }: HeroProps) {
  return (
    <header className="hero">
      <h1 className="hero-title">VERIFUSE</h1>
      <p className="hero-subtitle">Colorado Surplus Intelligence</p>

      <div className="hero-stats">
        <div className="stat-block">
          <span className="stat-value">
            {loading || !stats
              ? "..."
              : `$${stats.total_claimable_surplus.toLocaleString("en-US", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`}
          </span>
          <span className="stat-label">Claimable Surplus</span>
        </div>
        <div className="stat-block">
          <span className="stat-value">
            {loading || !stats ? "..." : stats.total_assets}
          </span>
          <span className="stat-label">Verified Assets</span>
        </div>
        <div className="stat-block">
          <span className="stat-value">
            {loading || !stats ? "..." : stats.gold_grade}
          </span>
          <span className="stat-label">GOLD Grade</span>
        </div>
      </div>
    </header>
  );
}
