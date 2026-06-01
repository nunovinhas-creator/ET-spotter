"""
Relatório semanal — perspectiva de analista:
sinais de compra, rotação sectorial, evolução semanal, gráficos.
"""

import html as html_mod
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import (load_config, get_etfs, get_category_map,
                   category_summary, build_buy_signals, build_advisor_candidates,
                   _c, _pct, _etf_row_raw)
from generate_charts import (
    plot_scores_bar, plot_category_summary,
    plot_trend, plot_score_evolution, plot_correlation_heatmap,
)
from send_email import send_email
from paths import DATA_DAILY, REPORTS


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
        info = cmap.get(sym, {})

        score     = round(float(last.get("score", 0) or 0), 3)
        score_ini = float(first.get("score", 0) or 0)
        delta     = round(score - score_ini, 4)

        row = _etf_row_raw(sym, last, info, delta_score=delta)
        rows_raw.append(row)
        rows_display.append({
            "etf": sym, "delta_score": delta, "ret_24h": row["ret_24h"],
            "ETF":          sym,
            "Nome":         row["nome"],
            "Categoria":    row["categoria"],
            "Cor":          row["cor"],
            "Score":        score,
            "Δ Score Sem.": delta,
            "Ret. Semana":  row["ret_5d"],
            "Ret. 3M":      row["ret_63d"],
            "RSI":          round(row["rsi"], 1),
            "RS vs SPY":    "✓" if row["rs_positive"] else "✗",
            "Vol 21d":      row["vol_21"],
            "Trend":        "↑" if row["trend_sma"] else "↓",
            "MACD":         "+" if row["macd_bullish"] else "−",
            "Drawdown":     round(row["drawdown"], 4),
        })

    if rows_display:
        df_display = pd.DataFrame(rows_display).sort_values("Score", ascending=False)
    else:
        df_display = pd.DataFrame()
    return rows_raw, df_display


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def advisor_weekly_html(rows_raw: list[dict]) -> str:
    candidates = build_advisor_candidates(rows_raw, top_n=3)
    if not candidates:
        return '<p style="color:#555;font-size:12px">Sem candidatos que cumpram os critérios técnicos esta semana.</p>'

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
        ret_5d    = float(r.get("ret_5d",   0) or 0)
        momentum  = (ret_252d - ret_21d) if ret_252d != 0 else (ret_126d - ret_21d)
        mom_label = "Momentum 12-1M" if ret_252d != 0 else "Momentum 6-1M"
        sharpe    = float(r.get("sharpe_63", 0) or 0)
        adx       = float(r.get("adx", 0) or 0)
        rs_pos    = bool(r.get("rs_positive", 0))
        rs_mom    = float(r.get("rs_mom_63", 0) or 0)
        ticker_e  = html_mod.escape(str(r.get("ticker", "")))
        nome_e    = html_mod.escape(str(r.get("nome", "")))
        cat_e     = html_mod.escape(str(r.get("categoria", "")))

        if momentum >= 0.20:
            p_mom = (f"O <b>{ticker_e}</b> tem um momentum excepcional de "
                     f"{_pct(momentum)} ({mom_label}) — o tipo de força continuada "
                     f"com maior evidência histórica de persistência.")
        elif momentum >= 0.10:
            p_mom = (f"O <b>{ticker_e}</b> apresenta um momentum sólido de "
                     f"{_pct(momentum)} ({mom_label}), indicando interesse institucional continuado.")
        else:
            p_mom = (f"O <b>{ticker_e}</b> mostra momentum positivo de "
                     f"{_pct(momentum)} ({mom_label}), em tendência ascendente estabelecida.")

        if ret_5d <= -0.02:
            p_entry = (f"Recuou {_pct(ret_5d)} esta semana dentro da tendência — "
                       f"cria um ponto de entrada tecnicamente favorável.")
        elif ret_5d <= 0.02:
            p_entry = f"Consolidou esta semana ({_pct(ret_5d)}), sem pressão vendedora relevante."
        else:
            p_entry = f"Subiu {_pct(ret_5d)} esta semana com o momentum activo."

        qualities = []
        if rs_pos and rs_mom >= 0.05:
            qualities.append(f"supera o S&P 500 em +{rs_mom:.1%} de força relativa (63d)")
        elif rs_pos:
            qualities.append("supera o S&P 500 em força relativa")
        if sharpe >= 1.0:
            qualities.append(f"Sharpe de {sharpe:.1f} — retorno consistente por unidade de risco")
        if adx >= 25:
            qualities.append(f"tendência confirmada pelo ADX ({adx:.0f})")

        p_quality = (". ".join(qualities).capitalize() + ".") if qualities else ""

        nivel = "elevado" if pts >= 70 else ("bom" if pts >= 50 else "moderado")
        p_score = (f"Score técnico composto: <b style='color:{bar_color}'>{pts}/100</b> "
                   f"(alinhamento {nivel}) — momentum, tendência, força relativa e qualidade de entrada.")

        cards += f"""
        <div style="background:#13162a;border-left:4px solid {bar_color};
                    padding:14px 18px;margin:8px 0;border-radius:4px">
          <div style="margin-bottom:10px">
            <span style="font-size:18px">{medal}</span>
            <span style="color:#e8eaf6;font-size:18px;font-weight:bold;margin-left:6px">{ticker_e}</span>
            <span style="color:#888;font-size:11px;margin-left:10px">{nome_e}</span>
            <span style="color:{r['cor']};font-size:11px;margin-left:10px">● {cat_e}</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <div style="flex:1;background:#0f1117;border-radius:4px;height:6px;max-width:180px">
              <div style="width:{pts}%;background:{bar_color};border-radius:4px;height:6px"></div>
            </div>
            <span style="color:{bar_color};font-weight:bold">{pts}/100</span>
          </div>
          <div style="font-size:11px;color:#aaa;line-height:2.0;margin-bottom:10px">
            <span style="color:#555">{mom_label}:</span> <b style="color:{_c(momentum)}">{_pct(momentum)}</b>
            &nbsp;·&nbsp;
            <span style="color:#555">Ret.3M:</span> <b style="color:{_c(r.get('ret_63d',0))}">{_pct(r.get('ret_63d',0))}</b>
            &nbsp;·&nbsp;
            <span style="color:#555">Ret.Sem.:</span> <b style="color:{_c(ret_5d)}">{_pct(ret_5d)}</b>
            &nbsp;·&nbsp;
            <span style="color:#555">RSI:</span> <b style="color:{'#4caf50' if 35<=rsi<=65 else '#ffd54f'}">{rsi:.0f}</b>
            &nbsp;·&nbsp;
            <span style="color:#555">Sharpe:</span> <b style="color:{'#4caf50' if sharpe>=1 else '#aaa'}">{sharpe:.1f}</b>
            &nbsp;·&nbsp;
            <span style="color:#555">RS/SPY:</span> <b style="color:{'#4caf50' if rs_pos else '#f44336'}">{'✓' if rs_pos else '✗'}</b>
          </div>
          <div style="color:#b0bec5;font-size:12px;line-height:1.8">
            {p_mom} {p_entry} {p_quality} {p_score}
          </div>
        </div>"""

    return cards


