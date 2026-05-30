"""
Gera data/reports/dashboard.html — dashboard visual permanentemente actualizado.

Lê: scores_latest.csv, scores_history.csv, backtest_signals.csv (opcional), SPY diário.
Produz: HTML auto-suficiente com Chart.js (CDN), tabela ordenável/pesquisável, sparklines.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_category_map, build_buy_signals, category_summary, compute_advisor_score, build_advisor_candidates

REPORTS     = Path("data/reports")
DATA_DAILY  = Path("data/daily")
SCORES_HIST = Path("data/scores_history.csv")


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

    # rows completos para build_buy_signals
    rows_raw = []
    for _, row in scores_df.iterrows():
        sym  = str(row.get("etf", ""))
        info = cmap.get(sym, {})
        rows_raw.append({
            "ticker":       sym,
            "nome":         info.get("name", sym),
            "categoria":    info.get("category_name", "—"),
            "cor":          info.get("color", "#7c83fd"),
            "score":        float(row.get("score",        0) or 0),
            "delta_score":  0.0,
            "trend_sma":    int(row.get("trend_sma",      0) or 0),
            "macd_bullish": int(row.get("macd_bullish",   0) or 0),
            "rsi":          float(row.get("rsi",          50) or 50),
            "rs_positive":  int(row.get("rs_positive",    0) or 0),
            "ret_5d":       float(row.get("ret_5d",       0) or 0),
            "ret_21d":      float(row.get("ret_21d",      0) or 0),
            "ret_63d":      float(row.get("ret_63d",      0) or 0),
            "ret_126d":     float(row.get("ret_126d",     0) or 0),
            "ret_252d":     float(row.get("ret_252d",     0) or 0),
            "drawdown":     float(row.get("drawdown",     0) or 0),
            "vol_21":       float(row.get("vol_21",       0) or 0),
            "adx":          float(row.get("adx",          0) or 0),
            "above_sma200": int(row.get("above_sma200",   0) or 0),
            "sharpe_63":    float(row.get("sharpe_63",    0) or 0),
            "calmar_63":    float(row.get("calmar_63",    0) or 0),
            "rs_mom_63":    float(row.get("rs_mom_63",    0) or 0),
            "score_pct":    row.get("score_pct", None),
        })

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


def _pct(v, digits=1) -> str:
    return f"{v:+.{digits}%}" if pd.notna(v) else "—"


def _num(v, digits=3) -> str:
    return f"{v:.{digits}f}" if pd.notna(v) else "—"


# ── Sections ──────────────────────────────────────────────────────────────────

def header_html(spy_close, spy_sma200, spy_regime, ts, n_etfs: int = 0) -> str:
    regime_color = "var(--green)" if spy_regime == "BULL" else ("var(--red)" if spy_regime == "BEAR" else "var(--muted)")
    spy_str = f"SPY {spy_close:.2f}" if spy_close else "SPY —"
    sma_str = f"SMA200 {spy_sma200:.2f}" if spy_sma200 else ""
    regime_badge = (
        f'<span style="background:{regime_color};color:#000;padding:2px 8px;'
        f'border-radius:8px;font-size:11px;font-weight:bold">{spy_regime}</span>'
    )
    return f"""
<header>
  <div class="header-inner">
    <div>
      <div class="logo">ET-Spotter</div>
      <div class="subtitle">Dashboard de monitorização técnica · {n_etfs} ETFs</div>
    </div>
    <div style="text-align:right">
      <div style="color:var(--text);font-size:13px">{spy_str} &nbsp;·&nbsp; {sma_str} &nbsp; {regime_badge}</div>
      <div style="color:var(--muted);font-size:11px;margin-top:3px">Actualizado: {ts}</div>
    </div>
  </div>
