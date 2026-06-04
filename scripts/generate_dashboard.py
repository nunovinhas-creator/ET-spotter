"""
Gera data/reports/dashboard.html — dashboard visual permanentemente actualizado.

Lê: scores_latest.csv, scores_history.csv, backtest_signals.csv (opcional), SPY diário.
Produz: HTML auto-suficiente com Chart.js (CDN), tabela ordenável/pesquisável, sparklines.
"""

import html as html_mod
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_category_map, build_buy_signals, category_summary, compute_advisor_score, build_advisor_candidates, _pct, _etf_row_raw, get_etf_metadata
from paths import DATA_DAILY, REPORTS, SCORES_HIST, PORTFOLIO
from constants import (
    CONVICTION_STRONG_BUY_SCORE, CONVICTION_STRONG_BUY_SIGNALS,
    CONVICTION_BUY_SCORE,        CONVICTION_BUY_SIGNALS,
    CONVICTION_POTENTIAL_SCORE,  CONVICTION_POTENTIAL_SIGNALS,
)


# ── Carrega dados ─────────────────────────────────────────────────────────────

def load_data(cfg: dict) -> dict:
    cmap = get_category_map(cfg)

    # scores actuais
    scores_path = REPORTS / "scores_latest.csv"
    if not scores_path.exists():
        return {}
    scores_df = pd.read_csv(scores_path)

    # SPY para regime
    spy_regime = "DESCONHECIDO"
    spy_close = spy_sma200 = None
    spy_path = DATA_DAILY / "SPY.csv"
    if spy_path.exists():
        spy_df = pd.read_csv(spy_path, index_col=0, parse_dates=True)
        if not spy_df.empty and "close" in spy_df.columns:
            spy_close  = float(spy_df["close"].iloc[-1])
            sma_series = spy_df["close"].rolling(200).mean()
            spy_sma200 = float(sma_series.iloc[-1]) if not sma_series.empty else None
            if spy_sma200 and spy_close:
                spy_regime = "BULL" if spy_close > spy_sma200 else "BEAR"

    # histórico para sparklines (últimos 30 dias)
    hist_df = pd.DataFrame()
    if SCORES_HIST.exists():
        hist_df = pd.read_csv(SCORES_HIST, parse_dates=["date"])
        if not hist_df.empty:
            cutoff = hist_df["date"].max() - pd.Timedelta(days=30)
            hist_df = hist_df[hist_df["date"] >= cutoff]

    # backtest (opcional)
    bt_path = REPORTS / "backtest_signals.csv"
    bt_df = pd.read_csv(bt_path) if bt_path.exists() else pd.DataFrame()

    # delta_score: day-over-day change per ETF from history
    delta_map: dict[str, float] = {}
    if not hist_df.empty and "score" in hist_df.columns and "etf" in hist_df.columns:
        for etf_sym, grp in hist_df.groupby("etf"):
            grp_sorted = grp.sort_values("date")
            if len(grp_sorted) >= 2:
                prev = float(grp_sorted["score"].iloc[-2] or 0)
                curr = float(grp_sorted["score"].iloc[-1] or 0)
                delta_map[str(etf_sym)] = round(curr - prev, 4)

    # rows completos para build_buy_signals
    rows_raw = [
        _etf_row_raw(str(r.get("etf", "")), r, cmap.get(str(r.get("etf", "")), {}), delta_map.get(str(r.get("etf", "")), 0.0))
        for r in scores_df.to_dict("records")
    ]

    df_for_cats = pd.DataFrame([{
        "etf": r["ticker"], "score": r["score"],
        "ret_24h": r.get("ret_21d", 0) / 21,
        "delta_score": r["delta_score"],
    } for r in rows_raw])
    cats = category_summary(df_for_cats, cfg)

    return {
        "scores_df":  scores_df,
        "rows_raw":   rows_raw,
        "cats":       cats,
        "hist_df":    hist_df,
        "bt_df":      bt_df,
        "cmap":       cmap,
        "spy_close":  spy_close,
        "spy_sma200": spy_sma200,
        "spy_regime": spy_regime,
    }


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _c(v: float, neutral: float = 0) -> str:
    return "var(--green)" if v >= neutral else "var(--red)"


def _num(v, digits=3) -> str:
    return f"{v:.{digits}f}" if pd.notna(v) else "—"


# ── Brand banner (inline SVG — self-contained, no external asset needed) ─────

BRAND_BANNER_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 160" width="100%" style="display:block">
  <defs>
    <linearGradient id="bb_fade" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"   stop-color="#7c83fd" stop-opacity="0"/>
      <stop offset="20%"  stop-color="#7c83fd" stop-opacity="1"/>
      <stop offset="80%"  stop-color="#7c83fd" stop-opacity="1"/>
      <stop offset="100%" stop-color="#7c83fd" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="bb_rule" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"   stop-color="#ffffff" stop-opacity="0"/>
      <stop offset="35%"  stop-color="#ffffff" stop-opacity="0.05"/>
      <stop offset="65%"  stop-color="#ffffff" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="160" fill="#000000"/>
  <rect x="0" y="0" width="1280" height="2" fill="url(#bb_fade)"/>
  <line x1="120" y1="30" x2="120" y2="130" stroke="#ffffff" stroke-width="0.5" opacity="0.04"/>
  <line x1="1160" y1="30" x2="1160" y2="130" stroke="#ffffff" stroke-width="0.5" opacity="0.04"/>
  <text x="640" y="96"
    font-family="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',Arial,sans-serif"
    font-size="72" font-weight="800" fill="#ffffff" text-anchor="middle" letter-spacing="-4">ET-SPOTTER</text>
  <text x="640" y="124"
    font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif"
    font-size="11" font-weight="400" fill="#7c83fd" text-anchor="middle" letter-spacing="7">
    QUANTITATIVE ETF ANALYSIS · AUTOMATED · OPEN SOURCE
  </text>
  <rect x="0" y="142" width="1280" height="1" fill="url(#bb_rule)"/>
  <text x="640" y="156"
    font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif"
    font-size="9" font-weight="400" fill="#1e1e1e" text-anchor="middle" letter-spacing="3">
    97 ETFs UCITS · GITHUB ACTIONS · YFINANCE · MIT LICENSE
  </text>
</svg>"""


def brand_banner_section_html() -> str:
    """Inline brand banner — exibido no fundo do dashboard antes do footer."""
    return f"""
<div style="margin:24px 0 0;border-top:1px solid var(--border);overflow:hidden;border-radius:0 0 2px 2px">
  {BRAND_BANNER_SVG}
</div>"""


# ── Sections ──────────────────────────────────────────────────────────────────

def header_html(spy_close, spy_sma200, spy_regime, ts, n_etfs: int = 0) -> str:
    regime_color = "var(--green)" if spy_regime == "BULL" else ("var(--red)" if spy_regime == "BEAR" else "var(--muted)")
    spy_price = f"{spy_close:.2f}" if spy_close else "—"
    sma_price = f"{spy_sma200:.2f}" if spy_sma200 else "—"
    arrow = ">" if spy_regime == "BULL" else "<"
    regime_tip = (
        f"Regime de mercado americano: SPY {spy_price} {arrow} SMA200 {sma_price}. "
        f"BULL = S&P 500 acima da média de 200 dias (tendência de alta). "
        f"BEAR = abaixo (tendência de baixa). "
        f"O dashboard usa isto para contextualizar os sinais."
    )
    regime_badge = (
        f'<span title="{regime_tip}" style="background:{regime_color};color:#000;padding:2px 8px;'
        f'border-radius:2px;font-size:11px;font-weight:bold;cursor:help">{spy_regime}</span>'
    )
    return f"""
<div class="top-accent"></div>
<header>
  <div class="header-inner">
    <div>
      <div class="logo">ET-SPOTTER</div>
      <div class="subtitle">Monitorização automática de ETFs UCITS · score técnico composto (0–1)</div>
      <div style="color:var(--muted);font-size:10px;margin-top:3px;letter-spacing:0.04em">{n_etfs} ETFs · momentum · tendência · risco · alpha</div>
    </div>
    <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:8px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end">
        {regime_badge}
      </div>
      <div style="color:var(--muted);font-size:11px;display:flex;align-items:center">
        <span class="live-dot"></span>Actualizado: {ts}
      </div>
    </div>
  </div>
</header>"""


def hero_bar_html(n_etfs: int = 97, n_total: int = 97) -> str:
    """Stat strip — visual branding bar with key project numbers."""
    etf_label = "ETFs UCITS"
    etf_sub   = f"de {n_total} no universo" if n_etfs != n_total else "ETFs UCITS"
    items = ""
    stats = [
        (str(n_etfs), etf_label, etf_sub, "var(--green)",        f"{n_etfs} de {n_total} ETFs com dados suficientes hoje"),
        ("4",         "Factores", "momentum·trend·risco·alpha", "#7c83fd", "Momentum 35% · Tendência 25% · Risco 25% · Alpha 15%"),
        ("22h",       "Diário",   "actualização EOD",  "var(--yellow)", "Dados de fecho actualizados todos os dias às 22h UTC"),
        ("€0",        "Custo",    "infra-estrutura",   "var(--green)",  "GitHub Actions free tier · yfinance · zero servidores"),
        ("~3min",     "Pipeline", "do fetch ao email", "oklch(70% 0.12 230)", "Pipeline completo em ~3 minutos por GitHub Actions"),
    ]
    for i, (val, label, sub, color, tip) in enumerate(stats):
        if i > 0:
            items += '<div class="stat-div"></div>'
        items += (
            f'<div class="stat-item" title="{tip}">'
            f'<span style="color:{color};font-size:22px;font-weight:700;font-family:\'Albert Sans\',sans-serif;line-height:1">{val}</span>'
            f'<span style="color:var(--muted);font-size:0.58rem;letter-spacing:0.10em;text-transform:uppercase;margin-top:4px">{label}</span>'
            f'<span style="color:var(--border);font-size:0.52rem;margin-top:1px;letter-spacing:0.04em">{sub}</span>'
            f'</div>'
        )
    return f'<div class="stat-bar">{items}</div>'


def cta_strip_html() -> str:
    """Faixa de CTA — converte visitantes em utilizadores."""
    return """
