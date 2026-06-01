"""
Valida historicamente os sinais de convicção.

Para cada (etf, date) em data/scores_history.csv onde há sinal activo,
calcula retornos forward em múltiplos horizontes usando data/daily/SYMBOL.csv.
Inclui retorno em excesso vs SPY, MAE/MFE, e decomposição por regime de mercado.

Requer mínimo de 42 dias de histórico em scores_history.csv.
Guarda resultados em data/reports/backtest_signals.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, compute_conviction
from paths import DATA_DAILY, REPORTS, SCORES_HIST

HORIZONS     = [5, 10, 21, 42]
FORWARD_DAYS = max(HORIZONS)


def load_history() -> pd.DataFrame:
    if not SCORES_HIST.exists():
        return pd.DataFrame()
    hist = pd.read_csv(SCORES_HIST, parse_dates=["date"])
    hist = hist.sort_values(["etf", "date"]).reset_index(drop=True)
    hist["delta_score"] = hist.groupby("etf")["score"].diff().fillna(0)
    return hist


def load_spy_daily() -> tuple[pd.Series, pd.Series]:
    """Carrega série de preços de fecho do SPY com SMA200 para regime."""
    path = DATA_DAILY / "SPY.csv"
    if not path.exists():
        return pd.Series(dtype=float), pd.Series(dtype=float)
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty or "close" not in df.columns:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    close = df["close"].astype(float)
    sma200 = close.rolling(200).mean()
    return close, sma200


def classify_conviction(row: pd.Series) -> str | None:
    conv = compute_conviction(
        score        = float(row.get("score",       0) or 0),
        trend_sma    = int(row.get("trend_sma",     0) or 0),
        macd_bullish = int(row.get("macd_bullish",  0) or 0),
        rsi          = float(row.get("rsi",         50) or 50),
        rs_positive  = int(row.get("rs_positive",   0) or 0),
        ret_63d      = float(row.get("ret_63d",     0) or 0),
        delta_score  = float(row.get("delta_score", 0) or 0),
        drawdown     = float(row.get("drawdown",   -0.5) or -0.5),
        ret_5d       = float(row.get("ret_5d",      0) or 0),
        vol_21       = float(row.get("vol_21",      0) or 0),
    )
    return conv["level"]


def run_backtest(cfg: dict) -> pd.DataFrame:
    hist = load_history()
    if hist.empty:
        print("[SKIP] Sem histórico de scores.")
        return pd.DataFrame()

    n_days = hist["date"].nunique()
    min_days = FORWARD_DAYS * 2 + 1
    if n_days < min_days:
        print(f"[SKIP] Histórico insuficiente ({n_days} dias únicos). Mínimo: {min_days}.")
        return pd.DataFrame()

    spy_close, spy_sma200 = load_spy_daily()
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
            future = daily[daily.index > signal_date]["close"].dropna()
            if len(future) < FORWARD_DAYS:
                continue  # dados forward insuficientes

            entry = float(future.iloc[0])
            if entry <= 0:
                continue

            # ── Retornos forward multi-horizonte ──────────────────────────
            fwd = {}
            for h in HORIZONS:
                if len(future) >= h:
                    exit_p = float(future.iloc[h - 1])
                    fwd[f"fwd_{h}d"] = round(exit_p / entry - 1, 6)
                else:
                    fwd[f"fwd_{h}d"] = np.nan

            # ── Excesso de retorno vs SPY ──────────────────────────────────
            if not spy_close.empty:
                spy_future = spy_close[spy_close.index > signal_date].dropna()
                if len(spy_future) >= 21:
                    spy_entry = float(spy_future.iloc[0])
                    spy_exit  = float(spy_future.iloc[20])
                    spy_fwd   = spy_exit / spy_entry - 1 if spy_entry > 0 else np.nan
                    fwd["fwd_21d_excess"] = round(
                        fwd["fwd_21d"] - spy_fwd, 6
                    ) if pd.notna(fwd.get("fwd_21d")) else np.nan
                else:
                    fwd["fwd_21d_excess"] = np.nan
            else:
                fwd["fwd_21d_excess"] = np.nan

            # ── MAE/MFE na janela de 21 dias ──────────────────────────────
            window21 = future.iloc[:21] if len(future) >= 21 else future
            prices21 = window21.values
            rets21   = prices21 / entry - 1
            mae_21d  = round(float(rets21.min()), 6) if len(rets21) > 0 else np.nan
            mfe_21d  = round(float(rets21.max()), 6) if len(rets21) > 0 else np.nan

            # ── Regime de mercado SPY na data do sinal ────────────────────
            if not spy_close.empty and not spy_sma200.empty:
                spy_at_signal = spy_close.asof(signal_date) if signal_date in spy_close.index or spy_close.index.min() <= signal_date else np.nan
                sma_at_signal = spy_sma200.asof(signal_date) if signal_date in spy_sma200.index or spy_sma200.index.min() <= signal_date else np.nan
                if pd.notna(spy_at_signal) and pd.notna(sma_at_signal) and sma_at_signal > 0:
                    spy_regime = "BULL" if spy_at_signal > sma_at_signal else "BEAR"
                else:
                    spy_regime = "UNKNOWN"
            else:
                spy_regime = "UNKNOWN"

            results.append({
                "etf":         etf,
                "date":        signal_date,
                "level":       level,
                "score":       round(float(row["score"]), 4),
                "spy_regime":  spy_regime,
                "mae_21d":     mae_21d,
                "mfe_21d":     mfe_21d,
                **fwd,
            })

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame) -> None:
    print("\n══════════════════════════════════════════════════════════════")
    print("  BACKTEST DE SINAIS — retornos forward multi-horizonte")
    print("══════════════════════════════════════════════════════════════")

    order = ["FORTE COMPRA", "COMPRA", "POTENCIAL"]

    for regime in ["ALL", "BULL", "BEAR"]:
        if regime == "ALL":
            sub_df = df
            print(f"\n{'─'*60}")
            print(f"  REGIME: TODOS OS MERCADOS")
        else:
            sub_df = df[df["spy_regime"] == regime]
            if sub_df.empty:
                continue
            print(f"\n{'─'*60}")
            print(f"  REGIME: SPY {regime} (acima/abaixo SMA200)")
        print(f"{'─'*60}")

        for level in order:
            sub = sub_df[sub_df["level"] == level]
            if sub.empty:
                print(f"\n  {level}: sem observações")
                continue

            fwd21 = sub["fwd_21d"].dropna()
            excess = sub["fwd_21d_excess"].dropna() if "fwd_21d_excess" in sub.columns else pd.Series(dtype=float)
            mae   = sub["mae_21d"].dropna() if "mae_21d" in sub.columns else pd.Series(dtype=float)
            mfe   = sub["mfe_21d"].dropna() if "mfe_21d" in sub.columns else pd.Series(dtype=float)

            if fwd21.empty:
                print(f"\n  {level}: sem dados forward suficientes")
                continue

            win_rate  = (fwd21 > 0).mean()
            avg_21    = fwd21.mean()
            median_21 = fwd21.median()
            std_21    = fwd21.std()
            sharpe    = avg_21 / (std_21 + 1e-10)

            print(f"\n  {level}  (n={len(fwd21)})")
            print(f"    Ret. médio 21d     : {avg_21:+.2%}")
            print(f"    Ret. mediano 21d   : {median_21:+.2%}")
            if not excess.empty:
                print(f"    Excesso vs SPY 21d : {excess.mean():+.2%}  (médio)")
            print(f"    Taxa de sucesso    : {win_rate:.1%}")
            print(f"    Sharpe implícito   : {sharpe:+.2f}")
            if not mae.empty:
                print(f"    MAE médio (drawdown): {mae.mean():.2%}")
            if not mfe.empty:
                print(f"    MFE médio (peak)   : {mfe.mean():.2%}")

            # Multi-horizonte
            for h in [5, 10, 42]:
                col = f"fwd_{h}d"
                if col in sub.columns:
                    s = sub[col].dropna()
                    if not s.empty:
                        print(f"    Ret. médio {h:2d}d     : {s.mean():+.2%}  (win {(s>0).mean():.0%})")

    # Totais
    all_fwd = df["fwd_21d"].dropna()
    if not all_fwd.empty:
        print(f"\n  Todos os sinais (n={len(all_fwd)}): média {all_fwd.mean():+.2%}")
        if "fwd_21d_excess" in df.columns:
            exc = df["fwd_21d_excess"].dropna()
            if not exc.empty:
                print(f"  Excesso vs SPY médio: {exc.mean():+.2%}")
    print("══════════════════════════════════════════════════════════════")


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
