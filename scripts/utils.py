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
                       ret_5d: float, delta_score: float, drawdown: float) -> dict:
    """
    Conta confluência de sinais técnicos e devolve nível de convicção.
    """
    signals = 0
    if trend_sma == 1:        signals += 1
    if macd_bullish == 1:     signals += 1
    if ret_5d > 0:            signals += 1
    if delta_score > 0.01:    signals += 1
    if drawdown > -0.08:      signals += 1

    if score >= 0.60 and signals >= 4:
        return {"level": "FORTE COMPRA", "color": "#4caf50", "bg": "#1b3a2a", "signals": signals}
    if score >= 0.52 and signals >= 3:
        return {"level": "COMPRA",       "color": "#8bc34a", "bg": "#1e2f1a", "signals": signals}
    if score >= 0.46 and signals >= 2 and delta_score >= 0:
        return {"level": "POTENCIAL",    "color": "#ffd54f", "bg": "#2a2510", "signals": signals}
    return {"level": None, "color": None, "bg": None, "signals": signals}


def analyst_rationale(trend_sma: int, macd_bullish: int, ret_5d: float,
                      ret_24h: float, delta_score: float,
                      drawdown: float, vol_30: float) -> str:
    parts = []

    if trend_sma and macd_bullish:
        parts.append("tendência e momentum alinhados (SMA20>SMA50, MACD+)")
    elif trend_sma:
        parts.append("tendência ascendente confirmada (SMA20>SMA50)")
    elif macd_bullish:
        parts.append("MACD cruzou para zona positiva")

    if ret_5d > 0.04:
        parts.append(f"forte dinâmica de {ret_5d:.1%} nos últimos 5 dias")
    elif ret_5d > 0.015:
        parts.append(f"retorno de {ret_5d:.1%} em 5 dias com consistência")
    elif ret_5d > 0:
        parts.append(f"dinâmica semanal positiva ({ret_5d:.1%})")

    if delta_score > 0.06:
        parts.append("score em forte aceleração")
    elif delta_score > 0.02:
        parts.append("score com trajectória ascendente")

    if drawdown > -0.03:
        parts.append("próximo de máximos históricos — força estrutural")
    elif drawdown > -0.08:
        parts.append(f"drawdown contido ({drawdown:.1%})")

    if vol_30 and 0 < vol_30 < 0.14:
        parts.append("volatilidade baixa favorece gestão de risco")

    return ". ".join(parts[:3]).capitalize() + "." if parts else "Confluência de sinais técnicos favoráveis."


def build_buy_signals(rows: list[dict], top_n: int = 8) -> list[dict]:
    """
    Filtra e ordena os ETFs com sinais de compra.
    Cada row deve ter: ticker, nome, categoria, cor, score, trend_sma,
                       macd_bullish, ret_5d, ret_24h, delta_score, drawdown, vol_30.
    """
    signals = []
    for r in rows:
        conv = compute_conviction(
            r["score"], r["trend_sma"], r["macd_bullish"],
            r["ret_5d"], r["delta_score"], r["drawdown"],
        )
        if conv["level"] is None:
            continue
        rationale = analyst_rationale(
            r["trend_sma"], r["macd_bullish"], r["ret_5d"], r["ret_24h"],
            r["delta_score"], r["drawdown"], r["vol_30"],
        )
        signals.append({**r, **conv, "rationale": rationale})

    # Ordena: FORTE COMPRA primeiro, depois score
    order = {"FORTE COMPRA": 0, "COMPRA": 1, "POTENCIAL": 2}
    signals.sort(key=lambda x: (order.get(x["level"], 9), -x["score"]))
    return signals[:top_n]
