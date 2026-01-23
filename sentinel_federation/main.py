import pandas as pd
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sentinel_federation.core.config import SystemConfig
from sentinel_federation.agents.observer import ObserverAgent
from sentinel_federation.agents.strategist import StrategistAgent
from sentinel_federation.agents.executor import ExecutionAgent
from sentinel_federation.agents.oracle import OracleAgent

def run_asset_simulation(ticker, spy_df, oracle):
    file_path = f"sentinel_federation/data/{ticker.lower()}_prices.csv"
    if not os.path.exists(file_path): return 0.0

    df = pd.read_csv(file_path, parse_dates=['timestamp']).sort_values('timestamp')
    df['timestamp'] = df['timestamp'].dt.tz_localize(None)

    common = pd.merge(spy_df, df, on='timestamp', suffixes=('_spy', '_nvda'))['timestamp']
    spy_subset = spy_df[spy_df['timestamp'].isin(common)].copy()
    asset_subset = df[df['timestamp'].isin(common)].copy()

    observer = ObserverAgent()
    strategist = StrategistAgent()
    executor = ExecutionAgent() 
    
    print(f"\n>>> DEPLOYING SQUAD ON [{ticker}]...")
    
    window = 300
    active_trade_start = None
    active_physics = None

    for i in range(window, len(common)):
        current_spy = spy_subset.iloc[i-window:i+1]
        current_asset = asset_subset.iloc[i-window:i+1]
        
        physics = observer.analyze_market_state(current_spy, current_asset)
        signal, reason = strategist.get_signal(physics)
        
        # --- THE AI INTERVENTION ---
        if signal == "BUY":
            # Ask Gemini if we should proceed
            allowed = oracle.consult(physics)
            if not allowed:
                signal = "HOLD" # AI Vetoed the trade

        # Execute
        if signal in ["BUY", "SELL"]:
            executor.execute_order(signal, physics['close_nvda'], physics['timestamp'], reason)
            
            # MEMORY RECORDING
            if signal == "BUY":
                active_trade_start = physics['close_nvda']
                active_physics = {
                    'z': float(physics['z_score']),
                    'rvol': float(physics.get('rvol', 0)),
                    'date': str(physics['timestamp'])
                }
            elif signal == "SELL" and active_trade_start:
                # Calculate Result
                pnl = (physics['close_nvda'] - active_trade_start) / active_trade_start
                result = "WIN" if pnl > 0 else "LOSS"
                
                # Teach the AI
                lesson = active_physics
                lesson['result'] = result
                lesson['pnl'] = pnl
                oracle.record_outcome(lesson)
                active_trade_start = None

    profit = executor.balance - SystemConfig.PAPER_BALANCE
    print(f"    [{ticker}] NET RESULT: ${profit:,.2f}")
    return profit

def run_federation():
    print("="*60 + "\n   🏛️ SENTINEL FEDERATION v4.0 (AI-ENHANCED)\n" + "="*60)
    
    spy_file = SystemConfig.SPY_FILE
    if not os.path.exists(spy_file): return
    spy = pd.read_csv(spy_file, parse_dates=['timestamp']).sort_values('timestamp')
    spy['timestamp'] = spy['timestamp'].dt.tz_localize(None)
    
    # Initialize the Global Brain
    oracle = OracleAgent()
    
    tickers = ["NVDA", "AMD"] 
    total_profit = 0.0
    
    for t in tickers:
        pnl = run_asset_simulation(t, spy, oracle)
        total_profit += pnl
        
    print("\n" + "="*60)
    print(f"    FEDERATION TOTAL PROFIT: ${total_profit:,.2f}")
    print("="*60)

if __name__ == "__main__":
    run_federation()
