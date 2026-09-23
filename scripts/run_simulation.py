import json
from pathlib import Path

import pandas as pd


INITIAL_CAPITAL = 10000.0
REBALANCE_EVERY_TRADING_DAYS = 21
TRANSACTION_COST_PER_ROUND = 0.002
RISK_FREE_RATE_ANNUAL = 0.03
BENCHMARK_TICKER = "VWCE.DE"


def _history_path() -> Path:
    report_path = Path("data/reports/scores_history.csv")
    if report_path.exists():
        return report_path
    return Path("data/scores_history.csv")


def _load_etf_names() -> dict[str, str]:
    config_path = Path(__file__).parent.parent / "config" / "etfs.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        etf["ticker"]: etf.get("name", etf["ticker"])
        for category in config.get("categories", [])
        for etf in category.get("etfs", [])
    }


def _load_benchmark_returns(dates: list[pd.Timestamp]) -> pd.Series:
    benchmark_path = Path(__file__).parent.parent / "data" / "daily" / f"{BENCHMARK_TICKER}.csv"
    if not benchmark_path.exists():
        return pd.Series(0.0, index=dates)
    benchmark = pd.read_csv(benchmark_path, parse_dates=["Date"])
    benchmark = benchmark.set_index("Date")["close"].pct_change()
    return benchmark.reindex(dates).fillna(0.0)


def run_backtest(
    transaction_cost: float = TRANSACTION_COST_PER_ROUND,
    rebalance_every: int = REBALANCE_EVERY_TRADING_DAYS,
    risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL,
) -> pd.DataFrame:
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be at least 1")
    if risk_free_rate_annual < 0:
        raise ValueError("risk_free_rate_annual must be non-negative")

    df = pd.read_csv(_history_path())
    df["date"] = pd.to_datetime(df["date"])

    required_columns = {"date", "etf", "score", "ret_1d"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    df_clean = df.dropna(subset=["score", "ret_1d"]).copy()
    etf_names = _load_etf_names()
    trading_dates = sorted(df_clean["date"].unique())
    benchmark_returns = _load_benchmark_returns(trading_dates)
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
        friction_cost_rate = transaction_cost * turnover
        gross_daily_returns = (
            df_clean[df_clean["date"].isin(cycle_dates) & df_clean["etf"].isin(holdings)]
            .pivot_table(index="date", columns="etf", values="ret_1d")
            .reindex(cycle_dates)
            .reindex(columns=sorted(holdings))
        )
        asset_cycle_returns = gross_daily_returns.fillna(0).add(1).prod() - 1
        gross_cycle_return = asset_cycle_returns.mean()
        risk_free_cycle_return = (1 + risk_free_rate_annual) ** (rebalance_every / 252) - 1
        portfolio_value_before = portfolio_value
        friction_cost_eur = portfolio_value_before * friction_cost_rate
        net_cycle_return = (1 + gross_cycle_return) * (1 - friction_cost_rate) - 1
        allocation_details = [
            {
                "ticker": ticker,
                "name": etf_names.get(ticker, ticker),
                "score": round(float(selection.loc[selection["etf"] == ticker, "score"].iloc[0]), 4),
                "weight": 1 / len(holdings),
                "contribution": float(asset_cycle_returns[ticker] / len(holdings)),
            }
            for ticker in sorted(holdings)
        ]
        benchmark_cycle_return = benchmark_returns.loc[cycle_dates].add(1).prod() - 1
        portfolio_value *= 1 + net_cycle_return
        benchmark_value = INITIAL_CAPITAL if not cycles else cycles[-1]["benchmark_value"]
        benchmark_value *= 1 + benchmark_cycle_return
        cycles.append(
            {
                "cycle": cycle_number,
                "date": start_date,
                "cycle_end": cycle_dates[-1],
                "holdings": ",".join(sorted(holdings)),
                "allocation_details": json.dumps(allocation_details, ensure_ascii=False),
                "turnover": turnover,
                "friction_cost_rate": friction_cost_rate,
                "friction_cost_eur": friction_cost_eur,
                "gross_cycle_return": gross_cycle_return,
                "strategy_ret": net_cycle_return,
                "risk_free_cycle_return": risk_free_cycle_return,
                "excess_return": net_cycle_return - risk_free_cycle_return,
                "portfolio_value": portfolio_value,
                "benchmark_ticker": BENCHMARK_TICKER,
                "benchmark_cycle_return": benchmark_cycle_return,
                "benchmark_value": benchmark_value,
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
    cumulative_return = portfolio_perf["portfolio_value"].iloc[-1] / INITIAL_CAPITAL - 1
    annualization = (252 / rebalance_every) ** 0.5
    cycle_std = portfolio_perf["excess_return"].std(ddof=1)
    sharpe_ratio = portfolio_perf["excess_return"].mean() / cycle_std * annualization if cycle_std else 0.0
    downside_deviation = portfolio_perf["excess_return"].clip(upper=0).pow(2).mean() ** 0.5
    sortino_ratio = portfolio_perf["excess_return"].mean() / downside_deviation * annualization if downside_deviation else 0.0
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
        "cumulative_return": cumulative_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "transaction_cost_per_round": transaction_cost,
        "risk_free_rate_annual": risk_free_rate_annual,
    }
    for key, value in summary.items():
        portfolio_perf[key] = value

    print("=== RELATÓRIO DE SIMULAÇÃO (TOP 3 ETFs por Score v3) ===")
    print(f"Período analisado: {analysis_start} a {analysis_end}")
    print(f"Número de rebalanceamentos reais: {real_rebalances}")
    print(f"Retorno médio por ciclo ajustado a custos: {summary['average_cycle_return_net'] * 100:.2f}%")
    print(f"Valor final do portfólio (base 10.000€): {summary['final_portfolio_value']:.2f}€")
    print(f"Max Drawdown da estratégia: {max_drawdown * 100:.2f}%")
    print(f"Rentabilidade acumulada: {cumulative_return * 100:.2f}%")
    print(f"Sharpe / Sortino: {sharpe_ratio:.2f} / {sortino_ratio:.2f}")

    output_path = Path("data/reports/simulation_results.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio_perf.to_csv(output_path, index=False)
    print(f"\nResultados gravados em {output_path}")
    return portfolio_perf


if __name__ == "__main__":
    run_backtest()