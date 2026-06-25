"""
Gera data/reports/dashboard.html — dashboard visual permanentemente actualizado.

Lê: scores_latest.csv, scores_history.csv, backtest_signals.csv (opcional), SPY diário.
Produz: HTML auto-suficiente com Chart.js (CDN), tabela ordenável/pesquisável, sparklines.
"""

import html as html_mod
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_category_map, build_buy_signals, category_summary, compute_advisor_score, build_advisor_candidates, _pct, _etf_row_raw, get_etf_metadata, level_display
from paths import DATA_DAILY, REPORTS, SCORES_HIST, PORTFOLIO
from constants import (
    CONVICTION_STRONG_BUY_SCORE, CONVICTION_STRONG_BUY_SIGNALS,
    CONVICTION_BUY_SCORE,        CONVICTION_BUY_SIGNALS,
    CONVICTION_POTENTIAL_SCORE,  CONVICTION_POTENTIAL_SIGNALS,
    LEVEL_STRONG, LEVEL_BUY, LEVEL_POTENTIAL,
)

# ── Monetisation config ────────────────────────────────────────────────────────
BEEHIIV_URL           = "https://et-spotter.beehiiv.com"   # newsletter subscription page
DEGIRO_AFFILIATE_LINK = ""   # e.g. "https://www.degiro.eu/?referral=XXXXXXXX"


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
    signal_deltas: list[dict] = []
    if not hist_df.empty and "score" in hist_df.columns and "etf" in hist_df.columns:
        for etf_sym, grp in hist_df.groupby("etf"):
            grp_sorted = grp.sort_values("date")
            if len(grp_sorted) >= 2:
                prev = float(grp_sorted["score"].iloc[-2] or 0)
                curr = float(grp_sorted["score"].iloc[-1] or 0)
                delta_map[str(etf_sym)] = round(curr - prev, 4)

        def _score_level(s: float) -> str | None:
            if s >= 0.62: return LEVEL_STRONG
            if s >= 0.54: return LEVEL_BUY
            if s >= 0.48: return LEVEL_POTENTIAL
            return None

        level_order = {None: 0, LEVEL_POTENTIAL: 1, LEVEL_BUY: 2, LEVEL_STRONG: 3}
        dates_sorted = sorted(hist_df["date"].unique())
        if len(dates_sorted) >= 2:
            prev_d = dates_sorted[-2]
            curr_d = dates_sorted[-1]
            prev_df = hist_df[hist_df["date"] == prev_d][["etf", "score"]].copy()
            curr_df = hist_df[hist_df["date"] == curr_d][["etf", "score"]].copy()
            prev_df["prev_level"] = prev_df["score"].apply(_score_level)
            curr_df["curr_level"] = curr_df["score"].apply(_score_level)
            merged_d = curr_df.merge(prev_df[["etf", "prev_level"]], on="etf", how="left")
            for _, row in merged_d.iterrows():
                cl = row["curr_level"]
                pl = row.get("prev_level")
                direction = level_order.get(cl, 0) - level_order.get(pl, 0)
                if direction != 0:
                    signal_deltas.append({
                        "etf": str(row["etf"]),
                        "prev_level": pl,
                        "curr_level": cl,
                        "score": float(row["score"]),
                        "direction": direction,
                    })
        signal_deltas.sort(key=lambda x: (-x["direction"], -x["score"]))

    # rows completos para build_buy_signals
    rows_raw = [
        _etf_row_raw(str(r.get("etf", "")), r, cmap.get(str(r.get("etf", "")), {}), delta_map.get(str(r.get("etf", "")), 0.0))
        for r in scores_df.to_dict("records")
    ]

    df_for_cats = pd.DataFrame([{
        "etf": r["ticker"], "score": r["score"],
        "ret_24h": r.get("ret_24h", 0),
        "delta_score": r["delta_score"],
    } for r in rows_raw])
    cats = category_summary(df_for_cats, cfg)

    return {
        "scores_df":     scores_df,
        "rows_raw":      rows_raw,
        "cats":          cats,
        "hist_df":       hist_df,
        "bt_df":         bt_df,
        "cmap":          cmap,
        "spy_close":     spy_close,
        "spy_sma200":    spy_sma200,
        "spy_regime":    spy_regime,
        "signal_deltas": signal_deltas,
    }


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _c(v: float, neutral: float = 0) -> str:
    return "var(--green)" if v >= neutral else "var(--red)"


def _num(v, digits=3) -> str:
    return f"{v:.{digits}f}" if pd.notna(v) else "—"


# ── Inline SVG icons (24×24, no background, glow stroke) ─────────────────────

_ICON = {
    "dashboard": '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke="#00D4FF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"><rect x="2" y="2" width="7" height="7" rx="1.5"/><rect x="11" y="2" width="7" height="7" rx="1.5"/><rect x="2" y="11" width="7" height="7" rx="1.5"/><rect x="11" y="11" width="7" height="7" rx="1.5"/></g></svg>',
    "scoring":   '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke="#00D4FF" stroke-width="1.5" stroke-linecap="round" fill="none"><path d="M3 15 A8 8 0 0 1 17 15"/><line x1="4.5" y1="11.5" x2="6" y2="9.5"/><line x1="10" y1="7" x2="10" y2="9"/><line x1="15.5" y1="11.5" x2="14" y2="9.5"/><line x1="10" y1="14" x2="14" y2="8"/><circle cx="10" cy="14" r="1.5" fill="#00D4FF" stroke="none"/></g></svg>',
    "etfs":      '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke-linecap="round"><line x1="5" y1="3" x2="5" y2="17" stroke="#00FF9D" stroke-width="1.5"/><rect x="3" y="6" width="4" height="8" rx="0.5" fill="#00FF9D" stroke="none"/><line x1="10" y1="3" x2="10" y2="17" stroke="#FF4466" stroke-width="1.5"/><rect x="8" y="8" width="4" height="5" rx="0.5" fill="#FF4466" stroke="none"/><line x1="15" y1="3" x2="15" y2="17" stroke="#4D9FFF" stroke-width="1.5"/><rect x="13" y="5" width="4" height="9" rx="0.5" fill="#4D9FFF" stroke="none"/></g></svg>',
    "data":      '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke="#4D9FFF" stroke-width="1.5" stroke-linecap="round" fill="none"><ellipse cx="10" cy="6" rx="7" ry="2.5"/><path d="M3 6v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5V6"/><path d="M3 10v4c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5v-4"/></g></svg>',
    "chart":     '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke="#7C83FD" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"><polyline points="2,16 5,11 9,13 13,7 18,9"/><line x1="2" y1="18" x2="18" y2="18" stroke-width="1"/></g></svg>',
    "backtest":  '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke-linecap="round" stroke-linejoin="round" fill="none"><rect x="2" y="2" width="16" height="16" rx="2" stroke="#FFB800" stroke-width="1.5"/><line x1="2" y1="8" x2="18" y2="8" stroke="#FFB800" stroke-width="0.8" opacity="0.5"/><polyline points="5,14 8,10 12,12 15,7" stroke="#00FF9D" stroke-width="1.5"/></g></svg>',
    "portfolio": '<svg viewBox="0 0 20 20" width="20" height="20" style="display:inline-block;vertical-align:middle;margin-right:8px;flex-shrink:0"><g stroke="#7C83FD" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"><rect x="2" y="7" width="16" height="11" rx="2"/><path d="M7 7V5a3 3 0 0 1 6 0v2"/><line x1="10" y1="11" x2="10" y2="15"/><line x1="7" y1="13" x2="13" y2="13"/></g></svg>',
}


def _icon(name: str) -> str:
    return _ICON.get(name, "")


# ── Glow divider (slim, inline SVG) ──────────────────────────────────────────

_GLOW_DIVIDER = """\
<div style="margin:4px 0 8px;overflow:hidden;line-height:0">
<svg viewBox="0 0 1200 12" width="100%" height="12" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gd" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%"   stop-color="#0A0F1A"/>
      <stop offset="20%"  stop-color="#00D4FF" stop-opacity="0.7"/>
      <stop offset="50%"  stop-color="#7C83FD"/>
      <stop offset="80%"  stop-color="#00D4FF" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="#0A0F1A"/>
    </linearGradient>
    <filter id="gf"><feGaussianBlur stdDeviation="2"/></filter>
  </defs>
  <line x1="0" y1="6" x2="1200" y2="6" stroke="#00D4FF" stroke-width="4" opacity="0.18" filter="url(#gf)"/>
  <line x1="0" y1="6" x2="1200" y2="6" stroke="url(#gd)" stroke-width="1"/>
  <polygon points="600,3 604,6 600,9 596,6" fill="#7C83FD"/>
</svg>
</div>"""


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
    OPEN SOURCE · MIT LICENSE · DATA: YFINANCE
  </text>
  <rect x="0" y="142" width="1280" height="1" fill="url(#bb_rule)"/>
</svg>"""


def ticker_html(signals_all: list[dict], spy_regime: str, avg_score: float, n_etfs: int) -> str:
    """Full-width scrolling ticker strip with live daily data."""
    regime_color = "#00FF9D" if spy_regime == "BULL" else ("#FF4466" if spy_regime == "BEAR" else "#4A6080")
    regime_label = f'<span style="color:{regime_color};font-weight:800">SPY {spy_regime}</span>'

    strong_buys = [s for s in signals_all if s["level"] == LEVEL_STRONG]
    buys        = [s for s in signals_all if s["level"] == LEVEL_BUY]

    etf_items = ""
    for s in strong_buys[:5]:
        sym   = s.get("etf", "")
        score = s.get("score", 0)
        etf_items += f' <span style="color:#00FF9D;font-weight:700">{sym}</span> <span style="color:#4A6080">{score:.2f}</span> ·'
    for s in buys[:3]:
        sym   = s.get("etf", "")
        score = s.get("score", 0)
        etf_items += f' <span style="color:#00D4FF">{sym}</span> <span style="color:#4A6080">{score:.2f}</span> ·'

    n_sb   = len(strong_buys)
    n_b    = len(buys)
    signal_summary = (
        f'<span style="color:#00FF9D;font-weight:700">'
        f'{n_sb} <span data-i18n="signal.strong_buy">RADAR MÁXIMO</span></span>'
        if n_sb else
        f'<span style="color:#4A6080">'
        f'0 <span data-i18n="signal.strong_buy">RADAR MÁXIMO</span></span>'
    )
    signal_summary += (
        f' · <span style="color:#00D4FF">'
        f'{n_b} <span data-i18n="signal.buy">EM DESTAQUE</span></span>'
    )

    # build text segment (will be duplicated for seamless loop)
    seg = (
        f'&nbsp;&nbsp;◈ ET-SPOTTER · {regime_label} · {signal_summary} ·'
        f'{etf_items}'
        f' <span data-i18n="ticker.score_label">Score médio</span>'
        f' <span style="color:#FFB800;font-weight:700">{avg_score:.3f}</span> ·'
        f' {n_etfs} <span data-i18n="ticker.etfs_label">ETFs UCITS analisados</span> ·'
        f' <span data-i18n="ticker.updated">Actualizado diariamente após o fecho</span> ·'
        f' <span data-i18n="common.free">Grátis</span> · Open Source ·'
        f' &nbsp;&nbsp;'
    )
    # duplicate for seamless infinite scroll
    track = seg * 2

    return f"""
<div style="width:100%;overflow:hidden;background:#03050d;border-bottom:1px solid #00D4FF18;
            padding:5px 0;white-space:nowrap;position:relative;z-index:100">
  <div style="display:inline-block;animation:et-ticker 55s linear infinite;
              font-size:0.62rem;letter-spacing:0.07em;font-family:'Albert Sans',sans-serif;
              color:#4A6080">
    {track}
  </div>
</div>
<style>
@keyframes et-ticker {{
  0%   {{ transform: translateX(0); }}
  100% {{ transform: translateX(-50%); }}
}}
</style>"""


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
        f"SPY {spy_price} {arrow} SMA200 {sma_price}. "
        f"BULL = S&P 500 above 200-day SMA (uptrend). "
        f"BEAR = below (downtrend)."
    )
    regime_badge = (
        f'<span title="{regime_tip}" data-i18n-title="header.regime_tip" data-spy="{spy_price}" data-sma="{sma_price}" data-arrow="{arrow}" '
        f'style="background:{regime_color};color:#000;padding:2px 8px;'
        f'border-radius:2px;font-size:11px;font-weight:bold;cursor:help">{spy_regime}</span>'
    )
    return f"""
<div class="top-accent"></div>
<header>
  <div class="header-inner">
    <div>
      <div class="logo">ET-SPOTTER</div>
      <div class="subtitle" data-i18n="header.subtitle" data-i18n-options='{{"count": {n_etfs}}}'>{n_etfs} ETFs europeus · nota diária de 0 a 1</div>
    </div>
    <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:8px">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end">
        {regime_badge}
        <div style="display:flex;align-items:center;border:1px solid #1E2D4D;border-radius:3px;overflow:hidden;font-size:0.68rem;font-family:inherit;letter-spacing:0.08em">
          <button id="lang-pt" onclick="window.setLanguage&&window.setLanguage('pt')"
            style="background:transparent;border:none;border-right:1px solid #1E2D4D;
                   color:#00D4FF;padding:3px 9px;cursor:pointer;font-size:inherit;
                   font-family:inherit;letter-spacing:inherit;font-weight:700">PT</button>
          <button id="lang-en" onclick="window.setLanguage&&window.setLanguage('en')"
            style="background:transparent;border:none;
                   color:#4A6080;padding:3px 9px;cursor:pointer;font-size:inherit;
                   font-family:inherit;letter-spacing:inherit">EN</button>
        </div>
      </div>
      <div style="color:var(--muted);font-size:11px;display:flex;align-items:center">
        <span class="live-dot"></span><span data-i18n="header.updated">Actualizado:</span> {ts}
      </div>
    </div>
  </div>
  <nav class="nav-tab-bar" style="border-top:1px solid #1E2D4D22;margin-top:10px;padding-top:2px;max-width:1400px;margin-left:auto;margin-right:auto">
    <button class="nav-tab active" onclick="switchTab('overview',this)" data-i18n="nav.overview">Overview</button>
    <button class="nav-tab" onclick="switchTab('signals',this)" data-i18n="nav.signals">Scores &amp; Alertas</button>
    <button class="nav-tab" onclick="switchTab('reports',this)" data-i18n="nav.reports">Relatórios</button>
    <button class="nav-tab" onclick="switchTab('guides',this)" data-i18n="nav.guides">Guias</button>
  </nav>
