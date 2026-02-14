
import { useState } from 'react';
import './AccessModal.css';

interface AccessModalProps {
  assetId: string;
  onClose: () => void;
}

export default function AccessModal({ assetId, onClose }: AccessModalProps) {
  const [step, setStep] = useState<'verify' | 'plan' | 'processing'>('verify');
  const [barNumber, setBarNumber] = useState('');

  const handleVerify = () => {
    if (!barNumber) return;
    setStep('processing');
    // Simulate API verification delay for psychological effect
    setTimeout(() => {
      setStep('plan');
    }, 1500);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-container">
        <button className="close-btn" onClick={onClose}>×</button>

        {step === 'verify' && (
          <div className="modal-content">
            <div className="modal-header">
              <span className="security-badge">SECURITY LEVEL 2</span>
              <h2>Credential Verification</h2>
              <p>Access to Asset ID: <span className="mono-highlight">{assetId}</span> requires Bar Association credentials.</p>
            </div>
            <div className="input-group">
              <label>ATTORNEY BAR NUMBER</label>
              <input 
                type="text" 
                placeholder="Ex: 55-90210" 
                value={barNumber}
                onChange={(e) => setBarNumber(e.target.value)}
                className="forensic-input"
                autoFocus
              />
            </div>
            <div className="input-group">
              <label>FIRM DOMAIN</label>
              <input type="text" placeholder="Ex: @skadden.com" className="forensic-input" />
            </div>
            <button className="action-btn" onClick={handleVerify}>
              VERIFY CREDENTIALS
            </button>
          </div>
        )}

        {step === 'processing' && (
          <div className="modal-content center-content">
            <div className="loader-ring"></div>
            <p className="processing-text">VERIFYING AGAINST STATE REGISTRY...</p>
          </div>
        )}

        {step === 'plan' && (
          <div className="modal-content">
            <div className="modal-header">
              <span className="success-badge">CREDENTIALS VERIFIED</span>
              <h2>Select Intelligence Tier</h2>
            </div>
            <div className="pricing-grid">
              <div className="plan-card standard">
                <h3>Single Packet</h3>
                <div className="price">$495<span>/asset</span></div>
                <ul>
                  <li>Full Owner Genealogy</li>
                  <li>Property Deed Hash</li>
                  <li>Surplus Calculation</li>
                </ul>
                <button className="plan-btn">UNLOCK SINGLE</button>
              </div>
              <div className="plan-card sovereign">
                <div className="best-value">RECOMMENDED</div>
                <h3>Sovereign Access</h3>
                <div className="price">$4,995<span>/mo</span></div>
                <ul>
                  <li>Unlimited Vault Access</li>
                  <li>Real-Time Decay Alerts</li>
                  <li>API Integration</li>
                </ul>
                <button className="plan-btn glow">INITIATE RETAINER</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
