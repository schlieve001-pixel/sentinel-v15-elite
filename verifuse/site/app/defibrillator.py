import os

# ENSURE DIRECTORIES EXIST
if not os.path.exists("src/components"):
    os.makedirs("src/components")

# 1. WRITE THE SCARCITY ENGINE (Guaranteed to work)
scarcity_code = """
import React from 'react';
export default function ScarcityBar() {
  return (
    <div className="scarcity-banner">
      <div className="scarcity-content">
        <span className="blink-dot">●</span>
        <span className="scarcity-text">
          TERRITORY ALERT: JEFFERSON COUNTY [1/3 SEATS REMAINING]
        </span>
      </div>
      <button className="lock-btn">SECURE JURISDICTION</button>
    </div>
  );
}
"""

with open("src/components/ScarcityBar.tsx", "w") as f:
    f.write(scarcity_code)

# 2. WRITE THE ASSET GRID (With Hardcoded 'Whale' Data to Force Render)
grid_code = """
import React from 'react';

const MOCK_WHALES = [
  { id: 'J2500271', county: 'JEFFERSON', value: '$1,057,500.57', days: 42, status: 'CRITICAL' },
  { id: 'J2500124', county: 'JEFFERSON', value: '$427,062.69', days: 88, status: 'ACTIVE' },
  { id: '0323-2023', county: 'ARAPAHOE', value: '$380,969.23', days: 112, status: 'STABLE' },
  { id: '2025-000205', county: 'DENVER', value: '$366,672.27', days: 150, status: 'STABLE' },
];

export default function LeadGrid() {
  return (
    <div className="vault-grid">
      {MOCK_WHALES.map((whale) => (
        <div key={whale.id} className="lead-card">
          <div className="card-header">
            <span className="county-badge">{whale.county}</span>
            <span className="timer-badge">{whale.days} DAYS REMAINING</span>
          </div>
          <div className="card-value">{whale.value}</div>
          <div className="card-id">CASE ID: {whale.id}</div>
          
          {/* THE REDACTED BLOCK */}
          <div className="redacted-field">
            CONFIDENTIAL OWNER DATA RESTRICTED
            <br/>
            PLEASE SUBMIT BAR NUMBER
          </div>

          <button className="decrypt-btn-sota">
            REQUEST DECRYPTION
          </button>
        </div>
      ))}
    </div>
  );
}
"""

with open("src/components/LeadGrid.tsx", "w") as f:
    f.write(grid_code)

# 3. WRITE THE CSS (The 'Empire' Theme)
css_code = """
:root { --bg: #020617; --card: #0f172a; --green: #10b981; --red: #ef4444; --text: #f8fafc; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: 'JetBrains Mono', monospace; }

/* SCARCITY */
.scarcity-banner {
  background: #450a0a; border-bottom: 1px solid var(--red); color: #fecaca;
  padding: 10px; display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; position: sticky; top: 0; z-index: 100;
}
.blink-dot { color: var(--red); animation: blink 1s infinite; margin-right: 8px; }
.lock-btn { background: rgba(239,68,68,0.2); color: #fff; border: 1px solid var(--red); cursor: pointer; }

/* HEADER */
.vault-header {
  padding: 20px; border-bottom: 1px solid #1e293b; display: flex; justify-content: space-between;
  background: rgba(2,6,23,0.95);
}

/* GRID */
.vault-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; padding: 20px; }
.lead-card { background: var(--card); border: 1px solid #1e293b; padding: 20px; border-left: 4px solid #334155; }
.lead-card:hover { border-left-color: var(--green); transform: translateY(-2px); }

.card-header { display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 10px; }
.county-badge { color: var(--green); font-weight: bold; }
.timer-badge { color: var(--red); border: 1px solid var(--red); padding: 2px 4px; border-radius: 2px; }

.card-value { font-size: 24px; font-weight: 800; color: #fff; margin-bottom: 5px; }
.card-id { font-size: 12px; color: #64748b; margin-bottom: 15px; }

.redacted-field { background: #1e293b; padding: 10px; font-size: 10px; color: transparent; text-shadow: 0 0 5px rgba(255,255,255,0.5); border-radius: 4px; user-select: none; margin-bottom: 15px; }

.decrypt-btn-sota { width: 100%; background: var(--green); border: none; padding: 12px; font-weight: 900; cursor: pointer; clip-path: polygon(0 0, 95% 0, 100% 100%, 0 100%); }
.decrypt-btn-sota:hover { filter: brightness(1.1); }

@keyframes blink { 50% { opacity: 0; } }
"""

with open("src/App.css", "w") as f:
    f.write(css_code)

# 4. WRITE THE MAIN APP (The Wiring)
app_code = """
import React from 'react'
import './App.css'
import ScarcityBar from './components/ScarcityBar'
import LeadGrid from './components/LeadGrid'

function App() {
  return (
    <div className="app-root">
      <ScarcityBar />
      <header className="vault-header">
        <div>VERIFUSE <span style={{color: '#10b981'}}>// INTELLIGENCE</span></div>
        <div style={{color: '#ef4444', fontSize: '10px'}}>SYSTEM STATUS: LIVE</div>
      </header>
      <main>
        <LeadGrid />
      </main>
    </div>
  )
}
export default App
"""

with open("src/App.tsx", "w") as f:
    f.write(app_code)

print("⚡ DEFIBRILLATOR COMPLETE. SYSTEM RESET.")
