import os

# 1. CREATE THE SCARCITY COMPONENT
scarcity_code = """
import React from 'react';

const ScarcityBar = () => {
  return (
    <div className="scarcity-banner">
      <div className="scarcity-content">
        <span className="blink-dot">●</span>
        <span className="scarcity-text">
          TERRITORY ALERT: JEFFERSON COUNTY [1/3 SEATS REMAINING]
        </span>
        <span className="scarcity-divider">|</span>
        <span className="scarcity-sub">
          FOUNDING MEMBER CAP REACHED IN 48H
        </span>
      </div>
      <button className="lock-btn">SECURE JURISDICTION</button>
    </div>
  );
};

export default ScarcityBar;
"""

# 2. ADD THE SCARCITY CSS
scarcity_css = """
/* SCARCITY ENGINE */
.scarcity-banner {
  background: #450a0a; /* Dark Crimson */
  border-bottom: 1px solid #ef4444;
  color: #fecaca;
  padding: 8px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.05em;
  position: sticky;
  top: 0;
  z-index: 1000;
}

.scarcity-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.blink-dot {
  color: #ef4444;
  animation: blink 1.5s infinite;
  font-size: 14px;
}

.scarcity-text {
  font-weight: 800;
  color: #fff;
}

.scarcity-divider {
  opacity: 0.3;
}

.lock-btn {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid #ef4444;
  color: #fff;
  padding: 4px 12px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
}

.lock-btn:hover {
  background: #ef4444;
  color: #000;
}

@keyframes blink {
  0% { opacity: 1; }
  50% { opacity: 0.4; }
  100% { opacity: 1; }
}
"""

# Write the Component
if not os.path.exists("src/components"):
    os.makedirs("src/components")

with open("src/components/ScarcityBar.tsx", "w") as f:
    f.write(scarcity_code)

# Append the CSS
with open("src/App.css", "a") as f:
    f.write(scarcity_css)

print("🚨 Scarcity Engine Installed: 'Territory Cap' logic active.")
print("⚠️ Next Step: Import <ScarcityBar /> into your main App.tsx to display it.")
