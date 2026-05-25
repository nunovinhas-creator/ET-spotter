"""
Recolhe dados intradiários (60min) de todos os ETFs via Alpha Vantage.
Guarda um CSV por ETF em data/hourly/ com timestamp UTC no nome.
"""

import os
import json
import requests
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
BASE_URL = "https://www.alphavantage.co/query"
CONFIG_PATH = Path("config/etfs.json")
DATA_HOURLY = Path("data/hourly")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def fetch_intraday(symbol: str, interval: str = "60min") -> pd.DataFrame:
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "outputsize": "compact",
        "apikey": API_KEY,
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "Note" in data:
        raise RuntimeError(f"Alpha Vantage rate limit: {data['Note']}")
    if "Error Message" in data:
        raise RuntimeError(f"Alpha Vantage error for {symbol}: {data['Error Message']}")

    key = next((k for k in data if "Time Series" in k), None)
    if key is None:
        raise RuntimeError(f"Resposta inesperada para {symbol}: {list(data.keys())}")

    df = pd.DataFrame.from_dict(data[key], orient="index")
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df.astype(float)
    return df


def main():
    if not API_KEY:
        print("ERRO: ALPHAVANTAGE_API_KEY não definida.", file=sys.stderr)
        sys.exit(1)

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
