import json
from pathlib import Path

import pandas as pd


INITIAL_CAPITAL = 10000.0
REBALANCE_EVERY_TRADING_DAYS = 21
TRANSACTION_COST_PER_ROUND = 0.003
RISK_FREE_RATE_ANNUAL = 0.03
BENCHMARK_TICKER = "VWCE.DE"
REBALANCE_THRESHOLD = 0.12
STRESS_SCENARIO_COUNT = 5
MAX_POSITIONS = 7
TARGET_VOLATILITY = 0.12
FRACTIONAL_KELLY = 0.25
VIX_STRESS_LEVEL = 28.0
DEFAULT_CATEGORY_CAP = 0.25
MIN_HOLDING_CYCLES = 3
MAX_NEW_POSITIONS = 2
MIN_SELL_SCORE = 0.40
REBALANCE_CYCLE_INTERVAL = 2
DEFAULT_POLICY_NAME = "C"
ENSEMBLE_V3_WEIGHT = 0.6
ENSEMBLE_XGB_WEIGHT = 0.4
REPORT_PATH = Path("data/reports/simulation_results.csv")
VALID_REPORT_PATH = Path("data/reports/simulation_results_valid_ensemble.csv")
LEGACY_REPORT_PATH = Path("data/reports/simulation_legacy_incomplete.csv")


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


def _load_etf_metadata() -> dict[str, dict]:
    config_path = Path(__file__).parent.parent / "config" / "etfs.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        etf["ticker"]: {
            "name": etf.get("name", etf["ticker"]),
            "category_id": category.get("id", "other"),
            "category_name": category.get("name", "Other"),
            "category_cap": category.get("max_weight", DEFAULT_CATEGORY_CAP),
        }
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
    vix_path = Path(__file__).parent.parent / "data" / "daily" / "VIX.csv"
    if vix_path.exists():
        vix = pd.read_csv(vix_path, index_col=0, parse_dates=True)
        benchmark["vix"] = vix["close"].reindex(dates).ffill()
    else:
        benchmark["vix"] = float("nan")
    benchmark = benchmark.reindex(dates).ffill()
    benchmark["ret_1d"] = benchmark["ret_1d"].fillna(0.0)
    return benchmark


def _capped_weights(
    raw_weights: pd.Series,
    metadata: dict[str, dict],
    exposure: float,
) -> dict[str, float]:
    """Normalise weights while respecting a cap for every ETF category."""
    if raw_weights.empty or exposure <= 0:
        return {ticker: 0.0 for ticker in raw_weights.index}

    remaining = raw_weights.astype(float).clip(lower=0).copy()
    result = pd.Series(0.0, index=remaining.index)
    open_tickers = set(remaining.index)
    remaining_exposure = exposure
    for _ in range(len(remaining) + 1):
        if not open_tickers or remaining_exposure <= 1e-9:
            break
        open_series = remaining.loc[sorted(open_tickers)]
        allocation = open_series / open_series.sum() * remaining_exposure
        capped = []
        for ticker, weight in allocation.items():
            cap = float(metadata.get(ticker, {}).get("category_cap", DEFAULT_CATEGORY_CAP))
            category = metadata.get(ticker, {}).get("category_id", "other")
            category_weight = result.loc[
                [t for t in result.index if metadata.get(t, {}).get("category_id", "other") == category]
            ].sum()
            if weight + category_weight > cap + 1e-9:
                capped.append((ticker, max(0.0, cap - category_weight)))
        if not capped:
            result.loc[sorted(open_tickers)] = allocation
            break
        for ticker, weight in capped:
            result[ticker] = weight
            remaining_exposure -= weight
            open_tickers.remove(ticker)
    return result.to_dict()


def _archive_incomplete_report() -> None:
    """Retain old cycles separately so they cannot enter the public track-record."""
    if not REPORT_PATH.exists():
        return
    old = pd.read_csv(REPORT_PATH)
    incomplete = False
    for details in old.get("allocation_details", pd.Series(dtype=str)).dropna():
        for allocation in json.loads(details):
            if any(
                key not in allocation or pd.isna(allocation.get(key))
                for key in ("score_v3", "score_final", "weight")
            ):
                incomplete = True
                break
            if "xgb_proba" not in allocation and allocation.get("ml_prob") is None:
                incomplete = True
                break
        if incomplete:
            break
    if incomplete:
        old["track_record_status"] = "LEGACY_INCOMPLETE"
        old["ensemble_active"] = False
        LEGACY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        old.to_csv(LEGACY_REPORT_PATH, index=False)