</header>
<script>
function switchTab(tab, btn) {{
  ['overview','signals','reports','guides'].forEach(function(t) {{
    var el = document.getElementById('tab-'+t);
    if (el) el.style.display = t === tab ? '' : 'none';
  }});
  document.querySelectorAll('.nav-tab').forEach(function(b) {{ b.classList.remove('active'); }});
  if (btn) btn.classList.add('active');
}}
</script>"""


def hero_plain_html(signals_all: list[dict], n_etfs: int, spy_regime: str) -> str:
    """Hero simples em linguagem corrente — primeira secção do Overview."""
    top3 = [s for s in signals_all if s.get("level")][:3]

    regime_key = (f"plainhero.regime_{spy_regime.lower()}"
                  if spy_regime in ("BULL", "BEAR") else "plainhero.regime_unknown")
    regime_fallback = {"BULL": "mercado em alta (SPY acima da SMA200)",
                       "BEAR": "mercado em baixa (SPY abaixo da SMA200)"}.get(
                           spy_regime, "regime de mercado indeterminado")
    regime_color = "#00FF9D" if spy_regime == "BULL" else ("#FF4466" if spy_regime == "BEAR" else "#8A9CC0")

    if top3:
        cards_html = ""
        for s in top3:
            ret63 = s.get("ret_63d", 0) or 0
            dir_key = "plainhero.top_etf_up" if ret63 >= 0 else "plainhero.top_etf_down"
            dir_fallback = f'{"subiu" if ret63 >= 0 else "caiu"} {abs(ret63):.1%} nos últimos 3 meses'
            pct_val = f"{abs(ret63):.1%}"
            lv = level_display(s.get("level"))
            lv_color = {"RADAR MÁXIMO": "#00FF9D", "EM DESTAQUE": "#00D4FF", "A OBSERVAR": "#FFB800"}.get(lv, "#7C83FD")
            cards_html += f"""
<div style="flex:1;min-width:160px;background:#0A1628;border:1px solid {lv_color}44;
            border-top:2px solid {lv_color};border-radius:8px;padding:14px 16px">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
    <span style="color:#E8F0FF;font-size:0.85rem;font-weight:800">{s['ticker']}</span>
    <span style="background:{lv_color};color:#000;padding:1px 8px;border-radius:2px;
                 font-size:0.58rem;font-weight:800" data-i18n="signal.{'strong_buy' if 'MÁXIMO' in lv else ('buy' if 'DESTAQUE' in lv else 'potential')}">{lv}</span>
  </div>
  <div style="color:#4A6080;font-size:0.62rem;margin-bottom:6px">{s.get('nome','')[:35]}</div>
  <div style="color:{lv_color};font-size:1.5rem;font-weight:900;line-height:1">{s['score']:.2f}</div>
  <div style="color:#4A6080;font-size:0.58rem;margin-top:4px"
       data-i18n="{dir_key}" data-i18n-options='{{"pct":"{pct_val}"}}'>{dir_fallback}</div>
</div>"""
        content_html = f'<div style="display:flex;gap:10px;flex-wrap:wrap;margin:16px 0">{cards_html}</div>'
    else:
        content_html = '<p style="color:#4A6080;font-size:0.85rem;margin:16px 0" data-i18n="plainhero.no_signals">Sem destaques hoje — não forçamos sinais quando o mercado não os dá.</p>'

    body_fallback = (f"Todos os dias, depois do fecho dos mercados, comparamos {n_etfs} ETFs europeus "
                     f"e damos a cada um uma nota de 0 a 1. Vês num relance quais estão a ganhar força "
                     f"— e recebes tudo por email, de graça.")

    return f"""
<div style="background:#060C1A;border:1px solid #1E2D4D;border-radius:10px;padding:20px 22px;margin-bottom:16px">
  <h1 style="color:#E8F0FF;font-size:1.25rem;font-weight:800;margin:0 0 8px" data-i18n="plainhero.title">
    Que ETFs estão mais fortes hoje?
  </h1>
  <p style="color:#8A9CC0;font-size:0.82rem;margin:0 0 10px;line-height:1.5"
     data-i18n="plainhero.body" data-i18n-options='{{"count":{n_etfs}}}'>
    {body_fallback}
  </p>
  <div style="margin-bottom:12px">
    <span style="color:{regime_color};font-size:0.75rem;font-weight:700">◉ {spy_regime}</span>
    <span style="color:#4A6080;font-size:0.72rem"> — <span
      data-i18n="{regime_key}">{regime_fallback}</span></span>
  </div>
  {content_html}
  <a href="#subscribe-section" style="display:inline-block;background:#FFB800;color:#000;
     font-size:0.80rem;font-weight:800;padding:10px 22px;border-radius:6px;
     text-decoration:none;margin-top:4px" data-i18n="plainhero.cta">
    Recebe isto por email todos os dias — grátis
  </a>
  <p style="color:#4A6080;font-size:0.58rem;margin:8px 0 0" data-i18n="plainhero.disclaimer">
    Informação estatística, não é recomendação de investimento.
  </p>
</div>"""


def hero_bar_html(n_etfs: int = 97, n_total: int = 97) -> str:
    """Hero stat strip with fintech premium CSS design."""
    etf_sub = f"de {n_total}" if n_etfs != n_total else str(n_total)
    stats = [
        (str(n_etfs), "ETFs UCITS",       etf_sub, "hero.universe",     "#00D4FF", "#00D4FF33",
         f"{n_etfs} ETFs europeus UCITS analisados todos os dias",
         "hero.etfs_ucits", ""),
        ("11",        "Categorias",       "mundo · sectores · obrigações", "hero.factors_desc", "#7C83FD", "#7C83FD33",
         "Mundo · Sectores · Obrigações · Commodities",
         "hero.factors", ""),
        ("23h",       "No teu email",     "hora de Lisboa",   "hero.daily_desc",   "#FFB800", "#FFB80033",
         "Relatório diário enviado às 23h (hora de Lisboa)",
         "hero.daily", ""),
        ("Grátis",    "Sem cartão",       "zero subscrição",  "hero.cost_desc",    "#00FF9D", "#00FF9D33",
         "Open source · GitHub Actions · sem servidores pagos",
         "hero.cost", "common.free"),
        ("0–1",       "Nota simples",     "quanto mais alta, mais forte", "hero.score_desc", "#4D9FFF", "#4D9FFF33",
         "Score cross-sectional: 0 = fraco · 1 = muito forte",
         "hero.score", ""),
    ]
    cards = ""
    for val, label, sub, sub_key, color, glow, tip, label_key, val_key in stats:
        if sub_key == "hero.universe":
            of_span  = f'<span data-i18n="summary.of">de</span> ' if n_etfs != n_total else ''
            sub_html = f'{of_span}{n_total} <span data-i18n="hero.universe">no universo</span>'
        else:
            sub_html = f'<span data-i18n="{sub_key}">{sub}</span>'
        val_html = f'<span data-i18n="{val_key}">{val}</span>' if val_key else val
        cards += f"""<div title="{tip}" style="
            flex:1;min-width:100px;padding:16px 12px;text-align:center;
            background:#0D1525;border:1px solid {color}33;border-top:2px solid {color};
            border-radius:6px;display:flex;flex-direction:column;align-items:center;gap:4px">
          <span style="color:{color};font-size:28px;font-weight:800;line-height:1;
                       text-shadow:0 0 20px {color},0 0 40px {color}88">{val_html}</span>
          <span data-i18n="{label_key}" style="color:#A0B4CC;font-size:0.60rem;letter-spacing:0.12em;text-transform:uppercase;font-weight:600">{label}</span>
          <span style="color:#4A6080;font-size:0.52rem;letter-spacing:0.03em">{sub_html}</span>
        </div>"""
    return f"""
<div style="margin:16px 0 0;padding:0">
  <div style="display:flex;gap:8px;flex-wrap:wrap">{cards}</div>
</div>"""


def articles_section_html() -> str:
    """Grid of SEO article cards linking to the static article pages."""
    site = "https://nunovinhas-creator.github.io/ET-spotter"
    articles = [
        {
            "href": f"{site}/vwce-vs-iwda.html",
            "tag": "COMPARATIVO",
            "title_pt": "VWCE vs IWDA — Qual o Melhor ETF Global?",
            "title_en": "VWCE vs IWDA — Which Global ETF Is Best?",
            "desc_pt": "Diferenças de TER, dividendos, liquidez e impostos para investidores portugueses.",
            "desc_en": "TER differences, dividends, liquidity and taxes for European investors.",
            "color": "#00D4FF",
        },
        {
            "href": f"{site}/melhor-etf-europa.html",
            "tag": "GUIA",
            "title_pt": "Melhor ETF para Europeus em 2026",
            "title_en": "Best ETF for Europeans in 2026",
            "desc_pt": "Como escolher ETFs UCITS com base em score quant, TER e regime de mercado.",
            "desc_en": "How to choose UCITS ETFs based on quant score, TER and market regime.",
            "color": "#00FF9D",
        },
        {
            "href": f"{site}/etf-esg-europa.html",
            "tag": "ESG",
            "title_pt": "ETFs ESG na Europa: Vale a Pena?",
            "title_en": "ESG ETFs in Europe: Is It Worth It?",
            "desc_pt": "Análise quantitativa de performance, TER e critérios de selecção ESG.",
            "desc_en": "Quantitative analysis of performance, TER and ESG selection criteria.",
            "color": "#7C83FD",
        },
        {
            "href": f"{site}/estrategia-momentum.html",
            "tag": "ESTRATÉGIA",
            "title_pt": "Estratégia de Momentum com ETFs",
            "title_en": "Momentum Strategy with ETFs",
            "desc_pt": "Como aplicar Dual Momentum (Antonacci, 2014) com ETFs UCITS acessíveis.",
            "desc_en": "How to apply Dual Momentum (Antonacci, 2014) with accessible UCITS ETFs.",
            "color": "#FFB800",
        },
        {
            "href": f"{site}/guia-etf-ucits.html",
            "tag": "INICIANTE",
            "title_pt": "Guia Completo de ETFs UCITS",
            "title_en": "Complete Guide to UCITS ETFs",
            "desc_pt": "O que são ETFs UCITS, como funcionam e como começar a investir na Europa.",
            "desc_en": "What UCITS ETFs are, how they work and how to start investing in Europe.",
            "color": "#FF6B9D",
        },
    ]
    cards_html = ""
    for a in articles:
        cards_html += f"""
  <a href="{a['href']}" target="_blank" rel="noopener" class="article-card"
     style="border-color:{a['color']}22;--card-accent:{a['color']}">
    <span class="article-card-tag" style="color:{a['color']}">{a['tag']}</span>
    <div class="article-card-title">
      <span class="lang-pt-only">{a['title_pt']}</span>
      <span class="lang-en-only">{a['title_en']}</span>
    </div>
    <div class="article-card-desc">
      <span class="lang-pt-only">{a['desc_pt']}</span>
      <span class="lang-en-only">{a['desc_en']}</span>
    </div>
    <span class="article-card-cta" style="color:{a['color']}">
      <span class="lang-pt-only">Ler artigo →</span>
      <span class="lang-en-only">Read article →</span>
    </span>
  </a>"""

    return f"""
<section class="section" id="guides-section">
  <h2 class="section-title" style="display:flex;align-items:center">
    {_icon("chart")}
    <span class="lang-pt-only">Guias &amp; Artigos</span>
    <span class="lang-en-only">Guides &amp; Articles</span>
  </h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:20px">
    <span class="lang-pt-only">Análises aprofundadas sobre ETFs UCITS, estratégias de momentum e investimento quantitativo na Europa.</span>
    <span class="lang-en-only">In-depth analyses on UCITS ETFs, momentum strategies and quantitative investing in Europe.</span>
  </p>
  <div class="articles-grid">{cards_html}
  </div>
</section>"""


def subscribe_section_html() -> str:
    """Email capture (Beehiiv form)."""
    return f"""
<section class="section" id="subscribe-section"
  style="background:linear-gradient(135deg,#08111f 0%,#0d1a2e 100%);
         border:1px solid #00D4FF18;border-radius:8px;margin:12px 0">
  <div style="padding:28px 20px;text-align:center">
    <div style="color:var(--green);font-size:0.58rem;letter-spacing:0.14em;font-weight:700;margin-bottom:8px">
      ● DAILY SIGNAL
    </div>
    <div style="font-size:1rem;font-weight:700;color:var(--text);margin-bottom:6px"
         data-i18n="subscribe.title">
      Recebe o relatório diário às 22h
    </div>
    <div style="color:var(--muted);font-size:0.75rem;margin-bottom:20px;
                max-width:380px;margin-left:auto;margin-right:auto;line-height:1.6"
         data-i18n="subscribe.desc">
      Score de todos os ETFs · alerta de regime SPY · rotação de categorias — grátis.
    </div>
    <div style="display:flex;justify-content:center;padding:16px 0">
      <div style="width:100%;max-width:340px">
        <script async src="https://subscribe-forms.beehiiv.com/v3/loader.js" data-beehiiv-form="d4e78e22-ed6f-401d-b41b-75f1e9b316fa"></script>
        <script type="text/javascript" async src="https://subscribe-forms.beehiiv.com/attribution.js"></script>
      </div>
    </div>
    <div style="color:var(--muted);font-size:0.68rem;margin-top:10px"
         data-i18n="subscribe.privacy">
      Sem spam. Cancelas quando quiseres.
    </div>
  </div>
</section>"""


def _panel(title: str, body: str, badge: str = "", title_key: str = "") -> str:
    k = f' data-i18n="{title_key}"' if title_key else ""
    badge_html = f'<span style="color:#4A6080;font-size:0.60rem">{badge}</span>' if badge else ""
    return (f'<div class="panel"><div class="panel-hdr">'
            f'<span class="panel-title"{k}>{title}</span>{badge_html}</div>'
            f'<div class="panel-body">{body}</div></div>')


def _score_pill(level: str | None) -> str:
    if level == LEVEL_STRONG:
        return '<span class="score-pill" style="background:#00FF9D;color:#000" data-i18n="signal.strong_short">Forte</span>'
    if level == LEVEL_BUY:
        return '<span class="score-pill" style="background:#00D4FF;color:#000" data-i18n="signal.buy_short">Compra</span>'
    if level == LEVEL_POTENTIAL:
        return '<span class="score-pill" style="background:#FFB800;color:#000" data-i18n="signal.pot">Pot.</span>'
    return '<span class="score-pill" style="background:#FF446655;color:#FF4466" data-i18n="signal.weak">Fraco</span>'


def _score_color(s: float) -> str:
    if s >= CONVICTION_STRONG_BUY_SCORE: return "#00FF9D"
    if s >= CONVICTION_BUY_SCORE:        return "#00D4FF"
    if s >= CONVICTION_POTENTIAL_SCORE:  return "#FFB800"
    return "#FF4466"


def overview_grid_html(rows_raw: list[dict], signals: list[dict],
                       scores_df, spy_close, spy_sma200, spy_regime, hist_df) -> str:
    """Two-column Bloomberg-style overview grid."""
    from utils import compute_conviction

    # ── Top ETF summary ──────────────────────────────────────────────────────
    top = rows_raw[0] if rows_raw else {}
    top_score = top.get("score", 0)
    top_level = compute_conviction(
        top_score, top.get("trend_sma",0), top.get("macd_bullish",0),
        top.get("rsi",50), top.get("rs_positive",0), top.get("ret_63d",0),
        top.get("delta_score",0), top.get("drawdown",-1),
        top.get("ret_5d",0), top.get("vol_21",0)
    )["level"]
    top_color = _score_color(top_score)

    summary_body = f"""
<div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
  <div>
    <span style="color:{top_color};font-size:52px;font-weight:800;line-height:1;
                 text-shadow:0 0 24px {top_color}88">{top_score:.2f}</span>
  </div>
  <div>
    <div style="margin-bottom:6px">{_score_pill(top_level)}</div>
    <div style="color:#E8F0FF;font-size:0.85rem;font-weight:700">{top.get("ticker","—")}</div>
    <div style="color:#4A6080;font-size:0.62rem;margin-top:2px;max-width:180px;
                overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{top.get("nome","")}</div>
  </div>
