import os

# DEFINING THE PERFECT EMPIRE LAYOUT
empire_app_code = """
import { useState, useEffect } from 'react'
import './App.css'
import LeadGrid from './components/LeadGrid'
import ScarcityBar from './components/ScarcityBar'

function App() {
  return (
    <div className="app-root" style={{ background: '#020617', minHeight: '100vh' }}>
      {/* 1. THE SCARCITY ENGINE (TOP) */}
      <ScarcityBar />

      {/* 2. THE SOVEREIGN HEADER */}
      <div className="vault-header">
        <div style={{ fontFamily: 'JetBrains Mono', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.05em' }}>
          VERIFUSE <span style={{ color: '#10b981' }}>// INTELLIGENCE</span>
        </div>
        <div className="countdown-timer">
          SYSTEM STATUS: LIVE
        </div>
      </div>

      {/* 3. THE ASSET VAULT */}
      <main style={{ padding: '20px' }}>
        <LeadGrid />
      </main>
    </div>
  )
}

export default App
"""

# OVERWRITE THE FILE
with open("src/App.tsx", "w") as f:
    f.write(empire_app_code)

print("💎 App.tsx has been re-forged. Structure is clean.")