def buy_signals_html(signals: list[dict]) -> str:
    if not signals:
        return '<p style="color:#666">Sem confluência de sinais suficiente esta semana.</p>'
    cards = ""
    for s in signals:
        badge = (
            f'<span style="background:{s["color"]};color:#000;padding:3px 10px;'
            f'border-radius:12px;font-size:11px;font-weight:bold">{s["level"]}</span>'
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
            f'<span style="color:{_c(s["score"],0.5)};font-weight:bold">{s["score"]:.3f}</span>'
            f'{pct_str}&nbsp;&nbsp;'
            f'<span style="color:#aaa">Ret. 3M:</span> '
            f'<span style="color:{_c(s.get("ret_63d", 0))}">{_pct(s.get("ret_63d", 0))}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Ret. Sem.:</span> '
            f'<span style="color:{_c(s["ret_5d"])}">{_pct(s["ret_5d"])}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">RSI:</span> '
            f'<span style="color:{rsi_color}">{rsi_val:.0f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">RS vs SPY:</span> '
            f'<span style="color:{rs_color}">{rs_icon}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Δ Semana:</span> '
            f'<span style="color:{_c(s["delta_score"])}">{s["delta_score"]:+.3f}</span>'
            f'&nbsp;&nbsp;'
            f'<span style="color:#aaa">Drawdown:</span> '
            f'<span style="color:{_c(s["drawdown"],-0.05)}">{_pct(s["drawdown"])}</span>'
        )
        ticker_e    = html_mod.escape(str(s.get("ticker", "")))
        nome_e      = html_mod.escape(str(s.get("nome", "")))
        cat_e       = html_mod.escape(str(s.get("categoria", "")))
        rationale_e = html_mod.escape(str(s.get("rationale", "")))
        cards += f"""
        <div style="background:{s['bg']};border-left:4px solid {s['color']};
                    padding:14px 18px;margin:8px 0;border-radius:4px">
          <div>
            <span style="color:#e8eaf6;font-size:19px;font-weight:bold">{ticker_e}</span>
            <span style="color:#888;font-size:11px;margin-left:8px">{nome_e}</span>
            &nbsp;{badge}
            <span style="color:{s['cor']};font-size:11px;margin-left:10px">● {cat_e}</span>
          </div>
          <div style="color:#bbb;font-size:12px;margin-top:8px;line-height:1.6">
            {rationale_e}
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
            f'{c["momentum"]} {html_mod.escape(c["name"])} '
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
    cols = ["ETF", "Nome", "Categoria", "Score", "Δ Score Sem.", "Ret. Semana", "Ret. 3M", "RSI", "RS vs SPY", "Vol 21d", "Trend", "MACD"]
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
                rows += f'<td style="{td};color:#555;text-align:left">{html_mod.escape(str(r["Nome"]))}</td>'
            elif c == "Categoria":
                rows += f'<td style="{td};color:{r["Cor"]}">{html_mod.escape(str(r["Categoria"]))}</td>'
            elif c in ("Ret. Semana", "Ret. 3M"):
                v = r.get(c, 0); rows += f'<td style="{td};color:{_c(v)}">{_pct(v)}</td>'
            elif c == "Δ Score Sem.":
                v = r[c]; rows += f'<td style="{td};color:{_c(v)}">{v:+.3f}</td>'
            elif c == "Score":
                v = r[c]; rows += f'<td style="{td};color:{_c(v,0.5)};font-weight:bold">{v}</td>'
            elif c == "Vol 21d":
                v = r.get(c, 0); rows += f'<td style="{td};color:#aaa">{_pct(v)}</td>'
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
            f'<td style="{td};color:{c["color"]};text-align:left">{html_mod.escape(c["name"])}</td>'
            f'<td style="{td};color:#555">{c["n"]}</td>'
            f'<td style="{td};color:{_c(sc,0.5)};font-weight:bold">{sc:.3f}</td>'
            f'<td style="{td};color:{_c(c["delta_avg"])}">{c["delta_avg"]:+.4f}</td>'
            f'<td style="{td};color:{mc};font-size:16px">{c["momentum"]}</td>'
            f'<td style="{td};color:{_c(rc)}">{_pct(rc)}</td>'
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
    adv_html   = advisor_weekly_html(rows_raw)
    rot_html   = sector_rotation_html(cats)
    images_html = "".join(
        f'<p><img src="cid:{n}" style="max-width:720px;border-radius:6px;margin:6px 0"></p>'
        for n in image_names
    )

    n_strong = sum(1 for s in signals if s["level"] == "FORTE COMPRA")
    n_buy    = sum(1 for s in signals if s["level"] == "COMPRA")
    n_etfs   = len(get_etfs(cfg))
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
  <p style="color:#555;margin-top:0;font-size:13px">Semana {html_mod.escape(week_str)} · {n_etfs} ETFs · sexta-feira</p>

  <!-- DECISÃO DA SEMANA — SECÇÃO PRINCIPAL -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0;
              border-top:3px solid #7c83fd">
    <h2 style="color:#7c83fd;margin-top:0;font-size:18px">
      Decisão da Semana — Melhor Posicionados
    </h2>
    <p style="color:#555;font-size:12px;margin-top:-8px;margin-bottom:16px">
      Top 3 ETFs com maior alinhamento técnico desta semana: momentum multi-período ·
      tendência confirmada · força relativa vs benchmark · qualidade de entrada.
      Baseado em critérios de análise técnica com suporte académico (Faber, Antonacci, AQR).
    </p>
    {adv_html}
    <p style="color:#333;font-size:10px;margin-top:14px">
      Análise técnica baseada em evidência histórica. Não constitui aconselhamento financeiro.
    </p>
  </div>

  <!-- SINAIS DE COMPRA -->
  <div style="background:#0d1021;border-radius:8px;padding:20px;margin:20px 0">
    <h2 style="color:#7c83fd;margin-top:0;font-size:16px">
      Sinais de Compra – Análise de Confluência
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
    try:
        df_top = pd.read_csv(DATA_DAILY / f"{top_etf}.csv", index_col=0, parse_dates=True)
        chart_paths.append(plot_trend(df_top, top_etf, df_display.iloc[0]["Nome"]))
        p = plot_score_evolution(df_top, top_etf)
        if p: chart_paths.append(p)
    except Exception as e:
        print(f"[AVISO] Gráfico de tendência indisponível para {top_etf}: {e}", file=sys.stderr)

    chart_paths = [p for p in chart_paths if p and p.exists()]

    now = datetime.now(timezone.utc)
    week_str = (
        f"{(now - timedelta(days=7)).strftime('%d/%m')} – "
        f"{now.strftime('%d/%m/%Y')}"
    )
    html = build_html(rows_raw, df_display, cats, week_str, cfg,
                      [p.name for p in chart_paths])

    out = REPORTS / f"weekly_{now.strftime('%Y%m%d')}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] {out.name}")

    email_to = os.getenv("EMAIL_TO", "")
    if email_to:
        send_email(
            f"ET-Spotter – Análise Semanal {now.strftime('%d %b %Y')}",
            html,
            [a.strip() for a in email_to.split(",")],
            images=chart_paths,
        )
    else:
        print("[EMAIL] EMAIL_TO não definido.")


if __name__ == "__main__":
    main()
