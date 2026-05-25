"""
Detecta alertas intradiários e estruturais. Envia email HTML se EMAIL_TO estiver definido.

Alertas reactivos (dados horários):
  - Queda horária >= ret_1h_drop

Alertas estruturais (dados diários) — apenas quando a condição é NOVA:
  - Break da SMA200: preço cruzou abaixo pela primeira vez (ontem acima, hoje abaixo)
  - Deterioração de score: score cruzou abaixo de 0.40 (ontem >= 0.40, hoje < 0.40)
  - Queda rápida de score: score caiu > 0.07 numa sessão (independente do limiar)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map

DATA_HOURLY   = Path("data/hourly")
DATA_DAILY    = Path("data/daily")
SCORES_LATEST = Path("data/reports/scores_latest.csv")

SCORE_DANGER    = 0.40   # limiar de deterioração
SCORE_DROP_FAST = 0.07   # queda numa sessão considerada "rápida"


# ── Dados de suporte ──────────────────────────────────────────────────────────

def load_scores() -> dict:
    """Carrega scores actuais → {etf: {"score", "score_pct"}}."""
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


# ── Alertas reactivos (horários) ──────────────────────────────────────────────

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
        return [{"type": "QUEDA HORÁRIA", "symbol": symbol, "ret_1h": ret_1h}]
    return []


# ── Alertas estruturais (diários) — apenas eventos NOVOS ─────────────────────

def detect_structural_alerts(symbol: str, scores: dict) -> list[dict]:
    """
    Todos os alertas são baseados em transições (ontem→hoje), nunca em estado permanente.
    Isto evita spam de alertas repetidos para ETFs que já estão em má situação há semanas.
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

    close_now   = float(last.get("close",  0) or 0)
    sma200_now  = float(last.get("sma200", 0) or 0)
    close_prev  = float(prev.get("close",  0) or 0)
    sma200_prev = float(prev.get("sma200", 0) or 0)

    score_now  = float(last.get("score", scores.get(symbol, {}).get("score", 0) or 0) or 0)
    score_prev = float(prev.get("score", score_now) or score_now)

    # 1. Break da SMA200 (transição: acima→abaixo)
    if (sma200_now > 0 and sma200_prev > 0
            and close_prev >= sma200_prev
            and close_now  <  sma200_now):
        pct_below = (close_now - sma200_now) / sma200_now
        alerts.append({
            "type":      "BREAK SMA200",
            "symbol":    symbol,
            "close":     close_now,
            "sma200":    sma200_now,
            "pct_below": pct_below,
            "score":     score_now,
        })

    # 2. Deterioração de score (transição: score cruzou abaixo de 0.40)
    if score_prev >= SCORE_DANGER > score_now:
        alerts.append({
            "type":       "DETERIORAÇÃO",
            "symbol":     symbol,
            "score":      score_now,
            "score_prev": score_prev,
            "score_pct":  scores.get(symbol, {}).get("score_pct", float("nan")),
        })

    # 3. Queda rápida de score (>7 pontos numa sessão, mesmo que ainda acima de 0.40)
    elif score_prev - score_now >= SCORE_DROP_FAST and score_now < 0.60:
        alerts.append({
            "type":       "QUEDA DE SCORE",
            "symbol":     symbol,
            "score":      score_now,
            "score_prev": score_prev,
            "delta":      score_prev - score_now,
        })

    return alerts


# ── Email HTML ────────────────────────────────────────────────────────────────

def _c(v: float, neutral: float = 0) -> str:
    return "#4caf50" if v > neutral else ("#f44336" if v < neutral else "#aaa")


def build_alert_html(all_alerts: list[dict], cmap: dict) -> str:
    ts = datetime.now().strftime("%d/%m/%Y  %H:%M")
    n  = len(all_alerts)

    type_order  = {"BREAK SMA200": 0, "DETERIORAÇÃO": 1, "QUEDA DE SCORE": 2, "QUEDA HORÁRIA": 3}
    type_color  = {
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
        clr, bg = type_color.get(t, ("#aaa", "#1a1d2e"))

        badge = (
            f'<span style="background:{clr};color:#000;padding:2px 9px;'
            f'border-radius:10px;font-size:11px;font-weight:bold">{t}</span>'
        )

        if t == "QUEDA HORÁRIA":
            detail = (
                f'<b style="color:{clr}">{a["ret_1h"]:.2%}</b> na última hora'
            )
        elif t == "BREAK SMA200":
            detail = (
                f'Preço <b style="color:{clr}">{a["close"]:.2f}</b> cruzou abaixo '
                f'da SMA200 <b>{a["sma200"]:.2f}</b> '
                f'(<span style="color:{clr}">{a["pct_below"]:.2%}</span>)'
                f'&nbsp;·&nbsp;score={a["score"]:.3f}'
            )
        elif t == "DETERIORAÇÃO":
            pct = a.get("score_pct")
            pct_str = f'&nbsp;·&nbsp;P{pct*100:.0f} histórico' if pd.notna(pct) else ""
            detail = (
                f'Score cruzou abaixo de {SCORE_DANGER}: '
                f'<b style="color:{clr}">{a["score"]:.3f}</b> '
                f'(era {a["score_prev"]:.3f} na sessão anterior){pct_str}'
            )
        else:  # QUEDA DE SCORE
            detail = (
                f'Score caiu <b style="color:{clr}">−{a["delta"]:.3f}</b> '
                f'numa sessão: {a["score_prev"]:.3f} → {a["score"]:.3f}'
            )

        cards += f"""
        <div style="background:{bg};border-left:4px solid {clr};
                    padding:12px 16px;margin:6px 0;border-radius:4px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <span style="color:#e8eaf6;font-size:17px;font-weight:bold">{sym}</span>
            <span style="color:#888;font-size:11px">{name}</span>
            {badge}
            <span style="color:{cor};font-size:11px">● {cat}</span>
          </div>
          <div style="color:#ccc;font-size:12px;margin-top:6px">{detail}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:sans-serif;
             margin:0;padding:20px">
  <div style="max-width:640px;margin:0 auto">

    <div style="border-bottom:1px solid #1e2130;padding-bottom:12px;margin-bottom:20px">
      <div style="font-size:22px;font-weight:bold;color:#f44336">
        ⚠ ET-Spotter — {n} alerta{'s' if n != 1 else ''} activo{'s' if n != 1 else ''}
      </div>
      <div style="color:#555;font-size:12px;margin-top:4px">{ts}</div>
    </div>

    <div style="font-size:11px;color:#555;margin-bottom:14px">
      Apenas alertas de <b>eventos novos</b> — a condição não existia na sessão anterior.
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
        html = build_alert_html(all_alerts, cmap)
        to_list = [t.strip() for t in email_to.split(",")]
        n = len(all_alerts)
        send_email(
            f"ET-Spotter: {n} alerta{'s' if n != 1 else ''} — {', '.join(a['symbol'] for a in all_alerts[:3])}{'...' if n > 3 else ''}",
            html,
            to_list,
        )

    sys.exit(1)


if __name__ == "__main__":
    main()
