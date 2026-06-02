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
from utils import load_config, get_category_map, build_buy_signals, category_summary, compute_advisor_score, build_advisor_candidates, _pct, _etf_row_raw
from paths import DATA_DAILY, REPORTS, SCORES_HIST
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


# ── Sections ──────────────────────────────────────────────────────────────────

def about_strip_html() -> str:
    return """
<div style="border-bottom:1px solid var(--border);background:var(--deep);padding:16px 0 20px">
  <div style="max-width:1400px;margin:0 auto;padding:0 24px">

    <p style="color:var(--muted);font-size:0.72rem;line-height:1.6;margin-bottom:14px">
      <span style="font-family:'SFMono-Regular','Roboto Mono',Consolas,monospace;
                   font-size:0.62rem;letter-spacing:0.12em;text-transform:uppercase;
                   color:var(--gold);margin-right:6px">ET-SPOTTER</span>
      — Monitorização automática de ETFs UCITS com sinais técnicos acionáveis e alertas por Email e Telegram.
    </p>

    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px">

      <div>
        <p style="color:var(--muted);font-size:0.68rem;line-height:1.7;margin-bottom:8px">
          ET‑Spotter recolhe dados diários e intradiários via yfinance e calcula indicadores técnicos.
          Gera um score técnico composto (0–1) por ETF e classifica sinais em
          <span style="color:var(--green)">FORTE COMPRA</span>,
          <span style="color:var(--light-green)">COMPRA</span> e
          <span style="color:var(--yellow)">POTENCIAL</span>.
        </p>
        <p style="color:var(--muted);font-size:0.67rem;line-height:1.6;margin-bottom:4px">
          <strong style="color:var(--champagne);font-size:0.62rem;letter-spacing:0.06em;text-transform:uppercase">Benefícios</strong>
        </p>
        <ul style="color:var(--muted);font-size:0.67rem;line-height:1.75;list-style:none;padding:0">
          <li style="padding-left:10px;position:relative"><span style="position:absolute;left:0;color:var(--gold)">·</span>Decisão mais rápida e menos emocional com sinais baseados em confluência de indicadores.</li>
          <li style="padding-left:10px;position:relative"><span style="position:absolute;left:0;color:var(--gold)">·</span>Transparência e auditabilidade: histórico e regras versionados em CSV no repositório.</li>
          <li style="padding-left:10px;position:relative"><span style="position:absolute;left:0;color:var(--gold)">·</span>Operacionalidade: alertas práticos para gerir posições em tempo real.</li>
        </ul>
      </div>

      <div>
        <p style="color:var(--muted);font-size:0.67rem;line-height:1.6;margin-bottom:4px">
          <strong style="color:var(--champagne);font-size:0.62rem;letter-spacing:0.06em;text-transform:uppercase">Fundamentação académica</strong>
        </p>
        <ul style="color:var(--muted);font-size:0.67rem;line-height:1.75;list-style:none;padding:0;margin-bottom:10px">
          <li><span style="color:var(--patina);margin-right:5px">✓</span>Baseia-se em 30+ anos de investigação académica (Jegadeesh, Titman, Faber, Sharpe)</li>
          <li><span style="color:var(--patina);margin-right:5px">✓</span>Valida cada factor independentemente (multicolinearidade &lt; 1.2)</li>
          <li><span style="color:var(--patina);margin-right:5px">✓</span>Exige convergência de múltiplos sinais (reduz falsos positivos)</li>
          <li><span style="color:var(--patina);margin-right:5px">✓</span>Demonstra edge estatístico comprovado (FORTE COMPRA: +1.7%/mês, p &lt; 0.05)</li>
          <li><span style="color:var(--patina);margin-right:5px">✓</span>Reconhece limitações (forward bias, regime-dependência, custos)</li>
        </ul>
        <p style="color:var(--muted);font-size:0.67rem;line-height:1.6">
          <strong style="color:var(--champagne)">Para quem:</strong>
          Investidores individuais europeus que seguem estratégias quantitativas baseadas em evidência académica
          e querem um fluxo de sinais técnicos transparentes e reproduzíveis.
        </p>
      </div>

      <div style="border-left:1px solid var(--border);padding-left:20px">
        <p style="color:var(--muted);font-size:0.67rem;line-height:1.6;margin-bottom:4px">
          <strong style="color:var(--champagne);font-size:0.62rem;letter-spacing:0.06em;text-transform:uppercase">Nota legal</strong>
        </p>
        <p style="color:var(--muted);font-size:0.65rem;line-height:1.7;font-style:italic">
          ET‑Spotter fornece informação técnica e resultados de backtest; não constitui aconselhamento financeiro.
          Use os sinais como input sistemático, não como recomendação isolada.
          Um sistema que não prediz preços futuros, mas identifica períodos de convergência estatística
          de múltiplos factores — quando a probabilidade de retorno positivo no horizonte de momentum
          (21 dias) é significativamente elevada acima do acaso.
        </p>
      </div>

    </div>
  </div>
</div>"""

