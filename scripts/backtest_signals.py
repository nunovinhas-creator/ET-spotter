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
from constants import (
    BACKTEST_COST_BPS, BACKTEST_MIN_EPISODES,
    SIGNAL_RULES_VERSION, SIGNAL_RULES_FROZEN_AT,
)

HORIZONS     = [5, 10, 21, 42]   # default; substituído por config em run_backtest()


def get_horizons(cfg: dict) -> list[int]:
    """Lê horizontes do config; fallback para HORIZONS se ausente ou inválido."""
    raw = cfg.get("params", {}).get("backtest_horizons", HORIZONS)
    parsed = [int(x) for x in raw if isinstance(x, (int, float)) and x > 0]
    return sorted(parsed) if parsed else list(HORIZONS)


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


def write_status(cfg: dict, df, n_days: int, min_days: int) -> None:
    """Escreve data/reports/backtest_status.json sempre, mesmo em SKIP."""
    import json as _json, datetime as _dt
    horizons = get_horizons(cfg)
    cost_bps = cfg.get("params", {}).get("backtest_cost_bps", BACKTEST_COST_BPS)
    min_ep   = cfg.get("params", {}).get("backtest_min_episodes", BACKTEST_MIN_EPISODES)

    days_missing = max(0, min_days - n_days)
    eta_days     = int(days_missing * 7 / 5) + 1
    eta_date     = (_dt.date.today() + _dt.timedelta(days=eta_days)).isoformat()

    by_level = {}
    if df is not None and len(df) > 0 and "level" in df.columns:
        ref_h = 21 if 21 in horizons else horizons[-1]
        for lvl in ["FORTE COMPRA", "COMPRA", "POTENCIAL"]:
            sub    = df[df["level"] == lvl]
            col_g  = f"fwd_{ref_h}d"
            col_n  = f"fwd_{ref_h}d_net"
            fwd_g  = sub[col_g].dropna() if col_g in sub.columns else pd.Series(dtype=float)
            fwd_n  = sub[col_n].dropna() if col_n in sub.columns else pd.Series(dtype=float)
            exc_c  = f"fwd_{ref_h}d_excess"
            n = len(fwd_g)
            by_level[lvl] = {
                "n":             n,
                "sufficient":    n >= min_ep,
                "avg_gross_21d": round(float(fwd_g.mean()), 4) if n > 0 else None,
                "avg_net_21d":   round(float(fwd_n.mean()), 4) if len(fwd_n) > 0 else None,
                "win_rate":      round(float((fwd_g > 0).mean()), 3) if n > 0 else None,
                "excess_spy":    round(float(df[df["level"] == lvl][exc_c].dropna().mean()), 4)
                                 if exc_c in df.columns else None,
            }

    n_episodes = len(df) if df is not None and len(df) > 0 else 0
    status = {
        "status":              "OK" if (df is not None and len(df) > 0 and n_days >= min_days) else "A_ACUMULAR",
        "rules_version":       SIGNAL_RULES_VERSION,
        "rules_frozen_at":     SIGNAL_RULES_FROZEN_AT,
        "history_days":        n_days,
        "min_days_required":   min_days,
        "days_missing":        days_missing,
        "first_results_eta":   eta_date,
        "n_episodes":          n_episodes,
        "min_episodes_target": min_ep,
        "cost_bps_roundtrip":  cost_bps,
        "by_level":            by_level,
        "generated_at":        _dt.datetime.utcnow().isoformat() + "Z",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "backtest_status.json", "w") as f:
        _json.dump(status, f, indent=2, ensure_ascii=False)
    print(f"[OK] backtest_status.json (status={status['status']}, days={n_days}/{min_days})")


def archive_legacy_backtest(cfg: dict) -> bool:
    """Arquiva backtest_signals.csv se for maioritariamente de universo antigo."""
    from utils import get_etfs
    out = REPORTS / "backtest_signals.csv"
    if not out.exists():
        return False
    try:
        old = pd.read_csv(out)
        if old.empty or "etf" not in old.columns:
            return False
        universe = set(get_etfs(cfg))
        old_etfs = set(old["etf"].unique())
        overlap  = len(old_etfs & universe)
        fraction = overlap / len(old_etfs) if old_etfs else 1.0
        if fraction < 0.5:
            legacy = REPORTS / "backtest_signals_legacy.csv"
            out.rename(legacy)
            print(f"[AVISO] backtest_signals.csv arquivado ({overlap}/{len(old_etfs)} ETFs no universo — {fraction:.0%})")
            return True
    except Exception as e:
        print(f"[AVISO] Não foi possível verificar legacy: {e}")
    return False


