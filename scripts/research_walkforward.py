#!/usr/bin/env python3
"""XGBoost walk-forward purgado; apenas avaliação preditiva fora da amostra.

Treino tem de satisfazer label_end < test_start (o retorno forward 21d
já era conhecido). Não reusa um modelo treinado com dados futuros.
As previsões fora da amostra NÃO representam backtest investível da
carteira operacional 60/40. Preços e features são em EUR no modo estrito.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_metrics import compute_metrics
from research_fx import convert_folder
from train_model import FEATURES, FWD_DAYS

WINDOW_SESSIONS = 63
MIN_TRAIN_SESSIONS = 504
MODEL_PARAMS = dict(n_estimators=140, max_depth=3, learning_rate=0.05,
                    subsample=0.85, colsample_bytree=0.85, min_child_weight=20,
                    random_state=42, n_jobs=2, eval_metric="logloss")


def prepared_dataset(root: Path) -> tuple[pd.DataFrame, dict]:
    config = json.loads((Path(__file__).resolve().parent.parent / "config/etfs.json").read_text())
    tickers = sorted({etf["ticker"] for cat in config["categories"] for etf in cat["etfs"]})
    converted, audit = convert_folder(root, tickers + ["SPY"], fail_on_unknown=False)
    if "SPY" not in converted:
        raise ValueError("SPY sem conversão EUR comprovada")
    spy = converted["SPY"]["close"]
    observations = []
    for ticker in tickers:
        df = converted.get(ticker)
        if df is None or len(df) < 300:
            continue
        features = compute_metrics(df, spy_close=spy)
        features["macd_hist"] = features["macd"] - features["macd_signal"]
        features["etf"] = ticker
        features["date"] = features.index
        features["fwd_21d"] = features["close"].shift(-FWD_DAYS) / features["close"] - 1
        # Datas reais de chegada do alvo em vez de embargo aproximado em
        # dias de calendário. Um target de dezembro que acaba em janeiro
        # NÃO pode entrar no treino de testes que começam em janeiro.
        features["label_end"] = pd.Series(features.index, index=features.index).shift(-FWD_DAYS)
        features["target"] = (features["fwd_21d"] > 0).astype(int)
        observations.append(features)
    if not observations:
        raise ValueError("Sem históricos de ETFs suficientes para treino OOS")
    result = pd.concat(observations, ignore_index=True)
    result = result.dropna(subset=[*FEATURES, "fwd_21d", "label_end"])
    result = result.sort_values(["date", "etf"]).reset_index(drop=True)
    audit["usable_etfs"] = result["etf"].nunique()
    audit["rows"] = len(result)
    return result, audit


def split_with_label_purge(frame: pd.DataFrame, start: pd.Timestamp,
                           end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cada rótulo de treino tem de estar resolvido ANTES de start."""
    train = frame[(frame["date"] < start) & (frame["label_end"] < start)].copy()
    test = frame[(frame["date"] >= start) & (frame["date"] < end)].copy()
    if not train.empty and not (train["label_end"] < test["date"].min()).all() and not test.empty:
        raise AssertionError("Rótulos de treino invadem a janela OOS")
    return train, test


