"""
Detecta alertas intradiários e estruturais. Envia alertas via email e Telegram.

Alertas reactivos (dados horários):
  - Queda horária >= ret_1h_drop

Alertas estruturais (dados diários) — apenas quando a condição é NOVA:
  - Break da SMA200: preço cruzou abaixo pela primeira vez (ontem acima, hoje abaixo)
  - Deterioração de score: score cruzou abaixo de 0.40 (ontem >= 0.40, hoje < 0.40)
  - Queda rápida de score: score caiu > 0.07 numa sessão

Cada alerta inclui snapshot técnico completo e avaliação de entrada.
"""

import os
import sys
import html
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, compute_conviction, analyst_rationale

try:
    from constants import US_MARKET_HOURS, SCORE_DANGER, SCORE_DROP_FAST, SCORE_RECOVERY_THRESHOLD
except ImportError:
    US_MARKET_HOURS = (13, 22)
    SCORE_DANGER = 0.40
    SCORE_DROP_FAST = 0.07
    SCORE_RECOVERY_THRESHOLD = 0.48

DATA_HOURLY   = Path("data/hourly")
DATA_DAILY    = Path("data/daily")
SCORES_LATEST = Path("data/reports/scores_latest.csv")


def load_scores() -> dict:
    if not SCORES_LATEST.exists():
        return {}
    try:
        df = pd.read_csv(SCORES_LATEST)
        return {
            row["etf"]: {
                "score":     float(row.get("score",     0) or 0),
                "score_pct": float(row.get("score_pct", float("nan")) or float("nan")),
            }
            for _, row in df.iterrows()
        }
    except Exception:
        return {}


def load_technicals(symbol: str) -> dict:
    """Lê snapshot técnico completo do último registo diário do ETF."""
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return {}
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        return {
            "close":        float(last.get("close",       0) or 0),
            "sma20":        float(last.get("sma20",       0) or 0),
            "sma50":        float(last.get("sma50",       0) or 0),
            "sma200":       float(last.get("sma200",      0) or 0),
            "trend_sma":    int(last.get("trend_sma",     0) or 0),
            "macd_bullish": int(last.get("macd_bullish",  0) or 0),
            "above_sma200": int(last.get("above_sma200",  0) or 0),
            "rsi":          float(last.get("rsi",         50) or 50),
            "adx":          float(last.get("adx",         0) or 0),
            "rs_positive":  int(last.get("rs_positive",   0) or 0),
            "rs_mom_21":    float(last.get("rs_mom_21",   0) or 0),
            "rs_mom_63":    float(last.get("rs_mom_63",   0) or 0),
            "ret_1d":       float(last.get("ret_1d",      0) or 0),
            "ret_5d":       float(last.get("ret_5d",      0) or 0),
            "ret_21d":      float(last.get("ret_21d",     0) or 0),
            "ret_63d":      float(last.get("ret_63d",     0) or 0),
            "drawdown":     float(last.get("drawdown",    0) or 0),
            "vol_21":       float(last.get("vol_21",      0) or 0),
            "score":        float(last.get("score",       0) or 0),
            "score_prev":   float(prev.get("score",       0) or 0),
        }
    except Exception:
        return {}


