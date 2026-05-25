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
    """Lista plana de todos os tickers de ETF (excluindo benchmarks)."""
    return [e["ticker"] for cat in cfg["categories"] for e in cat["etfs"]]


def get_all_symbols(cfg: dict) -> list[str]:
    """Benchmarks + todos os ETFs."""
    return cfg["benchmarks"] + get_etfs(cfg)


def get_categories(cfg: dict) -> list[dict]:
    """Lista de categorias com id, name, color e lista de ETFs."""
    return cfg["categories"]


def get_category_map(cfg: dict) -> dict[str, dict]:
    """
    Devolve um dict ticker → metadados da categoria.
    Ex: {"QQQ": {"name": "Nasdaq 100", "category_id": "us_broad",
                 "category_name": "EUA – Mercado Largo", "color": "#7c83fd"}}
    """
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
    """Nome descritivo de um ticker. Devolve o próprio ticker se não encontrado."""
    cmap = get_category_map(cfg)
    return cmap.get(ticker, {}).get("name", ticker)


def category_summary(scores_df, cfg: dict) -> list[dict]:
    """
    Agrega scores por categoria.
    scores_df deve ter colunas: etf, score (e opcionalmente ret_24h).
    Devolve lista de dicts ordenada por score médio decrescente.
    """
    cmap = get_category_map(cfg)
    cat_data: dict[str, list] = {}

    for _, row in scores_df.iterrows():
        ticker = row["etf"]
        info = cmap.get(ticker)
        if info is None:
            continue
        cid = info["category_id"]
        if cid not in cat_data:
            cat_data[cid] = {
                "id":    cid,
                "name":  info["category_name"],
                "color": info["color"],
                "scores": [],
                "rets":   [],
            }
        cat_data[cid]["scores"].append(row["score"])
        if "ret_24h" in row:
            cat_data[cid]["rets"].append(row["ret_24h"])

    result = []
    for cid, d in cat_data.items():
        scores = d["scores"]
        rets   = d["rets"]
        result.append({
            "id":          cid,
            "name":        d["name"],
            "color":       d["color"],
            "n":           len(scores),
            "score_avg":   round(sum(scores) / len(scores), 3) if scores else 0,
            "score_max":   round(max(scores), 3) if scores else 0,
            "score_min":   round(min(scores), 3) if scores else 0,
            "ret_avg":     round(sum(rets) / len(rets), 4) if rets else 0,
        })

    return sorted(result, key=lambda x: x["score_avg"], reverse=True)
