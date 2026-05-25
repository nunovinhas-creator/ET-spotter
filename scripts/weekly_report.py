"""
Relatório semanal: variações semanais por ETF e por categoria, gráficos, email HTML.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, category_summary
from generate_charts import (
    plot_scores_bar, plot_category_summary,
    plot_trend, plot_score_evolution, plot_correlation_heatmap,
)
from send_email import send_email

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")


def load_weekly_rows(cfg: dict, days: int = 7) -> pd.DataFrame:
    cmap   = get_category_map(cfg)
    cutoff = pd.Timestamp.now("UTC").tz_convert(None) - timedelta(days=days)
    rows   = []

    for sym in get_etfs(cfg):
        path = DATA_DAILY / f"{sym}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or "score" not in df.columns:
            continue
        week = df[df.index >= cutoff]
        if week.empty:
            week = df

        first, last = week.iloc[0], week.iloc[-1]
        info = cmap.get(sym, {})
        rows.append({
            "ETF":            sym,
            "Nome":           info.get("name", sym),
            "Categoria":      info.get("category_name", "—"),
            "Cor":            info.get("color", "#7c83fd"),
            "Score Atual":    round(last.get("score", float("nan")), 3),
            "Δ Score Sem.":   round((last.get("score", 0) or 0) - (first.get("score", 0) or 0), 3),
            "Ret. Semana":    last.get("ret_5d",  0) or 0,
            "Vol 30d":        last.get("vol_30",  0) or 0,
            "Trend":          "↑" if last.get("trend_sma",    0) else "↓",
            "MACD":           "+" if last.get("macd_bullish", 0) else "−",
            "Drawdown":       round(last.get("drawdown", float("nan")), 4),
        })

    return pd.DataFrame(rows).sort_values("Score Atual", ascending=False)


def _td(val, *, pct=False, delta=False, score=False) -> str:
    s = "padding:5px 10px;border-bottom:1px solid #1e2130;text-align:right"
    if pct:
        color = "#4caf50" if val >= 0 else "#f44336"
        text  = f"{val:.2%}"
    elif delta:
        color = "#4caf50" if val >= 0 else "#f44336"
        text  = f"{val:+.3f}"
    elif score:
        color = "#4caf50" if float(val) >= 0.5 else "#f44336"
        text  = str(val)
    else:
        color = "#e8eaf6"
        text  = str(val)
    return f'<td style="{s};color:{color}">{text}</td>'


def etf_table_html(df: pd.DataFrame) -> str:
    cols = ["ETF", "Nome", "Categoria", "Score Atual", "Δ Score Sem.", "Ret. Semana", "Vol 30d", "Trend", "MACD"]
    th = "background:#1e2130;color:#7c83fd;padding:6px 10px;text-align:right;font-size:12px"
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    td_base = "padding:5px 10px;border-bottom:1px solid #1e2130"
    rows = ""
    for _, r in df.iterrows():
        dot = f'<span style="color:{r["Cor"]};font-size:16px">●</span> '
        rows += "<tr>"
        for c in cols:
            if c == "ETF":
                rows += f'<td style="{td_base};color:#e8eaf6">{dot}{r["ETF"]}</td>'
            elif c == "Nome":
                rows += f'<td style="{td_base};color:#aaa;font-size:11px">{r["Nome"]}</td>'
            elif c == "Categoria":
                rows += f'<td style="{td_base};color:{r["Cor"]};font-size:11px;text-align:right">{r["Categoria"]}</td>'
            elif c in ("Ret. Semana", "Vol 30d"):
                rows += _td(r[c], pct=True)
            elif c == "Δ Score Sem.":
                rows += _td(r[c], delta=True)
            elif c == "Score Atual":
                rows += _td(r[c], score=True)
            else:
                rows += f'<td style="{td_base};color:#e8eaf6;text-align:right">{r[c]}</td>'
        rows += "</tr>"
    style = "border-collapse:collapse;width:100%;font-family:monospace;font-size:12px"
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def category_table_html(cats: list[dict]) -> str:
    th = "background:#1e2130;color:#7c83fd;padding:6px 10px;text-align:right;font-size:12px"
    cols = ["Categoria", "ETFs", "Score Médio", "Melhor", "Pior", "Ret. Média Semana"]
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    td = "padding:5px 10px;border-bottom:1px solid #1e2130;text-align:right"
    rows = ""
    for c in cats:
        sc = c["score_avg"]
        rc = c["ret_avg"]
        rows += (
            f'<tr>'
            f'<td style="{td};color:{c["color"]}">{c["name"]}</td>'
            f'<td style="{td};color:#e8eaf6">{c["n"]}</td>'
            f'<td style="{td};color:{"#4caf50" if sc>=0.5 else "#f44336"};font-weight:bold">{sc:.3f}</td>'
            f'<td style="{td};color:#4caf50">{c["score_max"]:.3f}</td>'
            f'<td style="{td};color:#f44336">{c["score_min"]:.3f}</td>'
            f'<td style="{td};color:{"#4caf50" if rc>=0 else "#f44336"}">{rc:.2%}</td>'
            f'</tr>'
        )
    style = "border-collapse:collapse;width:100%;font-family:monospace;font-size:12px"
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def build_html(df: pd.DataFrame, cats: list[dict], week_str: str,
               cfg: dict, image_names: list[str]) -> str:
    top_n    = cfg["email"]["top_n"]
    top_rows = df.head(top_n)

    top_items = "".join(
        f'<li><strong>{r["ETF"]}</strong> <span style="color:#888;font-size:11px">{r["Nome"]}</span>'
        f' — Score {r["Score Atual"]} | Sem. {r["Ret. Semana"]:.2%} | {r["Trend"]} MACD {r["MACD"]}</li>'
        for _, r in top_rows.iterrows()
    )
    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:720px;border-radius:8px;margin:8px 0"></p>'
        for n in image_names
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;padding:24px;max-width:800px">
  <h1 style="color:#7c83fd;margin-bottom:4px">ET-Spotter – Relatório Semanal</h1>
  <p style="color:#666;margin-top:0">Semana {week_str} · segunda 07h UTC</p>
  <h2 style="color:#7c83fd">Resumo por Categoria</h2>
  {category_table_html(cats)}
  <h2 style="color:#7c83fd">Top {top_n} ETFs da Semana</h2>
  <ol style="line-height:2">{top_items}</ol>
  <h2 style="color:#7c83fd">Gráficos</h2>
  {images_html}
  <h2 style="color:#7c83fd">Tabela Completa</h2>
  {etf_table_html(df)}
  <hr style="border-color:#1e2130;margin-top:32px">
  <p style="color:#444;font-size:11px">ET-Spotter · GitHub Actions · dados via yfinance</p>
</body></html>"""


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    df = load_weekly_rows(cfg)
    if df.empty:
        print("[SKIP] Sem dados para relatório semanal.")
        return

    # Agrega por categoria usando colunas renomeadas
    df_for_cats = df.rename(columns={"Score Atual": "score", "ETF": "etf", "Ret. Semana": "ret_24h"})
    cats = category_summary(df_for_cats, cfg)

    # Gráficos
    chart_paths = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary, cfg))
        p = plot_category_summary(summary, cfg)
        if p:
            chart_paths.append(p)

    p = plot_correlation_heatmap(cfg)
    if p:
        chart_paths.append(p)

    # Gráfico de tendência do top ETF
    top_etf = df.iloc[0]["ETF"]
    df_top  = pd.read_csv(DATA_DAILY / f"{top_etf}.csv", index_col=0, parse_dates=True)
    chart_paths.append(plot_trend(df_top, top_etf, df.iloc[0]["Nome"]))
    p = plot_score_evolution(df_top, top_etf)
    if p:
        chart_paths.append(p)

    chart_paths = [p for p in chart_paths if p and p.exists()]
    week_str    = f"{(datetime.utcnow()-timedelta(days=7)).strftime('%d/%m')} – {datetime.utcnow().strftime('%d/%m/%Y')}"
    html        = build_html(df, cats, week_str, cfg, [p.name for p in chart_paths])

    out = REPORTS / f"weekly_{datetime.utcnow().strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")

    email_to = os.getenv("EMAIL_TO", "")
    if email_to:
        subject = f"ET-Spotter – Relatório Semanal {datetime.utcnow().strftime('%d %b %Y')}"
        send_email(subject, html, [a.strip() for a in email_to.split(",")], images=chart_paths)
    else:
        print("[EMAIL] EMAIL_TO não definido.")


if __name__ == "__main__":
    main()
