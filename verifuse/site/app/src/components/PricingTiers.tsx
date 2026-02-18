/**
 * PricingTiers — Subscription tier cards with per-credit transparency.
 *
 * Tiers:
 *   Scout    ($49/mo, 25 credits, $1.96/credit)
 *   Operator ($149/mo, 100 credits, $1.49/credit) — Most Popular
 *   Sovereign ($499/mo, 500 credits, $0.99/credit) — Best Value
 *
 * Risk reduction: cancel anytime, no contract, credits roll over 30 days.
 * Urgency: founding member rates (no fake timers).
 */

import { Link } from "react-router-dom";

interface Tier {
  name: string;
  price: number;
  credits: number;
  perCredit: string;
  popular?: boolean;
  bestValue?: boolean;
  features: string[];
}

const TIERS: Tier[] = [
  {
    name: "Scout",
    price: 49,
    credits: 25,
    perCredit: "$1.96",
    features: [
      "25 lead unlocks / month",
      "100 lead views / day",
      "All Colorado counties",
      "Dossier PDF downloads",
      "Single-session access",
    ],
  },
  {
    name: "Operator",
    price: 149,
    credits: 100,
    perCredit: "$1.49",
    popular: true,
    features: [
      "100 lead unlocks / month",
      "500 lead views / day",
      "All Colorado counties",
      "Court motion PDF generation",
      "2 concurrent sessions",
    ],
  },
  {
    name: "Sovereign",
    price: 499,
    credits: 500,
    perCredit: "$0.99",
    bestValue: true,
    features: [
      "500 lead unlocks / month",
      "Unlimited lead views",
      "Priority new-lead alerts",
      "Motion + dossier generation",
      "5 concurrent sessions",
    ],
  },
];

export default function PricingTiers() {
  return (
    <section className="pricing-section">
      <div className="pricing-header">
        <h2>Founding Member Pricing</h2>
        <p className="pricing-sub">
          Lock in introductory rates. Cancel anytime. No contract.
        </p>
        <p className="pricing-founding">
          First 100 subscribers get these rates locked for 12 months.
        </p>
      </div>

      <div className="pricing-grid">
        {TIERS.map((tier) => (
          <div
            key={tier.name}
            className={`plan-card ${tier.popular ? "sovereign" : ""}`}
          >
            {tier.popular && <div className="best-value">MOST POPULAR</div>}
            {tier.bestValue && <div className="best-value value">BEST VALUE</div>}

            <h3>{tier.name}</h3>
            <div className="price">
              ${tier.price}
              <span>/mo</span>
            </div>
            <div className="per-credit">
              {tier.perCredit} per credit
            </div>
            <div className="credit-count">
              {tier.credits} credits included
            </div>

            <ul>
              {tier.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>

            <Link
              to="/register"
              className={`plan-btn ${tier.popular ? "glow" : ""}`}
            >
              GET STARTED
            </Link>
          </div>
        ))}
      </div>

      <div className="pricing-guarantees">
        <div className="guarantee-item">
          <strong>Cancel Anytime</strong>
          <span>No contracts, no lock-in</span>
        </div>
        <div className="guarantee-item">
          <strong>Credits Roll Over</strong>
          <span>Unused credits carry forward 30 days</span>
        </div>
        <div className="guarantee-item">
          <strong>Founding Rates</strong>
          <span>Locked for 12 months</span>
        </div>
      </div>
    </section>
  );
}