</header>"""


def summary_cards_html(signals: list[dict], scores_df: pd.DataFrame) -> str:
    n_fc  = sum(1 for s in signals if s["level"] == "FORTE COMPRA")
    n_c   = sum(1 for s in signals if s["level"] == "COMPRA")
    n_p   = sum(1 for s in signals if s["level"] == "POTENCIAL")
    n_high = int((scores_df["score"] >= 0.50).sum()) if "score" in scores_df.columns else 0
    avg_score = scores_df["score"].mean() if "score" in scores_df.columns else 0

    def card(label, value, color, sub=""):
        return f"""
        <div class="card" style="border-top:3px solid {color}">
          <div style="font-size:28px;font-weight:bold;color:{color}">{value}</div>
          <div style="color:var(--text);font-size:12px;margin-top:4px">{label}</div>
          {f'<div style="color:var(--muted);font-size:10px;margin-top:2px">{sub}</div>' if sub else ""}
        </div>"""

    return f"""
<section class="summary-grid">
  {card("FORTE COMPRA",   n_fc,  "var(--green)")}
  {card("COMPRA",         n_c,   "var(--light-green)")}
  {card("POTENCIAL",      n_p,   "var(--yellow)")}
  {card("Score > 0.50",   n_high,"var(--blue)", f"de {len(scores_df)} ETFs")}
  {card("Score médio",    f"{avg_score:.3f}", "var(--blue-light)")}
