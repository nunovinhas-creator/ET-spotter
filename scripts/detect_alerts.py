"""
Detecta alertas intradiários e estruturais. Envia email HTML se EMAIL_TO estiver definido.

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
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, compute_conviction, analyst_rationale

DATA_HOURLY   = Path("data/hourly")
DATA_DAILY    = Path("data/daily")
SCORES_LATEST = Path("data/reports/scores_latest.csv")

SCORE_DANGER    = 0.40
SCORE_DROP_FAST = 0.07


# ── Dados de suporte ──────────────────────────────────────────────────────────

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


# ── Avaliação de entrada ──────────────────────────────────────────────────────

def entry_assessment(alert_type: str, tech: dict) -> dict:
    """
    Gera avaliação contextual de entrada com base no tipo de alerta e técnicos.
    Devolve {"verdict": str, "color": str, "explanation": str}.
    """
    rsi      = tech.get("rsi",         50)
    adx      = tech.get("adx",         0)
    score    = tech.get("score",       0)
    ret_63d  = tech.get("ret_63d",     0)
    ret_5d   = tech.get("ret_5d",      0)
    drawdown = tech.get("drawdown",    0)
    trend    = tech.get("trend_sma",   0)
    macd     = tech.get("macd_bullish",0)
    rs_pos   = tech.get("rs_positive", 0)
    above200 = tech.get("above_sma200",0)

    if alert_type == "BREAK SMA200":
        if rsi < 38:
            return {
                "verdict": "MONITORIZAR",
                "color": "#ffd54f",
                "explanation": (
                    f"RSI em sobrevenda ({rsi:.0f}) — possível bounce técnico na SMA200. "
                    f"Aguardar 1-2 sessões de estabilização e MACD a virar antes de entrar. "
                    f"Risco: se RSI cair abaixo de 30 sem bounce, breakdown confirmado."
                )
            }
        elif rsi > 52:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": (
                    f"Break da SMA200 com RSI ainda elevado ({rsi:.0f}) — não há sobrevenda, "
                    f"o mercado não considera este preço barato. "
                    f"Tendência de longo prazo invertida. Risco assimétrico negativo."
                )
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": (
                    f"Break da SMA200 com RSI neutro ({rsi:.0f}). "
                    f"Zona de indecisão — aguardar reclame da SMA200 como suporte "
                    f"(preço a fechar acima durante 2+ sessões) antes de qualquer entrada."
                )
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
                "explanation": (
                    f"Score entrou em zona de risco mas {' e '.join(reasons[:2])}. "
                    f"Possível oportunidade contrária de curto prazo. "
                    f"Confirmar com MACD e volume antes de entrar."
                )
            }
        elif ret_63d < -0.08 or rsi > 55:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": (
                    f"Score deteriorado com momentum 3M negativo ({ret_63d:.1%}) "
                    f"e RSI sem sinais de sobrevenda ({rsi:.0f}). "
                    f"Sem catalisador visível para recuperação no curto prazo."
                )
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": (
                    f"Score acabou de entrar em zona de risco. "
                    f"Monitorizar RSI (entrada potencial se descer abaixo de 40) "
                    f"e ret 5d (confirmar estabilização)."
                )
            }

    elif alert_type == "QUEDA DE SCORE":
        if score > 0.52 and rsi < 55 and trend:
            return {
                "verdict": "MONITORIZAR",
                "color": "#ffd54f",
                "explanation": (
                    f"Score caiu mas mantém-se em território positivo ({score:.3f}). "
                    f"Tendência de médio prazo intacta (SMA20>SMA50). "
                    f"RSI ({rsi:.0f}) tem espaço para recuperação — possível ponto de entrada se score estabilizar."
                )
            }
        else:
            return {
                "verdict": "AGUARDAR",
                "color": "#ff7043",
                "explanation": (
                    f"Score em queda rápida ({score:.3f}). "
                    f"Aguardar estabilização do score durante 2+ sessões "
                    f"antes de avaliar entrada. Verificar se há news ou evento sectorial."
                )
            }

    else:  # QUEDA HORÁRIA
        if score >= 0.55 and rsi < 60 and drawdown > -0.10:
            return {
                "verdict": "OPORTUNIDADE",
                "color": "#4caf50",
                "explanation": (
                    f"Queda intradiária em ETF com fundamentais sólidos (score {score:.3f}, "
                    f"RSI {rsi:.0f}, drawdown {drawdown:.1%}). "
                    f"Quedas pontuais em ETFs com score alto são frequentemente oportunidades de entrada. "
                    f"Verificar se é específico do ETF ou movimento de mercado amplo (SPY)."
                )
            }
        elif score < 0.45:
            return {
                "verdict": "EVITAR",
                "color": "#f44336",
                "explanation": (
                    f"Queda horária em ETF já fraco (score {score:.3f}). "
                    f"Ausência de fundamentos que suportem recuperação — não é oportunidade de entrada."
                )
            }
        else:
            return {
                "verdict": "NEUTRO",
                "color": "#78909c",
                "explanation": (
                    f"Queda intradiária com score intermédio ({score:.3f}). "
                    f"Verificar contexto de mercado (SPY) e aguardar close do dia."
                )
            }


# ── Detecção de alertas ───────────────────────────────────────────────────────

def detect_intraday_alerts(symbol: str, thresholds: dict) -> list[dict]:
    path = DATA_HOURLY / f"{symbol}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty:
        return []
    df["ret_1h"] = df["close"].pct_change(1)
    ret_1h = float(df["ret_1h"].iloc[-1] or 0)
    if ret_1h <= thresholds.get("ret_1h_drop", -0.02):
        tech = load_technicals(symbol)
        return [{"type": "QUEDA HORÁRIA", "symbol": symbol, "ret_1h": ret_1h, "tech": tech}]
    return []


def detect_structural_alerts(symbol: str, scores: dict) -> list[dict]:
    alerts = []
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return []
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty or len(df) < 2:
        return []

    last = df.iloc[-1]
    prev = df.iloc[-2]
    tech = load_technicals(symbol)

    close_now   = float(last.get("close",  0) or 0)
    sma200_now  = float(last.get("sma200", 0) or 0)
    close_prev  = float(prev.get("close",  0) or 0)
    sma200_prev = float(prev.get("sma200", 0) or 0)
    score_now   = tech.get("score",      scores.get(symbol, {}).get("score", 0))
    score_prev  = tech.get("score_prev", score_now)

    if (sma200_now > 0 and sma200_prev > 0
            and close_prev >= sma200_prev
            and close_now  <  sma200_now):
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

    return alerts


# ── HTML ──────────────────────────────────────────────────────────────────────

def _c(v: float, neutral: float = 0) -> str:
    return "#4caf50" if v > neutral else ("#f44336" if v < neutral else "#aaa")


def _ind(label: str, value: str, color: str = "#e8eaf6") -> str:
    return (
        f'<span style="margin-right:14px">'
        f'<span style="color:#666;font-size:10px">{label}</span>&nbsp;'
        f'<span style="color:{color};font-weight:bold;font-size:12px">{value}</span>'
        f'</span>'
    )


def tech_grid(tech: dict) -> str:
    """Linha de indicadores técnicos resumidos."""
    if not tech:
        return ""
    rsi      = tech.get("rsi",         50)
    adx      = tech.get("adx",         0)
    ret_63d  = tech.get("ret_63d",     0)
    ret_5d   = tech.get("ret_5d",      0)
    drawdown = tech.get("drawdown",    0)
    score    = tech.get("score",       0)
    trend    = tech.get("trend_sma",   0)
    macd     = tech.get("macd_bullish",0)
    rs_pos   = tech.get("rs_positive", 0)
    above200 = tech.get("above_sma200",0)

    rsi_c = "#4caf50" if 40 <= rsi <= 65 else ("#ffd54f" if rsi > 70 else "#f44336" if rsi < 30 else "#aaa")

    return (
        '<div style="margin-top:10px;padding:8px 10px;background:#0d0f17;'
        'border-radius:4px;line-height:2">'
        + _ind("Score",   f"{score:.3f}", _c(score, 0.50))
        + _ind("RSI",     f"{rsi:.0f}",  rsi_c)
        + _ind("ADX",     f"{adx:.0f}",  "#4caf50" if adx > 25 else "#aaa")
        + _ind("Ret.3M",  f"{ret_63d:.1%}", _c(ret_63d))
        + _ind("Ret.5d",  f"{ret_5d:.1%}",  _c(ret_5d))
        + _ind("Drawdown",f"{drawdown:.1%}", _c(drawdown, -0.05))
        + _ind("Trend",   "↑" if trend else "↓",  "#4caf50" if trend else "#f44336")
        + _ind("MACD",    "+" if macd else "−",    "#4caf50" if macd else "#f44336")
        + _ind("RS/SPY",  "✓" if rs_pos else "✗",  "#4caf50" if rs_pos else "#f44336")
        + _ind("SMA200",  "✓" if above200 else "✗","#4caf50" if above200 else "#f44336")
        + '</div>'
    )


def build_alert_html(all_alerts: list[dict], cmap: dict) -> str:
    ts = datetime.now().strftime("%d/%m/%Y  %H:%M")
    n  = len(all_alerts)

    type_order = {"BREAK SMA200": 0, "DETERIORAÇÃO": 1, "QUEDA DE SCORE": 2, "QUEDA HORÁRIA": 3}
    type_color = {
        "BREAK SMA200":  ("#f44336", "#2a1010"),
        "DETERIORAÇÃO":  ("#ff7043", "#2a1508"),
        "QUEDA DE SCORE":("#ffd54f", "#2a2510"),
        "QUEDA HORÁRIA": ("#ef5350", "#2a1010"),
    }
    all_alerts.sort(key=lambda x: type_order.get(x["type"], 9))

    cards = ""
    for a in all_alerts:
        sym  = a["symbol"]
        info = cmap.get(sym, {})
        name = info.get("name", sym)
        cat  = info.get("category_name", "—")
        cor  = info.get("color", "#7c83fd")
        t    = a["type"]
        tech = a.get("tech", {})
        clr, bg = type_color.get(t, ("#aaa", "#1a1d2e"))

        # Avaliação de entrada
        assessment = entry_assessment(t, tech)
        verdict_clr = assessment["color"]
        verdict_lbl = assessment["verdict"]
        explanation = assessment["explanation"]

        badge = (
            f'<span style="background:{clr};color:#000;padding:2px 9px;'
            f'border-radius:10px;font-size:11px;font-weight:bold">{t}</span>'
        )
        verdict_badge = (
            f'<span style="background:{verdict_clr};color:#000;padding:2px 9px;'
            f'border-radius:10px;font-size:11px;font-weight:bold">{verdict_lbl}</span>'
        )

        if t == "QUEDA HORÁRIA":
            event_detail = f'Queda de <b style="color:{clr}">{a["ret_1h"]:.2%}</b> na última hora'
        elif t == "BREAK SMA200":
            event_detail = (
                f'Preço <b style="color:{clr}">{a["close"]:.2f}</b> fechou abaixo '
                f'da SMA200 ({a["sma200"]:.2f}) — '
                f'<span style="color:{clr}">{a["pct_below"]:.2%} abaixo</span>'
            )
        elif t == "DETERIORAÇÃO":
            pct = a.get("score_pct")
            pct_str = f'&nbsp;·&nbsp;P{pct*100:.0f} histórico' if pd.notna(pct) else ""
            event_detail = (
                f'Score cruzou abaixo de {SCORE_DANGER}: '
                f'<b style="color:{clr}">{a["score"]:.3f}</b> '
                f'(era {a["score_prev"]:.3f}){pct_str}'
            )
        else:
            event_detail = (
                f'Score caiu <b style="color:{clr}">−{a["delta"]:.3f}</b> '
                f'numa sessão: {a["score_prev"]:.3f} → {a["score"]:.3f}'
            )

        cards += f"""
        <div style="background:{bg};border-left:4px solid {clr};
                    padding:14px 18px;margin:10px 0;border-radius:4px">

          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px">
            <span style="color:#e8eaf6;font-size:18px;font-weight:bold">{sym}</span>
            <span style="color:#888;font-size:11px">{name}</span>
            {badge}
            <span style="color:{cor};font-size:11px">● {cat}</span>
          </div>

          <div style="color:#ccc;font-size:12px;margin-bottom:8px">{event_detail}</div>

          {tech_grid(tech)}

          <div style="margin-top:10px;padding:10px 12px;background:#111420;
                      border-radius:4px;border-left:3px solid {verdict_clr}">
            <div style="margin-bottom:5px">{verdict_badge}</div>
            <div style="color:#bbb;font-size:12px;line-height:1.6">{explanation}</div>
          </div>

        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:sans-serif;margin:0;padding:20px">
  <div style="max-width:660px;margin:0 auto">

    <div style="border-bottom:1px solid #1e2130;padding-bottom:12px;margin-bottom:20px">
      <div style="font-size:22px;font-weight:bold;color:#f44336">
        ⚠ ET-Spotter — {n} alerta{'s' if n != 1 else ''} activo{'s' if n != 1 else ''}
      </div>
      <div style="color:#555;font-size:12px;margin-top:4px">{ts} · apenas eventos novos desta sessão</div>
    </div>

    {cards}

    <div style="border-top:1px solid #1e2130;margin-top:24px;padding-top:12px;
                color:#444;font-size:11px;text-align:center">
      ET-Spotter · dados via yfinance · não constitui recomendação de investimento
    </div>
  </div>
</body>
</html>"""
    return html


# ── main ──────────────────────────────────────────────────────────────────────

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

    email_to = os.getenv("EMAIL_TO")
    if email_to:
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

    sys.exit(1)


if __name__ == "__main__":
    main()
