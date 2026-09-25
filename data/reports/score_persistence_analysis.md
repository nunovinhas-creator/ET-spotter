# Persistência do score_final

> **Aviso (dados corrigidos):** os números deste documento usam o histórico anterior à correção de fins de semana e datas desfasadas. Ver `data_quality_weekend_fix.md`. No período VALID_ENSEMBLE_60_40, a Política C passa a +3,99% líquido e MaxDD diário −11,87%.

## VALID_ENSEMBLE_60_40

Período analisado: 2026-06-09 a 2026-09-24. A Política C produz 3 ciclos e apenas 2 transições entre ciclos, pelo que os números são diagnósticos e não estatisticamente robustos.

| Métrica | Resultado |
|---|---:|
| Rank autocorrelation média | 0,515 |
| Correlação ponto-a-ponto do score_final | 0,522 |
| Top 7 repetido no ciclo seguinte | 14,3% |
| Top 8 repetido no ciclo seguinte | 12,5% |
| Permanência média no top 7 | 1,11 ciclos |
| Mediana da permanência no top 7 | 1 ciclo |

## FULL_HISTORY

O output da Política C completo tem 3 ciclos, dos quais um `PRE_ENSEMBLE`, e também apenas 2 transições:

| Métrica | Resultado |
|---|---:|
| Rank autocorrelation média | 0,389 |
| Correlação ponto-a-ponto do score_final | 0,368 |
| Top 7 repetido no ciclo seguinte | 0,0% |
| Top 8 repetido no ciclo seguinte | 6,25% |
| Permanência média no top 7 | 1 ciclo |

## Interpretação

O score muda bastante entre snapshots. A baixa repetição do top 7 explica por que uma estratégia que reage diretamente ao ranking pode gerar rotação elevada. A Política C já reduz a frequência de execução para aproximadamente 42 dias, portanto tornar a regra de saída ainda mais restritiva teria risco de manter posições cujo sinal já perdeu qualidade.

## Recomendação

**Manter a Política C em produção por agora.** A amostra tem apenas duas transições observáveis, logo não justifica trocar a política com base nestes números.

O próximo experimento recomendado é uma suavização de 2 ciclos do `score_final` para ranking/entrada, medindo novamente persistência, turnover e retorno num período mais longo. Não recomendo tornar a saída mais restritiva antes desse teste: a persistência baixa sugere ruído no ranking, não necessariamente que as posições atuais devam ser mantidas por mais tempo.
