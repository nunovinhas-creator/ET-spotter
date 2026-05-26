"""
Relatório diário às 19h — perspectiva de analista:
sinais de compra, rotação sectorial, tabela completa.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import (load_config, get_etfs, get_category_map,
                   category_summary, build_buy_signals)
from generate_charts import plot_scores_bar, plot_category_summary
from send_email import send_email

DATA_DAILY = Path("data/daily")
REPORTS    = Path("data/reports")


# ─── Carrega dados ────────────────────────────────────────────────────────────

def load_rows(cfg: dict) -> tuple[list[dict], pd.DataFrame]:
    """
    Devolve (rows_raw, df_display).
    rows_raw: dicts com campos numéricos para cálculos.
    df_display: DataFrame formatado para tabela HTML.
    """
    cmap = get_category_map(cfg)
    rows_raw, rows_display = [], []

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

        score       = float(last.get("score",        0) or 0)
        score_prev  = float(prev.get("score",        0) or 0)
        delta_score = round(score - score_prev, 4)
        trend_sma   = int(last.get("trend_sma",      0) or 0)
        macd_bull   = int(last.get("macd_bullish",   0) or 0)
        ret_1d      = float(last.get("ret_1d",       0) or 0)
        ret_5d      = float(last.get("ret_5d",       0) or 0)
        ret_21d     = float(last.get("ret_21d",      0) or 0)
        ret_63d     = float(last.get("ret_63d",      0) or 0)
        drawdown    = float(last.get("drawdown",     0) or 0)
        vol_21      = float(last.get("vol_21",       0) or 0)
        rsi         = float(last.get("rsi",          50) or 50)
        adx         = float(last.get("adx",          0) or 0)
        rs_positive = int(last.get("rs_positive",    0) or 0)
        rs_mom_21   = float(last.get("rs_mom_21",    0) or 0)
        above_sma200 = int(last.get("above_sma200",  0) or 0)
        score_pct_raw = last.get("score_pct", None)
        score_pct   = float(score_pct_raw) if score_pct_raw not in (None, "") else None

        rows_raw.append({
            "ticker": sym, "nome": info.get("name", sym),
            "categoria": info.get("category_name", "—"),
            "cor": info.get("color", "#7c83fd"),
            "score": round(score, 3), "delta_score": delta_score,
            "trend_sma": trend_sma, "macd_bullish": macd_bull,
            "ret_5d": ret_5d, "ret_21d": ret_21d, "ret_63d": ret_63d,
            "ret_24h": ret_1d,  # alias for category_summary compatibility
            "drawdown": drawdown, "vol_21": vol_21,
            "rsi": rsi, "adx": adx,
            "rs_positive": rs_positive, "rs_mom_21": rs_mom_21,
            "above_sma200": above_sma200, "score_pct": score_pct,
            "close": round(float(last.get("close", 0) or 0), 2),
        })
        rows_display.append({
            "etf": sym, "delta_score": delta_score, "ret_24h": ret_1d,
            "ETF":         sym,
            "Nome":        info.get("name", sym),
            "Categoria":   info.get("category_name", "—"),
            "Cor":         info.get("color", "#7c83fd"),
            "Score":       round(score, 3),
            "Δ Score":     delta_score,
            "Ret. Dia":    ret_1d,
            "Ret. 5d":     ret_5d,
            "Ret. 3M":     ret_63d,
            "Vol 21d":     vol_21,
            "RSI":         round(rsi, 1),
            "Trend":       "↑" if trend_sma else "↓",
            "MACD":        "+" if macd_bull else "−",
            "RS vs SPY":   "✓" if rs_positive else "✗",
        })

    if rows_display:
        df_display = pd.DataFrame(rows_display).sort_values("Score", ascending=False)
    else:
        df_display = pd.DataFrame()
    return rows_raw, df_display


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def _c(val: float, neutral: float = 0) -> str:
    return "#4caf50" if val >= neutral else "#f44336"


def buy_signals_html(signals: list[dict]) -> str:
    if not signals:
        return '<p style="color:#666">Sem confluência de sinais suficiente hoje.</p>'

    cards = ""
    for s in signals:
        badge_html = (
            f'<span style="background:{s["color"]};color:#000;padding:3px 10px;'
            f'border-radius:12px;font-size:11px;font-weight:bold;'
            f'letter-spacing:0.5px">{s["level"]}</span>'
        )
        rsi_val = s.get("rsi", 50) or 50
        rsi_color = "#4caf50" if 40 <= rsi_val <= 65 else ("#ffd54f" if rsi_val > 70 else "#aaa")
        rs_icon = "✓ superando SPY" if s.get("rs_positive") else "✗ abaixo SPY"
        rs_color = "#4caf50" if s.get("rs_positive") else "#f44336"
        score_pct = s.get("score_pct")
        pct_str = (
            f'&nbsp;<span style="color:#888;font-size:10px">'
            f'P{score_pct*100:.0f}</span>'
            if score_pct is not None and str(score_pct) != "nan" else ""
        )
        metrics = (
            f'<span style="color:#aaa">Score:</span> '
            f'<span style="color:{_c(s["score"], 0.5)};font-weight:bold">{s["score"]:.3f}</span>'
            f'{pct_str}&nbsp;&nbsp;'
            f'<span style="color:#aaa">Ret. 3M:</span> '
            f'<span style="color:{_c(s.get("ret_63d", 0))}">{s.get("ret_63d", 0):.2%}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Ret. 5d:</span> '
            f'<span style="color:{_c(s["ret_5d"])}">{s["ret_5d"]:.2%}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">RSI:</span> '
            f'<span style="color:{rsi_color}">{rsi_val:.0f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">RS vs SPY:</span> '
            f'<span style="color:{rs_color}">{rs_icon}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Δ Score:</span> '
            f'<span style="color:{_c(s["delta_score"])}">{s["delta_score"]:+.3f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Drawdown:</span> '
            f'<span style="color:{_c(s["drawdown"], -0.05)}">{s["drawdown"]:.1%}</span>'
        )
        cards += f"""
        <div style="background:{s['bg']};border-left:4px solid {s['color']};
                    padding:14px 18px;margin:8px 0;border-radius:4px">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <div>
              <span style="color:#e8eaf6;font-size:19px;font-weight:bold">{s['ticker']}</span>
              <span style="color:#888;font-size:11px;margin-left:8px">{s['nome']}</span>
              &nbsp;{badge_html}
              <span style="color:{s['cor']};font-size:11px;margin-left:10px">● {s['categoria']}</span>
            </div>
          </div>
          <div style="color:#bbb;font-size:12px;margin-top:8px;line-height:1.6">
            {s['rationale']}
          </div>
          <div style="margin-top:8px;font-size:12px">
            {metrics}
          </div>
        </div>"""
    return cards


def sector_rotation_html(cats: list[dict]) -> str:
    gaining  = [c for c in cats if c["momentum"] == "▲"]
    neutral  = [c for c in cats if c["momentum"] == "→"]
    losing   = [c for c in cats if c["momentum"] == "▼"]

    def cat_pill(c):
        return (
            f'<span style="background:#1a1d2e;border:1px solid {c["color"]};'
            f'color:{c["color"]};padding:4px 10px;border-radius:12px;'
            f'font-size:11px;margin:3px;display:inline-block">'
            f'{c["momentum"]} {c["name"]} <span style="color:#666">({c["score_avg"]:.2f})</span>'
            f'</span>'
        )

    g_html = "".join(cat_pill(c) for c in gaining) or '<span style="color:#555">—</span>'
    n_html = "".join(cat_pill(c) for c in neutral) or '<span style="color:#555">—</span>'
    l_html = "".join(cat_pill(c) for c in losing)  or '<span style="color:#555">—</span>'

    return f"""
    <table style="width:100%;border-collapse:collapse">
      <tr>
        <td style="width:33%;vertical-align:top;padding:8px">
          <div style="color:#4caf50;font-size:12px;font-weight:bold;margin-bottom:6px">▲ MOMENTUM POSITIVO</div>
          {g_html}
        </td>
        <td style="width:34%;vertical-align:top;padding:8px;border-left:1px solid #1e2130">
          <div style="color:#78909c;font-size:12px;font-weight:bold;margin-bottom:6px">→ NEUTRO</div>
          {n_html}
        </td>
        <td style="width:33%;vertical-align:top;padding:8px;border-left:1px solid #1e2130">
          <div style="color:#f44336;font-size:12px;font-weight:bold;margin-bottom:6px">▼ MOMENTUM NEGATIVO</div>
          {l_html}
        </td>
      </tr>
    </table>"""


def full_table_html(df: pd.DataFrame) -> str:
    cols = ["ETF", "Nome", "Categoria", "Score", "Δ Score", "Ret. Dia", "Ret. 5d", "Ret. 3M", "RSI", "RS vs SPY", "Vol 21d", "Trend", "MACD"]
    th = "background:#0d1021;color:#7c83fd;padding:6px 10px;text-align:right;font-size:11px;white-space:nowrap"
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    td = "padding:4px 10px;border-bottom:1px solid #0d1021;font-size:11px;text-align:right"
    rows = ""
    for _, r in df.iterrows():
        dot = f'<span style="color:{r["Cor"]}">●</span> '
        rows += "<tr>"
        for c in cols:
            if c == "ETF":
                rows += f'<td style="{td};color:#e8eaf6;text-align:left">{dot}{r["ETF"]}</td>'
            elif c == "Nome":
                rows += f'<td style="{td};color:#666;text-align:left;max-width:160px;overflow:hidden">{r["Nome"]}</td>'
            elif c == "Categoria":
                rows += f'<td style="{td};color:{r["Cor"]}">{r["Categoria"]}</td>'
            elif c in ("Ret. Dia", "Ret. 5d", "Ret. 3M"):
                v = r.get(c, 0); rows += f'<td style="{td};color:{_c(v)}">{v:.2%}</td>'
            elif c == "Δ Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v)}">{v:+.3f}</td>'
            elif c == "Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v,0.5)};font-weight:bold">{v}</td>'
            elif c == "Vol 21d":
                v = r.get(c, 0); rows += f'<td style="{td};color:#e8eaf6">{v:.2%}</td>'
            elif c == "RSI":
                v = r.get(c, 50)
                rsi_c = "#4caf50" if 40 <= v <= 65 else ("#ffd54f" if v > 70 else "#aaa")
                rows += f'<td style="{td};color:{rsi_c}">{v:.0f}</td>'
            elif c == "RS vs SPY":
                v = r.get(c, "✗")
                rs_c = "#4caf50" if v == "✓" else "#f44336"
                rows += f'<td style="{td};color:{rs_c}">{v}</td>'
            else:
                rows += f'<td style="{td};color:#aaa">{r.get(c, "")}</td>'
        rows += "</tr>"
    style = "border-collapse:collapse;width:100%;background:#0f1117"
    return f'<table style="{style}"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


def category_table_html(cats: list[dict]) -> str:
    th = "background:#0d1021;color:#7c83fd;padding:7px 12px;text-align:right;font-size:12px"
    td = "padding:6px 12px;border-bottom:1px solid #0d1021;text-align:right;font-size:12px"
    rows = ""
    for c in cats:
        sc, rc = c["score_avg"], c["ret_avg"]
        mom_color = {"▲": "#4caf50", "→": "#78909c", "▼": "#f44336"}.get(c["momentum"], "#aaa")
        rows += (
            f'<tr>'
            f'<td style="{td};color:{c["color"]};text-align:left">{c["name"]}</td>'
            f'<td style="{td};color:#666">{c["n"]}</td>'
            f'<td style="{td};color:{_c(sc,0.5)};font-weight:bold">{sc:.3f}</td>'
            f'<td style="{td};color:{_c(c["delta_avg"])}">{c["delta_avg"]:+.4f}</td>'
            f'<td style="{td};color:{mom_color};font-size:16px">{c["momentum"]}</td>'
            f'<td style="{td};color:{_c(rc)}">{rc:.2%}</td>'
            f'<td style="{td};color:#4caf50">{c["score_max"]:.3f}</td>'
            f'<td style="{td};color:#f44336">{c["score_min"]:.3f}</td>'
            f'</tr>'
        )
    headers = "".join(
        f'<th style="{th}">{h}</th>'
        for h in ["Categoria","N","Score Méd.","Δ Score","Mom.","Ret. Dia","Melhor","Pior"]
    )
    return f'<table style="border-collapse:collapse;width:100%;background:#0f1117"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>'


# ─── Build HTML ───────────────────────────────────────────────────────────────

def build_html(rows_raw, df_display, cats, date_str, cfg, image_names) -> str:
    signals     = build_buy_signals(rows_raw, top_n=8)
    sig_html    = buy_signals_html(signals)
    rot_html    = sector_rotation_html(cats)
    table_html  = full_table_html(df_display)
    cat_html    = category_table_html(cats)
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
        f' — de {len(df_display)} ETFs analisados'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;
             padding:24px 28px;max-width:820px;margin:0 auto">

  <h1 style="color:#7c83fd;margin-bottom:2px;font-size:22px">ET-Spotter</h1>
  <p style="color:#555;margin-top:0;font-size:13px">{date_str} · Análise técnica diária · {len(get_etfs(cfg))} ETFs</p>

  <!-- SINAIS DE COMPRA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Sinais de Compra – Próximas Semanas
    </h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      ETFs com confluência de indicadores técnicos favoráveis · {summary_line}
    </p>
    {sig_html}
  </div>

  <!-- ROTAÇÃO SECTORIAL -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Rotação de Capital – Sectores</h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      Momentum médio por categoria (score médio + trajectória)
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
    {cat_html}
  </div>

  <!-- TABELA COMPLETA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Todos os ETFs
      <span style="color:#555;font-size:12px;font-weight:normal;margin-left:8px">
        ordenados por score decrescente
      </span>
    </h2>
    {table_html}
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

    # category_summary espera colunas específicas
    df_for_cats = pd.DataFrame([{
        "etf": r["ticker"], "score": r["score"],
        "ret_24h": r["ret_24h"], "delta_score": r["delta_score"]
    } for r in rows_raw])
    cats = category_summary(df_for_cats, cfg)

    chart_paths = []
    scores_path = REPORTS / "scores_latest.csv"
    if scores_path.exists():
        summary = pd.read_csv(scores_path)
        chart_paths.append(plot_scores_bar(summary, cfg))
        p = plot_category_summary(summary, cfg)
        if p: chart_paths.append(p)
    chart_paths = [p for p in chart_paths if p and p.exists()]

    date_str    = datetime.utcnow().strftime("%d/%m/%Y")
    html        = build_html(rows_raw, df_display, cats, date_str, cfg,
                             [p.name for p in chart_paths])

    out = REPORTS / f"daily_{datetime.utcnow().strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")

    email_to = os.getenv("EMAIL_TO", "")
    if email_to:
        send_email(
            f"ET-Spotter – Análise Diária {date_str}",
            html,
            [a.strip() for a in email_to.split(",")],
            images=chart_paths,
        )
    else:
        print("[EMAIL] EMAIL_TO não definido.")


if __name__ == "__main__":
    main()
