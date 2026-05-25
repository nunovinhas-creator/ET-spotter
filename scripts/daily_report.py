"""
Relatório diário às 19h: scores, top movers, piores, resumo por categoria.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_etfs, get_category_map, category_summary
from generate_charts import plot_scores_bar, plot_category_summary
from send_email import send_email

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")


def load_rows(cfg: dict) -> pd.DataFrame:
    cmap = get_category_map(cfg)
    rows = []
    for sym in get_etfs(cfg):
        path = DATA_DAILY / f"{sym}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or "score" not in df.columns:
            continue
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        info = cmap.get(sym, {})
        rows.append({
            "ETF":           sym,
            "Nome":          info.get("name", sym),
            "Categoria":     info.get("category_name", "—"),
            "Cor":           info.get("color", "#7c83fd"),
            "Preço":         round(last.get("close",    float("nan")), 2),
            "Ret. 1h":       last.get("ret_1h",         0) or 0,
            "Ret. Dia":      last.get("ret_24h",        0) or 0,
            "Score":         round(last.get("score",    float("nan")), 3),
            "Δ Score":       round((last.get("score", 0) or 0) - (prev.get("score", 0) or 0), 3),
            "Trend":         "↑" if last.get("trend_sma",    0) else "↓",
            "MACD":          "+" if last.get("macd_bullish", 0) else "−",
            "Drawdown":      last.get("drawdown", 0) or 0,
        })
    return pd.DataFrame(rows).sort_values("Score", ascending=False)


def detect_alerts(df: pd.DataFrame, thresholds: dict) -> list[str]:
    alerts = []
    for _, r in df.iterrows():
        if r["Ret. 1h"]  <= thresholds.get("ret_1h_drop",  -0.02):
            alerts.append(f"QUEDA HORÁRIA: {r['ETF']} {r['Ret. 1h']:.2%}")
        if r["Ret. Dia"] <= thresholds.get("ret_24h_drop", -0.03):
            alerts.append(f"QUEDA DIÁRIA: {r['ETF']} {r['Ret. Dia']:.2%}")
        if r["Drawdown"]  <= -0.10:
            alerts.append(f"DRAWDOWN: {r['ETF']} {r['Drawdown']:.2%} do máximo")
    return alerts


def _color(val: float, neutral: float = 0) -> str:
    return "#4caf50" if val >= neutral else "#f44336"


def _td(val, *, pct=False, delta=False, score=False) -> str:
    s = "padding:5px 10px;border-bottom:1px solid #1e2130;text-align:right"
    if pct:
        color = _color(val)
        text  = f"{val:.2%}"
    elif delta:
        color = _color(val)
        text  = f"{val:+.3f}"
    elif score:
        color = _color(float(val), 0.5)
        text  = str(val)
    else:
        color = "#e8eaf6"
        text  = str(val)
    return f'<td style="{s};color:{color}">{text}</td>'


def etf_table_html(df: pd.DataFrame, cols: list[str]) -> str:
    th = "background:#1e2130;color:#7c83fd;padding:6px 10px;text-align:right;font-size:12px"
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    rows = ""
    for _, r in df.iterrows():
        dot = f'<span style="color:{r["Cor"]};font-size:18px">●</span> '
        rows += "<tr>"
        for c in cols:
            if c == "ETF":
                rows += f'<td style="padding:5px 10px;border-bottom:1px solid #1e2130;color:#e8eaf6">{dot}{r["ETF"]}</td>'
            elif c == "Nome":
                rows += f'<td style="padding:5px 10px;border-bottom:1px solid #1e2130;color:#aaa;font-size:11px">{r["Nome"]}</td>'
            elif c == "Categoria":
                rows += f'<td style="padding:5px 10px;border-bottom:1px solid #1e2130;color:{r["Cor"]};font-size:11px">{r["Categoria"]}</td>'
            elif c in ("Ret. 1h", "Ret. Dia"):
                rows += _td(r[c], pct=True)
            elif c == "Δ Score":
                rows += _td(r[c], delta=True)
            elif c == "Score":
                rows += _td(r[c], score=True)
            else:
                rows += f'<td style="padding:5px 10px;border-bottom:1px solid #1e2130;color:#e8eaf6;text-align:right">{r[c]}</td>'
        rows += "</tr>"
    style = "border-collapse:collapse;width:100%;font-family:monospace;font-size:12px"
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def category_table_html(cats: list[dict]) -> str:
    th = "background:#1e2130;color:#7c83fd;padding:6px 10px;text-align:right;font-size:12px"
    cols = ["Categoria", "ETFs", "Score Médio", "Melhor", "Pior", "Ret. Dia"]
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    td = "padding:5px 10px;border-bottom:1px solid #1e2130;text-align:right"
    rows = ""
    for c in cats:
        score_color = _color(c["score_avg"], 0.5)
        ret_color   = _color(c["ret_avg"])
        rows += (
            f'<tr>'
            f'<td style="{td};color:{c["color"]}">{c["name"]}</td>'
            f'<td style="{td};color:#e8eaf6">{c["n"]}</td>'
            f'<td style="{td};color:{score_color};font-weight:bold">{c["score_avg"]:.3f}</td>'
            f'<td style="{td};color:#4caf50">{c["score_max"]:.3f}</td>'
            f'<td style="{td};color:#f44336">{c["score_min"]:.3f}</td>'
            f'<td style="{td};color:{ret_color}">{c["ret_avg"]:.2%}</td>'
            f'</tr>'
        )
    style = "border-collapse:collapse;width:100%;font-family:monospace;font-size:12px"
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def build_html(df: pd.DataFrame, cats: list[dict], alerts: list[str],
               date_str: str, cfg: dict, image_names: list[str]) -> str:
    top_n   = cfg["email"]["top_n"]
    top_df  = df.head(top_n)
    worst_df = df.tail(5).iloc[::-1]

    alert_html = ""
    if alerts:
        items = "".join(f'<li style="color:#f44336;margin:4px 0">{a}</li>' for a in alerts)
        alert_html = f'<h2 style="color:#f44336">⚠ Alertas Activos</h2><ul>{items}</ul>'

    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:720px;border-radius:8px;margin:8px 0"></p>'
        for n in image_names
    )

    top_table  = etf_table_html(top_df,  ["ETF", "Nome", "Categoria", "Score", "Δ Score", "Ret. 1h", "Ret. Dia", "Trend", "MACD"])
    worst_table = etf_table_html(worst_df, ["ETF", "Nome", "Categoria", "Score", "Ret. Dia"])
    full_table = etf_table_html(df, ["ETF", "Categoria", "Score", "Δ Score", "Ret. 1h", "Ret. Dia", "Trend", "MACD"])
    cat_table  = category_table_html(cats)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;padding:24px;max-width:800px">
  <h1 style="color:#7c83fd;margin-bottom:4px">ET-Spotter – Relatório Diário</h1>
  <p style="color:#666;margin-top:0">{date_str} · 19h UTC</p>
  {alert_html}
  <h2 style="color:#7c83fd">Resumo por Categoria</h2>
  {cat_table}
  {images_html}
  <h2 style="color:#4caf50">Top {top_n} ETFs</h2>
  {top_table}
  <h2 style="color:#f44336">Piores 5 ETFs</h2>
  {worst_table}
  <h2 style="color:#7c83fd">Todos os ETFs</h2>
  {full_table}
  <hr style="border-color:#1e2130;margin-top:32px">
  <p style="color:#444;font-size:11px">ET-Spotter · GitHub Actions · dados via yfinance</p>
</body></html>"""


