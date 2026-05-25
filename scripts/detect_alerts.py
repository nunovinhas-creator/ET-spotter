"""
Detecta alertas extraordinários com base nos dados mais recentes de cada ETF.
Imprime alertas no stdout e, se EMAIL_TO estiver definido, envia email.
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path("config/etfs.json")
DATA_DAILY = Path("data/daily")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def detect_alerts(last: pd.Series, thresholds: dict, symbol: str) -> list[str]:
    alerts = []

    ret_1h = last.get("ret_1h", 0) or 0
    ret_24h = last.get("ret_24h", 0) or 0
    vol_30 = last.get("vol_30", 0) or 0
    drawdown = last.get("drawdown", 0) or 0

    if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
        alerts.append(
            f"QUEDA HORÁRIA: {symbol} caiu {ret_1h:.2%} na última hora"
        )
    if ret_24h <= thresholds.get("ret_24h_drop", -0.03):
        alerts.append(
            f"QUEDA DIÁRIA: {symbol} caiu {ret_24h:.2%} nas últimas 24h"
        )
    if vol_30 >= thresholds.get("vol_spike", 0.04):
        alerts.append(
            f"VOLATILIDADE ELEVADA: {symbol} vol_30={vol_30:.2%}"
        )
    if drawdown <= -0.10:
        alerts.append(
            f"DRAWDOWN: {symbol} está {drawdown:.2%} abaixo do máximo"
        )

    return alerts


def main():
    cfg = load_config()
    thresholds = cfg["params"]["alert_thresholds"]
    symbols = cfg["etfs"]

    all_alerts: dict[str, list[str]] = {}

    for symbol in symbols:
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        last = df.iloc[-1]
        alerts = detect_alerts(last, thresholds, symbol)
        if alerts:
            all_alerts[symbol] = alerts

    if not all_alerts:
        print("[OK] Sem alertas activos.")
        return

    lines = []
    for symbol, msgs in all_alerts.items():
        for m in msgs:
            print(f"[ALERTA] {m}")
            lines.append(m)

    email_to = os.getenv("EMAIL_TO")
    if email_to:
        from send_email import send_alert_email
        subject = f"ET-Spotter: {len(lines)} alerta(s) activo(s)"
        body = "\n".join(lines)
        send_alert_email(subject, body, email_to)

    # Sai com código 1 se houver alertas (útil para CI)
    sys.exit(1)


if __name__ == "__main__":
    main()
