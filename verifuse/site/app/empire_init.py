import os

# 1. APPLY THE FORENSIC THEME
empire_css = """
/* EMPIRE OVERHAUL */
.vault-header {
    background: #020617;
    border-bottom: 2px solid #10b981;
    padding: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.countdown-timer {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 800;
    color: #ef4444;
    padding: 4px 8px;
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid #ef4444;
    border-radius: 4px;
}

.decrypt-btn-sota {
    background: #10b981;
    color: #030712 !important;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 900;
    text-transform: uppercase;
    clip-path: polygon(0% 0%, 95% 0%, 100% 100%, 5% 100%);
    padding: 12px 25px;
    border: none;
    cursor: pointer;
    transition: all 0.2s ease;
}

.decrypt-btn-sota:hover {
    filter: brightness(1.2);
    box-shadow: 0 0 15px #10b981;
}

.redacted-field {
    background: rgba(148, 163, 184, 0.1);
    filter: blur(8px);
    user-select: none;
    color: transparent;
    border-radius: 4px;
}
"""

css_path = "src/App.css"
if os.path.exists(css_path):
    with open(css_path, "a") as f:
        f.write(empire_css)
    print("🏛️ VeriFuse Protocol: Phase 1 UI Deployed to src/App.css")
else:
    print(f"❌ Error: {css_path} not found. Ensure you are in the 'app' directory.")