</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
  <div style="background:#090E1A;border-radius:4px;padding:10px;text-align:center">
    <div style="color:#7C83FD;font-size:1.3rem;font-weight:700">{top.get("ret_21d",0)*100:+.1f}%</div>
    <div data-i18n="metric.momentum" style="color:#4A6080;font-size:0.58rem;text-transform:uppercase;letter-spacing:.06em;margin-top:3px">Momentum</div>
  </div>
  <div style="background:#090E1A;border-radius:4px;padding:10px;text-align:center">
    <div style="color:#FFB800;font-size:1.3rem;font-weight:700">{top.get("vol_21",0)*100:.1f}%</div>
    <div data-i18n="metric.volatility" style="color:#4A6080;font-size:0.58rem;text-transform:uppercase;letter-spacing:.06em;margin-top:3px">Volatilidade</div>
  </div>
  <div style="background:#090E1A;border-radius:4px;padding:10px;text-align:center">
    <div style="color:#FF4466;font-size:1.3rem;font-weight:700">{top.get("drawdown",0)*100:.1f}%</div>
    <div data-i18n="metric.drawdown" style="color:#4A6080;font-size:0.58rem;text-transform:uppercase;letter-spacing:.06em;margin-top:3px">Drawdown</div>
  </div>
</div>"""
    left_summary = _panel("ETF Analysis Summary", summary_body,
                           f'Top scorer · {len(rows_raw)} <span data-i18n="summary.etfs_analyzed">ETFs analisados</span>',
                           title_key="panel.etf_summary")

    # ── Score history mini-chart ──────────────────────────────────────────────
    chart_labels, chart_datasets = [], []
    top5_tickers = [r["ticker"] for r in rows_raw[:5]]
    palette = ["#00D4FF","#7C83FD","#00FF9D","#FFB800","#FF4466"]
    if not hist_df.empty and "etf" in hist_df.columns and "date" in hist_df.columns:
        dates_all = sorted(hist_df["date"].unique())[-30:]
        chart_labels = [str(d)[-5:] for d in dates_all]
        for i, ticker in enumerate(top5_tickers):
            sub = hist_df[hist_df["etf"]==ticker].sort_values("date")
            sub = sub[sub["date"].isin(dates_all)]
            date_score = dict(zip(sub["date"].astype(str), sub["score"].round(3)))
            data = [date_score.get(str(d)) for d in dates_all]
            chart_datasets.append({
                "label": ticker,
                "data": data,
                "borderColor": palette[i],
                "backgroundColor": "transparent",
                "borderWidth": 1.5,
                "pointRadius": 0,
                "tension": 0.3,
                "spanGaps": True,
            })

    chart_json_labels = json.dumps(chart_labels)
    chart_json_datasets = json.dumps(chart_datasets)
    chart_body = f"""
<div style="position:relative;height:140px">
  <canvas id="overviewChart"></canvas>
</div>
<script>
(function(){{
  var ctx = document.getElementById('overviewChart').getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: {chart_json_labels}, datasets: {chart_json_datasets} }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ display: true, position: 'top',
          labels: {{ color: '#4A6080', font: {{ size: 9 }}, boxWidth: 10, padding: 8 }} }},
        tooltip: {{ backgroundColor: '#0D1525', borderColor: '#1E2D4D', borderWidth: 1,
          titleColor: '#8BA4C8', bodyColor: '#E8F0FF', callbacks: {{
            label: function(c){{ return ' ' + c.dataset.label + ': ' + (c.parsed.y??'—'); }}
          }}}}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1E2D4D44' }}, ticks: {{ color: '#4A6080', font: {{ size: 9 }},
               maxTicksLimit: 6 }} }},
        y: {{ grid: {{ color: '#1E2D4D44' }}, ticks: {{ color: '#4A6080', font: {{ size: 9 }} }},
              min: 0, max: 1 }}
      }}
    }}
  }});
}})();
</script>"""
    left_chart = _panel("Score Trend — Top 5 ETFs (30 dias)", chart_body, title_key="panel.score_trend")

    # ── Key Indicators ────────────────────────────────────────────────────────
    regime_color = "#00FF9D" if spy_regime == "BULL" else "#FF4466"
    spy_p = f"{spy_close:.2f}" if spy_close else "—"
    sma_p = f"{spy_sma200:.2f}" if spy_sma200 else "—"
    avg_score = float(scores_df["score"].mean()) if "score" in scores_df.columns else 0
    n_strong = sum(1 for s in signals if s.get("level") == LEVEL_STRONG)

    def kpi(label, value, color="#E8F0FF", lkey=""):
        k = f' data-i18n="{lkey}"' if lkey else ""
        return (f'<div style="background:#090E1A;border-radius:4px;padding:9px 12px;'
                f'display:flex;flex-direction:column;gap:3px">'
                f'<span style="color:{color};font-size:1.0rem;font-weight:700">{value}</span>'
                f'<span{k} style="color:#4A6080;font-size:0.55rem;text-transform:uppercase;'
                f'letter-spacing:.06em">{label}</span></div>')

    kpi_body = f"""<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
  {kpi("Regime SPY", spy_regime, regime_color, "kpi.spy_regime")}
  {kpi("SPY Close",  spy_p,              "#E8F0FF", "kpi.spy_close")}
  {kpi("SMA 200",    sma_p,              "#8BA4C8", "kpi.sma200")}
  {kpi("Score Médio",   f"{avg_score:.3f}",                          "#7C83FD", "kpi.avg_score")}
  {kpi("Forte Compra",  str(n_strong),                               "#00FF9D", "kpi.strong_buy")}
  {kpi("Score > 0.50",  str(int((scores_df["score"]>=0.5).sum())),   "#4D9FFF", "kpi.score_above")}
</div>"""
    left_kpi = _panel("Key Indicators", kpi_body, title_key="panel.key_indicators")

    # ── Alertas Activos (right top) ───────────────────────────────────────────
    alert_icons = {LEVEL_STRONG: ("🟢","#00FF9D"), LEVEL_BUY: ("🔵","#00D4FF"),
                   LEVEL_POTENTIAL: ("🟡","#FFB800")}
    alerts_html = ""
    for s in signals[:6]:
        icon, color = alert_icons.get(s["level"], ("⚪","#4A6080"))
        ret5 = s.get("ret_5d", 0)
        ret5_str = f'{ret5*100:+.1f}%'
        alerts_html += f"""<div class="alert-item">
      <span style="font-size:14px;flex-shrink:0">{icon}</span>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="color:#E8F0FF;font-size:0.78rem;font-weight:700">{s["ticker"]}</span>
          {_score_pill(s["level"])}
          <span style="color:{_score_color(s["score"])};font-size:0.72rem;font-weight:700;margin-left:auto">{s["score"]:.3f}</span>
        </div>
        <div style="color:#4A6080;font-size:0.60rem;margin-top:3px;line-height:1.4">
          {s.get("nome","")[:40]} · 5d: <span style="color:{'#00FF9D' if ret5>=0 else '#FF4466'}">{ret5_str}</span>{'&nbsp;<span data-i18n="alert.correction" style="color:#8A9CC0;font-size:0.58rem">— em correcção; tendência mantém-se</span>' if ret5 < -0.05 else ""}
        </div>
      </div>
    </div>"""
    if not alerts_html:
        alerts_html = '<div data-i18n="signal.no_signals" style="color:#4A6080;font-size:0.72rem">Sem sinais activos hoje.</div>'
    right_alerts = _panel("Alertas Activos", alerts_html,
                           f'{len(signals)} <span data-i18n="panel.signals">sinais</span>',
                           title_key="panel.alerts")

    # ── Scores Recentes table (right middle) ──────────────────────────────────
    rows_sorted = sorted(rows_raw, key=lambda r: r["score"], reverse=True)[:10]
    tbl_rows = ""
    for r in rows_sorted:
        s = r["score"]
        color = _score_color(s)
        trend_icon = "↑" if r.get("trend_sma") else "↓"
        trend_color = "#00FF9D" if r.get("trend_sma") else "#FF4466"
        if r.get("drawdown", 0) > -0.05:
            risk_label, risk_key, risk_color = "Baixo", "table.risk_low", "#00FF9D"
        elif r.get("drawdown", 0) > -0.10:
            risk_label, risk_key, risk_color = "Médio", "table.risk_med", "#FFB800"
        else:
            risk_label, risk_key, risk_color = "Alto",  "table.risk_high", "#FF4466"
        tbl_rows += f"""<tr style="border-bottom:1px solid #1E2D4D22">
      <td style="padding:6px 4px;color:#E8F0FF;font-weight:700;font-size:0.72rem;white-space:nowrap">{r["ticker"]}</td>
      <td style="padding:6px 8px;text-align:right">
        <span style="color:{color};font-weight:700;font-size:0.75rem">{s:.3f}</span>
      </td>
      <td style="padding:6px 4px;text-align:center">{_score_pill(None if s < CONVICTION_POTENTIAL_SCORE else (LEVEL_STRONG if s>=CONVICTION_STRONG_BUY_SCORE else (LEVEL_BUY if s>=CONVICTION_BUY_SCORE else LEVEL_POTENTIAL)))}</td>
      <td style="padding:6px 4px;text-align:center;color:{trend_color};font-size:0.80rem">{trend_icon}</td>
      <td style="padding:6px 4px;text-align:right;color:{risk_color};font-size:0.65rem" data-i18n="{risk_key}">{risk_label}</td>
    </tr>"""

    _TH = "padding:4px;color:#4A6080;font-size:0.60rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase"
    scores_tbl = f"""<table style="width:100%;border-collapse:collapse">
  <thead>
    <tr style="border-bottom:1px solid #1E2D4D">
      <th style="{_TH};text-align:left;padding:4px 4px"><span data-i18n="table.etf">ETF</span></th>
      <th style="{_TH};text-align:right;padding:4px 8px"><span data-i18n="table.score">Score</span></th>
      <th style="{_TH};text-align:center"><span data-i18n="table.signal">Sinal</span></th>
      <th style="{_TH};text-align:center"><span data-i18n="table.trend">Tend.</span></th>
      <th style="{_TH};text-align:right"><span data-i18n="table.risk">Risco</span></th>
    </tr>
  </thead>
  <tbody>{tbl_rows}</tbody>
</table>"""
    right_table = _panel("Scores Recentes", scores_tbl, "top 10", title_key="panel.recent_scores")

    # ── ETF Heatmap (right bottom) ────────────────────────────────────────────
    top16 = rows_sorted[:16]
    heat_tiles = ""
    for r in top16:
        s = r["score"]
        # Map score 0-1 to green-yellow-red
        if s >= CONVICTION_STRONG_BUY_SCORE: bg, fg = "#00FF9D22", "#00FF9D"
        elif s >= CONVICTION_BUY_SCORE:      bg, fg = "#00D4FF22", "#00D4FF"
        elif s >= CONVICTION_POTENTIAL_SCORE: bg, fg = "#FFB80022", "#FFB800"
        elif s >= 0.35: bg, fg = "#4A608033", "#8BA4C8"
        else:           bg, fg = "#FF446622", "#FF4466"
        heat_tiles += (f'<div class="heat-tile" style="background:{bg};border:1px solid {fg}33" '
                       f'title="{r["ticker"]} — {r["nome"][:40]}">'
                       f'<div style="color:{fg};font-size:0.65rem;font-weight:800">{r["ticker"].replace(".L","").replace(".DE","")}</div>'
                       f'<div style="color:{fg};font-size:0.72rem;font-weight:700;margin-top:3px">{s:.2f}</div>'
                       f'</div>')
    right_heat = _panel("Heatmap de ETFs",
                        f'<div class="heat-grid">{heat_tiles}</div>',
                        "top 16", title_key="panel.heatmap")

    # ── Assemble grid ─────────────────────────────────────────────────────────
    return f"""
<div class="db-grid">
  <div class="db-col">
    {left_summary}
    {left_chart}
    {left_kpi}
  </div>
  <div class="db-col">
    {right_alerts}
    {right_table}
    {right_heat}
  </div>
</div>"""


def signal_legend_html(n_etfs: int = 0) -> str:
    """Mini-legenda de sinais — sempre visível, dá contexto antes dos cards."""
    ctx = (f'<span data-i18n="legend.of">de</span> {n_etfs} '
           f'<span data-i18n="legend.etfs_analyzed">ETFs analisados hoje:</span>') if n_etfs else ""
    return f"""
<div class="signal-legend">
  <span style="color:var(--muted);font-size:0.68rem">{ctx}</span>
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
    <span data-i18n="signal.strong_buy" style="background:var(--green);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">RADAR MÁXIMO</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ {CONVICTION_STRONG_BUY_SCORE} · <span data-i18n="legend.strong_buy_desc">percentil superior · todos os factores alinhados</span></span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <span data-i18n="signal.buy" style="background:var(--light-green);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">EM DESTAQUE</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ {CONVICTION_BUY_SCORE} · <span data-i18n="legend.buy_desc">sinal construtivo · maioria dos factores positivos</span></span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <span data-i18n="signal.potential" style="background:var(--yellow);color:#000;padding:2px 9px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.08em">A OBSERVAR</span>
    <span style="color:var(--muted);font-size:0.65rem">score ≥ {CONVICTION_POTENTIAL_SCORE} · <span data-i18n="legend.potential_desc">sinal incipiente · aguardar confirmação</span></span>
    <span style="color:var(--border);font-size:0.65rem">·</span>
    <a href="#" onclick="document.getElementById('explainer-details').open=true;document.getElementById('explainer-details').scrollIntoView({{behavior:'smooth'}});return false;"
       style="color:var(--patina);font-size:0.65rem;text-decoration:none"><span data-i18n="legend.guide">📖 guia completo ↓</span></a>
  </div>
