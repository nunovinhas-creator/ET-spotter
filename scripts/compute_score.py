"""
Calcula o score multi-fator para cada ETF e gera data/reports/scores_latest.csv.

Score v0.1:
  score_momentum = ret_24h + ret_5d  (normalizados)
  score_trend    = trend_sma + macd_bullish  (0/1 each)
  score_risk     = 1 / (vol_30 + ε)  (inverso da volatilidade)
  score_final    = 0.4*momentum + 0.3*trend + 0.3*risk
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

CONFIG_PATH = Path("config/etfs.json")
DATA_DAILY = Path("data/daily")
REPORTS = Path("data/reports")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def normalize_series(s: pd.Series) -> pd.Series:
    """Normaliza para [0, 1] usando min-max. Devolve 0.5 se constante."""
    rng = s.max() - s.min()
    if rng == 0:
        return pd.Series(0.5, index=s.index)
    return (s - s.min()) / rng


def compute_score_for_etf(df: pd.DataFrame, weights: dict) -> pd.Series:
    df = df.copy()

    # Momentum (normalizado por janela)
    mom_raw = df.get("ret_24h", pd.Series(0, index=df.index)).fillna(0) + \
              df.get("ret_5d", pd.Series(0, index=df.index)).fillna(0)
    score_momentum = normalize_series(mom_raw)

    # Tendência (já binário 0/1, normaliza para [0,1])
    trend = df.get("trend_sma", pd.Series(0, index=df.index)).fillna(0)
    macd_bull = df.get("macd_bullish", pd.Series(0, index=df.index)).fillna(0)
    score_trend = (trend + macd_bull) / 2.0

    # Risco (inverso da volatilidade, normalizado)
    vol = df.get("vol_30", pd.Series(1e-6, index=df.index)).fillna(1e-6).clip(lower=1e-6)
    score_risk = normalize_series(1.0 / vol)

    w_m = weights.get("momentum", 0.40)
    w_t = weights.get("trend", 0.30)
    w_r = weights.get("risk", 0.30)

    score = w_m * score_momentum + w_t * score_trend + w_r * score_risk
    return score


def build_summary(cfg: dict) -> pd.DataFrame:
    weights = cfg["params"]["weights"]
    symbols = cfg["etfs"]
    rows = []

    for symbol in symbols:
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
            "etf": symbol,
            "close": round(last.get("close", np.nan), 4),
            "ret_1h": round(last.get("ret_1h", np.nan), 6),
            "ret_24h": round(last.get("ret_24h", np.nan), 6),
            "ret_5d": round(last.get("ret_5d", np.nan), 6),
            "vol_30": round(last.get("vol_30", np.nan), 6),
            "trend_sma": int(last.get("trend_sma", 0)),
            "macd_bullish": int(last.get("macd_bullish", 0)),
            "drawdown": round(last.get("drawdown", np.nan), 6),
            "score": round(last.get("score", np.nan), 6),
        })

    summary = pd.DataFrame(rows).sort_values("score", ascending=False)
    return summary


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)
    summary = build_summary(cfg)
    out = REPORTS / "scores_latest.csv"
    summary.to_csv(out, index=False)
    print(summary.to_string(index=False))
    print(f"\n[OK] Scores guardados em {out}")


if __name__ == "__main__":
    main()
