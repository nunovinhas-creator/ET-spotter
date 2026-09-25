# Restrições de construção da carteira para reduzir o MaxDD

**Ponto de partida:** configuração oficial de 2026-09-24, Política C + `SCORE_SMOOTHING_CYCLES = 2` (ver `policy_evaluation_clean.md`). As regras de rotação não mudam.
**Período:** VALID_ENSEMBLE_60_40, de 2026-06-10 (1.º sinal) a 2026-09-23. São 2 ciclos de 42 dias de negociação.
**Comum a todas:** custos de 30 bps round-trip · threshold 12% · holding mínimo 3 ciclos · máx. 2 novas posições · máx. 7 posições · venda com score < 0,40 · ranking suavizado (média t, t-1).
**Benchmark:** VWCE.DE +6,78% no mesmo período (MaxDD diário −2,75%).

## Problema

O MaxDD de −11,87% vem da 1.ª carteira (CNDX, ECAR, IWFM, IWVL, RBOT, WTAI, XAIX): 4 temáticos, 2 factor e o Nasdaq-100, com vol ex-ante de 23,9%. A queda vai de €10.799 (22/06) a €9.517 (29/07).

## Descobertas no simulador (antes de testar)

1. **O cap de 25% por categoria não é aplicado à soma da categoria.** `_capped_weights` só compara cada ETF isoladamente com o cap. Na 1.ª carteira, os 4 temáticos somam 42,7% e os 2 factor 37,4%. Esta avaliação **não corrige** o bug, para que a comparação com a baseline se mantenha limpa. A correção fica como ponto em aberto (ver abaixo).
2. **`TARGET_VOLATILITY` (12%) e o Kelly fracionário só servem de escala relativa.** Os pesos são sempre normalizados para 100% da exposição, por isso a constante de vol-target anula-se. O Kelly vem de `0,5 + k·(2·hit_rate − 1)`. Sem histórico (hit_rate = 0,5) dá 0,5 para todos os ETFs nos primeiros ciclos. Por isso:
   - **3a (vol-target 10%)** foi implementado como vol-target **real**: a vol ex-ante da carteira é estimada com a covariância dos últimos 63 dias úteis, e a exposição é reduzida para `min(1, 10% / vol)`. O resto fica em cash, a 0%.
   - **3b (Kelly 0,20)** foi testado tal como pedido, mas **não tem efeito prático**. As diferenças (≤ 0,03 p.p.) vêm só do 2.º ciclo.
3. **Turnover com cash:** o cash passa a contar como posição. Passar de 100% cash para 42% investido conta 42% de turnover, não 100%. Com exposição a 100% o resultado é igual ao anterior.

## Definições

- **1a:** máximo de 2 ETFs por categoria de `config/etfs.json`. Aplica-se ao ranking de entrada, que vai mais fundo na lista se preciso, e às novas entradas face às posições retidas.
- **1b:** peso máximo no grupo de alto beta: categoria `thematic` (tecnologia, robótica, IA, energia limpa, VE, biotech, ciber) + CNDX.L, XNAS.L e IUIT.L. O excesso passa para os restantes ETFs.
- **2a:** excluir da **entrada** os ETFs com `vol_21` acima do percentil 75 do universo na data do ranking. As posições já detidas não são forçadas a sair.
- **2b:** peso × 0,5 para esses ETFs.
- **3a / 3b:** vol-target real de 10% / Kelly 0,20 nos primeiros 2 ciclos. Neste período só há 2 ciclos, portanto aplica-se ao período inteiro.

## Resultados (VALID_ENSEMBLE_60_40)

