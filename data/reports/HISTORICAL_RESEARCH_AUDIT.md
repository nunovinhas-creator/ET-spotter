# Auditoria histórica ET-Spotter — 23-10-2026

## Estado
**Investigação retrospetiva, NÃO validação de rentabilidade do ensemble oficial.**
O simulador publicado, a configuração operacional e o dashboard permanecem intactos.
O workflow Historical ETF Research (isolated) só descarrega preços quando pedido
manualmente, e guarda o output nos artefactos da execução, nunca no track record.

## Achados verificados
- scripts/fetch_daily.py usa period=2y: não tem cobertura completa para 2020/2022.
- scripts/run_simulation.py depende de scores_history.csv recolhido desde 2026;
  usar esses sinais em 2020 seria fabricar decisões.
- scripts/train_model.py tem corte temporal 2026-01-01. O modelo serializado
  não pode prever honestamente 2020, pois viu o futuro. O relatório XGB
  regista ROC-AUC 0,534 e accuracy 54,3%, abaixo do baseline 58,8%.
- scripts/run_simulation.py usa anualização sqrt(252/21) e taxa de risco
  para 21 sessões, embora os ciclos da política C durem cerca de 42 sessões.
  Sharpe e Sortino publicados devem ser reavaliados com NAV diário.
- data/reports/simulation_stress.csv contém cenários estimados por
  beta/alpha, não o resultado de operações históricas reais.

## O que o motor novo faz
1. Descarrega preços ajustados via yfinance para diretório separado.
2. Recalcula indicadores técnicos passados pelo compute_metrics existente.
3. Aplica o score V3 em snapshots passados, sem usar o modelo XGB posterior.
4. Aplica caps por categoria, exclusão do quartil de volatilidade alta,
   filtro de regime VWCE SMA200/VIX, scores suavizados e rotação parcial.
5. Sinal no fecho de D -> compra na abertura de D+1; custos explícitos por
   lado negociado; participações, dinheiro e equity diária.
6. Compara CAGR, drawdown, volatilidade, Sharpe e Sortino diários com VWCE.

## Limites materiais
- Ausência do ensemble de IA (60/40), do Kelly e da reprodução integral
  da política de permanência: replay V3 é uma variante exploratória.
- Universo atual de ETFs retroprojetado para anos anteriores: risco de
  enviesamento de sobrevivência.
- Londres/EUA: cotação em outras moedas, sem conversão cambial fidedigna
  para euros. ROI não é executável e não se pode tratar como retorno EUR.
- Regras escolhidas em 2026 não são out-of-sample ao testá-las em 2020.
- SMA200 requer 200 sessões de VWCE; até esse ponto regime é UNKNOWN e
  as operações não representam a queda inicial de 2020.
- O preço de abertura seguinte é uma idealização; execução real varia.
- Comparação do VWCE aplica buy-and-hold direto só para datas com cotações.

## Execução e evidência
GitHub -> Actions -> Historical ETF Research (isolated) -> Run workflow.
Usar start=2020-01-01 e cost_side_bps=15. Os testes offline correm primeiro;
o job histórico tenta recolha desde 2013 (se o ETF já estava cotado) e
publica equity_v3_research.csv + audit_v3_research.json como artefactos.
Qualquer falha de dados é sinalizada; não se inventam retornos.

## Para validar a estratégia oficial
1. Histórico de preços ajustado, moeda EUR, ETFs extintos e delistings.
2. Reproduzir todas as regras point-in-time do simulador, custos e cash.
3. Treinar XGB novamente em cada janela walk-forward, com embargo mínimo
   de 21 dias úteis nos rótulos fwd21 e sem informação futura.
4. Parâmetros fixados ANTES do holdout; testar em janela realmente intocada.
5. Stress de custos, FX, slippage, spreads e qualidade de dados.
6. Só então comparar alfa robusto, ROI, Sharpe, Sortino e drawdowns com VWCE.


## Primeira execução plurianual observada (run 39964452566)

Execução GitHub Actions: https://github.com/nunovinhas-creator/ET-spotter/actions/runs/39964452566
Artefacto histórico: https://github.com/nunovinhas-creator/ET-spotter/actions/runs/39964452566/artifacts/12506157645

- 97 símbolos pedidos, 82 séries descarregadas e 15 falhas/insuficiências;
  HMCA.L e IIND.L foram ainda rejeitados por dados de abertura inválidos.
- Primeira decisão elegível: 2020-07-03, depois de 127 sessões de aquecimento
  (VWCE SMA200); a grande queda pandémica de fevereiro/março 2020 NÃO foi testada.
- Última data: 2026-10-23; 1606 retornos diários, 39 rebalanceamentos.
- Score V3 sem XGB: retorno total +36,84%, CAGR +5,04%,
  MaxDD -21,20%, Sharpe 0,24.
- VWCE nas datas coincidentes: retorno total +130,82%, CAGR +14,03%,
  MaxDD -22,43%, Sharpe 0,79.
- Custos do modelo aproximado: EUR 284,67 sobre capital inicial EUR 10 000
  com 15 bps por lado transacionado; não incluem conversão FX.
- 2022: score V3 -17,15% contra VWCE -13,12%.
- Em todos os anos analisados (2020 parcial a 2026 parcial) o VWCE ganhou
  em retorno. Resultados EXPLORATÓRIOS, não equivalentes a desempenho
  investível nem a validação fora da amostra da política 60/40.

### Defeito metodológico adicional da avaliação XGB existente

Em scripts/train_model.py, o target de cada observação utiliza preço em t+21.
O split treino < 2026-01-01 / teste >= 2026-01-01 não aplica purga:
alguns rótulos de treino de dezembro de 2025 usam preços de janeiro de
2026, já dentro do período de teste. Portanto, a divisão temporal nominal
NÃO é uma separação rigorosamente sem fuga de rótulos. Corrigir com embargo
de pelo menos 21 sessões e treino walk-forward antes de qualquer conclusão
de validação IA. Não se alterou o modelo nem se publicou novos sinais.

### Recomendação após esta execução

Não promover o replay V3 para estratégia oficial nem interpretar melhoria
de risco como vantagem: o Sharpe e o CAGR foram inferiores ao VWCE,
incluindo 2022. O workflow histórico completo requer agora disparo
manual explícito, para não repetir downloads em cada commit/PR.