def run_walkforward(frame: pd.DataFrame,
                    test_from: str = "2020-01-01",
                    test_until: str = "2026-10-23",
                    min_train_sessions: int = MIN_TRAIN_SESSIONS,
                    window_sessions: int = WINDOW_SESSIONS):
    from xgboost import XGBClassifier
    dates = pd.DatetimeIndex(sorted(frame["date"].dropna().unique()))
    dates = dates[(dates >= pd.Timestamp(test_from) - pd.DateOffset(years=12))
                  & (dates <= pd.Timestamp(test_until))]
    if len(dates) < min_train_sessions + window_sessions:
        raise ValueError("Histórico insuficiente para walk-forward independente")
    preds = []
    folds = []
    # O início fixado antes do treino impede escolher retrospetivamente a
    # primeira janela que mais favorece os resultados.
    first = max(min_train_sessions, dates.searchsorted(pd.Timestamp(test_from)))
    for idx in range(first, len(dates), window_sessions):
        t0 = dates[idx]
        t1 = dates[min(idx + window_sessions, len(dates)-1)] + pd.Timedelta(days=1)
        train, test = split_with_label_purge(frame, t0, t1)
        if train["date"].nunique() < min_train_sessions or test.empty or train["target"].nunique() < 2:
            continue
        model = XGBClassifier(**MODEL_PARAMS)
        model.fit(train[FEATURES].astype(float), train["target"])
        probability = model.predict_proba(test[FEATURES].astype(float))[:, 1]
        baseline = float(train["target"].mean())
        batch = test[["date", "etf", "label_end", "fwd_21d", "target"]].copy()
        batch["prob"] = probability
        batch["baseline_prob"] = baseline
        batch["fold_start"] = t0
        batch["train_last_label_end"] = train["label_end"].max()
        if not (batch["train_last_label_end"] < batch["date"]).all():
            raise AssertionError("Look-ahead detectado no treino")
        preds.append(batch)
        folds.append({"fold_start": t0.strftime("%Y-%m-%d"),
                      "test_end": test["date"].max().strftime("%Y-%m-%d"),
                      "train_rows": len(train), "test_rows": len(test),
                      "train_last_label_end": train["label_end"].max().strftime("%Y-%m-%d"),
                      "test_first_decision": test["date"].min().strftime("%Y-%m-%d"),
                      "model_params": MODEL_PARAMS})
    if not preds:
        raise ValueError("Nenhuma janela OOS válida; sem resultados não há afirmações")
    output = pd.concat(preds).sort_values(["date", "etf"])
    y = output["target"].astype(int)
    def safe_auc(pred):
        return float(roc_auc_score(y, pred)) if y.nunique() == 2 else None
    prob = output["prob"].astype(float)
    baseline = output["baseline_prob"].astype(float)
    summary = {
        "status": "POINT_IN_TIME_XGB_OOS_PREDICTION_ONLY",
        "interpretation": "AUC e Brier preditivos; NÃO é retorno de carteira 60/40",
        "observations": len(output), "etfs": output["etf"].nunique(),
        "first_prediction": output["date"].min().strftime("%Y-%m-%d"),
        "last_prediction": output["date"].max().strftime("%Y-%m-%d"),
        "fold_count": len(folds), "label_horizon_sessions": FWD_DAYS,
        "auc_xgb": safe_auc(prob), "auc_baseline": safe_auc(baseline),
        "brier_xgb": float(brier_score_loss(y, prob)),
        "brier_baseline": float(brier_score_loss(y, baseline)),
        "accuracy_xgb": float(accuracy_score(y, prob >= 0.5)),
        "accuracy_baseline": float(accuracy_score(y, baseline >= 0.5)),
        "mean_forward_return_if_prob_ge_055": (
            float(output.loc[output["prob"] >= .55, "fwd_21d"].mean())
            if (output["prob"] >= .55).any() else None),
        "mean_forward_return_buy_hold": float(output["fwd_21d"].mean()),
        "fractions_selected": float((prob >= .55).mean()),
        "folds": folds,
        "limitations": [
            "Resultados de sinais de 21 dias sobrepostos, não P/L executável de portfólio",
            "Estratégia operacional 60/40 não reproduzida (fase posterior)",
            "Universo contemporâneo pode omitir ETFs descontinuados",
            "Parâmetros definidos após 2020: inferência histórica é exploratória",
            "Modelo refeito por janela; não é o modelo serializado de produção",
        ],
    }
    return output, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices-dir", type=Path, default=Path("data/research_prices"))
    ap.add_argument("--test-from", default="2020-01-01")
    ap.add_argument("--test-until", default="2026-10-23")
    ap.add_argument("--output", type=Path, default=Path("research_results"))
    args = ap.parse_args()
    ds, currency_audit = prepared_dataset(args.prices_dir)
    predictions, report = run_walkforward(ds, args.test_from, args.test_until)
    report["currency_audit"] = currency_audit
    args.output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(args.output / "walkforward_oos_predictions.csv", index=False)
    (args.output / "walkforward_oos_metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("folds", "currency_audit")},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
