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
