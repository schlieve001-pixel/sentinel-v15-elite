import streamlit as st
import pandas as pd
import json
import os
import time
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="Sentinel V15 Command", layout="wide", page_icon="🦅", initial_sidebar_state="collapsed")
st.markdown("<style>.stApp {background-color: #0e1117;} .metric-card {background-color: #1e2127; padding: 15px; border-radius: 10px; border: 1px solid #303339; margin-bottom: 10px;}</style>", unsafe_allow_html=True)

BASE_DIR = "sentinel_federation/data"
JOURNAL_PATH = f"{BASE_DIR}/journal.json"
LEDGER_PATH = f"{BASE_DIR}/ledger.csv"

def load_data():
    if os.path.exists(LEDGER_PATH):
        try: ledger = pd.read_csv(LEDGER_PATH); ledger['timestamp'] = pd.to_datetime(ledger['timestamp'])
        except: ledger = pd.DataFrame(columns=['timestamp', 'balance'])
    else: ledger = pd.DataFrame({'timestamp': [datetime.now()], 'balance': [100000]})

    if os.path.exists(JOURNAL_PATH):
        try: 
            with open(JOURNAL_PATH, 'r') as f: trades = pd.DataFrame(json.load(f))
        except: trades = pd.DataFrame()
    else: trades = pd.DataFrame()
    return ledger, trades

def main():
    st.title("🦅 SENTINEL V15 COMMAND CENTER")
    if st.button("🔄 REFRESH DATA"): st.rerun()

    ledger, trades = load_data()
    curr_eq = ledger['balance'].iloc[-1] if not ledger.empty else 100000
    start_eq = ledger['balance'].iloc[0] if not ledger.empty else 100000
    pnl = curr_eq - start_eq
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 EQUITY", f"${curr_eq:,.2f}", f"{pnl:,.2f}")
    
    wr = 0.0
    if not trades.empty:
        wins = len(trades[trades['result'] == 'WIN'])
        wr = (wins / len(trades)) * 100
    c2.metric("🏆 WIN RATE", f"{wr:.1f}%", f"{len(trades)} Trades")
    c3.metric("🛡️ STATUS", "ACTIVE", "Guardian Online")

    st.markdown("### 📈 Equity Curve")
    if not ledger.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ledger['timestamp'], y=ledger['balance'], mode='lines', line=dict(color='#00ff00'), fill='tozeroy'))
        fig.update_layout(paper_bgcolor='#0e1117', plot_bgcolor='#1e2127', font=dict(color='white'), height=300, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 📜 Event Log")
    if not ledger.empty:
        st.dataframe(ledger.sort_values('timestamp', ascending=False).head(10), use_container_width=True, hide_index=True)

    time.sleep(5)
    st.rerun()

if __name__ == "__main__":
    main()