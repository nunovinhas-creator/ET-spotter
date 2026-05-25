"""
Detecta alertas extraordinários e envia email se EMAIL_TO estiver definido.
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs

DATA_DAILY = Path("data/daily")


def detect_alerts(last: pd.Series, thresholds: dict, symbol: str) -> list[str]:
    alerts = []
    ret_1h   = last.get("ret_1h",   0) or 0
    ret_24h  = last.get("ret_24h",  0) or 0
    vol_30   = last.get("vol_30",   0) or 0
    drawdown = last.get("drawdown", 0) or 0

    if ret_1h   <= thresholds.get("ret_1h_drop",  -0.02):
        alerts.append(f"QUEDA HORÁRIA: {symbol} {ret_1h:.2%} na última hora")
    if ret_24h  <= thresholds.get("ret_24h_drop", -0.03):
        alerts.append(f"QUEDA DIÁRIA: {symbol} {ret_24h:.2%} nas últimas 24h")
    if vol_30   >= thresholds.get("vol_spike",     0.60):
        alerts.append(f"VOLATILIDADE ELEVADA: {symbol} vol_30={vol_30:.2%}")
    if drawdown <= -0.10:
        alerts.append(f"DRAWDOWN: {symbol} {drawdown:.2%} abaixo do máximo")

    return alerts


def main():
    cfg        = load_config()
    thresholds = cfg["params"]["alert_thresholds"]
    all_alerts: dict[str, list[str]] = {}

    for symbol in get_etfs(cfg):
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            continue
        alerts = detect_alerts(df.iloc[-1], thresholds, symbol)
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
