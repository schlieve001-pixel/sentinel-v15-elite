import os
import sys

# === SENTINEL FEDERATION V15: THE COMPLETE SUITE ===
# INCLUDES: Black Box Logic + Guardian Alerts + Dashboard GUI

BASE_DIR = "sentinel_federation"
DIRS = [f"{BASE_DIR}/core", f"{BASE_DIR}/agents", f"{BASE_DIR}/data"]

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"✅ INSTALLED: {path}")

# 1. CREATE DIRECTORIES
for d in DIRS:
    if not os.path.exists(d): os.makedirs(d)

# 2. CONFIGURATION (With Webhook)
write_file(f"{BASE_DIR}/core/config.py", """
class SystemConfig:
    # --- COMMUNICATIONS ---
    # PASTE DISCORD WEBHOOK URL BELOW TO ENABLE PHONE ALERTS
    DISCORD_WEBHOOK_URL = "" 
    
    # --- STRATEGY SETTINGS ---
    VOLATILITY_LOOKBACK = 14
    BASE_Z_ENTRY = -1.5
    BASE_RSI_ENTRY = 35
    
    # --- RISK MANAGEMENT ---
    MAX_KELLY_FRACTION = 0.5   
    MAX_CAPITAL_USAGE  = 0.25  
    MAX_DAILY_DRAWDOWN = -0.03 
    
    # --- REALITY SIMULATION ---
    SIMULATE_SLIPPAGE = 0.001 
    SIMULATE_FEES     = 1.00  
""")

# 3. GUARDIAN AGENT (Alerts)
write_file(f"{BASE_DIR}/agents/guardian.py", """
import requests
import json
from datetime import datetime
from sentinel_federation.core.config import SystemConfig

class GuardianAgent:
    def __init__(self):
        self.url = SystemConfig.DISCORD_WEBHOOK_URL
        self.enabled = len(self.url) > 10

    def notify(self, title, message, color=0x00ff00):
        if not self.enabled: return
        payload = {
            "username": "SENTINEL COMMAND",
            "embeds": [{
                "title": f"📢 {title}",
                "description": message,
                "color": color,
                "footer": {"text": f"Time: {datetime.now().strftime('%H:%M:%S')}"}
            }]
        }
        try: requests.post(self.url, json=payload, timeout=2)
        except: pass

    def alert_buy(self, ticker, price, size, reason):
        msg = f"**BUYING** {ticker} @ ${price:.2f}\\nSize: {size:.2f}x\\nLogic: {reason}"
        self.notify("TRADE ENTRY", msg, 0x00ff00)

    def alert_sell(self, ticker, price, pnl, result):
        color = 0x00ff00 if result == "WIN" else 0xff0000
        msg = f"**SOLD** {ticker} @ ${price:.2f}\\nResult: {result}\\nPnL: ${pnl:.2f}"
        self.notify(f"TRADE EXIT ({result})", msg, color)

    def alert_risk(self, message):
        self.notify("🚨 RISK LOCKDOWN", message, 0xff0000)
""")

# 4. RISK MANAGER
write_file(f"{BASE_DIR}/agents/risk.py", """
from datetime import datetime
from sentinel_federation.core.config import SystemConfig

class RiskManager:
    def __init__(self):
        self.daily_pnl = 0.0
        self.current_date = datetime.now().date()
        self.circuit_breaker_active = False

    def check_health(self):
        if datetime.now().date() != self.current_date:
            self.daily_pnl = 0.0
            self.current_date = datetime.now().date()
            self.circuit_breaker_active = False
            return True, "NEW_DAY"

        if self.circuit_breaker_active: return False, "LOCKED"
        
        if self.daily_pnl < (100000 * SystemConfig.MAX_DAILY_DRAWDOWN):
            self.circuit_breaker_active = True
            return False, f"MAX_LOSS_HIT ({self.daily_pnl:.2f})"

        return True, "GREEN"

    def update_pnl(self, amount):
        self.daily_pnl += amount
""")

