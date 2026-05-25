"""
Calcula o score multi-fator por ETF e gera data/reports/scores_latest.csv.

Score v0.1:
  momentum = ret_24h + ret_5d  (normalizado)
  trend    = trend_sma + macd_bullish  (0–1)
  risk     = 1 / vol_30  (normalizado)
  final    = 0.4*momentum + 0.3*trend + 0.3*risk
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")


def normalize_series(s: pd.Series) -> pd.Series:
    rng = s.max() - s.min()
    if rng == 0:
        return pd.Series(0.5, index=s.index)
    return (s - s.min()) / rng


def compute_score_for_etf(df: pd.DataFrame, weights: dict) -> pd.Series:
    mom_raw = (
        df.get("ret_24h", pd.Series(0, index=df.index)).fillna(0)
        + df.get("ret_5d", pd.Series(0, index=df.index)).fillna(0)
    )
    score_momentum = normalize_series(mom_raw)

    trend    = df.get("trend_sma",   pd.Series(0, index=df.index)).fillna(0)
    macd_b   = df.get("macd_bullish", pd.Series(0, index=df.index)).fillna(0)
    score_trend = (trend + macd_b) / 2.0

    vol          = df.get("vol_30", pd.Series(1e-6, index=df.index)).fillna(1e-6).clip(lower=1e-6)
    score_risk   = normalize_series(1.0 / vol)

    return (
        weights.get("momentum", 0.40) * score_momentum
        + weights.get("trend",  0.30) * score_trend
        + weights.get("risk",   0.30) * score_risk
    )


def build_summary(cfg: dict) -> pd.DataFrame:
    weights = cfg["params"]["weights"]
    rows = []

    for symbol in get_etfs(cfg):
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue

        df["score"] = compute_score_for_etf(df, weights)
        df.to_csv(path)

        last = df.iloc[-1]
        rows.append({
            "etf":         symbol,
            "close":       round(last.get("close",       np.nan), 4),
            "ret_1h":      round(last.get("ret_1h",      np.nan), 6),
            "ret_24h":     round(last.get("ret_24h",     np.nan), 6),
            "ret_5d":      round(last.get("ret_5d",      np.nan), 6),
            "vol_30":      round(last.get("vol_30",      np.nan), 6),
            "trend_sma":   int(last.get("trend_sma",     0)),
            "macd_bullish":int(last.get("macd_bullish",  0)),
            "drawdown":    round(last.get("drawdown",    np.nan), 6),
            "score":       round(last.get("score",       np.nan), 6),
        })

    return pd.DataFrame(rows).sort_values("score", ascending=False)


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)
    summary = build_summary(cfg)
    summary.to_csv(REPORTS / "scores_latest.csv", index=False)
    print(summary.to_string(index=False))
    print(f"\n[OK] {len(summary)} ETFs · scores guardados em data/reports/scores_latest.csv")


if __name__ == "__main__":
    main()
