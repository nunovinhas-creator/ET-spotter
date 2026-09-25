# Avaliação limpa: Política C/B × score cru/suavizado

> **Atualização 2026-09-25:** a configuração oficial passou a incluir restrições de construção da carteira (máx. 2 ETFs por categoria + exclusão do quartil superior de vol_21). MaxDD −11,87% → −4,11%. Ver `maxdd_constraints_analysis.md`.

**Dados:** `scores_history.csv` corrigido (sem fins de semana, datas de mercado reais; ver `data_quality_weekend_fix.md`). Retornos diários a partir dos preços finais em dias úteis.
**Período:** VALID_ENSEMBLE_60_40, de 2026-06-10 (1.º sinal com o ensemble ativo) a 2026-09-22 (último preço disponível).
**Comum a todas:** custos de 30 bps round-trip · threshold 12% · holding mínimo 3 ciclos · máx. 2 novas posições · máx. 7 posições · venda com score < 0,40 · ciclos de 21 dias de negociação.

## Resultados

| Combinação | Ciclos | Líquido | MaxDD diário (desde €10.000) | Turnover médio | Custos | vs VWCE.DE (+7,07%) |
|---|---:|---:|---:|---:|---:|---:|
| A · Pol. C (rebalance a cada 2 ciclos) + score cru | 2 | +3,99% | −11,87% | 64,4% | €38,82 | −3,08 p.p. |
| **B · Pol. C + score suavizado** | 2 | **+6,26%** | −11,87% | 60,3% | €36,32 | **−0,81 p.p.** |
| C · Pol. B (rebalance todos os ciclos) + score cru | 4 | +3,57% | −11,79% | 46,7% | €56,41 | −3,50 p.p. |
| D · Pol. B + score suavizado | 4 | +6,20% | −11,84% | 41,3% | €50,37 | −0,87 p.p. |

Bruto: A +4,39%, B +6,65%, C +4,16%, D +6,73%. O VWCE.DE teve MaxDD diário de −2,75% no mesmo período.

O turnover médio inclui a alocação inicial (100% no 1.º ciclo). Sem ela, o turnover por rebalanceamento é de 28,7% (A), 20,6% (B), 22,2% (C) e 21,7% (D).

## Leitura

- **MaxDD igual em todas:** as quatro começam com a mesma carteira (CNDX, ECAR, IWFM, IWVL, RBOT, WTAI, XAIX). O drawdown acontece no 1.º ciclo, de €10.799 a 22/06 até €9.517 a 29/07. Nenhuma combinação fica ≤ 8% nem ≤ 10%. A diferença de MaxDD entre elas (≤ 0,08 p.p.) é ruído.
- **A suavização é o que muda o resultado:** +2,3 p.p. na Política C e +2,6 p.p. na B. Mas na Política C a diferença vem de **uma única decisão**. No 2.º ciclo, o score cru de ECAR.L era 0,390, abaixo do limiar de venda de 0,40, e A trocou-o por IUFS.L. O score suavizado (0,585) manteve ECAR, que rendeu mais.
- **Rebalance a cada ciclo (B/D) não ajuda:** mais custos (€50–56 contra €36–39) sem melhor retorno nem menor drawdown.
- **Todas ficam abaixo do VWCE.DE**, com drawdown ~4× maior.

## Decisão

Critério: melhor equilíbrio entre retorno líquido e MaxDD, com preferência por MaxDD ≤ 10% se nenhuma ficar ≤ 8%. Nenhuma cumpre sequer os 10%, e o MaxDD é igual nas quatro. O desempate faz-se pelo retorno líquido e pelos custos: **B · Política C + score suavizado** (+6,26%, custos mais baixos). D fica praticamente empatada, mas com mais custos e o dobro dos rebalanceamentos.

**Configuração oficial atualizada:** `SCORE_SMOOTHING_CYCLES = 2` em `scripts/run_simulation.py`. A Política C mantém-se sem alterações. O dashboard mostra "ranking: score_final suavizado (média t, t-1)".

## Ressalvas

- **Amostra mínima:** 2 ciclos, e a vantagem da suavização vem de uma decisão. Isto não prova edge da suavização. Justifica apenas a escolha dentro das regras de desempate definidas.
- **Risco fora do limite:** o MaxDD de −11,87% está acima dos limites pretendidos, e a estratégia ficou abaixo do VWCE.DE. O problema de risco está na carteira inicial (temática e de beta alto), não na política de rotação. Qualquer melhoria de MaxDD terá de vir do sizing, dos caps de categoria ou dos critérios de seleção, não destas quatro variantes.
- **Âmbito:** a suavização aplica-se ao simulador (track-record). Os sinais diários, o dashboard de ranking e os alertas continuam a usar o `score_final` do dia.
- **Reavaliação:** voltar a avaliar quando houver ≥ 6 ciclos de 21 dias de negociação no período VALID_ENSEMBLE_60_40.
