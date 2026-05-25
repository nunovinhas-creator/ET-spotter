"""
Relatório semanal — perspectiva de analista:
sinais de compra, rotação sectorial, evolução semanal, gráficos.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import (load_config, get_etfs, get_category_map,
                   category_summary, build_buy_signals)
from generate_charts import (
    plot_scores_bar, plot_category_summary,
    plot_trend, plot_score_evolution, plot_correlation_heatmap,
)
from send_email import send_email

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")


# ─── Carrega dados ────────────────────────────────────────────────────────────

def load_rows(cfg: dict, days: int = 7) -> tuple[list[dict], pd.DataFrame]:
    cmap   = get_category_map(cfg)
    cutoff = pd.Timestamp.now("UTC").tz_convert(None) - timedelta(days=days)
    rows_raw, rows_display = [], []

    for sym in get_etfs(cfg):
        path = DATA_DAILY / f"{sym}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.empty or "score" not in df.columns:
            continue
        week  = df[df.index >= cutoff] if not df.empty else df
        if week.empty:
            week = df

        first, last = week.iloc[0], week.iloc[-1]
        info        = cmap.get(sym, {})

        score      = float(last.get("score",       0) or 0)
        score_ini  = float(first.get("score",      0) or 0)
        delta      = round(score - score_ini, 4)
        trend_sma  = int(last.get("trend_sma",     0) or 0)
        macd_bull  = int(last.get("macd_bullish",  0) or 0)
        ret_5d     = float(last.get("ret_5d",      0) or 0)
        ret_20d    = float(last.get("ret_20d",     0) or 0)
        ret_24h    = float(last.get("ret_24h",     0) or 0)
        drawdown   = float(last.get("drawdown",    0) or 0)
        vol_30     = float(last.get("vol_30",      0) or 0)

        rows_raw.append({
            "ticker": sym, "nome": info.get("name", sym),
            "categoria": info.get("category_name", "—"),
            "cor": info.get("color", "#7c83fd"),
            "score": round(score, 3), "delta_score": delta,
            "trend_sma": trend_sma, "macd_bullish": macd_bull,
            "ret_5d": ret_5d, "ret_24h": ret_24h, "ret_1h": ret_24h,
            "drawdown": drawdown, "vol_30": vol_30,
            "close": round(float(last.get("close", 0) or 0), 2),
        })
        rows_display.append({
            "etf": sym, "delta_score": delta, "ret_24h": ret_24h,
            "ETF":         sym,
            "Nome":        info.get("name", sym),
            "Categoria":   info.get("category_name", "—"),
            "Cor":         info.get("color", "#7c83fd"),
            "Score":       round(score, 3),
            "Δ Score Sem.": delta,
            "Ret. Semana": ret_5d,
            "Ret. 20d":    ret_20d,
            "Vol 30d":     vol_30,
            "Trend":       "↑" if trend_sma else "↓",
            "MACD":        "+" if macd_bull else "−",
            "Drawdown":    round(drawdown, 4),
        })

    df_display = pd.DataFrame(rows_display).sort_values("Score", ascending=False)
    return rows_raw, df_display


# ─── HTML helpers (reutilizados do daily_report) ──────────────────────────────

def _c(val: float, neutral: float = 0) -> str:
    return "#4caf50" if val >= neutral else "#f44336"


def buy_signals_html(signals: list[dict]) -> str:
    if not signals:
        return '<p style="color:#666">Sem confluência de sinais suficiente esta semana.</p>'
    cards = ""
    for s in signals:
        badge = (
            f'<span style="background:{s["color"]};color:#000;padding:3px 10px;'
            f'border-radius:12px;font-size:11px;font-weight:bold">{s["level"]}</span>'
        )
        metrics = (
            f'<span style="color:#aaa">Ret. Sem.:</span> '
            f'<span style="color:{_c(s["ret_5d"])}">{s["ret_5d"]:.2%}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Score:</span> '
            f'<span style="color:{_c(s["score"],0.5)};font-weight:bold">{s["score"]:.3f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Δ Semana:</span> '
            f'<span style="color:{_c(s["delta_score"])}">{s["delta_score"]:+.3f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Drawdown:</span> '
            f'<span style="color:{_c(s["drawdown"],-0.05)}">{s["drawdown"]:.1%}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Vol 30d:</span> '
            f'<span style="color:#e8eaf6">{s["vol_30"]:.1%}</span>'
        )
        cards += f"""
        <div style="background:{s['bg']};border-left:4px solid {s['color']};
                    padding:14px 18px;margin:8px 0;border-radius:4px">
          <div>
            <span style="color:#e8eaf6;font-size:19px;font-weight:bold">{s['ticker']}</span>
            <span style="color:#888;font-size:11px;margin-left:8px">{s['nome']}</span>
            &nbsp;{badge}
            <span style="color:{s['cor']};font-size:11px;margin-left:10px">● {s['categoria']}</span>
          </div>
          <div style="color:#bbb;font-size:12px;margin-top:8px;line-height:1.6">
            {s['rationale']}
          </div>
          <div style="margin-top:8px;font-size:12px">{metrics}</div>
        </div>"""
    return cards


def sector_rotation_html(cats: list[dict]) -> str:
    gaining = [c for c in cats if c["momentum"] == "▲"]
    neutral = [c for c in cats if c["momentum"] == "→"]
    losing  = [c for c in cats if c["momentum"] == "▼"]

    def pill(c):
        return (
            f'<span style="background:#1a1d2e;border:1px solid {c["color"]};'
            f'color:{c["color"]};padding:4px 10px;border-radius:12px;'
            f'font-size:11px;margin:3px;display:inline-block">'
            f'{c["momentum"]} {c["name"]} '
            f'<span style="color:#555">({c["score_avg"]:.2f})</span></span>'
        )

    g = "".join(pill(c) for c in gaining) or '<span style="color:#555">—</span>'
    n = "".join(pill(c) for c in neutral) or '<span style="color:#555">—</span>'
    l = "".join(pill(c) for c in losing)  or '<span style="color:#555">—</span>'

    return f"""
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td style="width:33%;vertical-align:top;padding:8px">
          <div style="color:#4caf50;font-size:12px;font-weight:bold;margin-bottom:6px">▲ A GANHAR FORÇA</div>{g}
        </td>
        <td style="width:34%;vertical-align:top;padding:8px;border-left:1px solid #1e2130">
          <div style="color:#78909c;font-size:12px;font-weight:bold;margin-bottom:6px">→ ESTÁVEL</div>{n}
        </td>
        <td style="width:33%;vertical-align:top;padding:8px;border-left:1px solid #1e2130">
          <div style="color:#f44336;font-size:12px;font-weight:bold;margin-bottom:6px">▼ A PERDER FORÇA</div>{l}
        </td>
      </tr>
    </table>"""


def full_table_html(df: pd.DataFrame) -> str:
    cols = ["ETF", "Nome", "Categoria", "Score", "Δ Score Sem.", "Ret. Semana", "Ret. 20d", "Vol 30d", "Trend", "MACD"]
    th = "background:#0d1021;color:#7c83fd;padding:6px 10px;text-align:right;font-size:11px;white-space:nowrap"
    td = "padding:4px 10px;border-bottom:1px solid #0d1021;font-size:11px;text-align:right"
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    rows = ""
    for _, r in df.iterrows():
        dot = f'<span style="color:{r["Cor"]}">●</span> '
        rows += "<tr>"
        for c in cols:
            if c == "ETF":
                rows += f'<td style="{td};color:#e8eaf6;text-align:left">{dot}{r["ETF"]}</td>'
            elif c == "Nome":
                rows += f'<td style="{td};color:#555;text-align:left">{r["Nome"]}</td>'
            elif c == "Categoria":
                rows += f'<td style="{td};color:{r["Cor"]}">{r["Categoria"]}</td>'
            elif c in ("Ret. Semana", "Ret. 20d"):
                v = r[c]; rows += f'<td style="{td};color:{_c(v)}">{v:.2%}</td>'
            elif c == "Δ Score Sem.":
                v = r[c]; rows += f'<td style="{td};color:{_c(v)}">{v:+.3f}</td>'
            elif c == "Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v,0.5)};font-weight:bold">{v}</td>'
            elif c == "Vol 30d":
                rows += f'<td style="{td};color:#aaa">{r[c]:.2%}</td>'
            else:
                rows += f'<td style="{td};color:#aaa">{r[c]}</td>'
        rows += "</tr>"
    return f'<table style="border-collapse:collapse;width:100%;background:#0f1117"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def category_table_html(cats: list[dict]) -> str:
    th = "background:#0d1021;color:#7c83fd;padding:7px 12px;text-align:right;font-size:12px"
    td = "padding:6px 12px;border-bottom:1px solid #0d1021;text-align:right;font-size:12px"
    rows = ""
    for c in cats:
        sc, rc = c["score_avg"], c["ret_avg"]
        mc = {"▲": "#4caf50", "→": "#78909c", "▼": "#f44336"}.get(c["momentum"], "#aaa")
        rows += (
            f'<tr>'
            f'<td style="{td};color:{c["color"]};text-align:left">{c["name"]}</td>'
            f'<td style="{td};color:#555">{c["n"]}</td>'
            f'<td style="{td};color:{_c(sc,0.5)};font-weight:bold">{sc:.3f}</td>'
            f'<td style="{td};color:{_c(c["delta_avg"])}">{c["delta_avg"]:+.4f}</td>'
            f'<td style="{td};color:{mc};font-size:16px">{c["momentum"]}</td>'
            f'<td style="{td};color:{_c(rc)}">{rc:.2%}</td>'
            f'<td style="{td};color:#4caf50">{c["score_max"]:.3f}</td>'
            f'<td style="{td};color:#f44336">{c["score_min"]:.3f}</td>'
            f'</tr>'
        )
    hdrs = "".join(f'<th style="{th}">{h}</th>'
                   for h in ["Categoria","N","Score Méd.","Δ Score","Mom.","Ret. Sem.","Melhor","Pior"])
    return f'<table style="border-collapse:collapse;width:100%;background:#0f1117"><thead><tr>{hdrs}</tr></thead><tbody>{rows}</tbody></table>'


# ─── Build HTML ───────────────────────────────────────────────────────────────

def build_html(rows_raw, df_display, cats, week_str, cfg, image_names) -> str:
    signals    = build_buy_signals(rows_raw, top_n=8)
    sig_html   = buy_signals_html(signals)
    rot_html   = sector_rotation_html(cats)
    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:720px;border-radius:6px;margin:6px 0"></p>'
        for n in image_names
    )

    n_strong = sum(1 for s in signals if s["level"] == "FORTE COMPRA")
    n_buy    = sum(1 for s in signals if s["level"] == "COMPRA")
    summary_line = (
        f'<span style="color:#4caf50;font-weight:bold">{n_strong} FORTE COMPRA</span> · '
        f'<span style="color:#8bc34a">{n_buy} COMPRA</span> · '
        f'<span style="color:#ffd54f">{len(signals)-n_strong-n_buy} POTENCIAL</span>'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;
             padding:24px 28px;max-width:820px;margin:0 auto">

  <h1 style="color:#7c83fd;margin-bottom:2px;font-size:22px">ET-Spotter – Análise Semanal</h1>
  <p style="color:#555;margin-top:0;font-size:13px">Semana {week_str} · 123 ETFs · sexta-feira</p>

  <!-- SINAIS DE COMPRA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Sinais de Compra – Próximas Semanas
    </h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      Confluência de indicadores técnicos: {summary_line}
    </p>
    {sig_html}
  </div>

  <!-- ROTAÇÃO SECTORIAL -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Rotação Sectorial</h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      Categorias por momentum médio esta semana
    </p>
    {rot_html}
  </div>

  <!-- GRÁFICOS -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Scores Visuais</h2>
    {images_html}
  </div>

  <!-- RESUMO POR CATEGORIA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Resumo por Categoria</h2>
    {category_table_html(cats)}
  </div>

  <!-- TABELA COMPLETA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Todos os ETFs
      <span style="color:#555;font-size:12px;font-weight:normal;margin-left:8px">
        ordenados por score
      </span>
    </h2>
    {full_table_html(df_display)}
  </div>

  <hr style="border-color:#1e2130;margin-top:32px">
  <p style="color:#333;font-size:10px">
    ET-Spotter · GitHub Actions · dados via yfinance ·
    Este relatório é informativo e não constitui aconselhamento financeiro.
  </p>
</body></html>"""


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    rows_raw, df_display = load_rows(cfg)
    if df_display.empty:
        print("[SKIP] Sem dados.")
        return

    df_for_cats = pd.DataFrame([{
        "etf": r["ticker"], "score": r["score"],
        "ret_24h": r["ret_5d"], "delta_score": r["delta_score"]
    } for r in rows_raw])
    cats = category_summary(df_for_cats, cfg)

    chart_paths = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary, cfg))
        p = plot_category_summary(summary, cfg)
        if p: chart_paths.append(p)

    p = plot_correlation_heatmap(cfg)
    if p: chart_paths.append(p)

    top_etf = df_display.iloc[0]["ETF"]
    df_top  = pd.read_csv(DATA_DAILY / f"{top_etf}.csv", index_col=0, parse_dates=True)
    chart_paths.append(plot_trend(df_top, top_etf, df_display.iloc[0]["Nome"]))
    p = plot_score_evolution(df_top, top_etf)
    if p: chart_paths.append(p)
    chart_paths = [p for p in chart_paths if p and p.exists()]

    week_str = (
        f"{(datetime.utcnow()-timedelta(days=7)).strftime('%d/%m')} – "
        f"{datetime.utcnow().strftime('%d/%m/%Y')}"
    )
    html = build_html(rows_raw, df_display, cats, week_str, cfg,
                      [p.name for p in chart_paths])

    out = REPORTS / f"weekly_{datetime.utcnow().strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")

    email_to = os.getenv("EMAIL_TO", "")
    if email_to:
        send_email(
            f"ET-Spotter – Análise Semanal {datetime.utcnow().strftime('%d %b %Y')}",
            html,
            [a.strip() for a in email_to.split(",")],
            images=chart_paths,
        )
    else:
        print("[EMAIL] EMAIL_TO não definido.")


if __name__ == "__main__":
    main()
