"""
Gera gráficos e infografias para os relatórios diário e semanal.
Guarda imagens em data/reports/.
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, get_categories, category_summary

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")

PALETTE = {
    "bg":       "#0f1117",
    "fg":       "#e8eaf6",
    "accent":   "#7c83fd",
    "positive": "#4caf50",
    "negative": "#f44336",
    "sma20":    "#ffd54f",
    "sma50":    "#ff7043",
    "grid":     "#1e2130",
}


def _dark(ax, title: str = ""):
    ax.set_facecolor(PALETTE["bg"])
    ax.figure.patch.set_facecolor(PALETTE["bg"])
    ax.tick_params(colors=PALETTE["fg"])
    for spine in ax.spines.values():
        spine.set_edgecolor("#333344")
    if title:
        ax.set_title(title, color=PALETTE["fg"], fontsize=13, pad=10)
    if ax.get_xlabel():
        ax.xaxis.label.set_color(PALETTE["fg"])
    if ax.get_ylabel():
        ax.yaxis.label.set_color(PALETTE["fg"])


# ─── 1. Barras de score coloridas por categoria ──────────────────────────────

def plot_scores_bar(summary: pd.DataFrame, cfg: dict) -> Path:
    """Barras horizontais ordenadas por score, coloridas por categoria."""
    cmap = get_category_map(cfg)
    summary = summary.sort_values("score")

    colors = [cmap.get(t, {}).get("color", PALETTE["accent"]) for t in summary["etf"]]
    n = len(summary)
    fig, ax = plt.subplots(figsize=(10, max(6, n * 0.28)))

    bars = ax.barh(summary["etf"], summary["score"], color=colors, edgecolor="#ffffff11", height=0.75)
    ax.axvline(0.5, color="#ffffff33", linewidth=0.8, linestyle="--")
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("Score [0–1]", color=PALETTE["fg"])

    for bar, val in zip(bars, summary["score"]):
        ax.text(
            val + 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}", va="center", color=PALETTE["fg"], fontsize=7,
        )

    # Legenda de categorias
    seen = {}
    for t, c in zip(summary["etf"], colors):
        cat = cmap.get(t, {}).get("category_name", "")
        if cat and cat not in seen:
            seen[cat] = c
    handles = [mpatches.Patch(color=c, label=l) for l, c in seen.items()]
    ax.legend(handles=handles, loc="lower right",
              facecolor="#1a1d2e", labelcolor=PALETTE["fg"],
              framealpha=0.85, fontsize=7, ncol=2)

    _dark(ax, "Score Multi-Factor – todos os ETFs (por categoria)")
    ax.tick_params(axis="y", labelsize=7)
    plt.tight_layout()
    out = REPORTS / "scores_bar.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    return out


# ─── 2. Resumo por categoria ──────────────────────────────────────────────────

def plot_category_summary(summary: pd.DataFrame, cfg: dict) -> Path:
    """Barras agrupadas: score médio por categoria + spread min-max."""
    cats = category_summary(summary, cfg)
    if not cats:
        return None

    names  = [c["name"] for c in cats]
    avgs   = [c["score_avg"] for c in cats]
    mins   = [c["score_min"] for c in cats]
    maxs   = [c["score_max"] for c in cats]
    colors = [c["color"] for c in cats]
    ns     = [c["n"] for c in cats]

    fig, ax = plt.subplots(figsize=(12, 5))
    y = np.arange(len(names))

    # Barras de score médio
    bars = ax.barh(y, avgs, color=colors, edgecolor="#ffffff11", height=0.55, zorder=3)

    # Linha de spread min–max
    for i, (mn, mx) in enumerate(zip(mins, maxs)):
        ax.plot([mn, mx], [y[i], y[i]], color="#ffffff55", linewidth=2, zorder=4)
        ax.plot(mn, y[i], "o", color="#f44336", markersize=5, zorder=5)
        ax.plot(mx, y[i], "o", color="#4caf50", markersize=5, zorder=5)

    # Score médio como label
    for bar, avg, n in zip(bars, avgs, ns):
        ax.text(avg + 0.01, bar.get_y() + bar.get_height() / 2,
                f"{avg:.3f}  (n={n})", va="center",
                color=PALETTE["fg"], fontsize=8)

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.axvline(0.5, color="#ffffff33", linewidth=0.8, linestyle="--")
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("Score médio [0–1]", color=PALETTE["fg"])
    ax.grid(axis="x", color="#1e2130", linewidth=0.5, zorder=0)

    _dark(ax, "Score por Categoria  ●=min  ●=max")
    plt.tight_layout()
    out = REPORTS / "category_summary.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    return out


# ─── 3. Tendência de preço com SMAs ──────────────────────────────────────────

def plot_trend(df: pd.DataFrame, symbol: str, name: str = "") -> Path:
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df.index, df["close"], color=PALETTE["accent"], linewidth=1.5, label="Preço")
    if "sma20" in df.columns:
        ax.plot(df.index, df["sma20"], color=PALETTE["sma20"], linewidth=1, label="SMA20")
    if "sma50" in df.columns:
        ax.plot(df.index, df["sma50"], color=PALETTE["sma50"], linewidth=1, label="SMA50")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(facecolor="#1a1d2e", labelcolor=PALETTE["fg"], framealpha=0.8, fontsize=8)
    title = f"Tendência – {symbol}" + (f"  |  {name}" if name else "")
    _dark(ax, title)
    plt.tight_layout()
    out = REPORTS / f"trend_{symbol}.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    return out


# ─── 4. Evolução do score ─────────────────────────────────────────────────────

def plot_score_evolution(df: pd.DataFrame, symbol: str) -> Path | None:
    if "score" not in df.columns or df["score"].isna().all():
        return None
    fig, ax = plt.subplots(figsize=(12, 3))
    ax.plot(df.index, df["score"], color=PALETTE["accent"], linewidth=1.5)
    ax.fill_between(df.index, df["score"], 0.5, alpha=0.2,
                    where=df["score"] >= 0.5, color=PALETTE["positive"])
    ax.fill_between(df.index, df["score"], 0.5, alpha=0.2,
                    where=df["score"] < 0.5, color=PALETTE["negative"])
    ax.axhline(0.5, color="#ffffff33", linewidth=0.8, linestyle="--")
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _dark(ax, f"Score – {symbol}")
    plt.tight_layout()
    out = REPORTS / f"score_evolution_{symbol}.png"
    plt.savefig(out, dpi=120, bbox_inches="tight")
    plt.close()
    return out


# ─── 5. Heatmap de correlações (top N por score) ──────────────────────────────

def plot_correlation_heatmap(cfg: dict, max_symbols: int = 25) -> Path | None:
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        ordered = pd.read_csv(scores_path).sort_values("score", ascending=False)["etf"].tolist()
    else:
        ordered = get_etfs(cfg)

    closes = {}
    for sym in ordered[:max_symbols]:
        path = DATA_DAILY / f"{sym}.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if "close" in df.columns and not df["close"].isna().all():
                closes[sym] = df["close"].astype(float)

    if len(closes) < 2:
        return None

    corr = pd.DataFrame(closes).dropna(how="all").pct_change().dropna().corr()
    n = len(closes)
    fig, ax = plt.subplots(figsize=(n * 0.6 + 1, n * 0.5 + 1))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", center=0,
                ax=ax, linewidths=0.3,
                annot_kws={"size": 7, "color": "white"},
                cbar_kws={"shrink": 0.6})
    ax.set_title(f"Correlação (top {n} por score)", color=PALETTE["fg"], pad=10)
    fig.patch.set_facecolor(PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])
    ax.tick_params(colors=PALETTE["fg"], labelsize=8)
    plt.tight_layout()
    out = REPORTS / "correlation_heatmap.png"
    plt.savefig(out, dpi=110, bbox_inches="tight")
    plt.close()
    return out


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)
    cmap = get_category_map(cfg)
    generated = []

    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        p = plot_scores_bar(summary, cfg)
        generated.append(p)
        p = plot_category_summary(summary, cfg)
        if p:
            generated.append(p)

    for symbol in get_etfs(cfg):
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or "close" not in df.columns:
            continue
        name = cmap.get(symbol, {}).get("name", "")
        generated.append(plot_trend(df, symbol, name))
        p = plot_score_evolution(df, symbol)
        if p:
            generated.append(p)

    p = plot_correlation_heatmap(cfg)
    if p:
        generated.append(p)

    generated = [g for g in generated if g]
    print(f"[OK] {len(generated)} gráfico(s) gerado(s)")


if __name__ == "__main__":
    main()
