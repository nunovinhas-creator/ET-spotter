"""
Relatório diário às 19h — perspectiva de analista:
sinais de compra, rotação sectorial, tabela completa.
"""

import html as html_mod
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import (load_config, get_etfs, get_category_map, is_trading_day,
                   category_summary, build_buy_signals, build_advisor_candidates,
                   _c, _pct, _etf_row_raw, level_display)
from generate_charts import plot_scores_bar, plot_category_summary
from send_email import send_email
from paths import DATA_DAILY, REPORTS
from email_helpers import email_intro_html, email_glossary_html


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

        score      = round(float(last.get("score", 0) or 0), 3)
        score_prev = float(prev.get("score", 0) or 0)
        delta      = round(score - score_prev, 4)

        row = _etf_row_raw(sym, last, info, delta_score=delta)
        rows_raw.append(row)
        rows_display.append({
            "etf": sym, "delta_score": delta, "ret_24h": row["ret_24h"],
            "ETF":       sym,
            "Nome":      row["nome"],
            "Categoria": row["categoria"],
            "Cor":       row["cor"],
            "Score":     score,
            "Δ Score":   delta,
            "Ret. Dia":  row["ret_24h"],
            "Ret. 5d":   row["ret_5d"],
            "Ret. 3M":   row["ret_63d"],
            "Vol 21d":   row["vol_21"],
            "RSI":       round(row["rsi"], 1),
            "Trend":     "↑" if row["trend_sma"] else "↓",
            "MACD":      "+" if row["macd_bullish"] else "−",
            "RS vs SPY": "✓" if row["rs_positive"] else "✗",
        })

    if rows_display:
        df_display = pd.DataFrame(rows_display).sort_values("Score", ascending=False)
    else:
        df_display = pd.DataFrame()
    return rows_raw, df_display


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def advisor_email_html(rows_raw: list[dict]) -> str:
    candidates = build_advisor_candidates(rows_raw, top_n=3)
    if not candidates:
        return '<p style="color:#555;font-size:12px">Sem candidatos que cumpram os critérios técnicos hoje.</p>'

    medals = ["🥇", "🥈", "🥉"]
    cards = ""
    for i, r in enumerate(candidates):
        pts       = int(r.get("advisor_pts", 0))
        medal     = medals[i] if i < len(medals) else f"#{i+1}"
        bar_color = "#4caf50" if pts >= 70 else ("#ffd54f" if pts >= 50 else "#7c83fd")
        rsi       = float(r.get("rsi", 50) or 50)
        ret_252d  = float(r.get("ret_252d", 0) or 0)
        ret_126d  = float(r.get("ret_126d", 0) or 0)
        ret_21d   = float(r.get("ret_21d",  0) or 0)
        momentum  = (ret_252d - ret_21d) if ret_252d != 0 else (ret_126d - ret_21d)
        mom_label = "Mom.12-1M" if ret_252d != 0 else "Mom.6-1M"
        ticker_e  = html_mod.escape(str(r.get("ticker", "")))
        nome_e    = html_mod.escape(str(r.get("nome", "")))
        cards += f"""
        <div style="background:#13162a;border-left:4px solid {bar_color};
                    padding:12px 16px;margin:6px 0;border-radius:4px">
          <div style="margin-bottom:6px">
            <span style="font-size:16px">{medal}</span>
            <span style="color:#e8eaf6;font-size:16px;font-weight:bold;margin-left:6px">{ticker_e}</span>
            <span style="color:#666;font-size:11px;margin-left:8px">{nome_e}</span>
            <span style="background:{bar_color};color:#000;padding:1px 8px;border-radius:8px;
                         font-size:10px;font-weight:bold;margin-left:8px">{pts}/100</span>
          </div>
          <div style="font-size:11px;color:#aaa;line-height:1.8">
            <span style="color:#666">{mom_label} <span style="color:#444;font-size:10px">(retorno anual excl. último mês)</span>:</span> <b style="color:{_c(momentum)}">{_pct(momentum)}</b>
            &nbsp;·&nbsp;
            <span style="color:#666">Retorno 3M <span style="color:#444;font-size:10px">(últimos 3 meses)</span>:</span> <b style="color:{_c(r.get('ret_63d',0))}">{_pct(r.get('ret_63d',0))}</b>
            &nbsp;·&nbsp;
            <span style="color:#666">RSI <span style="color:#444;font-size:10px">(40–65 = zona saudável)</span>:</span> <b style="color:{'#4caf50' if 35<=rsi<=65 else '#ffd54f'}">{rsi:.0f}</b>
            &nbsp;·&nbsp;
            <span style="color:#666">Sharpe <span style="color:#444;font-size:10px">(retorno/risco, ≥1 é bom)</span>:</span> <b style="color:{'#4caf50' if r.get('sharpe_63',0)>=1 else '#aaa'}">{r.get('sharpe_63',0):.1f}</b>
            &nbsp;·&nbsp;
            <span style="color:#666">vs S&P 500 <span style="color:#444;font-size:10px">(supera o índice americano?)</span>:</span> <b style="color:{'#4caf50' if r.get('rs_positive') else '#f44336'}">{'✓ sim' if r.get('rs_positive') else '✗ não'}</b>
          </div>
        </div>"""

    return cards


