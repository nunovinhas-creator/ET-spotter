"""
Lê data/daily/SYMBOL.csv (dados diários), calcula métricas técnicas e guarda no mesmo ficheiro.

Métricas calculadas:
  - Retornos: ret_1d, ret_5d, ret_21d, ret_63d, ret_126d
  - Tendência: sma20, sma50, sma200, trend_sma, above_sma200
  - MACD(12,26,9) diário, macd_bullish
  - RSI(14) via Wilder EWM
  - ADX(14) via Wilder EWM
  - Volatilidade anualizada: vol_21
  - Sharpe 63 dias
  - Drawdown
  - Força relativa vs SPY: rs_ratio, rs_mom_21, rs_mom_63, rs_positive
  - Calmar 63d: retorno anualizado / max drawdown 63d
"""

import sys
from pathlib import Path
from math import sqrt

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols
from paths import DATA_DAILY


def compute_macd(series: pd.Series, fast=12, slow=26, signal=9) -> tuple:
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs    = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    plus_dm  = high - prev_high
    minus_dm = prev_low - low
    plus_dm  = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    alpha = 1 / period
    atr      = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1e-10)
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1e-10)

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10))
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx


def validate_data(df: pd.DataFrame, symbol: str) -> None:
    """Imprime avisos para gaps > 7 dias ou taxa de NaN > 5%."""
    if df.index.dtype == "datetime64[ns]":
        diffs = df.index.to_series().diff().dropna()
        max_gap = diffs.max()
        if pd.notna(max_gap) and max_gap > pd.Timedelta(days=7):
            print(f"[AVISO] {symbol}: gap de {max_gap.days} dias detectado")

    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            nan_rate = df[col].isna().mean()
            if nan_rate > 0.05:
                print(f"[AVISO] {symbol}: {col} tem {nan_rate:.1%} de NaN")


def compute_metrics(df: pd.DataFrame, spy_close: pd.Series = None) -> pd.DataFrame:
    df = df.copy()
    df["close"] = df["close"].astype(float)
    close = df["close"]

    # ── Retornos ───────────────────────────────────────────────────────────────
    df["ret_1d"]   = close.pct_change(1)
    df["ret_5d"]   = close.pct_change(5)
    df["ret_21d"]  = close.pct_change(21)
    df["ret_63d"]  = close.pct_change(63)
    df["ret_126d"] = close.pct_change(126)
    df["ret_252d"] = close.pct_change(252)

    # ── Tendência ──────────────────────────────────────────────────────────────
    df["sma20"]       = close.rolling(20).mean()
    df["sma50"]       = close.rolling(50).mean()
    df["sma200"]      = close.rolling(200).mean()
    df["trend_sma"]   = (df["sma20"] > df["sma50"]).astype(int)
    df["above_sma200"] = (close > df["sma200"]).astype(int)

    # ── MACD(12,26,9) ──────────────────────────────────────────────────────────
    macd_line, signal_line = compute_macd(close)
    df["macd"]         = macd_line
    df["macd_signal"]  = signal_line
    df["macd_bullish"] = (macd_line > signal_line).astype(int)

    # ── RSI(14) ────────────────────────────────────────────────────────────────
    df["rsi"] = compute_rsi(close, period=14)

    # ── ADX(14) ────────────────────────────────────────────────────────────────
    if "high" in df.columns and "low" in df.columns:
        df["adx"] = compute_adx(
            df["high"].astype(float),
            df["low"].astype(float),
            close,
            period=14,
        )
    else:
        df["adx"] = np.nan

    # ── Volatilidade anualizada 21d ───────────────────────────────────────────
    df["vol_21"] = df["ret_1d"].rolling(21).std() * sqrt(252)

    # ── Sharpe 63d ────────────────────────────────────────────────────────────
    mean_63 = df["ret_1d"].rolling(63).mean()
    std_63  = df["ret_1d"].rolling(63).std()
    df["sharpe_63"] = (mean_63 * 252) / (std_63 * sqrt(252)).replace(0, 1e-10)

    # ── Drawdown ───────────────────────────────────────────────────────────────
    df["drawdown"] = (close / close.cummax()) - 1

    # ── Calmar 63d: retorno anualizado / max drawdown 63d ─────────────────────
    # Mais estável que Sharpe com amostras curtas (SE de Sharpe com n=63 é ~0.13)
    rolling_high_63 = close.rolling(63).max()
    dd_daily_63     = (close - rolling_high_63) / rolling_high_63  # ≤ 0
    max_dd_63       = dd_daily_63.rolling(63).min()                 # pior drawdown
    ann_ret_63      = close.pct_change(63) * (252 / 63)
    df["calmar_63"] = (ann_ret_63 / (-max_dd_63 + 1e-10)).clip(-10, 10)

    # ── Força relativa vs SPY ─────────────────────────────────────────────────
    if spy_close is not None and not spy_close.empty:
        spy_aligned = spy_close.reindex(df.index).ffill()
        rs_ratio        = close / spy_aligned.replace(0, np.nan)
        df["rs_ratio"]    = rs_ratio
        df["rs_mom_21"]   = rs_ratio.pct_change(21)
        df["rs_mom_63"]   = rs_ratio.pct_change(63)
        df["rs_mom_126d"] = rs_ratio.pct_change(126)
        df["rs_positive"] = (df["rs_mom_63"] > 0).astype(int)
    else:
        df["rs_ratio"]    = np.nan
        df["rs_mom_21"]   = np.nan
        df["rs_mom_63"]   = np.nan
        df["rs_mom_126d"] = np.nan
        df["rs_positive"] = 0

    return df


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)

    # Carrega SPY para força relativa
    spy_close = None
    spy_path  = DATA_DAILY / "SPY.csv"
    if spy_path.exists():
        spy_df = pd.read_csv(spy_path, index_col=0, parse_dates=True)
        if not spy_df.empty and "close" in spy_df.columns:
            spy_close = spy_df["close"].astype(float)

    for symbol in get_all_symbols(cfg):
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            print(f"[SKIP] {symbol}: sem dados em data/daily/")
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue

        validate_data(df, symbol)
        df = compute_metrics(df, spy_close=spy_close)
        df.to_csv(path)
        print(f"[OK] {symbol} ({len(df)} linhas)")


if __name__ == "__main__":
    main()
