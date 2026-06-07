"""
Gera páginas SEO estáticas em docs/ para et-spotter.com.
Correr: python scripts/generate_articles.py
"""
import json
from datetime import datetime
from pathlib import Path

DOCS     = Path(__file__).parent.parent / "docs"
TODAY    = datetime.now().strftime("%Y-%m-%d")
SITE_URL = "https://et-spotter.com"
BEEHIIV_URL = "https://et-spotter.beehiiv.com"

# ── CSS partilhado ─────────────────────────────────────────────────────────────
CSS = """
<style>
:root{--bg:#080a10;--surface:#0f1629;--surface2:#111827;--text:#E8EAF0;
      --muted:#4A6080;--border:#1E2D45;--green:#00FF9D;--accent:#00D4FF;
      --yellow:#FFB800;--red:#FF4466;
      --font:'Albert Sans',system-ui,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.75;font-size:15px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.container{max-width:740px;margin:0 auto;padding:0 18px}

/* header */
.site-header{border-bottom:1px solid var(--border);padding:12px 0;margin-bottom:0}
.site-header .inner{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.logo{font-size:1rem;font-weight:800;letter-spacing:0.06em;color:var(--text);white-space:nowrap}
.logo span{color:var(--accent)}
.back-btn{font-size:0.72rem;color:var(--muted);border:1px solid var(--border);
          padding:5px 12px;border-radius:3px;white-space:nowrap;transition:color .2s}
.back-btn:hover{color:var(--accent);text-decoration:none;border-color:var(--accent)}

/* article */
.article{padding:36px 0 48px}
.article-tag{display:inline-block;color:var(--green);font-size:0.6rem;letter-spacing:0.14em;
             font-weight:700;margin-bottom:14px}
h1{font-size:1.55rem;font-weight:800;line-height:1.3;margin-bottom:10px}
.article-meta{color:var(--muted);font-size:0.72rem;margin-bottom:28px;padding-bottom:20px;
              border-bottom:1px solid var(--border)}
h2{font-size:1.05rem;font-weight:700;color:var(--accent);margin:36px 0 10px;
   padding-bottom:6px;border-bottom:1px solid var(--border)}
h3{font-size:0.92rem;font-weight:700;margin:22px 0 8px;color:var(--text)}
p{margin-bottom:14px;color:#C8CEDD}
ul,ol{margin:10px 0 16px 22px;color:#C8CEDD}
li{margin-bottom:6px;font-size:0.9rem}
strong{color:var(--text)}

/* table */
.table-wrap{overflow-x:auto;margin:20px 0}
table{width:100%;border-collapse:collapse;font-size:0.82rem}
th{background:var(--surface2);padding:9px 14px;text-align:left;
   border:1px solid var(--border);color:var(--accent);font-weight:700;white-space:nowrap}
td{padding:9px 14px;border:1px solid var(--border);color:#C8CEDD}
tr:nth-child(even) td{background:#090c14}
.winner{color:var(--green);font-weight:700}

/* badge */
.badge{display:inline-block;padding:2px 8px;border-radius:3px;
       font-size:0.68rem;font-weight:700;margin:0 2px}
.bg{background:#00FF9D22;color:#00FF9D;border:1px solid #00FF9D44}
.bb{background:#00D4FF22;color:#00D4FF;border:1px solid #00D4FF44}
.by{background:#FFB80022;color:#FFB800;border:1px solid #FFB80044}

/* callout */
.callout{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
         border-radius:4px;padding:14px 16px;margin:20px 0;font-size:0.85rem}
.callout.green{border-left-color:var(--green)}
.callout.yellow{border-left-color:var(--yellow)}

/* CTA scanner */
.cta-scanner{background:linear-gradient(135deg,#08111f 0%,#0d1a2e 100%);
             border:1px solid #00D4FF22;border-radius:8px;padding:24px 20px;
             text-align:center;margin:36px 0}
.cta-scanner h3{color:var(--text);font-size:1rem;margin-bottom:6px}
.cta-scanner p{font-size:0.8rem;margin-bottom:16px}
.btn-primary{display:inline-block;background:var(--green);color:#000;
             font-weight:800;font-size:0.82rem;padding:11px 24px;border-radius:4px}
.btn-primary:hover{text-decoration:none;opacity:.9}

/* subscribe */
.subscribe-box{background:var(--surface);border:1px solid var(--border);
               border-radius:8px;padding:22px 20px;text-align:center;margin:36px 0}
.subscribe-box h3{font-size:0.95rem;margin-bottom:6px}
.subscribe-box p{font-size:0.78rem;color:var(--muted);margin-bottom:14px}
.sub-form{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
.sub-form input{flex:1;min-width:200px;max-width:280px;background:#0a0d17;
                border:1px solid var(--border);border-radius:4px;padding:10px 14px;
                color:var(--text);font-size:0.8rem;font-family:var(--font);outline:none}
.sub-form input:focus{border-color:var(--green)}
.sub-form button{background:var(--green);color:#000;border:none;border-radius:4px;
                 padding:10px 18px;font-weight:700;font-size:0.78rem;cursor:pointer;
                 font-family:var(--font);white-space:nowrap}
.privacy{color:var(--muted);font-size:0.65rem;margin-top:8px}

/* footer */
.site-footer{border-top:1px solid var(--border);padding:20px 0;margin-top:40px}
.site-footer p{font-size:0.68rem;color:var(--muted);text-align:center;line-height:1.6}

/* faq */
.faq-item{border-bottom:1px solid var(--border);padding:16px 0}
.faq-item:last-child{border-bottom:none}
.faq-q{font-weight:700;font-size:0.9rem;margin-bottom:8px;color:var(--text)}
.faq-a{font-size:0.85rem;color:#C8CEDD}

@media(max-width:520px){h1{font-size:1.25rem}.sub-form{flex-direction:column;align-items:stretch}}
</style>"""

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Albert+Sans:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">'


