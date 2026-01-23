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
                f.write("timestamp,ticker,action,price,qty,fees,balance\n")

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
            f.write(f"{datetime.datetime.now()},{ticker},{action},{price:.2f},{qty:.4f},{fees:.2f},{self.cash:.2f}\n")