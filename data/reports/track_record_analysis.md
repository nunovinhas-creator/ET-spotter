# ET-Spotter: track-record completo e ensemble

**Regras aplicadas em ambos os escopos:** threshold 8%, holding mínimo 2 ciclos, máximo 3 novas posições por rotação, máximo 8 posições e custos de 30 bps round-trip.  
**Look-ahead:** o sinal é observado na data do ciclo e os retornos começam apenas no dia de dados seguinte.

## Escopos publicados

### Histórico completo

Fonte: `simulation_results.csv`  
Período: 2026-06-03 a 2026-09-24  
Ciclos: 6, dos quais 1 `PRE_ENSEMBLE` e 5 `VALID_ENSEMBLE_60_40`.

| Métrica | Resultado |
|---|---:|
| Retorno bruto composto | -19,96% |
| Retorno líquido | **-21,14%** |
| Max drawdown | -7,12% |
| Sharpe | -1,85 |
| Turnover médio | 82,6% |
| Custos totais | €128,45 |
| Correlação média | 70,6% |
| VWCE.DE buy-and-hold | +3,87% |
| CSPX.L buy-and-hold | +2,75% |

O histórico começa em 2026-06-03 porque é a primeira data em que os quatro sub-scores necessários para reconstruir o score v3 estão completos. Os dias anteriores têm score bruto, mas não têm componentes suficientes para uma reconstrução auditável.

### Ensemble fiável

Fonte: `simulation_results_valid_ensemble.csv`  
Período: 2026-06-09 a 2026-09-24  
Todos os ciclos têm score v3, `xgb_proba`, score final e pesos persistidos.

| Métrica | Resultado |
|---|---:|
| Número de ciclos | 5 |
| Retorno bruto composto | +5,08% |
| Retorno líquido | **+3,76%** |
| Max drawdown | -4,82% |
| Sharpe | +0,42 |
| Turnover médio | 84,2% |
| Custos totais | €130,06 |
| Correlação média | 63,9% |
| VWCE.DE buy-and-hold | +6,90% |
| CSPX.L buy-and-hold | +6,20% |

O ensemble fiável teve retorno positivo, mas ficou atrás de VWCE.DE em 3,14 pontos percentuais e de CSPX.L em 2,44 pontos percentuais.

## Rastreabilidade

Cada ciclo grava:

- `score_v3`, reconstruído apenas quando os quatro sub-scores estão presentes;
- `xgb_proba`, ou `null` no ciclo `PRE_ENSEMBLE`;
- `score_final`;
- pesos alvo e pesos ativos;
- regime e exposição;
- turnover e custos;
- `track_record_status` e `track_record_scope`.

O ciclo `PRE_ENSEMBLE` é mostrado no histórico completo, mas não entra em `simulation_results_valid_ensemble.csv` nem deve ser usado para medir o desempenho do ensemble 60/40.

## Conclusões

1. O histórico disponível com qualidade suficiente para score v3 começa em 2026-06-03; não há dados auditáveis anteriores no `scores_history.csv`.
2. A remoção do look-ahead reduziu materialmente o resultado face ao backtest anterior, tornando esta versão a referência correta.
3. O track-record fiável tem apenas cinco ciclos, ainda insuficientes para concluir que o ensemble tem edge persistente.
4. O turnover continua elevado, cerca de 84% por ciclo, e os custos retiraram aproximadamente 1,30 pontos percentuais ao retorno bruto no período fiável.
5. Todos os ciclos observados foram `BULL`; não há validação empírica de `BEAR` ou `STRESS`, e o VIX continua sem dados locais.

## Próximos passos

- Acumular mais ciclos sem alterar a definição do track-record.
- Adicionar dados VIX e validar regimes adversos.
- Executar walk-forward com janelas temporais maiores.
- Manter sempre os ficheiros `FULL_HISTORY` e `VALID_ENSEMBLE_60_40` separados.
