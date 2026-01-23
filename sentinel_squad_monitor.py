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
    print("\033[H\033[J") 
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
                print(f"\n❌ RISK ALERT: {risk_msg}")
                guardian.alert_risk(risk_msg)
                time.sleep(3600)
                continue

            now_ny = datetime.now(NY_TZ).time()
            is_open = dtime(9,45) < now_ny < dtime(15,55)
            status = "OPEN" if is_open else "CLOSED"
            
            print(f"\n>>> [{datetime.now().strftime('%H:%M:%S')}] MKT:{status} | CASH:${broker.cash:.0f} | SCAN...", end="")
            
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
                        print(f"\n    ⚡ BOUGHT {ticker} @ ${fill:.2f}")
                        guardian.alert_buy(ticker, fill, mult, reason)
                    
                    elif signal == "SELL" and current_pos:
                        fill, profit_amt = broker.execute_order(ticker, "SELL", physics['close_nvda'])
                        res = "WIN" if profit_amt > 0 else "LOSS"
                        print(f"\n    💰 SOLD {ticker} | PnL: ${profit_amt:.2f}")
                        guardian.alert_sell(ticker, fill, profit_amt, res)
                        risk_manager.update_pnl(profit_amt)
                        oracle.record_outcome({
                            "ticker": ticker, "date": str(physics['timestamp']),
                            "z": float(physics['z_score']), "result": res, "pnl": profit_amt
                        })

                    p = physics['close_nvda']
                    z = physics['z_score']
                    pos_str = "\033[92mLONG\033[0m" if current_pos else "FLAT"
                    print(f"\n    [{ticker}] ${p:.2f} | Z:{z:.2f} | {pos_str}", end="")
                else: print(f"\n    [{ticker}] ...", end="")
            print("\n" + "-"*60)
            time.sleep(60) 
        except KeyboardInterrupt: break
        except Exception as e: 
            print(f"\n⚠️ ERROR: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()