"""
Recolhe dados intradiários (60min) de todos os ETFs via yfinance.
Sem API key, sem limites práticos.
Guarda um CSV fixo por ETF em data/hourly/SYMBOL.csv (sobrescreve).
"""

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols

DATA_HOURLY = Path("data/hourly")


def fetch_intraday(symbol: str, period: str = "60d", interval: str = "1h") -> pd.DataFrame:
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
    DATA_HOURLY.mkdir(parents=True, exist_ok=True)

    for symbol in get_all_symbols(cfg):
        try:
            df = fetch_intraday(symbol)
            df.to_csv(DATA_HOURLY / f"{symbol}.csv")
            print(f"[OK] {symbol} ({len(df)} registos)")
        except Exception as e:
            print(f"[ERRO] {symbol}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
