# Suavização do score_final: comparação sob a Política C

> **Atualização:** com dados corrigidos, a suavização passou a ser a configuração oficial (`SCORE_SMOOTHING_CYCLES = 2`). Ver `policy_evaluation_clean.md`.

> **Aviso (dados corrigidos):** os números deste documento usam o histórico anterior à correção de fins de semana e datas desfasadas. Ver `data_quality_weekend_fix.md`. No período VALID_ENSEMBLE_60_40, a Política C passa a +3,99% líquido e MaxDD diário −11,87%.

**Período:** `VALID_ENSEMBLE_60_40`, de 2026-06-09 a 2026-09-24 (3 ciclos de ~42 dias, 2 transições).
**Política C em ambas as variantes:** threshold 12% · holding mínimo 3 ciclos · máx. 2 novas posições · máx. 7 posições · venda só com score < 0,40 · rebalance a cada 2 ciclos · custos 30 bps round-trip.

## Variantes

- **V1 (atual):** ranking, entradas, saídas e sizing usam o `score_final` cru do ciclo.
- **V2 (suavizada):** `score_suave = (score_final(t) + score_final(t-1)) / 2`, em que t-1 é o sinal do ciclo de decisão anterior; sem t-1 usa-se o score atual. Ranking, entradas, saídas (limiar 0,40) e sizing passam a usar o `score_suave`.

Implementado em `scripts/run_simulation.py` com o parâmetro `score_smoothing_cycles` (1 = cru, 2 = suavizado; constante `SCORE_SMOOTHING_CYCLES`).

## Resultados

| Métrica | V1 cru | V2 suavizado |
|---|---:|---:|
| Retorno bruto | +5,98% | +5,98% |
| Retorno líquido | +5,66% | +5,66% |
| MaxDD (diário, desde €10.000) | −7,72% | −7,72% |
| Turnover médio | 33,3% | 33,3% |
| Custos | €30,00 | €30,00 |
| Correlação média das posições | 70,0% | 70,0% |
| Top 7 repetido no ciclo seguinte | 14,3% | 35,7% |
| Permanência média no top 7 | 1,11 ciclos | 1,31 ciclos |

Correlação média = média, por ciclo, da correlação par-a-par dos retornos diários das posições ativas. Persistência calculada sobre o top 7 do ranking usado para decidir (cru em V1, suavizado em V2).

Os retornos diferem dos +6,93% do relatório anterior porque o último ciclo (em curso até 2026-09-24) foi reavaliado com os dados atualizados; a comparação entre variantes usa exatamente os mesmos dados.

## Leitura

A suavização **mais do que duplica a repetição do top 7** (14,3% → 35,7%), o que confirma que parte da rotação do ranking é ruído de um só ciclo. **Mas as carteiras são idênticas nos três ciclos** (CNDX, CSPX, CYBR, VWRL, VWRP, XMAW, XNAS). A Política C já filtra esse ruído: com a venda condicionada a score < 0,40, nenhuma posição saiu, não abriram vagas para novas entradas e os desvios de peso (10,4% e 10,5%) ficaram abaixo do threshold de 12%. O ranking suavizado nunca chegou a ser posto em prática.

## Decisão

Ambas as variantes cumprem MaxDD ≤ 8% e turnover ≤ 40%, com retorno líquido idêntico. Como não há diferença económica e a amostra tem apenas 2 transições, **mantém-se a V1 (score_final cru) em produção**: `SCORE_SMOOTHING_CYCLES = 1`. O parâmetro fica disponível para repetir o teste quando houver mais ciclos, sobretudo ciclos com saídas forçadas ou vagas livres, onde a suavização pode de facto alterar decisões.

## Nota lateral

O MaxDD desta tabela já usa o cálculo corrigido (equity curve diária desde os €10.000 iniciais; ver `max_drawdown_fix.md`). Antes aparecia 0,00%. Ambas as variantes continuam a cumprir MaxDD ≤ 8%, e a decisão mantém-se.
