# Qualidade de dados: fins de semana e datas desfasadas em scores_history.csv

## Sintoma

Em `data/scores_history.csv`, sábado e domingo repetiam o `ret_1d` de sexta. Exemplo: CSPX.L com −1,28% em 17, 18 e 19/07, contado três vezes no retorno composto e no MaxDD diário. O benchmark (VWCE.DE) tinha o mesmo problema: `_load_benchmark_data` reindexava os preços para as datas do histórico e fazia forward-fill do **retorno**.

## Causa

Os ficheiros `data/daily/*.csv` estavam corretos: só têm dias úteis. O erro estava na construção do histórico:

1. `compute_score.persist_scores()` gravava cada snapshot com a **data do relógio** (`pd.Timestamp.now()`), não com a data da barra de preços.
2. `daily.yml` corre **todos os dias** (`0 22 * * *`). Ao sábado e domingo não há barra nova, logo a barra de sexta era gravada com data de sábado e depois de domingo.
3. O `hourly.yml` não faz fetch diário. Entre as 13h e as 22h UTC de cada dia útil, gravava a barra do **dia anterior** com a data de hoje. Quando o fetch diário das 22h falhava (ex.: 23/09), a linha desfasada ficava definitiva. Segundas-feiras com a barra de sexta eram frequentes (590 linhas).

A auditoria encontrou 2 527 linhas de fim de semana. Além disso, 75 dos 117 snapshots tinham a data errada.

## Correção

**Na origem (`scripts/compute_score.py`):**
- A data gravada é a **data de mercado**: a última barra diária da maioria dos ETFs do snapshot.
- Corridas ao fim de semana e antes do fetch reescrevem a linha do dia de mercado a que pertencem (de-dup `keep="last"`) em vez de criarem um dia novo.
- ETFs com outra última barra (feriado no seu mercado, fetch parcial) ficam com preço mantido (forward-fill) e o retorno calculado pelos preços: 0% sem negociação.

**Reparação do histórico (`scripts/repair_scores_history.py`, idempotente):**
- Cada linha é associada à barra real, procurando o `ret_1d` nas barras diárias do ETF.
- O snapshot passa para a data da barra da maioria. Por data de mercado fica o snapshot gravado mais tarde.
- `close` e `ret_1d` passam a vir dos preços finais num calendário de dias úteis (forward-fill só do preço, 0% sem negociação). Scores e features ficam como foram calculados na altura.
- Resultado: 9 771 → 6 229 linhas, 117 → 74 snapshots, 0 linhas de fim de semana.
- Sem preço diário (AIGA.L e PHPT.L, cujos ficheiros diários só têm uma barra) mantém-se o valor do snapshot. Nenhum dos dois é detido na simulação.

**Simulador (`scripts/run_simulation.py`):**
- Os retornos diários da carteira e do benchmark vêm dos **preços diários finais** num calendário contínuo de dias úteis, não do `ret_1d` do histórico.
- Assim a equity curve não depende de falhas no histórico: os 14 dias úteis sem snapshot (ex.: 08/06, 09/06, 23/09) continuam a ter retorno.
- As datas de sinal continuam a ser os snapshots, com um filtro defensivo que só aceita dias úteis.

As regras de trading não mudaram: Política C, 30 bps, sizing e regime.

## Efeito colateral nas regras de ciclo

O ciclo é de `REBALANCE_EVERY_TRADING_DAYS = 21` snapshots, com rebalance a cada 2 ciclos. Com fins de semana no histórico, 42 "dias" eram ~6 semanas de calendário. Agora são 42 dias de negociação (~9 semanas). A regra é a mesma; muda a duração real dos ciclos. No período VALID_ENSEMBLE_60_40 há 2 ciclos em vez de 3.

O início do período continua a ser 2026-06-09, a data em que o ensemble entrou em produção. Com as datas corrigidas, o snapshot gravado a 09/06 era a barra de 05/06 e fica fora do período. O 1.º sinal válido passa a ser 10/06, o que é conservador e sem look-ahead.

