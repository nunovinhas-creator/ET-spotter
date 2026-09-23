from pathlib import Path

import pandas as pd


INITIAL_CAPITAL = 10000.0
REBALANCE_EVERY_TRADING_DAYS = 21
TRANSACTION_COST_PER_ROUND = 0.002


def _history_path() -> Path:
    report_path = Path("data/reports/scores_history.csv")
    if report_path.exists():
        return report_path
    return Path("data/scores_history.csv")


def run_backtest(
    transaction_cost: float = TRANSACTION_COST_PER_ROUND,
    rebalance_every: int = REBALANCE_EVERY_TRADING_DAYS,
) -> pd.DataFrame:
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be at least 1")

    df = pd.read_csv(_history_path())
    df["date"] = pd.to_datetime(df["date"])

    required_columns = {"date", "etf", "score", "ret_1d"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    df_clean = df.dropna(subset=["score", "ret_1d"]).copy()
    trading_dates = sorted(df_clean["date"].unique())
    cycles = []
    previous_holdings = set()
    portfolio_value = INITIAL_CAPITAL

    for cycle_number, start_index in enumerate(range(0, len(trading_dates), rebalance_every), start=1):
        start_date = trading_dates[start_index]
        end_index = min(start_index + rebalance_every, len(trading_dates))
        cycle_dates = trading_dates[start_index:end_index]
        selection = (
            df_clean[df_clean["date"] == start_date]
            .sort_values("score", ascending=False)
            .head(3)
        )
        holdings = set(selection["etf"])
        if len(holdings) != 3:
            continue

        turnover = 1.0 if not previous_holdings else 1 - len(holdings & previous_holdings) / 3
        gross_daily_returns = (
            df_clean[df_clean["date"].isin(cycle_dates) & df_clean["etf"].isin(holdings)]
            .pivot_table(index="date", columns="etf", values="ret_1d")
            .reindex(cycle_dates)
            .reindex(columns=sorted(holdings))
        )
        gross_cycle_return = gross_daily_returns.mean(axis=1).add(1).prod() - 1
        net_cycle_return = (1 + gross_cycle_return) * (1 - transaction_cost * turnover) - 1
        portfolio_value *= 1 + net_cycle_return
        cycles.append(
            {
                "cycle": cycle_number,
                "date": start_date,
                "cycle_end": cycle_dates[-1],
                "holdings": ",".join(sorted(holdings)),
                "turnover": turnover,
                "gross_cycle_return": gross_cycle_return,
                "strategy_ret": net_cycle_return,
                "portfolio_value": portfolio_value,
            }
        )
        previous_holdings = holdings

    portfolio_perf = pd.DataFrame(cycles)
    if portfolio_perf.empty:
        raise ValueError("No valid 21-day portfolio cycles could be calculated")

    portfolio_perf["cumulative_return"] = portfolio_perf["portfolio_value"] / INITIAL_CAPITAL
    running_max = portfolio_perf["portfolio_value"].cummax()
    portfolio_perf["drawdown"] = portfolio_perf["portfolio_value"] / running_max - 1
    max_drawdown = portfolio_perf["drawdown"].min()
    real_rebalances = int((portfolio_perf["turnover"].iloc[1:] > 0).sum())
    analysis_start = portfolio_perf["date"].min().strftime("%Y-%m-%d")
    analysis_end = portfolio_perf["cycle_end"].max().strftime("%Y-%m-%d")
    summary = {
        "analysis_start": analysis_start,
        "analysis_end": analysis_end,
        "real_rebalances": real_rebalances,
        "average_cycle_return_net": portfolio_perf["strategy_ret"].mean(),
        "final_portfolio_value": portfolio_perf["portfolio_value"].iloc[-1],
        "max_drawdown": max_drawdown,
        "transaction_cost_per_round": transaction_cost,
    }
    for key, value in summary.items():
        portfolio_perf[key] = value

    print("=== RELATÓRIO DE SIMULAÇÃO (TOP 3 ETFs por Score v3) ===")
    print(f"Período analisado: {analysis_start} a {analysis_end}")
    print(f"Número de rebalanceamentos reais: {real_rebalances}")
    print(f"Retorno médio por ciclo ajustado a custos: {summary['average_cycle_return_net'] * 100:.2f}%")
    print(f"Valor final do portfólio (base 10.000€): {summary['final_portfolio_value']:.2f}€")
    print(f"Max Drawdown da estratégia: {max_drawdown * 100:.2f}%")

    output_path = Path("data/reports/simulation_results.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio_perf.to_csv(output_path, index=False)
    print(f"\nResultados gravados em {output_path}")
    return portfolio_perf


if __name__ == "__main__":
    run_backtest()