def entry_assessment(alert_type: str, tech: dict) -> dict:
    """Gera avaliação contextual de entrada com base no tipo de alerta e técnicos."""
    rsi      = tech.get("rsi",         50)
    adx      = tech.get("adx",         0)
    score    = tech.get("score",       0)
    ret_63d  = tech.get("ret_63d",     0)
    ret_5d   = tech.get("ret_5d",      0)
    drawdown = tech.get("drawdown",    0)
    trend    = tech.get("trend_sma",   0)
    macd     = tech.get("macd_bullish",0)

    if alert_type == "BREAK SMA200":
        if rsi < 38:
            return {
                "verdict": "MONITORIZAR",
                "color": "#ffd54f",
                "explanation": f"RSI em sobrevenda ({rsi:.0f}) — possível bounce técnico na SMA200."
            }
        elif rsi > 52:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": f"Break da SMA200 com RSI elevado ({rsi:.0f}) — sem sobrevenda."
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": f"Break da SMA200 com RSI neutro ({rsi:.0f}). Zona de indecisão."
            }

    elif alert_type == "DETERIORAÇÃO":
        reasons = []
        if rsi < 40:
            reasons.append(f"RSI em sobrevenda ({rsi:.0f})")
        if ret_63d > 0.05:
            reasons.append(f"momentum 3M ainda positivo ({ret_63d:.1%})")
        if drawdown > -0.08:
            reasons.append(f"drawdown contido ({drawdown:.1%})")

        if len(reasons) >= 2 and rsi < 42:
            return {
                "verdict": "MONITORIZAR",
                "color": "#ffd54f",
                "explanation": f"Score entrou em zona de risco mas {' e '.join(reasons[:2])}."
            }
        elif ret_63d < -0.08 or rsi > 55:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": f"Score deteriorado com momentum 3M negativo ({ret_63d:.1%})."
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": "Score acabou de entrar em zona de risco. Monitorizar RSI."
            }

    elif alert_type == "QUEDA DE SCORE":
        if score > 0.52 and rsi < 55 and trend:
            return {
                "verdict": "MONITORIZAR",
                "color": "#ffd54f",
                "explanation": f"Score caiu mas mantém-se positivo ({score:.3f}). Tendência intacta."
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": f"Score em queda rápida ({score:.3f}). Aguardar estabilização."
            }

    elif alert_type == "RECUPERAÇÃO SCORE":
        return {
            "verdict": "MONITORIZAR",
            "color": "#4caf50",
            "explanation": f"Score recuperou para {score:.3f}. Confirmar com mais sessões."
        }

    elif alert_type == "RECUPERAÇÃO SMA200":
        return {
            "verdict": "MONITORIZAR",
            "color": "#4caf50",
            "explanation": "Preço recuperou acima da SMA200. Possível fim de tendência baixista."
        }

    else:  # QUEDA HORÁRIA
        if score >= 0.55 and rsi < 60 and drawdown > -0.10:
            return {
                "verdict": "OPORTUNIDADE",
                "color": "#4caf50",
                "explanation": f"Queda intradiária em ETF com fundamentais sólidos (score {score:.3f})."
            }
        elif score < 0.45:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": f"Queda horária em ETF fraco (score {score:.3f})."
            }
        else:
            return {
                "verdict": "NEUTRO",
                "color": "#78909c",
                "explanation": f"Queda intradiária com score intermédio ({score:.3f})."
            }


def detect_intraday_alerts(symbol: str, thresholds: dict) -> list[dict]:
    """Detecta quedas intradiárias durante horas de mercado US."""
    utc_hour = datetime.utcnow().hour
    if not (US_MARKET_HOURS[0] <= utc_hour <= US_MARKET_HOURS[1]):
        return []
    path = DATA_HOURLY / f"{symbol}.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty:
            return []
        df["ret_1h"] = df["close"].pct_change(1)
        ret_1h = float(df["ret_1h"].iloc[-1] or 0)
        if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
            tech = load_technicals(symbol)
            return [{"type": "QUEDA HORÁRIA", "symbol": symbol, "ret_1h": ret_1h, "tech": tech}]
        return []
    except Exception:
        return []


def detect_structural_alerts(symbol: str, scores: dict) -> list[dict]:
    """Detecta alertas estruturais (breaks, deteriorações, etc.)."""
    alerts = []
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or len(df) < 3:
            return []

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        prev2 = df.iloc[-3]
        tech = load_technicals(symbol)

        close_now    = float(last.get("close",  0) or 0)
        sma200_now   = float(last.get("sma200", 0) or 0)
        close_prev   = float(prev.get("close",  0) or 0)
        sma200_prev  = float(prev.get("sma200", 0) or 0)
        close_prev2  = float(prev2.get("close",  0) or 0)
        sma200_prev2 = float(prev2.get("sma200", 0) or 0)
        score_now   = tech.get("score",      scores.get(symbol, {}).get("score", 0))
        score_prev  = tech.get("score_prev", score_now)

        if (sma200_now > 0 and sma200_prev > 0 and sma200_prev2 > 0
                and close_prev2 >= sma200_prev2
                and close_prev  <  sma200_prev
                and close_now   <  sma200_now):
            alerts.append({
                "type": "BREAK SMA200", "symbol": symbol,
                "close": close_now, "sma200": sma200_now,
                "pct_below": (close_now - sma200_now) / sma200_now,
                "tech": tech,
            })

        if score_prev >= SCORE_DANGER > score_now:
            alerts.append({
                "type": "DETERIORAÇÃO", "symbol": symbol,
                "score": score_now, "score_prev": score_prev,
                "score_pct": scores.get(symbol, {}).get("score_pct", float("nan")),
                "tech": tech,
            })
        elif score_prev - score_now >= SCORE_DROP_FAST and score_now < 0.60:
            alerts.append({
                "type": "QUEDA DE SCORE", "symbol": symbol,
                "score": score_now, "score_prev": score_prev,
                "delta": score_prev - score_now,
                "tech": tech,
            })

        if score_prev < SCORE_DANGER and score_now >= SCORE_RECOVERY_THRESHOLD:
            alerts.append({
                "type": "RECUPERAÇÃO SCORE", "symbol": symbol,
                "score": score_now, "score_prev": score_prev,
                "delta": score_now - score_prev,
                "tech": tech,
            })

        if (sma200_now > 0 and sma200_prev > 0
                and close_prev < sma200_prev
                and close_now >= sma200_now):
            alerts.append({
                "type": "RECUPERAÇÃO SMA200", "symbol": symbol,
                "close": close_now, "sma200": sma200_now,
                "pct_above": (close_now - sma200_now) / sma200_now,
                "tech": tech,
            })

        return alerts
    except Exception:
        return []


