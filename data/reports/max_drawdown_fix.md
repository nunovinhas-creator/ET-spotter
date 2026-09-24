# Correção do cálculo do Max Drawdown do simulador

## Problema

`run_simulation.py` calculava o MaxDD só com os valores de **fim de ciclo** e sem o capital inicial. O pico de referência começava no fim do 1.º ciclo. Por isso uma perda de −2,09% no 1.º ciclo aparecia como MaxDD 0,00%, e as quedas dentro de cada ciclo (~42 dias) ficavam invisíveis.

## Correção

- A equity curve começa em **€10.000 no dia 0**, a data do 1.º sinal, antes de qualquer ciclo.
- Os custos de cada ciclo são debitados no início do ciclo. Depois a equity compõe diariamente com os retornos ponderados da carteira ativa e termina exatamente no `portfolio_value` de fim de ciclo.
- `max_drawdown` passa a ser o pior drawdown dessa série **diária** completa.
- Novos campos: `max_drawdown_cycle_end` (mesma métrica só com fins de ciclo, incluindo os €10.000), `max_drawdown_method`, e por ciclo `drawdown` e `max_drawdown_to_date`.
- A equity curve diária é gravada em `simulation_results_equity.csv` e `simulation_results_valid_ensemble_equity.csv`.
- No dashboard, o gráfico começa no ponto €10.000 (estratégia e benchmark) e o cartão passa a dizer "Max Drawdown diário".

As regras de trading (Política C, custos de 30 bps, sizing, regime) não foram alteradas. Retornos, turnover e custos ficam iguais.

## Impacto (VALID_ENSEMBLE_60_40, 2026-06-09 a 2026-09-24)

| Métrica | Antes | Depois |
|---|---:|---:|
| MaxDD reportado | 0,00% | **−7,72%** |
| MaxDD só com fins de ciclo (desde €10.000) | — | −2,09% |
| Retorno líquido | +5,66% | +5,66% |

O MaxDD real vai do pico de €10.514 (2026-07-06) ao vale de €9.702 (2026-07-23), dentro do 1.º ciclo.

Histórico completo (`FULL_HISTORY`, com o ciclo PRE_ENSEMBLE): **−26,92%** (−25,05% só com fins de ciclo).

## Consequência para decisões anteriores

Com a métrica corrigida, a Política C tem MaxDD de −7,72% e continua a cumprir o limite de 8%, mas **com pouca margem**. A Política B dá −7,86%. A escolha de C mantém-se: melhor retorno líquido (+5,66% contra +5,55%) e ambas dentro do limite. A comparação da suavização também não muda: as carteiras são idênticas, portanto o MaxDD é igual nas duas variantes.

## Nota sobre os dados

`scores_history.csv` inclui fins de semana, com retornos diários repetidos entre sexta e domingo (ex.: 17–19/07, −1,31% em cada dia). Isto afeta a forma da curva diária e o retorno composto. É um problema anterior a esta correção e deve ser investigado à parte.
