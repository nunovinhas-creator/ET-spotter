"""
Blocos HTML reutilizáveis para os emails diário e semanal.
Escritos em linguagem simples para utilizadores sem experiência técnica.
"""

import html as html_mod


def email_intro_html(n_strong: int, n_buy: int, n_pot: int, n_etfs: int,
                     tipo: str = "diária") -> str:
    """Bloco de introdução no topo do email — explica o que é e o que significa cada sinal."""
    total = n_strong + n_buy + n_pot
    if total == 0:
        resumo = f"Hoje nenhum dos {n_etfs} ETFs atingiu os critérios mínimos de sinal. Mercado sem confluência."
    elif n_strong > 0:
        resumo = (
            f"Hoje encontrámos <b style='color:#4caf50'>{n_strong} ETF{'s' if n_strong>1 else ''} "
            f"com sinal FORTE COMPRA</b> e {n_buy + n_pot} com sinais positivos adicionais, "
            f"de um universo de {n_etfs} ETFs analisados."
        )
    else:
        resumo = (
            f"Hoje encontrámos <b style='color:#8bc34a'>{n_buy} ETF{'s' if n_buy>1 else ''} "
            f"com sinal de COMPRA</b> e {n_pot} com potencial, de {n_etfs} ETFs analisados."
        )

    return f"""
<div style="background:#0a0e1a;border:1px solid #1e2130;border-radius:6px;
            padding:16px 20px;margin:0 0 20px">
  <p style="color:#7c83fd;font-size:13px;font-weight:bold;margin:0 0 8px">
    📋 O que é este email?
  </p>
  <p style="color:#aaa;font-size:12px;line-height:1.8;margin:0 0 12px">
    O <b style="color:#e8eaf6">ET-Spotter</b> analisa automaticamente {n_etfs} ETFs (fundos
    negociados em bolsa) todos os dias, com base em indicadores técnicos.
    Este email é a análise {tipo} — resume os ETFs que estão melhor posicionados
    e explica porquê em linguagem simples.
  </p>
  <p style="color:#aaa;font-size:12px;line-height:1.8;margin:0 0 14px">
    {resumo}
  </p>
  <div style="display:flex;flex-wrap:wrap;gap:8px">
    <div style="background:#0d200f;border-left:3px solid #4caf50;padding:6px 12px;border-radius:3px;font-size:11px">
      <b style="color:#4caf50">FORTE COMPRA</b>
      <span style="color:#888"> — vários indicadores alinhados, momentum forte (score ≥ 0.75)</span>
    </div>
    <div style="background:#131f0e;border-left:3px solid #8bc34a;padding:6px 12px;border-radius:3px;font-size:11px">
      <b style="color:#8bc34a">COMPRA</b>
      <span style="color:#888"> — maioria dos indicadores positivos, fase construtiva (score ≥ 0.55)</span>
    </div>
    <div style="background:#1a1900;border-left:3px solid #ffd54f;padding:6px 12px;border-radius:3px;font-size:11px">
      <b style="color:#ffd54f">POTENCIAL</b>
      <span style="color:#888"> — alguns sinais positivos, aguardar confirmação (score ≥ 0.40)</span>
    </div>
  </div>
</div>"""


def email_glossary_html() -> str:
    """Glossário simplificado no final do email."""
    terms = [
        ("Score (0–1)",    "Avaliação técnica composta de 0 a 1. Quanto mais perto de 1, mais indicadores estão alinhados positivamente. Não é uma previsão do preço futuro."),
        ("Momentum",       "Se o ETF tem estado a subir nos últimos meses. Momentum forte significa que a tendência se mantém no tempo."),
        ("Mom.12-1M",      "Retorno dos últimos 12 meses excluindo o último mês. Mede o momentum de médio prazo, o factor mais estudado academicamente."),
        ("Ret. 3M / 5d",   "Quanto o ETF ganhou ou perdeu nos últimos 3 meses / 5 dias. A verde é positivo, a vermelho é negativo."),
        ("RSI",            "Mede se o ETF está 'caro' tecnicamente (RSI > 70, pode pausar) ou 'barato' (RSI < 30, pode recuperar). Entre 40–65 é zona neutra e saudável."),
        ("ADX",            "Força da tendência. Acima de 25 existe uma tendência clara. Abaixo de 20 o mercado está sem direcção definida."),
        ("SMA200",         "Média dos últimos 200 dias de preço. Acima = tendência de alta. Abaixo = tendência de baixa. Uma das referências mais usadas no mundo."),
        ("RS/SPY ✓/✗",     "Força Relativa vs S&P 500. ✓ significa que o ETF está a superar o índice americano — sinal de liderança positivo."),
        ("Sharpe",         "Retorno dividido pelo risco. Sharpe ≥ 1.0 significa retorno razoável para o risco assumido."),
        ("Drawdown",       "Quanto o ETF caiu face ao seu máximo recente. Ex: −8% significa que está 8% abaixo do pico. Pequeno é melhor."),
        ("Δ Score",        "Variação do score face ao dia anterior. Positivo (↑) significa melhoria, negativo (↓) significa deterioração."),
        ("BULL / BEAR",    "O SPY (S&P 500, índice americano) está em alta (BULL, acima da média de 200 dias) ou em baixa (BEAR). Em regime BEAR os sinais são lidos com mais cautela."),
    ]
    rows = "".join(
        f'<tr>'
        f'<td style="color:#e8eaf6;font-weight:bold;padding:5px 12px 5px 0;'
        f'white-space:nowrap;vertical-align:top;font-size:11px">{html_mod.escape(t)}</td>'
        f'<td style="color:#888;padding:5px 0;font-size:11px;line-height:1.6">{html_mod.escape(d)}</td>'
        f'</tr>'
        for t, d in terms
    )
    return f"""
<div style="background:#0a0e1a;border:1px solid #1e2130;border-radius:6px;
            padding:16px 20px;margin:20px 0">
  <p style="color:#7c83fd;font-size:13px;font-weight:bold;margin:0 0 12px">
    📖 Glossário — o que significa cada termo
  </p>
  <table style="border-collapse:collapse;width:100%">
    {rows}
  </table>
  <p style="color:#333;font-size:10px;margin:12px 0 0;border-top:1px solid #1e2130;padding-top:10px">
    Esta análise é baseada em indicadores técnicos históricos e não constitui aconselhamento financeiro.
    Os sinais identificam convergência estatística de factores — não predizem preços futuros.
    Consulta sempre um profissional antes de investir.
  </p>
</div>"""


def metric_label(label: str, explanation: str) -> str:
    """Etiqueta de métrica com explicação em texto mais pequeno."""
    return (
        f'<span style="color:#666">{html_mod.escape(label)}</span>'
        f'<span style="color:#444;font-size:10px"> ({html_mod.escape(explanation)})</span>'
    )


# Mapa de explicações para cada métrica usada nos emails
METRIC_EXPLANATIONS = {
    "Mom.12-1M":  "retorno anual excl. último mês",
    "Mom.6-1M":   "retorno 6M excl. último mês",
    "Ret.3M":     "últimos 3 meses",
    "Ret. 3M":    "últimos 3 meses",
    "Ret.5d":     "últimos 5 dias",
    "Ret. 5d":    "últimos 5 dias",
    "Ret. Dia":   "hoje",
    "RSI":        "40–65 = zona saudável",
    "ADX":        ">25 = tendência forte",
    "Sharpe":     "retorno/risco, ≥1 é bom",
    "RS/SPY":     "supera o S&P 500?",
    "Δ Score":    "variação face a ontem",
    "Vol 21d":    "volatilidade 21 dias",
}
