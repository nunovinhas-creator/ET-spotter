"""
Gera o relatório semanal: agrega dados da semana, calcula variações,
produz HTML e envia por email com gráficos em anexo inline.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path("config/etfs.json")
DATA_DAILY = Path("data/daily")
REPORTS = Path("data/reports")

# Importações locais
sys.path.insert(0, str(Path(__file__).parent))
from generate_charts import (
    plot_scores_bar,
    plot_trend,
    plot_score_evolution,
    plot_correlation_heatmap,
)
from send_email import send_email


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_weekly_data(symbol: str, days: int = 7) -> pd.DataFrame | None:
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    cutoff = pd.Timestamp.now("UTC").tz_localize(None) - timedelta(days=days)
    return df[df.index >= cutoff] if not df.empty else df


def build_weekly_table(cfg: dict) -> pd.DataFrame:
    rows = []
    for sym in cfg["etfs"]:
        df = load_weekly_data(sym)
        if df is None or df.empty or "score" not in df.columns:
            continue
        first = df.iloc[0]
        last = df.iloc[-1]
        rows.append({
            "ETF": sym,
            "Score Atual": round(last["score"], 3),
            "Score Início Sem.": round(first["score"], 3),
            "Δ Score": round(last["score"] - first["score"], 3),
            "Ret. Semana": f"{last.get('ret_5d', 0):.2%}",
            "Vol 30d": f"{last.get('vol_30', 0):.2%}",
            "Trend": "↑" if last.get("trend_sma", 0) else "↓",
            "MACD": "+" if last.get("macd_bullish", 0) else "−",
        })
    return pd.DataFrame(rows).sort_values("Score Atual", ascending=False)


def df_to_html_table(df: pd.DataFrame) -> str:
    style = (
        "border-collapse:collapse;width:100%;font-family:monospace;font-size:13px"
    )
    th_style = "background:#1e2130;color:#7c83fd;padding:8px 12px;text-align:right"
    td_style = "padding:6px 12px;border-bottom:1px solid #2a2d3e;color:#e8eaf6"

    rows_html = ""
    for _, row in df.iterrows():
        delta = row["Δ Score"]
        delta_color = "#4caf50" if delta >= 0 else "#f44336"
        rows_html += "<tr>"
        for col, val in row.items():
            val_str = str(val)
            color = delta_color if col == "Δ Score" else "#e8eaf6"
            rows_html += f'<td style="{td_style};color:{color}">{val_str}</td>'
        rows_html += "</tr>"

    headers = "".join(f'<th style="{th_style}">{c}</th>' for c in df.columns)
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>'


def build_html(table_html: str, top_n: list[dict], week_str: str, image_names: list[str]) -> str:
    top_items = "".join(
        f'<li><strong>{r["ETF"]}</strong> – Score {r["Score Atual"]:.3f}'
        f' | Ret. {r["Ret. Semana"]} | Trend {r["Trend"]}</li>'
        for r in top_n
    )
    images_html = "".join(
        f'<p><img src="cid:{name}" style="max-width:700px;border-radius:8px"></p>'
        for name in image_names
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;padding:24px">
  <h1 style="color:#7c83fd">ET-Spotter – Relatório Semanal</h1>
  <p style="color:#aaa">Semana de {week_str} · gerado automaticamente</p>
  <h2 style="color:#7c83fd">Top ETFs por Score</h2>
  <ol style="line-height:1.8">{top_items}</ol>
  <h2 style="color:#7c83fd">Tabela Completa</h2>
  {table_html}
  <h2 style="color:#7c83fd">Gráficos</h2>
  {images_html}
  <hr style="border-color:#2a2d3e;margin-top:32px">
  <p style="color:#555;font-size:11px">ET-Spotter · GitHub Actions · dados via Alpha Vantage</p>
</body>
</html>"""


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    table_df = build_weekly_table(cfg)
    if table_df.empty:
        print("[SKIP] Sem dados suficientes para relatório semanal.")
        return

    # Gerar gráficos
    chart_paths: list[Path] = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary))

    p_heatmap = plot_correlation_heatmap(cfg)
    if p_heatmap:
        chart_paths.append(p_heatmap)

    top_etf = table_df.iloc[0]["ETF"]
    df_top = pd.read_csv(DATA_DAILY / f"{top_etf}.csv", index_col=0, parse_dates=True)
    chart_paths.append(plot_trend(df_top, top_etf))
    p_evo = plot_score_evolution(df_top, top_etf)
    if p_evo:
        chart_paths.append(p_evo)

    chart_paths = [p for p in chart_paths if p and p.exists()]

    week_str = f"{(datetime.utcnow() - timedelta(days=7)).strftime('%d/%m')} – {datetime.utcnow().strftime('%d/%m/%Y')}"
    top_n = table_df.head(cfg["email"]["top_n"]).to_dict("records")
    table_html = df_to_html_table(table_df)
    image_names = [p.name for p in chart_paths]
    html = build_html(table_html, top_n, week_str, image_names)

    # Guardar HTML localmente
    report_file = REPORTS / f"weekly_{datetime.utcnow().strftime('%Y%m%d')}.html"
    report_file.write_text(html, encoding="utf-8")
    print(f"[OK] Relatório HTML: {report_file}")

    # Enviar email
    email_to_env = os.getenv("EMAIL_TO", "")
    if email_to_env:
        to_list = [a.strip() for a in email_to_env.split(",")]
        subject = f"ET-Spotter – Relatório {datetime.utcnow().strftime('%d %b %Y')}"
        send_email(subject, html, to_list, images=chart_paths)
    else:
        print("[EMAIL] EMAIL_TO não definido – email não enviado.")


if __name__ == "__main__":
    main()
