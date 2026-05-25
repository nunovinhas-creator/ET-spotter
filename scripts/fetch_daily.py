"""
Recolhe 2 anos de dados diários OHLCV para todos os símbolos via yfinance.
Guarda em data/daily/SYMBOL.csv (sobrescreve).
"""

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols

DATA_DAILY = Path("data/daily")


def fetch_daily(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise RuntimeError(f"Sem dados para {symbol}")
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)

    for symbol in get_all_symbols(cfg):
        try:
            df = fetch_daily(symbol)
            df.to_csv(DATA_DAILY / f"{symbol}.csv")
            print(f"[OK] {symbol} ({len(df)} registos)")
        except Exception as e:
            print(f"[ERRO] {symbol}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
