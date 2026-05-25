"""
Lê os CSVs de data/hourly/, calcula métricas técnicas e guarda em data/daily/.
Agrega os dados de múltiplos snapshots do mesmo ETF num único ficheiro por ETF.
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG_PATH = Path("config/etfs.json")
DATA_HOURLY = Path("data/hourly")
DATA_DAILY = Path("data/daily")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def compute_macd(series: pd.Series, fast=12, slow=26, signal=9) -> tuple:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def compute_metrics(df: pd.DataFrame, vol_window: int = 30) -> pd.DataFrame:
    df = df.copy()
    df["close"] = df["close"].astype(float)

    # Retornos
    df["ret_1h"] = df["close"].pct_change(1)
    df["ret_24h"] = df["close"].pct_change(24)
    df["ret_5d"] = df["close"].pct_change(24 * 5)
    df["ret_20d"] = df["close"].pct_change(24 * 20)

    # Médias móveis e tendência
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["trend_sma"] = (df["sma20"] > df["sma50"]).astype(int)

    # MACD
    macd_line, signal_line = compute_macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_bullish"] = (df["macd"] > df["macd_signal"]).astype(int)

    # Volatilidade e risco
    df["vol_30"] = df["ret_1h"].rolling(vol_window * 24).std() * np.sqrt(24 * 252)
    df["drawdown"] = (df["close"] / df["close"].cummax()) - 1

    return df


def load_latest_per_etf(symbol: str) -> pd.DataFrame | None:
    """Carrega e concatena todos os snapshots existentes do ETF, removendo duplicados."""
    pattern = re.compile(rf"^{re.escape(symbol)}_\d{{8}}_\d{{4}}\.csv$")
    files = sorted(f for f in DATA_HOURLY.glob("*.csv") if pattern.match(f.name))
    if not files:
        return None
    frames = [pd.read_csv(f, index_col=0, parse_dates=True) for f in files]
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    return df


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)
    vol_window = cfg["params"]["vol_window"]

    symbols = cfg["benchmarks"] + cfg["etfs"]
    for symbol in symbols:
        df = load_latest_per_etf(symbol)
        if df is None:
            print(f"[SKIP] {symbol}: sem dados em data/hourly/")
            continue
        df = compute_metrics(df, vol_window=vol_window)
        out = DATA_DAILY / f"{symbol}.csv"
        df.to_csv(out)
        print(f"[OK] {symbol} -> {out.name} ({len(df)} linhas)")


if __name__ == "__main__":
    main()