<div class="cta-strip">
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
    <span style="color:var(--green);font-size:14px">●</span>
    <span style="color:var(--text);font-size:0.78rem;font-weight:500">Receber este relatório por email todos os dias às 22h</span>
    <span style="color:var(--muted);font-size:0.72rem">— grátis, sem servidores, sem subscrição</span>
  </div>
  <a href="https://github.com/nunovinhas-creator/ET-spotter/fork" target="_blank" rel="noopener"
     class="gh-btn" style="white-space:nowrap;border-color:var(--green);color:var(--green)">
    🍴 Fork e configura em 3 minutos
  </a>
</div>"""


def signal_legend_html(n_etfs: int = 0) -> str:
    """Mini-legenda de sinais — sempre visível, dá contexto antes dos cards."""
    ctx = f"de {n_etfs} ETFs analisados hoje:" if n_etfs else ""
    return f"""
<div class="signal-legend">
  <span style="color:var(--muted);font-size:0.68rem">{ctx}</span>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <span style="background:var(--green);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">FORTE COMPRA</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ 0.75</span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <span style="background:var(--light-green);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">COMPRA</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ 0.55</span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <span style="background:var(--yellow);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">POTENCIAL</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ 0.40</span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <a href="#" onclick="document.getElementById('explainer-details').open=true;document.getElementById('explainer-details').scrollIntoView({{behavior:'smooth'}});return false;"
       style="color:var(--patina);font-size:0.65rem;text-decoration:none">📖 guia completo ↓</a>
  </div>
</div>"""


def summary_cards_html(signals: list[dict], scores_df: pd.DataFrame) -> str:
    n_fc  = sum(1 for s in signals if s["level"] == "FORTE COMPRA")
    n_c   = sum(1 for s in signals if s["level"] == "COMPRA")
    n_p   = sum(1 for s in signals if s["level"] == "POTENCIAL")
    n_high = int((scores_df["score"] >= 0.50).sum()) if "score" in scores_df.columns else 0
    avg_score = scores_df["score"].mean() if "score" in scores_df.columns else 0

    def card(label, value, color, sub=""):
        return f"""
        <div class="card" style="border-top:1px solid {color}">
          <div style="font-size:26px;font-weight:600;font-family:'Albert Sans',sans-serif;color:{color}">{value}</div>
          <div style="font-family:'SFMono-Regular','Roboto Mono',Consolas,monospace;font-size:0.62rem;letter-spacing:0.14em;text-transform:uppercase;color:var(--muted);margin-top:6px">{label}</div>
          {f'<div style="color:var(--muted);font-size:10px;margin-top:2px">{sub}</div>' if sub else ""}
        </div>"""

    legend = (
        '<span style="color:var(--green)">&#9679;</span> score&nbsp;≥&nbsp;0.75 &nbsp;·&nbsp;'
        '<span style="color:var(--light-green)">&#9679;</span> score&nbsp;≥&nbsp;0.55 &nbsp;·&nbsp;'
        '<span style="color:var(--yellow)">&#9679;</span> score&nbsp;≥&nbsp;0.40 &nbsp;·&nbsp;'
        'confluência de momentum, tendência e risco'
    )
    return f"""
<section class="summary-grid">
  {card("FORTE COMPRA",   n_fc,  "var(--green)")}
  {card("COMPRA",         n_c,   "var(--light-green)")}
  {card("POTENCIAL",      n_p,   "var(--yellow)")}
  {card("Score > 0.50",   n_high,"var(--blue)", f"de {len(scores_df)} ETFs")}
  {card("Score médio",    f"{avg_score:.3f}", "var(--blue-light)")}
</section>
<div style="padding:6px 0 14px;color:var(--muted);font-size:0.62rem;letter-spacing:0.03em;opacity:0.7">
  {legend}
</div>"""


def explainer_section() -> str:
    """Painel colapsável 'Como ler este dashboard' para utilizadores sem experiência técnica."""
    return """
<details id="explainer-details" style="margin-bottom:16px;border:1px solid var(--border);border-radius:2px;background:var(--surface)">
  <summary style="padding:10px 16px;cursor:pointer;list-style:none;display:flex;
                  justify-content:space-between;align-items:center;user-select:none">
    <span style="color:var(--text);font-size:0.75rem;font-weight:600;letter-spacing:0.04em">
      📖 Novo aqui? Guia completo — o que é um ETF, como ler o score, glossário
    </span>
    <span style="color:var(--muted);font-size:0.70rem">clica para expandir</span>
  </summary>

  <div style="padding:0 16px 16px;display:flex;flex-direction:column;gap:18px">

    <!-- O que é um ETF -->
    <div>
      <div style="color:var(--patina);font-size:0.62rem;font-weight:bold;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px">O que é um ETF?</div>
      <p style="color:var(--muted);font-size:0.72rem;line-height:1.7;margin:0">
        Um ETF (fundo negociado em bolsa) funciona como um cabaz de ações: em vez de comprares uma
        empresa, compras um fundo que replica centenas de empresas ao mesmo tempo.
        É diversificado, barato e compra-se como uma ação normal. Os ETFs desta ferramenta
        são todos <b style="color:var(--text)">UCITS</b> — regulados para investidores europeus.
      </p>
    </div>

    <!-- Score técnico -->
    <div>
      <div style="color:var(--patina);font-size:0.62rem;font-weight:bold;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px">O que é o Score Técnico (0–1)?</div>
      <p style="color:var(--muted);font-size:0.72rem;line-height:1.7;margin:0 0 8px">
        É um número calculado automaticamente que resume o estado técnico de cada ETF
        numa escala de 0 a 1. Quanto mais próximo de 1, mais indicadores apontam para
        uma fase positiva. <b style="color:var(--text)">Não é uma previsão</b> — é uma fotografia do momento actual.
      </p>
      <div style="display:flex;flex-direction:column;gap:5px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--green);color:#000;font-size:0.60rem;font-weight:bold;
                       padding:2px 8px;border-radius:2px;white-space:nowrap">FORTE COMPRA</span>
          <span style="color:var(--muted);font-size:0.70rem">Score ≥ 0.75 — vários indicadores alinhados, momentum forte</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--light-green);color:#000;font-size:0.60rem;font-weight:bold;
                       padding:2px 8px;border-radius:2px;white-space:nowrap">COMPRA</span>
          <span style="color:var(--muted);font-size:0.70rem">Score ≥ 0.55 — maioria dos indicadores positivos, fase construtiva</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--yellow);color:#000;font-size:0.60rem;font-weight:bold;
                       padding:2px 8px;border-radius:2px;white-space:nowrap">POTENCIAL</span>
          <span style="color:var(--muted);font-size:0.70rem">Score ≥ 0.40 — alguns sinais positivos, aguardar confirmação</span>
        </div>
      </div>
    </div>

    <!-- Sub-scores -->
    <div>
      <div style="color:var(--patina);font-size:0.62rem;font-weight:bold;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px">Os 4 componentes do score</div>
      <div style="display:flex;flex-direction:column;gap:7px">
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--green);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">M</span>
          <div>
            <span style="color:var(--text);font-size:0.72rem;font-weight:600">Momentum</span>
            <span style="color:var(--muted);font-size:0.70rem"> — O ETF tem estado a subir nos últimos 1, 3 e 6 meses?
            Momentum forte significa que a tendência de alta se mantém no tempo.</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:#7c83fd;font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">T</span>
          <div>
            <span style="color:var(--text);font-size:0.72rem;font-weight:600">Tendência</span>
            <span style="color:var(--muted);font-size:0.70rem"> — O preço está acima das médias de curto e longo prazo?
            O MACD (indicador de força da tendência) é positivo?</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--blue-light);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">R</span>
          <div>
            <span style="color:var(--text);font-size:0.72rem;font-weight:600">Risco</span>
            <span style="color:var(--muted);font-size:0.70rem"> — A volatilidade está controlada? A queda face ao máximo
            (drawdown) é pequena? O retorno compensa o risco assumido?</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--yellow);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">α</span>
          <div>
            <span style="color:var(--text);font-size:0.72rem;font-weight:600">Alpha</span>
            <span style="color:var(--muted);font-size:0.70rem"> — O ETF está a superar o S&amp;P 500?
            O momentum está a acelerar? Mede a qualidade e consistência do desempenho.</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Glossário -->
    <div>
      <div style="color:var(--patina);font-size:0.62rem;font-weight:bold;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px">Glossário de termos</div>
      <div style="display:flex;flex-direction:column;gap:6px">
        <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline">
          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">SMA200</span>
          <span style="color:var(--muted);font-size:0.70rem">Média dos últimos 200 dias de fecho.
            Acima = tendência de alta. Abaixo = tendência de baixa. Uma das linhas de referência mais usadas no mundo.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RSI</span>
          <span style="color:var(--muted);font-size:0.70rem">Mede se o ETF está "caro" tecnicamente (RSI &gt; 70, possível
            pausa) ou "barato" (RSI &lt; 30, possível recuperação). Entre 40–65 é zona neutra saudável.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">ADX</span>
          <span style="color:var(--muted);font-size:0.70rem">Força da tendência. Acima de 25 significa que existe
            uma tendência clara (para cima ou para baixo). Abaixo de 20 é mercado sem direcção.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Drawdown</span>
          <span style="color:var(--muted);font-size:0.70rem">Quanto o ETF caiu face ao seu máximo mais recente.
            Ex: −8% significa que está 8% abaixo do pico. Drawdown pequeno = boa gestão do risco.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">BULL / BEAR</span>
          <span style="color:var(--muted);font-size:0.70rem">Indica se o mercado americano (SPY) está em fase de alta
            (BULL, acima da SMA200) ou de baixa (BEAR, abaixo). Em regime BEAR os sinais são lidos com mais cautela.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RS/SPY</span>
          <span style="color:var(--muted);font-size:0.70rem">Força Relativa face ao S&amp;P 500.
            ✓ significa que o ETF está a superar o índice americano — sinal positivo de liderança.</span>

          <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Sharpe</span>
          <span style="color:var(--muted);font-size:0.70rem">Retorno dividido pelo risco. Um Sharpe de 1.0 ou mais
            significa que o ETF está a gerar retorno razoável para o risco que implica.</span>
        </div>
      </div>
    </div>

    <p style="color:var(--muted);font-size:0.65rem;font-style:italic;margin:0;border-top:1px solid var(--border);padding-top:10px">
      Esta ferramenta é para investigação técnica. Não constitui aconselhamento financeiro.
      Consulta sempre um profissional antes de investir.
    </p>
  </div>
