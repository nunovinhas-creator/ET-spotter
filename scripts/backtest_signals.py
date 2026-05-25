"""
Valida historicamente os sinais de convicção.

Para cada (etf, date) em data/scores_history.csv onde há sinal activo,
calcula o retorno forward de 21 dias usando data/daily/SYMBOL.csv.

Requer mínimo de 22 dias de histórico em scores_history.csv.
Guarda resultados em data/reports/backtest_signals.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, compute_conviction

SCORES_HIST = Path("data/scores_history.csv")
DATA_DAILY  = Path("data/daily")
REPORTS     = Path("data/reports")

FORWARD_DAYS = 21


def load_history() -> pd.DataFrame:
    if not SCORES_HIST.exists():
        return pd.DataFrame()
    hist = pd.read_csv(SCORES_HIST, parse_dates=["date"])
    # Calcula delta_score por ETF (não está guardado no histórico)
    hist = hist.sort_values(["etf", "date"]).reset_index(drop=True)
    hist["delta_score"] = hist.groupby("etf")["score"].diff().fillna(0)
    return hist


def classify_conviction(row: pd.Series) -> str | None:
    conv = compute_conviction(
        score       = float(row.get("score",       0) or 0),
        trend_sma   = int(row.get("trend_sma",     0) or 0),
        macd_bullish= int(row.get("macd_bullish",  0) or 0),
        rsi         = float(row.get("rsi",         50) or 50),
        rs_positive = int(row.get("rs_positive",   0) or 0),
        ret_63d     = float(row.get("ret_63d",     0) or 0),
        delta_score = float(row.get("delta_score", 0) or 0),
        drawdown    = float(row.get("drawdown",   -0.5) or -0.5),
        ret_5d      = float(row.get("ret_5d",      0) or 0),
    )
    return conv["level"]


def run_backtest(cfg: dict) -> pd.DataFrame:
    hist = load_history()
    if hist.empty:
        print("[SKIP] Sem histórico de scores.")
        return pd.DataFrame()

    n_days = hist["date"].nunique()
    if n_days < FORWARD_DAYS + 1:
        print(f"[SKIP] Histórico insuficiente ({n_days} dias únicos). Mínimo: {FORWARD_DAYS + 1}.")
        return pd.DataFrame()

    results = []

    for etf, etf_hist in hist.groupby("etf"):
        daily_path = DATA_DAILY / f"{etf}.csv"
        if not daily_path.exists():
            continue
        daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        if daily.empty or "close" not in daily.columns:
            continue

        etf_hist = etf_hist.sort_values("date").reset_index(drop=True)

        for _, row in etf_hist.iterrows():
            level = classify_conviction(row)
            if level is None:
                continue

            signal_date = row["date"]
            # Preços após o sinal
            future = daily[daily.index > signal_date]["close"].dropna()
            if len(future) < FORWARD_DAYS:
                continue  # sem dados forward suficientes (sinal recente)

            entry = float(future.iloc[0])
            exit_ = float(future.iloc[FORWARD_DAYS - 1])
            fwd   = exit_ / entry - 1 if entry > 0 else np.nan

            results.append({
                "etf":    etf,
                "date":   signal_date,
                "level":  level,
                "score":  round(float(row["score"]), 4),
                "fwd_21d": round(fwd, 6) if pd.notna(fwd) else np.nan,
            })

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame) -> None:
    print("\n══════════════════════════════════════════")
    print("  BACKTEST DE SINAIS — retorno forward 21d")
    print("══════════════════════════════════════════")

    order = ["FORTE COMPRA", "COMPRA", "POTENCIAL"]
    for level in order:
        sub = df[df["level"] == level]["fwd_21d"].dropna()
        if sub.empty:
            print(f"\n{level}: sem observações com dados forward suficientes")
            continue
        win_rate  = (sub > 0).mean()
        avg       = sub.mean()
        median    = sub.median()
        std       = sub.std()
        sharpe    = avg / (std + 1e-10)
        best      = sub.max()
        worst     = sub.min()
        print(f"\n{level}  (n={len(sub)})")
        print(f"  Retorno médio 21d  : {avg:+.2%}")
        print(f"  Retorno mediano 21d: {median:+.2%}")
        print(f"  Taxa de sucesso    : {win_rate:.1%}")
        print(f"  Sharpe implícito   : {sharpe:+.2f}")
        print(f"  Melhor / Pior      : {best:+.2%} / {worst:+.2%}")

    # Benchmarking: sinal vs buy-and-hold aleatório
    all_fwd = df["fwd_21d"].dropna()
    if not all_fwd.empty:
        print(f"\nTodos os sinais combinados (n={len(all_fwd)}): média {all_fwd.mean():+.2%}")
    print("══════════════════════════════════════════")


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    df = run_backtest(cfg)
    if df.empty:
        return

    print_summary(df)
    out = REPORTS / "backtest_signals.csv"
    df.to_csv(out, index=False)
    print(f"\n[OK] Resultados guardados em {out}")


if __name__ == "__main__":
    main()
