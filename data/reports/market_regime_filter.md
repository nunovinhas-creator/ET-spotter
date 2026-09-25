# Filtro de regime de mercado — VIX + SMA200 do VWCE

**Data:** 2026-09-25 · **Ponto de partida:** configuração oficial congelada (Política C, score suavizado, máx. 2 ETFs/categoria, exclusão do quartil superior de vol_21, cap de 25% por categoria).
**Objetivo:** proteger a carteira em mercados em queda ou em pânico. O objetivo não é melhorar o retorno do período recente, que foi quase todo BULL.

## Regras

| Regime | Condição | Exposição máxima |
|---|---|---:|
| **BULL** | VWCE > SMA200 e VIX < 22 | 100% (sizing normal) |
| **NEUTRAL** | VWCE > SMA200 e 22 ≤ VIX < 28 | 60% (resto em cash) |
| **STRESS** | VIX ≥ 28 | 0% (100% cash) |
| **BEAR** | VWCE ≤ SMA200 | 0% (100% cash) |

- **Prioridade:** VWCE < SMA200 com VIX ≥ 28 ao mesmo tempo é STRESS. Tanto STRESS como BEAR levam a 100% cash.
- **Fallback sem VIX:** se o download falhar ou o último VIX tiver mais de 5 dias úteis, o VIX fica ausente. O regime passa a usar só a SMA200: acima → BULL, abaixo → BEAR. O dashboard mostra um aviso e a coluna `vix_available` dos CSVs fica `False`.
- **Sem SMA200** (menos de 200 sessões do VWCE): UNKNOWN → cash, como antes.
- **Quando é avaliado:** na data de construção de cada ciclo (fecho do VWCE e do VIX do dia do sinal). Os retornos começam na sessão seguinte, por isso não há look-ahead.
- **Aplicação da exposição:** multiplica a exposição que entra em `_capped_weights`. Os pesos continuam a ser vol-target × Kelly × score. O cap de 25% por categoria continua a ser absoluto, sobre o capital total.
- **Rebalanceamento forçado:** se a exposição do regime mudar face ao ciclo anterior, ou se a carteira estiver acima do teto, o rebalanceamento é feito mesmo que nenhum peso se desvie ≥ 12%. Sem esta regra, passar de 100% para 60% (ou para cash) com posições de 10–14% nunca ultrapassava o threshold, e o filtro não atuava.

## Implementação

| Ficheiro | O quê |
|---|---|
| `scripts/market_regime.py` | Fonte única das regras: `classify_regime`, `regime_exposure`, download do VIX com fallbacks, histórico diário de regimes, `market_regime.json` + `market_regime_history.csv` |
| `scripts/fetch_daily.py` | Chama `update_vix_file()` no fim; uma falha só gera um aviso |
| `scripts/run_simulation.py` | `REGIME_FILTER = "vix_sma200"` (oficial). `"legacy"` (binário antigo) e `"none"` (sempre 100%) servem só para comparação. Novas colunas: `vix_available`, `regime_filter`, `regime_forced_rebalance`, `average_invested_weight`, `neutral_cycles`, `vix_neutral_level`, `regime_exposure_rules`, `vix_available_cycles` |
| `scripts/portfolio_optimizer.py` | Usa `current_regime()`: NEUTRAL multiplica os pesos por 0,6 e acrescenta uma linha CASH; STRESS/BEAR → 100% CASH |
| `scripts/generate_dashboard.py` | Badge "CARTEIRA <regime> · <exposição>" no header. Painel "Regime de mercado" no separador Simulação: regime atual, VIX, VWCE vs SMA200, desde quando, barra de regimes dos últimos 12 meses, gráfico VWCE/SMA200/VIX com limiares 22/28 e tabela de períodos. Regime + VIX por ciclo na tabela de alocações. Passa também a regenerar o CSV VALID_ENSEMBLE a cada execução |

**Fontes do VIX, por ordem:** yfinance `^VIX` → CSV oficial da CBOE (`cdn.cboe.com`) → espelho desse CSV no GitHub (`datasets/finance-vix`). A série é gravada em `data/daily/VIX.csv` (janela de 3 anos) e é fundida com o histórico existente, por isso um download parcial nunca a encurta. Nesta sessão, o Yahoo, a CBOE e o FRED estavam bloqueados pela rede do contentor. O VIX veio do espelho do GitHub, com último valor a 2026-09-22 (14,21). Nos GitHub Actions o yfinance deve funcionar.