</details>"""


def _nome_curto(s: dict) -> str:
    """Extrai o nome curto do ETF removendo o provider entre parênteses."""
    nome = s.get("nome", s.get("ticker", "Este ETF"))
    curto = nome.split("(")[0].strip()
    return curto if curto else s.get("ticker", "Este ETF")


def narrativa_simples(s: dict) -> str:
    """Gera um parágrafo humanizado em PT-PT explicando o sinal de compra."""
    nome    = _nome_curto(s)
    ret_63d = float(s.get("ret_63d", 0) or 0)
    ret_5d  = float(s.get("ret_5d",  0) or 0)
    rsi     = float(s.get("rsi",    50) or 50)
    rs_pos  = bool(s.get("rs_positive", 0))

    # ── Parte 1: desempenho a médio prazo (3 meses) ───────────────────────────
    if abs(ret_63d) < 0.01:
        p1 = f"O {nome} está a consolidar sem movimento expressivo nos últimos 3 meses"
    elif ret_63d >= 0.10:
        p1 = f"O {nome} está com uma força notável a médio prazo ({ret_63d:+.1%} nos últimos 3 meses)"
    elif ret_63d >= 0.03:
        p1 = f"O {nome} tem vindo a ganhar terreno nos últimos 3 meses ({ret_63d:+.1%})"
    elif ret_63d >= 0:
        p1 = f"O {nome} regista uma valorização modesta nos últimos 3 meses ({ret_63d:+.1%})"
    else:
        p1 = f"O {nome} está em fase de recuperação após um período mais fraco ({ret_63d:+.1%} nos últimos 3 meses)"

    # ── Parte 2: comportamento semanal (5d) ────────────────────────────────────
    if ret_5d <= -0.05:
        p2 = f"No entanto, recuou {ret_5d:+.1%} esta semana — uma queda que criou um desconto técnico relevante face aos máximos recentes"
    elif ret_5d <= -0.02:
        p2 = f"No entanto, deu um passo atrás de {ret_5d:+.1%} esta semana — um respiro saudável que abre janela de entrada"
    elif ret_5d < 0:
        p2 = f"A ligeira correção de {ret_5d:+.1%} esta semana afastou o preço de zonas mais caras"
    elif ret_5d <= 0.01:
        p2 = f"Esta semana manteve-se estável, a consolidar ganhos sem pressão de venda"
    elif ret_5d <= 0.04:
        p2 = f"Subiu {ret_5d:+.1%} esta semana, com o momentum a ganhar tração"
    else:
        p2 = f"Acelerou {ret_5d:+.1%} esta semana — atenção porque entradas após subidas rápidas exigem mais cautela"

    # ── Parte 3: RSI (tradução para linguagem comum) ──────────────────────────
    if rsi < 35:
        p3 = f"O indicador de força RSI ({rsi:.0f}) está em zona de sobre-venda, o que pode sinalizar uma inversão próxima"
    elif rsi <= 50:
        p3 = f"O indicador de força RSI ({rsi:.0f}) mostra que o preço saiu de zonas caras e está num ponto de entrada tecnicamente ideal — como se estivesse 'em promoção'"
    elif rsi <= 62:
        p3 = f"O RSI ({rsi:.0f}) mantém-se em zona equilibrada, sem sinais de sobrecompra excessiva"
    elif rsi <= 68:
        p3 = f"O RSI ({rsi:.0f}) está a aquecer, mas ainda dentro de margens aceitáveis"
    else:
        p3 = f"O RSI ({rsi:.0f}) já em zona quente — os restantes indicadores suportam a tese, mas uma pequena espera pode melhorar o ponto de entrada"

    # ── Encerramento: força relativa vs mercado ───────────────────────────────
    if rs_pos:
        fecho = ", estando inclusivamente a superar o mercado americano em geral no mesmo período."
    else:
        fecho = "."

    return f"{p1}. {p2}. {p3}{fecho}"


def _sub_bars_html(r: dict) -> str:
    """Breakdown visual dos 4 sub-scores: M / T / R / α."""
    mom = r.get("_momentum")
    trd = r.get("_trend")
    rsk = r.get("_risk")
    alp = r.get("_alpha")
    if None in (mom, trd, rsk, alp):
        return ""

    def bar(label, name, val, color):
        pct = round(val * 100)
        return (
            f'<div style="display:flex;align-items:center;gap:7px">'
            f'<span style="color:{color};font-size:10px;font-weight:bold;width:80px;flex-shrink:0">'
            f'{label} <span style="color:var(--muted);font-weight:normal">{name}</span></span>'
            f'<div style="flex:1;background:var(--border);border-radius:3px;height:5px;overflow:hidden">'
            f'<div style="width:{pct}%;background:{color};border-radius:3px;height:5px"></div>'
            f'</div>'
            f'<span style="color:var(--muted);font-size:10px;width:30px;text-align:right;flex-shrink:0">{val:.2f}</span>'
            f'</div>'
        )

    return (
        '<div style="display:flex;flex-direction:column;gap:5px;margin-bottom:10px">'
        + bar("M", "Momentum",   mom, "var(--green)")
        + bar("T", "Tendência",  trd, "#7c83fd")
        + bar("R", "Risco",      rsk, "var(--blue-light)")
        + bar("α", "Alpha",      alp, "var(--yellow)")
        + '</div>'
    )


def narrativa_advisor(r: dict) -> str:
    """Explicação em português simples do porquê este ETF está bem posicionado."""
    nome      = _nome_curto(r)
    ret_252d  = float(r.get("ret_252d",  0) or 0)
    ret_126d  = float(r.get("ret_126d",  0) or 0)
    ret_21d   = float(r.get("ret_21d",   0) or 0)
    ret_5d    = float(r.get("ret_5d",    0) or 0)
    rsi       = float(r.get("rsi",      50) or 50)
    adx       = float(r.get("adx",       0) or 0)
    rs_pos    = bool(r.get("rs_positive", 0))
    sharpe    = float(r.get("sharpe_63", 0) or 0)
    pts       = int(r.get("advisor_pts", 0))

    # Momentum principal: 12-1M ou 6-1M
    momentum = (ret_252d - ret_21d) if ret_252d != 0 else (ret_126d - ret_21d)
    ref_period = "12" if ret_252d != 0 else "6"

    if momentum >= 0.25:
        p1 = (f"O {nome} tem um momentum de {ref_period} meses excepcionalmente forte "
              f"({momentum:+.1%} excluindo o ruído do último mês) — o tipo de força "
              f"continuada que os estudos académicos identificam como o preditor técnico mais robusto.")
    elif momentum >= 0.12:
        p1 = (f"O {nome} apresenta um momentum sólido de {ref_period} meses ({momentum:+.1%}), "
              f"o que indica que os investidores institucionais continuam a comprar. "
              f"Este factor é o que tem mais evidência histórica de continuação.")
    else:
        p1 = (f"O {nome} mostra um momentum positivo de {ref_period} meses ({momentum:+.1%}), "
              f"suficiente para ser considerado em tendência ascendente estabelecida.")

    # Timing de entrada
    if ret_5d <= -0.03:
        p2 = (f"Esta semana corrigiu {ret_5d:+.1%} dentro de uma tendência de alta — "
              f"tecnicamente o melhor cenário: o activo 'respira' sem quebrar a estrutura. "
              f"Historicamente, pullbacks neste contexto criam pontos de entrada favoráveis.")
    elif ret_5d <= 0.01:
        p2 = (f"Está a consolidar esta semana ({ret_5d:+.1%}), o que é normal após um período de força. "
              f"A ausência de pressão vendedora nesta fase é um sinal de acumulação.")
    else:
        p2 = (f"Subiu {ret_5d:+.1%} esta semana — o momentum está activo. "
              f"O RSI ({rsi:.0f}) ainda não está em zona de sobrecompra extrema.")

    # Qualidade técnica
    parts = []
    if rs_pos:
        parts.append("supera o S&P 500 em força relativa")
    if adx >= 25:
        parts.append(f"tendência confirmada pelo ADX ({adx:.0f})")
    if sharpe >= 1.0:
        parts.append(f"Sharpe de {sharpe:.1f} — retorno consistente por unidade de risco")

    p3_base = ". ".join(parts).capitalize() + "." if parts else ""

    nivel = "elevado" if pts >= 70 else ("bom" if pts >= 50 else "moderado")
    p3 = (f"{p3_base} Score técnico composto: {pts}/100 (alinhamento {nivel}) — "
          f"baseado em momentum multi-período, regime de tendência, força relativa e qualidade de entrada.")

    return f"{p1} {p2} {p3}"


def advisor_section(rows_raw: list[dict]) -> str:
    candidates = build_advisor_candidates(rows_raw, top_n=3)
    if not candidates:
        return ""

    medals = ["🥇", "🥈", "🥉"]
    cards = ""
    for i, r in enumerate(candidates):
        pts       = int(r.get("advisor_pts", 0))
        medal     = medals[i] if i < 3 else f"#{i+1}"
        rsi       = float(r.get("rsi", 50) or 50)
        bar_color      = "var(--green)"  if pts >= 70 else ("var(--yellow)" if pts >= 50 else "var(--muted)")
        bar_border_clr = "oklch(48% 0.09 188)" if pts >= 70 else ("oklch(48% 0.12 80)" if pts >= 50 else "var(--border)")

        ret_252d = float(r.get("ret_252d", 0) or 0)
        ret_126d = float(r.get("ret_126d", 0) or 0)
        momentum = (ret_252d - float(r.get("ret_21d", 0) or 0)) if ret_252d != 0 else (ret_126d - float(r.get("ret_21d", 0) or 0))
        mom_label = "Mom.12-1M" if ret_252d != 0 else "Mom.6-1M"

        advisor_forte = ' class="signal-forte"' if i == 0 and pts >= 70 else ""
        cards += f"""
        <div{advisor_forte} style="background:var(--bg);border:1px solid {bar_border_clr};padding:14px 16px;
                    margin:8px 0;border-radius:2px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
            <span style="font-size:18px">{medal}</span>
            <span style="color:var(--text);font-size:16px;font-weight:bold">{html_mod.escape(r['ticker'])}</span>
            <span style="color:var(--muted);font-size:11px">{html_mod.escape(r['nome'])}</span>
            <span style="color:{r['cor']};font-size:10px">● {html_mod.escape(r['categoria'])}</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <span style="color:var(--muted);font-size:11px">Score técnico</span>
            <div style="flex:1;background:var(--border);border-radius:4px;height:7px;max-width:200px">
              <div style="width:{pts}%;background:{bar_color};border-radius:4px;height:7px"></div>
            </div>
            <span style="color:{bar_color};font-weight:bold;font-size:13px">{pts}/100</span>
          </div>
          {_sub_bars_html(r)}
          <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:11px;margin-bottom:10px">
            <span><span style="color:var(--muted)">{mom_label}</span> <b style="color:{'var(--green)' if momentum>=0 else 'var(--red)'}">{_pct(momentum)}</b></span>
            <span><span style="color:var(--muted)">Ret.3M</span> <b style="color:{'var(--green)' if r.get('ret_63d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_63d',0))}</b></span>
            <span><span style="color:var(--muted)">Ret.5d</span> <b style="color:{'var(--green)' if r.get('ret_5d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_5d',0))}</b></span>
            <span><span style="color:var(--muted)">RSI</span> <b style="color:{'var(--green)' if 35<=rsi<=65 else 'var(--yellow)'}">{rsi:.0f}</b></span>
            <span><span style="color:var(--muted)">ADX</span> <b style="color:{'var(--green)' if r.get('adx',0)>=25 else 'var(--muted)'}">{r.get('adx',0):.0f}</b></span>
            <span><span style="color:var(--muted)">Sharpe</span> <b style="color:{'var(--green)' if r.get('sharpe_63',0)>=1 else 'var(--muted)'}">{r.get('sharpe_63',0):.1f}</b></span>
            <span><span style="color:var(--muted)">RS/SPY</span> <b style="color:{'var(--green)' if r.get('rs_positive') else 'var(--red)'}">{'✓' if r.get('rs_positive') else '✗'}</b></span>
          </div>
          <div style="color:var(--border);font-size:0.58rem;letter-spacing:0.08em;margin-bottom:2px">ANÁLISE GERADA AUTOMATICAMENTE · NÃO CONSTITUI ACONSELHAMENTO FINANCEIRO</div>
          <p style="color:var(--muted);font-size:11px;line-height:1.7;font-style:italic">{narrativa_advisor(r)}</p>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title">Melhor Posicionados — Análise Técnica Consolidada</h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:10px">
    Top 3 ETFs com maior alinhamento de momentum multi-período, tendência e força relativa.
    Baseado em critérios académicos: Jegadeesh &amp; Titman (1993), Faber (2007), Antonacci (2014), Ang et al. (2006), Kakushadze alpha101.
  </p>
  {cards}
  <p style="color:var(--muted);font-size:10px;margin-top:12px;font-style:italic">
    Análise técnica baseada em evidência histórica. Não constitui aconselhamento financeiro nem garantia de retorno.
  </p>