| Variante | Líquido | MaxDD diário (desde €10.000) | Ret/DD | Turnover médio | Custos | vs VWCE.DE | Vol ex-ante 1.º ciclo |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline (C + suavizado) | +6,09% | −11,87% | 0,51 | 60,3% | €36,32 | −0,70 p.p. | 23,9% |
| **Só 1** · 1a máx. 2/categoria | +6,48% | −7,34% | 0,88 | 50,0% | €30,00 | −0,30 p.p. | 16,9% |
| Só 1 · 1b alto beta ≤ 35% | +5,09% | −10,75% | 0,47 | 67,8% | €40,98 | −1,69 p.p. | 22,4% |
| Só 1 · 1b alto beta ≤ 40% | +5,20% | −10,95% | 0,48 | 66,8% | €40,34 | −1,58 p.p. | 22,7% |
| **Só 2** · 2a excluir vol top 25% | +6,55% | −3,36% | 1,95 | 50,0% | €30,00 | −0,23 p.p. | 12,8% |
| Só 2 · 2b vol top 25% a 50% | +5,81% | −11,71% | 0,50 | 73,3% | €44,28 | −0,97 p.p. | 23,6% |
| **Só 3** · 3a vol-target 10% | +2,71% | −5,05% | 0,54 | 20,9% | €12,53 | −4,07 p.p. | 23,9% (42% investido) |
| Só 3 · 3b Kelly 0,20 | +6,06% | −11,87% | 0,51 | 60,4% | €36,36 | −0,72 p.p. | 23,9% |
| **1 + 2** · 1a + 2a ✅ | **+6,81%** | **−4,11%** | 1,66 | 50,0% | €30,00 | **+0,03 p.p.** | 14,2% |
| 1 + 2 · 1a + 2b | +6,11% | −7,25% | 0,84 | 61,3% | €36,98 | −0,67 p.p. | 16,9% |
| 1 + 2 · 1b35 + 2a | +6,55% | −3,36% | 1,95 | 50,0% | €30,00 | −0,23 p.p. | 12,8% |
| 1 + 2 · 1b35 + 2b | +5,34% | −10,61% | 0,50 | 74,1% | €44,84 | −1,44 p.p. | 22,2% |
| 1 + 2 · 1a + 1b35 + 2a | +6,81% | −4,11% | 1,66 | 50,0% | €30,00 | +0,03 p.p. | 14,2% |
| **1 + 2 + 3** · 1a + 2a + 3a | +4,81% | −2,88% | 1,67 | 35,1% | €21,07 | −1,97 p.p. | 14,2% (70% investido) |
| 1 + 2 + 3 · 1a + 2b + 3a | +4,00% | −4,33% | 0,92 | 29,7% | €17,80 | −2,79 p.p. | 16,9% (59% investido) |
| 1 + 2 + 3 · 1b35 + 2a + 3a | +5,15% | −2,63% | 1,96 | 39,2% | €23,50 | −1,63 p.p. | 12,8% (78% investido) |
| 1 + 2 + 3 · 1a + 2a + 3b | +6,81% | −4,11% | 1,66 | 50,0% | €30,00 | +0,03 p.p. | 14,2% |

O turnover médio inclui a alocação inicial. Nas variantes com 50%, o 2.º ciclo não teve rotação: nenhum desvio ≥ 12%.

### Composição da 1.ª carteira (10/06/2026)

| Variante | 1.ª carteira (peso) |
|---|---|
| Baseline | CNDX 20%, ECAR 8%, IWFM 19%, IWVL 18%, RBOT 13%, WTAI 10%, XAIX 12% |
| 1a | CNDX 14%, IUSA 24%, IWFM 13%, IWVL 13%, WTAI 7%, XAIX 8%, XMAW 22% |
| 1b ≤ 35% | CNDX 11%, ECAR 5%, IWFM 33%, IWVL 32%, RBOT 7%, WTAI 5%, XAIX 7% |
| 1b ≤ 40% | CNDX 13%, ECAR 5%, IWFM 31%, IWVL 29%, RBOT 8%, WTAI 6%, XAIX 8% |
| 2a (= 1b35 + 2a) | CNDX 9%, CSPX 14%, HMJP 13%, IUSA 16%, VUSA 16%, XDWD 17%, XMAW 15% |
| 2b | CNDX 25%, ECAR 8%, IWFM 18%, IWVL 17%, RBOT 12%, WTAI 9%, XAIX 11% |
| 3a | CNDX 8%, ECAR 3%, IWFM 8%, IWVL 8%, RBOT 5%, WTAI 4%, XAIX 5% (58% cash) |
| 3b | igual à baseline |
| **1a + 2a** (= 1a + 1b35 + 2a) | **CNDX 10%, HMJP 13%, IJPA 12%, IUSA 17%, SUSW 14%, XDWD 18%, XMAW 16%** |
| 1a + 2b | IUSA 25%, IWFM 16%, IWVL 16%, WTAI 8%, XAIX 10%, XMAW 25% |
| 1a + 2a + 3a | CNDX 7%, HMJP 9%, IJPA 8%, IUSA 12%, SUSW 10%, XDWD 13%, XMAW 11% (30% cash) |
| 1a + 2b + 3a | IUSA 15%, IWFM 10%, IWVL 9%, WTAI 5%, XAIX 6%, XMAW 15% (41% cash) |
| 1b35 + 2a + 3a | CNDX 7%, CSPX 11%, HMJP 10%, IUSA 13%, VUSA 12%, XDWD 13%, XMAW 12% (22% cash) |

## Leitura