def buy_signals_html(signals: list[dict]) -> str:
    if not signals:
        return '<p style="color:#666">Sem confluência de sinais suficiente hoje.</p>'

    cards = ""
    for s in signals:
        badge_html = (
            f'<span style="background:{s["color"]};color:#000;padding:3px 10px;'
            f'border-radius:12px;font-size:11px;font-weight:bold;'
            f'letter-spacing:0.5px">{level_display(s["level"])}</span>'
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
            f'<span style="color:#aaa">Score <span style="color:#555;font-size:10px">(0–1, mais alto = melhor)</span>:</span> '
            f'<span style="color:{_c(s["score"], 0.5)};font-weight:bold">{s["score"]:.3f}</span>'
            f'{pct_str}&nbsp;&nbsp;'
            f'<span style="color:#aaa">Retorno 3M <span style="color:#555;font-size:10px">(últimos 3 meses)</span>:</span> '
            f'<span style="color:{_c(s.get("ret_63d", 0))}">{_pct(s.get("ret_63d", 0))}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Retorno 5d <span style="color:#555;font-size:10px">(últimos 5 dias)</span>:</span> '
            f'<span style="color:{_c(s["ret_5d"])}">{_pct(s["ret_5d"])}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">RSI <span style="color:#555;font-size:10px">(40–65 = zona saudável)</span>:</span> '
            f'<span style="color:{rsi_color}">{rsi_val:.0f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">vs S&P 500 <span style="color:#555;font-size:10px">(está a superar o índice?)</span>:</span> '
            f'<span style="color:{rs_color}">{rs_icon}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Δ Score <span style="color:#555;font-size:10px">(variação face a ontem)</span>:</span> '
            f'<span style="color:{_c(s["delta_score"])}">{s["delta_score"]:+.3f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Drawdown <span style="color:#555;font-size:10px">(queda face ao máximo recente)</span>:</span> '
            f'<span style="color:{_c(s["drawdown"], -0.05)}">{_pct(s["drawdown"])}</span>'
        )
        ticker_e = html_mod.escape(str(s.get("ticker", "")))
        nome_e   = html_mod.escape(str(s.get("nome", "")))
        cat_e    = html_mod.escape(str(s.get("categoria", "")))
        rationale_e = html_mod.escape(str(s.get("rationale", "")))
        cards += f"""
        <div style="background:{s['bg']};border-left:4px solid {s['color']};
                    padding:14px 18px;margin:8px 0;border-radius:4px">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <div>
              <span style="color:#e8eaf6;font-size:19px;font-weight:bold">{ticker_e}</span>
              <span style="color:#888;font-size:11px;margin-left:8px">{nome_e}</span>
              &nbsp;{badge_html}
              <span style="color:{s['cor']};font-size:11px;margin-left:10px">● {cat_e}</span>
            </div>
          </div>
          <div style="color:#bbb;font-size:12px;margin-top:8px;line-height:1.6">
            {rationale_e}
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
            f'{c["momentum"]} {html_mod.escape(c["name"])} <span style="color:#666">({c["score_avg"]:.2f})</span>'
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
    td = "padding:4px 10px;border-bottom:1px solid #0d1021;font-size:11px;text-align:right"
    headers = "".join(f'<th style="{th}">{c}</th>' for c in cols)
    rows = ""
    for _, r in df.iterrows():
        dot = f'<span style="color:{r["Cor"]}">●</span> '
        rows += "<tr>"
        for c in cols:
            if c == "ETF":
                rows += f'<td style="{td};color:#e8eaf6;text-align:left">{dot}{html_mod.escape(str(r["ETF"]))}</td>'
            elif c == "Nome":
                rows += f'<td style="{td};color:#666;text-align:left;max-width:160px;overflow:hidden">{html_mod.escape(str(r["Nome"]))}</td>'
            elif c == "Categoria":
                rows += f'<td style="{td};color:{r["Cor"]}">{html_mod.escape(str(r["Categoria"]))}</td>'
            elif c in ("Ret. Dia", "Ret. 5d", "Ret. 3M"):
                v = r.get(c, 0); rows += f'<td style="{td};color:{_c(v)}">{_pct(v)}</td>'
            elif c == "Δ Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v)}">{v:+.3f}</td>'
            elif c == "Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v,0.5)};font-weight:bold">{v}</td>'
            elif c == "Vol 21d":
                v = r.get(c, 0); rows += f'<td style="{td};color:#e8eaf6">{_pct(v)}</td>'
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
            f'<td style="{td};color:{c["color"]};text-align:left">{html_mod.escape(c["name"])}</td>'
            f'<td style="{td};color:#666">{c["n"]}</td>'
            f'<td style="{td};color:{_c(sc,0.5)};font-weight:bold">{sc:.3f}</td>'
            f'<td style="{td};color:{_c(c["delta_avg"])}">{c["delta_avg"]:+.4f}</td>'
            f'<td style="{td};color:{mom_color};font-size:16px">{c["momentum"]}</td>'
            f'<td style="{td};color:{_c(rc)}">{_pct(rc)}</td>'
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
    adv_html    = advisor_email_html(rows_raw)
    rot_html    = sector_rotation_html(cats)
    table_html  = full_table_html(df_display)
    cat_html    = category_table_html(cats)
    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:720px;border-radius:6px;margin:6px 0"></p>'
        for n in image_names
    )

    n_strong = sum(1 for s in signals if s["level"] == "FORTE COMPRA")
    n_buy    = sum(1 for s in signals if s["level"] == "COMPRA")
    n_pot    = len(signals) - n_strong - n_buy
    n_etfs   = len(get_etfs(cfg))
    intro_html    = email_intro_html(n_strong, n_buy, n_pot, n_etfs)
    glossary_html = email_glossary_html()
    summary_line = (
        f'<span style="color:#4caf50;font-weight:bold">{n_strong} {level_display("FORTE COMPRA")}</span> · '
        f'<span style="color:#8bc34a">{n_buy} {level_display("COMPRA")}</span> · '
        f'<span style="color:#ffd54f">{n_pot} {level_display("POTENCIAL")}</span>'
        f' — de {len(df_display)} ETFs analisados'
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="background:#0f1117;color:#e8eaf6;font-family:Arial,sans-serif;
             padding:24px 28px;max-width:820px;margin:0 auto">

  <h1 style="color:#7c83fd;margin-bottom:2px;font-size:22px">ET-Spotter</h1>
  <p style="color:#555;margin-top:0;font-size:13px">{html_mod.escape(date_str)} · Análise diária · {n_etfs} ETFs monitorizados</p>

  {intro_html}

  <!-- MELHOR POSICIONADOS -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0;
              border-top:2px solid #7c83fd">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Os Melhores ETFs Hoje
    </h2>
    <p style="color:#555;font-size:11px;margin-top:-8px;margin-bottom:12px">
      Top 3 com mais indicadores alinhados. Score alto = momentum, tendência, força relativa e risco todos a apontar na mesma direcção.
    </p>
    {adv_html}
  </div>

  <!-- SINAIS DE COMPRA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Sinais de Compra
    </h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      ETFs onde vários indicadores convergem em simultâneo — sinais mais fiáveis quando aparecem em conjunto. {summary_line}
    </p>
    {sig_html}
  </div>

  <!-- ROTAÇÃO SECTORIAL -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Que Sectores Estão a Ganhar Força?</h2>
    <p style="color:#666;font-size:12px;margin-top:-8px">
      Áreas do mercado com mais ETFs em tendência positiva — útil para perceber onde o dinheiro se está a mover
    </p>
    {rot_html}
  </div>

  <!-- GRÁFICOS -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">Scores em Gráfico</h2>
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
        ordenados do melhor score para o pior
      </span>
    </h2>
    {table_html}
  </div>

  {glossary_html}

  <hr style="border-color:#1e2130;margin-top:32px">
  <p style="color:#333;font-size:10px">
    ET-Spotter · GitHub Actions · dados via yfinance ·
    Análise técnica baseada em evidência histórica. Não constitui aconselhamento financeiro.
  </p>
</body></html>"""


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    if not is_trading_day():
        from datetime import date
        print(f"[SKIP] {date.today()} não é dia de negociação (fim-de-semana ou feriado).")
        return

    cfg = load_config()
    REPORTS.mkdir(parents=True, exist_ok=True)

    rows_raw, df_display = load_rows(cfg)
    if df_display.empty:
        print("[SKIP] Sem dados.")
        return

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

    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    html     = build_html(rows_raw, df_display, cats, date_str, cfg,
                          [p.name for p in chart_paths])

    out = REPORTS / f"daily_{datetime.now(timezone.utc).strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")

    from beehiiv_subscribers import get_active_subscribers

    subscribers = get_active_subscribers()
    email_to    = os.getenv("EMAIL_TO", "")

    all_recipients = list(set(subscribers + ([email_to] if email_to else [])))

    if not all_recipients:
        print("[SKIP] Sem destinatários — EMAIL_TO vazio e sem subscritores Beehiiv")
    else:
        print(f"[INFO] A enviar para {len(all_recipients)} destinatário(s)")
        send_email(all_recipients, f"ET-Spotter – Análise Diária {date_str}", html)


if __name__ == "__main__":
    main()