</section>"""


def buy_signals_section(signals: list[dict]) -> str:
    if not signals:
        return '<section class="section"><p style="color:var(--muted)">Sem confluência de sinais suficiente.</p></section>'

    cards = ""
    for s in signals:
        level_colors = {
            "FORTE COMPRA": ("var(--green)",       "oklch(13% 0.045 188)", "oklch(48% 0.09 188)"),
            "COMPRA":       ("var(--light-green)", "oklch(12% 0.025 188)", "oklch(38% 0.08 188)"),
            "POTENCIAL":    ("var(--yellow)",       "oklch(13% 0.04 80)",   "oklch(48% 0.12 80)"),
        }
        clr, bg, border_clr = level_colors.get(s["level"], ("var(--muted)", "var(--bg)", "var(--border)"))
        pct = s.get("score_pct")
        pct_html = (
            f'<span style="color:var(--muted);font-size:10px">P{pct*100:.0f}</span>'
            if pct is not None and str(pct) != "nan" else ""
        )
        rsi = s.get("rsi", 50) or 50
        rsi_c = "var(--green)" if 40 <= rsi <= 65 else ("var(--yellow)" if rsi > 70 else "var(--red)" if rsi < 35 else "var(--muted)")

        forte_class = ' class="signal-forte"' if s["level"] == "FORTE COMPRA" else ""
        cards += f"""
        <div{forte_class} style="background:{bg};border:1px solid {border_clr};padding:12px 16px;margin:6px 0;border-radius:2px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="color:var(--text);font-size:17px;font-weight:bold">{html_mod.escape(s['ticker'])}</span>
            <span style="color:var(--muted);font-size:11px">{html_mod.escape(s['nome'])}</span>
            <span style="background:{clr};color:#000;padding:1px 8px;border-radius:2px;font-size:10px;font-weight:bold">{s['level']}</span>
            <span style="color:{s['cor']};font-size:10px">● {html_mod.escape(s['categoria'])}</span>
          </div>
          <div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap;font-size:11px">
            <span><span style="color:var(--muted)">Score</span> <b style="color:{clr}">{s['score']:.3f}</b> {pct_html}</span>
            <span><span style="color:var(--muted)">Ret.3M</span> <b style="color:{'var(--green)' if s.get('ret_63d',0)>=0 else 'var(--red)'}">{_pct(s.get('ret_63d',0))}</b></span>
            <span><span style="color:var(--muted)">Ret.5d</span> <b style="color:{'var(--green)' if s.get('ret_5d',0)>=0 else 'var(--red)'}">{_pct(s.get('ret_5d',0))}</b></span>
            <span><span style="color:var(--muted)">RSI</span> <b style="color:{rsi_c}">{rsi:.0f}</b></span>
            <span><span style="color:var(--muted)">ADX</span> <b style="color:{'var(--green)' if s.get('adx',0)>25 else 'var(--muted)'}">{s.get('adx',0):.0f}</b></span>
            <span><span style="color:var(--muted)">Drawdown</span> <b style="color:{'var(--green)' if s.get('drawdown',0)>-0.05 else 'var(--red)'}">{_pct(s.get('drawdown',0))}</b></span>
            <span><span style="color:var(--muted)">RS/SPY</span> <b style="color:{'var(--green)' if s.get('rs_positive') else 'var(--red)'}">{'✓' if s.get('rs_positive') else '✗'}</b></span>
          </div>
          <div style="color:var(--muted);font-size:11px;margin-top:6px;font-style:italic">{html_mod.escape(s.get('rationale',''))}</div>
          <div style="color:var(--border);font-size:0.58rem;letter-spacing:0.08em;margin-top:6px;margin-bottom:2px">ANÁLISE GERADA AUTOMATICAMENTE · NÃO CONSTITUI ACONSELHAMENTO FINANCEIRO</div>
          <p style="color:var(--muted);font-size:11px;margin-top:0;line-height:1.6;font-style:italic">{narrativa_simples(s)}</p>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title">Sinais de Compra</h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:12px">
    Confluência de indicadores técnicos · entrada não comprometida
  </p>
  {cards}
</section>"""


def category_heatmap_section(cats: list[dict]) -> str:
    def score_to_bg(score):
        if score >= 0.65: return "oklch(13% 0.045 188)"
        if score >= 0.55: return "oklch(12% 0.025 188)"
        if score >= 0.45: return "oklch(13% 0.04 80)"
        if score >= 0.35: return "oklch(12% 0.04 35)"
        return "oklch(11% 0.025 35)"

    items = ""
    for c in cats:
        mom_color = {"▲": "var(--green)", "→": "var(--muted)", "▼": "var(--red)"}.get(c["momentum"], "var(--muted)")
        bg = score_to_bg(c["score_avg"])
        items += f"""
        <div class="cat-tile" style="background:{bg};border:1px solid {c['color']}">
          <div style="color:{c['color']};font-size:10px;font-weight:bold;margin-bottom:4px">{c['name']}</div>
          <div style="font-size:20px;font-weight:bold;color:{'var(--green)' if c['score_avg']>=0.5 else 'var(--red)'}">{c['score_avg']:.3f}</div>
          <div style="font-size:10px;color:{mom_color};margin-top:2px">{c['momentum']} {c['n']} ETFs · top {c['score_max']:.3f}</div>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title">Rotação por Categoria</h2>
  <div class="cat-grid">{items}</div>
