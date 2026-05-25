"""
Gera gráficos e infografias para o relatório semanal.
Guarda imagens em data/reports/.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import seaborn as sns

CONFIG_PATH = Path("config/etfs.json")
DATA_DAILY = Path("data/daily")
REPORTS = Path("data/reports")

PALETTE = {
    "bg": "#0f1117",
    "fg": "#e8eaf6",
    "accent": "#7c83fd",
    "positive": "#4caf50",
    "negative": "#f44336",
    "sma20": "#ffd54f",
    "sma50": "#ff7043",
}


def _apply_dark_style(ax, title: str = ""):
    ax.set_facecolor(PALETTE["bg"])
    ax.figure.patch.set_facecolor(PALETTE["bg"])
    ax.title.set_color(PALETTE["fg"])
    ax.xaxis.label.set_color(PALETTE["fg"])
    ax.yaxis.label.set_color(PALETTE["fg"])
    ax.tick_params(colors=PALETTE["fg"])
    for spine in ax.spines.values():
        spine.set_edgecolor("#333344")
    if title:
        ax.set_title(title, color=PALETTE["fg"], fontsize=13, pad=10)


def plot_trend(df: pd.DataFrame, symbol: str) -> Path:
    """Gráfico de preço com SMA20 e SMA50."""
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(df.index, df["close"], color=PALETTE["accent"], linewidth=1.5, label="Preço")
    if "sma20" in df.columns:
        ax.plot(df.index, df["sma20"], color=PALETTE["sma20"], linewidth=1, label="SMA20")
    if "sma50" in df.columns:
        ax.plot(df.index, df["sma50"], color=PALETTE["sma50"], linewidth=1, label="SMA50")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(facecolor="#1a1d2e", labelcolor=PALETTE["fg"], framealpha=0.8)
    _apply_dark_style(ax, f"Tendência – {symbol}")
    plt.tight_layout()
    out = REPORTS / f"trend_{symbol}.png"
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    return out


def plot_scores_bar(summary: pd.DataFrame) -> Path:
    """Gráfico de barras horizontal com os scores finais de todos os ETFs."""
    summary = summary.sort_values("score")
    colors = [
        PALETTE["positive"] if s >= 0.5 else PALETTE["negative"]
        for s in summary["score"]
    ]

    fig, ax = plt.subplots(figsize=(8, max(4, len(summary) * 0.7)))
    bars = ax.barh(summary["etf"], summary["score"], color=colors, edgecolor="#ffffff22")
    ax.axvline(0.5, color="#ffffff44", linewidth=0.8, linestyle="--")
    ax.set_xlim(0, 1)
    ax.set_xlabel("Score [0–1]", color=PALETTE["fg"])

    for bar, val in zip(bars, summary["score"]):
        ax.text(
            val + 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}",
            va="center", color=PALETTE["fg"], fontsize=9,
        )

    _apply_dark_style(ax, "Score Multi-Factor – ETFs")
    plt.tight_layout()
    out = REPORTS / "scores_bar.png"
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    return out


def plot_score_evolution(df: pd.DataFrame, symbol: str) -> Path:
    """Evolução temporal do score de um ETF."""
    if "score" not in df.columns or df["score"].isna().all():
        return None

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df.index, df["score"], color=PALETTE["accent"], linewidth=1.5)
    ax.fill_between(df.index, df["score"], 0.5, alpha=0.2,
                    where=df["score"] >= 0.5, color=PALETTE["positive"])
    ax.fill_between(df.index, df["score"], 0.5, alpha=0.2,
                    where=df["score"] < 0.5, color=PALETTE["negative"])
    ax.axhline(0.5, color="#ffffff44", linewidth=0.8, linestyle="--")
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _apply_dark_style(ax, f"Evolução do Score – {symbol}")
    plt.tight_layout()
    out = REPORTS / f"score_evolution_{symbol}.png"
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    return out


def plot_correlation_heatmap(cfg: dict) -> Path | None:
    """Heatmap de correlações de retornos diários entre os ETFs."""
    symbols = cfg["etfs"]
    closes = {}
    for sym in symbols:
        path = DATA_DAILY / f"{sym}.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if "close" in df.columns and not df["close"].isna().all():
                closes[sym] = df["close"].astype(float)

    if len(closes) < 2:
        return None

    price_df = pd.DataFrame(closes).dropna(how="all")
    corr = price_df.pct_change().dropna().corr()

    fig, ax = plt.subplots(figsize=(7, 6))
    sns.heatmap(
        corr, annot=True, fmt=".2f", cmap="coolwarm",
        center=0, ax=ax, linewidths=0.5,
        annot_kws={"size": 10, "color": "white"},
        cbar_kws={"shrink": 0.8},
    )
    ax.set_title("Correlação de Retornos", color=PALETTE["fg"], pad=10)
    fig.patch.set_facecolor(PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])
    ax.tick_params(colors=PALETTE["fg"])
    plt.tight_layout()
    out = REPORTS / "correlation_heatmap.png"
    plt.savefig(out, dpi=130, bbox_inches="tight")
    plt.close()
    return out


def main():
    import json as _json
    REPORTS.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH) as f:
        cfg = _json.load(f)

    generated = []

    # Scores bar
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        p = plot_scores_bar(summary)
        generated.append(str(p))

    # Trend + score evolution por ETF
    for symbol in cfg["etfs"]:
        path = DATA_DAILY / f"{symbol}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or "close" not in df.columns:
            continue
        p1 = plot_trend(df, symbol)
        generated.append(str(p1))
        p2 = plot_score_evolution(df, symbol)
        if p2:
            generated.append(str(p2))

    # Heatmap
    p = plot_correlation_heatmap(cfg)
    if p:
        generated.append(str(p))

    print(f"[OK] {len(generated)} gráfico(s) gerado(s):")
    for g in generated:
        print(f"  {g}")


if __name__ == "__main__":
    main()
