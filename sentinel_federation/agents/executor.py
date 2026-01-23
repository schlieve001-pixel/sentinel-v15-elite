from sentinel_federation.core.config import SystemConfig

class ExecutionAgent:
    def __init__(self):
        self.balance = SystemConfig.PAPER_BALANCE
        self.position = 0
        self.entry_price = 0
        self.trade_history = []
        self.slippage = 0.0005 
        print(f"    [EXECUTOR] Online. Balance: ${self.balance:,.2f} | Slippage Mode: ON")

    def execute_order(self, action, price, timestamp, reason):
        if action == "BUY" and self.position == 0:
            execution_price = price * (1 + self.slippage)
            self.position = self.balance / execution_price
            self.entry_price = execution_price
            self.balance = 0
            print(f"    🟢 [EXECUTE] BUY  @ ${execution_price:.2f} | Reason: {reason}")
            
        elif action == "SELL" and self.position > 0:
            execution_price = price * (1 - self.slippage)
            revenue = self.position * execution_price
            pnl = revenue - (self.position * self.entry_price)
            self.balance = revenue
            self.trade_history.append({'pnl': pnl, 'reason': reason})
            print(f"    🔴 [EXECUTE] SELL @ ${execution_price:.2f} | PnL: ${pnl:,.2f} | Reason: {reason}")
            print(f"       [BALANCE] Current: ${self.balance:,.2f}")
            self.position = 0