</section>"""


def etf_table_section(scores_df: pd.DataFrame, cmap: dict, metadata: dict | None = None) -> str:
    meta = metadata or {}
    rows_js = []
    for _, r in scores_df.iterrows():
        sym  = str(r.get("etf", ""))
        info = cmap.get(sym, {})
        m    = meta.get(sym, {})
        score    = float(r.get("score",        0) or 0)
        ret_1d   = float(r.get("ret_1d",       0) or 0)
        ret_5d   = float(r.get("ret_5d",       0) or 0)
        ret_21d  = float(r.get("ret_21d",      0) or 0)
        ret_63d  = float(r.get("ret_63d",      0) or 0)
        rsi      = float(r.get("rsi",          50) or 50)
        adx      = float(r.get("adx",          0) or 0)
        drawdown = float(r.get("drawdown",     0) or 0)
        vol_21   = float(r.get("vol_21",       0) or 0)
        trend    = int(r.get("trend_sma",      0) or 0)
        macd     = int(r.get("macd_bullish",   0) or 0)
        rs_pos   = int(r.get("rs_positive",    0) or 0)
        above200 = int(r.get("above_sma200",   0) or 0)
        pct_raw  = r.get("score_pct", None)
        pct      = float(pct_raw) if pct_raw is not None and str(pct_raw) not in ("", "nan") else None
        pct_str  = f"P{pct*100:.0f}" if pct is not None else "—"

        ter_val  = m.get("ter")
        aum_val  = m.get("aum_bn")

        def _sub(col):
            v = r.get(col)
            if v is None or str(v) in ("", "nan"):
                return None
            try:
                return round(float(v), 3)
            except (TypeError, ValueError):
                return None

        rows_js.append({
            "ticker":    sym,
            "nome":      info.get("name", sym),
            "cat":       info.get("category_name", "—"),
            "cat_color": info.get("color", "#7c83fd"),
            "score":     round(score, 4),
            "pct":       pct_str,
            "r1d":       round(ret_1d,  4),
            "r5d":       round(ret_5d,  4),
            "r21d":      round(ret_21d, 4),
            "r63d":      round(ret_63d, 4),
            "rsi":       round(rsi, 1),
            "adx":       round(adx, 1),
            "dd":        round(drawdown, 4),
            "vol":       round(vol_21, 4),
            "trend":     trend,
            "macd":      macd,
            "rs":        rs_pos,
            "s200":      above200,
            "ter":       round(ter_val, 4) if ter_val is not None else None,
            "aum":       round(aum_val, 2) if aum_val is not None else None,
            "replica":   m.get("replica") or "—",
            "esg":       bool(m.get("esg", False)),
            "isin":      m.get("isin") or "—",
            "mom":       _sub("_momentum"),
            "trd":       _sub("_trend"),
            "rsk":       _sub("_risk"),
            "alp":       _sub("_alpha_quality"),
        })

    rows_json = json.dumps(rows_js, ensure_ascii=False)
    return f"""
<section class="section">
  <h2 class="section-title">Todos os ETFs</h2>
  <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
    <input id="tbl-search" type="text" placeholder="Pesquisar ETF ou categoria…"
      style="width:220px">
    <select id="tbl-filter">
      <option value="">Todos</option>
      <option value="FORTE COMPRA">FORTE COMPRA</option>
      <option value="COMPRA">COMPRA</option>
      <option value="POTENCIAL">POTENCIAL</option>
      <option value="score_high">Score ≥ 0.60</option>
    </select>
    <button id="wl-toggle" onclick="toggleWatchlist()"
      style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
             padding:6px 12px;border-radius:2px;cursor:pointer;font-size:0.8rem">
      ☆ Watchlist
    </button>
  </div>
  <div style="overflow-x:auto">
    <table id="etf-table" style="border-collapse:collapse;width:100%;min-width:900px;font-size:11px;background:var(--bg)">
      <thead>
        <tr id="tbl-head" style="background:var(--deep);color:var(--champagne)">
          <th style="padding:7px 6px;text-align:center;cursor:pointer" title="Watchlist">☆</th>
          <th class="sortable" data-col="ticker"  style="padding:7px 10px;text-align:left;cursor:pointer;white-space:nowrap">ETF ↕</th>
          <th class="sortable" data-col="nome"    style="padding:7px 10px;text-align:left;cursor:pointer">Nome ↕</th>
          <th class="sortable" data-col="cat"     style="padding:7px 10px;text-align:left;cursor:pointer">Categ. ↕</th>
          <th class="sortable" data-col="score"   style="padding:7px 10px;text-align:right;cursor:pointer">Score ↕</th>
          <th style="padding:7px 10px;text-align:right">Pct.</th>
          <th class="sortable" data-col="r1d"  style="padding:7px 10px;text-align:right;cursor:pointer">Dia ↕</th>
          <th class="sortable" data-col="r5d"  style="padding:7px 10px;text-align:right;cursor:pointer">5d ↕</th>
          <th class="sortable" data-col="r63d" style="padding:7px 10px;text-align:right;cursor:pointer">3M ↕</th>
          <th class="sortable" data-col="rsi"  style="padding:7px 10px;text-align:right;cursor:pointer">RSI ↕</th>
          <th class="sortable" data-col="adx"  style="padding:7px 10px;text-align:right;cursor:pointer">ADX ↕</th>
          <th class="sortable" data-col="dd"   style="padding:7px 10px;text-align:right;cursor:pointer">Drawdown ↕</th>
          <th style="padding:7px 10px;text-align:center">Trend</th>
          <th style="padding:7px 10px;text-align:center">MACD</th>
          <th style="padding:7px 10px;text-align:center">RS/SPY</th>
          <th style="padding:7px 10px;text-align:center">SMA200</th>
          <th class="sortable" data-col="ter"     style="padding:7px 10px;text-align:right;cursor:pointer">TER ↕</th>
          <th class="sortable" data-col="aum"     style="padding:7px 10px;text-align:right;cursor:pointer">AuM Bn ↕</th>
          <th style="padding:7px 10px;text-align:center">Réplica</th>
          <th style="padding:7px 10px;text-align:center">ESG</th>
          <th style="padding:7px 10px;text-align:left">ISIN</th>
        </tr>
      </thead>
      <tbody id="etf-tbody"></tbody>
    </table>
  </div>
  <script>
    const ETF_ROWS = {rows_json};
    let sortCol = "score", sortAsc = false, wlOnly = false;

    const CONV_STRONG_SCORE = {CONVICTION_STRONG_BUY_SCORE}, CONV_STRONG_SIGS = {CONVICTION_STRONG_BUY_SIGNALS};
    const CONV_BUY_SCORE    = {CONVICTION_BUY_SCORE},        CONV_BUY_SIGS    = {CONVICTION_BUY_SIGNALS};
    const CONV_POT_SCORE    = {CONVICTION_POTENTIAL_SCORE},  CONV_POT_SIGS    = {CONVICTION_POTENTIAL_SIGNALS};

    function loadWatchlist() {{
      try {{ return new Set(JSON.parse(localStorage.getItem("et_watchlist") || "[]")); }}
      catch {{ return new Set(); }}
    }}
    function saveWatchlist(wl) {{
      localStorage.setItem("et_watchlist", JSON.stringify([...wl]));
    }}
    function watchlistStar(ticker) {{
      const wl = loadWatchlist();
      if (wl.has(ticker)) wl.delete(ticker); else wl.add(ticker);
      saveWatchlist(wl);
      applyFilters();
    }}
    function toggleWatchlist() {{
      wlOnly = !wlOnly;
      const btn = document.getElementById("wl-toggle");
      btn.style.color = wlOnly ? "var(--gold)" : "var(--muted)";
      btn.style.borderColor = wlOnly ? "var(--gold)" : "var(--border)";
      btn.textContent = wlOnly ? "★ Watchlist" : "☆ Watchlist";
      applyFilters();
    }}

    function convictionLevel(row) {{
      const s = row.score, trend = row.trend, macd = row.macd,
            rsi = row.rsi, rs = row.rs, r5d = row.r5d, dd = row.dd;
      const vol_thresh = 0.07;
      const late = rsi > 68 || r5d > vol_thresh;
      let sigs = (trend?1:0)+(macd?1:0)+(rsi>=40&&rsi<=65?1:0)+(rs?1:0)+(r5d<0.04?1:0)+(dd>-0.08?1:0);
      if (!late && s >= CONV_STRONG_SCORE && sigs >= CONV_STRONG_SIGS) return "FORTE COMPRA";
      if (!late && s >= CONV_BUY_SCORE    && sigs >= CONV_BUY_SIGS)    return "COMPRA";
      if (s >= CONV_POT_SCORE             && sigs >= CONV_POT_SIGS)    return "POTENCIAL";
      return null;
    }}

    function pctColor(v) {{ return v >= 0 ? "var(--green)" : "var(--red)"; }}
    function rsiColor(v) {{ return (v>=40&&v<=65)?"var(--green)":(v>70?"var(--yellow)":(v<30?"var(--red)":"var(--muted)")); }}
    function flagHtml(v, t, f) {{
      return `<span style="color:${{v?'var(--green)':'var(--red)'}}">${{v?t:f}}</span>`;
    }}

    function renderTable(rows) {{
      const wl = loadWatchlist();
      const tbody = document.getElementById("etf-tbody");
      const td = "padding:5px 10px;border-bottom:1px solid var(--border)";
      const tds = "padding:5px 6px;border-bottom:1px solid var(--border)";
      tbody.innerHTML = rows.map(r => {{
        const lvl = convictionLevel(r);
        const starred = wl.has(r.ticker);
        const lvlBadge = lvl ? `<span style="background:${{
          lvl==='FORTE COMPRA'?'var(--green)':lvl==='COMPRA'?'var(--light-green)':'var(--yellow)'
        }};color:#000;padding:1px 6px;border-radius:2px;font-size:9px;font-weight:bold">${{lvl}}</span>` : "";
        const terStr = r.ter !== null ? (r.ter*100).toFixed(2)+"%" : "—";
        const aumStr = r.aum !== null ? r.aum.toFixed(1)+"B" : "—";
        const repColor = r.replica === "fisica" ? "var(--green)" : r.replica === "sintetica" ? "var(--yellow)" : "var(--muted)";
        return `<tr style="background:var(--bg)">
          <td style="${{tds}};text-align:center">
            <span onclick="watchlistStar('${{r.ticker}}')" title="Watchlist"
              style="cursor:pointer;color:${{starred?'var(--gold)':'var(--border)'}};font-size:14px">
              ${{starred?'★':'☆'}}
            </span>
          </td>
          <td style="${{td}};color:var(--text);font-weight:bold">
            <span style="color:${{r.cat_color}}">●</span> ${{r.ticker}} ${{lvlBadge}}
          </td>
          <td style="${{td}};color:var(--muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{r.nome}}</td>
          <td style="${{td}};color:${{r.cat_color}};white-space:nowrap">${{r.cat}}</td>
          <td style="${{td}};text-align:right" title="M:${{r.mom??'—'}} T:${{r.trd??'—'}} R:${{r.rsk??'—'}} α:${{r.alp??'—'}}">
            <span style="color:${{r.score>=0.75?'var(--green)':r.score>=0.55?'var(--light-green)':r.score>=0.40?'var(--yellow)':'var(--red)'}};font-weight:bold">${{r.score.toFixed(3)}}</span>
            ${{r.mom!=null ? `<div style="display:flex;gap:3px;justify-content:flex-end;margin-top:4px;align-items:center">
              <span style="color:var(--muted);font-size:9px;margin-right:1px">M</span>
              <span title="Momentum ${{r.mom}}" style="display:inline-block;width:${{Math.round(r.mom*28)}}px;height:4px;background:var(--green);border-radius:2px"></span>
              <span style="color:var(--muted);font-size:9px;margin-left:2px">T</span>
              <span title="Trend ${{r.trd}}" style="display:inline-block;width:${{Math.round(r.trd*28)}}px;height:4px;background:#7c83fd;border-radius:2px"></span>
              <span style="color:var(--muted);font-size:9px;margin-left:2px">R</span>
              <span title="Risk ${{r.rsk}}" style="display:inline-block;width:${{Math.round(r.rsk*28)}}px;height:4px;background:var(--blue-light);border-radius:2px"></span>
              <span style="color:var(--muted);font-size:9px;margin-left:2px">α</span>
              <span title="Alpha ${{r.alp}}" style="display:inline-block;width:${{Math.round(r.alp*28)}}px;height:4px;background:var(--yellow);border-radius:2px"></span>
            </div>` : ''}}
          </td>
          <td style="${{td}};color:var(--muted);text-align:right">${{r.pct}}</td>
          <td style="${{td}};color:${{pctColor(r.r1d)}};text-align:right">${{(r.r1d*100).toFixed(2)}}%</td>
          <td style="${{td}};color:${{pctColor(r.r5d)}};text-align:right">${{(r.r5d*100).toFixed(2)}}%</td>
          <td style="${{td}};color:${{pctColor(r.r63d)}};text-align:right">${{(r.r63d*100).toFixed(1)}}%</td>
          <td style="${{td}};color:${{rsiColor(r.rsi)}};text-align:right">${{r.rsi.toFixed(0)}}</td>
          <td style="${{td}};color:${{r.adx>25?'var(--green)':'var(--muted)'}};text-align:right">${{r.adx.toFixed(0)}}</td>
          <td style="${{td}};color:${{r.dd>-0.05?'var(--green)':'var(--red)'}};text-align:right">${{(r.dd*100).toFixed(1)}}%</td>
          <td style="${{td}};text-align:center">${{flagHtml(r.trend,'↑','↓')}}</td>
          <td style="${{td}};text-align:center">${{flagHtml(r.macd,'+','−')}}</td>
          <td style="${{td}};text-align:center">${{flagHtml(r.rs,'✓','✗')}}</td>
          <td style="${{td}};text-align:center">${{flagHtml(r.s200,'✓','✗')}}</td>
          <td style="${{td}};color:var(--muted);text-align:right">${{terStr}}</td>
          <td style="${{td}};color:var(--muted);text-align:right">${{aumStr}}</td>
          <td style="${{td}};color:${{repColor}};text-align:center">${{r.replica}}</td>
          <td style="${{td}};text-align:center">${{flagHtml(r.esg,'✓','✗')}}</td>
          <td style="${{td}};color:var(--muted);font-family:monospace;font-size:10px">${{r.isin}}</td>
        </tr>`;
      }}).join("");
    }}

    function applyFilters() {{
      const q = document.getElementById("tbl-search").value.toLowerCase();
      const f = document.getElementById("tbl-filter").value;
      const wl = loadWatchlist();
      let rows = [...ETF_ROWS];
      if (wlOnly) rows = rows.filter(r => wl.has(r.ticker));
      if (q) rows = rows.filter(r => r.ticker.toLowerCase().includes(q) || r.nome.toLowerCase().includes(q) || r.cat.toLowerCase().includes(q));
      if (f === "score_high") rows = rows.filter(r => r.score >= 0.60);
      else if (f) rows = rows.filter(r => convictionLevel(r) === f);
      rows.sort((a, b) => {{
        const va = a[sortCol] ?? "", vb = b[sortCol] ?? "";
        if (typeof va === "string") return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        return sortAsc ? va - vb : vb - va;
      }});
      renderTable(rows);
    }}

    document.getElementById("tbl-search").addEventListener("input", applyFilters);
    document.getElementById("tbl-filter").addEventListener("change", applyFilters);
    document.querySelectorAll(".sortable").forEach(th => {{
      th.addEventListener("click", () => {{
        const col = th.dataset.col;
        if (sortCol === col) sortAsc = !sortAsc;
        else {{ sortCol = col; sortAsc = col === "ticker" || col === "nome"; }}
        applyFilters();
      }});
    }});
    applyFilters();
  </script>
