"""
Lê data/hourly/SYMBOL.csv, calcula métricas técnicas e guarda em data/daily/SYMBOL.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols

DATA_HOURLY = Path("data/hourly")
DATA_DAILY  = Path("data/daily")


def compute_macd(series: pd.Series, fast=12, slow=26, signal=9) -> tuple:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    return macd_line, macd_line.ewm(span=signal, adjust=False).mean()


def compute_metrics(df: pd.DataFrame, vol_window: int = 30) -> pd.DataFrame:
    df = df.copy()
    df["close"] = df["close"].astype(float)

    df["ret_1h"]  = df["close"].pct_change(1)
    df["ret_24h"] = df["close"].pct_change(24)
    df["ret_5d"]  = df["close"].pct_change(24 * 5)
    df["ret_20d"] = df["close"].pct_change(24 * 20)

    df["sma20"]     = df["close"].rolling(20).mean()
    df["sma50"]     = df["close"].rolling(50).mean()
    df["trend_sma"] = (df["sma20"] > df["sma50"]).astype(int)

    macd_line, signal_line = compute_macd(df["close"])
    df["macd"]         = macd_line
    df["macd_signal"]  = signal_line
    df["macd_bullish"] = (df["macd"] > df["macd_signal"]).astype(int)

    df["vol_30"]   = df["ret_1h"].rolling(vol_window * 24).std() * np.sqrt(24 * 252)
    df["drawdown"] = (df["close"] / df["close"].cummax()) - 1

    return df


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)
    vol_window = cfg["params"]["vol_window"]

    for symbol in get_all_symbols(cfg):
        path = DATA_HOURLY / f"{symbol}.csv"
        if not path.exists():
            print(f"[SKIP] {symbol}: sem dados em data/hourly/")
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        df = compute_metrics(df, vol_window=vol_window)
        df.to_csv(DATA_DAILY / f"{symbol}.csv")
        print(f"[OK] {symbol} ({len(df)} linhas)")


if __name__ == "__main__":
    main()