def _header() -> str:
    return f"""
<header class="site-header">
  <div class="container inner">
    <a href="{SITE_URL}/" class="logo" style="text-decoration:none">ET<span>-</span>SPOTTER</a>
    <a href="{SITE_URL}/" class="back-btn">← Ver scanner</a>
  </div>
</header>"""


def _subscribe() -> str:
    return f"""
<div class="subscribe-box">
  <h3>📬 Sinal diário às 22h — grátis</h3>
  <p>Score de todos os ETFs · alerta de regime SPY · rotação de categorias</p>
  <form action="{BEEHIIV_URL}/subscribe" method="POST" target="_blank" class="sub-form">
    <input type="email" name="email" placeholder="o teu email" required>
    <button type="submit">Subscrever</button>
  </form>
  <p class="privacy">Sem spam. Cancelas quando quiseres.</p>
</div>"""


def _cta_scanner(msg: str = "Ver scores actuais de todos os ETFs") -> str:
    return f"""
<div class="cta-scanner">
  <h3>📊 ET-Spotter — Scanner Quantitativo de ETFs UCITS</h3>
  <p>{msg}</p>
  <a href="{SITE_URL}/" class="btn-primary">Abrir scanner →</a>
</div>"""


def _footer() -> str:
    return f"""
<footer class="site-footer">
  <div class="container">
    <p>© ET-Spotter · <a href="{SITE_URL}/">et-spotter.com</a> · Dados via yfinance · Actualizado diariamente</p>
    <p style="margin-top:6px">Informação técnica e educacional. Não constitui aconselhamento financeiro.
    Consulta sempre um profissional antes de investir.</p>
  </div>
</footer>"""


def article_page(
    slug: str,
    title: str,
    description: str,
    keywords: str,
    tag: str,
    content_html: str,
    faqs: list[dict] | None = None,
) -> str:
    faq_schema = ""
    faq_html   = ""
    if faqs:
        faq_schema = json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faqs
            ]
        }, ensure_ascii=False, separators=(',', ':'))
        faq_html = '<h2>Perguntas frequentes</h2><div class="faq-list">'
        for f in faqs:
            faq_html += f'<div class="faq-item"><p class="faq-q">{f["q"]}</p><p class="faq-a">{f["a"]}</p></div>'
        faq_html += '</div>'

    article_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "author": {"@type": "Organization", "name": "ET-Spotter", "url": SITE_URL},
        "publisher": {"@type": "Organization", "name": "ET-Spotter", "url": SITE_URL},
        "datePublished": TODAY,
        "dateModified": TODAY,
        "url": f"{SITE_URL}/{slug}.html"
    }, ensure_ascii=False, separators=(',', ':'))

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#080a10">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="keywords" content="{keywords}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{SITE_URL}/{slug}.html">
  <meta property="og:type" content="article">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{SITE_URL}/{slug}.html">
  <meta property="og:image" content="{SITE_URL}/assets/banner.svg">
  <meta property="og:site_name" content="ET-Spotter">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <script type="application/ld+json">{article_schema}</script>
  {"<script type='application/ld+json'>" + faq_schema + "</script>" if faq_schema else ""}
  {FONTS}
  {CSS}
</head>
<body>
{_header()}
<div class="container">
  <article class="article">
    <div class="article-tag">{tag}</div>
    <h1>{title}</h1>
    <div class="article-meta">ET-Spotter · Actualizado em {TODAY.replace("-", "/")} · Leitura: ~5 min</div>
    {content_html}
    {faq_html}
    {_subscribe()}
  </article>
</div>
{_footer()}
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# ARTIGOS
# ══════════════════════════════════════════════════════════════════════════════

ARTICLES = []

