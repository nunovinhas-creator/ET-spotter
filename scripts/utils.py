"""
Funções utilitárias partilhadas por todos os scripts.
Abstrai a estrutura do config para que os scripts não dependam do formato JSON.
"""

import json
from pathlib import Path


def load_config(path: str | Path = "config/etfs.json") -> dict:
    with open(path) as f:
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
            }
    return result


def get_etf_name(cfg: dict, ticker: str) -> str:
    return get_category_map(cfg).get(ticker, {}).get("name", ticker)


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

    if not late_entry and score >= 0.62 and signals >= 6:
        return {"level": "FORTE COMPRA", "color": "#4caf50", "bg": "#1b3a2a", "signals": signals}
    if not late_entry and score >= 0.54 and signals >= 4:
        return {"level": "COMPRA",       "color": "#8bc34a", "bg": "#1e2f1a", "signals": signals}
    if score >= 0.48 and signals >= 3:
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


def compute_upside_score(
    ret_63d: float, ret_5d: float, rsi: float, adx: float,
    macd_bullish: int, delta_score: float, rs_positive: int,
    trend_sma: int, above_sma200: int, vol_21: float, drawdown: float,
) -> int | None:
    """
    Pontuação 0-100 para ETFs com potencial de subir >5% no mês seguinte.
    Devolve None se qualquer condição disqualificadora estiver activa.
    """
    # Disqualificadores duros
    if not trend_sma:        return None   # sem tendência ascendente
    if not above_sma200:     return None   # abaixo da média de longo prazo
    if rsi > 72:             return None   # sobrecomprado
    if ret_5d > 0.08:        return None   # já subiu demasiado esta semana
    if vol_21 < 0.10:        return None   # volatilidade demasiado baixa (sem impulso)
    if drawdown < -0.30:     return None   # em queda livre

    pts = 0

    # Momentum 3 meses (0-30 pts) — motor principal de continuação
    if ret_63d >= 0.20:    pts += 30
    elif ret_63d >= 0.12:  pts += 22
    elif ret_63d >= 0.06:  pts += 15
    elif ret_63d >= 0.02:  pts += 8

    # RSI — ponto de entrada (0-14 pts): ideal ligeiramente abaixo de 50
    if 38 <= rsi <= 52:    pts += 14
    elif 52 < rsi <= 62:   pts += 9
    elif 30 <= rsi < 38:   pts += 5

    # Correção semanal = janela de entrada (0-11 pts)
    if ret_5d <= -0.04:    pts += 11
    elif ret_5d <= -0.015: pts += 8
    elif ret_5d <= 0.01:   pts += 4

    # Força de tendência ADX (0-12 pts)
    if adx >= 35:          pts += 12
    elif adx >= 25:        pts += 8
    elif adx >= 18:        pts += 4

    # MACD bullish (0-8 pts)
    if macd_bullish:       pts += 8

    # Aceleração do score (0-15 pts)
    if delta_score >= 0.05:    pts += 15
    elif delta_score >= 0.02:  pts += 10
    elif delta_score >= 0.00:  pts += 5

    # Força relativa vs SPY (0-10 pts)
    if rs_positive:        pts += 10

    return min(pts, 100)