</div>"""


def summary_cards_html(signals: list[dict], scores_df: pd.DataFrame) -> str:
    n_fc  = sum(1 for s in signals if s["level"] == LEVEL_STRONG)
    n_c   = sum(1 for s in signals if s["level"] == LEVEL_BUY)
    n_p   = sum(1 for s in signals if s["level"] == LEVEL_POTENTIAL)
    n_high = int((scores_df["score"] >= 0.50).sum()) if "score" in scores_df.columns else 0
    avg_score = scores_df["score"].mean() if "score" in scores_df.columns else 0
    n_ml_confirmed = sum(
        1 for s in signals
        if s.get("ml_prob") is not None and s["ml_prob"] >= 0.55
        and s["level"] in (LEVEL_STRONG, LEVEL_BUY)
    )

    def signal_card(label, label_key, value, color, bg, desc, desc_key=""):
        bar_w = min(100, int(float(str(value)) / max(n_fc + n_c + n_p, 1) * 100)) if str(value).isdigit() else 0
        bar_html = f'<div style="margin-top:8px;height:3px;background:#1E2D4D;border-radius:2px"><div style="width:{bar_w}%;height:3px;background:{color};border-radius:2px;box-shadow:0 0 6px {color}"></div></div>' if bar_w > 0 else ""
        dk = f' data-i18n="{desc_key}"' if desc_key else ""
        return f"""<div style="flex:1;min-width:120px;padding:16px 14px;
            background:linear-gradient(135deg,#0D1525,#0A0F1A);
            border:1px solid {color}44;border-left:3px solid {color};border-radius:6px">
          <div style="color:{color};font-size:36px;font-weight:800;line-height:1;
                      text-shadow:0 0 16px {color}">{value}</div>
          <div data-i18n="{label_key}" style="color:#E8F0FF;font-size:0.68rem;font-weight:700;letter-spacing:0.06em;
                      text-transform:uppercase;margin-top:6px">{label}</div>
          <div{dk} style="color:#4A6080;font-size:0.55rem;margin-top:3px">{desc}</div>
          {bar_html}
        </div>"""

    return f"""
<div style="display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 8px">
  {signal_card("Forte Compra", "summary.strong_buy", n_fc,  "#00FF9D", "#0D2318", f"score ≥ {CONVICTION_STRONG_BUY_SCORE} · todos factores alinhados", "summary.strong_buy_desc")}
  {signal_card("Compra",       "summary.buy",        n_c,   "#00D4FF", "#0A1A25", f"score ≥ {CONVICTION_BUY_SCORE} · sinal construtivo",                "summary.buy_desc")}
  {signal_card("Potencial",    "summary.potential",  n_p,   "#FFB800", "#1A1400", f"score ≥ {CONVICTION_POTENTIAL_SCORE} · aguardar confirmação",        "summary.potential_desc")}
  {signal_card("Score > 0.50", "summary.score_above",n_high,"#7C83FD", "#0F1020", f'<span data-i18n="summary.of">de</span> {len(scores_df)} <span data-i18n="summary.etfs_analyzed">ETFs analisados</span>')}
  {signal_card("Score Médio",  "summary.avg_score",  f"{avg_score:.3f}", "#4D9FFF", "#0A1020", "média cross-sectional", "summary.avg_score_desc")}
  {signal_card("ML ✓",        "summary.ml_confirmed", n_ml_confirmed, "#A78BFA", "#0E0A1A", "quant + XGBoost confirmados", "summary.ml_confirmed_desc")}
</div>"""


def explainer_section() -> str:
    """Painel colapsável 'Como ler este dashboard' — bilingual PT/EN."""
    _hdr = 'style="color:var(--patina);font-size:0.62rem;font-weight:bold;letter-spacing:0.10em;text-transform:uppercase;margin-bottom:6px"'
    _p   = 'style="color:var(--muted);font-size:0.72rem;line-height:1.7;margin:0"'
    _sub = 'style="color:var(--muted);font-size:0.70rem"'
    return f"""
<details id="explainer-details" style="margin-bottom:16px;border:1px solid var(--border);border-radius:2px;background:var(--surface)">
  <summary style="padding:10px 16px;cursor:pointer;list-style:none;display:flex;
                  justify-content:space-between;align-items:center;user-select:none">
    <span style="color:var(--text);font-size:0.75rem;font-weight:600;letter-spacing:0.04em"
          data-i18n="explainer.title">📖 Novo aqui? Guia completo — o que é um ETF, como ler o score, glossário</span>
    <span style="color:var(--muted);font-size:0.70rem" data-i18n="explainer.expand">clica para expandir</span>
  </summary>

  <!-- PT content -->
  <div class="lang-pt-only" style="padding:0 16px 16px;display:flex;flex-direction:column;gap:18px">
    <div>
      <div {_hdr}>O que é um ETF?</div>
      <p {_p}>Um ETF (fundo negociado em bolsa) funciona como um cabaz de ações: em vez de comprares uma empresa, compras um fundo que replica centenas de empresas ao mesmo tempo. É diversificado, barato e compra-se como uma ação normal. Os ETFs desta ferramenta são todos <b style="color:var(--text)">UCITS</b> — regulados para investidores europeus.</p>
    </div>
    <div>
      <div {_hdr}>Score Composto v3 — metodologia quantitativa</div>
      <p {_p} style="margin-bottom:8px">Cada ETF recebe um score cross-sectional de 0 a 1, calculado diariamente como média ponderada de 4 factores académicos. O ranking é relativo ao universo: um score de 0.62 significa que o ETF está no percentil superior do universo analisado nesse dia. <b style="color:var(--text)">Não é uma previsão de retorno</b> — é um snapshot quantitativo do alinhamento de factores no momento actual.</p>
      <div style="display:flex;flex-direction:column;gap:5px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--green);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">RADAR MÁXIMO</span>
          <span {_sub}>Score ≥ {CONVICTION_STRONG_BUY_SCORE} — percentil superior: momentum 12-1M forte, tendência confirmada (ADX &gt; 25), risco controlado, alpha positivo vs SPY</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--light-green);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">EM DESTAQUE</span>
          <span {_sub}>Score ≥ {CONVICTION_BUY_SCORE} — sinal construtivo: momentum médio-alto, preço acima da SMA200, Sharpe aceitável</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--yellow);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">A OBSERVAR</span>
          <span {_sub}>Score ≥ {CONVICTION_POTENTIAL_SCORE} — sinal incipiente: momentum positivo mas sem confirmação total de tendência ou risco ajustado</span>
        </div>
      </div>
    </div>
    <div>
      <div {_hdr}>Os 4 factores do score composto (pesos fixos)</div>
      <div style="display:flex;flex-direction:column;gap:7px">
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--green);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">M</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Momentum <span style="color:var(--muted);font-weight:400">35%</span></span><span {_sub}> — Retorno 12-1M (Jegadeesh &amp; Titman, 1993): retorno dos últimos 12 meses excluindo o último (neutraliza reversão de curto prazo). Combinado com janelas de 6M e 3M para robustez multi-período. A anomalia de continuação de retornos é a mais replicada em finanças académicas.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:#7c83fd;font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">T</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Tendência <span style="color:var(--muted);font-weight:400">25%</span></span><span {_sub}> — SMA50/200, MACD (Appel), ADX (Wilder, 1978), regime Faber (2007): posição do preço face às médias móveis, força direcional e cruzamentos de tendência. ADX &gt; 25 confirma tendência consolidada.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--blue-light);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">R</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Risco <span style="color:var(--muted);font-weight:400">25%</span></span><span {_sub}> — Rácio de Sharpe (1966), Calmar Ratio, Maximum Drawdown, volatilidade 21d (Ang et al., 2006): retorno ajustado ao risco por unidade de desvio-padrão e por queda máxima do pico ao vale.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--yellow);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">α</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Alpha <span style="color:var(--muted);font-weight:400">15%</span></span><span {_sub}> — Força Relativa vs SPY (Antonacci, 2014) + alpha101 cross-sectional (Kakushadze, 2015) + aceleração de momentum: liderança sobre o benchmark e qualidade de alpha composta. Dual Momentum: combina momentum absoluto e relativo.</span></div>
        </div>
      </div>
    </div>
    <div>
      <div {_hdr}>Referências académicas</div>
      <p {_p}>Jegadeesh &amp; Titman (1993) · Faber (2007) · Antonacci (2014) · Ang et al. (2006) · Kakushadze (2015) · AQR · Sharpe (1966) · Wilder (1978) · Moskowitz, Ooi &amp; Pedersen (2012)</p>
    </div>
    <div>
      <div {_hdr}>Glossário de termos</div>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline">
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">SMA200</span><span {_sub}>Simple Moving Average de 200 dias (Faber, 2007). Filtro de regime: preço &gt; SMA200 = BULL; abaixo = BEAR. O filtro de Faber demonstrou reduzir drawdowns em backtests de longo prazo sem sacrificar retorno.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RSI</span><span {_sub}>Relative Strength Index (Wilder, 1978). Oscilador 0–100: &gt;70 sobrecompra, &lt;30 sobrevenda. Zona saudável: 40–65.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">ADX</span><span {_sub}>Average Directional Index (Wilder, 1978). Força da tendência: ADX &gt; 25 = tendência consolidada; &lt; 20 = mercado lateral.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Drawdown</span><span {_sub}>Queda máxima do pico ao vale. Ex: −8% = está 8% abaixo do máximo recente.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">BULL / BEAR</span><span {_sub}>Regime de mercado (Faber, 2007): SPY &gt; SMA200 = BULL; SPY &lt; SMA200 = BEAR.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RS/SPY</span><span {_sub}>Força Relativa vs S&amp;P 500 (Antonacci, 2014). ✓ = o ETF supera o benchmark.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Sharpe</span><span {_sub}>Rácio de Sharpe (1966): retorno ajustado ao risco. &gt;1.0 = bom; &gt;2.0 = excelente.</span>
      </div>
    </div>
    <p style="color:var(--muted);font-size:0.65rem;font-style:italic;margin:0;border-top:1px solid var(--border);padding-top:10px">
      Esta ferramenta é para investigação técnica. Não constitui aconselhamento financeiro. Consulta sempre um profissional antes de investir.
    </p>
  </div>

  <!-- EN content -->
  <div class="lang-en-only" style="padding:0 16px 16px;display:flex;flex-direction:column;gap:18px">
    <div>
      <div {_hdr}>What is an ETF?</div>
      <p {_p}>An ETF (Exchange-Traded Fund) works like a basket of stocks: instead of buying one company, you buy a fund that tracks hundreds of companies at once. It is diversified, cheap, and traded like a regular stock. All ETFs in this tool are <b style="color:var(--text)">UCITS</b> — regulated for European investors.</p>
    </div>
    <div>
      <div {_hdr}>Composite Score v3 — quantitative methodology</div>
      <p {_p} style="margin-bottom:8px">Each ETF receives a cross-sectional score from 0 to 1, calculated daily as a weighted average of 4 academic factors. The ranking is relative to the universe: a score of 0.62 means the ETF is in the top percentile of the universe analysed that day. <b style="color:var(--text)">This is not a return forecast</b> — it is a quantitative snapshot of factor alignment at the current moment.</p>
      <div style="display:flex;flex-direction:column;gap:5px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--green);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">TOP RADAR</span>
          <span {_sub}>Score ≥ {CONVICTION_STRONG_BUY_SCORE} — top percentile: strong 12-1M momentum, confirmed trend (ADX &gt; 25), controlled risk, positive alpha vs SPY</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--light-green);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">HIGHLIGHTED</span>
          <span {_sub}>Score ≥ {CONVICTION_BUY_SCORE} — constructive signal: medium-high momentum, price above SMA200, acceptable Sharpe</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span style="background:var(--yellow);color:#000;font-size:0.60rem;font-weight:bold;padding:2px 8px;border-radius:2px;white-space:nowrap">WATCHING</span>
          <span {_sub}>Score ≥ {CONVICTION_POTENTIAL_SCORE} — nascent signal: positive momentum without full trend confirmation or adjusted risk</span>
        </div>
      </div>
    </div>
    <div>
      <div {_hdr}>The 4 factors of the composite score (fixed weights)</div>
      <div style="display:flex;flex-direction:column;gap:7px">
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--green);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">M</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Momentum <span style="color:var(--muted);font-weight:400">35%</span></span><span {_sub}> — 12-1M Return (Jegadeesh &amp; Titman, 1993): return over the past 12 months excluding the most recent (neutralises short-term reversal). Combined with 6M and 3M windows for multi-period robustness. The return continuation anomaly is the most replicated in academic finance.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:#7c83fd;font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">T</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Trend <span style="color:var(--muted);font-weight:400">25%</span></span><span {_sub}> — SMA50/200, MACD (Appel), ADX (Wilder, 1978), Faber (2007) regime: price position relative to moving averages, directional strength and trend crossovers. ADX &gt; 25 confirms consolidated trend.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--blue-light);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">R</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Risk <span style="color:var(--muted);font-weight:400">25%</span></span><span {_sub}> — Sharpe Ratio (1966), Calmar Ratio, Maximum Drawdown, 21d volatility (Ang et al., 2006): risk-adjusted return per unit of standard deviation and per peak-to-trough drawdown.</span></div>
        </div>
        <div style="display:flex;gap:10px;align-items:flex-start">
          <span style="color:var(--yellow);font-weight:bold;font-size:0.72rem;width:22px;flex-shrink:0">α</span>
          <div><span style="color:var(--text);font-size:0.72rem;font-weight:600">Alpha <span style="color:var(--muted);font-weight:400">15%</span></span><span {_sub}> — Relative Strength vs SPY (Antonacci, 2014) + alpha101 cross-sectional (Kakushadze, 2015) + momentum acceleration: benchmark leadership and composite alpha quality. Dual Momentum: combines absolute and relative momentum.</span></div>
        </div>
      </div>
    </div>
    <div>
      <div {_hdr}>Glossary of terms</div>
      <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 10px;align-items:baseline">
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">SMA200</span><span {_sub}>Simple Moving Average of 200 days (Faber, 2007). Trend regime filter: price &gt; SMA200 = BULL; below = BEAR. Faber's filter has demonstrated reduced drawdowns in long-term backtests without sacrificing return.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RSI</span><span {_sub}>Relative Strength Index (Wilder, 1978). Momentum oscillator 0–100: &gt;70 overbought, &lt;30 oversold. Healthy zone: 40–65.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">ADX</span><span {_sub}>Average Directional Index (Wilder, 1978). Trend strength: ADX &gt; 25 = consolidated trend; &lt; 20 = sideways market.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Drawdown</span><span {_sub}>Maximum peak-to-trough decline. E.g. −8% = 8% below its recent all-time high.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">BULL / BEAR</span><span {_sub}>Market regime (Faber, 2007): SPY &gt; SMA200 = BULL; SPY &lt; SMA200 = BEAR.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">RS/SPY</span><span {_sub}>Relative Strength vs S&amp;P 500 (Antonacci, 2014). ✓ = ETF outperforms the benchmark.</span>
        <span style="color:var(--text);font-size:0.70rem;font-weight:600;white-space:nowrap">Sharpe</span><span {_sub}>Sharpe Ratio (1966): risk-adjusted return. &gt;1.0 = good; &gt;2.0 = excellent.</span>
      </div>
    </div>
    <p style="color:var(--muted);font-size:0.65rem;font-style:italic;margin:0;border-top:1px solid var(--border);padding-top:10px">
      This tool is for technical research only. It does not constitute financial advice. Always consult a professional before investing.
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


def narrativa_simples_en(s: dict) -> str:
    """English mirror of narrativa_simples() — humanised buy-signal paragraph."""
    nome    = _nome_curto(s)
    ret_63d = float(s.get("ret_63d", 0) or 0)
    ret_5d  = float(s.get("ret_5d",  0) or 0)
    rsi     = float(s.get("rsi",    50) or 50)
    rs_pos  = bool(s.get("rs_positive", 0))

    if abs(ret_63d) < 0.01:
        p1 = f"{nome} is consolidating without significant movement over the past 3 months"
    elif ret_63d >= 0.10:
        p1 = f"{nome} is showing notable medium-term strength ({ret_63d:+.1%} over the past 3 months)"
    elif ret_63d >= 0.03:
        p1 = f"{nome} has been gaining ground over the past 3 months ({ret_63d:+.1%})"
    elif ret_63d >= 0:
        p1 = f"{nome} records a modest gain over the past 3 months ({ret_63d:+.1%})"
    else:
        p1 = f"{nome} is in recovery mode after a weaker period ({ret_63d:+.1%} over the past 3 months)"

    if ret_5d <= -0.05:
        p2 = f"However, it pulled back {ret_5d:+.1%} this week — a drop that created a meaningful technical discount from recent highs"
    elif ret_5d <= -0.02:
        p2 = f"However, it stepped back {ret_5d:+.1%} this week — a healthy pause that opens an entry window"
    elif ret_5d < 0:
        p2 = f"The slight correction of {ret_5d:+.1%} this week moved the price away from more expensive zones"
    elif ret_5d <= 0.01:
        p2 = f"This week it held steady, consolidating gains without selling pressure"
    elif ret_5d <= 0.04:
        p2 = f"It rose {ret_5d:+.1%} this week, with momentum gaining traction"
    else:
        p2 = f"It accelerated {ret_5d:+.1%} this week — note that entries after rapid rallies warrant extra caution"

    if rsi < 35:
        p3 = f"The RSI ({rsi:.0f}) is in oversold territory, which may signal an imminent reversal"
    elif rsi <= 50:
        p3 = f"The RSI ({rsi:.0f}) shows the price has pulled back from expensive zones to a technically ideal entry point — essentially 'on sale'"
    elif rsi <= 62:
        p3 = f"The RSI ({rsi:.0f}) remains in a balanced zone, with no signs of excessive overbought conditions"
    elif rsi <= 68:
        p3 = f"The RSI ({rsi:.0f}) is warming up, but still within acceptable bounds"
    else:
        p3 = f"The RSI ({rsi:.0f}) is already in hot territory — the remaining indicators support the thesis, but a brief wait may improve the entry point"

    if rs_pos:
        closing = ", and it is also outperforming the broad US market over the same period."
    else:
        closing = "."

    return f"{p1}. {p2}. {p3}{closing}"