</section>"""


def history_chart_section(hist_df: pd.DataFrame, scores_df: pd.DataFrame) -> str:
    if hist_df.empty or scores_df.empty:
        return ""

    # Top 5 ETFs by current score for sparklines
    top5 = scores_df.nlargest(5, "score")["etf"].tolist() if "score" in scores_df.columns else []
    if not top5:
        return ""

    dates_all = sorted(hist_df["date"].unique())
    date_labels = [str(d)[:10] for d in dates_all]

    datasets = []
    palette = [
        "oklch(84% 0.19 80.46)",
        "oklch(68% 0.11 188)",
        "oklch(58% 0.15 35)",
        "oklch(78% 0.10 188)",
        "oklch(68% 0.16 80)",
    ]
    for i, etf in enumerate(top5):
        sub = hist_df[hist_df["etf"] == etf].set_index("date")["score"]
        data_points = []
        for d in dates_all:
            v = sub.get(d, None)
            data_points.append(None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4))
        datasets.append({
            "label":       etf,
            "data":        data_points,
            "borderColor": palette[i % len(palette)],
            "backgroundColor": "transparent",
            "tension":     0.3,
            "pointRadius": 1,
            "borderWidth": 2,
        })

    chart_data = json.dumps({"labels": date_labels, "datasets": datasets})
    return f"""
<section class="section">
  <h2 class="section-title">Evolução de Score — Top 5 ETFs (últimos 30 dias)</h2>
  <div style="position:relative;height:240px">
    <canvas id="scoreChart"></canvas>
  </div>
  <script>
    (function() {{
      const ctx = document.getElementById("scoreChart").getContext("2d");
      new Chart(ctx, {{
        type: "line",
        data: {chart_data},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          scales: {{
            x: {{ ticks: {{ color:"oklch(63% 0.024 82)", maxTicksLimit:8, font:{{size:10}} }},
                   grid: {{ color:"oklch(15% 0.008 95)" }} }},
            y: {{ min:0, max:1, ticks: {{ color:"oklch(63% 0.024 82)", font:{{size:10}} }},
                   grid: {{ color:"oklch(15% 0.008 95)" }} }}
          }},
          plugins: {{
            legend: {{ labels: {{ color:"oklch(81% 0.03 82)", font:{{size:11}} }} }},
            tooltip: {{ backgroundColor:"oklch(4% 0.004 95)",titleColor:"oklch(84% 0.19 80.46)",bodyColor:"oklch(81% 0.03 82)" }}
          }}
        }}
      }});
    }})();
  </script>
