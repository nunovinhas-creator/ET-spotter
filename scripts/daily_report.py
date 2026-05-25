"""
Relatório diário às 19h: snapshot do dia, top movers, alertas activos.
Envia email HTML com gráfico de barras dos scores.
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

sys.path.insert(0, str(Path(__file__).parent))
from generate_charts import plot_scores_bar
from send_email import send_email


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_last_two_rows(symbol: str) -> tuple[pd.Series | None, pd.Series | None]:
    """Devolve (penúltima linha, última linha) de data/daily/SYMBOL.csv."""
    path = DATA_DAILY / f"{symbol}.csv"
    if not path.exists():
        return None, None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if df.empty or "score" not in df.columns:
        return None, None
    prev = df.iloc[-2] if len(df) >= 2 else None
    last = df.iloc[-1]
    return prev, last


def build_daily_rows(cfg: dict) -> pd.DataFrame:
    rows = []
    for sym in cfg["etfs"]:
        prev, last = load_last_two_rows(sym)
        if last is None:
            continue
        score_now = last.get("score", float("nan"))
        score_prev = prev.get("score", float("nan")) if prev is not None else float("nan")
        rows.append({
            "ETF": sym,
            "Preço": round(last.get("close", float("nan")), 2),
            "Ret. 1h": last.get("ret_1h", 0),
            "Ret. Dia": last.get("ret_24h", 0),
            "Score": round(score_now, 3),
            "Δ Score": round(score_now - score_prev, 3) if not pd.isna(score_prev) else 0,
            "Trend": "↑" if last.get("trend_sma", 0) else "↓",
            "MACD": "+" if last.get("macd_bullish", 0) else "−",
            "Drawdown": last.get("drawdown", 0),
        })
    return pd.DataFrame(rows).sort_values("Score", ascending=False)


def detect_daily_alerts(df: pd.DataFrame, thresholds: dict) -> list[str]:
    alerts = []
    for _, row in df.iterrows():
        sym = row["ETF"]
        if row["Ret. 1h"] <= thresholds.get("ret_1h_drop", -0.02):
            alerts.append(f"QUEDA HORÁRIA: {sym} {row['Ret. 1h']:.2%}")
        if row["Ret. Dia"] <= thresholds.get("ret_24h_drop", -0.03):
            alerts.append(f"QUEDA DIÁRIA: {sym} {row['Ret. Dia']:.2%}")
        if row["Drawdown"] <= -0.10:
            alerts.append(f"DRAWDOWN: {sym} {row['Drawdown']:.2%} do máximo")
    return alerts


def _color(val: float, threshold: float = 0) -> str:
    return "#4caf50" if val >= threshold else "#f44336"


def df_to_html_table(df: pd.DataFrame) -> str:
    style = "border-collapse:collapse;width:100%;font-family:monospace;font-size:13px"
    th_s = "background:#1e2130;color:#7c83fd;padding:8px 12px;text-align:right"
    td_s = "padding:6px 12px;border-bottom:1px solid #2a2d3e;color:#e8eaf6;text-align:right"

    display_cols = ["ETF", "Preço", "Ret. 1h", "Ret. Dia", "Score", "Δ Score", "Trend", "MACD"]
    headers = "".join(f'<th style="{th_s}">{c}</th>' for c in display_cols)

    rows_html = ""
    for _, row in df.iterrows():
        cells = ""
        for col in display_cols:
            val = row[col]
            color = "#e8eaf6"
            if col in ("Ret. 1h", "Ret. Dia"):
                color = _color(val)
                val = f"{val:.2%}"
            elif col == "Δ Score":
                color = _color(val)
                val = f"{val:+.3f}"
            elif col == "Score":
                color = _color(float(val), 0.5)
            cells += f'<td style="{td_s};color:{color}">{val}</td>'
        rows_html += f"<tr>{cells}</tr>"

    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows_html}</tbody></table>'


def build_html(table_html: str, df: pd.DataFrame, alerts: list[str],
               date_str: str, cfg: dict, image_names: list[str]) -> str:
    top_n = cfg["email"]["top_n"]
    top = df.head(top_n)
    worst = df.tail(min(3, len(df)))

    top_items = "".join(
        f'<li><strong>{r["ETF"]}</strong> – Score {r["Score"]:.3f}'
        f' | Dia {r["Ret. Dia"]:.2%} | {r["Trend"]} MACD {r["MACD"]}</li>'
        for _, r in top.iterrows()
    )
    worst_items = "".join(
        f'<li><strong>{r["ETF"]}</strong> – Score {r["Score"]:.3f}'
        f' | Dia {r["Ret. Dia"]:.2%}</li>'
        for _, r in worst.iterrows()
    )
    alert_html = ""
    if alerts:
        items = "".join(f'<li style="color:#f44336">{a}</li>' for a in alerts)
        alert_html = f'<h2 style="color:#f44336">Alertas Activos</h2><ul>{items}</ul>'

    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:700px;border-radius:8px"></p>'
        for n in image_names
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;padding:24px">
  <h1 style="color:#7c83fd">ET-Spotter – Relatório Diário</h1>
  <p style="color:#aaa">{date_str} · 19h UTC · gerado automaticamente</p>
  {alert_html}
  <h2 style="color:#7c83fd">Top {top_n} ETFs</h2>
  <ol style="line-height:1.8">{top_items}</ol>
  <h2 style="color:#f44336">Piores Hoje</h2>
  <ol style="line-height:1.8" reversed>{worst_items}</ol>
  <h2 style="color:#7c83fd">Todos os ETFs</h2>
  {table_html}
  <h2 style="color:#7c83fd">Score Visual</h2>
  {images_html}
  <hr style="border-color:#2a2d3e;margin-top:32px">
  <p style="color:#555;font-size:11px">ET-Spotter · GitHub Actions · dados via yfinance</p>
</body>
</html>"""


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    df = build_daily_rows(cfg)
    if df.empty:
        print("[SKIP] Sem dados para relatório diário.")
        return

    thresholds = cfg["params"]["alert_thresholds"]
    alerts = detect_daily_alerts(df, thresholds)

    # Gráfico de barras dos scores
    chart_paths = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary))

    date_str = datetime.utcnow().strftime("%d/%m/%Y")
    table_html = df_to_html_table(df)
    image_names = [p.name for p in chart_paths if p and p.exists()]
    html = build_html(table_html, df, alerts, date_str, cfg, image_names)

    report_file = REPORTS / f"daily_{datetime.utcnow().strftime('%Y%m%d')}.html"
    report_file.write_text(html, encoding="utf-8")
    print(f"[OK] Relatório diário: {report_file}")
    if alerts:
        for a in alerts:
            print(f"[ALERTA] {a}")

    email_to_env = os.getenv("EMAIL_TO", "")
    if email_to_env:
        to_list = [a.strip() for a in email_to_env.split(",")]
        prefix = "ALERTAS " if alerts else ""
        subject = f"ET-Spotter – {prefix}Relatório Diário {date_str}"
        send_email(subject, html, to_list, images=[p for p in chart_paths if p and p.exists()])
    else:
        print("[EMAIL] EMAIL_TO não definido – email não enviado.")


if __name__ == "__main__":
    main()