def _sub_bars_html(r: dict) -> str:
    """Breakdown visual dos 4 sub-scores: M / T / R / α."""
    mom = r.get("_momentum")
    trd = r.get("_trend")
    rsk = r.get("_risk")
    alp = r.get("_alpha")
    if None in (mom, trd, rsk, alp):
        return ""

    def bar(label, name, i18n_key, val, color):
        pct = round(val * 100)
        name_span = (f'<span style="color:var(--muted);font-weight:normal" data-i18n="{i18n_key}">{name}</span>'
                     if i18n_key else f'<span style="color:var(--muted);font-weight:normal">{name}</span>')
        return (
            f'<div style="display:flex;align-items:center;gap:7px">'
            f'<span style="color:{color};font-size:10px;font-weight:bold;width:80px;flex-shrink:0">'
            f'{label} {name_span}</span>'
            f'<div style="flex:1;background:var(--border);border-radius:3px;height:5px;overflow:hidden">'
            f'<div style="width:{pct}%;background:{color};border-radius:3px;height:5px"></div>'
            f'</div>'
            f'<span style="color:var(--muted);font-size:10px;width:30px;text-align:right;flex-shrink:0">{val:.2f}</span>'
            f'</div>'
        )

    return (
        '<div style="display:flex;flex-direction:column;gap:5px;margin-bottom:10px">'
        + bar("M", "Momentum",  "metric.momentum", mom, "var(--green)")
        + bar("T", "Tendência", "metric.trend",    trd, "#7c83fd")
        + bar("R", "Risco",     "metric.risk",     rsk, "var(--blue-light)")
        + bar("α", "Alpha",     "",                alp, "var(--yellow)")
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
            <span style="color:var(--muted);font-size:11px" data-i18n="advisor.tech_score">Score técnico</span>
            <div style="flex:1;background:var(--border);border-radius:4px;height:7px;max-width:200px">
              <div style="width:{pts}%;background:{bar_color};border-radius:4px;height:7px"></div>
            </div>
            <span style="color:{bar_color};font-weight:bold;font-size:13px">{pts}/100</span>
          </div>
          {_sub_bars_html(r)}
          <div style="display:flex;gap:14px;flex-wrap:wrap;font-size:11px;margin-bottom:10px">
            <span><span style="color:var(--muted)">{mom_label}</span> <b style="color:{'var(--green)' if momentum>=0 else 'var(--red)'}">{_pct(momentum)}</b></span>
            <span><span style="color:var(--muted)" data-i18n="advisor.ret3m">Ret.3M</span> <b style="color:{'var(--green)' if r.get('ret_63d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_63d',0))}</b></span>
            <span><span style="color:var(--muted)" data-i18n="advisor.ret5d">Ret.5d</span> <b style="color:{'var(--green)' if r.get('ret_5d',0)>=0 else 'var(--red)'}">{_pct(r.get('ret_5d',0))}</b></span>
            <span><span style="color:var(--muted)">RSI</span> <b style="color:{'var(--green)' if 35<=rsi<=65 else 'var(--yellow)'}">{rsi:.0f}</b></span>
            <span><span style="color:var(--muted)">ADX</span> <b style="color:{'var(--green)' if r.get('adx',0)>=25 else 'var(--muted)'}">{r.get('adx',0):.0f}</b></span>
            <span><span style="color:var(--muted)">Sharpe</span> <b style="color:{'var(--green)' if r.get('sharpe_63',0)>=1 else 'var(--muted)'}">{r.get('sharpe_63',0):.1f}</b></span>
            <span><span style="color:var(--muted)">RS/SPY</span> <b style="color:{'var(--green)' if r.get('rs_positive') else 'var(--red)'}">{'✓' if r.get('rs_positive') else '✗'}</b></span>
          </div>
          <div style="color:var(--border);font-size:0.58rem;letter-spacing:0.08em;margin-bottom:2px" data-i18n="advisor.disclaimer">ANÁLISE GERADA AUTOMATICAMENTE · NÃO CONSTITUI ACONSELHAMENTO FINANCEIRO</div>
          <p class="lang-pt-only" style="color:var(--muted);font-size:11px;line-height:1.7;font-style:italic">{narrativa_advisor(r)}</p>
          <p class="lang-en-only" style="color:var(--muted);font-size:11px;line-height:1.7;font-style:italic">Quantitative technical analysis — multi-period momentum, trend regime, relative strength and entry quality. Score: {pts}/100.</p>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("dashboard")}<span data-i18n="section.best_positioned">Melhor Posicionados — Análise Técnica Consolidada</span></h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:10px" data-i18n="advisor.section_desc">
    Top 3 ETFs com maior alinhamento de momentum multi-período, tendência e força relativa.
    Baseado em critérios académicos: Jegadeesh &amp; Titman (1993), Faber (2007), Antonacci (2014), Ang et al. (2006), Kakushadze (2015), AQR, Sharpe.
  </p>
  {cards}
  <p style="color:var(--muted);font-size:10px;margin-top:12px;font-style:italic" data-i18n="advisor.legal">
    Análise técnica baseada em evidência histórica. Não constitui aconselhamento financeiro nem garantia de retorno.
  </p>
</section>"""


def buy_signals_section(signals: list[dict]) -> str:
    if not signals:
        return '<section class="section"><p style="color:var(--muted)" data-i18n="buy.no_signals">Sem confluência de sinais suficiente.</p></section>'

    cards = ""
    for s in signals:
        level_colors = {
            LEVEL_STRONG:   ("var(--green)",       "oklch(13% 0.045 188)", "oklch(48% 0.09 188)"),
            LEVEL_BUY:      ("var(--light-green)", "oklch(12% 0.025 188)", "oklch(38% 0.08 188)"),
            LEVEL_POTENTIAL:("var(--yellow)",       "oklch(13% 0.04 80)",   "oklch(48% 0.12 80)"),
        }
        clr, bg, border_clr = level_colors.get(s["level"], ("var(--muted)", "var(--bg)", "var(--border)"))
        pct = s.get("score_pct")
        pct_html = (
            f'<span style="color:var(--muted);font-size:10px">P{pct*100:.0f}</span>'
            if pct is not None and str(pct) != "nan" else ""
        )
        rsi = s.get("rsi", 50) or 50
        rsi_c = "var(--green)" if 40 <= rsi <= 65 else ("var(--yellow)" if rsi > 70 else "var(--red)" if rsi < 35 else "var(--muted)")

        forte_class = ' class="signal-forte"' if s["level"] == LEVEL_STRONG else ""
        level_label_key = {LEVEL_STRONG: "signal.strong_buy", LEVEL_BUY: "signal.buy", LEVEL_POTENTIAL: "signal.potential"}.get(s["level"], "signal.potential")

        ml_prob = s.get("ml_prob")
        ml_confirmed = ml_prob is not None and ml_prob >= 0.55
        ml_badge = ""
        if ml_prob is not None:
            ml_color = "#00FF9D" if ml_confirmed else "#4A6080"
            ml_icon  = "🤖 ML ✓" if ml_confirmed else "🤖 ML"
            ml_badge = (f'<span title="XGBoost: probabilidade de retorno positivo a 21 dias = {ml_prob:.0%}" '
                        f'style="background:{ml_color}22;color:{ml_color};border:1px solid {ml_color}44;'
                        f'padding:1px 7px;border-radius:2px;font-size:0.58rem;font-weight:700;cursor:help">'
                        f'{ml_icon} {ml_prob:.0%}</span>')

        cards += f"""
        <div{forte_class} style="background:{bg};border:1px solid {border_clr};padding:12px 16px;margin:6px 0;border-radius:2px">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <span style="color:var(--text);font-size:17px;font-weight:bold">{html_mod.escape(s['ticker'])}</span>
            <span style="color:var(--muted);font-size:11px">{html_mod.escape(s['nome'])}</span>
            <span style="background:{clr};color:#000;padding:1px 8px;border-radius:2px;font-size:10px;font-weight:bold" data-i18n="{level_label_key}">{level_display(s['level'])}</span>
            <span style="color:{s['cor']};font-size:10px">● {html_mod.escape(s['categoria'])}</span>
            {ml_badge}
          </div>
          <div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap;font-size:11px">
            <span><span style="color:var(--muted)">Score</span> <b style="color:{clr}">{s['score']:.3f}</b> {pct_html}</span>
            <span><span style="color:var(--muted)" data-i18n="advisor.ret3m">Ret.3M</span> <b style="color:{'var(--green)' if s.get('ret_63d',0)>=0 else 'var(--red)'}">{_pct(s.get('ret_63d',0))}</b></span>
            <span><span style="color:var(--muted)" data-i18n="advisor.ret5d">Ret.5d</span> <b style="color:{'var(--green)' if s.get('ret_5d',0)>=0 else 'var(--red)'}">{_pct(s.get('ret_5d',0))}</b></span>
            <span><span style="color:var(--muted)">RSI</span> <b style="color:{rsi_c}">{rsi:.0f}</b></span>
            <span><span style="color:var(--muted)">ADX</span> <b style="color:{'var(--green)' if s.get('adx',0)>25 else 'var(--muted)'}">{s.get('adx',0):.0f}</b></span>
            <span><span style="color:var(--muted)" data-i18n="table.drawdown">Drawdown</span> <b style="color:{'var(--green)' if s.get('drawdown',0)>-0.05 else 'var(--red)'}">{_pct(s.get('drawdown',0))}</b></span>
            <span><span style="color:var(--muted)">RS/SPY</span> <b style="color:{'var(--green)' if s.get('rs_positive') else 'var(--red)'}">{'✓' if s.get('rs_positive') else '✗'}</b></span>
          </div>
          <div class="lang-pt-only" style="color:var(--muted);font-size:11px;margin-top:6px;font-style:italic">{html_mod.escape(s.get('rationale',''))}</div>
          <div class="lang-en-only" style="color:var(--muted);font-size:11px;margin-top:6px;font-style:italic">{html_mod.escape(s.get('rationale_en',''))}</div>
          <div style="color:var(--border);font-size:0.58rem;letter-spacing:0.08em;margin-top:6px;margin-bottom:2px" data-i18n="advisor.disclaimer">ANÁLISE GERADA AUTOMATICAMENTE · NÃO CONSTITUI ACONSELHAMENTO FINANCEIRO</div>
          <p class="lang-pt-only" style="color:var(--muted);font-size:11px;margin-top:0;line-height:1.6;font-style:italic">{html_mod.escape(narrativa_simples(s))}</p>
          <p class="lang-en-only" style="color:var(--muted);font-size:11px;margin-top:0;line-height:1.6;font-style:italic">{html_mod.escape(narrativa_simples_en(s))}</p>
        </div>"""

    return f"""