</section>"""


def backtest_section(bt_df: pd.DataFrame) -> str:
    if bt_df.empty:
        return ""

    fwd_col = "fwd_21d"
    exc_col = "fwd_21d_excess"
    if fwd_col not in bt_df.columns:
        return ""

    levels = ["FORTE COMPRA", "COMPRA", "POTENCIAL"]
    level_colors = {"FORTE COMPRA": "var(--green)", "COMPRA": "var(--light-green)", "POTENCIAL": "var(--yellow)"}

    def regime_block(df_sub, regime_label):
        rows_html = ""
        for lvl in levels:
            sub = df_sub[df_sub["level"] == lvl][fwd_col].dropna() if "level" in df_sub.columns else pd.Series()
            if sub.empty:
                continue
            win = (sub > 0).mean()
            avg = sub.mean()
            exc_avg = df_sub[df_sub["level"] == lvl][exc_col].dropna().mean() if exc_col in df_sub.columns else float("nan")
            clr = level_colors.get(lvl, "var(--muted)")
            exc_html = f'&nbsp;·&nbsp;<span style="color:var(--muted)">Excesso SPY</span> <b style="color:{_c(exc_avg)}">{_pct(exc_avg)}</b>' if pd.notna(exc_avg) else ""
            rows_html += f"""
            <div style="display:flex;align-items:center;gap:12px;padding:7px 0;border-bottom:1px solid var(--border);flex-wrap:wrap">
              <span style="background:{clr};color:#000;padding:1px 8px;border-radius:2px;font-size:10px;font-weight:bold;min-width:90px;text-align:center">{lvl}</span>
              <span style="color:var(--muted);font-size:11px">n={len(sub)}</span>
              <span style="font-size:12px"><span style="color:var(--muted)">Ret. médio 21d</span> <b style="color:{_c(avg)}">{_pct(avg)}</b>{exc_html}</span>
              <span style="font-size:12px"><span style="color:var(--muted)">Win rate</span> <b style="color:{_c(win-0.5)}">{win:.0%}</b></span>
            </div>"""
        return rows_html or '<p style="color:var(--muted);font-size:11px">Sem dados suficientes.</p>'

    all_html  = regime_block(bt_df, "TODOS")
    bull_html = regime_block(bt_df[bt_df.get("spy_regime", pd.Series()) == "BULL"] if "spy_regime" in bt_df.columns else pd.DataFrame(), "BULL")
    bear_html = regime_block(bt_df[bt_df.get("spy_regime", pd.Series()) == "BEAR"] if "spy_regime" in bt_df.columns else pd.DataFrame(), "BEAR")

    return f"""
<section class="section">
  <h2 class="section-title">Backtest — Retorno Forward 21d por Sinal</h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:12px">
    Retorno dos 21 dias seguintes a cada sinal · excesso vs SPY no mesmo período
  </p>
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('bt-all',this)">Todos</button>
    <button class="tab-btn" onclick="showTab('bt-bull',this)">BULL</button>
    <button class="tab-btn" onclick="showTab('bt-bear',this)">BEAR</button>
  </div>
  <div id="bt-all"  class="tab-content active">{all_html}</div>
  <div id="bt-bull" class="tab-content" style="display:none">{bull_html}</div>
  <div id="bt-bear" class="tab-content" style="display:none">{bear_html}</div>
  <script>
    function showTab(id, btn) {{
      document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
      document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
      document.getElementById(id).style.display = "block";
      btn.classList.add("active");
    }}
  </script>

  <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border);
              display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div>
      <div style="font-family:'SFMono-Regular',monospace;font-size:0.59rem;letter-spacing:0.10em;
                  text-transform:uppercase;color:var(--patina);margin-bottom:8px">Base Académica</div>
      <div style="display:flex;flex-wrap:wrap;gap:5px">
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Momentum 12-1M: comprar vencedores, vender perdedores">Jegadeesh &amp; Titman (1993)</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Trend following com SMA de 10 meses">Faber (2007)</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Dual momentum: absoluto e relativo">Antonacci (2014)</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Anomalia low-volatility: retorno ajustado ao risco (factor IR-momentum)">Ang et al. (2006)</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="101 fórmulas de alpha cross-sectional — base do factor alpha quality">Kakushadze (2015) · alpha101</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Value &amp; Momentum Everywhere">AQR — Value &amp; Momentum</span>
        <span style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
                     font-size:0.60rem;padding:2px 7px;border-radius:2px"
              title="Retorno ajustado ao risco: base do factor calmar/sharpe">Sharpe Ratio</span>
      </div>
    </div>
    <div>
      <div style="font-family:'SFMono-Regular',monospace;font-size:0.59rem;letter-spacing:0.10em;
                  text-transform:uppercase;color:var(--patina);margin-bottom:8px">Para quem</div>
      <p style="color:var(--muted);font-size:0.67rem;line-height:1.6;margin:0">
        Investidores europeus que seguem estratégias quantitativas baseadas em evidência académica
        e querem sinais técnicos transparentes, reproduzíveis e auditáveis.
      </p>
    </div>
  </div>
</section>"""


def portfolio_section(portfolio_path: Path, cmap: dict) -> str:
    if not portfolio_path.exists():
        return ""
    try:
        df = pd.read_csv(portfolio_path)
    except Exception:
        return ""
    if df.empty:
        return ""

    required = {"symbol", "qty", "market_value", "unrealized_pl", "unrealized_plpc"}
    if not required.issubset(df.columns):
        return ""

    df = df.sort_values("market_value", ascending=False)
    total_value = df["market_value"].sum()
    total_pl    = df["unrealized_pl"].sum()
    pl_color    = "var(--green)" if total_pl >= 0 else "var(--red)"

    th = "padding:7px 10px;background:var(--deep);color:var(--champagne);text-align:right;font-size:11px"
    td = "padding:5px 10px;border-bottom:1px solid var(--border);font-size:11px;text-align:right"

    headers = "".join(f'<th style="{th};text-align:{"left" if i < 2 else "right"}">{h}</th>'
                      for i, h in enumerate(["Símbolo", "Nome", "Qtd.", "Valor", "P&L", "P&L %", "Peso"]))
    rows_html = ""
    for _, r in df.iterrows():
        sym      = str(r.get("symbol", ""))
        info     = cmap.get(sym, {})
        name     = info.get("name", sym)
        qty      = float(r.get("qty", 0) or 0)
        mv       = float(r.get("market_value", 0) or 0)
        pl       = float(r.get("unrealized_pl", 0) or 0)
        plpc     = float(r.get("unrealized_plpc", 0) or 0)
        weight   = mv / total_value if total_value > 0 else 0
        pl_c     = "var(--green)" if pl >= 0 else "var(--red)"
        cat_color = info.get("color", "var(--muted)")
        rows_html += (
            f'<tr>'
            f'<td style="{td};text-align:left;font-weight:bold">'
            f'<span style="color:{cat_color}">●</span> {html_mod.escape(sym)}</td>'
            f'<td style="{td};text-align:left;color:var(--muted);max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{html_mod.escape(name)}</td>'
            f'<td style="{td}">{qty:.4g}</td>'
            f'<td style="{td}">${mv:,.2f}</td>'
            f'<td style="{td};color:{pl_c}">{pl:+,.2f}</td>'
            f'<td style="{td};color:{pl_c}">{plpc*100:+.2f}%</td>'
            f'<td style="{td};color:var(--muted)">{weight:.1%}</td>'
            f'</tr>'
        )

    return f"""
<section class="section">
  <h2 class="section-title">Portfólio Alpaca</h2>
  <div style="display:flex;gap:24px;margin-bottom:14px;flex-wrap:wrap">
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em">Valor Total</div>
      <div style="color:var(--champagne);font-size:18px;font-weight:600">${total_value:,.2f}</div>
    </div>
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em">P&L Não Realizado</div>
      <div style="color:{pl_color};font-size:18px;font-weight:600">{total_pl:+,.2f}</div>
    </div>
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em">Posições</div>
      <div style="color:var(--champagne);font-size:18px;font-weight:600">{len(df)}</div>
    </div>
  </div>
  <div style="overflow-x:auto">
    <table style="border-collapse:collapse;width:100%;min-width:600px;background:var(--bg)">
      <thead><tr>{headers}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</section>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600&display=swap');

:root {
  /* Impeccable — Neo Kinpaku */
  --bg:        oklch(7% 0.006 95);
  --deep:      oklch(4% 0.004 95);
  --surface:   oklch(11% 0.006 95);
  --border:    oklch(19% 0.008 95);
  --gold:      oklch(84% 0.19 80.46);
  --patina:    oklch(70% 0.12 188);
  --champagne: oklch(84% 0.035 82);
  --text:      oklch(81% 0.03 82);
  --muted:     oklch(63% 0.024 82);
  --vermilion: oklch(58% 0.15 35);

  /* semantic aliases — used in JS template strings */
  --green:       oklch(68% 0.11 188);
  --light-green: oklch(58% 0.10 188);
  --yellow:      oklch(84% 0.19 80.46);
  --red:         oklch(58% 0.15 35);
  --orange:      oklch(62% 0.13 50);
  --blue:        oklch(84% 0.19 80.46);
  --blue-light:  oklch(70% 0.12 188);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Albert Sans', 'Avenir Next', 'Helvetica Neue', Arial, system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.65;
}

header {
  background: var(--deep);
  border-bottom: 1px solid oklch(15% 0.008 95);
  padding: 14px 24px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.header-inner {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.logo {
  font-family: 'Albert Sans', sans-serif;
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  color: var(--gold);
}
.subtitle {
  color: var(--muted);
  font-family: 'SFMono-Regular', 'Roboto Mono', Consolas, monospace;
  font-size: 0.62rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-top: 4px;
}
.main { max-width: 1400px; margin: 0 auto; padding: 20px 24px; }

.summary-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 1px;
  margin-bottom: 16px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.card { background: var(--surface); padding: 20px 16px; flex: 1 1 140px; }

.section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 20px;
  margin-bottom: 12px;
}
.section-title {
  font-family: 'Albert Sans', sans-serif;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--champagne);
  margin-bottom: 14px;
}
.cat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.cat-tile { padding: 14px 12px; }

.tabs { display: flex; gap: 6px; margin-bottom: 14px; }
.tab-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 5px 14px;
  border-radius: 2px;
  cursor: pointer;
  font-family: 'Albert Sans', sans-serif;
  font-size: 0.75rem;
  font-weight: 500;
  transition: color 180ms cubic-bezier(0.2, 0.8, 0.2, 1),
              border-color 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.tab-btn:hover { color: var(--champagne); border-color: oklch(40% 0.012 82); }