# ── 1. VWCE vs IWDA ───────────────────────────────────────────────────────────
ARTICLES.append(dict(
    slug="vwce-vs-iwda",
    title="VWCE vs IWDA — Qual escolher? Comparação completa para investidores europeus",
    description="Comparação detalhada entre VWCE (Vanguard FTSE All-World) e IWDA (iShares MSCI World). TER, cobertura, mercados emergentes, liquidez e quando escolher cada um.",
    keywords="VWCE vs IWDA, VWCE IWDA diferença, Vanguard FTSE All-World, iShares MSCI World, ETF UCITS Portugal, melhor ETF mundo",
    tag="● COMPARAÇÃO DE ETFs",
    faqs=[
        {"q": "Qual a principal diferença entre VWCE e IWDA?",
         "a": "O VWCE (FTSE All-World) inclui mercados emergentes (~12% do peso) e cobre ~3.700 empresas. O IWDA (MSCI World) cobre apenas mercados desenvolvidos com ~1.500 empresas. O VWCE é um fundo completo; o IWDA precisa de ser complementado com um ETF de emergentes (ex. EIMI) para cobertura global."},
        {"q": "VWCE ou IWDA + EIMI?",
         "a": "VWCE é mais simples (um só fundo, um só rebalanceamento). IWDA + EIMI dá-te mais controlo: podes ajustar o peso em emergentes conforme a tua convicção. Para a maioria dos investidores passivos, VWCE é suficiente."},
        {"q": "Qual tem melhor desempenho histórico?",
         "a": "Depende do período. Quando os mercados emergentes superam os desenvolvidos, o VWCE tem vantagem. Em períodos de dominância americana, o IWDA tende a sair-se melhor por ter maior peso nos EUA. No longo prazo, a diferença é pequena."},
        {"q": "Qual é mais barato?",
         "a": "O IWDA tem TER de 0,20% vs 0,22% do VWCE — diferença de 0,02% ao ano. Negligível. Não use o TER como critério único de escolha."},
    ],
    content_html=f"""
<p>VWCE e IWDA são os dois ETFs de acumulação mais populares entre investidores passivos europeus. Ambos seguem índices globais, ambos acumulam dividendos, ambos estão domiciliados na Irlanda (vantagem fiscal). A grande questão é: <strong>qual cobre melhor o mercado mundial?</strong></p>

{_cta_scanner("Ver o score actual de VWCE e IWDA no scanner quantitativo")}

<h2>Ficha técnica comparativa</h2>
<div class="table-wrap">
<table>
<tr><th></th><th>VWCE</th><th>IWDA</th></tr>
<tr><td>Nome completo</td><td>Vanguard FTSE All-World UCITS ETF (USD) Acc</td><td>iShares Core MSCI World UCITS ETF (Acc)</td></tr>
<tr><td>ISIN</td><td>IE00B3RBWM25</td><td>IE00B4L5Y983</td></tr>
<tr><td>Índice</td><td>FTSE All-World</td><td>MSCI World</td></tr>
<tr><td>TER</td><td>0,22% / ano</td><td class="winner">0,20% / ano</td></tr>
<tr><td>Nº de posições</td><td class="winner">~3.700 empresas</td><td>~1.500 empresas</td></tr>
<tr><td>Mercados emergentes</td><td class="winner">Sim (~12%)</td><td>Não</td></tr>
<tr><td>Países cobertos</td><td class="winner">~50</td><td>~23</td></tr>
<tr><td>Dividendos</td><td>Acumulação</td><td>Acumulação</td></tr>
<tr><td>Domicílio</td><td>Irlanda</td><td>Irlanda</td></tr>
<tr><td>Replica</td><td>Física (amostragem)</td><td>Física (amostragem)</td></tr>
</table>
</div>

<h2>A diferença que realmente importa: mercados emergentes</h2>
<p>O IWDA cobre apenas os <strong>mercados desenvolvidos</strong> — EUA, Europa, Japão, Austrália, etc. Os EUA representam ~70% do índice. Não inclui China, Índia, Brasil, Coreia do Sul ou Taiwan.</p>
<p>O VWCE adiciona os <strong>mercados emergentes</strong> (~12% do peso), que incluem mais de 1.000 empresas em países em desenvolvimento. Essa exposição reduz ligeiramente a concentração nos EUA e dá acesso ao crescimento de economias emergentes.</p>

<div class="callout green">
<strong>Regra prática:</strong> Se queres um único ETF que cubra o mercado mundial completo, escolhe o <strong>VWCE</strong>. Se já tens ou queres controlar separadamente o peso em emergentes, usa <strong>IWDA + EIMI</strong>.
</div>

<h2>Estratégia IWDA + EIMI</h2>
<p>Alguns investidores preferem separar os dois blocos:</p>
<ul>
<li><strong>IWDA</strong> — 88% do portfólio → mercados desenvolvidos</li>
<li><strong>EIMI</strong> (iShares Core MSCI EM IMI, TER 0,18%) — 12% → mercados emergentes</li>
</ul>
<p>Esta configuração replica aproximadamente o VWCE com custos ligeiramente inferiores, mas exige rebalanceamento manual periódico. Para a maioria dos investidores com portfólios abaixo de €100.000, a diferença de custos não justifica a complexidade extra.</p>

<h2>Quando o VWCE é melhor</h2>
<ul>
<li>Queres simplicidade: um único ETF, um único rebalanceamento</li>
<li>Estás a começar e não queres gerir dois fundos</li>
<li>Acreditas que os mercados emergentes têm potencial de crescimento no longo prazo</li>
<li>O teu montante investido não justifica optimização de 0,02% de TER</li>
</ul>

<h2>Quando o IWDA é melhor</h2>
<ul>
<li>Já tens exposição a emergentes noutro veículo (ex. EIMI, fundo de pensões)</li>
<li>Preferes uma composição mais concentrada nos mercados desenvolvidos, com maior peso EUA</li>
<li>Queres controlo granular sobre a alocação geográfica</li>
</ul>

<h2>Scores actuais no ET-Spotter</h2>
<p>O ET-Spotter analisa diariamente VWCE, IWDA e centenas de outros ETFs UCITS usando um score composto de momentum, tendência, risco e alpha relativo. Consulta os scores actuais abaixo:</p>

{_cta_scanner("Ver score VWCE vs IWDA — actualizado diariamente")}

<h2>Conclusão</h2>
<p>Para a grande maioria dos investidores europeus com horizonte de longo prazo, <strong>VWCE e IWDA são ambas excelentes escolhas</strong>. A diferença real é a exposição a emergentes: se a queres integrada, VWCE. Se preferes gerir separadamente, IWDA + EIMI.</p>
<p>Não existe resposta errada. O que existe é a resposta errada para o <em>teu</em> perfil — e essa descobres-a clarificando quanto de exposição a emergentes faz sentido para a tua estratégia.</p>
"""))

