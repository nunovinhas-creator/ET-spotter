"""
Funções utilitárias partilhadas por todos os scripts.
Abstrai a estrutura do config para que os scripts não dependam do formato JSON.
"""

import json
import math
from pathlib import Path

from constants import (
    CONVICTION_STRONG_BUY_SCORE, CONVICTION_STRONG_BUY_SIGNALS,
    CONVICTION_BUY_SCORE,        CONVICTION_BUY_SIGNALS,
    CONVICTION_POTENTIAL_SCORE,  CONVICTION_POTENTIAL_SIGNALS,
)

_CONFIG_DEFAULT = Path(__file__).parent.parent / "config" / "etfs.json"


def load_config(path: str | Path | None = None) -> dict:
    with open(path or _CONFIG_DEFAULT) as f:
        return json.load(f)


def get_etfs(cfg: dict) -> list[str]:
    return [e["ticker"] for cat in cfg["categories"] for e in cat["etfs"]]


def get_all_symbols(cfg: dict) -> list[str]:
    return cfg["benchmarks"] + get_etfs(cfg)


def get_categories(cfg: dict) -> list[dict]:
    return cfg["categories"]


def get_category_map(cfg: dict) -> dict[str, dict]:
    result = {}
    for cat in cfg["categories"]:
        for e in cat["etfs"]:
            result[e["ticker"]] = {
                "name":          e["name"],
                "category_id":   cat["id"],
                "category_name": cat["name"],
                "color":         cat["color"],
                # metadata opcional — None quando não preenchido
                "ter":           e.get("ter"),
                "aum_bn":        e.get("aum_bn"),
                "replica":       e.get("replica"),
                "esg":           e.get("esg"),
                "isin":          e.get("isin"),
            }
    return result


def get_etf_metadata(cfg: dict) -> dict[str, dict]:
    """Devolve dicionário ticker → {ter, aum_bn, replica, esg, isin}."""
    result = {}
    for cat in cfg["categories"]:
        for e in cat["etfs"]:
            result[e["ticker"]] = {
                "ter":     e.get("ter"),
                "aum_bn":  e.get("aum_bn"),
                "replica": e.get("replica"),
                "esg":     e.get("esg"),
                "isin":    e.get("isin"),
            }
    return result