# 5. GHOST BROKER (With Ledger)
write_file(f"{BASE_DIR}/agents/broker.py", """
import datetime
import os
import csv
from sentinel_federation.core.config import SystemConfig

class GhostBroker:
    def __init__(self):
        self.positions = {} 
        self.cash = 100000.00
        self.ledger_path = "sentinel_federation/data/ledger.csv"
        self._init_ledger()

    def _init_ledger(self):
        if not os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'w') as f:
                f.write("timestamp,ticker,action,price,qty,fees,balance\\n")

    def get_position(self, ticker): return self.positions.get(ticker)

    def execute_order(self, ticker, action, current_price, size_multiplier=1.0):
        slippage = current_price * SystemConfig.SIMULATE_SLIPPAGE
        
        if action == "BUY":
            fill_price = current_price + slippage
            cost = 10000 * size_multiplier 
            qty = cost / fill_price
            self.positions[ticker] = {"qty": qty, "entry": fill_price, "date": str(datetime.datetime.now())}
            self.cash -= cost
            self._log(ticker, "BUY", fill_price, qty, 0)
            return fill_price, qty
            
        elif action == "SELL":
            if ticker not in self.positions: return 0, 0
            fill_price = current_price - slippage
            pos = self.positions.pop(ticker)
            proceeds = pos['qty'] * fill_price - SystemConfig.SIMULATE_FEES
            self.cash += proceeds
            profit_amt = proceeds - (pos['qty'] * pos['entry'])
            self._log(ticker, "SELL", fill_price, pos['qty'], SystemConfig.SIMULATE_FEES)
            return fill_price, profit_amt
        return 0, 0

    def _log(self, ticker, action, price, qty, fees):
        with open(self.ledger_path, 'a') as f:
            f.write(f"{datetime.datetime.now()},{ticker},{action},{price:.2f},{qty:.4f},{fees:.2f},{self.cash:.2f}\\n")
""")

# 6. OBSERVER (Physics)
write_file(f"{BASE_DIR}/agents/observer.py", """
import pandas as pd
import numpy as np

class ObserverAgent:
    def analyze_market_state(self, df_spy, df_nvda):
        df = pd.merge(df_spy, df_nvda, on='timestamp', suffixes=('_spy', '_nvda')).dropna()
        
        df['ret'] = np.log(df['close_nvda'] / df['close_nvda'].shift(1))
        df['z_score'] = (df['ret'] - df['ret'].rolling(20).mean()) / df['ret'].rolling(20).std()
        
        df['date_str'] = df['timestamp'].dt.date.astype(str)
        df['pv'] = df['close_nvda'] * df['volume_nvda']
        df['vwap'] = df.groupby('date_str')['pv'].cumsum() / df.groupby('date_str')['volume_nvda'].cumsum()
        df['vwap_dist'] = (df['close_nvda'] - df['vwap']) / df['vwap']

        high, low, close = df['high_nvda'], df['low_nvda'], df['close_nvda'].shift(1)
        tr = pd.concat([high-low, (high-close).abs(), (low-close).abs()], axis=1).max(axis=1)
        df['atr_pct'] = tr.rolling(14).mean() / df['close_nvda']

        delta = df['close_nvda'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        df['sma_200'] = df['close_nvda'].rolling(200).mean()
        df['trend_ok'] = df['close_nvda'] > df['sma_200']
        return df.iloc[-1]
""")

