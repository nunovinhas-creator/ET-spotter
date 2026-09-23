import json
from pathlib import Path

import pandas as pd


INITIAL_CAPITAL = 10000.0
REBALANCE_EVERY_TRADING_DAYS = 21
TRANSACTION_COST_PER_ROUND = 0.002
RISK_FREE_RATE_ANNUAL = 0.03
BENCHMARK_TICKER = "VWCE.DE"
REBALANCE_THRESHOLD = 0.05


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


def _load_benchmark_data(dates: list[pd.Timestamp]) -> pd.DataFrame:
    benchmark_path = Path(__file__).parent.parent / "data" / "daily" / f"{BENCHMARK_TICKER}.csv"
    if not benchmark_path.exists():
        return pd.DataFrame(index=dates, data={"close": float("nan"), "ret_1d": 0.0, "sma200": float("nan")})
    benchmark = pd.read_csv(benchmark_path, parse_dates=["Date"])
    benchmark = benchmark.set_index("Date")[["close"]]
    benchmark["ret_1d"] = benchmark["close"].pct_change().fillna(0.0)
    benchmark["sma200"] = benchmark["close"].rolling(200, min_periods=200).mean()
    benchmark = benchmark.reindex(dates).ffill()
    benchmark["ret_1d"] = benchmark["ret_1d"].fillna(0.0)
    return benchmark