def _reconstruct_score_v3(df: pd.DataFrame) -> pd.Series:
    components = {"_momentum": 0.35, "_trend": 0.25, "_risk": 0.25, "_alpha_quality": 0.15}
    complete = df[list(components)].notna().all(axis=1)
    reconstructed = sum(df[column] * weight for column, weight in components.items()).round(6)
    return df["score_v3"].where(df["score_v3"].notna(), reconstructed.where(complete))


def _historical_stress_scenarios(
    alpha_cycle: float,
    beta: float,
    risk_free_cycle_return: float,
    rebalance_every: int,
) -> pd.DataFrame:
    benchmark_path = Path(__file__).parent.parent / "data" / "daily" / f"{BENCHMARK_TICKER}.csv"
    if not benchmark_path.exists():
        return pd.DataFrame()
    benchmark = pd.read_csv(benchmark_path, parse_dates=["Date"]).set_index("Date")
    rolling_return = benchmark["close"].pct_change(rebalance_every).dropna().sort_values()
    selected = []
    for end_date, benchmark_return in rolling_return.items():
        if all(abs((end_date - previous_date).days) >= rebalance_every for previous_date, _ in selected):
            selected.append((end_date, benchmark_return))
        if len(selected) == STRESS_SCENARIO_COUNT:
            break

    scenarios = []
    for scenario_number, (end_date, benchmark_return) in enumerate(selected, start=1):
        start_position = benchmark.index.get_loc(end_date) - rebalance_every
        start_date = benchmark.index[max(0, start_position)]
        estimated_strategy_return = risk_free_cycle_return + alpha_cycle + beta * (benchmark_return - risk_free_cycle_return)
        scenarios.append(
            {
                "scenario": scenario_number,
                "window_start": start_date.strftime("%Y-%m-%d"),
                "window_end": end_date.strftime("%Y-%m-%d"),
                "benchmark_return": benchmark_return,
                "estimated_strategy_return": estimated_strategy_return,
                "stress_level": "SEVERO" if benchmark_return <= -0.20 else "FORTE",
            }
        )
    return pd.DataFrame(scenarios)


