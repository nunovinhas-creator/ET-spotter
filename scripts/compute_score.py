"""
Calcula scores multi-factor cross-sectionais por ETF.

Score v2:
  - Normalização cross-sectional via z-score (todos os ETFs ao mesmo momento)
  - Momentum: sigmoid(0.2*cs_z(ret_21d) + 0.4*cs_z(ret_63d) + 0.4*cs_z(ret_126d))
  - Trend: (trend_sma + macd_bullish + rsi_zone + rs_positive) / 4
  - Risk: 0.4*sigmoid(cs_z(sharpe_63)) + 0.3*(adx>20) + 0.3*(1+drawdown.clip(-1,0))
  - Final: 0.40*momentum + 0.30*trend + 0.30*risk

Gera data/reports/scores_latest.csv e appenda a data/scores_history.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs

DATA_DAILY    = Path("data/daily")
REPORTS       = Path("data/reports")
SCORES_HIST   = Path("data/scores_history.csv")


def cs_z(s: pd.Series) -> pd.Series:
    """Z-score cross-sectional (todos os ETFs ao mesmo momento)."""
    return (s - s.mean()) / (s.std() + 1e-10)


def sigmoid(z: pd.Series) -> pd.Series:
    return 1 / (1 + np.exp(-z.clip(-6, 6)))


def build_snapshot(cfg: dict) -> pd.DataFrame:
    """Carrega último registo de cada ETF e devolve DataFrame cross-sectional."""
    etfs   = get_etfs(cfg)
    rows   = []

    for symbol in etfs:
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        last = df.iloc[-1]

        rows.append({
            "etf":          symbol,
            "close":        float(last.get("close",       np.nan) or np.nan),
            "ret_1d":       float(last.get("ret_1d",      np.nan) or np.nan),
            "ret_5d":       float(last.get("ret_5d",      np.nan) or np.nan),
            "ret_21d":      float(last.get("ret_21d",     np.nan) or np.nan),
            "ret_63d":      float(last.get("ret_63d",     np.nan) or np.nan),
            "ret_126d":     float(last.get("ret_126d",    np.nan) or np.nan),
            "vol_21":       float(last.get("vol_21",      np.nan) or np.nan),
            "sharpe_63":    float(last.get("sharpe_63",   np.nan) or np.nan),
            "rsi":          float(last.get("rsi",         np.nan) or np.nan),
            "adx":          float(last.get("adx",         np.nan) or np.nan),
            "rs_positive":  int(last.get("rs_positive",   0) or 0),
            "rs_mom_21":    float(last.get("rs_mom_21",   np.nan) or np.nan),
            "trend_sma":    int(last.get("trend_sma",     0) or 0),
            "macd_bullish": int(last.get("macd_bullish",  0) or 0),
            "above_sma200": int(last.get("above_sma200",  0) or 0),
            "drawdown":     float(last.get("drawdown",    np.nan) or np.nan),
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def compute_scores(snap: pd.DataFrame) -> pd.DataFrame:
    """Calcula scores cross-sectionais para o snapshot de ETFs."""
    snap = snap.copy()

    # ── Momentum ──────────────────────────────────────────────────────────────
    ret21  = snap["ret_21d"].fillna(0)
    ret63  = snap["ret_63d"].fillna(0)
    ret126 = snap["ret_126d"].fillna(0)
    momentum = sigmoid(0.2 * cs_z(ret21) + 0.4 * cs_z(ret63) + 0.4 * cs_z(ret126))

    # ── Trend ─────────────────────────────────────────────────────────────────
    rsi_zone = ((snap["rsi"] >= 40) & (snap["rsi"] <= 65)).astype(float).fillna(0)
    trend = (
        snap["trend_sma"].fillna(0).astype(float)
        + snap["macd_bullish"].fillna(0).astype(float)
        + rsi_zone
        + snap["rs_positive"].fillna(0).astype(float)
    ) / 4.0

    # ── Risk ──────────────────────────────────────────────────────────────────
    sharpe_z  = sigmoid(cs_z(snap["sharpe_63"].fillna(0)))
    adx_ok    = (snap["adx"] > 20).astype(float).fillna(0)
    dd_factor = (1 + snap["drawdown"].clip(lower=-1, upper=0)).fillna(0.9)
    risk = 0.4 * sharpe_z + 0.3 * adx_ok + 0.3 * dd_factor

    # ── Final score ───────────────────────────────────────────────────────────
    snap["score"] = (0.40 * momentum + 0.30 * trend + 0.30 * risk).round(6)

    return snap


def compute_score_percentile(snap: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona score_pct: percentil do score actual vs últimos 252 dias do histórico.
    Ex: 0.85 → ETF está no top 15% dos seus próprios scores históricos.
    """
    if not SCORES_HIST.exists():
        snap["score_pct"] = np.nan
        return snap

    hist = pd.read_csv(SCORES_HIST)
    pcts = []
    for _, row in snap.iterrows():
        etf_hist = hist[hist["etf"] == row["etf"]]["score"].dropna()
        # Últimos 252 registos (aprox. 1 ano de dias úteis)
        etf_hist = etf_hist.iloc[-252:]
        if len(etf_hist) < 5:
            pcts.append(np.nan)
        else:
            pcts.append(round((etf_hist < row["score"]).mean(), 3))
    snap["score_pct"] = pcts
    return snap


def persist_scores(snap: pd.DataFrame) -> None:
    """Guarda scores_latest.csv e appenda a scores_history.csv."""
    REPORTS.mkdir(parents=True, exist_ok=True)

    cols = [
        "etf", "close", "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d",
        "vol_21", "sharpe_63", "rsi", "adx", "rs_positive", "rs_mom_21",
        "trend_sma", "macd_bullish", "above_sma200", "drawdown", "score", "score_pct",
    ]
    out = snap[[c for c in cols if c in snap.columns]].sort_values("score", ascending=False)
    out.to_csv(REPORTS / "scores_latest.csv", index=False)

    # ── Histórico diário ──────────────────────────────────────────────────────
    today = pd.Timestamp.now().date().isoformat()
    hist  = snap.copy()
    hist["date"] = today

    if SCORES_HIST.exists():
        existing = pd.read_csv(SCORES_HIST)
        combined = pd.concat([existing, hist], ignore_index=True)
        # De-duplica por (date, etf), mantém último
        combined = combined.drop_duplicates(subset=["date", "etf"], keep="last")
    else:
        combined = hist

    combined.to_csv(SCORES_HIST, index=False)


def main():
    cfg = load_config()
    snap = build_snapshot(cfg)

    if snap.empty:
        print("[SKIP] Sem dados.")
        return

    snap = compute_scores(snap)
    snap = compute_score_percentile(snap)

    # Guarda scores nos ficheiros diários individuais
    for _, row in snap.iterrows():
        path = DATA_DAILY / f"{row['etf']}.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if not df.empty:
                df.loc[df.index[-1], "score"]     = row["score"]
                df.loc[df.index[-1], "score_pct"] = row.get("score_pct", np.nan)
                df.to_csv(path)

    persist_scores(snap)
    cols_show = ["etf", "score", "score_pct", "ret_21d", "ret_63d", "rsi", "adx"]
    print(snap[[c for c in cols_show if c in snap.columns]].to_string(index=False))
    print(f"\n[OK] {len(snap)} ETFs · scores guardados em data/reports/scores_latest.csv")


if __name__ == "__main__":
    main()