</section>"""


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
        bar_color = "#4caf50" if pts >= 70 else ("#ffd54f" if pts >= 50 else "#7c83fd")

        ret_252d = float(r.get("ret_252d", 0) or 0)
        ret_126d = float(r.get("ret_126d", 0) or 0)
        momentum = (ret_252d - float(r.get("ret_21d", 0) or 0)) if ret_252d != 0 else (ret_126d - float(r.get("ret_21d", 0) or 0))
        mom_label = "Mom.12-1M" if ret_252d != 0 else "Mom.6-1M"

        cards += f"""
        <div style="background:#0d1021;border-left:4px solid {bar_color};padding:14px 16px;
                    margin:8px 0;border-radius:4px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
            <span style="font-size:18px">{medal}</span>
            <span style="color:var(--text);font-size:16px;font-weight:bold">{r['ticker']}</span>
            <span style="color:var(--muted);font-size:11px">{r['nome']}</span>
            <span style="color:{r['cor']};font-size:10px">● {r['categoria']}</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <span style="color:var(--muted);font-size:11px">Score técnico</span>
            <div style="flex:1;background:#1e2130;border-radius:4px;height:7px;max-width:200px">
              <div style="width:{pts}%;background:{bar_color};border-radius:4px;height:7px"></div>
            </div>
            <span style="color:{bar_color};font-weight:bold;font-size:13px">{pts}/100</span>
          </div>
          <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:11px;margin-bottom:10px">
            <span><span style="color:var(--muted)">{mom_label}</span> <b style="color:{'var(--green)' if momentum>=0 else 'var(--red)'}">{_pct(momentum)}</b></span>
            <span><span style="color:var(--muted)">Ret.3M</span> <b style="color:{'var(--green)' if r.get('ret_63d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_63d',0))}</b></span>
            <span><span style="color:var(--muted)">Ret.5d</span> <b style="color:{'var(--green)' if r.get('ret_5d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_5d',0))}</b></span>
            <span><span style="color:var(--muted)">RSI</span> <b style="color:{'var(--green)' if 35<=rsi<=65 else 'var(--yellow)'}">{rsi:.0f}</b></span>
            <span><span style="color:var(--muted)">ADX</span> <b style="color:{'var(--green)' if r.get('adx',0)>=25 else 'var(--muted)'}">{r.get('adx',0):.0f}</b></span>
            <span><span style="color:var(--muted)">Sharpe</span> <b style="color:{'var(--green)' if r.get('sharpe_63',0)>=1 else 'var(--muted)'}">{r.get('sharpe_63',0):.1f}</b></span>
            <span><span style="color:var(--muted)">RS/SPY</span> <b style="color:{'var(--green)' if r.get('rs_positive') else 'var(--red)'}">{'✓' if r.get('rs_positive') else '✗'}</b></span>
          </div>
          <p style="color:#b0bec5;font-size:11px;line-height:1.7;font-style:italic">{narrativa_advisor(r)}</p>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title">Melhor Posicionados — Análise Técnica Consolidada</h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:14px">
    Top 3 ETFs com maior alinhamento de momentum multi-período, tendência e força relativa.
    Baseado em critérios académicos e de prática profissional (Faber, Antonacci, AQR).
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
            "FORTE COMPRA": ("var(--green)",       "#1b3a2a"),
            "COMPRA":       ("var(--light-green)", "#1e2f1a"),
            "POTENCIAL":    ("var(--yellow)",       "#2a2510"),
        }
        clr, bg = level_colors.get(s["level"], ("var(--blue)", "#0d1021"))
        pct = s.get("score_pct")
        pct_html = (
            f'<span style="color:var(--muted);font-size:10px">P{pct*100:.0f}</span>'
            if pct is not None and str(pct) != "nan" else ""
        )
        rsi = s.get("rsi", 50) or 50
        rsi_c = "var(--green)" if 40 <= rsi <= 65 else ("var(--yellow)" if rsi > 70 else "var(--red)" if rsi < 35 else "var(--muted)")

        cards += f"""
        <div style="background:{bg};border-left:4px solid {clr};padding:12px 16px;margin:6px 0;border-radius:4px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="color:var(--text);font-size:17px;font-weight:bold">{s['ticker']}</span>
            <span style="color:var(--muted);font-size:11px">{s['nome']}</span>
            <span style="background:{clr};color:#000;padding:1px 8px;border-radius:8px;font-size:10px;font-weight:bold">{s['level']}</span>
            <span style="color:{s['cor']};font-size:10px">● {s['categoria']}</span>
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
          <div style="color:var(--muted);font-size:11px;margin-top:6px;font-style:italic">{s.get('rationale','')}</div>
          <p style="color:#9fa8da;font-size:11px;margin-top:8px;line-height:1.6;font-style:italic">{narrativa_simples(s)}</p>
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
        if score >= 0.65: return "#1b3a2a"
        if score >= 0.55: return "#1e2f1a"
        if score >= 0.45: return "#2a2510"
        if score >= 0.35: return "#2a1508"
        return "#2a1010"

    items = ""
    for c in cats:
        mom_color = {"▲": "var(--green)", "→": "var(--muted)", "▼": "var(--red)"}.get(c["momentum"], "var(--muted)")
        bg = score_to_bg(c["score_avg"])
        items += f"""
        <div class="cat-tile" style="background:{bg};border-left:3px solid {c['color']}">
          <div style="color:{c['color']};font-size:10px;font-weight:bold;margin-bottom:4px">{c['name']}</div>
          <div style="font-size:20px;font-weight:bold;color:{'var(--green)' if c['score_avg']>=0.5 else 'var(--red)'}">{c['score_avg']:.3f}</div>
          <div style="font-size:10px;color:{mom_color};margin-top:2px">{c['momentum']} {c['n']} ETFs · top {c['score_max']:.3f}</div>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title">Rotação por Categoria</h2>
  <div class="cat-grid">{items}</div>
</section>"""


def etf_table_section(scores_df: pd.DataFrame, cmap: dict) -> str:
    rows_js = []
    for _, r in scores_df.iterrows():
        sym  = str(r.get("etf", ""))
        info = cmap.get(sym, {})
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
        })

    rows_json = json.dumps(rows_js, ensure_ascii=False)
    return f"""
