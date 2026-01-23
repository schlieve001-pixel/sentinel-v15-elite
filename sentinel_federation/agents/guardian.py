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
        msg = f"**BUYING** {ticker} @ ${price:.2f}\nSize: {size:.2f}x\nLogic: {reason}"
        self.notify("TRADE ENTRY", msg, 0x00ff00)

    def alert_sell(self, ticker, price, pnl, result):
        color = 0x00ff00 if result == "WIN" else 0xff0000
        msg = f"**SOLD** {ticker} @ ${price:.2f}\nResult: {result}\nPnL: ${pnl:.2f}"
        self.notify(f"TRADE EXIT ({result})", msg, color)

    def alert_risk(self, message):
        self.notify("🚨 RISK LOCKDOWN", message, 0xff0000)