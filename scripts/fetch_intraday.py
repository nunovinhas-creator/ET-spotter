"""
Recolhe dados intradiários (60min) de todos os ETFs via yfinance.
Sem API key, sem limites práticos. Guarda CSV em data/hourly/.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

CONFIG_PATH = Path("config/etfs.json")
DATA_HOURLY = Path("data/hourly")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_intraday(symbol: str, period: str = "60d", interval: str = "1h") -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise RuntimeError(f"Sem dados para {symbol}")
    df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]]
    return df


def main():
    cfg = load_config()
    DATA_HOURLY.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M")

    symbols = cfg["benchmarks"] + cfg["etfs"]
    for symbol in symbols:
        try:
            df = fetch_intraday(symbol)
            out = DATA_HOURLY / f"{symbol}_{ts}.csv"
            df.to_csv(out)
            print(f"[OK] {symbol} -> {out.name} ({len(df)} registos)")
        except Exception as e:
            print(f"[ERRO] {symbol}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