def run_backtest(cfg: dict) -> pd.DataFrame:
    horizons     = get_horizons(cfg)
    forward_days = max(horizons)
    cost_bps     = cfg.get("params", {}).get("backtest_cost_bps",      BACKTEST_COST_BPS)
    dedup        = cfg.get("params", {}).get("backtest_dedup_episodes", True)
    cost         = cost_bps / 10_000

    hist = load_history()
    if hist.empty:
        print("[SKIP] Sem histórico de scores.")
        return pd.DataFrame()

    n_days   = hist["date"].nunique()
    min_days = forward_days * 2 + 1

    if n_days < min_days:
        print(f"[SKIP] Histórico insuficiente ({n_days} dias). Mínimo: {min_days}.")
        return pd.DataFrame()

    spy_close, spy_sma200 = load_spy_daily()
    results     = []
    level_order = {None: 0, "POTENCIAL": 1, "COMPRA": 2, "FORTE COMPRA": 3}

    for etf, etf_hist in hist.groupby("etf"):
        daily_path = DATA_DAILY / f"{etf}.csv"
        if not daily_path.exists():
            continue
        daily = pd.read_csv(daily_path, index_col=0, parse_dates=True)
        if daily.empty or "close" not in daily.columns:
            continue

        etf_hist   = etf_hist.sort_values("date").reset_index(drop=True)
        prev_level = None

        for _, row in etf_hist.iterrows():
            level = classify_conviction(row)

            if dedup:
                if level_order.get(level, 0) <= level_order.get(prev_level, 0):
                    prev_level = level
                    continue
            prev_level = level

            if level is None:
                continue

            signal_date = row["date"]
            future = daily[daily.index > signal_date]["close"].dropna()
            if len(future) < forward_days:
                continue

            entry = float(future.iloc[0])
            if entry <= 0:
                continue

            fwd = {}
            for h in horizons:
                if len(future) >= h:
                    gross             = round(float(future.iloc[h - 1]) / entry - 1, 6)
                    fwd[f"fwd_{h}d"]     = gross
                    fwd[f"fwd_{h}d_net"] = round(gross - cost, 6)
                else:
                    fwd[f"fwd_{h}d"]     = np.nan
                    fwd[f"fwd_{h}d_net"] = np.nan

            ref_h = 21 if 21 in horizons else horizons[-1]
            if not spy_close.empty:
                spy_fut = spy_close[spy_close.index > signal_date].dropna()
                if len(spy_fut) >= ref_h:
                    se, sx  = float(spy_fut.iloc[0]), float(spy_fut.iloc[ref_h - 1])
                    spy_fwd = sx / se - 1 if se > 0 else np.nan
                    rf      = fwd.get(f"fwd_{ref_h}d")
                    fwd[f"fwd_{ref_h}d_excess"] = round(rf - spy_fwd, 6) if pd.notna(rf) else np.nan
                else:
                    fwd[f"fwd_{ref_h}d_excess"] = np.nan
            else:
                fwd[f"fwd_{ref_h}d_excess"] = np.nan

            window21 = future.iloc[:21] if len(future) >= 21 else future
            rets21   = window21.values / entry - 1
            mae_21d  = round(float(rets21.min()), 6) if len(rets21) > 0 else np.nan
            mfe_21d  = round(float(rets21.max()), 6) if len(rets21) > 0 else np.nan

            if not spy_close.empty and not spy_sma200.empty:
                try:
                    sa = spy_close.asof(signal_date)
                    sm = spy_sma200.asof(signal_date)
                    spy_regime = ("BULL" if sa > sm else "BEAR") if pd.notna(sa) and pd.notna(sm) and sm > 0 else "UNKNOWN"
                except Exception:
                    spy_regime = "UNKNOWN"
            else:
                spy_regime = "UNKNOWN"

            results.append({
                "etf":           etf,
                "date":          signal_date,
                "level":         level,
                "score":         round(float(row["score"]), 4),
                "spy_regime":    spy_regime,
                "mae_21d":       mae_21d,
                "mfe_21d":       mfe_21d,
                "rules_version": SIGNAL_RULES_VERSION,
                **fwd,
            })

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame, horizons: list[int] | None = None) -> None:
    if horizons is None:
        horizons = HORIZONS
    ref_h        = 21 if 21 in horizons else horizons[-1]
    fwd_ref_col  = f"fwd_{ref_h}d"
    exc_ref_col  = f"fwd_{ref_h}d_excess"
    other_hs     = [h for h in horizons if h != ref_h]

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
            sub_df = df[df["spy_regime"] == regime] if "spy_regime" in df.columns else pd.DataFrame()
            if sub_df.empty:
                continue
            print(f"\n{'─'*60}")
            print(f"  REGIME: SPY {regime} (acima/abaixo SMA200)")
        print(f"{'─'*60}")

        for level in order:
            sub = sub_df[sub_df["level"] == level] if "level" in sub_df.columns else pd.DataFrame()
            if sub.empty:
                print(f"\n  {level}: sem observações")
                continue

            fwd_ref = sub[fwd_ref_col].dropna() if fwd_ref_col in sub.columns else pd.Series(dtype=float)
            excess  = sub[exc_ref_col].dropna()  if exc_ref_col  in sub.columns else pd.Series(dtype=float)
            mae     = sub["mae_21d"].dropna()    if "mae_21d"     in sub.columns else pd.Series(dtype=float)
            mfe     = sub["mfe_21d"].dropna()    if "mfe_21d"     in sub.columns else pd.Series(dtype=float)

            if fwd_ref.empty:
                print(f"\n  {level}: sem dados forward suficientes")
                continue

            win_rate = (fwd_ref > 0).mean()
            avg_ref  = fwd_ref.mean()
            med_ref  = fwd_ref.median()
            std_ref  = fwd_ref.std()
            sharpe   = avg_ref / (std_ref + 1e-10)

            insuf = " (INSUFICIENTE)" if len(fwd_ref) < BACKTEST_MIN_EPISODES else ""
            print(f"\n  {level}  (n={len(fwd_ref)}){insuf}")
            print(f"    Ret. médio {ref_h}d (bruto) : {avg_ref:+.2%}")
            net_col = f"fwd_{ref_h}d_net"
            if net_col in sub.columns:
                net_s = sub[net_col].dropna()
                if not net_s.empty:
                    print(f"    Ret. médio {ref_h}d (líq.)  : {net_s.mean():+.2%}")
            print(f"    Ret. mediano {ref_h}d   : {med_ref:+.2%}")
            if not excess.empty:
                print(f"    Excesso vs SPY {ref_h}d : {excess.mean():+.2%}  (médio)")
            print(f"    Taxa de sucesso    : {win_rate:.1%}")
            print(f"    Sharpe implícito   : {sharpe:+.2f}")
            if not mae.empty:
                print(f"    MAE médio (drawdown): {mae.mean():.2%}")
            if not mfe.empty:
                print(f"    MFE médio (peak)   : {mfe.mean():.2%}")

            for h in other_hs:
                col = f"fwd_{h}d"
                if col in sub.columns:
                    s = sub[col].dropna()
                    if not s.empty:
                        print(f"    Ret. médio {h:2d}d     : {s.mean():+.2%}  (win {(s>0).mean():.0%})")

    all_fwd = df[fwd_ref_col].dropna() if fwd_ref_col in df.columns else pd.Series(dtype=float)
    if not all_fwd.empty:
        print(f"\n  Todos os sinais (n={len(all_fwd)}): média {all_fwd.mean():+.2%}")
        if exc_ref_col in df.columns:
            exc = df[exc_ref_col].dropna()
            if not exc.empty:
                print(f"  Excesso vs SPY médio: {exc.mean():+.2%}")
    print("══════════════════════════════════════════════════════════════")


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    archive_legacy_backtest(cfg)

    horizons = get_horizons(cfg)
    hist     = load_history()
    n_days   = hist["date"].nunique() if not hist.empty else 0
    min_days = max(horizons) * 2 + 1

    df = run_backtest(cfg)
    write_status(cfg, df if not df.empty else None, n_days, min_days)

    if df.empty:
        return

    print_summary(df, horizons=horizons)
    out = REPORTS / "backtest_signals.csv"
    df.to_csv(out, index=False)
    print(f"\n[OK] Resultados guardados em {out}")


if __name__ == "__main__":
    main()