def run_backtest(
    transaction_cost: float = TRANSACTION_COST_PER_ROUND,
    rebalance_every: int = REBALANCE_EVERY_TRADING_DAYS,
    risk_free_rate_annual: float = RISK_FREE_RATE_ANNUAL,
    rebalance_threshold: float = REBALANCE_THRESHOLD,
    min_holding_cycles: int = MIN_HOLDING_CYCLES,
    max_new_positions: int | None = MAX_NEW_POSITIONS,
    persist_output: bool = True,
    start_date: str | None = None,
    require_ensemble: bool = False,
    output_path: Path = REPORT_PATH,
    track_record_scope: str = "FULL_HISTORY",
    max_positions: int = MAX_POSITIONS,
    min_sell_score: float = MIN_SELL_SCORE,
    rebalance_cycle_interval: int = REBALANCE_CYCLE_INTERVAL,
    policy_name: str = DEFAULT_POLICY_NAME,
) -> pd.DataFrame:
    if transaction_cost < 0:
        raise ValueError("transaction_cost must be non-negative")
    if rebalance_every < 1:
        raise ValueError("rebalance_every must be at least 1")
    if risk_free_rate_annual < 0:
        raise ValueError("risk_free_rate_annual must be non-negative")
    if not 0 <= rebalance_threshold <= 1:
        raise ValueError("rebalance_threshold must be between 0 and 1")
    if min_holding_cycles < 0:
        raise ValueError("min_holding_cycles must be non-negative")
    if max_new_positions is not None and max_new_positions < 1:
        raise ValueError("max_new_positions must be positive when provided")
    if max_positions < 1:
        raise ValueError("max_positions must be positive")
    if not 0 <= min_sell_score <= 1:
        raise ValueError("min_sell_score must be between 0 and 1")
    if rebalance_cycle_interval < 1:
        raise ValueError("rebalance_cycle_interval must be positive")

    df = pd.read_csv(_history_path())
    df["date"] = pd.to_datetime(df["date"])

    required_columns = {"date", "etf", "score", "ret_1d", "vol_21"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    df_clean = df.dropna(subset=["score", "ret_1d"]).copy()
    etf_names = _load_etf_names()
    etf_metadata = _load_etf_metadata()
    if "score_v3" not in df_clean.columns:
        df_clean["score_v3"] = float("nan")
    df_clean["score_v3"] = _reconstruct_score_v3(df_clean)
    df_clean["xgb_proba"] = df_clean.get("ml_prob", pd.Series(float("nan"), index=df_clean.index))
    model_available = df_clean["xgb_proba"].notna().any()
    df_clean["score_final"] = df_clean["score_v3"]
    ensemble_mask = df_clean["score_v3"].notna() & df_clean["xgb_proba"].notna()
    df_clean.loc[ensemble_mask, "score_final"] = (
        ENSEMBLE_V3_WEIGHT * df_clean.loc[ensemble_mask, "score_v3"]
        + ENSEMBLE_XGB_WEIGHT * df_clean.loc[ensemble_mask, "xgb_proba"]
    ).round(6)

    def _date_is_eligible(date: pd.Timestamp) -> bool:
        candidates = df_clean[df_clean["date"] == date].sort_values("score_final", ascending=False).head(max_positions)
        if len(candidates) != max_positions or candidates["score_v3"].isna().any():
            return False
        return not require_ensemble or candidates["xgb_proba"].notna().all()

    all_dates = sorted(df_clean["date"].unique())
    eligible_dates = [date for date in all_dates if _date_is_eligible(date)]
    if not eligible_dates:
        raise ValueError("No complete ensemble dates available for the public track-record")
    ensemble_dates = [
        date
        for date in all_dates
        if len(df_clean[df_clean["date"] == date].sort_values("score_final", ascending=False).head(max_positions)) == max_positions
        and df_clean[df_clean["date"] == date].sort_values("score_final", ascending=False).head(max_positions)["xgb_proba"].notna().all()
    ]
    ensemble_active_from = pd.Timestamp(ensemble_dates[0]).strftime("%Y-%m-%d") if ensemble_dates else "UNAVAILABLE"
    first_date = pd.Timestamp(start_date) if start_date else pd.Timestamp(eligible_dates[0])
    trading_dates = [date for date in all_dates if date >= first_date and _date_is_eligible(date)]
    if require_ensemble:
        trading_dates = [date for date in trading_dates if pd.Timestamp(date) >= pd.Timestamp(ensemble_active_from)]
    if not trading_dates:
        raise ValueError(f"No eligible dates for {track_record_scope}")
    if persist_output and output_path == REPORT_PATH:
        _archive_incomplete_report()
    benchmark_data = _load_benchmark_data(trading_dates)
    cycles = []
    current_weights: dict[str, float] = {}
    holding_age: dict[str, int] = {}
    asset_returns_history: dict[str, list[float]] = {}
    portfolio_value = INITIAL_CAPITAL

    cycle_span = rebalance_every * rebalance_cycle_interval
    for cycle_number, start_index in enumerate(range(0, len(trading_dates) - 1, cycle_span), start=1):
        start_date = trading_dates[start_index]
        end_index = min(start_index + cycle_span + 1, len(trading_dates))
        # The signal is observed at start_date; returns begin on the next date.
        cycle_dates = trading_dates[start_index + 1:end_index]
        if not cycle_dates:
            continue
        ranking_selection = (
            df_clean[df_clean["date"] == start_date]
            .sort_values("score_final", ascending=False)
            .head(max_positions)
        )
        selected_holdings = set(ranking_selection["etf"])
        if (
            len(selected_holdings) != max_positions
            or ranking_selection["score_v3"].isna().any()
            or (require_ensemble and ranking_selection["xgb_proba"].isna().any())
        ):
            continue

        current_holdings = {ticker for ticker, weight in current_weights.items() if weight > 0}
        initial_allocation = not current_holdings
        score_by_ticker = ranking_selection.set_index("etf")["score_final"].to_dict()
        score_lookup = df_clean[df_clean["date"] == start_date].set_index("etf")["score_final"].to_dict()
        forced_exits = {
            ticker
            for ticker in current_holdings
            if ticker not in score_lookup or score_lookup[ticker] < min_sell_score
        }
        locked_holdings = {
            ticker
            for ticker in current_holdings - forced_exits
            if holding_age.get(ticker, 0) < min_holding_cycles
        }
        retained_selected = current_holdings.intersection(selected_holdings) - forced_exits
        retained_holdings = (locked_holdings | retained_selected) if min_sell_score <= 0.35 else (current_holdings - forced_exits)
        if len(retained_holdings) > max_positions:
            retained_holdings = set(sorted(retained_holdings, key=lambda ticker: score_lookup.get(ticker, 0), reverse=True)[:max_positions])
        available_slots = max(0, max_positions - len(retained_holdings))
        new_candidates = [ticker for ticker in ranking_selection["etf"] if ticker not in current_holdings]
        if max_new_positions is not None and current_holdings:
            new_candidates = new_candidates[:max_new_positions]
        target_holdings = retained_holdings | set(new_candidates[:available_slots])
        if not current_holdings:
            target_holdings = selected_holdings
        selection = df_clean[
            (df_clean["date"] == start_date) & df_clean["etf"].isin(target_holdings)
        ].copy()
        if len(selection) != len(target_holdings) or selection["score_v3"].isna().any():
            continue

        benchmark_row = benchmark_data.loc[start_date]
        benchmark_close = benchmark_row["close"]
        benchmark_sma200 = benchmark_row["sma200"]
        vix_level = benchmark_row.get("vix", float("nan"))
        if pd.isna(benchmark_sma200) or pd.isna(benchmark_close):
            market_regime = "UNKNOWN"
        elif not pd.isna(vix_level) and vix_level >= VIX_STRESS_LEVEL:
            market_regime = "STRESS"
        elif benchmark_close > benchmark_sma200:
            market_regime = "BULL"
        else:
            market_regime = "BEAR"
        exposure = 1.0 if market_regime == "BULL" else 0.0
        volatility = selection.set_index("etf")["vol_21"].abs().replace(0, float("nan"))
        volatility = volatility.replace([float("inf"), float("-inf")], float("nan"))
        volatility = volatility.fillna(volatility.median()).fillna(1.0)
        score_strength = (selection.set_index("etf")["score_final"] / selection["score_final"].max()).clip(0.5, 1.0)
        kelly_multiplier = {}
        for ticker in target_holdings:
            history = asset_returns_history.get(ticker, [])
            hit_rate = sum(value > 0 for value in history) / len(history) if history else 0.5
            kelly_fraction = FRACTIONAL_KELLY * max(0.0, 2 * hit_rate - 1)
            kelly_multiplier[ticker] = 0.5 + kelly_fraction
        raw_weights = (TARGET_VOLATILITY / volatility) * score_strength
        raw_weights = raw_weights * pd.Series(kelly_multiplier)
        target_weights = _capped_weights(raw_weights, etf_metadata, exposure)
        weight_keys = set(current_weights) | set(target_weights)
        max_weight_deviation = max(
            (abs(current_weights.get(ticker, 0.0) - target_weights.get(ticker, 0.0)) for ticker in weight_keys),
            default=1.0,
        )
        rebalance_executed = not current_weights or max_weight_deviation >= rebalance_threshold
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
                "score": (round(float(selection.loc[selection["etf"] == ticker, "score_final"].iloc[0]), 4) if ticker in target_holdings else None),
                "score_v3": (round(float(selection.loc[selection["etf"] == ticker, "score_v3"].iloc[0]), 4) if ticker in target_holdings else None),
                "xgb_proba": (round(float(selection.loc[selection["etf"] == ticker, "xgb_proba"].iloc[0]), 4) if ticker in target_holdings and pd.notna(selection.loc[selection["etf"] == ticker, "xgb_proba"].iloc[0]) else None),
                "score_final": (round(float(selection.loc[selection["etf"] == ticker, "score_final"].iloc[0]), 4) if ticker in target_holdings else None),
                "volatility_21": (round(float(volatility[ticker]), 6) if ticker in volatility else None),
                "target_weight": float(target_weights.get(ticker, 0.0)),
                "weight": float(active_weights.get(ticker, 0.0)),
                "contribution": float(active_asset_returns.get(ticker, 0.0) * active_weights.get(ticker, 0.0)),
                "weighting": "volatility_targeted_fractional_kelly",
                "kelly_multiplier": float(kelly_multiplier.get(ticker, 0.0)),
                "category": etf_metadata.get(ticker, {}).get("category_name", "Other"),
                "active": bool(active_weights.get(ticker, 0.0)),
            }
            for ticker in sorted(set(target_holdings) | set(active_holdings))
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
                "positions_count": len(active_holdings),
                "target_holdings": ",".join(sorted(target_holdings)) if target_weights else "CASH",
                "allocation_details": json.dumps(allocation_details, ensure_ascii=False),
                "market_regime": market_regime,
                "regime": market_regime,
                "benchmark_close": benchmark_close,
                "benchmark_sma200": benchmark_sma200,
                "vix_level": vix_level,
                "exposure": exposure,
                "max_weight_deviation": max_weight_deviation,
                "rebalance_threshold": rebalance_threshold,
                "rebalance_executed": rebalance_executed,
                "cost_saving": not rebalance_executed,
                "turnover": turnover,
                "friction_cost_rate": friction_cost_rate,
                "friction_cost_eur": friction_cost_eur,
                "cost_eur": friction_cost_eur,
                "gross_cycle_return": gross_cycle_return,
                "strategy_ret": net_cycle_return,
                "risk_free_cycle_return": risk_free_cycle_return,
                "excess_return": net_cycle_return - risk_free_cycle_return,
                "portfolio_value": portfolio_value,
                "benchmark_ticker": BENCHMARK_TICKER,
                "benchmark_cycle_return": benchmark_cycle_return,
                "benchmark_value": benchmark_value,
                "new_positions": 0 if initial_allocation else len(set(active_holdings) - current_holdings),
                "initial_positions": len(active_holdings) if initial_allocation else 0,
                "min_holding_cycles": min_holding_cycles,
                "max_new_positions": max_new_positions,
                "max_positions": max_positions,
                "min_sell_score": min_sell_score,
                "rebalance_cycle_interval": rebalance_cycle_interval,
                "policy_name": policy_name,
                "ensemble_active_from": ensemble_active_from,
                "ensemble_version": "score_v3_60_xgb_40",
                "track_record_status": "VALID_ENSEMBLE_60_40" if require_ensemble else (
                    "VALID_ENSEMBLE_60_40" if pd.Timestamp(start_date) >= pd.Timestamp(ensemble_active_from) and ranking_selection["xgb_proba"].notna().all() else "PRE_ENSEMBLE"
                ),
                "track_record_scope": track_record_scope,
            }
        )
        end_asset_values = pd.Series(active_weights) * (1 + active_asset_returns)
        total_growth = 1 + gross_cycle_return
        current_weights = {
            ticker: float(value / total_growth)
            for ticker, value in end_asset_values.items()
            if value > 0
        }
        holding_age = {
            ticker: holding_age.get(ticker, 0) + 1
            for ticker in current_weights
        }
        for ticker, asset_return in active_asset_returns.items():
            asset_returns_history.setdefault(ticker, []).append(float(asset_return))

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
    benchmark_excess = portfolio_perf["benchmark_cycle_return"] - portfolio_perf["risk_free_cycle_return"]
    benchmark_variance = benchmark_excess.var(ddof=1)
    beta = portfolio_perf["excess_return"].cov(benchmark_excess) / benchmark_variance if benchmark_variance else 0.0
    alpha_cycle = portfolio_perf["excess_return"].mean() - beta * benchmark_excess.mean()
    jensen_alpha_annual = alpha_cycle * (252 / rebalance_every)
    stress_scenarios = _historical_stress_scenarios(
        alpha_cycle, beta, portfolio_perf["risk_free_cycle_return"].iloc[0], rebalance_every
    )
    real_rebalances = int(portfolio_perf["rebalance_executed"].sum())
    cost_saving_cycles = int(portfolio_perf["cost_saving"].sum())
    analysis_start = portfolio_perf["date"].min().strftime("%Y-%m-%d")
    analysis_end = portfolio_perf["cycle_end"].max().strftime("%Y-%m-%d")
    legacy_cycles_excluded = (
        len(pd.read_csv(LEGACY_REPORT_PATH)) if LEGACY_REPORT_PATH.exists() else 0
    )
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
        "jensen_alpha_annual": jensen_alpha_annual,
        "beta": beta,
        "transaction_cost_per_round": transaction_cost,
        "risk_free_rate_annual": risk_free_rate_annual,
        "bull_cycles": int((portfolio_perf["market_regime"] == "BULL").sum()),
        "bear_cycles": int((portfolio_perf["market_regime"].isin(["BEAR", "STRESS"])).sum()),
        "stress_cycles": int((portfolio_perf["market_regime"] == "STRESS").sum()),
        "average_exposure": portfolio_perf["exposure"].mean(),
        "rebalance_threshold": rebalance_threshold,
        "cost_saving_cycles": cost_saving_cycles,
        "max_positions": max_positions,
        "min_holding_cycles": min_holding_cycles,
        "max_new_positions": max_new_positions,
        "min_sell_score": min_sell_score,
        "rebalance_cycle_interval": rebalance_cycle_interval,
        "policy_name": policy_name,
        "target_volatility": TARGET_VOLATILITY,
        "fractional_kelly": FRACTIONAL_KELLY,
        "vix_stress_level": VIX_STRESS_LEVEL,
        "ensemble_score_weight_v3": 0.6,
        "ensemble_score_weight_xgb": 0.4,
        "ensemble_active_from": ensemble_active_from,
        "legacy_cycles_excluded": legacy_cycles_excluded,
        "track_record_summary_status": track_record_scope,
        "track_record_scope": track_record_scope,
        "cost_model": "30 bps round-trip: 5 bps commission + 15 bps spread + 10 bps slippage",
    }
    for key, value in summary.items():
        portfolio_perf[key] = value

    print("=== RELATÓRIO DE SIMULAÇÃO (SCORE v3 + XGBOOST) ===")
    print(f"Período analisado: {analysis_start} a {analysis_end}")
    print(f"Número de rebalanceamentos reais: {real_rebalances}")
    print(f"Retorno médio por ciclo ajustado a custos: {summary['average_cycle_return_net'] * 100:.2f}%")
    print(f"Valor final do portfólio (base 10.000€): {summary['final_portfolio_value']:.2f}€")
    print(f"Max Drawdown da estratégia: {max_drawdown * 100:.2f}%")
    print(f"Rentabilidade acumulada: {cumulative_return * 100:.2f}%")
    print(f"Sharpe / Sortino: {sharpe_ratio:.2f} / {sortino_ratio:.2f}")
    print(f"Alpha de Jensen anualizado / Beta: {jensen_alpha_annual * 100:.2f}% / {beta:.2f}")
    print(f"Filtro SMA200: {summary['bull_cycles']} Bull / {summary['bear_cycles']} Bear | exposição média: {summary['average_exposure'] * 100:.1f}%")
    print(f"Ponderação: alvo de volatilidade {TARGET_VOLATILITY * 100:.0f}% + Kelly fracionário {FRACTIONAL_KELLY:.2f} + caps por categoria")
    print(f"Regime: BULL exige VWCE > SMA200 e VIX < {VIX_STRESS_LEVEL:.0f}; BEAR/STRESS ficam em cash")
    print(f"Threshold de rebalanceamento: {rebalance_threshold * 100:.1f}% | {cost_saving_cycles} ciclos sem rotação")

    if persist_output:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        portfolio_perf.to_csv(output_path, index=False)
        stress_path = output_path.parent / "simulation_stress.csv"
        stress_scenarios.to_csv(stress_path, index=False)
        print(f"\nResultados gravados em {output_path}")
        print(f"Stress tests gravados em {stress_path}")
    return portfolio_perf


if __name__ == "__main__":
    run_backtest(
        output_path=REPORT_PATH,
        track_record_scope="FULL_HISTORY",
    )
    run_backtest(
        start_date="2026-06-09",
        require_ensemble=True,
        output_path=VALID_REPORT_PATH,
        track_record_scope="VALID_ENSEMBLE_60_40",
    )