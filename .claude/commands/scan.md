# /scan — ET-Spotter Full Scan

Orquestra os 4 subagentes do ET-Spotter e produz uma tabela de estado consolidada.

## Sequência de execução

1. **data-fetcher** — lê scores_latest.csv → top-10 ETFs + regime + contagem de sinais
2. **model-runner** — lê model_report.txt + backtest_status.json → estado XGBoost + gate
3. **portfolio-tracker** — lê backtest_signals.csv → ROI por categoria + gate check
4. **alert-notifier** — recebe output do data-fetcher → decide se prepara alerta Telegram

Os agentes 2, 3 e 4 podem correr em paralelo após o agente 1 terminar.

## Output final obrigatório

Após receber os outputs de todos os agentes, apresenta esta tabela consolidada:

```
═══════════════════════════════════════════════════════
  ET-SPOTTER SCAN — {DATA_HOJE}
═══════════════════════════════════════════════════════

REGIME SPY: 🟢 BULL | 🔴 BEAR | ⚪ DESCONHECIDO

TOP-5 ETFs (score decrescente):
  #  ETF        score  sinal          ml_prob
  1  XXXX.L     0.856  RADAR MÁXIMO   0.51
  2  XXXX.L     0.851  RADAR MÁXIMO   0.44
  3  XXXX.L     0.830  RADAR MÁXIMO   0.10
  4  XXXX.L     0.822  EM DESTAQUE    0.25
  5  XXXX.L     0.811  EM DESTAQUE    0.78

SINAIS ACTIVOS:
  RADAR MÁXIMO:  N ETFs
  EM DESTAQUE:   N ETFs
  A OBSERVAR:    N ETFs

MODELO XGBOOST:
  Accuracy: 0.543 | ROC-AUC: 0.534
  Gate: ACTIVO (BULL) | INACTIVO (BEAR)

BACKTEST:
  Status: A_ACUMULAR (18/85 dias) | DISPONIVEL (N ep.)
  RADAR MÁXIMO: ret=+X.X% win=XX%  [ou N/D]
  EM DESTAQUE:  ret=+X.X% win=XX%  [ou N/D]

ALERTA TELEGRAM:
  ✅ APROVADO — comando pronto  |  ⛔ SUPRIMIDO (BEAR)  |  — SEM RADAR MÁXIMO
═══════════════════════════════════════════════════════
```

## Notas

- Nunca altera ficheiros durante o scan
- Linguagem neutra MiFID II em todos os outputs (RADAR MÁXIMO / EM DESTAQUE / A OBSERVAR)
- Se algum agente falhar, preenche a secção com `[INDISPONÍVEL]` e continua
