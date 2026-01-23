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