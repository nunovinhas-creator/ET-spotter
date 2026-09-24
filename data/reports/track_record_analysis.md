# ET-Spotter: políticas de baixa frequência

**Universo de comparação:** apenas `VALID_ENSEMBLE_60_40`, desde 2026-06-09.  
**Custos:** 30 bps round-trip.  
**Look-ahead:** retornos começam no dia seguinte ao sinal.  
**Limite de seleção:** máximo 8 posições em A; 7 em B/C.

## Comparação A/B/C

| Política | Regras principais | Bruto | Líquido | MaxDD | Turnover médio | Custos | Correlação média | Posições médias |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | 8% · 2 ciclos · 3 novas · 8 posições | +2,66% | +1,82% | -5,13% | 54,4% | €82,78 | 64,9% | 7,2 |
| B | 12% · 3 ciclos · 2 novas · 7 posições · venda <0,40 | +7,14% | +6,82% | -5,97% | 20,0% | €30,00 | 75,6% | 7,0 |
| **C vencedora** | **B + rebalance a cada 2 ciclos (~42 dias)** | **+7,25%** | **+6,93%** | **0,00%** | **33,3%** | **€30,00** | **73,2%** | **7,0** |

Todas as políticas respeitaram `MaxDD <= 8%`. B e C respeitaram também turnover <=45%; C teve o melhor retorno líquido e foi escolhida.

## Política aplicada

A Política C está agora nos defaults de produção:

- threshold de rebalanceamento: `12%`;
- holding mínimo: `3` ciclos;
- máximo de `2` novas posições por ciclo de rebalanceamento;
- máximo de `7` posições;
- venda apenas quando `score_final < 0,40` ou quando necessário para respeitar o limite de posições;
- rebalanceamento a cada `2` ciclos, aproximadamente 42 dias;
- custos de `30 bps` round-trip.

A alocação inicial é bootstrap e pode abrir as posições máximas; o limite de novas posições aplica-se às rotações seguintes.

## Output oficial C

O ficheiro `simulation_results_valid_ensemble.csv` contém 3 ciclos de 2026-06-09 a 2026-09-24:

- retorno bruto: +7,25%;
- retorno líquido: **+6,93%**;
- MaxDD: 0,00%;
- turnover médio: 33,3%;
- custos: €30,00;
- correlação média: 73,2%;
- posições médias: 7,0.

No mesmo período, os benchmarks tiveram:

- VWCE.DE: +6,90%;
- CSPX.L: +6,20%.

A vantagem sobre VWCE.DE é de apenas cerca de 0,03 pontos percentuais e baseia-se em três ciclos; não é evidência suficiente de edge persistente.

## Histórico completo

`simulation_results.csv` continua a separar o período completo. Com a frequência de 42 dias, contém 3 ciclos desde 2026-06-03: um `PRE_ENSEMBLE` e dois `VALID_ENSEMBLE_60_40`. O retorno agregado é negativo porque inclui o ciclo pré-ensemble; este valor não deve ser usado para avaliar a Política C.

Todos os ciclos persistem score v3, `xgb_proba`, score final, pesos, regime, exposição, turnover, custos, política e escopo. O ciclo `PRE_ENSEMBLE` tem `xgb_proba = null` e aparece apenas no histórico completo.

## Conclusão

A Política C é a vencedora no sample disponível porque reduz a frequência de rebalanceamento e mantém turnover abaixo de 45%, mas a amostra efetiva tem apenas três ciclos. É necessário acumular dados antes de concluir que a melhoria face a B ou VWCE.DE é estrutural.
