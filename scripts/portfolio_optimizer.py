"""Gera pesos-alvo auditáveis a partir do score e do risco recente.

O optimizador usa uma aproximação robusta de risk parity: inverso da
volatilidade marginal da matriz de covariância, ajustado pela view do score.
Mantém no máximo 10 ETFs, exige AUM mínimo e limita cada categoria a 25%.
A exposição total segue o filtro de regime (market_regime.py): BULL 100%,
NEUTRAL 60% (resto em CASH), STRESS/BEAR 100% CASH.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from market_regime import current_regime

ROOT = Path(__file__).parent.parent
SCORES_PATH = ROOT / "data" / "reports" / "scores_latest.csv"
DAILY_PATH = ROOT / "data" / "daily"
OUTPUT_PATH = ROOT / "data" / "portfolio" / "target_weights.csv"
BENCHMARK = "VWCE.DE"
MAX_POSITIONS = 10
MIN_AUM_BN = 0.2
CATEGORY_CAP = 0.25


def _config() -> dict:
    return json.loads((ROOT / "config" / "etfs.json").read_text(encoding="utf-8"))


def _metadata(config: dict) -> dict[str, dict]:
    return {
        etf["ticker"]: {
            "name": etf.get("name", etf["ticker"]),
            "category": category.get("name", category.get("id", "Other")),
            "aum_bn": float(etf.get("aum_bn", 0) or 0),
        }
        for category in config.get("categories", [])
        for etf in category.get("etfs", [])
    }


def _prices(tickers: list[str]) -> pd.DataFrame:
    frames = {}
    for ticker in tickers:
        path = DAILY_PATH / f"{ticker}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        if "close" in frame:
            frames[ticker] = frame["close"]
    return pd.DataFrame(frames).sort_index().pct_change(fill_method=None).tail(126)


def _regime() -> tuple[str, float | None, float]:
    """Regime atual, VIX e exposição máxima (VWCE vs SMA200 + VIX; sem VIX só SMA200)."""
    status = current_regime()
    return status["regime"], status.get("vix"), float(status.get("exposure", 0.0))


def _cap_categories(weights: pd.Series, categories: pd.Series) -> pd.Series:
    weights = weights.clip(lower=0)
    result = pd.Series(0.0, index=weights.index)
    remaining = set(weights.index)
    budget = 1.0
    while remaining and budget > 1e-9:
        proposal = weights.loc[sorted(remaining)] / weights.loc[sorted(remaining)].sum() * budget
        capped = proposal.groupby(categories.loc[proposal.index]).transform("sum") > CATEGORY_CAP + 1e-9
        if not capped.any():
            result.loc[proposal.index] = proposal
            break
        for category in categories.loc[proposal.index[capped]].unique():
            members = proposal.index[(categories.loc[proposal.index] == category)]
            category_weight = min(CATEGORY_CAP, budget * weights.loc[members].sum() / weights.loc[sorted(remaining)].sum())
            result.loc[members] = proposal.loc[members] / proposal.loc[members].sum() * category_weight
            budget -= category_weight
            remaining -= set(members)
    return result


def build_target_weights() -> pd.DataFrame:
    if not SCORES_PATH.exists():
        raise FileNotFoundError(SCORES_PATH)
    scores = pd.read_csv(SCORES_PATH)
    metadata = _metadata(_config())
    scores["score_v3"] = scores.get("score_v3", scores["score"])
    scores["final_score"] = scores["score"]
    scores["ml_prob"] = scores.get("ml_prob", np.nan)
    if "ml_prob" in scores:
        valid_ml = scores["ml_prob"].notna()
        scores.loc[valid_ml, "final_score"] = 0.6 * scores.loc[valid_ml, "score_v3"] + 0.4 * scores.loc[valid_ml, "ml_prob"]
    scores["category"] = scores["etf"].map(lambda ticker: metadata.get(ticker, {}).get("category", "Other"))
    scores["name"] = scores["etf"].map(lambda ticker: metadata.get(ticker, {}).get("name", ticker))
    scores["aum_bn"] = scores["etf"].map(lambda ticker: metadata.get(ticker, {}).get("aum_bn", 0.0))
    candidates = scores[scores["aum_bn"] >= MIN_AUM_BN].nlargest(MAX_POSITIONS, "final_score").copy()
    regime, vix, exposure = _regime()
    if candidates.empty or exposure <= 0:
        return pd.DataFrame([{"date": pd.Timestamp.now().date().isoformat(), "ticker": "CASH", "weight": 1.0, "regime": regime, "vix": vix}])

    returns = _prices(candidates["etf"].tolist()).reindex(columns=candidates["etf"].tolist())
    covariance = returns.cov().fillna(0)
    variances = np.diag(covariance.to_numpy())
    marginal_risk = np.sqrt(np.maximum(variances, 1e-10))
    score_view = candidates.set_index("etf")["final_score"].clip(lower=0.01)
    raw_weights = pd.Series(1 / marginal_risk, index=covariance.index) * (score_view / score_view.mean()).clip(0.5, 1.5)
    weights = _cap_categories(raw_weights / raw_weights.sum(), candidates.set_index("etf")["category"])
    weights = weights * exposure
    output = candidates[candidates["etf"].isin(weights.index)].copy()
    output["weight"] = output["etf"].map(weights).fillna(0.0)
    output["date"] = pd.Timestamp.now().date().isoformat()
    output["regime"] = regime
    output["vix"] = vix
    output["volatility_126d"] = output["etf"].map(returns.std())
    output = output[["date", "etf", "name", "category", "aum_bn", "score_v3", "ml_prob", "final_score", "volatility_126d", "weight", "regime", "vix"]].rename(columns={"etf": "ticker"})
    cash = 1.0 - float(output["weight"].sum())
    if cash > 1e-6:
        output = pd.concat([output, pd.DataFrame([{"date": output["date"].iloc[0], "ticker": "CASH", "weight": cash, "regime": regime, "vix": vix}])], ignore_index=True)
    return output


def main() -> None:
    target = build_target_weights()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    target.to_csv(OUTPUT_PATH, index=False)
    print(f"[OK] {len(target)} target weights -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()