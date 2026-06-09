"""
Treina um modelo XGBoost para prever a direcção do retorno a 21 dias de cada ETF.

Features: indicadores técnicos já calculados nos ficheiros daily/
Target:   fwd_21d = close[t+21] / close[t] - 1  (construído aqui por shift)

Uso:
    python scripts/train_model.py

Output:
    data/models/xgb_signal.pkl   — modelo treinado
    data/models/model_report.txt — métricas e feature importance
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, classification_report,
                             roc_auc_score)
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).parent))
from paths import DATA_DAILY

MODELS_DIR = Path(__file__).parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

FEATURES = [
    "ret_5d", "ret_21d", "ret_63d", "ret_126d",
    "vol_21", "sharpe_63", "drawdown", "calmar_63",
    "rsi", "adx",
    "trend_sma", "above_sma200", "macd_bullish",
    "rs_mom_21", "rs_mom_63", "rs_positive",
    "macd_hist",
]

FWD_DAYS   = 21      # horizonte de previsão
TRAIN_CUTOFF = "2026-01-01"   # dados até aqui → treino; depois → teste


# ── 1. Carregar e construir dataset ──────────────────────────────────────────

def load_dataset() -> pd.DataFrame:
    frames = []
    for path in sorted(DATA_DAILY.glob("*.csv")):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        except Exception:
            continue
        if "close" not in df.columns or len(df) < FWD_DAYS + 50:
            continue

        df = df.sort_index()
        df["etf"] = path.stem

        # target: retorno forward a 21 dias
        df["fwd_21d"] = df["close"].shift(-FWD_DAYS) / df["close"] - 1

        # feature derivada: MACD histogram
        if "macd" in df.columns and "macd_signal" in df.columns:
            df["macd_hist"] = df["macd"] - df["macd_signal"]
        else:
            df["macd_hist"] = np.nan

        frames.append(df)

    if not frames:
        raise RuntimeError("Nenhum ficheiro daily encontrado.")

    data = pd.concat(frames).dropna(subset=["fwd_21d"] + FEATURES)
    data["target"] = (data["fwd_21d"] > 0).astype(int)
    print(f"[dataset] {len(data):,} linhas · {data['etf'].nunique()} ETFs · "
          f"{data.index.min().date()} → {data.index.max().date()}")
    return data


# ── 2. Split temporal ─────────────────────────────────────────────────────────

def split(data: pd.DataFrame):
    train = data[data.index < TRAIN_CUTOFF]
    test  = data[data.index >= TRAIN_CUTOFF]
    print(f"[split] treino {len(train):,} linhas · teste {len(test):,} linhas")
    return (train[FEATURES], train["target"],
            test[FEATURES],  test["target"],
            test["fwd_21d"], test["etf"])


# ── 3. Treinar ────────────────────────────────────────────────────────────────

def train(X_train: pd.DataFrame, y_train: pd.Series) -> XGBClassifier:
    pos_rate = y_train.mean()
    scale_pw  = (1 - pos_rate) / pos_rate   # class imbalance

    model = XGBClassifier(
        n_estimators=400,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=20,
        scale_pos_weight=scale_pw,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train,
              eval_set=[(X_train, y_train)],
              verbose=False)
    return model


# ── 4. Avaliar ────────────────────────────────────────────────────────────────

def evaluate(model, X_test, y_test, fwd_21d, etf_col):
    prob  = model.predict_proba(X_test)[:, 1]
    pred  = (prob >= 0.5).astype(int)

    acc   = accuracy_score(y_test, pred)
    auc   = roc_auc_score(y_test, prob)
    report = classification_report(y_test, pred, target_names=["DOWN","UP"])

    # simular estratégia: comprar quando prob >= 0.55, medir retorno médio
    mask_buy   = prob >= 0.55
    mask_nobuy = prob <  0.55

    avg_ret_ml   = fwd_21d[mask_buy].mean()   if mask_buy.any()   else float("nan")
    win_rate_ml  = (fwd_21d[mask_buy] > 0).mean() if mask_buy.any() else float("nan")
    avg_ret_skip = fwd_21d[mask_nobuy].mean() if mask_nobuy.any() else float("nan")

    # comparar com rule-based: usar rs_positive como proxy de "sinal positivo"
    mask_rb  = (X_test["rs_positive"] == 1) & (X_test["trend_sma"] == 1) & (X_test["above_sma200"] == 1)
    avg_ret_rb   = fwd_21d[mask_rb].mean()   if mask_rb.any()   else float("nan")
    win_rate_rb  = (fwd_21d[mask_rb] > 0).mean() if mask_rb.any() else float("nan")

    lines = [
        "=" * 60,
        "ET-Spotter — XGBoost Signal Model — Relatório de Avaliação",
        "=" * 60,
        f"\nPeríodo de teste: {TRAIN_CUTOFF} → fim",
        f"Linhas de teste:  {len(y_test):,}",
        "",
        f"Accuracy:  {acc:.3f}",
        f"ROC-AUC:   {auc:.3f}",
        "",
        report,
        "",
        "── Comparação de estratégias (retorno médio 21d) ──",
        f"ML (prob≥0.55):   retorno {avg_ret_ml:+.2%}  win-rate {win_rate_ml:.1%}  n={mask_buy.sum()}",
        f"ML (prob<0.55):   retorno {avg_ret_skip:+.2%}  (excluídos pelo modelo)",
        f"Rule-based proxy: retorno {avg_ret_rb:+.2%}  win-rate {win_rate_rb:.1%}  n={mask_rb.sum()}",
        f"Buy-and-hold all: retorno {fwd_21d.mean():+.2%}  win-rate {(fwd_21d>0).mean():.1%}",
    ]
    return "\n".join(lines), {"accuracy": acc, "auc": auc,
                               "avg_ret_ml": avg_ret_ml, "win_rate_ml": win_rate_ml,
                               "avg_ret_rb": avg_ret_rb, "win_rate_rb": win_rate_rb}


# ── 5. Feature importance ─────────────────────────────────────────────────────

def importance_lines(model) -> str:
    scores = model.feature_importances_
    pairs  = sorted(zip(FEATURES, scores), key=lambda x: x[1], reverse=True)
    lines  = ["\n── Feature Importance ──"]
    for feat, imp in pairs:
        bar = "█" * int(imp * 200)
        lines.append(f"  {feat:<20} {imp:.4f}  {bar}")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("[1/4] A carregar dados...")
    data = load_dataset()

    print("[2/4] A dividir treino/teste...")
    X_tr, y_tr, X_te, y_te, fwd, etf = split(data)

    print("[3/4] A treinar XGBoost...")
    model = train(X_tr, y_tr)

    print("[4/4] A avaliar...")
    report_text, metrics = evaluate(model, X_te, y_te, fwd, etf)
    report_text += importance_lines(model)

    print("\n" + report_text)

    # guardar modelo
    model_path = MODELS_DIR / "xgb_signal.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "features": FEATURES, "metrics": metrics}, f)
    print(f"\n[OK] Modelo guardado: {model_path}")

    report_path = MODELS_DIR / "model_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"[OK] Relatório:       {report_path}")


if __name__ == "__main__":
    main()