.tab-btn.active { color: var(--gold); border-color: var(--gold); }

#tbl-search, #tbl-filter {
  background: var(--deep);
  border: 1px solid oklch(28% 0.010 95);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 2px;
  font-family: 'Albert Sans', sans-serif;
  font-size: 0.8rem;
  transition: border-color 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
#tbl-search:focus, #tbl-filter:focus { outline: none; border-color: var(--patina); }
#tbl-search::placeholder { color: var(--muted); }
.sortable { transition: color 180ms cubic-bezier(0.2, 0.8, 0.2, 1); }
.sortable:hover { color: var(--gold) !important; }

footer {
  text-align: center;
  color: var(--muted);
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  padding: 24px 0 40px;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}

/* Hero stat bar */
.stat-bar {
  display: flex;
  align-items: stretch;
  background: var(--deep);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 16px;
}
.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 12px 12px;
  flex: 1;
  background: var(--surface);
  cursor: default;
}

/* CTA strip */
.cta-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  background: oklch(9% 0.012 188);
  border: 1px solid oklch(22% 0.06 188);
  border-radius: 2px;
  padding: 10px 16px;
  margin-bottom: 12px;
}

/* Signal legend bar */
.signal-legend {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 0 10px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}
.stat-div {
  width: 1px;
  background: var(--border);
  flex-shrink: 0;
  align-self: stretch;
}

/* GitHub link button */
.gh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 5px 12px;
  border-radius: 2px;
  font-size: 0.72rem;
  font-family: 'Albert Sans', sans-serif;
  text-decoration: none;
  letter-spacing: 0.04em;
  white-space: nowrap;
  transition: color 180ms cubic-bezier(0.2, 0.8, 0.2, 1),
              border-color 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.gh-btn:hover { color: var(--gold); border-color: var(--gold); }

/* Academic badges */
.acad-badge {
  display: inline-block;
  background: var(--deep);
  border: 1px solid var(--border);
  color: var(--muted);
  font-size: 0.60rem;
  padding: 2px 7px;
  border-radius: 2px;
  text-decoration: none;
  transition: color 140ms, border-color 140ms;
}
.acad-badge:hover { color: var(--champagne); border-color: oklch(40% 0.012 82); }

@media (max-width: 600px) {
  .stat-bar { flex-wrap: wrap; }
  .stat-item { flex: 1 1 calc(33% - 2px); min-width: 80px; }
  .stat-div { display: none; }
}

/* Live pulse dot */
@keyframes pulse-live {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.35; transform: scale(0.7); }
}
.live-dot {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--green);
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: middle;
  animation: pulse-live 2s ease-in-out infinite;
  flex-shrink: 0;
}

/* FORTE COMPRA glow pulse */
@keyframes glow-forte {
  0%, 100% { box-shadow: 0 0 0 0 rgba(76,175,80,0); }
  50%       { box-shadow: 0 0 14px 3px rgba(76,175,80,0.30); }
}
.signal-forte { animation: glow-forte 3s ease-in-out infinite; }

/* Animated gradient top accent */
@keyframes shift-accent {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
.top-accent {
  height: 2px;
  background: linear-gradient(90deg, #080a10 0%, #4caf50 20%, #7c83fd 50%, #ffd54f 80%, #080a10 100%);
  background-size: 200% 100%;
  animation: shift-accent 6s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
  .live-dot, .signal-forte, .top-accent { animation: none !important; }
}
</style>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_dashboard(cfg: dict) -> None:
    data = load_data(cfg)
    if not data:
        print("[SKIP] Sem dados para o dashboard.")
        return

    ts       = datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M UTC")
    ts_epoch = int(datetime.now(timezone.utc).timestamp())
    signals      = build_buy_signals(data["rows_raw"], top_n=10)   # para display (secção sinais)
    signals_all  = build_buy_signals(data["rows_raw"], top_n=200)  # para contagens nos cards
    metadata = get_etf_metadata(cfg)
    vapid_key = cfg.get("params", {}).get("vapid_public_key", "")

    push_btn = ""
    goatcounter_code = cfg.get("params", {}).get("goatcounter_code", "")
    goatcounter_script = (
        f'\n<script data-goatcounter="https://{goatcounter_code}.goatcounter.com/count"'
        f' async src="//gc.zgo.at/count.js"></script>'
        if goatcounter_code else
        "\n<!-- GoatCounter: define params.goatcounter_code em config/etfs.json para activar analytics -->"
    )
    sw_script = f"""
<script>
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('./sw.js').catch(function(){{}});
  }}
</script>{goatcounter_script}"""

    if vapid_key:
        push_btn = f"""
<button id="push-btn" onclick="subscribePush()"
  style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
         padding:6px 12px;border-radius:2px;cursor:pointer;font-size:0.8rem;
         margin-left:12px" title="Receber alertas push">
  🔔 Activar alertas
</button>
<script>
const VAPID_PUBLIC_KEY = "{vapid_key}";
async function subscribePush() {{
  try {{
    const sw = await navigator.serviceWorker.ready;
    const sub = await sw.pushManager.subscribe({{
      userVisibleOnly: true,
      applicationServerKey: VAPID_PUBLIC_KEY,
    }});
    await fetch('/api/subscribe', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(sub),
    }});
    document.getElementById('push-btn').textContent = '🔔 Alertas activos';
    document.getElementById('push-btn').style.color = 'var(--green)';
    document.getElementById('push-btn').style.borderColor = 'var(--green)';
  }} catch (e) {{
    console.error('Push subscription failed:', e);
  }}
}}
</script>"""

    n_etfs_today = len(data["scores_df"])
    n_total = sum(
        len(cat.get("etfs", []))
        for cat in cfg.get("categories", [])
        if isinstance(cat, dict)
    ) or 97

    sections = [
        header_html(data["spy_close"], data["spy_sma200"], data["spy_regime"], ts, n_etfs=n_etfs_today),
        '<div class="main">',
        hero_bar_html(n_etfs=n_etfs_today, n_total=n_total),
        signal_legend_html(n_etfs=n_etfs_today),
        summary_cards_html(signals_all, data["scores_df"]),
        explainer_section(),
        advisor_section(data["rows_raw"]),
        buy_signals_section(signals),
        category_heatmap_section(data["cats"]),
        history_chart_section(data["hist_df"], data["scores_df"]),
        backtest_section(data["bt_df"]),
        portfolio_section(PORTFOLIO, data["cmap"]),
        etf_table_section(data["scores_df"], data["cmap"], metadata),
        brand_banner_section_html(),
        '</div>',
        f'<footer>'
        f'<div style="max-width:900px;margin:0 auto">'
        f'<div style="margin-bottom:10px"></div>'
        f'<div style="color:var(--muted);font-size:0.65rem;margin-bottom:6px">ET-Spotter · dados via yfinance · GitHub Actions · actualização diária às 22h UTC</div>'
        f'<div style="display:flex;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap;margin-bottom:12px">'
        f'<span class="acad-badge" title="Momentum 12-1M">Jegadeesh &amp; Titman (1993)</span>'
        f'<span class="acad-badge" title="Trend following SMA">Faber (2007)</span>'
        f'<span class="acad-badge" title="Dual momentum">Antonacci (2014)</span>'
        f'<span class="acad-badge" title="Low-volatility anomaly">Ang et al. (2006)</span>'
        f'<span class="acad-badge" title="Alpha cross-sectional">Kakushadze (2015)</span>'
        f'</div>'
        f'<span style="font-size:0.68rem;opacity:0.75;line-height:1.6">⚠️ Informação técnica e resultados de backtest — <b>não constitui aconselhamento financeiro</b>. Os sinais identificam períodos de convergência estatística de múltiplos factores; não predizem preços futuros. Consulta sempre um profissional antes de investir.</span>'
        f'</div>'
        f'{push_btn}</footer>',
    ]

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <meta name="theme-color" content="#080a10">
  <title>ET-Spotter — Análise Automática de ETFs UCITS</title>
  <meta name="description" content="Análise técnica automática de {n_etfs_today} ETFs UCITS todos os dias. Score composto de momentum, tendência, risco e alpha. Grátis, open-source, sem servidores.">
  <meta property="og:type" content="website">
  <meta property="og:title" content="ET-Spotter — Análise Automática de ETFs UCITS">
  <meta property="og:description" content="{n_etfs_today} ETFs europeus analisados diariamente. Recebe o sinal técnico por email — €0, open-source, GitHub Actions.">
  <meta property="og:url" content="https://nunovinhas-creator.github.io/ET-spotter">
  <meta property="og:image" content="https://raw.githubusercontent.com/nunovinhas-creator/ET-spotter/claude/youthful-euler-SKkX7/docs/assets/banner.svg">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="ET-Spotter — Análise Automática de ETFs UCITS">
  <meta name="twitter:description" content="{n_etfs_today} ETFs UCITS analisados diariamente. Score de momentum, tendência, risco e alpha. Grátis.">
  <link rel="manifest" href="./manifest.json">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  {CSS}
</head>
<body>
{"".join(sections)}
{sw_script}
</body>
</html>"""

    # Replace service worker cache-bust placeholder
    html = html.replace("__BUILD_TS__", str(ts_epoch))

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "dashboard.html"
    out.write_text(html, encoding="utf-8")

    # Copia para docs/index.html → servido via GitHub Pages
    docs = Path("docs")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(html, encoding="utf-8")

    print(f"[OK] Dashboard gerado: {out}  ({len(html)//1024} KB)")
    print(f"[OK] GitHub Pages:     docs/index.html")


def main():
    cfg = load_config()
    generate_dashboard(cfg)


if __name__ == "__main__":
    main()