- **O filtro de volatilidade (2a) é o que resolve o MaxDD.** Tira da entrada ECAR, RBOT, WTAI e XAIX, que eram os ETFs responsáveis pelas quedas diárias de 3–6%. Sozinho leva o MaxDD de −11,87% para −3,36%, sem perder retorno.
- **Reduzir o peso (2b) ou limitar o grupo (1b) não chega.** Os mesmos ETFs continuam na carteira. No caso de 1b, o excesso vai para IWFM/IWVL, que também caíram no mesmo período.
- **1a sozinho ajuda** (−7,34%), mas ainda deixa 2 temáticos.
- **O vol-target real (3a) funciona, mas só por reduzir a exposição.** O rácio retorno/MaxDD quase não melhora (0,54 contra 0,51 na baseline; 1,96 contra 1,95 quando se junta a 1b35 + 2a). Custa 1–2 p.p. de retorno porque o cash rende 0%.
- **1a e 2a juntos:** 2a sozinho entra com 3 clones do S&P 500 (CSPX, IUSA, VUSA) mais CNDX, ou seja, 4 ETFs da categoria EUA. 1a reparte a carteira por EUA, Global, Japão e ESG. Com a combinação, o retorno sobe para +6,81% e o MaxDD fica em −4,11%.
- O cap de alto beta a 35% não faz nada em cima de 2a: o único ETF de alto beta que sobra é o CNDX, com 9–10%.

### Robustez

**Histórico completo (FULL_HISTORY, desde 2026-06-02, inclui o ciclo PRE_ENSEMBLE):**

| Variante | Líquido | MaxDD diário |
|---|---:|---:|
| Baseline | −3,34% | −15,23% |
| 1a | −0,81% | −11,91% |
| 2a | +1,87% | −5,04% |
| **1a + 2a** | **+2,00%** | **−4,83%** |
| 1b35 + 2a + 3a | +1,43% | −3,71% |
| 1a + 2a + 3a | +1,39% | −3,19% |

VWCE.DE: +3,13%.

**Sensibilidade à data de início** (VALID, início deslocado entre 12/06 e 08/07): quando a carteira inicial não é temática, as restrições quase não mudam nada. Todas as variantes ficam entre −2,0% e −3,7% de MaxDD e com retornos parecidos (±0,6 p.p.). Ou seja, as restrições **atuam quando o ranking fica concentrado em alto beta e são quase neutras no resto do tempo**, que é o comportamento pretendido.

## Decisão

Critério: MaxDD tão baixo quanto possível (alvo ≤ 9%) sem destruir o retorno. Todas as combinações 1 + 2 com 2a e todas as 1 + 2 + 3 ficam ≤ 9%.

**Escolha: 1 + 2 = máx. 2 ETFs por categoria + excluir da entrada o quartil superior de vol_21.**
- MaxDD −11,87% → **−4,11%**, bem dentro do alvo de 9%.
- Retorno líquido +6,09% → **+6,81%**, o melhor de todas as variantes. Única a bater o VWCE.DE (+0,03 p.p.).
- Custos €36,32 → €30,00. Turnover médio 60,3% → 50,0%.
- No histórico completo melhora retorno e drawdown (−15,23% → −4,83%).

**Alternativas não escolhidas:**
- **1b35 + 2a + 3a** tem o MaxDD mais baixo (−2,63%), mas só porque fica com 22% em cash. Perde 1,66 p.p. de retorno face à escolhida, com o mesmo rácio retorno/MaxDD que 2a sozinho. Os ~1,5 p.p. de MaxDD a mais não justificam essa perda com 2 ciclos de amostra.
- **2a sozinho** tem o melhor rácio retorno/MaxDD (1,95 contra 1,66). Foi preterido porque concentra 4 ETFs na mesma categoria, 3 deles clones do S&P 500. A diferença de 0,75 p.p. de MaxDD está dentro do ruído de 2 ciclos. 1a é uma regra estrutural de diversificação que deve proteger melhor fora da amostra.

**Configuração oficial** (`scripts/run_simulation.py`): `MAX_ETFS_PER_CATEGORY = 2`, `VOL_FILTER_MODE = "exclude"` (percentil 75 de vol_21). `HIGH_BETA_CAP`, `EARLY_TARGET_VOLATILITY` e `EARLY_FRACTIONAL_KELLY` ficam implementados mas desligados (`None`). A Política C e a suavização não mudam. O dashboard mostra a linha "Construção da carteira".

## Ressalvas

- **Amostra mínima:** 2 ciclos. O ganho vem de evitar uma carteira inicial concentrada em temáticos num período em que esses temáticos caíram. Não prova edge, mas o efeito vai na direção esperada e repete-se no histórico completo.
- **Custo de oportunidade:** em fases de liderança temática forte, o filtro de volatilidade vai deixar ganhos de fora. É uma troca consciente: menos cauda por menos upside.
- **Âmbito:** as restrições aplicam-se ao simulador (track-record). Os sinais diários, o ranking do dashboard e os alertas não mudam.
- **Em aberto:** corrigir `_capped_weights` para aplicar o cap de 25% à soma de cada categoria, como o dashboard descreve. Com 1a ativo o impacto é pequeno (na 1.ª carteira escolhida, EUA soma 27%), mas o cap devia fazer o que diz.
- **Reavaliação:** quando houver ≥ 6 ciclos no período VALID_ENSEMBLE_60_40.