<section class="section">
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("scoring")}<span data-i18n="section.buy_signals">Sinais de Compra</span></h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:12px" data-i18n="buy.section_desc">
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
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("etfs")}<span data-i18n="section.category_rotation">Rotação por Categoria</span></h2>
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
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("etfs")}<span data-i18n="section.all_etfs">Todos os ETFs</span></h2>
  <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
    <input id="tbl-search" type="text" placeholder="Pesquisar ETF ou categoria…" data-i18n-ph="search.placeholder"
      style="width:220px">
    <select id="tbl-filter">
      <option value="" data-i18n="search.all">Todos</option>
      <option value="STRONG_BUY" data-i18n="signal.strong_buy">RADAR MÁXIMO</option>
      <option value="BUY" data-i18n="signal.buy">EM DESTAQUE</option>
      <option value="POTENTIAL" data-i18n="signal.potential">A OBSERVAR</option>
      <option value="score_high">Score ≥ 0.60</option>
    </select>
    <button id="wl-toggle" onclick="toggleWatchlist()"
      style="background:var(--deep);border:1px solid var(--border);color:var(--muted);
             padding:6px 12px;border-radius:2px;cursor:pointer;font-size:0.8rem"
      data-i18n="search.watchlist">
      ☆ Watchlist
    </button>
  </div>
  <div style="overflow-x:auto">
    <table id="etf-table" style="border-collapse:collapse;width:100%;min-width:900px;font-size:11px;background:var(--bg)">
      <thead>
        <tr id="tbl-head" style="background:var(--deep);color:var(--champagne)">
          <th style="padding:7px 6px;text-align:center;cursor:pointer" title="Watchlist">☆</th>
          <th class="sortable" data-col="ticker"  style="padding:7px 10px;text-align:left;cursor:pointer;white-space:nowrap"><span data-i18n="table.etf">ETF</span> ↕</th>
          <th class="sortable" data-col="nome"    style="padding:7px 10px;text-align:left;cursor:pointer"><span data-i18n="table.name">Nome</span> ↕</th>
          <th class="sortable" data-col="cat"     style="padding:7px 10px;text-align:left;cursor:pointer"><span data-i18n="table.category">Categ.</span> ↕</th>
          <th class="sortable" data-col="score"   style="padding:7px 10px;text-align:right;cursor:pointer"><span data-i18n="table.score">Score</span> ↕</th>
          <th style="padding:7px 10px;text-align:right"><span data-i18n="table.pct">Pct.</span></th>
          <th class="sortable" data-col="r1d"  style="padding:7px 10px;text-align:right;cursor:pointer"><span data-i18n="table.day">Dia</span> ↕</th>
          <th class="sortable" data-col="r5d"  style="padding:7px 10px;text-align:right;cursor:pointer">5d ↕</th>
          <th class="sortable" data-col="r63d" style="padding:7px 10px;text-align:right;cursor:pointer">3M ↕</th>
          <th class="sortable" data-col="rsi"  style="padding:7px 10px;text-align:right;cursor:pointer">RSI ↕</th>
          <th class="sortable" data-col="adx"  style="padding:7px 10px;text-align:right;cursor:pointer">ADX ↕</th>
          <th class="sortable" data-col="dd"   style="padding:7px 10px;text-align:right;cursor:pointer"><span data-i18n="table.drawdown">Drawdown</span> ↕</th>
          <th style="padding:7px 10px;text-align:center"><span data-i18n="table.trend">Trend</span></th>
          <th style="padding:7px 10px;text-align:center">MACD</th>
          <th style="padding:7px 10px;text-align:center">RS/SPY</th>
          <th style="padding:7px 10px;text-align:center">SMA200</th>
          <th class="sortable" data-col="ter"     style="padding:7px 10px;text-align:right;cursor:pointer">TER ↕</th>
          <th class="sortable" data-col="aum"     style="padding:7px 10px;text-align:right;cursor:pointer">AuM Bn ↕</th>
          <th style="padding:7px 10px;text-align:center"><span data-i18n="table.replica">Réplica</span></th>
          <th style="padding:7px 10px;text-align:center"><span data-i18n="table.esg">ESG</span></th>
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
      btn.textContent = wlOnly
        ? (typeof i18next !== 'undefined' ? i18next.t('search.watchlist_on') : '★ Watchlist')
        : (typeof i18next !== 'undefined' ? i18next.t('search.watchlist')    : '☆ Watchlist');
      applyFilters();
    }}

    function convictionLevel(row) {{
      const s = row.score, trend = row.trend, macd = row.macd,
            rsi = row.rsi, rs = row.rs, r5d = row.r5d, dd = row.dd;
      const vol_thresh = 0.07;
      const late = rsi > 68 || r5d > vol_thresh;
      let sigs = (trend?1:0)+(macd?1:0)+(rsi>=40&&rsi<=65?1:0)+(rs?1:0)+(r5d<0.04?1:0)+(dd>-0.08?1:0);
      if (!late && s >= CONV_STRONG_SCORE && sigs >= CONV_STRONG_SIGS) return "STRONG_BUY";
      if (!late && s >= CONV_BUY_SCORE    && sigs >= CONV_BUY_SIGS)    return "BUY";
      if (s >= CONV_POT_SCORE             && sigs >= CONV_POT_SIGS)    return "POTENTIAL";
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
          lvl==='STRONG_BUY'?'var(--green)':lvl==='BUY'?'var(--light-green)':'var(--yellow)'
        }};color:#000;padding:1px 6px;border-radius:2px;font-size:9px;font-weight:bold">${{(window._ET_SIGNAL_LABELS||{{}})[lvl]||lvl}}</span>` : "";
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
            <span style="color:${{r.score>={CONVICTION_STRONG_BUY_SCORE}?'var(--green)':r.score>={CONVICTION_BUY_SCORE}?'var(--light-green)':r.score>={CONVICTION_POTENTIAL_SCORE}?'var(--yellow)':'var(--red)'}};font-weight:bold">${{r.score.toFixed(3)}}</span>
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
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("chart")}<span data-i18n="section.score_history">Evolução de Score — Top 5</span></h2>
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
    # Ler status do backtest — mostrar painel de acumulação se necessário
    status_path = REPORTS / "backtest_status.json"
    if status_path.exists():
        try:
            bst = json.load(open(status_path))
            if bst.get("status") == "A_ACUMULAR":
                days     = bst.get("history_days", 0)
                min_days = bst.get("min_days_required", 85)
                eta      = bst.get("first_results_eta", "?")
                pct      = min(100, int(days / max(min_days, 1) * 100))
                return f"""
<section class="section">
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("backtest")}<span data-i18n="section.backtest">Backtest — Validação Histórica</span></h2>
  <div style="background:#0A1628;border:1px solid #1E2D4D;border-radius:8px;padding:18px 20px;margin-top:8px">
    <div style="color:#FFB800;font-size:0.75rem;font-weight:700;margin-bottom:8px"
         data-i18n="backtest.accumulating">⏳ A ACUMULAR HISTÓRICO</div>
    <p style="color:#8A9CC0;font-size:0.80rem;margin:0 0 12px;line-height:1.5"
       data-i18n="backtest.accumulating_desc"
       data-i18n-options='{{"min_days":{min_days},"days":{days},"eta":"{eta}"}}'>
      O backtest requer mínimo de {min_days} dias de histórico de sinais.
      Estado actual: {days} de {min_days} dias.
      Primeiros resultados estimados: {eta}.
    </p>
    <div style="background:#0D1525;border-radius:4px;height:8px;overflow:hidden">
      <div style="background:linear-gradient(90deg,#FFB800,#FF8800);height:100%;width:{pct}%;transition:width .3s"></div>
    </div>
    <div style="color:#4A6080;font-size:0.62rem;margin-top:6px"
         data-i18n="backtest.pct_complete"
         data-i18n-options='{{"pct":{pct}}}'>{pct}% completo</div>
  </div>
</section>"""
        except Exception:
            pass

    if bt_df.empty:
        return ""

    fwd_col = "fwd_21d"
    exc_col = "fwd_21d_excess"
    if fwd_col not in bt_df.columns:
        return ""

    levels = [LEVEL_STRONG, LEVEL_BUY, LEVEL_POTENTIAL]
    level_colors = {LEVEL_STRONG: "var(--green)", LEVEL_BUY: "var(--light-green)", LEVEL_POTENTIAL: "var(--yellow)"}
    level_i18n   = {LEVEL_STRONG: "signal.strong_buy", LEVEL_BUY: "signal.buy", LEVEL_POTENTIAL: "signal.potential"}

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
            i18n_key = level_i18n.get(lvl, "")
            exc_html = (f'&nbsp;·&nbsp;<span style="color:var(--muted)" data-i18n="backtest.excess_spy">Excesso SPY</span>'
                        f' <b style="color:{_c(exc_avg)}">{_pct(exc_avg)}</b>') if pd.notna(exc_avg) else ""
            rows_html += f"""
            <div style="display:flex;align-items:center;gap:12px;padding:7px 0;border-bottom:1px solid var(--border);flex-wrap:wrap">
              <span style="background:{clr};color:#000;padding:1px 8px;border-radius:2px;font-size:10px;font-weight:bold;min-width:90px;text-align:center" data-i18n="{i18n_key}">{level_display(lvl)}</span>
              <span style="color:var(--muted);font-size:11px">n={len(sub)}</span>
              <span style="font-size:12px"><span style="color:var(--muted)" data-i18n="backtest.avg_ret">Ret. médio 21d</span> <b style="color:{_c(avg)}">{_pct(avg)}</b>{exc_html}</span>
              <span style="font-size:12px"><span style="color:var(--muted)" data-i18n="backtest.win_rate">Win rate</span> <b style="color:{_c(win-0.5)}">{win:.0%}</b></span>
            </div>"""
        return rows_html or '<p style="color:var(--muted);font-size:11px" data-i18n="backtest.no_data">Sem dados suficientes.</p>'

    all_html  = regime_block(bt_df, "TODOS")
    bull_html = regime_block(bt_df[bt_df.get("spy_regime", pd.Series()) == "BULL"] if "spy_regime" in bt_df.columns else pd.DataFrame(), "BULL")
    bear_html = regime_block(bt_df[bt_df.get("spy_regime", pd.Series()) == "BEAR"] if "spy_regime" in bt_df.columns else pd.DataFrame(), "BEAR")

    return f"""
<section class="section">
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("backtest")}<span data-i18n="section.backtest">Backtest — Validação Histórica</span></h2>
  <p style="color:var(--muted);font-size:11px;margin-top:-8px;margin-bottom:12px" data-i18n="backtest.desc">
    Retorno dos 21 dias seguintes a cada sinal · excesso vs SPY no mesmo período
  </p>
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('bt-all',this)" data-i18n="backtest.all_tab">Todos</button>
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
                  text-transform:uppercase;color:var(--patina);margin-bottom:8px" data-i18n="backtest.academic_basis">Base Académica</div>
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
                  text-transform:uppercase;color:var(--patina);margin-bottom:8px" data-i18n="backtest.for_whom">Para quem</div>
      <p style="color:var(--muted);font-size:0.67rem;line-height:1.6;margin:0" data-i18n="backtest.for_whom_desc">
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

    if "date" in df.columns:
        df = df[df["date"] == df["date"].max()]
    df = df.sort_values("market_value", ascending=False)
    total_value = df["market_value"].sum()
    total_pl    = df["unrealized_pl"].sum()
    pl_color    = "var(--green)" if total_pl >= 0 else "var(--red)"

    th = "padding:7px 10px;background:var(--deep);color:var(--champagne);text-align:right;font-size:11px"
    td = "padding:5px 10px;border-bottom:1px solid var(--border);font-size:11px;text-align:right"

    _header_defs = [
        ("portfolio.symbol", "Símbolo", "left"),
        ("table.name",       "Nome",    "left"),
        ("portfolio.qty",    "Qtd.",    "right"),
        ("portfolio.value",  "Valor",   "right"),
        ("portfolio.pnl",    "P&L",     "right"),
        ("portfolio.pnl_pct","P&L %",   "right"),
        ("portfolio.weight", "Peso",    "right"),
    ]
    headers = "".join(
        f'<th style="{th};text-align:{align}" data-i18n="{key}">{label}</th>'
        for key, label, align in _header_defs
    )
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
  <h2 class="section-title" style="display:flex;align-items:center">{_icon("portfolio")}<span data-i18n="section.portfolio">Portfólio Alpaca</span></h2>
  <div style="display:flex;gap:24px;margin-bottom:14px;flex-wrap:wrap">
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em" data-i18n="portfolio.total_value">Valor Total</div>
      <div style="color:var(--champagne);font-size:18px;font-weight:600">${total_value:,.2f}</div>
    </div>
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em" data-i18n="portfolio.unrealized_pnl">P&L Não Realizado</div>
      <div style="color:{pl_color};font-size:18px;font-weight:600">{total_pl:+,.2f}</div>
    </div>
    <div>
      <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.1em" data-i18n="portfolio.positions">Posições</div>
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
.articles-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.article-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 18px 16px 14px;
  text-decoration: none;
  transition: border-color .2s, background .2s;
}
.article-card:hover {
  border-color: var(--card-accent, #00D4FF);
  background: #0d1628;
  text-decoration: none;
}
.article-card-tag {
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.14em;
}
.article-card-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.35;
}
.article-card-desc {
  font-size: 0.75rem;
  color: var(--muted);
  line-height: 1.5;
  flex: 1;
}
.article-card-cta {
  font-size: 0.72rem;
  font-weight: 600;
  margin-top: 4px;
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

/* ── Bloomberg layout ───────────────────────────── */
.db-grid {
  display: grid;
  grid-template-columns: 1.35fr 1fr;
  gap: 12px;
  margin-top: 16px;
}
.db-col { display: flex; flex-direction: column; gap: 12px; }
.panel {
  background: #0D1525;
  border: 1px solid #1E2D4D;
  border-radius: 6px;
  overflow: hidden;
}
.panel-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  border-bottom: 1px solid #1E2D4D;
  background: #090E1A;
}
.panel-title {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: #8BA4C8;
}
.panel-body { padding: 14px; }
.score-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 0.58rem;
  font-weight: 800;
  letter-spacing: 0.06em;
}
.heat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.heat-tile {
  border-radius: 4px;
  padding: 8px 4px;
  text-align: center;
  cursor: default;
  transition: opacity 120ms;
}
.heat-tile:hover { opacity: 0.85; }
.nav-tab-bar {
  display: flex;
  gap: 2px;
  align-items: center;
}
.nav-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #4A6080;
  padding: 4px 14px 6px;
  font-size: 0.72rem;
  font-weight: 500;
  font-family: 'Albert Sans', sans-serif;
  cursor: pointer;
  transition: color 150ms, border-color 150ms;
  letter-spacing: 0.02em;
}
.nav-tab:hover { color: #8BA4C8; }
.nav-tab.active { color: #00D4FF; border-bottom-color: #00D4FF; }
.alert-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px solid #1E2D4D11;
}
.alert-item:last-child { border-bottom: none; padding-bottom: 0; }

@media (max-width: 700px) {
  .db-grid { grid-template-columns: 1fr; }
  .heat-grid { grid-template-columns: repeat(4, 1fr); }
}
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

/* i18n: lang-specific content — JS toggles .lang-hidden */
.lang-hidden { display: none !important; }
/* CSS fallback for pre-JS load: html starts with lang="pt" */
html[lang="en"] .lang-pt-only { display: none !important; }
html[lang="pt"] .lang-en-only { display: none !important; }
</style>"""




# ── Daily article ──────────────────────────────────────────────────────────────

_MONTHS_PT = ["janeiro","fevereiro","março","abril","maio","junho",
              "julho","agosto","setembro","outubro","novembro","dezembro"]
_MONTHS_EN = ["January","February","March","April","May","June",
              "July","August","September","October","November","December"]

def signal_deltas_html(deltas: list[dict]) -> str:
    """Banner compacto com upgrades/downgrades de nível de sinal dia-a-dia."""
    upgrades   = [d for d in deltas if d["direction"] > 0]
    downgrades = [d for d in deltas if d["direction"] < 0]
    if not upgrades and not downgrades:
        return ""

    level_colors = {LEVEL_STRONG: "#00FF9D", LEVEL_BUY: "#00D4FF", LEVEL_POTENTIAL: "#FFB800"}

    def _pill(level: str | None) -> str:
        if not level:
            return '<span style="color:#4A6080;font-size:0.58rem">—</span>'
        c = level_colors.get(level, "#4A6080")
        return (f'<span style="background:{c};color:#000;padding:1px 6px;border-radius:2px;'
                f'font-size:0.58rem;font-weight:800">{level_display(level)}</span>')

    items = ""
    for d in upgrades[:8]:
        items += f"""
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #1E2D4D40">
        <span style="color:#00FF9D;font-size:13px;flex-shrink:0">▲</span>
        <span style="color:#E8F0FF;font-size:0.78rem;font-weight:700;min-width:72px">{d['etf']}</span>
        {_pill(d['prev_level'])}
        <span style="color:#4A6080;font-size:0.62rem">→</span>
        {_pill(d['curr_level'])}
        <span style="color:{level_colors.get(d['curr_level'],'#4A6080')};font-size:0.72rem;font-weight:700;margin-left:auto">{d['score']:.3f}</span>
      </div>"""
    for d in downgrades[:4]:
        items += f"""
      <div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #1E2D4D20;opacity:0.65">
        <span style="color:#FF4466;font-size:11px;flex-shrink:0">▼</span>
        <span style="color:#8A9CC0;font-size:0.72rem;font-weight:600;min-width:72px">{d['etf']}</span>
        {_pill(d['prev_level'])}
        <span style="color:#4A6080;font-size:0.62rem">→</span>
        {_pill(d['curr_level'])}
        <span style="color:#8A9CC0;font-size:0.68rem;margin-left:auto">{d['score']:.3f}</span>
      </div>"""

    badge = (f'<span style="background:#00FF9D22;color:#00FF9D;padding:1px 8px;'
             f'border-radius:2px;font-size:0.6rem;font-weight:700">{len(upgrades)} ↑</span>')
    if downgrades:
        badge += (f' <span style="background:#FF446622;color:#FF4466;padding:1px 8px;'
                  f'border-radius:2px;font-size:0.6rem;font-weight:700">{len(downgrades)} ↓</span>')

    return f"""
<div style="background:#0A1628;border:1px solid #1E2D4D;border-radius:8px;padding:14px 16px;margin-bottom:16px">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
    <span style="color:#E8F0FF;font-size:0.75rem;font-weight:700;letter-spacing:0.06em">
      <span class="lang-pt-only">VARIAÇÕES DE SINAL · HOJE</span>
      <span class="lang-en-only">SIGNAL CHANGES · TODAY</span>
    </span>
    {badge}
  </div>
  <div>{items}</div>
</div>"""


