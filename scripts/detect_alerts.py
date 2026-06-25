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
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, compute_conviction, analyst_rationale, get_users
from constants import US_MARKET_HOURS, SCORE_DANGER, SCORE_DROP_FAST, SCORE_RECOVERY_THRESHOLD
from paths import DATA_INTRA as DATA_HOURLY, DATA_DAILY, REPORTS, SCORES_HIST

SCORES_LATEST = REPORTS / "scores_latest.csv"


def _load_prev_scores() -> dict[str, float]:
    """Lê o penúltimo score de cada ETF do histórico para calcular delta diário."""
    if not SCORES_HIST.exists():
        return {}
    try:
        hist = pd.read_csv(SCORES_HIST)
        result = {}
        for etf, grp in hist.groupby("etf"):
            s = grp["score"].dropna()
            if len(s) >= 2:
                result[str(etf)] = float(s.iloc[-2])
        return result
    except Exception:
        return {}


def load_scores() -> dict:
    if not SCORES_LATEST.exists():
        return {}
    try:
        df = pd.read_csv(SCORES_LATEST)
        return {
            r["etf"]: {
                "score":     float(r.get("score",     0) or 0),
                "score_pct": float(r.get("score_pct", float("nan")) or float("nan")),
            }
            for r in df.to_dict("records")
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
        }
    except Exception as e:
        print(f"[AVISO] load_technicals({symbol}): {e}", file=sys.stderr)
        return {}


def technical_snapshot(tech: dict) -> str:
    """Builds a compact one-line technical summary from available signal data. Zero-cost, rule-based."""
    import math
    parts = []

    score      = tech.get("score",        0)
    score_pct  = tech.get("score_pct",    float("nan"))
    rsi        = tech.get("rsi",          50)
    above_sma  = tech.get("above_sma200", 0)
    trend_sma  = tech.get("trend_sma",    0)
    ret_21d    = tech.get("ret_21d",      0)
    ret_63d    = tech.get("ret_63d",      0)
    drawdown   = tech.get("drawdown",     0)
    vol_21     = tech.get("vol_21",       0)

    if score > 0:
        pct_str = f" · top {100 - int(score_pct * 100)}% universo" if (score_pct and not math.isnan(score_pct)) else ""
        parts.append(f"Score {score:.2f}{pct_str}")

    parts.append("acima SMA200" if above_sma else "abaixo SMA200")

    if rsi >= 70:
        parts.append(f"RSI sobrecomprado ({rsi:.0f})")
    elif rsi <= 30:
        parts.append(f"RSI sobrevenda ({rsi:.0f})")
    else:
        parts.append(f"RSI {rsi:.0f}")

    if ret_63d != 0:
        sign = "+" if ret_63d > 0 else ""
        parts.append(f"momentum 3M {sign}{ret_63d:.1%}")

    if ret_21d != 0:
        sign = "+" if ret_21d > 0 else ""
        parts.append(f"1M {sign}{ret_21d:.1%}")

    if drawdown < -0.05:
        parts.append(f"drawdown {drawdown:.1%}")

    if vol_21 > 0:
        parts.append(f"vol {vol_21:.1%}")

    return " · ".join(parts)


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
    utc_hour = datetime.now(timezone.utc).hour
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
        val_1h = df["ret_1h"].iloc[-1]
        if pd.isna(val_1h):   # só 1 linha: sem retorno calculável
            return []
        ret_1h = float(val_1h)
        if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
            tech = load_technicals(symbol)
            return [{"type": "QUEDA HORÁRIA", "symbol": symbol, "ret_1h": ret_1h, "tech": tech}]
        return []
    except Exception as e:
        print(f"[AVISO] {symbol}: erro em alerta intradiário: {e}", file=sys.stderr)
        return []


def detect_structural_alerts(symbol: str, scores: dict, prev_scores: dict) -> list[dict]:
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
        score_now  = scores.get(symbol, {}).get("score", 0.0)
        score_prev = prev_scores.get(symbol, score_now)  # default: sem delta

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
    except Exception as e:
        print(f"[AVISO] {symbol}: erro em alerta estrutural: {e}", file=sys.stderr)
        return []