# 7. STRATEGIST (Logic)
write_file(f"{BASE_DIR}/agents/strategist.py", """
class StrategistAgent:
    def get_signal(self, physics, position=None):
        z = physics['z_score']
        rsi = physics['rsi']
        vwap_dist = physics['vwap_dist']
        atr_pct = physics['atr_pct']
        trend_ok = physics['trend_ok']
        price = physics['close_nvda']
        
        if position:
            entry_price = position['entry']
            pnl_pct = (price - entry_price) / entry_price
            target_pct = 0.02 if atr_pct > 0.01 else 0.01
            stop_pct = -0.02
            
            if pnl_pct > target_pct: return "SELL", f"TARGET (+{pnl_pct*100:.1f}%)"
            if pnl_pct < stop_pct: return "SELL", f"STOP (-{pnl_pct*100:.1f}%)"
            if rsi > 75: return "SELL", f"RSI_HOT ({rsi:.0f})"
            return "HOLD", "RIDING"

        is_volatile = atr_pct > 0.005
        required_z = -2.0 if is_volatile else -1.5
        required_rsi = 30 if is_volatile else 35
        
        if vwap_dist < 0:
            if z < required_z and rsi < required_rsi:
                if trend_ok: return "BUY", f"BULL_DIP (Z:{z:.2f})"
                elif z < -3.0: return "BUY", f"CRASH_BUY (Z:{z:.2f})"
        return "HOLD", ""
""")

# 8. ORACLE (Brain)
write_file(f"{BASE_DIR}/agents/oracle.py", """
import json
import os
import pandas as pd

class OracleAgent:
    def __init__(self):
        self.journal_path = "sentinel_federation/data/journal.json"
        
    def consult(self, physics, ticker):
        history = self._read_journal()
        if len(history) < 5: return True, "LEARNING", 1.0

        df = pd.DataFrame(history)
        wins = len(df[df['result'] == "WIN"])
        losses = len(df[df['result'] == "LOSS"])
        if wins + losses == 0: return True, "NO_DATA", 1.0
        
        win_rate = wins / (wins + losses)
        avg_win = df[df['result'] == "WIN"]['pnl'].mean()
        avg_loss = abs(df[df['result'] == "LOSS"]['pnl'].mean())
        
        if pd.isna(avg_win) or pd.isna(avg_loss) or avg_loss == 0: return True, "MATH_WAIT", 1.0
        
        wl_ratio = avg_win / avg_loss
        kelly = (win_rate * wl_ratio - (1 - win_rate)) / wl_ratio
        safe_kelly = max(0.0, kelly * 0.5)
        
        mult = max(0.5, min(safe_kelly * 10, 3.0))
        if safe_kelly <= 0: return False, "BAD_EDGE", 0.0
        return True, "APPROVED", mult

    def record_outcome(self, data):
        h = self._read_journal()
        h.append(data)
        with open(self.journal_path, 'w') as f: json.dump(h, f, indent=2)

    def _read_journal(self):
        if not os.path.exists(self.journal_path): return []
        try:
            with open(self.journal_path, 'r') as f: return json.load(f)
        except: return []
""")