# ── 2. Melhor ETF Europa ──────────────────────────────────────────────────────
ARTICLES.append(dict(
    slug="melhor-etf-europa",
    title="Melhores ETFs UCITS para Investidores Europeus — Ranking 2025",
    description="Quais os melhores ETFs UCITS disponíveis para investidores europeus em 2025? Análise por categoria: mercado mundial, tecnologia, emergentes, ESG e imobiliário.",
    keywords="melhor ETF Europa 2025, melhores ETFs UCITS, ETF investidores europeus, ETF Portugal 2025, ranking ETF Europa",
    tag="● RANKING & ANÁLISE",
    faqs=[
        {"q": "Qual o melhor ETF para investidores europeus em 2025?",
         "a": "Não existe um único 'melhor' ETF — depende do teu perfil de risco, horizonte temporal e objectivos. Para exposição global diversificada, VWCE e IWDA são as escolhas mais populares. Para tecnologia, o Invesco QQQ UCITS (EQQQ) ou o iShares S&P 500 Information Technology. Use o ET-Spotter para ver qual tem melhor score quantitativo no momento actual."},
        {"q": "O que é um ETF UCITS e porquê é importante para europeus?",
         "a": "UCITS (Undertakings for Collective Investment in Transferable Securities) é um quadro regulatório europeu que garante protecção ao investidor, transparência e diversificação mínima. ETFs UCITS têm tratamento fiscal vantajoso para residentes na UE vs ETFs americanos (não sujeitos à retenção na fonte de 30% dos dividendos americanos para não-residentes)."},
        {"q": "Devo escolher ETFs de acumulação ou distribuição?",
         "a": "Para maximizar o crescimento do capital, os ETFs de acumulação (Acc) reinvestem os dividendos automaticamente, aproveitando o efeito de juro composto e diferindo o imposto. Os de distribuição (Dist) são preferíveis se precisas de rendimento regular. Para investidores em fase de acumulação, Acc é geralmente superior."},
    ],
    content_html=f"""
<p>Com mais de 84 ETFs UCITS analisados diariamente pelo ET-Spotter, a escolha pode parecer difícil. Este guia organiza as melhores opções por categoria, com base em critérios académicos de momentum, tendência, risco e alpha.</p>

<div class="callout">
<strong>Nota metodológica:</strong> o ET-Spotter não faz recomendações de investimento. Os scores medem convergência estatística de múltiplos factores técnicos — não predizem retornos futuros. Consulta sempre um profissional antes de investir.
</div>

<h2>Porquê UCITS e não ETFs americanos?</h2>
<p>Investidores europeus devem preferir ETFs com estrutura UCITS por três razões principais:</p>
<ul>
<li><strong>Regulação europeia</strong>: diversificação obrigatória, limites de concentração, relatórios periódicos</li>
<li><strong>Fiscalidade</strong>: acesso ao tratamento preferencial de dividendos em muitos países da UE</li>
<li><strong>Disponibilidade</strong>: brokers europeus como DEGIRO, Trade Republic e XTB limitam ou proíbem ETFs americanos para retalho</li>
</ul>

<h2>Categorias principais e ETFs de referência</h2>

<h3>🌍 Mercado global</h3>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>Índice</th><th>TER</th><th>Cobertura</th></tr>
<tr><td><strong>VWCE</strong></td><td>FTSE All-World</td><td>0,22%</td><td>Desenvolvidos + Emergentes</td></tr>
<tr><td><strong>IWDA</strong></td><td>MSCI World</td><td>0,20%</td><td>Mercados desenvolvidos</td></tr>
<tr><td><strong>SPYI</strong></td><td>S&amp;P 500</td><td>0,03%</td><td>500 maiores empresas EUA</td></tr>
</table>
</div>

<h3>💻 Tecnologia</h3>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>Índice</th><th>TER</th><th>Nota</th></tr>
<tr><td><strong>EQQQ</strong></td><td>NASDAQ-100</td><td>0,30%</td><td>Top 100 tech EUA</td></tr>
<tr><td><strong>IUIT</strong></td><td>MSCI World IT</td><td>0,25%</td><td>Tecnologia global</td></tr>
</table>
</div>

<h3>🌱 Mercados emergentes</h3>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>Índice</th><th>TER</th><th>Cobertura</th></tr>
<tr><td><strong>EIMI</strong></td><td>MSCI EM IMI</td><td>0,18%</td><td>Emergentes amplo</td></tr>
<tr><td><strong>VFEM</strong></td><td>FTSE Emerging</td><td>0,22%</td><td>Emergentes Vanguard</td></tr>
</table>
</div>

<h3>♻️ ESG / Sustentável</h3>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>TER</th><th>Critério ESG</th></tr>
<tr><td><strong>SUAS</strong></td><td>0,20%</td><td>MSCI World SRI (critérios estritos)</td></tr>
<tr><td><strong>ESGW</strong></td><td>0,20%</td><td>MSCI World ESG Enhanced</td></tr>
<tr><td><strong>VFTE</strong></td><td>0,24%</td><td>FTSE All-World ESG</td></tr>
</table>
</div>

<h3>🏗️ Imobiliário (REITs)</h3>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>TER</th><th>Cobertura</th></tr>
<tr><td><strong>IWDP</strong></td><td>0,59%</td><td>REITs globais (iShares)</td></tr>
<tr><td><strong>EPRA</strong></td><td>0,40%</td><td>REITs Europa</td></tr>
</table>
</div>

<h2>Como usar o ET-Spotter para escolher</h2>
<p>O scanner analisa diariamente todos estes ETFs com 4 factores:</p>
<ul>
<li><strong>Momentum (35%)</strong> — retorno 12-1M, 6M e 3M (Jegadeesh &amp; Titman, 1993)</li>
<li><strong>Tendência (25%)</strong> — posição relativa à SMA200 (Faber, 2007)</li>
<li><strong>Risco (25%)</strong> — Sharpe ratio, drawdown máximo, volatilidade 21d</li>
<li><strong>Alpha (15%)</strong> — força relativa vs SPY, alpha cross-sectional (Kakushadze, 2015)</li>
</ul>
<p>Um score ≥ 0,62 com ≥ 3 sinais activos corresponde a <span class="badge bg">FORTE COMPRA</span>. Entre 0,54 e 0,62 corresponde a <span class="badge bb">COMPRA</span>.</p>

{_cta_scanner("Ver scores actuais de todos os ETFs UCITS — actualizado diariamente")}

<h2>Critérios para escolher o teu ETF</h2>
<ol>
<li><strong>Horizonte temporal</strong>: horizonte longo (10+ anos) tolera mais volatilidade → mais acções, incluindo emergentes</li>
<li><strong>Exposição geográfica</strong>: queres concentração nos EUA (S&amp;P 500) ou diversificação global (VWCE)?</li>
<li><strong>Acumulação vs distribuição</strong>: em fase de crescimento, acumulação é mais eficiente fiscalmente</li>
<li><strong>TER</strong>: diferenças de 0,05% ao ano têm impacto mínimo no longo prazo — não optimizes em excesso</li>
<li><strong>Score técnico actual</strong>: o ET-Spotter indica quais têm momentum e tendência favoráveis no momento</li>
</ol>
"""))

