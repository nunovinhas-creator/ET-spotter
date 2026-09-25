import json
from pathlib import Path

import pandas as pd

from market_regime import REGIME_EXPOSURE, VIX_NEUTRAL_LEVEL, VIX_STRESS_LEVEL, align_vix, classify_regime, load_vix, regime_exposure


# CONFIGURAÇÃO OFICIAL CONGELADA desde 2026-09-25 (ver CLAUDE.md): Política C + score suavizado
# + máx. 2 ETFs/categoria + exclusão do quartil superior de vol_21 + cap de 25% por categoria
# + filtro de regime VIX + SMA200 (desde 2026-09-25, ver market_regime_filter.md).
# Não alterar sem instrução explícita e nova avaliação documentada em data/reports/.
# Modo acumulação: sem otimização até haver ≥ 6–8 ciclos VALID_ENSEMBLE_60_40 completos.
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
# Filtro de regime (ver market_regime.py e market_regime_filter.md), aplicado na construção:
# "vix_sma200" = BULL 100% / NEUTRAL 60% / STRESS e BEAR cash (oficial desde 2026-09-25);
# "legacy" = binário anterior (BULL 100%, resto cash); "none" = sempre 100% (só para comparação).
REGIME_FILTER = "vix_sma200"
DEFAULT_CATEGORY_CAP = 0.25
MIN_HOLDING_CYCLES = 3
MAX_NEW_POSITIONS = 2
MIN_SELL_SCORE = 0.40
REBALANCE_CYCLE_INTERVAL = 2
DEFAULT_POLICY_NAME = "C"
# 1 = score_final cru; 2 = média de score_final(t) e score_final(t-1) do ciclo anterior.
# Oficial desde 2026-09-24: Política C + score suavizado (ver policy_evaluation_clean.md).
SCORE_SMOOTHING_CYCLES = 2
# Restrições de construção da carteira (None = desligada).
# Oficial desde 2026-09-25: máx. 2 ETFs por categoria + excluir da entrada o quartil
# superior de vol_21 do universo (ver maxdd_constraints_analysis.md).
MAX_ETFS_PER_CATEGORY: int | None = 2
HIGH_BETA_CAP: float | None = None
# Categorias/tickers de alto beta: temáticos (tecnologia, robótica, IA, energia limpa,
# veículos elétricos, biotech, cibersegurança) + Nasdaq-100 e sector tecnológico dos EUA.
HIGH_BETA_CATEGORIES = {"thematic"}
HIGH_BETA_TICKERS = {"CNDX.L", "XNAS.L", "IUIT.L"}
# "exclude" = não entra se vol_21 estiver no quartil superior do universo; "halve" = peso × 0,5.
VOL_FILTER_MODE: str | None = "exclude"
VOL_FILTER_QUANTILE = 0.75
# Vol-target real da carteira (reduz a exposição, resto em cash) nos primeiros N ciclos.
EARLY_TARGET_VOLATILITY: float | None = None
EARLY_FRACTIONAL_KELLY: float | None = None
EARLY_SIZING_CYCLES = 2
VOL_TARGET_LOOKBACK_DAYS = 63
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


def _read_daily_close(ticker: str) -> pd.Series:
    path = Path(__file__).parent.parent / "data" / "daily" / f"{ticker}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    daily = pd.read_csv(path, index_col=0, parse_dates=True)
    daily.index = pd.to_datetime(daily.index).normalize()
    daily = daily[~daily.index.duplicated(keep="last")].sort_index()
    return daily["close"].astype(float) if "close" in daily.columns else pd.Series(dtype=float)


