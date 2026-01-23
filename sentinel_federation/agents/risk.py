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