# ── 3. ETF ESG Europa ────────────────────────────────────────────────────────
ARTICLES.append(dict(
    slug="etf-esg-europa",
    title="Melhores ETFs ESG e Sustentáveis para Investidores Europeus 2025",
    description="Guia completo sobre ETFs ESG UCITS: diferenças entre SRI, ESG Enhanced e exclusão, principais opções disponíveis e como avaliar o impacto real.",
    keywords="ETF ESG Europa, ETF sustentável UCITS, ETF SRI Portugal, investimento responsável ETF, SUAS ESGW VFTE",
    tag="● ESG & SUSTENTABILIDADE",
    faqs=[
        {"q": "ETF ESG vale a pena?",
         "a": "Depende dos teus objectivos. ETFs ESG têm, em muitos períodos, desempenho similar aos convencionais com ligeiramente menor volatilidade. Contudo, excluem sectores como combustíveis fósseis e armamento, o que pode reduzir diversificação em determinados ciclos. Se o alinhamento ético é importante para ti, existem opções de qualidade com TERs competitivos."},
        {"q": "Qual a diferença entre ESG, SRI e ESG Enhanced?",
         "a": "SRI (Socially Responsible Investing) aplica critérios mais estritos — exclui mais sectores e selecciona apenas os melhores em cada indústria. ESG Enhanced aplica critérios mais leves, tipicamente apenas excluindo os piores. O resultado é que ETFs SRI têm menos empresas (mais concentrados) enquanto os ESG Enhanced mantêm composição próxima do índice-mãe."},
        {"q": "ETFs ESG têm pior desempenho?",
         "a": "Historicamente a diferença é pequena e varia por período. Em anos com commodities e petróleo em alta (ex. 2022), ETFs ESG ficaram atrás por excluírem energia fóssil. Em anos de liderança tecnológica, a diferença é mínima. No longo prazo, a academic evidence não mostra penalização sistemática de desempenho."},
    ],
    content_html=f"""
<p>O investimento sustentável deixou de ser nicho. Hoje existem dezenas de ETFs UCITS com critérios ESG disponíveis em brokers europeus, cobrindo desde o mercado mundial a sectores específicos. O desafio é perceber o que cada rótulo significa na prática.</p>

<h2>O que significam ESG, SRI e ESG Enhanced</h2>

<h3>ESG (Environmental, Social, Governance)</h3>
<p>O termo genérico. Um ETF que diz ser "ESG" pode significar coisas muito diferentes dependendo do fornecedor. Geralmente implica avaliação das empresas em três dimensões: impacto ambiental, práticas sociais e qualidade de governança.</p>

<h3>SRI (Socially Responsible Investing)</h3>
<p>Mais restritivo. Além dos critérios ESG, exclui empresas em sectores controversos (armamento, tabaco, jogos, combustíveis fósseis) e selecciona apenas as melhores em cada indústria pelo critério "best-in-class".</p>

<h3>ESG Enhanced / Optimized</h3>
<p>O mais próximo do índice convencional. Aplica apenas exclusões básicas (armas nucleares, tabaco) mas mantém a maioria das empresas. Menor tracking error face ao índice-mãe.</p>

<div class="callout yellow">
<strong>Atenção ao "greenwashing":</strong> nem todos os ETFs com "ESG" no nome têm critérios rigorosos. Verifica sempre o índice subjacente e as políticas de exclusão no KIID (documento de informação).
</div>

<h2>Principais ETFs ESG UCITS disponíveis</h2>
<div class="table-wrap">
<table>
<tr><th>ETF</th><th>Tipo</th><th>TER</th><th>Índice</th><th>Empresas</th></tr>
<tr><td><strong>SUAS</strong></td><td><span class="badge by">SRI Estrito</span></td><td>0,20%</td><td>MSCI World SRI</td><td>~400</td></tr>
<tr><td><strong>ESGW</strong></td><td><span class="badge bb">ESG Enhanced</span></td><td>0,20%</td><td>MSCI World ESG Enhanced</td><td>~1.400</td></tr>
<tr><td><strong>VFTE</strong></td><td><span class="badge bb">ESG Enhanced</span></td><td>0,24%</td><td>FTSE All-World ESG</td><td>~1.600</td></tr>
<tr><td><strong>MSRW</strong></td><td><span class="badge by">SRI Estrito</span></td><td>0,18%</td><td>MSCI World SRI PAB</td><td>~400</td></tr>
</table>
</div>

<h2>ESG vs índice convencional: o que mudas na prática</h2>
<p>Usando o SUAS (MSCI World SRI) como exemplo, em comparação com o IWDA (MSCI World):</p>
<ul>
<li><strong>Removido</strong>: petróleo &amp; gás, carvão, armamento, tabaco, jogos — aproximadamente 10-15% do índice convencional</li>
<li><strong>Sobre-ponderado</strong>: tecnologia, saúde, utilities renováveis</li>
<li><strong>TER igual</strong>: 0,20% — sem custo extra por ser ESG</li>
<li><strong>Menos diversificação</strong>: ~400 vs ~1.500 empresas — maior concentração sectorial</li>
</ul>

<h2>Para quem faz sentido um ETF ESG</h2>
<ul>
<li>Investidores que preferem não ter exposição a combustíveis fósseis, armamento ou tabaco</li>
<li>Quem acredita que práticas ESG criam valor de longo prazo</li>
<li>Investidores com restrições éticas pessoais ou institucionais</li>
</ul>

<h2>Para quem pode não fazer sentido</h2>
<ul>
<li>Quem prioriza máxima diversificação sectorial</li>
<li>Quem prevê que sectores excluídos (energia, defesa) terão forte desempenho no curto prazo</li>
<li>Quem suspeita de greenwashing e prefere controlo directo (via ETF convencional + selecção própria)</li>
</ul>

{_cta_scanner("Ver scores actuais de ETFs ESG no scanner — SUAS, ESGW, VFTE e outros")}

<h2>Score técnico dos ETFs ESG</h2>
<p>O ET-Spotter analisa ETFs ESG com o mesmo rigor que os convencionais: momentum multi-período, tendência relativa à SMA200, risco e alpha vs SPY. Em períodos em que o sector tecnológico lidera, ETFs ESG tendem a ter scores competitivos por sobre-ponderarem tech. Em ciclos de commodities, ficam normalmente abaixo dos índices amplos.</p>
"""))