def run_backtest(
    transaction_cost: float = TRANSACTION_COST_PER_ROUND,
    rebalance_every: int = REBALANCE_EVERY_TRADING_DAYS,
    risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL,
    rebalance_threshold: float = REBALANCE_THRESHOLD,
) -> pd.DataFrame:
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be at least 1")
    if risk_free_rate_annual < 0:
        raise ValueError("risk_free_rate_annual must be non-negative")
    if not 0 <= rebalance_threshold <= 1:
        raise ValueError("rebalance_threshold must be between 0 and 1")

    df = pd.read_csv(_history_path())
    df["date"] = pd.to_datetime(df["date"])

    required_columns = {"date", "etf", "score", "ret_1d", "vol_21"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    df_clean = df.dropna(subset=["score", "ret_1d"]).copy()
    etf_names = _load_etf_names()
    trading_dates = sorted(df_clean["date"].unique())
    benchmark_data = _load_benchmark_data(trading_dates)
    cycles = []
    current_weights: dict[str, float] = {}
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
        selected_holdings = set(selection["etf"])
        if len(selected_holdings) != 3:
            continue

        benchmark_row = benchmark_data.loc[start_date]
        benchmark_close = benchmark_row["close"]
        benchmark_sma200 = benchmark_row["sma200"]
        if pd.isna(benchmark_sma200) or pd.isna(benchmark_close):
            market_regime = "UNKNOWN"
        else:
            market_regime = "BULL" if benchmark_close > benchmark_sma200 else "BEAR"
        exposure = 0.0 if market_regime == "BEAR" else 1.0
        volatility = selection.set_index("etf")["vol_21"].abs().replace(0, float("nan"))
        volatility = volatility.replace([float("inf"), float("-inf")], float("nan"))
        volatility = volatility.fillna(volatility.median()).fillna(1.0)
        inverse_volatility = 1 / volatility
        target_weights = (inverse_volatility / inverse_volatility.sum() * exposure).to_dict()
        weight_keys = set(current_weights) | set(target_weights)
        max_weight_deviation = max(
            (abs(current_weights.get(ticker, 0.0) - target_weights.get(ticker, 0.0)) for ticker in weight_keys),
            default=1.0,
        )
        rebalance_executed = not current_weights or max_weight_deviation > rebalance_threshold
        active_weights = target_weights if rebalance_executed else current_weights.copy()
        active_holdings = {ticker for ticker, weight in active_weights.items() if weight > 0}
        turnover = (
            1 - sum(min(current_weights.get(ticker, 0.0), target_weights.get(ticker, 0.0)) for ticker in weight_keys)
            if rebalance_executed
            else 0.0
        )
        friction_cost_rate = transaction_cost * turnover
        gross_daily_returns = (
            df_clean[df_clean["date"].isin(cycle_dates) & df_clean["etf"].isin(active_holdings)]
            .pivot_table(index="date", columns="etf", values="ret_1d")
            .reindex(cycle_dates)
            .reindex(columns=sorted(active_holdings))
        )
        active_asset_returns = gross_daily_returns.fillna(0).add(1).prod() - 1
        weighted_daily_returns = gross_daily_returns.fillna(0).mul(pd.Series(active_weights), axis=1).sum(axis=1)
        gross_cycle_return = (1 + weighted_daily_returns).prod() - 1
        risk_free_cycle_return = (1 + risk_free_rate_annual) ** (rebalance_every / 252) - 1
        portfolio_value_before = portfolio_value
        friction_cost_eur = portfolio_value_before * friction_cost_rate
        net_cycle_return = (1 + gross_cycle_return) * (1 - friction_cost_rate) - 1
        allocation_details = [
            {
                "ticker": ticker,
                "name": etf_names.get(ticker, ticker),
                "score": (round(float(selection.loc[selection["etf"] == ticker, "score"].iloc[0]), 4) if ticker in selected_holdings else None),
                "volatility_21": (round(float(volatility[ticker]), 6) if ticker in volatility else None),
                "target_weight": float(target_weights.get(ticker, 0.0)),
                "weight": float(active_weights.get(ticker, 0.0)),
                "contribution": float(active_asset_returns.get(ticker, 0.0) * active_weights.get(ticker, 0.0)),
                "weighting": "inverse_volatility",
                "active": bool(active_weights.get(ticker, 0.0)),
            }
            for ticker in sorted(set(selected_holdings) | set(active_holdings))
        ]
        benchmark_cycle_return = benchmark_data.loc[cycle_dates, "ret_1d"].fillna(0).add(1).prod() - 1
        portfolio_value *= 1 + net_cycle_return
        benchmark_value = INITIAL_CAPITAL if not cycles else cycles[-1]["benchmark_value"]
        benchmark_value *= 1 + benchmark_cycle_return
        cycles.append(
            {
                "cycle": cycle_number,
                "date": start_date,
                "cycle_end": cycle_dates[-1],
                "holdings": ",".join(sorted(active_holdings)) if active_holdings else "CASH",
                "target_holdings": ",".join(sorted(selected_holdings)) if target_weights else "CASH",
                "allocation_details": json.dumps(allocation_details, ensure_ascii=False),
                "market_regime": market_regime,
                "benchmark_close": benchmark_close,
                "benchmark_sma200": benchmark_sma200,
                "exposure": exposure,
                "max_weight_deviation": max_weight_deviation,
                "rebalance_threshold": rebalance_threshold,
                "rebalance_executed": rebalance_executed,
                "cost_saving": not rebalance_executed,
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
        end_asset_values = pd.Series(active_weights) * (1 + active_asset_returns)
        total_growth = 1 + gross_cycle_return
        current_weights = {
            ticker: float(value / total_growth)
            for ticker, value in end_asset_values.items()
            if value > 0
        }

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
    real_rebalances = int(portfolio_perf["rebalance_executed"].sum())
    cost_saving_cycles = int(portfolio_perf["cost_saving"].sum())
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
        "bull_cycles": int((portfolio_perf["market_regime"] == "BULL").sum()),
        "bear_cycles": int((portfolio_perf["market_regime"] == "BEAR").sum()),
        "average_exposure": portfolio_perf["exposure"].mean(),
        "rebalance_threshold": rebalance_threshold,
        "cost_saving_cycles": cost_saving_cycles,
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
    print(f"Filtro SMA200: {summary['bull_cycles']} Bull / {summary['bear_cycles']} Bear | exposição média: {summary['average_exposure'] * 100:.1f}%")
    print("Ponderação: inversa à volatilidade histórica de 21 dias")
    print(f"Threshold de rebalanceamento: {rebalance_threshold * 100:.1f}% | {cost_saving_cycles} ciclos sem rotação")

    output_path = Path("data/reports/simulation_results.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio_perf.to_csv(output_path, index=False)
    print(f"\nResultados gravados em {output_path}")
    return portfolio_perf


if __name__ == "__main__":
    run_backtest()