def _daily_returns_on_calendar(close: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Retornos diários no calendário de dias úteis: forward-fill só do preço, 0% sem negociação."""
    if close.empty:
        return pd.Series(0.0, index=calendar)
    prices = close.reindex(close.index.union(calendar)).ffill().reindex(calendar)
    return prices.pct_change(fill_method=None).fillna(0.0)


def _load_price_returns(tickers: list[str], calendar: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {ticker: _daily_returns_on_calendar(_read_daily_close(ticker), calendar) for ticker in tickers},
        index=calendar,
    )


def _load_benchmark_data(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    close = _read_daily_close(BENCHMARK_TICKER)
    if close.empty:
        return pd.DataFrame(index=calendar, data={"close": float("nan"), "ret_1d": 0.0, "sma200": float("nan")})
    benchmark = pd.DataFrame(index=calendar)
    benchmark["close"] = close.reindex(close.index.union(calendar)).ffill().reindex(calendar)
    benchmark["ret_1d"] = _daily_returns_on_calendar(close, calendar)
    sma200 = close.rolling(200, min_periods=200).mean()
    benchmark["sma200"] = sma200.reindex(sma200.index.union(calendar)).ffill().reindex(calendar)
    benchmark["vix"] = align_vix(load_vix(), calendar)
    return benchmark


def _capped_weights(
    raw_weights: pd.Series,
    metadata: dict[str, dict],
    exposure: float,
) -> dict[str, float]:
    """Normaliza os pesos respeitando o cap de cada categoria sobre a SOMA dos seus ETFs.

    Water-filling: distribui a exposição proporcionalmente aos pesos brutos; cada categoria
    cuja soma ultrapasse o cap fica fixa no cap (os seus ETFs reduzidos na mesma proporção)
    e o excesso é redistribuído pelas restantes categorias. Se todas atingirem o cap, o
    resto fica em cash.
    """
    if raw_weights.empty or exposure <= 0:
        return {ticker: 0.0 for ticker in raw_weights.index}

    raw = raw_weights.astype(float).clip(lower=0)
    category_of = {ticker: metadata.get(ticker, {}).get("category_id", "other") for ticker in raw.index}
    cap_of = {
        category_of[ticker]: float(metadata.get(ticker, {}).get("category_cap", DEFAULT_CATEGORY_CAP))
        for ticker in raw.index
    }
    result = pd.Series(0.0, index=raw.index)
    open_categories = set(category_of.values())
    remaining_exposure = exposure
    while open_categories and remaining_exposure > 1e-9:
        open_tickers = [ticker for ticker in raw.index if category_of[ticker] in open_categories]
        open_total = raw.loc[open_tickers].sum()
        if open_total <= 0:
            break
        allocation = raw.loc[open_tickers] / open_total * remaining_exposure
        category_totals = allocation.groupby(pd.Series(category_of).loc[open_tickers]).sum()
        breached = [category for category, total in category_totals.items() if total > cap_of[category] + 1e-9]
        if not breached:
            result.loc[open_tickers] = allocation
            break
        for category in breached:
            members = [ticker for ticker in open_tickers if category_of[ticker] == category]
            result.loc[members] = allocation.loc[members] * cap_of[category] / category_totals[category]
            remaining_exposure -= cap_of[category]
            open_categories.remove(category)
    return result.to_dict()


def _apply_group_cap(weights: dict[str, float], members: set[str], cap: float) -> dict[str, float]:
    """Limita o peso total de um grupo; o excesso vai para os restantes ETFs (ou cash se não houver)."""
    result = dict(weights)
    group_weight = sum(weight for ticker, weight in result.items() if ticker in members)
    if group_weight <= cap + 1e-9:
        return result
    excess = group_weight - cap
    for ticker in members.intersection(result):
        result[ticker] *= cap / group_weight
    others_weight = sum(weight for ticker, weight in result.items() if ticker not in members)
    if others_weight > 0:
        for ticker in [ticker for ticker in result if ticker not in members]:
            result[ticker] += excess * result[ticker] / others_weight
    return result


def _portfolio_volatility(weights: dict[str, float], end_date: pd.Timestamp, lookback: int) -> float:
    """Volatilidade anualizada ex-ante com a matriz de covariância dos últimos `lookback` dias úteis."""
    tickers = [ticker for ticker, weight in weights.items() if weight > 0]
    if not tickers:
        return 0.0
    calendar = pd.bdate_range(end=end_date, periods=lookback + 1)
    returns = _load_price_returns(tickers, calendar).iloc[1:]
    weight_vector = pd.Series(weights).reindex(tickers)
    variance = float(weight_vector @ returns.cov() @ weight_vector) * 252
    return max(variance, 0.0) ** 0.5


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
    score_smoothing_cycles: int = SCORE_SMOOTHING_CYCLES,
    max_etfs_per_category: int | None = MAX_ETFS_PER_CATEGORY,
    high_beta_cap: float | None = HIGH_BETA_CAP,
    vol_filter_mode: str | None = VOL_FILTER_MODE,
    early_target_volatility: float | None = EARLY_TARGET_VOLATILITY,
    early_fractional_kelly: float | None = EARLY_FRACTIONAL_KELLY,
    early_sizing_cycles: int = EARLY_SIZING_CYCLES,
    regime_filter: str = REGIME_FILTER,
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
    if score_smoothing_cycles not in (1, 2):
        raise ValueError("score_smoothing_cycles must be 1 or 2")
    if vol_filter_mode not in (None, "exclude", "halve"):
        raise ValueError("vol_filter_mode must be None, 'exclude' or 'halve'")
    if max_etfs_per_category is not None and max_etfs_per_category < 1:
        raise ValueError("max_etfs_per_category must be positive when provided")
    if regime_filter not in ("vix_sma200", "legacy", "none"):
        raise ValueError("regime_filter must be 'vix_sma200', 'legacy' or 'none'")

    df = pd.read_csv(_history_path())
    df["date"] = pd.to_datetime(df["date"])

    required_columns = {"date", "etf", "score", "ret_1d", "vol_21"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    df_clean = df.dropna(subset=["score", "ret_1d"]).copy()
    # Só dias úteis contam como datas de sinal (ver data_quality_weekend_fix.md).
    df_clean = df_clean[df_clean["date"].dt.dayofweek < 5]
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
    # Retornos vêm dos preços diários finais num calendário contínuo de dias úteis,
    # não do ret_1d do histórico de scores (que tinha fins de semana repetidos e falhas).
    business_days = pd.bdate_range(trading_dates[0], trading_dates[-1])
    benchmark_data = _load_benchmark_data(business_days)
    price_returns = _load_price_returns(sorted(df_clean["etf"].unique()), business_days)
    cycles = []
    current_weights: dict[str, float] = {}
    holding_age: dict[str, int] = {}
    asset_returns_history: dict[str, list[float]] = {}
    portfolio_value = INITIAL_CAPITAL
    previous_cycle_scores: dict[str, float] = {}
    previous_exposure: float | None = None
    # Equity curve diária ancorada no capital inicial (dia 0 = data do 1.º sinal),
    # para que o MaxDD inclua a perda entre o capital inicial e o fim do 1.º ciclo.
    equity_curve: list[dict] = []

    cycle_span = rebalance_every * rebalance_cycle_interval
    for cycle_number, start_index in enumerate(range(0, len(trading_dates) - 1, cycle_span), start=1):
        start_date = trading_dates[start_index]
        end_index = min(start_index + cycle_span + 1, len(trading_dates))
        # The signal is observed at start_date; returns begin on the next date.
        cycle_dates = list(business_days[(business_days > start_date) & (business_days <= trading_dates[end_index - 1])])
        if not cycle_dates:
            continue
        day_scores = df_clean[df_clean["date"] == start_date].copy()
        day_scores["score_raw"] = day_scores["score_final"]
        if score_smoothing_cycles == 2:
            # score_suave = média de score_final(t) e score_final(t-1); sem t-1 usa t.
            day_scores["score_final"] = (
                day_scores["score_raw"] + day_scores["etf"].map(previous_cycle_scores).fillna(day_scores["score_raw"])
            ) / 2
        previous_cycle_scores = day_scores.set_index("etf")["score_raw"].to_dict()
        # Filtro de volatilidade: quartil superior de vol_21 do universo na data do ranking.
        vol_threshold = day_scores["vol_21"].abs().quantile(VOL_FILTER_QUANTILE)
        high_vol_tickers = set(day_scores.loc[day_scores["vol_21"].abs() > vol_threshold, "etf"]) if vol_filter_mode else set()
        category_of = {ticker: etf_metadata.get(ticker, {}).get("category_id", "other") for ticker in day_scores["etf"]}
        ranked = day_scores.sort_values("score_final", ascending=False)
        if vol_filter_mode == "exclude":
            ranked = ranked[~ranked["etf"].isin(high_vol_tickers)]
        if max_etfs_per_category is not None:
            category_counts: dict[str, int] = {}
            keep = []
            for ticker in ranked["etf"]:
                category = category_of.get(ticker, "other")
                keep.append(category_counts.get(category, 0) < max_etfs_per_category)
                category_counts[category] = category_counts.get(category, 0) + keep[-1]
            ranked = ranked[keep]
        ranking_selection = ranked.head(max_positions)
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
        score_lookup = day_scores.set_index("etf")["score_final"].to_dict()
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
        if max_etfs_per_category is not None and current_holdings:
            held_counts: dict[str, int] = {}
            for ticker in retained_holdings:
                held_counts[category_of.get(ticker, "other")] = held_counts.get(category_of.get(ticker, "other"), 0) + 1
            allowed_candidates = []
            for ticker in new_candidates:
                category = category_of.get(ticker, "other")
                if held_counts.get(category, 0) < max_etfs_per_category:
                    allowed_candidates.append(ticker)
                    held_counts[category] = held_counts.get(category, 0) + 1
            new_candidates = allowed_candidates
        if max_new_positions is not None and current_holdings:
            new_candidates = new_candidates[:max_new_positions]
        target_holdings = retained_holdings | set(new_candidates[:available_slots])
        if not current_holdings:
            target_holdings = selected_holdings
        selection = day_scores[day_scores["etf"].isin(target_holdings)].copy()
        if len(selection) != len(target_holdings) or selection["score_v3"].isna().any():
            continue

        benchmark_row = benchmark_data.loc[start_date]
        benchmark_close = benchmark_row["close"]
        benchmark_sma200 = benchmark_row["sma200"]
        vix_level = benchmark_row.get("vix", float("nan"))
        # Sem VIX (ou VIX obsoleto) classify_regime usa só a SMA200.
        market_regime = classify_regime(benchmark_close, benchmark_sma200, vix_level)
        if regime_filter == "vix_sma200":
            exposure = regime_exposure(market_regime)
        elif regime_filter == "legacy":
            # Binário anterior: investido se VWCE > SMA200 e VIX < 28 (BULL ou NEUTRAL).
            exposure = 1.0 if market_regime in ("BULL", "NEUTRAL") else 0.0
        else:
            exposure = 1.0
        volatility = selection.set_index("etf")["vol_21"].abs().replace(0, float("nan"))
        volatility = volatility.replace([float("inf"), float("-inf")], float("nan"))
        volatility = volatility.fillna(volatility.median()).fillna(1.0)
        score_strength = (selection.set_index("etf")["score_final"] / selection["score_final"].max()).clip(0.5, 1.0)
        early_cycle = len(cycles) < early_sizing_cycles
        fractional_kelly = early_fractional_kelly if early_cycle and early_fractional_kelly is not None else FRACTIONAL_KELLY
        kelly_multiplier = {}
        for ticker in target_holdings:
            history = asset_returns_history.get(ticker, [])
            hit_rate = sum(value > 0 for value in history) / len(history) if history else 0.5
            kelly_fraction = fractional_kelly * max(0.0, 2 * hit_rate - 1)
            kelly_multiplier[ticker] = 0.5 + kelly_fraction
        raw_weights = (TARGET_VOLATILITY / volatility) * score_strength
        raw_weights = raw_weights * pd.Series(kelly_multiplier)
        if vol_filter_mode == "halve":
            raw_weights = raw_weights * pd.Series({ticker: 0.5 if ticker in high_vol_tickers else 1.0 for ticker in raw_weights.index})
        target_weights = _capped_weights(raw_weights, etf_metadata, exposure)
        if high_beta_cap is not None:
            high_beta_members = {
                ticker for ticker in target_weights
                if ticker in HIGH_BETA_TICKERS or category_of.get(ticker) in HIGH_BETA_CATEGORIES
            }
            target_weights = _apply_group_cap(target_weights, high_beta_members, high_beta_cap)
        estimated_portfolio_volatility = _portfolio_volatility(target_weights, start_date, VOL_TARGET_LOOKBACK_DAYS)
        vol_target_scale = 1.0
        if early_cycle and early_target_volatility is not None and estimated_portfolio_volatility > 0:
            vol_target_scale = min(1.0, early_target_volatility / estimated_portfolio_volatility)
            target_weights = {ticker: weight * vol_target_scale for ticker, weight in target_weights.items()}
        weight_keys = set(current_weights) | set(target_weights)
        max_weight_deviation = max(
            (abs(current_weights.get(ticker, 0.0) - target_weights.get(ticker, 0.0)) for ticker in weight_keys),
            default=1.0,
        )
        # Mudança da exposição do regime (ou carteira acima do teto) obriga a rebalancear,
        # mesmo que nenhum peso individual se desvie mais do que o threshold.
        regime_forced_rebalance = bool(current_weights) and (
            (previous_exposure is not None and exposure != previous_exposure)
            or sum(current_weights.values()) > exposure + 1e-6
        )
        rebalance_executed = not current_weights or max_weight_deviation >= rebalance_threshold or regime_forced_rebalance
        active_weights = target_weights if rebalance_executed else current_weights.copy()
        active_holdings = {ticker for ticker, weight in active_weights.items() if weight > 0}
        # Cash conta como posição: passar de 100% cash para 60% investido é 60% de turnover.
        current_cash = max(0.0, 1 - sum(current_weights.values()))
        target_cash = max(0.0, 1 - sum(target_weights.values()))
        turnover = (
            1
            - sum(min(current_weights.get(ticker, 0.0), target_weights.get(ticker, 0.0)) for ticker in weight_keys)
            - min(current_cash, target_cash)
            if rebalance_executed
            else 0.0
        )
        friction_cost_rate = transaction_cost * turnover
        gross_daily_returns = price_returns.reindex(index=cycle_dates, columns=sorted(active_holdings))
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
                "score_final": (round(float(selection.loc[selection["etf"] == ticker, "score_raw"].iloc[0]), 4) if ticker in target_holdings else None),
                "score_ranking": (round(float(selection.loc[selection["etf"] == ticker, "score_final"].iloc[0]), 4) if ticker in target_holdings else None),
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
        if not equity_curve:
            equity_curve.append({"date": start_date, "equity": INITIAL_CAPITAL, "point": "initial_capital"})
        # Custos debitados no início do ciclo, depois composição diária (fecha em portfolio_value).
        equity_after_cost = portfolio_value_before * (1 - friction_cost_rate)
        equity_curve.append({"date": start_date, "equity": equity_after_cost, "point": "after_costs"})
        daily_equity = equity_after_cost * (1 + weighted_daily_returns).cumprod()
        equity_curve.extend(
            {"date": date, "equity": float(value), "point": "daily"} for date, value in daily_equity.items()
        )
        equity_curve_so_far = pd.Series([point["equity"] for point in equity_curve])
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
                "ranking_top": ",".join(ranking_selection["etf"]),
                "allocation_details": json.dumps(allocation_details, ensure_ascii=False),
                "market_regime": market_regime,
                "regime": market_regime,
                "benchmark_close": benchmark_close,
                "benchmark_sma200": benchmark_sma200,
                "vix_level": vix_level,
                "vix_available": bool(pd.notna(vix_level)),
                "regime_filter": regime_filter,
                "exposure": exposure,
                "regime_forced_rebalance": regime_forced_rebalance,
                "invested_weight": float(sum(active_weights.values())),
                "estimated_portfolio_volatility": estimated_portfolio_volatility,
                "vol_target_scale": vol_target_scale,
                "high_vol_threshold": float(vol_threshold),
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
                "drawdown": portfolio_value / equity_curve_so_far.max() - 1,
                "max_drawdown_to_date": float((equity_curve_so_far / equity_curve_so_far.cummax() - 1).min()),
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
                "score_smoothing_cycles": score_smoothing_cycles,
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
        previous_exposure = exposure
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
    # MaxDD sobre a equity curve diária completa, a partir dos €10.000 iniciais.
    # (Antes era medido só entre valores de fim de ciclo, ignorando o capital inicial.)
    equity_df = pd.DataFrame(equity_curve)
    equity_df["drawdown"] = equity_df["equity"] / equity_df["equity"].cummax() - 1
    max_drawdown = float(equity_df["drawdown"].min())
    cycle_end_equity = pd.concat([pd.Series([INITIAL_CAPITAL]), portfolio_perf["portfolio_value"]], ignore_index=True)
    max_drawdown_cycle_end = float((cycle_end_equity / cycle_end_equity.cummax() - 1).min())
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
        "max_drawdown_cycle_end": max_drawdown_cycle_end,
        "max_drawdown_method": "daily_equity_from_initial_capital",
        "cumulative_return": cumulative_return,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "jensen_alpha_annual": jensen_alpha_annual,
        "beta": beta,
        "transaction_cost_per_round": transaction_cost,
        "risk_free_rate_annual": risk_free_rate_annual,
        "bull_cycles": int((portfolio_perf["market_regime"] == "BULL").sum()),
        "neutral_cycles": int((portfolio_perf["market_regime"] == "NEUTRAL").sum()),
        "bear_cycles": int((portfolio_perf["market_regime"].isin(["BEAR", "STRESS"])).sum()),
        "stress_cycles": int((portfolio_perf["market_regime"] == "STRESS").sum()),
        "average_exposure": portfolio_perf["exposure"].mean(),
        "average_invested_weight": portfolio_perf["invested_weight"].mean(),
        "regime_filter": regime_filter,
        "vix_neutral_level": VIX_NEUTRAL_LEVEL,
        "regime_exposure_rules": json.dumps(REGIME_EXPOSURE),
        "vix_available_cycles": int(portfolio_perf["vix_available"].sum()),
        "rebalance_threshold": rebalance_threshold,
        "cost_saving_cycles": cost_saving_cycles,
        "max_positions": max_positions,
        "min_holding_cycles": min_holding_cycles,
        "max_new_positions": max_new_positions,
        "min_sell_score": min_sell_score,
        "rebalance_cycle_interval": rebalance_cycle_interval,
        "policy_name": policy_name,
        "score_smoothing_cycles": score_smoothing_cycles,
        "target_volatility": TARGET_VOLATILITY,
        "fractional_kelly": FRACTIONAL_KELLY,
        "max_etfs_per_category": max_etfs_per_category,
        "high_beta_cap": high_beta_cap,
        "vol_filter_mode": vol_filter_mode,
        "early_target_volatility": early_target_volatility,
        "early_fractional_kelly": early_fractional_kelly,
        "early_sizing_cycles": early_sizing_cycles,
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
    print(f"Max Drawdown da estratégia (diário, desde €{INITIAL_CAPITAL:,.0f}): {max_drawdown * 100:.2f}% | só fim de ciclo: {max_drawdown_cycle_end * 100:.2f}%")
    print(f"Rentabilidade acumulada: {cumulative_return * 100:.2f}%")
    print(f"Sharpe / Sortino: {sharpe_ratio:.2f} / {sortino_ratio:.2f}")
    print(f"Alpha de Jensen anualizado / Beta: {jensen_alpha_annual * 100:.2f}% / {beta:.2f}")
    print(
        f"Regime ({regime_filter}): {summary['bull_cycles']} BULL / {summary['neutral_cycles']} NEUTRAL / "
        f"{summary['bear_cycles']} BEAR+STRESS | exposição máx. média {summary['average_exposure'] * 100:.1f}% · "
        f"investido médio {summary['average_invested_weight'] * 100:.1f}% · VIX disponível em {summary['vix_available_cycles']}/{len(portfolio_perf)} ciclos"
    )
    print(f"Ponderação: alvo de volatilidade {TARGET_VOLATILITY * 100:.0f}% + Kelly fracionário {FRACTIONAL_KELLY:.2f} + caps por categoria")
    print(
        f"Construção: máx. {max_etfs_per_category or 'sem limite'} ETFs/categoria · "
        f"cap alto beta {f'{high_beta_cap * 100:.0f}%' if high_beta_cap is not None else 'desligado'} · "
        f"filtro vol_21 top {100 - VOL_FILTER_QUANTILE * 100:.0f}%: {vol_filter_mode or 'desligado'} · "
        f"vol-target inicial {f'{early_target_volatility * 100:.0f}%' if early_target_volatility is not None else 'desligado'}"
    )
    print(
        f"Regime: BULL = VWCE > SMA200 e VIX < {VIX_NEUTRAL_LEVEL:.0f} (100%) · NEUTRAL = VIX {VIX_NEUTRAL_LEVEL:.0f}–{VIX_STRESS_LEVEL:.0f} (máx. 60%) · "
        f"STRESS = VIX ≥ {VIX_STRESS_LEVEL:.0f} e BEAR = VWCE < SMA200 (cash)"
    )
    print(f"Threshold de rebalanceamento: {rebalance_threshold * 100:.1f}% | {cost_saving_cycles} ciclos sem rotação")

    if persist_output:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        portfolio_perf.to_csv(output_path, index=False)
        equity_path = output_path.with_name(f"{output_path.stem}_equity.csv")
        equity_df.to_csv(equity_path, index=False)
        print(f"Equity curve diária gravada em {equity_path}")
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