# ── 4. Estratégia Momentum ────────────────────────────────────────────────────
ARTICLES.append(dict(
    slug="estrategia-momentum",
    title="Estratégia Momentum em ETFs — O que é e como aplicar em Portugal",
    description="Guia prático sobre a estratégia momentum aplicada a ETFs UCITS. Base académica, como o ET-Spotter usa momentum e como implementar na prática.",
    keywords="estratégia momentum ETF, momentum investing Portugal, Jegadeesh Titman momentum, ETF momentum UCITS, como investir momentum",
    tag="● ESTRATÉGIA QUANTITATIVA",
    faqs=[
        {"q": "O que é a estratégia momentum?",
         "a": "Momentum é a tendência de activos com forte desempenho recente continuarem a superar no curto a médio prazo (3-12 meses). É uma das anomalias mais estudadas e replicadas em finanças — documentada por Jegadeesh & Titman em 1993 e confirmada em dezenas de mercados e classes de activos desde então."},
        {"q": "O momentum funciona em ETFs?",
         "a": "Sim. Estudos académicos e práticos (Faber 2007, Antonacci 2014) mostram que momentum funciona bem em ETFs diversificados, especialmente quando combinado com um filtro de tendência absoluta (estar acima ou abaixo da SMA de 200 dias). Evita grandes drawdowns em mercados bear."},
        {"q": "Momentum é market timing?",
         "a": "Não exactamente. Market timing implica prever pontos de inversão. Momentum é uma estratégia sistemática e baseada em regras — compra o que está a subir, evita o que está a cair. Não prevê o futuro; reage à evidência presente com um modelo reproduzível."},
    ],
    content_html=f"""
<p>A maioria dos investidores sabe que "comprar barato e vender caro" é a ideia central do value investing. Menos conhecida mas igualmente robusta academicamente é a estratégia oposta: <strong>comprar o que já está a subir</strong>. Isso é momentum.</p>

<h2>A base académica</h2>
<p>Em 1993, Jegadeesh &amp; Titman publicaram o paper seminal <em>"Returns to Buying Winners and Selling Losers"</em> no Journal of Finance. A conclusão: acções com forte retorno nos 3-12 meses anteriores continuam a superar nos 3-12 meses seguintes — e acções com fraco desempenho continuam a ficar abaixo.</p>
<p>Esta anomalia foi desde então confirmada em:</p>
<ul>
<li>Mais de 40 países e mercados diferentes</li>
<li>ETFs de índice, acções individuais e obrigações</li>
<li>Períodos de até 200 anos de dados históricos</li>
</ul>
<p>Não é uma coincidência estatística. É um dos efeitos mais replicados em finanças académicas.</p>

<div class="callout green">
<strong>Porquê funciona?</strong> A teoria comportamental sugere que os investidores reagem lentamente à nova informação (underreaction) e depois sobereagem (overreaction) — criando tendências exploráveis. Além disso, fundos institucionais têm mandatos que os forçam a comprar vencedores e vender perdedores, amplificando o efeito.
</div>

<h2>Momentum absoluto vs relativo</h2>

<h3>Momentum relativo (cross-sectional)</h3>
<p>Compara o desempenho de diferentes activos entre si e compra os que estão à frente dos pares. Exemplo: de 10 ETFs de mercado, investir nos 3 com maior retorno nos últimos 12 meses.</p>

<h3>Momentum absoluto (trend following)</h3>
<p>Gary Antonacci popularizou o conceito em 2014: antes de comprar um activo pelo momentum relativo, verifica se tem momentum positivo em absoluto — ou seja, se está acima da sua própria média histórica. Se estiver em tendência de baixa, fica em liquidez.</p>
<p>Esta combinação é conhecida como <strong>Dual Momentum</strong> e reduz significativamente os drawdowns máximos em mercados bear.</p>

<h2>Como o ET-Spotter usa momentum</h2>
<p>O score composto do ET-Spotter integra momentum em 35% do peso total, com três janelas temporais:</p>
<ul>
<li><strong>12-1M</strong>: retorno dos últimos 12 meses excluindo o último (neutraliza reversão de curto prazo)</li>
<li><strong>6M</strong>: janela de médio prazo</li>
<li><strong>3M</strong>: janela mais recente para captar aceleração</li>
</ul>
<p>O momentum é combinado com tendência (posição vs SMA200), risco (Sharpe, drawdown) e alpha relativo para gerar um score 0-1. Scores ≥ 0,62 com múltiplos sinais activos recebem classificação <span class="badge bg">FORTE COMPRA</span>.</p>

<h2>Implementação prática para investidores europeus</h2>

<h3>Versão simples (Faber 2007)</h3>
<ol>
<li>Escolhe um universo de 5-10 ETFs (ex: VWCE, EQQQ, EIMI, IWDP, IUST)</li>
<li>No final de cada mês, ordena por retorno 12-1M</li>
<li>Investe nos top 3</li>
<li>Se um ETF estiver abaixo da SMA200, substitui por obrigações ou liquidez</li>
</ol>

<h3>Versão avançada (Dual Momentum)</h3>
<ol>
<li>Compara o ETF com SPY (momentum relativo)</li>
<li>Verifica se o ETF tem retorno positivo nos últimos 12 meses (momentum absoluto)</li>
<li>Só entra se ambas as condições forem verdade</li>
</ol>

<div class="callout yellow">
<strong>Atenção:</strong> momentum tem maior rotatividade de carteira que buy-and-hold. Considera os custos de transacção e o impacto fiscal de cada rebalanceamento antes de implementar.
</div>

{_cta_scanner("Ver quais ETFs UCITS têm momentum mais forte hoje")}

<h2>O que o momentum não resolve</h2>
<p>Momentum tem um ponto fraco bem documentado: <strong>crashes rápidos</strong>. Em quedas abruptas de mercado (como Março 2020), pode demorar algumas semanas a sair de posições — gerando drawdowns temporários superiores ao buy-and-hold. A combinação com o filtro de tendência absoluta (SMA200) mitiga mas não elimina este risco.</p>
"""))

