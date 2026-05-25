# ET-Spotter

Sistema quantitativo de monitorização de ETFs com scoring multi-fator, alertas por email e relatórios semanais automatizados via GitHub Actions.

## Estrutura

```
etf-monitor/
 ├── config/etfs.json          # lista de ETFs, parâmetros, pesos
 ├── data/
 │    ├── hourly/              # snapshots intradiários (CSV por ETF)
 │    ├── daily/               # métricas agregadas + scores
 │    └── reports/             # gráficos e relatórios HTML
 ├── scripts/
 │    ├── fetch_intraday.py    # recolha via Alpha Vantage
 │    ├── compute_metrics.py   # SMA, MACD, volatilidade, drawdown
 │    ├── compute_score.py     # score multi-fator normalizado [0,1]
 │    ├── detect_alerts.py     # alertas extraordinários
 │    ├── weekly_report.py     # relatório semanal HTML + email
 │    ├── generate_charts.py   # gráficos (tendência, barras, heatmap)
 │    └── send_email.py        # envio SMTP via Gmail
 └── .github/workflows/
      ├── hourly.yml           # cron horário: fetch → métricas → score
      ├── alerts.yml           # cron :15: detecção e envio de alertas
      └── weekly.yml           # segunda 07h UTC: relatório + email
```

## Modelo de Scoring (v0.1)

| Fator     | Peso | Componentes                          |
|-----------|------|--------------------------------------|
| Momentum  | 40%  | ret_24h + ret_5d (normalizados)      |
| Tendência | 30%  | SMA20>SMA50 + MACD bullish (0–1)    |
| Risco     | 30%  | 1/volatilidade_30d (normalizado)     |

Score final ∈ [0, 1]. Valores > 0.5 são favoráveis.

## Configuração

### 1. API Alpha Vantage

Regista em [alphavantage.co](https://www.alphavantage.co) e obtém uma `API_KEY` gratuita.

### 2. Variáveis de ambiente (local)

Cria um ficheiro `.env` na raiz:

```env
ALPHAVANTAGE_API_KEY=<a_tua_chave>
EMAIL_FROM=teu@gmail.com
EMAIL_PASSWORD=<app_password_gmail>
EMAIL_TO=destino@email.com
```

> Para o Gmail, usa uma **App Password** (Conta Google → Segurança → Palavras-passe de aplicações).

### 3. GitHub Secrets

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Secret                  | Valor                          |
|-------------------------|--------------------------------|
| `ALPHAVANTAGE_API_KEY`  | Chave da Alpha Vantage         |
| `EMAIL_FROM`            | Endereço Gmail de envio        |
| `EMAIL_PASSWORD`        | App Password do Gmail          |
| `EMAIL_TO`              | Destinatário(s) dos emails     |

### 4. Permissões do repositório

**Settings → Actions → General → Workflow permissions** → selecciona **Read and write permissions**.

## Uso local

```bash
pip install -r requirements.txt

# 1. Recolher dados
python scripts/fetch_intraday.py

# 2. Calcular métricas
python scripts/compute_metrics.py

# 3. Calcular scores
python scripts/compute_score.py

# 4. Verificar alertas
python scripts/detect_alerts.py

# 5. Gerar gráficos
python scripts/generate_charts.py

# 6. Relatório semanal
python scripts/weekly_report.py
```

## Alertas

Os alertas são enviados por email quando:
- Queda > 2% na última hora
- Queda > 3% nas últimas 24h
- Volatilidade 30d acima do limiar configurado
- Drawdown > 10% face ao máximo histórico

Os limiares são configuráveis em `config/etfs.json` → `params.alert_thresholds`.

## Roadmap

- [ ] Fator Sentimento/Macro (VIX, news sentiment)
- [ ] Calibração de pesos com backtest histórico
- [ ] Dashboard web estático (GitHub Pages)
- [ ] Fluxos de capital (in/outflows)
