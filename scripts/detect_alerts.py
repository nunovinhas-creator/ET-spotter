"""
Detecta alertas intradiários e envia email se EMAIL_TO estiver definido.

Lê dados horários de data/hourly/SYMBOL.csv para alertas de queda horária.
Enriquece alertas com o score actual de data/reports/scores_latest.csv.
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs

DATA_HOURLY   = Path("data/hourly")
SCORES_LATEST = Path("data/reports/scores_latest.csv")


def load_scores() -> dict:
    """Carrega scores actuais de scores_latest.csv → {etf: score}."""
    if not SCORES_LATEST.exists():
        return {}
    try:
        df = pd.read_csv(SCORES_LATEST)
        return dict(zip(df["etf"], df["score"]))
    except Exception:
        return {}


def detect_alerts(last: pd.Series, thresholds: dict, symbol: str,
                  scores: dict) -> list[str]:
    alerts = []
    ret_1h = float(last.get("ret_1h", 0) or 0)

    if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
        score_str = ""
        if symbol in scores:
            score_str = f" | score={scores[symbol]:.3f}"
        alerts.append(
            f"QUEDA HORÁRIA: {symbol} {ret_1h:.2%} na última hora{score_str}"
        )

    return alerts


def main():
    cfg        = load_config()
    thresholds = cfg["params"]["alert_thresholds"]
    scores     = load_scores()
    all_alerts: dict[str, list[str]] = {}

    for symbol in get_etfs(cfg):
        path = DATA_HOURLY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        # Calcula ret_1h a partir dos dados horários
        df["ret_1h"] = df["close"].pct_change(1)
        alerts = detect_alerts(df.iloc[-1], thresholds, symbol, scores)
        if alerts:
            all_alerts[symbol] = alerts

    if not all_alerts:
        print("[OK] Sem alertas activos.")
        return

    lines = []
    for msgs in all_alerts.values():
        for m in msgs:
            print(f"[ALERTA] {m}")
            lines.append(m)

    email_to = os.getenv("EMAIL_TO")
    if email_to:
        from send_email import send_alert_email
        send_alert_email(
            f"ET-Spotter: {len(lines)} alerta(s) activo(s)",
            "\n".join(lines),
            email_to,
        )

    sys.exit(1)


if __name__ == "__main__":
    main()