def build_alert_html(all_alerts: list[dict], cmap: dict) -> str:
    """Constrói email HTML com os alertas."""
    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M UTC")
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

        snapshot = technical_snapshot(a.get("tech", {}))
        cards += f"""<div style="background:{bg};border-left:4px solid {clr};padding:14px;margin:10px 0;border-radius:4px">
          <div style="color:#e8eaf6;font-weight:bold">{html.escape(sym)} — {name} — {html.escape(t)}</div>
          <div style="color:#bbb;font-size:12px;margin-top:5px">{html.escape(assessment['explanation'])}</div>
          <div style="color:#666;font-size:11px;margin-top:6px;font-family:monospace">{html.escape(snapshot)}</div>
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


def _resolve_thresholds(user: dict, global_thresholds: dict) -> dict:
    """Merges per-user threshold overrides with global defaults."""
    merged = dict(global_thresholds)
    merged.update(user.get("thresholds", {}) or {})
    return merged


def _filter_alerts_for_user(all_alerts: list[dict], watchlist: list[str] | None) -> list[dict]:
    """Returns alerts filtered to user's watchlist; all alerts when watchlist is None/empty."""
    if not watchlist:
        return all_alerts
    wl = set(watchlist)
    return [a for a in all_alerts if a["symbol"] in wl]


def main():
    cfg             = load_config()
    global_thresh   = cfg["params"]["alert_thresholds"]
    scores          = load_scores()
    prev_scores     = _load_prev_scores()
    cmap            = get_category_map(cfg)
    telegram_token  = os.getenv("TELEGRAM_BOT_TOKEN")

    all_alerts: list[dict] = []
    for symbol in get_etfs(cfg):
        all_alerts.extend(detect_intraday_alerts(symbol, global_thresh))
        all_alerts.extend(detect_structural_alerts(symbol, scores, prev_scores))

    if not all_alerts:
        print("[OK] Sem alertas activos.")
        return

    for a in all_alerts:
        print(f"[ALERTA] {a['type']}: {a['symbol']}")

    users = get_users(cfg)
    if not users:
        print("[AVISO] Nenhum utilizador configurado.")
        return

    from send_email import send_email

    for user in users:
        user_alerts = _filter_alerts_for_user(all_alerts, user.get("watchlist"))
        if not user_alerts:
            continue

        n       = len(user_alerts)
        tickers = ", ".join(a["symbol"] for a in user_alerts[:3])
        suffix  = "..." if n > 3 else ""
        subject = f"ET-Spotter: {n} alerta{'s' if n!=1 else ''} — {tickers}{suffix}"

        email_to = user.get("email", "")
        if email_to:
            try:
                alert_html = build_alert_html(user_alerts, cmap)
                to_list = [t.strip() for t in email_to.split(",") if t.strip()]
                send_email(to_list, subject, alert_html)
                print(f"[EMAIL] ✓ {user.get('name', email_to)}: {n} alerta(s)")
            except Exception as e:
                print(f"[EMAIL] ✗ {user.get('name', email_to)}: {e}", file=sys.stderr)

        tg_chat = user.get("telegram_chat_id", "")
        if tg_chat and telegram_token:
            try:
                from send_telegram import send_telegram_alert
                tg_lines = []
                for a in user_alerts[:5]:
                    sym = a["symbol"]
                    info = cmap.get(sym, {})
                    name_short = info.get("name", sym)[:30]
                    snap = technical_snapshot(a.get("tech", {}))
                    tg_lines.append(f"<b>{sym}</b> {a['type']}\n<i>{name_short}</i>\n{snap}")
                suffix_tg = f"\n…+{n-5} mais" if n > 5 else ""
                message = f"🚨 <b>ET-Spotter: {n} alerta{'s' if n!=1 else ''}</b>\n\n" + "\n\n".join(tg_lines) + suffix_tg
                send_telegram_alert(message, chat_id=tg_chat)
                print(f"[TELEGRAM] ✓ {user.get('name', tg_chat)}: {n} alerta(s)")
            except Exception as e:
                print(f"[TELEGRAM] ✗ {user.get('name', tg_chat)}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
