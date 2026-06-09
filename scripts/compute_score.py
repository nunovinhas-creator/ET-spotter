"""
Calcula scores multi-factor cross-sectionais por ETF.

Score v3 — adicionados 4 factores alpha (inspirados em alpha101/WorldQuant e literatura académica):
  - Normalização cross-sectional via z-score (todos os ETFs ao mesmo momento)
  - Momentum    (35%): sigmoid(0.2*cs_z(ret_21d) + 0.4*cs_z(ret_63d) + 0.4*cs_z(ret_126d))
  - Trend       (25%): (trend_sma + macd_bullish + rsi_zone + f_rs_quality) / 4
                       f_rs_quality: RS contínuo vs SPY (substitui binário rs_positive)
  - Risk        (25%): 0.4*sigmoid(cs_z(calmar_63)) + 0.3*(adx>20) + 0.3*(1+drawdown)
  - Alpha       (15%): média de 4 factores alpha101-inspired:
      f_ir_mom    : ret_63d / vol_21  (retorno ajustado ao risco, Information Ratio proxy)
      f_mom_accel : ret_21d - ret_63d/3  (aceleração do momentum: ritmo recente vs média 3M)
      f_rs_quality: 0.4*cs_z(rs_mom_21) + 0.6*cs_z(rs_mom_63)  (RS contínuo vs benchmark)
      f_annual_mom: ret_252d  (Jegadeesh-Titman 12M, factor mais validado empiricamente)

Referências: Jegadeesh & Titman (1993), Ang et al. (2006), Kakushadze (2015) alpha101.

Gera data/reports/scores_latest.csv e appenda a data/scores_history.csv.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs
from paths import DATA_DAILY, REPORTS, SCORES_HIST


def _safe(v, default=np.nan):
    """Float seguro: preserva 0.0; converte None/NaN para default."""
    try:
        x = float(v)
        return default if x != x else x  # x != x é True apenas para NaN
    except (TypeError, ValueError):
        return default


def cs_z(s: pd.Series) -> pd.Series:
    """Z-score cross-sectional (todos os ETFs ao mesmo momento)."""
    return (s - s.mean()) / (s.std() + 1e-10)


def sigmoid(z: pd.Series) -> pd.Series:
    return 1 / (1 + np.exp(-z.clip(-6, 6)))


def winsorize(s: pd.Series, n_sigma: float = 2.5) -> pd.Series:
    """Limita outliers a ±2.5σ antes do z-score cross-seccional."""
    mean, std = s.mean(), s.std()
    if std < 1e-10:
        return s
    return s.clip(mean - n_sigma * std, mean + n_sigma * std)


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
            "close":        _safe(last.get("close")),
            "ret_1d":       _safe(last.get("ret_1d")),
            "ret_5d":       _safe(last.get("ret_5d")),
            "ret_21d":      _safe(last.get("ret_21d")),
            "ret_63d":      _safe(last.get("ret_63d")),
            "ret_126d":     _safe(last.get("ret_126d")),
            "ret_252d":     _safe(last.get("ret_252d")),
            "vol_21":       _safe(last.get("vol_21")),
            "sharpe_63":    _safe(last.get("sharpe_63")),
            "rsi":          _safe(last.get("rsi")),
            "adx":          _safe(last.get("adx")),
            "rs_positive":  int(last.get("rs_positive",   0) or 0),
            "rs_mom_21":    _safe(last.get("rs_mom_21")),
            "rs_mom_63":    _safe(last.get("rs_mom_63")),
            "calmar_63":    _safe(last.get("calmar_63")),
            "trend_sma":    int(last.get("trend_sma",     0) or 0),
            "macd_bullish": int(last.get("macd_bullish",  0) or 0),
            "above_sma200": int(last.get("above_sma200",  0) or 0),
            "drawdown":     _safe(last.get("drawdown")),
            "macd":         _safe(last.get("macd")),
            "macd_signal":  _safe(last.get("macd_signal")),
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def compute_scores(snap: pd.DataFrame) -> pd.DataFrame:
    """Calcula scores cross-sectionais para o snapshot de ETFs (v3 com alpha factors)."""
    snap = snap.copy()

    # ── Momentum (35%) ────────────────────────────────────────────────────────
    ret21  = winsorize(snap["ret_21d"].fillna(0))
    ret63  = winsorize(snap["ret_63d"].fillna(0))
    ret126 = winsorize(snap["ret_126d"].fillna(0))
    momentum = sigmoid(0.2 * cs_z(ret21) + 0.4 * cs_z(ret63) + 0.4 * cs_z(ret126))

    # ── Alpha Quality (15%) — 4 factores alpha101-inspired ────────────────────

    # F1: IR-momentum — retorno ajustado à volatilidade (Information Ratio proxy)
    #     Ang et al. (2006): low-vol anomaly; high IR → melhor qualidade de retorno
    vol_safe  = snap["vol_21"].replace(0, np.nan).fillna(snap["vol_21"].median())
    f_ir_mom  = sigmoid(cs_z(winsorize((snap["ret_63d"] / vol_safe).fillna(0))))

    # F2: Momentum acceleration — ritmo recente vs média mensal do trimestre
    #     Positivo quando o último mês supera o ritmo médio dos últimos 3 meses
    mom_accel   = winsorize((snap["ret_21d"] - snap["ret_63d"] / 3.0).fillna(0))
    f_mom_accel = sigmoid(cs_z(mom_accel))

    # F3: Continuous relative strength — RS contínuo vs benchmark (SPY)
    #     Jegadeesh-Titman: RS normalizado em vez de binário 0/1
    rs_cont      = winsorize(
        (0.4 * snap["rs_mom_21"].fillna(0) + 0.6 * snap["rs_mom_63"].fillna(0))
    )
    f_rs_quality = sigmoid(cs_z(rs_cont))

    # F4: Annual momentum — Jegadeesh-Titman 12M, factor mais replicado na literatura
    f_annual_mom = sigmoid(cs_z(winsorize(snap["ret_252d"].fillna(0))))

    alpha_quality = (f_ir_mom + f_mom_accel + f_rs_quality + f_annual_mom) / 4.0

    # ── Trend (25%) ───────────────────────────────────────────────────────────
    # Usa f_rs_quality (contínuo 0–1) em vez do binário rs_positive
    rsi_zone = ((snap["rsi"] >= 40) & (snap["rsi"] <= 65)).astype(float).fillna(0)
    trend = (
        snap["trend_sma"].fillna(0).astype(float)
        + snap["macd_bullish"].fillna(0).astype(float)
        + rsi_zone
        + f_rs_quality
    ) / 4.0

    # ── Risk (25%) ────────────────────────────────────────────────────────────
    risk_series = snap["calmar_63"] if "calmar_63" in snap.columns else snap["sharpe_63"]
    sharpe_z  = sigmoid(cs_z(winsorize(risk_series.fillna(0))))
    adx_ok    = (snap["adx"] > 20).astype(float).fillna(0)
    dd_factor = (1 + snap["drawdown"].clip(lower=-1, upper=0)).fillna(0.9)
    risk = 0.4 * sharpe_z + 0.3 * adx_ok + 0.3 * dd_factor

    # ── Final score v3 ────────────────────────────────────────────────────────
    # 35% momentum · 25% trend · 25% risk · 15% alpha quality
    snap["score"] = (
        0.35 * momentum
        + 0.25 * trend
        + 0.25 * risk
        + 0.15 * alpha_quality
    ).round(6)

    # Guardar sub-scores para auditoria/debug
    snap["_momentum"]      = momentum.round(4)
    snap["_trend"]         = trend.round(4)
    snap["_risk"]          = risk.round(4)
    snap["_alpha_quality"] = alpha_quality.round(4)

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
    hist_by_etf = {
        etf: grp["score"].dropna().iloc[-252:]
        for etf, grp in hist.groupby("etf")
    }

    def _calc_pct(row):
        h = hist_by_etf.get(row["etf"], pd.Series(dtype=float))
        return round((h < row["score"]).mean(), 3) if len(h) >= 5 else np.nan

    snap["score_pct"] = snap.apply(_calc_pct, axis=1)
    return snap


def compute_ml_score(snap: pd.DataFrame) -> pd.DataFrame:
    """Adiciona ml_prob: probabilidade XGBoost de retorno positivo a 21 dias."""
    import pickle
    model_path = Path(__file__).parent.parent / "data" / "models" / "xgb_signal.pkl"
    if not model_path.exists():
        snap["ml_prob"] = np.nan
        return snap

    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    model    = bundle["model"]
    features = bundle["features"]

    snap = snap.copy()
    snap["macd_hist"] = snap["macd"].fillna(0) - snap["macd_signal"].fillna(0)

    missing = [c for c in features if c not in snap.columns]
    if missing:
        snap["ml_prob"] = np.nan
        return snap

    X = snap[features].fillna(0)
    snap["ml_prob"] = model.predict_proba(X)[:, 1].round(3)
    return snap


def persist_scores(snap: pd.DataFrame) -> None:
    """Guarda scores_latest.csv e appenda a scores_history.csv."""
    REPORTS.mkdir(parents=True, exist_ok=True)

    cols = [
        "etf", "close", "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "ret_252d",
        "vol_21", "sharpe_63", "rsi", "adx", "rs_positive", "rs_mom_21", "rs_mom_63",
        "calmar_63", "trend_sma", "macd_bullish", "above_sma200", "drawdown",
        "score", "score_pct", "ml_prob",
        "_momentum", "_trend", "_risk", "_alpha_quality",
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

    tmp = SCORES_HIST.with_suffix(".tmp")
    combined.to_csv(tmp, index=False)
    tmp.replace(SCORES_HIST)  # rename atómico: evita corrupção em falha a meio da escrita


def main():
    cfg = load_config()
    snap = build_snapshot(cfg)

    if snap.empty:
        print("[SKIP] Sem dados.")
        return

    snap = compute_scores(snap)
    snap = compute_score_percentile(snap)
    snap = compute_ml_score(snap)

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