def daily_highlight_card_html(signals_all: list[dict], spy_regime: str, avg_score: float, today_iso: str) -> str:
    """Destaque da análise diária — aparece no topo do tab Overview."""
    from zoneinfo import ZoneInfo
    today_obj    = datetime.now(ZoneInfo("Europe/Lisbon"))
    day_fmt_pt   = f"{today_obj.day} de {_MONTHS_PT[today_obj.month-1]} de {today_obj.year}"
    day_fmt_en   = f"{today_obj.day} {_MONTHS_EN[today_obj.month-1]} {today_obj.year}"
    day_fmt      = (f'<span class="lang-pt-only">{day_fmt_pt}</span>'
                    f'<span class="lang-en-only">{day_fmt_en}</span>')
    site        = "https://nunovinhas-creator.github.io/ET-spotter"
    article_url = f"{site}/analise-diaria.html"

    strong_buys = [s for s in signals_all if s["level"] == LEVEL_STRONG]
    buys        = [s for s in signals_all if s["level"] == LEVEL_BUY]
    n_sb, n_b   = len(strong_buys), len(buys)

    regime_color = "#00FF9D" if spy_regime == "BULL" else ("#FF4466" if spy_regime == "BEAR" else "#4A6080")
    regime_badge = f'<span style="background:{regime_color}22;color:{regime_color};border:1px solid {regime_color}44;padding:2px 8px;border-radius:2px;font-size:0.60rem;font-weight:800;letter-spacing:0.1em">SPY {spy_regime}</span>'

    top_etfs_html = ""
    for s in strong_buys[:3]:
        sym   = s.get("etf", "")
        score = s.get("score", 0)
        top_etfs_html += f'<span style="color:#00FF9D;font-weight:700">{sym}</span><span style="color:#4A6080;font-size:0.68rem"> {score:.2f}</span>  '
    for s in buys[:2]:
        sym   = s.get("etf", "")
        score = s.get("score", 0)
        top_etfs_html += f'<span style="color:#00D4FF">{sym}</span><span style="color:#4A6080;font-size:0.68rem"> {score:.2f}</span>  '

    avg_str = f"{avg_score:.3f}"
    if (n_sb + n_b) > 0:
        headline_fb  = f"{n_sb} em Radar Máximo · {n_b} em Destaque · Score médio {avg_str}"
        headline_key = "highlight.headline"
        headline_opts = f'{{"strong":{n_sb},"buy":{n_b},"avg":"{avg_str}"}}'
    else:
        headline_fb  = f"Score médio {avg_str} · Sem sinais de compra hoje"
        headline_key = "highlight.headline_no_signals"
        headline_opts = f'{{"avg":"{avg_str}"}}'

    return f"""
<div style="margin:0 0 18px;background:linear-gradient(135deg,#05080f 0%,#0a111e 100%);
            border:1px solid #FFB80033;border-left:3px solid #FFB800;border-radius:6px;
            padding:14px 18px;display:flex;align-items:center;justify-content:space-between;
            gap:16px;flex-wrap:wrap">
  <div style="display:flex;flex-direction:column;gap:6px;min-width:0">
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <span style="color:#FFB800;font-size:0.60rem;font-weight:800;letter-spacing:0.14em"
            data-i18n="highlight.label">📰 ANÁLISE DO DIA</span>
      <span style="color:var(--muted);font-size:0.60rem">{day_fmt}</span>
      {regime_badge}
    </div>
    <div style="color:var(--text);font-size:0.82rem;font-weight:600"
         data-i18n="{headline_key}"
         data-i18n-options='{headline_opts}'>{headline_fb}</div>
    <div style="font-size:0.72rem;letter-spacing:0.02em">{top_etfs_html}</div>
  </div>
  <a href="{article_url}" target="_blank" rel="noopener"
     style="flex-shrink:0;background:#FFB800;color:#000;font-weight:800;font-size:0.72rem;
            padding:9px 18px;border-radius:4px;text-decoration:none;white-space:nowrap;
            letter-spacing:0.04em"
     data-i18n="highlight.read_more">
    Ler análise →
  </a>
</div>"""


