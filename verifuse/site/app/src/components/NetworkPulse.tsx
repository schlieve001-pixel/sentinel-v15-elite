
import { useState, useEffect } from 'react';

export default function NetworkPulse() {
  const events = [
    "INTEL: New $380k Surplus identified in Arapahoe...",
    "ACCESS: Bar #55831 requesting Jefferson clearance...",
    "ALERT: J2500271 approaching 180-day escheatment limit...",
    "DECAY: $4.6M total capital approaching state sweep...",
    "NETWORK: 7 Forensic Dossiers minted in last 12hrs..."
  ];
  const [pulse, setPulse] = useState(events[0]);
  useEffect(() => {
    const interval = setInterval(() => {
      setPulse(events[Math.floor(Math.random() * events.length)]);
    }, 4000);
    return () => clearInterval(interval);
  }, []);
  return (
    <div className="network-pulse">
      <span className="pulse-dot"></span>
      <span className="pulse-text">{pulse}</span>
    </div>
  );
}