## Validação — VALID_ENSEMBLE_60_40 (2026-06-10 → 2026-09-23, 2 ciclos de 42 sessões)

| Variante | Líquido | MaxDD diário | Exposição média | Turnover médio | Custos |
|---|---:|---:|---:|---:|---:|
| **Com filtro VIX + SMA200 (novo oficial)** | **+4,79%** | **−2,46%** | 80% | 49,5% | €30,00 |
| Sem filtro de regime (sempre 100%) | +6,69% | −4,11% | 100% | 50,0% | €30,00 |
| Filtro binário anterior (SMA200 + VIX ≥ 28) | +6,69% | −4,11% | 100% | 50,0% | €30,00 |
| VWCE.DE (benchmark) | +6,78% | −2,75% | — | — | — |

"Sem filtro" e "binário anterior" reproduzem exatamente a referência congelada (+6,69% / −4,11% / 50% / €30). Neste período nunca houve BEAR nem STRESS numa data de construção.

### Por ciclo

| Ciclo | Data do sinal | VIX | Regime | Exposição | Bruto com filtro | Bruto sem filtro | VWCE |
|---|---|---:|---|---:|---:|---:|---:|
| 1 | 2026-06-10 | 22,22 | NEUTRAL | 60% | +2,75% | +4,61% | +4,56% |
| 2 | 2026-08-19 | 14,89 | BULL | 100% | +2,29% (rebalance forçado, turnover 39%) | +2,29% | +2,13% |

**Leitura:**
- O 1.º ciclo começou num dia NEUTRAL isolado: VIX 22,22, só 0,22 acima do limiar. A 09/06 e a 11/06 o regime já era BULL. Esse dia custou ~1,9 p.p. de retorno e cortou o MaxDD em 1,65 p.p. Com 2 ciclos, a diferença diz mais sobre esse dia do que sobre o filtro. Não serve para concluir se o filtro "funciona".
- A exposição média de 80% explica quase toda a diferença de retorno. Os custos totais ficam iguais (€30): o 1.º ciclo investe só 60% (turnover 60%) e o 2.º faz um rebalance forçado de 39% para voltar a 100%.

### Teste complementar (proxy VWCE, 2025-07-10 → 2026-09-23)

Não há scores para trás de junho de 2026. Para ver o filtro num período com picos de VIX (novembro de 2025, março de 2026 com VIX 31), apliquei as regras a uma carteira 100% VWCE, com 30 bps por unidade de turnover:

| Variante | Retorno | MaxDD | Exposição média |
|---|---:|---:|---:|
| VWCE buy & hold | +29,70% | −6,55% | 100% |
| Filtro avaliado todos os dias | +27,68% | −5,13% | 95,4% (15 mudanças de exposição) |
| Filtro avaliado a cada 21 ou 42 sessões | +26,92% | −4,89% | 94,7% |
| Binário anterior, diário | +29,08% | −6,16% | — |

Em 12 meses: 88% dos dias BULL, 11% NEUTRAL, 1% STRESS, 0% BEAR. O VWCE está acima da SMA200 desde julho de 2025, por isso **a regra BEAR ainda não foi posta à prova** com dados reais.

## Limitações e próximos passos (não implementados; a configuração continua congelada)

1. **Cadência:** com a Política C o regime só é lido de 42 em 42 sessões. Um crash a meio do ciclo só é apanhado na construção seguinte. Uma verificação diária ou semanal do regime, que só reduza a exposição e nunca abra posições, daria mais proteção. Muda o simulador e precisa de decisão explícita.
2. **Sensibilidade ao limiar:** um único fecho do VIX perto de 22 decide 40% da exposição de um ciclo inteiro. Pode valer a pena testar histerese (ex.: entrar em NEUTRAL com VIX ≥ 22 e voltar a BULL só com VIX < 20) ou usar a média de 5 dias do VIX.
3. **Amostra:** a configuração está congelada em modo acumulação. Reavaliar só com ≥ 6–8 ciclos VALID_ENSEMBLE_60_40 completos (6 por volta de 2027-05-28, 8 por volta de 2027-09-23). Os pontos 1 e 2 ficam em espera até lá.