def generate_daily_article(data: dict, signals_all: list[dict], avg_score: float, n_etfs: int) -> None:
    """Gera docs/analise-diaria.html com análise do dia baseada em dados reais."""
    from zoneinfo import ZoneInfo
    from pathlib import Path

    today_obj   = datetime.now(ZoneInfo("Europe/Lisbon"))
    today_iso   = today_obj.strftime("%Y-%m-%d")
    day_fmt     = f"{today_obj.day} de {_MONTHS_PT[today_obj.month-1]} de {today_obj.year}"
    site        = "https://nunovinhas-creator.github.io/ET-spotter"
    article_url = f"{site}/analise-diaria.html"

    spy_regime   = data.get("spy_regime", "DESCONHECIDO")
    spy_close    = data.get("spy_close")
    spy_sma200   = data.get("spy_sma200")
    cats         = data.get("cats", [])

    strong_buys = [s for s in signals_all if s["level"] in ("FORTE COMPRA", "STRONG_BUY")]
    buys        = [s for s in signals_all if s["level"] in ("COMPRA", "BUY")]
    n_sb, n_b   = len(strong_buys), len(buys)

    regime_color_css = "#00FF9D" if spy_regime == "BULL" else ("#FF4466" if spy_regime == "BEAR" else "#4A6080")
    regime_label_pt  = "mercado em tendência de alta" if spy_regime == "BULL" else ("mercado abaixo da média de 200 dias" if spy_regime == "BEAR" else "regime indefinido")

    # ── Parágrafo de contexto de mercado ─────────────────────────────────────
    spy_ctx = ""
    if spy_close and spy_sma200:
        dist = (spy_close / spy_sma200 - 1) * 100
        spy_ctx = (
            f"O S&P 500 (SPY) fecha em {spy_close:.2f}, "
            f"{'acima' if spy_regime=='BULL' else 'abaixo'} da sua média móvel de 200 dias ({spy_sma200:.2f}) "
            f"em {abs(dist):.1f}%. "
        )

    if n_sb + n_b == 0:
        intro = (f"{spy_ctx}Hoje não se registam confluências de sinais suficientes para emitir alertas de compra. "
                 f"O score médio do universo de {n_etfs} ETFs UCITS é de {avg_score:.3f}, "
                 f"sugerindo um mercado neutro sem pressão direcional clara.")
        title_suffix = "Mercado Neutro"
    elif n_sb >= 3:
        intro = (f"{spy_ctx}Dia de grande confluência quantitativa: {n_sb} ETFs UCITS atingem o nível {level_display('FORTE COMPRA')} "
                 f"e {n_b} atingem {level_display('COMPRA')}, num universo de {n_etfs} ETFs analisados. "
                 f"O score médio do dia é {avg_score:.3f}. O modelo identifica alinhamento simultâneo "
                 f"de momentum multi-período, tendência confirmada e força relativa positiva.")
        title_suffix = f"{n_sb} ETFs em Radar Máximo"
    else:
        intro = (f"{spy_ctx}O scanner quantitativo identifica hoje {n_sb} ETF{'s' if n_sb!=1 else ''} em {level_display('FORTE COMPRA')} "
                 f"e {n_b} em {level_display('COMPRA')}, num universo de {n_etfs} ETFs UCITS analisados. "
                 f"Score médio do universo: {avg_score:.3f}.")
        title_suffix = f"{n_sb} Sinal{'is' if n_sb!=1 else ''} em Destaque"

    article_title = f"Análise ETFs UCITS — {day_fmt}: {title_suffix}"
    meta_desc     = (f"Análise quantitativa diária de ETFs UCITS para {day_fmt}. "
                     f"SPY {spy_regime} · {n_sb} {level_display('FORTE COMPRA')} · {n_b} {level_display('COMPRA')} · Score médio {avg_score:.3f}. "
                     f"Baseada em momentum, tendência, risco e alpha.")

    # ── Secção FORTE COMPRA ────────────────────────────────────────────────────
    def etf_card(s: dict, highlight: bool = False) -> str:
        sym    = s.get("etf", "")
        nome   = _nome_curto(s)
        score  = s.get("score", 0)
        ret63  = float(s.get("ret_63d", 0) or 0)
        ret5d  = float(s.get("ret_5d",  0) or 0)
        level  = s.get("level", "")
        color  = "#00FF9D" if "FORTE" in level or "STRONG" in level else "#00D4FF"
        label  = level_display("FORTE COMPRA") if "FORTE" in level or "STRONG" in level else level_display("COMPRA")
        narr   = narrativa_simples(s)
        border = f"border-left:3px solid {color};" if highlight else ""
        return (
            f'<div style="background:#0d1525;border:1px solid #1e2d4d;{border}border-radius:6px;padding:16px 18px;margin-bottom:12px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">'
            f'<span style="color:{color};font-size:1.1rem;font-weight:800">{sym}</span>'
            f'<span style="color:#c8cedd;font-size:0.78rem">{nome}</span>'
            f'<span style="margin-left:auto;background:{color}22;color:{color};border:1px solid {color}44;'
            f'padding:2px 8px;border-radius:3px;font-size:0.62rem;font-weight:700">{label}</span>'
            f'</div>'
            f'<div style="display:flex;gap:18px;font-size:0.72rem;color:#4a6080;margin-bottom:10px;flex-wrap:wrap">'
            f'<span>Score <strong style="color:{color}">{score:.3f}</strong></span>'
            f'<span>3 meses <strong style="color:{"#00FF9D" if ret63>=0 else "#FF4466"}">{ret63:+.1%}</strong></span>'
            f'<span>5 dias <strong style="color:{"#00FF9D" if ret5d>=0 else "#FF4466"}">{ret5d:+.1%}</strong></span>'
            f'</div>'
            f'<p style="color:#c8cedd;font-size:0.82rem;line-height:1.65;margin:0">{narr}</p>'
            f'</div>'
        )

    sb_cards = "".join(etf_card(s, highlight=True) for s in strong_buys[:5])
    b_cards  = "".join(etf_card(s, highlight=False) for s in buys[:5])

    forte_section = ""
    if strong_buys:
        forte_section = f"""
<h2 style="font-size:1.05rem;font-weight:700;color:#00FF9D;margin:32px 0 10px;
           padding-bottom:6px;border-bottom:1px solid #1e2d4d">
  Forte Compra — {n_sb} ETF{'s' if n_sb!=1 else ''} com todos os factores alinhados
</h2>
<p style="color:#c8cedd;font-size:0.85rem;margin-bottom:16px">
  O modelo identifica alinhamento simultâneo de momentum multi-período (Jegadeesh &amp; Titman, 1993),
  tendência confirmada acima da SMA (Faber, 2007) e força relativa positiva (Antonacci, 2014).
</p>
{sb_cards}"""

    buy_section = ""
    if buys:
        buy_section = f"""
<h2 style="font-size:1.05rem;font-weight:700;color:#00D4FF;margin:32px 0 10px;
           padding-bottom:6px;border-bottom:1px solid #1e2d4d">
  Compra — {n_b} ETF{'s' if n_b!=1 else ''} com sinal construtivo
</h2>
{b_cards}"""

    # ── Rotação de categorias ─────────────────────────────────────────────────
    top_cats = sorted(cats, key=lambda c: c.get("score_avg", 0), reverse=True)[:3]
    cat_rows = ""
    for c in top_cats:
        sc = c.get("score_avg", 0)
        cat_rows += (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'padding:8px 0;border-bottom:1px solid #1e2d4d">'
            f'<span style="color:{c.get("color","#ccc")};font-weight:600;font-size:0.82rem">{c.get("name","")}</span>'
            f'<span style="color:{"#00FF9D" if sc>=0.5 else "#4a6080"};font-weight:700">{sc:.3f}</span>'
            f'</div>'
        )
    cat_section = ""
    if cat_rows:
        cat_section = f"""
<h2 style="font-size:1.05rem;font-weight:700;color:#7C83FD;margin:32px 0 10px;
           padding-bottom:6px;border-bottom:1px solid #1e2d4d">
  Categorias em Destaque
</h2>
<p style="color:#c8cedd;font-size:0.85rem;margin-bottom:12px">
  Top 3 categorias por score médio — útil para identificar rotação sectorial.
</p>
<div style="background:#0d1525;border:1px solid #1e2d4d;border-radius:6px;padding:4px 16px">
  {cat_rows}
</div>"""

    no_signals_section = ""
    if n_sb + n_b == 0:
        no_signals_section = """
<div style="background:#0d1525;border:1px solid #1e2d4d;border-left:3px solid #4a6080;
            border-radius:6px;padding:16px 18px;margin:20px 0">
  <p style="color:#c8cedd;font-size:0.85rem;margin:0">
    Dias sem sinal são igualmente informativos: indicam ausência de confluência técnica e sugerem
    cautela ou espera. O modelo emite sinais apenas quando todos os critérios convergem —
    precisamente para evitar falsos positivos.
  </p>
</div>"""

    # ── JSON-LD Article schema ────────────────────────────────────────────────
    import json as _json
    article_schema = _json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article_title,
        "description": meta_desc,
        "author": {"@type": "Organization", "name": "ET-Spotter", "url": site},
        "publisher": {"@type": "Organization", "name": "ET-Spotter", "url": site},
        "datePublished": today_iso,
        "dateModified": today_iso,
        "url": article_url
    }, ensure_ascii=False, separators=(',', ':'))

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#080a10">
  <title>{article_title}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="keywords" content="análise ETF UCITS {today_iso}, ETF forte compra hoje, scanner ETF diário, momentum ETF Europa">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{article_url}">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{article_title}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:url" content="{article_url}">
  <meta property="og:site_name" content="ET-Spotter">
  <meta name="twitter:card" content="summary_large_image">
  <script type="application/ld+json">{article_schema}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root{{--bg:#080a10;--surface:#0f1629;--text:#E8EAF0;--muted:#4A6080;--border:#1E2D45;
          --green:#00FF9D;--accent:#00D4FF;--yellow:#FFB800;--font:'Albert Sans',system-ui,sans-serif}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.75;font-size:15px}}
    a{{color:var(--accent);text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .container{{max-width:740px;margin:0 auto;padding:0 18px}}
    .site-header{{border-bottom:1px solid var(--border);padding:12px 0;margin-bottom:0}}
    .site-header .inner{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
    .logo{{font-size:1rem;font-weight:800;letter-spacing:0.06em;color:var(--text);white-space:nowrap}}
    .logo span{{color:var(--accent)}}
    .back-btn{{font-size:0.72rem;color:var(--muted);border:1px solid var(--border);
              padding:5px 12px;border-radius:3px;white-space:nowrap;transition:color .2s}}
    .back-btn:hover{{color:var(--accent);text-decoration:none;border-color:var(--accent)}}
    .article{{padding:32px 0 48px}}
    .article-tag{{display:inline-block;color:var(--yellow);font-size:0.6rem;letter-spacing:0.14em;
                 font-weight:700;margin-bottom:12px}}
    h1{{font-size:1.45rem;font-weight:800;line-height:1.3;margin-bottom:10px}}
    .article-meta{{color:var(--muted);font-size:0.72rem;margin-bottom:24px;padding-bottom:16px;
                  border-bottom:1px solid var(--border)}}
    .intro{{color:#C8CEDD;font-size:0.92rem;line-height:1.75;margin-bottom:8px;
            background:#0d1525;border:1px solid #1e2d4d;border-left:3px solid var(--yellow);
            border-radius:6px;padding:14px 18px}}
    .subscribe-box{{background:var(--surface);border:1px solid var(--border);
                   border-radius:8px;padding:22px 20px;text-align:center;margin:36px 0}}
    .subscribe-box h3{{font-size:0.95rem;margin-bottom:6px}}
    .subscribe-box p{{font-size:0.78rem;color:var(--muted);margin-bottom:14px}}
    .sub-form{{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}}
    .sub-form input{{flex:1;min-width:200px;max-width:280px;background:#0a0d17;
                    border:1px solid var(--border);border-radius:4px;padding:10px 14px;
                    color:var(--text);font-size:0.8rem;font-family:var(--font);outline:none}}
    .sub-form input:focus{{border-color:var(--green)}}
    .sub-form button{{background:var(--green);color:#000;border:none;border-radius:4px;
                     padding:10px 18px;font-weight:700;font-size:0.78rem;cursor:pointer;font-family:var(--font)}}
    .privacy{{color:var(--muted);font-size:0.65rem;margin-top:8px}}
    .cta-scanner{{background:linear-gradient(135deg,#08111f 0%,#0d1a2e 100%);
                 border:1px solid #00D4FF22;border-radius:8px;padding:24px 20px;
                 text-align:center;margin:36px 0}}
    .cta-scanner h3{{color:var(--text);font-size:1rem;margin-bottom:6px}}
    .cta-scanner p{{font-size:0.8rem;color:var(--muted);margin-bottom:16px}}
    .btn-primary{{display:inline-block;background:var(--green);color:#000;font-weight:800;
                 font-size:0.82rem;padding:11px 24px;border-radius:4px;text-decoration:none}}
    .btn-primary:hover{{text-decoration:none;opacity:.9}}
    .site-footer{{border-top:1px solid var(--border);padding:20px 0;margin-top:40px}}
    .site-footer p{{font-size:0.68rem;color:var(--muted);text-align:center;line-height:1.6}}
    @keyframes et-ticker{{0%{{transform:translateX(0)}}100%{{transform:translateX(-50%)}}}}
    @media(max-width:520px){{h1{{font-size:1.2rem}}}}
  </style>
</head>
<body>
<div style="width:100%;overflow:hidden;background:#03050d;border-bottom:1px solid #FFB80022;
            padding:5px 0;white-space:nowrap">
  <div style="display:inline-block;animation:et-ticker 50s linear infinite;
              font-size:0.62rem;letter-spacing:0.07em;font-family:'Albert Sans',sans-serif;color:#4A6080">
    &nbsp;&nbsp;◈ ET-SPOTTER · Análise quantitativa actualizada às 22h · SPY {spy_regime} · {n_sb} {level_display('FORTE COMPRA')} · {n_b} {level_display('COMPRA')} · Score médio {avg_score:.3f} · {n_etfs} ETFs UCITS analisados · Momentum · Tendência · Risco · Alpha · Grátis · Open Source · &nbsp;&nbsp;◈ ET-SPOTTER · Análise quantitativa actualizada às 22h · SPY {spy_regime} · {n_sb} {level_display('FORTE COMPRA')} · {n_b} {level_display('COMPRA')} · Score médio {avg_score:.3f} · {n_etfs} ETFs UCITS analisados · Momentum · Tendência · Risco · Alpha · Grátis · Open Source ·
  </div>
</div>
<header class="site-header">
  <div class="container inner">
    <a href="{site}/" class="logo" style="text-decoration:none">ET<span>-</span>SPOTTER</a>
    <a href="{site}/" class="back-btn">← Ver scanner ao vivo</a>
  </div>
</header>
<div class="container">
  <article class="article">
    <div class="article-tag">📰 ANÁLISE DIÁRIA · {day_fmt.upper()}</div>
    <h1>{article_title}</h1>
    <div class="article-meta">
      ET-Spotter · Gerado automaticamente em {day_fmt} às 22h UTC ·
      Universo: {n_etfs} ETFs UCITS · SPY <span style="color:{regime_color_css};font-weight:700">{spy_regime}</span>
      ({regime_label_pt})
    </div>

    <div class="intro">{intro}</div>

    {forte_section}
    {buy_section}
    {no_signals_section}
    {cat_section}

    <div class="subscribe-box" style="margin-top:40px">
      <h3>📬 Recebe esta análise por email todos os dias às 22h</h3>
      <p>Score de todos os ETFs · alerta de regime SPY · rotação de categorias — grátis</p>
      <div style="display:flex;justify-content:center;padding:16px 0">
        <div style="width:100%;max-width:340px">
          <script async src="https://subscribe-forms.beehiiv.com/v3/loader.js" data-beehiiv-form="d4e78e22-ed6f-401d-b41b-75f1e9b316fa"></script>
          <script type="text/javascript" async src="https://subscribe-forms.beehiiv.com/attribution.js"></script>
        </div>
      </div>
      <p class="privacy">Sem spam. Cancelas quando quiseres.</p>
    </div>

    <div class="cta-scanner">
      <h3>📊 Ver o scanner completo ao vivo</h3>
      <p>Todos os {n_etfs} ETFs ordenados por score · gráficos de evolução · backtest histórico</p>
      <a href="{site}/" class="btn-primary">Abrir ET-Spotter →</a>
    </div>

    <p style="color:var(--muted);font-size:0.68rem;margin-top:32px;line-height:1.6">
      ⚠️ Análise gerada automaticamente com base em dados históricos de preços via yfinance.
      Não constitui aconselhamento financeiro nem garantia de retorno. Consulta sempre um profissional antes de investir.
    </p>
  </article>
</div>
<footer class="site-footer">
  <div class="container">
    <p>© ET-Spotter · <a href="{site}/">ET-Spotter</a> · Dados via yfinance · Actualizado diariamente às 22h</p>
    <p style="margin-top:6px">Base académica: Jegadeesh &amp; Titman (1993) · Faber (2007) · Antonacci (2014) · Ang et al. (2006) · Kakushadze (2015)</p>
  </div>
</footer>
</body>
</html>"""

    out = Path(__file__).parent.parent / "docs" / "analise-diaria.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK] analise-diaria.html  ({len(html)//1024} KB)")


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_dashboard(cfg: dict) -> None:
    data = load_data(cfg)
    if not data:
        print("[SKIP] Sem dados para o dashboard.")
        return

    from zoneinfo import ZoneInfo
    ts       = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%d/%m/%Y  %H:%M (Lisboa)")
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
    n_strong_buy = sum(1 for s in signals_all if s["level"] == LEVEL_STRONG)
    n_buy        = sum(1 for s in signals_all if s["level"] == LEVEL_BUY)

    avg_score    = float(data["scores_df"]["score"].mean()) if not data["scores_df"].empty and "score" in data["scores_df"].columns else 0.0
    today_iso    = datetime.now(ZoneInfo("Europe/Lisbon")).strftime("%Y-%m-%d")

    generate_daily_article(data, signals_all, avg_score, n_etfs_today)

    sections = [
        ticker_html(signals_all, data["spy_regime"], avg_score, n_etfs_today),
        header_html(data["spy_close"], data["spy_sma200"], data["spy_regime"], ts, n_etfs=n_etfs_today),
        '<div class="main">',

        # ── Tab: Overview ─────────────────────────────────────────────────────
        '<div id="tab-overview">',
        hero_plain_html(signals_all, n_etfs_today, data["spy_regime"]),
        hero_bar_html(n_etfs=n_etfs_today, n_total=n_total),
        signal_legend_html(n_etfs=n_etfs_today),
        daily_highlight_card_html(signals_all, data["spy_regime"], avg_score, today_iso),
        signal_deltas_html(data["signal_deltas"]),
        summary_cards_html(signals_all, data["scores_df"]),
        overview_grid_html(data["rows_raw"], signals_all, data["scores_df"],
                           data["spy_close"], data["spy_sma200"], data["spy_regime"],
                           data["hist_df"]),
        '</div>',

        # ── Tab: Scores & Alertas ─────────────────────────────────────────────
        '<div id="tab-signals" style="display:none">',
        explainer_section(),
        _GLOW_DIVIDER,
        advisor_section(data["rows_raw"]),
        _GLOW_DIVIDER,
        buy_signals_section(signals),
        _GLOW_DIVIDER,
        category_heatmap_section(data["cats"]),
        '</div>',

        # ── Tab: Relatórios ───────────────────────────────────────────────────
        '<div id="tab-reports" style="display:none">',
        _GLOW_DIVIDER,
        history_chart_section(data["hist_df"], data["scores_df"]),
        _GLOW_DIVIDER,
        backtest_section(data["bt_df"]),
        portfolio_section(PORTFOLIO, data["cmap"]),
        _GLOW_DIVIDER,
        etf_table_section(data["scores_df"], data["cmap"], metadata),
        '</div>',

        # ── Tab: Guias ────────────────────────────────────────────────────────
        '<div id="tab-guides" style="display:none">',
        articles_section_html(),
        '</div>',

        subscribe_section_html(),
        brand_banner_section_html(),
        '</div>',
        f'<footer>'
        f'<div style="max-width:900px;margin:0 auto">'
        f'<div style="display:flex;align-items:center;justify-content:center;gap:8px;flex-wrap:wrap;margin-bottom:14px">'
        f'<span data-i18n="footer.auto_updated" style="background:#0F1629;border:1px solid #00D4FF44;color:#00D4FF;padding:3px 10px;border-radius:3px;font-size:0.60rem;letter-spacing:0.08em;font-weight:600">⟳ AUTO-UPDATED</span>'
        f'<span data-i18n="footer.quant_engine" style="background:#0F1629;border:1px solid #7C83FD44;color:#7C83FD;padding:3px 10px;border-radius:3px;font-size:0.60rem;letter-spacing:0.08em;font-weight:600">⚙ QUANT ENGINE</span>'
        f'<span data-i18n="footer.etf_scanner" style="background:#0F1629;border:1px solid #00FF9D44;color:#00FF9D;padding:3px 10px;border-radius:3px;font-size:0.60rem;letter-spacing:0.08em;font-weight:600">◈ ETF SCANNER</span>'
        f'<span data-i18n="footer.open_source" style="background:#0F1629;border:1px solid #FFB80044;color:#FFB800;padding:3px 10px;border-radius:3px;font-size:0.60rem;letter-spacing:0.08em;font-weight:600">✦ OPEN SOURCE</span>'
        f'</div>'
        f'<div data-i18n="footer.data_source" style="color:var(--muted);font-size:0.65rem;margin-bottom:8px;text-align:center">ET-Spotter · dados via yfinance · actualização diária</div>'
        f'<div style="display:flex;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap;margin-bottom:12px">'
        f'<span class="acad-badge" title="Momentum 12-1M">Jegadeesh &amp; Titman (1993)</span>'
        f'<span class="acad-badge" title="Trend following SMA">Faber (2007)</span>'
        f'<span class="acad-badge" title="Dual momentum">Antonacci (2014)</span>'
        f'<span class="acad-badge" title="Low-volatility anomaly">Ang et al. (2006)</span>'
        f'<span class="acad-badge" title="Alpha cross-sectional">Kakushadze (2015)</span>'
        f'<span class="acad-badge" title="Value &amp; Momentum Everywhere">AQR</span>'
        f'<span class="acad-badge" title="Risk-adjusted return">Sharpe</span>'
        f'</div>'
        f'<span data-i18n="footer.disclaimer" style="font-size:0.68rem;opacity:0.75;line-height:1.6">⚠️ Informação técnica e resultados de backtest — não constitui aconselhamento financeiro. Os sinais identificam períodos de convergência estatística de múltiplos factores; não predizem preços futuros. Consulta sempre um profissional antes de investir.</span>'
        f'</div>'
        f'{push_btn}</footer>',
    ]

    # Actualizar para "https://et-spotter.com" quando o domínio estiver comprado e DNS configurado
    site_url     = "https://nunovinhas-creator.github.io/ET-spotter"
    meta_desc_en = (f"ET-Spotter — daily score from 0 to 1 for {n_etfs_today} European UCITS ETFs. "
                    f"See which are strongest today. Free, open source, updated daily.")
    meta_desc_pt = (f"ET-Spotter — nota diária de 0 a 1 para {n_etfs_today} ETFs UCITS europeus. "
                    f"Vê quais estão mais fortes hoje. Grátis, código aberto, actualizado diariamente.")
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": "ET-Spotter",
        "url": site_url,
        "description": meta_desc_en,
        "applicationCategory": "FinanceApplication",
        "operatingSystem": "Any",
        "inLanguage": ["pt", "en"],
        "dateModified": today_iso,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock"},
        "author": {"@type": "Organization", "name": "ET-Spotter", "url": site_url},
        "keywords": ("UCITS ETF scanner, ETF momentum Europa, ETF ranking Europa, "
                     "melhor ETF Europa, ETF UCITS Portugal, VWCE IWDA score")
    }, ensure_ascii=False, separators=(',', ':'))

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <meta name="theme-color" content="#080a10">
  <title>ET-Spotter · UCITS ETF Scanner — Momentum, Trend & Risk Score</title>
  <meta name="description" content="{meta_desc_pt}">
  <meta name="keywords" content="ETF UCITS, ETF momentum, ETF Europa, VWCE, IWDA, ETF scanner, ETF ranking Portugal, melhor ETF Europa">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{site_url}/">
  <link rel="alternate" hreflang="pt" href="{site_url}/?lang=pt">
  <link rel="alternate" hreflang="en" href="{site_url}/?lang=en">
  <link rel="alternate" hreflang="x-default" href="{site_url}/">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="ET-Spotter">
  <meta property="og:title" content="Que ETFs estão mais fortes hoje? · ET-Spotter">
  <meta property="og:description" content="{meta_desc_en}">
  <meta property="og:url" content="{site_url}/">
  <meta property="og:image" content="{site_url}/assets/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:locale" content="pt_PT">
  <meta property="og:locale:alternate" content="en_GB">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="ET-Spotter — nota diária de 0 a 1 para ETFs europeus">
  <meta name="twitter:description" content="{meta_desc_en}">
  <meta name="twitter:image" content="{site_url}/assets/og-image.png">
  <script type="application/ld+json">{json_ld}</script>
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <link rel="manifest" href="./manifest.json">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  {CSS}
</head>
<body>
{"".join(sections)}
{sw_script}
<script src="https://unpkg.com/i18next@23.11.5/dist/umd/i18next.min.js"></script>
<script src="./i18n.js"></script>
</body>
</html>"""

    # Replace service worker cache-bust placeholder in HTML
    html = html.replace("__BUILD_TS__", str(ts_epoch))

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "dashboard.html"
    out.write_text(html, encoding="utf-8")

    # Anchored to repo root regardless of CWD when script is invoked
    docs = Path(__file__).parent.parent / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "index.html").write_text(html, encoding="utf-8")

    # Update sw.js cache version so returning visitors always get the latest build
    sw_path = docs / "sw.js"
    if sw_path.exists():
        sw_content = sw_path.read_text(encoding="utf-8")
        sw_content = re.sub(r"et-spotter-[^\s'\"]+", f"et-spotter-{ts_epoch}", sw_content)
        sw_path.write_text(sw_content, encoding="utf-8")

    print(f"[OK] Dashboard gerado: {out}  ({len(html)//1024} KB)")
    print(f"[OK] GitHub Pages:     docs/index.html")


def main():
    cfg = load_config()
    generate_dashboard(cfg)


if __name__ == "__main__":
    main()