def get_users(cfg: dict) -> list[dict]:
    """
    Devolve lista de utilizadores do config.
    Fallback para single-user via variáveis de ambiente quando 'users' está ausente.
    """
    import os
    users = cfg.get("users", [])
    if users:
        return users
    # compatibilidade retroactiva: single-user a partir de env vars
    email   = os.getenv("EMAIL_TO", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if email or tg_chat:
        return [{
            "name":             "default",
            "email":            email,
            "telegram_chat_id": tg_chat,
            "thresholds":       {},
            "watchlist":        None,
        }]
    return []


def category_summary(scores_df, cfg: dict) -> list[dict]:
    """
    Agrega scores por categoria.
    scores_df deve ter colunas: etf, score, ret_24h (opcional), delta_score (opcional).
    """
    cmap = get_category_map(cfg)
    cat_data: dict[str, dict] = {}

    for _, row in scores_df.iterrows():
        info = cmap.get(row["etf"])
        if info is None:
            continue
        cid = info["category_id"]
        if cid not in cat_data:
            cat_data[cid] = {
                "id": cid, "name": info["category_name"],
                "color": info["color"],
                "scores": [], "rets": [], "deltas": [],
            }
        cat_data[cid]["scores"].append(row["score"])
        if "ret_24h" in row.index:
            cat_data[cid]["rets"].append(row["ret_24h"])
        if "delta_score" in row.index:
            cat_data[cid]["deltas"].append(row["delta_score"])

    result = []
    for d in cat_data.values():
        sc = d["scores"]
        rt = d["rets"]
        dl = d["deltas"]
        avg_delta = sum(dl) / len(dl) if dl else 0
        result.append({
            "id":          d["id"],
            "name":        d["name"],
            "color":       d["color"],
            "n":           len(sc),
            "score_avg":   round(sum(sc) / len(sc), 3) if sc else 0,
            "score_max":   round(max(sc), 3) if sc else 0,
            "score_min":   round(min(sc), 3) if sc else 0,
            "ret_avg":     round(sum(rt) / len(rt), 4) if rt else 0,
            "delta_avg":   round(avg_delta, 4),
            "momentum":    "▲" if avg_delta > 0.01 else ("▼" if avg_delta < -0.01 else "→"),
        })

    return sorted(result, key=lambda x: x["score_avg"], reverse=True)


# ─── Análise de convicção ─────────────────────────────────────────────────────

def compute_conviction(score: float, trend_sma: int, macd_bullish: int,
                       rsi: float, rs_positive: int, ret_63d: float,
                       delta_score: float, drawdown: float,
                       ret_5d: float = 0.0, vol_21: float = 0.0) -> dict:
    """
    Conta confluência de 7 sinais técnicos e devolve nível de convicção.

    Sinais (máx 7):
      1. trend_sma == 1
      2. macd_bullish == 1
      3. 40 <= rsi <= 65 (zona de entrada ideal)
      4. rs_positive == 1 (a bater SPY)
      5. ret_5d < 4%  — entrada não comprometida (ainda não subiu muito)
      6. delta_score > 0.01
      7. drawdown > -0.08

    Caps de entrada tardia (evita "comprar o topo"):
      - RSI > 68 → máximo POTENCIAL
      - ret_5d > 7% → máximo POTENCIAL (já subiu demasiado na semana)
    """
    rsi_val  = rsi or 0
    ret5     = ret_5d or 0

    signals = 0
    if trend_sma == 1:                      signals += 1
    if macd_bullish == 1:                   signals += 1
    if 40 <= rsi_val <= 65:                 signals += 1
    if rs_positive == 1:                    signals += 1
    if ret5 < 0.04:                         signals += 1  # janela de entrada aberta
    if delta_score > 0.01:                  signals += 1
    if drawdown > -0.08:                    signals += 1

    # Caps: RSI sobrecomprado ou movimento semanal excessivo → entrada tardia
    # Threshold adaptado à volatilidade: 2σ do movimento esperado em 5 dias
    # Floor 4%, cap 10% para evitar thresholds absurdos em ETFs extremos
    if vol_21 > 0:
        expected_5d = vol_21 * (5 / 252) ** 0.5
        vol_threshold = max(0.04, min(0.10, 2.0 * expected_5d))
    else:
        vol_threshold = 0.07
    late_entry = rsi_val > 68 or ret5 > vol_threshold

    if not late_entry and score >= CONVICTION_STRONG_BUY_SCORE and signals >= CONVICTION_STRONG_BUY_SIGNALS:
        return {"level": "FORTE COMPRA", "color": "#4caf50", "bg": "#1b3a2a", "signals": signals}
    if not late_entry and score >= CONVICTION_BUY_SCORE and signals >= CONVICTION_BUY_SIGNALS:
        return {"level": "COMPRA",       "color": "#8bc34a", "bg": "#1e2f1a", "signals": signals}
    if score >= CONVICTION_POTENTIAL_SCORE and signals >= CONVICTION_POTENTIAL_SIGNALS:
        return {"level": "POTENCIAL",    "color": "#ffd54f", "bg": "#2a2510", "signals": signals}
    return {"level": None, "color": None, "bg": None, "signals": signals}


def analyst_rationale(trend_sma: int, macd_bullish: int, ret_5d: float,
                      ret_63d: float, delta_score: float, drawdown: float,
                      rsi: float, rs_positive: int, adx: float) -> str:
    parts = []
    rsi_val = rsi or 0
    ret5    = ret_5d or 0

    if trend_sma and macd_bullish:
        parts.append("tendência e momentum alinhados (SMA20>SMA50, MACD+)")
    elif trend_sma:
        parts.append("tendência ascendente confirmada (SMA20>SMA50)")
    elif macd_bullish:
        parts.append("MACD cruzou para zona positiva")

    # Qualidade da janela de entrada (crítico para evitar comprar o topo)
    if ret5 < 0.01 and delta_score > 0.01:
        parts.append("janela de entrada favorável — movimento ainda no início")
    elif ret5 < 0.03:
        parts.append(f"entrada não comprometida (ret. semanal {ret5:.1%})")
    elif ret5 > 0.07:
        parts.append(f"atenção: já subiu {ret5:.1%} esta semana — aguardar pullback")
    elif ret5 > 0.04:
        parts.append(f"movimento semanal avançado ({ret5:.1%}) — entrada com cautela")

    if rsi_val > 68:
        parts.append(f"RSI em sobrecompra ({rsi_val:.0f}) — aguardar correcção")
    elif 40 <= rsi_val <= 58:
        parts.append(f"RSI em zona óptima de entrada ({rsi_val:.0f})")
    elif rsi_val < 40:
        parts.append(f"RSI fraco ({rsi_val:.0f}) — confirmar reversão antes de entrar")

    if rs_positive:
        parts.append("força relativa positiva vs SPY (últimos 63 dias)")

    if (ret_63d or 0) > 0.08:
        parts.append(f"momentum 3M sólido ({ret_63d:.1%})")
    elif (ret_63d or 0) > 0.03:
        parts.append(f"retorno 3M positivo ({ret_63d:.1%})")

    if (adx or 0) > 25:
        parts.append(f"tendência forte (ADX {adx:.0f})")

    if delta_score > 0.06:
        parts.append("score em forte aceleração")
    elif delta_score > 0.02:
        parts.append("score com trajectória ascendente")

    if drawdown > -0.03:
        parts.append("próximo de máximos — força estrutural")
    elif drawdown > -0.08:
        parts.append(f"drawdown contido ({drawdown:.1%})")

    return ". ".join(parts[:3]).capitalize() + "." if parts else "Confluência de sinais técnicos favoráveis."


def _safe_finite(v, default: float = 0.0) -> float:
    """Float seguro: NaN/inf/None → default. Preserva 0.0."""
    try:
        x = float(v)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return default


def _is_finite(v) -> bool:
    """True se v é um float finito válido (não NaN, não inf)."""
    try:
        x = float(v)
        return not (math.isnan(x) or math.isinf(x))
    except (TypeError, ValueError):
        return False


def _c(val: float, neutral: float = 0) -> str:
    """Cor HTML para valor positivo/negativo (emails HTML)."""
    return "#4caf50" if val >= neutral else "#f44336"


def _pct(v, digits: int = 1) -> str:
    """Formata float como percentagem com sinal; retorna '—' se inválido."""
    try:
        x = float(v)
        return f"{x:+.{digits}%}" if x == x else "—"
    except (TypeError, ValueError):
        return "—"


def _etf_row_raw(sym: str, last, info: dict, delta_score: float = 0.0) -> dict:
    """Extrai campos padrão de ETF de uma última linha de DataFrame."""
    score_pct_raw = last.get("score_pct", None)
    return {
        "ticker":       sym,
        "nome":         info.get("name", sym),
        "categoria":    info.get("category_name", "—"),
        "cor":          info.get("color", "#7c83fd"),
        "score":        round(float(last.get("score",        0) or 0), 3),
        "delta_score":  delta_score,
        "trend_sma":    int(last.get("trend_sma",      0) or 0),
        "macd_bullish": int(last.get("macd_bullish",   0) or 0),
        "ret_5d":       float(last.get("ret_5d",       0) or 0),
        "ret_21d":      float(last.get("ret_21d",      0) or 0),
        "ret_63d":      float(last.get("ret_63d",      0) or 0),
        "ret_126d":     float(last.get("ret_126d",     0) or 0),
        "ret_252d":     float(last.get("ret_252d",     0) or 0),
        "ret_24h":      float(last.get("ret_1d",       0) or 0),
        "drawdown":     float(last.get("drawdown",     0) or 0),
        "vol_21":       float(last.get("vol_21",       0) or 0),
        "rsi":          float(last.get("rsi",          50) or 50),
        "adx":          float(last.get("adx",          0) or 0),
        "rs_positive":  int(last.get("rs_positive",    0) or 0),
        "rs_mom_21":    float(last.get("rs_mom_21",    0) or 0),
        "rs_mom_63":    float(last.get("rs_mom_63",    0) or 0),
        "above_sma200": int(last.get("above_sma200",   0) or 0),
        "score_pct":    float(score_pct_raw) if score_pct_raw not in (None, "") else None,
        "sharpe_63":    float(last.get("sharpe_63",    0) or 0),
        "calmar_63":    float(last.get("calmar_63",    0) or 0),
        "close":        round(float(last.get("close",  0) or 0), 2),
    }


def build_buy_signals(rows: list[dict], top_n: int = 8) -> list[dict]:
    """
    Filtra e ordena os ETFs com sinais de compra.
    Cada row deve ter: ticker, nome, categoria, cor, score, trend_sma,
                       macd_bullish, rsi, rs_positive, ret_63d, ret_5d,
                       delta_score, drawdown, adx.
    """
    signals = []
    for r in rows:
        conv = compute_conviction(
            r["score"], r["trend_sma"], r["macd_bullish"],
            r.get("rsi", 50), r.get("rs_positive", 0), r.get("ret_63d", 0),
            r.get("delta_score", 0), r.get("drawdown", -0.5),
            r.get("ret_5d", 0), r.get("vol_21", 0),
        )
        if conv["level"] is None:
            continue
        rationale = analyst_rationale(
            r["trend_sma"], r["macd_bullish"], r.get("ret_5d", 0),
            r.get("ret_63d", 0), r.get("delta_score", 0), r.get("drawdown", -0.5),
            r.get("rsi", 50), r.get("rs_positive", 0), r.get("adx", 0),
        )
        signals.append({**r, **conv, "rationale": rationale})

    # Ordena: nível de convicção → dentro do mesmo nível prioriza ret_5d baixo
    # (entrada mais cedo = movimento ainda não comprometido)
    order = {"FORTE COMPRA": 0, "COMPRA": 1, "POTENCIAL": 2}
    signals.sort(key=lambda x: (order.get(x["level"], 9), x.get("ret_5d", 0), -x["score"]))
    return signals[:top_n]


def compute_advisor_score(
    ret_252d: float, ret_126d: float, ret_21d: float, ret_5d: float,
    rsi: float, adx: float, macd_bullish: int,
    rs_positive: int, rs_mom_63: float,
    trend_sma: int, above_sma200: int,
    sharpe_63: float, calmar_63: float,
    vol_21: float, drawdown: float,
) -> int | None:
    """
    Score técnico composto 0-100 baseado em evidência académica e prática profissional:

    Fontes:
      - Momentum cross-seccional (Jegadeesh & Titman 1993; AQR): ret 12-1M
      - Trend following / regime filter (Meb Faber 2007): preço > SMA200
      - Dual momentum absoluto + relativo (Gary Antonacci 2012)
      - Risk-adjusted return: Sharpe + Calmar como proxy de qualidade
      - Entry timing: RSI + pullback em uptrend (não prever, posicionar bem)

    Devolve None se o ETF não cumpre os critérios de regime mínimos.
    """
    # Check data availability BEFORE NaN-cleaning (to distinguish NaN from genuine 0.0)
    _has_252d = _is_finite(ret_252d)
    _has_126d = _is_finite(ret_126d)

    ret_252d  = _safe_finite(ret_252d)
    ret_126d  = _safe_finite(ret_126d)
    ret_21d   = _safe_finite(ret_21d)
    ret_5d    = _safe_finite(ret_5d)
    rsi       = _safe_finite(rsi, 50.0)
    adx       = _safe_finite(adx)
    rs_mom_63 = _safe_finite(rs_mom_63)
    sharpe_63 = _safe_finite(sharpe_63)
    calmar_63 = _safe_finite(calmar_63)
    vol_21    = _safe_finite(vol_21)
    drawdown  = _safe_finite(drawdown, -0.25)   # safe-side: unknown drawdown → disqualify

    # ── Filtros de regime (Faber: só estar comprado quando acima de SMA200) ─────
    if not above_sma200:   return None
    if rsi > 75:           return None   # extremamente sobrecomprado
    if ret_5d > 0.12:      return None   # spike extremo — não perseguir
    if drawdown < -0.20:   return None   # queda estrutural activa

    # ── Momentum composto: 12-1M ou 6-1M (Antonacci) ─────────────────────────
    # A exclusão do último mês evita o efeito de reversão de curto prazo
    if not _has_252d and not _has_126d:
        return None  # sem histórico de retornos suficiente

    if _has_252d:
        momentum = ret_252d - ret_21d   # 12-1M (preferido)
    else:
        momentum = ret_126d - ret_21d   # 6-1M (fallback para ETFs mais recentes)

    # Momentum absoluto negativo = não estar comprado (Antonacci)
    if momentum < 0:
        return None

    pts = 0

    # 1. Momentum cross-seccional (45 pts) — factor com maior evidência
    if momentum >= 0.30:    pts += 45
    elif momentum >= 0.20:  pts += 35
    elif momentum >= 0.12:  pts += 25
    elif momentum >= 0.06:  pts += 15
    else:                   pts += 5

    # 2. Regime de tendência (10 pts) — Faber SMA200 + SMA20>SMA50
    if trend_sma and above_sma200:  pts += 10
    else:                           pts += 5  # acima de SMA200 mas sem trend_sma

    # 3. Força relativa vs benchmark (15 pts) — Antonacci dual momentum relativo
    if rs_positive and rs_mom_63 >= 0.05:  pts += 15
    elif rs_positive:                       pts += 10
    elif rs_mom_63 > 0:                    pts += 5

    # 4. Qualidade risk-adjusted (15 pts) — Sharpe + Calmar premiam consistência
    s_pts = 8 if sharpe_63 >= 2.0 else (5 if sharpe_63 >= 1.0 else (2 if sharpe_63 >= 0.5 else 0))
    c_pts = 7 if calmar_63 >= 2.0 else (4 if calmar_63 >= 1.0 else (2 if calmar_63 >= 0.5 else 0))
    pts += s_pts + c_pts

    # 5. Timing de entrada (10 pts) — RSI não sobrecomprado + pullback em uptrend
    if 35 <= rsi <= 55:              pts += 7
    elif 55 < rsi <= 65:             pts += 4
    elif rsi < 35 and trend_sma:     pts += 3   # oversold em uptrend = oportunidade
    if ret_5d <= -0.02:              pts += 3   # pullback = desconto técnico
    elif ret_5d <= 0.01:             pts += 1

    # 6. Força da tendência ADX (5 pts)
    if adx >= 30:   pts += 5
    elif adx >= 20: pts += 3

    return min(pts, 100)


def build_advisor_candidates(rows: list[dict], top_n: int = 3) -> list[dict]:
    """
    Filtra e ordena os ETFs pelo score técnico composto (compute_advisor_score).
    Cada row deve ter os campos correspondentes aos parâmetros de compute_advisor_score.
    """
    candidates = []
    for r in rows:
        pts = compute_advisor_score(
            ret_252d=r.get("ret_252d",  0),
            ret_126d=r.get("ret_126d",  0),
            ret_21d=r.get("ret_21d",    0),
            ret_5d=r.get("ret_5d",      0),
            rsi=r.get("rsi",            50),
            adx=r.get("adx",            0),
            macd_bullish=r.get("macd_bullish", 0),
            rs_positive=r.get("rs_positive",   0),
            rs_mom_63=r.get("rs_mom_63",       0),
            trend_sma=r.get("trend_sma",       0),
            above_sma200=r.get("above_sma200", 0),
            sharpe_63=r.get("sharpe_63",       0),
            calmar_63=r.get("calmar_63",       0),
            vol_21=r.get("vol_21",             0),
            drawdown=r.get("drawdown",        -0.5),
        )
        if pts is not None:
            candidates.append({**r, "advisor_pts": pts})
    candidates.sort(key=lambda x: -x["advisor_pts"])
    return candidates[:top_n]
