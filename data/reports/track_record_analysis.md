# ET-Spotter: otimização de turnover

**Universo:** apenas ciclos `VALID_ENSEMBLE_60_40`  
**Período:** 2026-06-09 a 2026-09-24  
**Custos:** 30 bps round-trip  
**Posições:** máximo 8  
**Capital inicial:** 10.000 EUR

## Comparação cumulativa

| Variante | Retorno bruto | Retorno líquido | MaxDD | Turnover médio | Custos | Correlação média |
|---|---:|---:|---:|---:|---:|---:|
| Baseline: 5%, sem holding, sem limite | +3,07% | +1,89% | -4,13% | 76,5% | €116,69 | 67,1% |
| Threshold 8% | +3,07% | +1,89% | -4,13% | 76,5% | €116,69 | 67,1% |
| Threshold 8% + holding 2 ciclos | +3,07% | +1,89% | -4,13% | 76,5% | €116,69 | 67,1% |
| **Threshold 8% + holding 2 + máximo 3 novas** | **+3,78%** | **+2,47%** | **-4,50%** | **84,2%** | **€128,60** | **63,9%** |

Todas as variantes respeitam `MaxDD <= 8%`. A combinação vencedora é a política final aplicada no código:

- só rebalancear quando o desvio for `>= 8%`;
- não vender uma posição antes de dois ciclos completos, salvo score final abaixo de 0,35;
- permitir no máximo três novas posições por ciclo de rotação (a alocação inicial de oito posições é bootstrap e fica registada separadamente);
- manter no máximo oito posições;
- manter custos de 30 bps round-trip.

## Leitura dos resultados

O threshold de 8% e o holding mínimo não alteraram este período curto: os desvios de peso foram suficientemente grandes para continuar a rebalancear. O limite de três novas posições alterou a trajetória e produziu o melhor retorno líquido, mas aumentou o turnover neste sample, porque as posições retidas foram recalculadas com pesos diferentes e houve mais rotação efetiva nas transições.

A melhoria líquida face ao baseline foi de **+0,58 pontos percentuais**, com aumento do MaxDD de 0,37 pontos percentuais, ainda muito abaixo do limite de 8%. A correlação média caiu de 67,1% para 63,9%, uma melhoria modesta de diversificação.

## Estado final

O track-record público continua limitado aos cinco ciclos válidos desde 2026-06-09. Os seis ciclos incompletos anteriores permanecem separados como `LEGACY_INCOMPLETE` e não contaminam as métricas. Todos os ciclos finais persistem `score_v3`, `xgb_proba`, `score_final`, pesos, regime, exposição, turnover e custos.

O período contém apenas regimes `BULL`; não há ainda evidência empírica sobre `BEAR` ou `STRESS`, e o VIX continua sem dados locais.

## Recomendações

1. Acumular mais ciclos antes de concluir que o limite de três entradas é estruturalmente superior.
2. Reavaliar a regra com vários períodos de mercado e walk-forward.
3. Adicionar VIX e testar explicitamente os regimes `BEAR` e `STRESS`.
4. Considerar um limite explícito de turnover mensal, porque a variante vencedora aumentou a rotação apesar de reduzir o número de entradas novas.
