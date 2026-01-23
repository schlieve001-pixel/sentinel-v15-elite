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