"""
Detecta alertas intradiários e estruturais. Envia email se EMAIL_TO estiver definido.

Alertas reactivos (dados horários):
  - Queda horária >= ret_1h_drop

Alertas estruturais (dados diários):
  - Break da SMA200: preço fechou abaixo da SMA200 pela primeira vez
  - Score de deterioração: score caiu abaixo de 0.40 (sinal de risco)
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs

DATA_HOURLY   = Path("data/hourly")
DATA_DAILY    = Path("data/daily")
SCORES_LATEST = Path("data/reports/scores_latest.csv")

SCORE_DANGER  = 0.40   # abaixo disto → alerta de deterioração


def load_scores() -> dict:
    """Carrega scores actuais → {etf: {"score": float, "score_pct": float}}."""
    if not SCORES_LATEST.exists():
        return {}
    try:
        df = pd.read_csv(SCORES_LATEST)
        result = {}
        for _, row in df.iterrows():
            result[row["etf"]] = {
                "score":     float(row.get("score",     0) or 0),
                "score_pct": float(row.get("score_pct", float("nan")) or float("nan")),
            }
        return result
    except Exception:
        return {}


def _score_str(symbol: str, scores: dict) -> str:
    if symbol not in scores:
        return ""
    s = scores[symbol]
    pct = s["score_pct"]
    pct_str = f" | P{pct*100:.0f}" if pd.notna(pct) else ""
    return f" | score={s['score']:.3f}{pct_str}"


# ── Alertas reactivos (horários) ──────────────────────────────────────────────

def detect_intraday_alerts(symbol: str, thresholds: dict, scores: dict) -> list[str]:
    path = DATA_HOURLY / f"{symbol}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty:
        return []

    df["ret_1h"] = df["close"].pct_change(1)
    ret_1h = float(df["ret_1h"].iloc[-1] or 0)

    if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
        return [f"QUEDA HORÁRIA: {symbol} {ret_1h:.2%} na última hora{_score_str(symbol, scores)}"]
    return []


# ── Alertas estruturais (diários) ─────────────────────────────────────────────

def detect_structural_alerts(symbol: str, scores: dict) -> list[str]:
    """
    Dois tipos de alertas preditivos que não dependem de dados horários:
      1. Break da SMA200 — sinal de risco estrutural (tendência de longo prazo invertida)
      2. Score < 0.40 — deterioração rápida dos fundamentos técnicos
    """
    alerts = []
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return []

    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty or len(df) < 2:
        return []

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 1. Break da SMA200: estava acima ontem, está abaixo hoje
    if "sma200" in df.columns and "close" in df.columns:
        close_now  = float(last.get("close",  0) or 0)
        sma200_now = float(last.get("sma200", 0) or 0)
        close_prev = float(prev.get("close",  0) or 0)
        sma200_prev= float(prev.get("sma200", 0) or 0)

        if (sma200_now > 0 and sma200_prev > 0
                and close_prev >= sma200_prev
                and close_now  <  sma200_now):
            pct_below = (close_now - sma200_now) / sma200_now
            alerts.append(
                f"BREAK SMA200: {symbol} fechou abaixo da SMA200"
                f" ({close_now:.2f} vs {sma200_now:.2f}, {pct_below:.2%})"
                f"{_score_str(symbol, scores)}"
            )

    # 2. Score de deterioração: abaixo do limiar de risco
    if symbol in scores:
        score = scores[symbol]["score"]
        if score < SCORE_DANGER:
            score_pct = scores[symbol]["score_pct"]
            pct_str = f" | P{score_pct*100:.0f} histórico" if pd.notna(score_pct) else ""
            alerts.append(
                f"DETERIORAÇÃO: {symbol} score={score:.3f} (abaixo de {SCORE_DANGER}){pct_str}"
                " — reavaliar posição"
            )

    return alerts


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    cfg        = load_config()
    thresholds = cfg["params"]["alert_thresholds"]
    scores     = load_scores()
    all_alerts: dict[str, list[str]] = {}

    for symbol in get_etfs(cfg):
        msgs = (
            detect_intraday_alerts(symbol, thresholds, scores)
            + detect_structural_alerts(symbol, scores)
        )
        if msgs:
            all_alerts[symbol] = msgs

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