def header_html(spy_close, spy_sma200, spy_regime, ts, n_etfs: int = 0) -> str:
    regime_color = "var(--green)" if spy_regime == "BULL" else ("var(--red)" if spy_regime == "BEAR" else "var(--muted)")
    spy_str = f"SPY {spy_close:.2f}" if spy_close else "SPY —"
    sma_str = f"SMA200 {spy_sma200:.2f}" if spy_sma200 else ""
    regime_badge = (
        f'<span style="background:{regime_color};color:#000;padding:2px 8px;'
        f'border-radius:2px;font-size:11px;font-weight:bold">{spy_regime}</span>'
    )
    return f"""
<header>
  <div class="header-inner">
    <div>
      <div class="logo">ET-SPOTTER</div>
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
        <div class="card" style="border-top:1px solid {color}">
          <div style="font-size:26px;font-weight:600;font-family:'Albert Sans',sans-serif;color:{color}">{value}</div>
          <div style="font-family:'SFMono-Regular','Roboto Mono',Consolas,monospace;font-size:0.62rem;letter-spacing:0.14em;text-transform:uppercase;color:var(--muted);margin-top:6px">{label}</div>
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
        bar_color      = "var(--green)"  if pts >= 70 else ("var(--yellow)" if pts >= 50 else "var(--muted)")
        bar_border_clr = "oklch(48% 0.09 188)" if pts >= 70 else ("oklch(48% 0.12 80)" if pts >= 50 else "var(--border)")

        ret_252d = float(r.get("ret_252d", 0) or 0)
        ret_126d = float(r.get("ret_126d", 0) or 0)
        momentum = (ret_252d - float(r.get("ret_21d", 0) or 0)) if ret_252d != 0 else (ret_126d - float(r.get("ret_21d", 0) or 0))
        mom_label = "Mom.12-1M" if ret_252d != 0 else "Mom.6-1M"

        cards += f"""
        <div style="background:var(--bg);border:1px solid {bar_border_clr};padding:14px 16px;
                    margin:8px 0;border-radius:2px">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
            <span style="font-size:18px">{medal}</span>
            <span style="color:var(--text);font-size:16px;font-weight:bold">{html_mod.escape(r['ticker'])}</span>
            <span style="color:var(--muted);font-size:11px">{html_mod.escape(r['nome'])}</span>
            <span style="color:{r['cor']};font-size:10px">● {html_mod.escape(r['categoria'])}</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <span style="color:var(--muted);font-size:11px">Score técnico</span>
            <div style="flex:1;background:var(--border);border-radius:4px;height:7px;max-width:200px">
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
          <p style="color:var(--muted);font-size:11px;line-height:1.7;font-style:italic">{narrativa_advisor(r)}</p>
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

        cards += f"""
        <div style="background:{bg};border:1px solid {border_clr};padding:12px 16px;margin:6px 0;border-radius:2px">
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
          <p style="color:var(--muted);font-size:11px;margin-top:8px;line-height:1.6;font-style:italic">{narrativa_simples(s)}</p>
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
      style="width:220px">
    <select id="tbl-filter">
      <option value="">Todos</option>
      <option value="FORTE COMPRA">FORTE COMPRA</option>
      <option value="COMPRA">COMPRA</option>
      <option value="POTENCIAL">POTENCIAL</option>
      <option value="score_high">Score ≥ 0.60</option>
    </select>
  </div>
  <div style="overflow-x:auto">
    <table id="etf-table" style="border-collapse:collapse;width:100%;min-width:900px;font-size:11px;background:var(--bg)">
      <thead>
        <tr id="tbl-head" style="background:var(--deep);color:var(--champagne)">
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

    const CONV_STRONG_SCORE = {CONVICTION_STRONG_BUY_SCORE}, CONV_STRONG_SIGS = {CONVICTION_STRONG_BUY_SIGNALS};
    const CONV_BUY_SCORE    = {CONVICTION_BUY_SCORE},        CONV_BUY_SIGS    = {CONVICTION_BUY_SIGNALS};
    const CONV_POT_SCORE    = {CONVICTION_POTENTIAL_SCORE},  CONV_POT_SIGS    = {CONVICTION_POTENTIAL_SIGNALS};

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
      const tbody = document.getElementById("etf-tbody");
      const td = "padding:5px 10px;border-bottom:1px solid var(--border)";
      tbody.innerHTML = rows.map(r => {{
        const lvl = convictionLevel(r);
        const lvlBadge = lvl ? `<span style="background:${{
          lvl==='FORTE COMPRA'?'var(--green)':lvl==='COMPRA'?'var(--light-green)':'var(--yellow)'
        }};color:#000;padding:1px 6px;border-radius:2px;font-size:9px;font-weight:bold">${{lvl}}</span>` : "";
        return `<tr style="background:var(--bg)">
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
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1px;
  margin-bottom: 16px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.card { background: var(--surface); padding: 20px 16px; }

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

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
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
        about_strip_html(),
        '<div class="main">',
        summary_cards_html(signals, data["scores_df"]),
        advisor_section(data["rows_raw"]),
        buy_signals_section(signals),
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
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
