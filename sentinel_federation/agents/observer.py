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