def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    df = load_rows(cfg)
    if df.empty:
        print("[SKIP] Sem dados para relatório diário.")
        return

    alerts = detect_alerts(df, cfg["params"]["alert_thresholds"])
    cats   = category_summary(df.rename(columns={"Score": "score", "ETF": "etf",
                                                   "Ret. Dia": "ret_24h"}), cfg)

    chart_paths = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary, cfg))
        p = plot_category_summary(summary, cfg)
        if p:
            chart_paths.append(p)
    chart_paths = [p for p in chart_paths if p and p.exists()]

    date_str    = datetime.utcnow().strftime("%d/%m/%Y")
    image_names = [p.name for p in chart_paths]
    html        = build_html(df, cats, alerts, date_str, cfg, image_names)

    out = REPORTS / f"daily_{datetime.utcnow().strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")
    for a in alerts:
        print(f"[ALERTA] {a}")

    email_to = os.getenv("EMAIL_TO", "")
    if email_to:
        prefix  = "ALERTAS " if alerts else ""
        subject = f"ET-Spotter – {prefix}Relatório Diário {date_str}"
        send_email(subject, html, [a.strip() for a in email_to.split(",")], images=chart_paths)
    else:
        print("[EMAIL] EMAIL_TO não definido.")


if __name__ == "__main__":
    main()