<section class="section">
  <h2 class="section-title">Todos os ETFs</h2>
  <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
    <input id="tbl-search" type="text" placeholder="Pesquisar ETF ou categoria…"
      style="background:#0d1021;border:1px solid var(--border);color:var(--text);
             padding:6px 12px;border-radius:4px;font-size:12px;width:220px">
    <select id="tbl-filter" style="background:#0d1021;border:1px solid var(--border);
             color:var(--text);padding:6px 10px;border-radius:4px;font-size:12px">
      <option value="">Todos</option>
      <option value="FORTE COMPRA">FORTE COMPRA</option>
      <option value="COMPRA">COMPRA</option>
      <option value="POTENCIAL">POTENCIAL</option>
      <option value="score_high">Score ≥ 0.60</option>
    </select>
  </div>
  <div style="overflow-x:auto">
    <table id="etf-table" style="border-collapse:collapse;width:100%;min-width:900px;font-size:11px">
      <thead>
        <tr id="tbl-head" style="background:#0d1021;color:var(--blue)">
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
        </tr>
      </thead>
      <tbody id="etf-tbody"></tbody>
    </table>
  </div>
  <script>
    const ETF_ROWS = {rows_json};
    let sortCol = "score", sortAsc = false;

    function convictionLevel(row) {{
      const s = row.score, trend = row.trend, macd = row.macd,
            rsi = row.rsi, rs = row.rs, r5d = row.r5d, dd = row.dd;
      const vol_thresh = 0.07;
      const late = rsi > 68 || r5d > vol_thresh;
      let sigs = (trend?1:0)+(macd?1:0)+(rsi>=40&&rsi<=65?1:0)+(rs?1:0)+(r5d<0.04?1:0)+(dd>-0.08?1:0);
      if (!late && s >= 0.62 && sigs >= 6) return "FORTE COMPRA";
      if (!late && s >= 0.54 && sigs >= 4) return "COMPRA";
      if (s >= 0.48 && sigs >= 3) return "POTENCIAL";
      return null;
    }}

    function pctColor(v) {{ return v >= 0 ? "var(--green)" : "var(--red)"; }}
    function rsiColor(v) {{ return (v>=40&&v<=65)?"var(--green)":(v>70?"var(--yellow)":(v<30?"var(--red)":"var(--muted)")); }}
    function flagHtml(v, t, f) {{
      return `<span style="color:${{v?'var(--green)':'var(--red)'}}">${{v?t:f}}</span>`;
    }}

    function renderTable(rows) {{
      const tbody = document.getElementById("etf-tbody");
      const td = "padding:5px 10px;border-bottom:1px solid #0d1021";
      tbody.innerHTML = rows.map(r => {{
        const lvl = convictionLevel(r);
        const lvlBadge = lvl ? `<span style="background:${{
          lvl==='FORTE COMPRA'?'var(--green)':lvl==='COMPRA'?'var(--light-green)':'var(--yellow)'
        }};color:#000;padding:1px 6px;border-radius:6px;font-size:9px;font-weight:bold">${{lvl}}</span>` : "";
        return `<tr style="background:#0f1117">
          <td style="${{td}};color:var(--text);font-weight:bold">
            <span style="color:${{r.cat_color}}">●</span> ${{r.ticker}} ${{lvlBadge}}
          </td>
          <td style="${{td}};color:var(--muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{r.nome}}</td>
          <td style="${{td}};color:${{r.cat_color}};white-space:nowrap">${{r.cat}}</td>
          <td style="${{td}};color:${{r.score>=0.5?'var(--green)':'var(--red)'}};font-weight:bold;text-align:right">${{r.score.toFixed(3)}}</td>
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
        </tr>`;
      }}).join("");
    }}

    function applyFilters() {{
      const q = document.getElementById("tbl-search").value.toLowerCase();
      const f = document.getElementById("tbl-filter").value;
      let rows = [...ETF_ROWS];
      if (q) rows = rows.filter(r => r.ticker.toLowerCase().includes(q) || r.nome.toLowerCase().includes(q) || r.cat.toLowerCase().includes(q));
      if (f === "score_high") rows = rows.filter(r => r.score >= 0.60);
      else if (f) rows = rows.filter(r => convictionLevel(r) === f);
      rows.sort((a, b) => {{
        const va = a[sortCol], vb = b[sortCol];
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
    palette  = ["#7c83fd","#4caf50","#ffd54f","#f44336","#29b6f6"]
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
            x: {{ ticks: {{ color:"#666", maxTicksLimit:8, font:{{size:10}} }},
                   grid: {{ color:"#1e2130" }} }},
            y: {{ min:0, max:1, ticks: {{ color:"#666", font:{{size:10}} }},
                   grid: {{ color:"#1e2130" }} }}
          }},
          plugins: {{
            legend: {{ labels: {{ color:"#e8eaf6", font:{{size:11}} }} }},
            tooltip: {{ backgroundColor:"#0d1021" }}
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
            <div style="display:flex;align-items:center;gap:12px;padding:7px 0;border-bottom:1px solid #0d1021;flex-wrap:wrap">
              <span style="background:{clr};color:#000;padding:1px 8px;border-radius:8px;font-size:10px;font-weight:bold;min-width:90px;text-align:center">{lvl}</span>
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
</section>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
<style>
:root {
  --bg: #0f1117; --card: #0d1021; --border: #1e2130; --text: #e8eaf6;
  --muted: #666; --green: #4caf50; --light-green: #8bc34a; --yellow: #ffd54f;
  --red: #f44336; --orange: #ff7043; --blue: #7c83fd; --blue-light: #29b6f6;
}
*  { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text);
       font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       font-size: 13px; }
header { background: #0a0c14; border-bottom: 1px solid var(--border);
         padding: 14px 24px; position: sticky; top: 0; z-index: 100; }
.header-inner { max-width: 1400px; margin: 0 auto; display: flex;
                justify-content: space-between; align-items: center; }
.logo   { color: var(--blue); font-size: 20px; font-weight: bold; }
.subtitle { color: var(--muted); font-size: 11px; }
.main   { max-width: 1400px; margin: 0 auto; padding: 20px 24px; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(140px,1fr));
                gap: 12px; margin-bottom: 20px; }
.card { background: var(--card); border-radius: 8px; padding: 16px; }
.section { background: var(--card); border-radius: 8px; padding: 20px;
           margin-bottom: 16px; }
.section-title { color: var(--blue); font-size: 15px; margin-bottom: 14px; }
.cat-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(180px,1fr)); gap: 10px; }
.cat-tile { padding: 12px; border-radius: 4px; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tab-btn { background: #0a0c14; border: 1px solid var(--border); color: var(--muted);
           padding: 4px 14px; border-radius: 4px; cursor: pointer; font-size: 11px; }
.tab-btn.active { color: var(--text); border-color: var(--blue); }
footer { text-align: center; color: var(--muted); font-size: 10px;
         padding: 20px 0 32px; border-top: 1px solid var(--border); }
</style>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_dashboard(cfg: dict) -> None:
    data = load_data(cfg)
    if not data:
        print("[SKIP] Sem dados para o dashboard.")
        return

    ts = datetime.now(timezone.utc).strftime("%d/%m/%Y  %H:%M UTC")
    signals = build_buy_signals(data["rows_raw"], top_n=10)

    sections = [
        header_html(data["spy_close"], data["spy_sma200"], data["spy_regime"], ts, n_etfs=len(data["scores_df"])),
        '<div class="main">',
        summary_cards_html(signals, data["scores_df"]),
        buy_signals_section(signals),
        advisor_section(data["rows_raw"]),
        category_heatmap_section(data["cats"]),
        history_chart_section(data["hist_df"], data["scores_df"]),
        backtest_section(data["bt_df"]),
        etf_table_section(data["scores_df"], data["cmap"]),
        '</div>',
        '<footer>ET-Spotter · dados via yfinance · não constitui aconselhamento financeiro</footer>',
    ]

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>ET-Spotter Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  {CSS}
</head>
<body>
{"".join(sections)}
</body>
</html>"""

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
