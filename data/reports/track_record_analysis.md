# ET-Spotter: track-record auditável

**Estado:** `VALID_ENSEMBLE_60_40`  
**Ensemble ativo desde:** 2026-06-09  
**Período público:** 2026-06-09 a 2026-09-24  
**Ciclos válidos:** 5  
**Ciclos legados excluídos:** 6  
**Capital inicial:** 10.000 EUR

## Resumo

| Métrica | Resultado |
|---|---:|
| Retorno bruto composto | +3,07% |
| Custos totais | 116,69 EUR |
| Retorno líquido | **+1,89%** |
| Valor final | 10.189,10 EUR |
| Max drawdown | -4,13% |
| Sharpe / Sortino | 0,17 / 0,30 |
| Exposição média | 100% investido |
| Turnover médio | 76,5% por ciclo |
| Correlação média das posições | 67,1% |

Todos os cinco ciclos públicos contêm obrigatoriamente `score_v3`, `xgb_proba`, `score_final`, peso final, regime, exposição, turnover e custo. Os seis ciclos anteriores foram movidos para `simulation_legacy_incomplete.csv` com estado `LEGACY_INCOMPLETE` e não entram no gráfico nem nas métricas públicas.

## Regimes

| Regime | Ciclos | Retorno líquido | Exposição |
|---|---:|---:|---:|
| BULL | 5 | +1,89% composto | 100% |
| BEAR | 0 | n/a | n/a |
| STRESS | 0 | n/a | n/a |

Não existem ciclos BEAR/STRESS neste intervalo. O VIX continua indisponível nos dados locais; portanto, a componente VIX do filtro ainda não foi validada.

## Benchmarks

No mesmo período e usando os preços disponíveis até 2026-09-22:

| Ativo | Retorno |
|---|---:|
| Estratégia limpa | **+1,89%** |
| Buy-and-hold VWCE.DE | **+6,90%** |
| Buy-and-hold CSPX.L | **+6,20%** |

A estratégia ficou atrás de VWCE.DE em 5,01 pontos percentuais e de CSPX.L em 4,31 pontos percentuais.

## Contributo por ETF

Contributos ponderados agregados antes da dedução separada dos custos:

| ETF | Contributo |
|---|---:|
| WTAI.L | -0,858% |
| VWRP.L | -0,597% |
| XAIX.L | -0,572% |
| HMWO.L | -0,476% |
| MVOL.L | -0,466% |
| MVEW.L | -0,358% |
| IWSZ.L | -0,322% |
| CUKX.L | -0,320% |
| VERX.L | -0,190% |
| INRG.L | -0,169% |
| VEUR.L | -0,149% |
| SMEA.L | -0,100% |
| IWQU.L | +0,063% |
| XMAW.L | +0,073% |
| IWDA.L | +0,080% |
| SWRD.L | +0,101% |
| VUKE.L | +0,153% |
| CNDX.L | +0,225% |
| XNAS.L | +0,247% |
| IUSA.L | +0,258% |
| VUSA.L | +0,282% |
| IUFS.L | +0,351% |
| CSPX.L | +0,384% |
| XDWD.DE | +0,656% |
| SUSW.L | +0,667% |
| VWRL.L | +0,813% |
| VWCE.DE | +0,835% |
| CYBR.L | +1,152% |
| HEAL.L | +1,725% |

## Conclusões

1. O track-record público está agora limpo e auditável a partir de 2026-06-09.
2. A estratégia teve retorno positivo, mas ficou claramente atrás dos dois benchmarks passivos.
3. A correlação média de 67,1% mostra diversificação limitada entre as oito posições.
4. O turnover médio de 76,5% continua alto e os custos consumiram cerca de 1,18 pontos percentuais do retorno bruto.
5. Ainda não há evidência sobre BEAR/STRESS porque nenhum desses regimes ocorreu e não há série VIX disponível.

## Próximas prioridades

- Adicionar uma série VIX e testar períodos BEAR/STRESS.
- Reduzir turnover com bandas de rebalanceamento e período mínimo de manutenção.
- Limitar correlação/concentração entre posições altamente relacionadas.
- Acumular mais ciclos válidos antes de avaliar o edge do ensemble 60/40.
- Comparar formalmente o ensemble com score v3 puro, XGBoost puro e equal-weight Top 8 usando walk-forward.