def build_alert_html(all_alerts: list[dict], cmap: dict) -> str:
    """Constrói email HTML com os alertas."""
    ts = datetime.now().strftime("%d/%m/%Y  %H:%M")
    n  = len(all_alerts)

    type_color = {
        "BREAK SMA200":       ("#f44336", "#2a1010"),
        "DETERIORAÇÃO":       ("#ff7043", "#2a1508"),
        "QUEDA DE SCORE":     ("#ffd54f", "#2a2510"),
        "QUEDA HORÁRIA":      ("#ef5350", "#2a1010"),
        "RECUPERAÇÃO SCORE":  ("#4caf50", "#0d1f14"),
        "RECUPERAÇÃO SMA200": ("#29b6f6", "#0d1520"),
    }

    cards = ""
    for a in all_alerts:
        sym  = a["symbol"]
        info = cmap.get(sym, {})
        name = html.escape(info.get("name", sym))
        t    = a["type"]
        assessment = entry_assessment(t, a.get("tech", {}))

        clr, bg = type_color.get(t, ("#aaa", "#1a1d2e"))
        verdict_clr = assessment["color"]

        cards += f"""<div style="background:{bg};border-left:4px solid {clr};padding:14px;margin:10px 0;border-radius:4px">
          <div style="color:#e8eaf6;font-weight:bold">{html.escape(sym)} - {html.escape(t)}</div>
          <div style="color:#bbb;font-size:12px;margin-top:5px">{html.escape(assessment['explanation'])}</div>
        </div>"""

    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:sans-serif;padding:20px">
  <div style="max-width:660px;margin:0 auto">
    <div style="font-size:22px;font-weight:bold;color:#f44336">⚠ ET-Spotter — {n} alerta(s)</div>
    <div style="color:#555;font-size:12px;margin-top:4px">{ts}</div>
    {cards}
    <div style="color:#444;font-size:11px;text-align:center;margin-top:20px">ET-Spotter · dados via yfinance</div>
  </div>
</body></html>"""
    return html_content


def main():
    cfg        = load_config()
    thresholds = cfg["params"]["alert_thresholds"]
    scores     = load_scores()
    cmap       = get_category_map(cfg)
    all_alerts = []

    for symbol in get_etfs(cfg):
        all_alerts.extend(detect_intraday_alerts(symbol, thresholds))
        all_alerts.extend(detect_structural_alerts(symbol, scores))

    if not all_alerts:
        print("[OK] Sem alertas activos.")
        return

    for a in all_alerts:
        print(f"[ALERTA] {a['type']}: {a['symbol']}")

    # Enviar por email
    email_to = os.getenv("EMAIL_TO")
    if email_to:
        try:
            from send_email import send_email
            html    = build_alert_html(all_alerts, cmap)
            to_list = [t.strip() for t in email_to.split(",")]
            n       = len(all_alerts)
            tickers = ", ".join(a["symbol"] for a in all_alerts[:3])
            suffix  = "..." if n > 3 else ""
            
            send_email(
                f"ET-Spotter: {n} alerta{'s' if n!=1 else ''} — {tickers}{suffix}",
                html,
                to_list,
            )
            print(f"[EMAIL] ✓ Enviado para {email_to}")
        except Exception as e:
            print(f"[EMAIL] ✗ Erro: {e}")

    # Enviar por Telegram
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        try:
            from send_telegram import send_telegram_alert
            n = len(all_alerts)
            tickers = ", ".join(a["symbol"] for a in all_alerts[:3])
            suffix = "..." if n > 3 else ""
            
            message = f"🚨 <b>ET-Spotter: {n} alerta{'s' if n!=1 else ''}</b>\n\n{tickers}{suffix}"
            send_telegram_alert(message)
            print("[TELEGRAM] ✓ Alerta enviado")
        except Exception as e:
            print(f"[TELEGRAM] ✗ Erro: {e}")


if __name__ == "__main__":
    main()