# ── 5. Guia ETF UCITS ─────────────────────────────────────────────────────────
ARTICLES.append(dict(
    slug="guia-etf-ucits",
    title="O que é um ETF UCITS? Guia completo para investidores portugueses",
    description="Guia completo sobre ETFs UCITS: o que são, como funcionam, como comprar em Portugal, diferença entre acumulação e distribuição, e como ler um score técnico.",
    keywords="o que é ETF UCITS, como comprar ETF Portugal, ETF acumulação distribuição, investir ETF Portugal, guia ETF iniciantes",
    tag="● GUIA PARA INICIANTES",
    faqs=[
        {"q": "O que é um ETF?",
         "a": "ETF (Exchange Traded Fund) é um fundo de investimento que é transaccionado em bolsa como se fosse uma acção. Ao comprar um ETF, estás a comprar uma quota de um cesto diversificado de activos — que pode incluir centenas ou milhares de empresas, obrigações ou commodities — com uma única transacção."},
        {"q": "O que significa UCITS?",
         "a": "UCITS (Undertakings for Collective Investment in Transferable Securities) é um quadro regulatório europeu criado para proteger os investidores de retalho. Garante diversificação mínima, transparência de custos, relatórios periódicos e supervisão regulatória. Todos os ETFs disponíveis para retalho em Portugal devem ser UCITS."},
        {"q": "Onde posso comprar ETFs em Portugal?",
         "a": "Os brokers mais usados em Portugal são DEGIRO, Trade Republic, XTB e Interactive Brokers. Todos permitem acesso a centenas de ETFs UCITS nas principais bolsas europeias (Euronext Amsterdam, Xetra, London Stock Exchange)."},
        {"q": "ETF de acumulação ou distribuição?",
         "a": "Acumulação (Acc) reinveste os dividendos automaticamente — mais eficiente em fase de crescimento. Distribuição (Dist) paga dividendos em dinheiro — útil se precisas de rendimento regular. Para a maioria dos investidores em fase de poupança, acumulação é preferível."},
    ],
    content_html=f"""
<p>Se estás a começar a investir e já ouviste falar de ETFs mas não tens claro o que são, como funcionam ou como comprar — este guia foi escrito para ti.</p>

<h2>O que é um ETF?</h2>
<p>Um <strong>ETF (Exchange Traded Fund)</strong> é um fundo de investimento que replica um índice de mercado e é transaccionado em bolsa em tempo real, como uma acção normal.</p>
<p>Quando compras uma unidade de VWCE (um ETF popular), estás efectivamente a comprar uma fatia de ~3.700 empresas de todo o mundo — da Apple à Samsung, da Nestlé à Petrobras — com uma única transacção e uma comissão de corretagem.</p>

<div class="callout green">
<strong>A vantagem central dos ETFs:</strong> diversificação instantânea a custo muito baixo. Um ETF de mercado mundial custa tipicamente 0,20-0,22% ao ano. Um fundo de gestão activa equivalente pode custar 1,5-2,5%.
</div>

<h2>O que significa UCITS?</h2>
<p>UCITS é um quadro legal europeu (Directiva 2009/65/CE) que define as regras para fundos de investimento vendidos a investidores de retalho na União Europeia. Um ETF UCITS tem de cumprir:</p>
<ul>
<li><strong>Diversificação mínima</strong>: nenhum activo pode representar mais de 10% do fundo</li>
<li><strong>Transparência</strong>: publicação de KIID (Key Investor Information Document) — documento de 2 páginas com todos os custos e riscos</li>
<li><strong>Liquidez</strong>: possibilidade de resgatar em qualquer dia de mercado</li>
<li><strong>Supervisão</strong>: regulado por autoridade europeia (em Portugal, CMVM)</li>
</ul>
<p>Para investidores portugueses, <strong>só estão disponíveis ETFs UCITS</strong> nos brokers de retalho. ETFs americanos (como os da Vanguard EUA) não podem ser vendidos a retalho europeu.</p>

<h2>Como funcionam os ETFs na prática</h2>
<p>Imagina o índice MSCI World como uma lista com as 1.500 maiores empresas do mundo desenvolvido. O ETF IWDA (iShares Core MSCI World) <strong>compra acções nessa proporção exacta</strong> — se a Apple representa 4% do índice, o ETF tem 4% em Apple.</p>
<p>Quando o índice sobe, o preço do ETF sobe proporcionalmente. Quando uma empresa é removida do índice, o ETF vende-a e compra o substituto. <strong>Tudo automático, sem que tenhas de fazer nada.</strong></p>

<h2>Acumulação vs Distribuição</h2>
<div class="table-wrap">
<table>
<tr><th></th><th>Acumulação (Acc)</th><th>Distribuição (Dist)</th></tr>
<tr><td>Dividendos</td><td>Reinvestidos automaticamente</td><td>Pagos em dinheiro</td></tr>
<tr><td>Crescimento</td><td>Beneficia do juro composto</td><td>Menor crescimento do capital</td></tr>
<tr><td>Fiscalidade PT</td><td>Imposto diferido até venda</td><td>IRS sobre dividendos recebidos</td></tr>
<tr><td>Ideal para</td><td>Fase de acumulação (longo prazo)</td><td>Fase de rendimento (reforma)</td></tr>
</table>
</div>
<p>Para a esmagadora maioria dos investidores em fase de crescimento de capital, <strong>acumulação é superior</strong> — os dividendos são automaticamente reinvestidos, o que maximiza o efeito do juro composto e adia o imposto.</p>

<h2>Como comprar ETFs em Portugal</h2>
<ol>
<li><strong>Escolhe um broker</strong>: DEGIRO, Trade Republic e XTB são os mais populares em Portugal para ETFs. Compara comissões antes de abrir conta</li>
<li><strong>Abre conta</strong>: processo online, 10-15 minutos, com verificação de identidade</li>
<li><strong>Deposita fundos</strong>: transferência bancária, geralmente sem custo</li>
<li><strong>Pesquisa o ETF pelo ISIN ou ticker</strong>: ex. IE00B3RBWM25 para VWCE</li>
<li><strong>Compra</strong>: ordem de mercado (ao preço actual) ou ordem limite (ao preço que defines)</li>
</ol>

<div class="callout">
<strong>Tip:</strong> prefere sempre comprar na bolsa onde o ETF tem maior volume (Xetra ou Euronext Amsterdam para a maioria dos ETFs UCITS). Evita a London Stock Exchange para ETFs cotados em libras se queres evitar risco cambial.
</div>

<h2>Como ler o score do ET-Spotter</h2>
<p>O ET-Spotter analisa cada ETF com um score 0-1 composto por quatro factores académicos:</p>
<ul>
<li><strong>Momentum</strong>: o ETF está a ganhar força? Retornos 12-1M, 6M, 3M todos positivos?</li>
<li><strong>Tendência</strong>: o preço está acima da média de 200 dias (SMA200)?</li>
<li><strong>Risco</strong>: o retorno justifica o risco? Sharpe ratio, drawdown máximo, volatilidade</li>
<li><strong>Alpha</strong>: o ETF está a superar o benchmark (SPY)?</li>
</ul>
<p>Um score alto não garante retorno futuro — <strong>não constitui aconselhamento financeiro</strong>. Indica convergência de múltiplos factores técnicos que historicamente estiveram associados a períodos de força relativa.</p>

{_cta_scanner("Explorar scores de todos os ETFs UCITS — actualizado diariamente")}
"""))


# ══════════════════════════════════════════════════════════════════════════════
# GERAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    slugs = []
    for art in ARTICLES:
        html = article_page(**art)
        out  = DOCS / f"{art['slug']}.html"
        out.write_text(html, encoding="utf-8")
        slugs.append(art["slug"])
        print(f"[OK] {out.name}  ({len(html)//1024} KB)")

    # actualiza sitemap.xml com os novos artigos
    sitemap_path = DOCS / "sitemap.xml"
    url_entries  = f"""  <url>
    <loc>https://et-spotter.com/</loc>
    <xhtml:link rel="alternate" hreflang="pt" href="https://et-spotter.com/?lang=pt"/>
    <xhtml:link rel="alternate" hreflang="en" href="https://et-spotter.com/?lang=en"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="https://et-spotter.com/"/>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""
    for slug in slugs:
        url_entries += f"""
  <url>
    <loc>https://et-spotter.com/{slug}.html</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
    <lastmod>{TODAY}</lastmod>
  </url>"""
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{url_entries}
</urlset>
"""
    sitemap_path.write_text(sitemap, encoding="utf-8")
    print(f"[OK] sitemap.xml actualizado ({len(slugs)+1} URLs)")


if __name__ == "__main__":
    main()