## Resultados: VALID_ENSEMBLE_60_40, Política C (score cru)

| Métrica | Antes (dados com fins de semana) | Depois |
|---|---:|---:|
| Período | 09/06 – 24/09 | 10/06 – 22/09 (último preço disponível) |
| Ciclos | 3 | 2 |
| Retorno bruto | +5,98% | +4,39% |
| **Retorno líquido** | +5,66% | **+3,99%** |
| **MaxDD diário (desde €10.000)** | −7,72% | **−11,87%** |
| MaxDD só com fins de ciclo | −2,09% | 0,00% |
| Turnover médio | 33,3% | 64,4% |
| Custos | €30,00 | €38,82 |
| VWCE.DE no mesmo período | — | +7,07% |

O MaxDD vai do pico de €10.799 (22/06) ao vale de €9.517 (29/07). A carteira do 1.º ciclo (CNDX, ECAR, IWFM, IWVL, RBOT, WTAI, XAIX) é mais temática e de beta mais alto do que a do snapshot antigo, com quedas diárias de 3–6% em 23/06 e 07/07 que são movimentos reais de mercado, confirmados em todos os ETFs.

### Sensibilidade (não altera decisões)

| Variante | Líquido | MaxDD diário | Turnover |
|---|---:|---:|---:|
| C oficial (início 09/06) | +3,99% | −11,87% | 64,4% |
| C a começar no snapshot de 05/06 | +4,67% | −3,84% | 50,0% |
| C com score suavizado | +6,26% | −11,87% | 60,3% |
| B (rebalance em todos os ciclos) | +3,57% | −11,79% | 46,7% |

Com apenas 2 ciclos, **o resultado depende fortemente da data de início**. A carteira inicial decide quase tudo.

## Consequências

- Com dados corrigidos, a Política C **não cumpre** os critérios usados nas decisões anteriores (MaxDD ≤ 8%, turnover ≤ 40%), e fica abaixo do VWCE.DE. As conclusões de `track_record_analysis.md`, `score_smoothing_analysis.md`, `score_persistence_analysis.md` e `max_drawdown_fix.md` usavam dados com fins de semana e devem ser revistas antes de qualquer nova decisão.
- O backtest de sinais (`backtest_signals.py`) passa de 117 para 74 dias de histórico. Volta ao estado `A_ACUMULAR` (74/85 dias), porque os fins de semana estavam a contar como dias.
- Sharpe/Sortino com 2 ciclos não têm significado (Sortino = 0 sem ciclos negativos).

## Adenda: AIGA.L e PHPT.L truncados

**Causa:** o batch do Yahoo devolveu intermitentemente só a última barra destes dois tickers: AIGA.L desde julho, PHPT.L desde meados de setembro. `fetch_daily.py` sobrescrevia o ficheiro sem verificar, apagando ~2 anos de histórico.

**Correção em `fetch_daily.py`:** um download que começa mais de 10 dias depois do histórico existente é tratado como truncado. É repetido individualmente e, se continuar curto, fundido com o histórico existente. O ficheiro nunca é encurtado.

**Reconstrução:** o ambiente desta sessão não tem acesso ao Yahoo Finance (proxy 403). Os ficheiros foram reconstruídos a partir das 289 (AIGA.L) e 305 (PHPT.L) versões guardadas no histórico git. Cada versão truncada continha a barra real desse dia. Por data fica a versão mais recente.
- AIGA.L: 575 barras, de 2024-06-03 a 2026-09-23. Fica um buraco de 04/09 a 15/09 (6 dias úteis).
- PHPT.L: 585 barras, de 2024-06-03 a 2026-09-23, completo.

**Download completo pendente:** corre o workflow manual `Refetch Prices` (`refetch_prices.yml`, input `AIGA.L PHPT.L`). Chama `scripts/refetch_symbols.py`, que valida o resultado (sem duplicados, sem fins de semana, ≥ 400 barras, sem buracos > 5 dias úteis) e falha se o ficheiro continuar incompleto.