# 9. MONITOR (The Engine)
write_file("sentinel_squad_monitor.py", """
import time
import sys
import os
import pytz
import yfinance as yf
from datetime import datetime, time as dtime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from sentinel_federation.agents.observer import ObserverAgent
from sentinel_federation.agents.strategist import StrategistAgent
from sentinel_federation.agents.oracle import OracleAgent
from sentinel_federation.agents.broker import GhostBroker
from sentinel_federation.agents.risk import RiskManager
from sentinel_federation.agents.guardian import GuardianAgent

TICKERS = ["NVDA", "AMD"]
NY_TZ = pytz.timezone('America/New_York')

def fetch_data_robust(symbol):
    for i in range(3):
        try:
            df = yf.download(symbol, period="60d", interval="15m", progress=False)
            spy = yf.download("SPY", period="60d", interval="15m", progress=False)
            if df.empty or spy.empty: continue
            for d in [df, spy]:
                if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
                d.reset_index(inplace=True)
                d.columns = [c.lower() for c in d.columns]
                d.rename(columns={'date': 'timestamp', 'datetime': 'timestamp'}, inplace=True)
            return spy, df
        except: time.sleep(2)
    return None, None

def main():
    print("\\033[H\\033[J") 
    print("="*60)
    print("      🦅 SENTINEL V15: THE FEDERATION 🦅")
    print("      [GUARDIAN] [RISK] [BROKER] [DASHBOARD-READY]")
    print("="*60)
    
    broker = GhostBroker()
    oracle = OracleAgent()
    risk_manager = RiskManager()
    guardian = GuardianAgent()
    guardian.notify("SYSTEM BOOT", "Sentinel V15 is Online.", 0x0000ff)
    
    squad = {}
    for t in TICKERS:
        squad[t] = {"observer": ObserverAgent(), "strategist": StrategistAgent()}

    while True:
        try:
            risk_status, risk_msg = risk_manager.check_health()
            if not risk_status:
                print(f"\\n❌ RISK ALERT: {risk_msg}")
                guardian.alert_risk(risk_msg)
                time.sleep(3600)
                continue

            now_ny = datetime.now(NY_TZ).time()
            is_open = dtime(9,45) < now_ny < dtime(15,55)
            status = "OPEN" if is_open else "CLOSED"
            
            print(f"\\n>>> [{datetime.now().strftime('%H:%M:%S')}] MKT:{status} | CASH:${broker.cash:.0f} | SCAN...", end="")
            
            for ticker in TICKERS:
                spy_df, asset_df = fetch_data_robust(ticker)
                if spy_df is not None and asset_df is not None:
                    physics = squad[ticker]["observer"].analyze_market_state(spy_df, asset_df)
                    current_pos = broker.get_position(ticker)
                    signal, reason = squad[ticker]["strategist"].get_signal(physics, current_pos)
                    
                    mult = 1.0
                    if signal == "BUY":
                        ok, msg, mult = oracle.consult(physics, ticker)
                        if not ok: signal, reason = "HOLD", msg
                    
                    if not is_open and signal == "BUY": signal, reason = "HOLD", "MARKET_CLOSED"

                    if signal == "BUY" and not current_pos:
                        fill, qty = broker.execute_order(ticker, "BUY", physics['close_nvda'], mult)
                        print(f"\\n    ⚡ BOUGHT {ticker} @ ${fill:.2f}")
                        guardian.alert_buy(ticker, fill, mult, reason)
                    
                    elif signal == "SELL" and current_pos:
                        fill, profit_amt = broker.execute_order(ticker, "SELL", physics['close_nvda'])
                        res = "WIN" if profit_amt > 0 else "LOSS"
                        print(f"\\n    💰 SOLD {ticker} | PnL: ${profit_amt:.2f}")
                        guardian.alert_sell(ticker, fill, profit_amt, res)
                        risk_manager.update_pnl(profit_amt)
                        oracle.record_outcome({
                            "ticker": ticker, "date": str(physics['timestamp']),
                            "z": float(physics['z_score']), "result": res, "pnl": profit_amt
                        })

                    p = physics['close_nvda']
                    z = physics['z_score']
                    pos_str = "\\033[92mLONG\\033[0m" if current_pos else "FLAT"
                    print(f"\\n    [{ticker}] ${p:.2f} | Z:{z:.2f} | {pos_str}", end="")
                else: print(f"\\n    [{ticker}] ...", end="")
            print("\\n" + "-"*60)
            time.sleep(60) 
        except KeyboardInterrupt: break
        except Exception as e: 
            print(f"\\n⚠️ ERROR: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
""")

# 10. THE DASHBOARD GUI (sentinel_dashboard.py)
write_file("sentinel_dashboard.py", """
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
""")

print("\n🚀 V15 FULL SUITE INSTALLED.")
print("1. RUN INSTALLER: python install_v15.py")
print("2. START MONITOR: python sentinel_squad_monitor.py")
print("3. START DASHBOARD: streamlit run sentinel_dashboard.py")

