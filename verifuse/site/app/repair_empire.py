import os

# 1. RESET APP.CSS (Wipe it clean and write the full SOTA theme)
full_css = """
/* VERIFUSE SOVEREIGN THEME - RESET */
:root {
  --bg-obsidian: #020617;
  --bg-card: #0f172a;
  --accent-emerald: #10b981;
  --accent-crimson: #ef4444;
  --text-primary: #f8fafc;
  --text-muted: #94a3b8;
}

body {
  margin: 0;
  padding: 0;
  background-color: var(--bg-obsidian);
  color: var(--text-primary);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
}

/* SCARCITY BAR */
.scarcity-banner {
  background: #450a0a;
  border-bottom: 1px solid var(--accent-crimson);
  color: #fecaca;
  padding: 8px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  position: sticky;
  top: 0;
  z-index: 50;
}

.blink-dot { animation: pulse 1.5s infinite; color: var(--accent-crimson); }

/* HEADER */
.vault-header {
  background: rgba(2, 6, 23, 0.9);
  border-bottom: 1px solid rgba(16, 185, 129, 0.2);
  padding: 16px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  backdrop-filter: blur(8px);
}

.brand-title {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  letter-spacing: -0.05em;
  font-size: 18px;
}

/* GRID & CARDS */
.vault-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 20px;
  padding: 24px;
}

.lead-card {
  background: var(--bg-card);
  border: 1px solid rgba(255,255,255,0.05);
  border-left: 3px solid #334155;
  padding: 20px;
  border-radius: 4px;
}

.lead-card:hover {
  border-left-color: var(--accent-emerald);
  transform: translateY(-2px);
  transition: all 0.2s ease;
}

/* ACTIONS */
.decrypt-btn-sota {
  width: 100%;
  background: var(--accent-emerald);
  color: #000;
  font-weight: 900;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
  border: none;
  padding: 12px;
  margin-top: 15px;
  cursor: pointer;
  clip-path: polygon(0 0, 95% 0, 100% 100%, 0 100%);
}

.decrypt-btn-sota:hover { filter: brightness(1.1); }

@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
"""

with open("src/App.css", "w") as f:
    f.write(full_css)

# 2. RESET APP.TSX (Ensure correct imports)
app_tsx = """
import React from 'react'
import './App.css'
import ScarcityBar from './components/ScarcityBar'
import LeadGrid from './components/LeadGrid'

function App() {
  return (
    <div className="app-root">
      {/* 1. SCARCITY ENGINE */}
      <ScarcityBar />

      {/* 2. SOVEREIGN HEADER */}
      <header className="vault-header">
        <div className="brand-title">
          VERIFUSE <span style={{ color: '#10b981' }}>// INTELLIGENCE</span>
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: '12px', color: '#ef4444' }}>
          SYSTEM STATUS: LIVE
        </div>
      </header>

      {/* 3. ASSET VAULT */}
      <main>
        <LeadGrid />
      </main>
    </div>
  )
}

export default App
"""

with open("src/App.tsx", "w") as f:
    f.write(app_tsx)

print("💎 SYSTEM REPAIR COMPLETE: CSS and Layout have been normalized.")
