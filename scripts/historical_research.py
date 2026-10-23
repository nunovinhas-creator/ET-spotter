#!/usr/bin/env python3
"""Investigação retrospetiva V3 (SEM XGBoost). Isolada da simulação oficial.

Sinais calculados exclusivamente com barras disponíveis no fecho de D.
Ordens executadas na abertura de D+1, com custos por lado negociado.
NÃO é um backtest OOS do ensemble 60/40, nem prova de vantagem futura.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compute_metrics import compute_metrics
from compute_score import compute_scores
from market_regime import classify_regime, regime_exposure
from run_simulation import _capped_weights, _load_etf_metadata

INITIAL = 10000.0
REBALANCE = 42
MAX_POSITIONS = 7
COST_SIDE_BPS = 15.0
FEATURES = ("ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_126d", "ret_252d",
            "vol_21", "sharpe_63", "rsi", "adx", "rs_positive", "rs_mom_21",
            "rs_mom_63", "calmar_63", "trend_sma", "macd_bullish",
            "above_sma200", "drawdown", "macd", "macd_signal")


def download_prices(destination: Path, start: str) -> dict:
    """Pesquisa histórica só no diretório de investigação, sem tocar em data/daily."""
    import yfinance as yf
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config/etfs.json").read_text())
    tickers = sorted({e["ticker"] for c in cfg["categories"] for e in c["etfs"]})
    symbols = sorted(set(tickers + ["SPY", "VWCE.DE", "^VIX"]))
    destination.mkdir(parents=True, exist_ok=True)
    failures = []
    saved = []
    for offset in range(0, len(symbols), 12):
        batch = symbols[offset:offset + 12]
        try:
            raw = yf.download(batch, start=start, auto_adjust=True, group_by="ticker",
                              progress=False, threads=True, timeout=25)
        except Exception as exc:
            failures.extend(batch)
            print(f"[WARN] Lote {offset}: {exc}", file=sys.stderr)
            continue
        for ticker in batch:
            try:
                sub = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
                sub = sub.rename(columns=str.lower)
                sub = sub[[c for c in ("open", "high", "low", "close", "volume") if c in sub]]
                sub = sub.dropna(subset=["open", "close"]).sort_index()
                sub.index = pd.to_datetime(sub.index).tz_localize(None).normalize()
                sub = sub[~sub.index.duplicated(keep="last")]
                if len(sub) < 200:
                    raise ValueError(f"apenas {len(sub)} barras")
                sub.to_csv(destination / (("VIX" if ticker == "^VIX" else ticker) + ".csv"),
                           index_label="Date")
                saved.append(ticker)
            except Exception as exc:
                failures.append(ticker)
                print(f"[WARN] {ticker}: {exc}", file=sys.stderr)
    return {"requested": len(symbols), "saved": len(saved), "failed": failures,
            "start": start, "provider": "Yahoo via yfinance (auto_adjust=True)"}


def read_ohlc(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index).normalize()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    for col in ("open", "close"):
        if col not in frame or (frame[col].dropna() <= 0).any():
            raise ValueError(f"{path.name}: preços {col} inválidos")
    return frame


def calculate_metrics(equity: pd.Series, benchmark: pd.Series) -> dict:
    if len(equity) < 3 or not equity.index.equals(benchmark.index):
        raise ValueError("Séries insuficientes ou calendários diferentes")
    ret = equity.pct_change().dropna()
    bench = benchmark.pct_change().dropna()
    years = len(ret) / 252.0
    rf_daily = (1.03 ** (1 / 252)) - 1
    def stats(nav, r):
        sd = float(r.std(ddof=1))
        downside = float(np.sqrt(np.minimum(r-rf_daily, 0).pow(2).mean()))
        return {"return": float(nav.iloc[-1]/nav.iloc[0]-1),
                "cagr": float((nav.iloc[-1]/nav.iloc[0]) ** (1/years)-1),
                "max_drawdown": float((nav/nav.cummax()-1).min()),
                "volatility": sd*math.sqrt(252),
                "sharpe": (float(r.mean())-rf_daily)/sd*math.sqrt(252) if sd>0 else None,
                "sortino": (float(r.mean())-rf_daily)/downside*math.sqrt(252) if downside>0 else None}
    return {"strategy": stats(equity, ret), "vwce": stats(benchmark, bench),
            "active_cagr_pp": 100*(stats(equity, ret)["cagr"]-stats(benchmark, bench)["cagr"]),
            "sessions": len(ret)}


def snapshot_at(day: pd.Timestamp, metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sem tickers anteriores à cotação, sem barras com mais de 7 dias."""
    rows = []
    for ticker, frame in metrics.items():
        if ticker in ("SPY", "VWCE.DE", "VIX"):
            # VWCE entra se estiver listado na configuração, tratado mais abaixo.
            if ticker != "VWCE.DE":
                continue
        available = frame.loc[:day]
        if len(available) < 253:
            continue
        row = available.iloc[-1]
        if (day - available.index[-1]).days > 7:
            continue
        if not np.isfinite(row.get("vol_21", np.nan)) or row["vol_21"] <= 0:
            continue
        item = {"etf": ticker}
        item.update({k: row.get(k, np.nan) for k in FEATURES})
        rows.append(item)
    return pd.DataFrame(rows)


def construct_weights(day: pd.Timestamp, metrics: dict[str, pd.DataFrame],
                      metadata: dict, prior_raw: dict[str, float],
                      held: dict[str, float], hold_cycles: dict[str, int]) -> tuple[dict, dict]:
    snap = snapshot_at(day, metrics)
    if len(snap) < 7:
        return {}, {"status": "insufficient_universe", "available": len(snap)}
    snap = compute_scores(snap)
    snap["rank_score"] = (snap["score_v3"] + snap["etf"].map(prior_raw).fillna(snap["score_v3"])) / 2
    prior_raw.update(snap.set_index("etf")["score_v3"].to_dict())
    vol_cutoff = snap["vol_21"].quantile(.75)
    ranking = snap.loc[snap["vol_21"] <= vol_cutoff].sort_values(
        ["rank_score", "etf"], ascending=[False, True])
    selected = []
    by_category = {}
    for ticker in ranking["etf"]:
        category = metadata.get(ticker, {}).get("category_id", "other")
        if by_category.get(category, 0) < 2:
            selected.append(ticker)
            by_category[category] = by_category.get(category, 0) + 1
        if len(selected) == MAX_POSITIONS:
            break
    if len(selected) < MAX_POSITIONS:
        return {}, {"status": "insufficient_categories", "available": len(selected)}
    lookup = snap.set_index("etf")["rank_score"].to_dict()
    existing = {t for t, w in held.items() if w > 1e-9}
    forced = {t for t in existing if t not in lookup or lookup[t] < .40}
    retained = existing - forced
    if len(retained) > MAX_POSITIONS:
        retained = set(sorted(retained, key=lambda t: lookup.get(t, 0), reverse=True)[:MAX_POSITIONS])
    new = []
    counts = {}
    for t in retained:
        c = metadata.get(t, {}).get("category_id", "other")
        counts[c] = counts.get(c, 0) + 1
    for t in selected:
        if t in existing or len(new) >= (MAX_POSITIONS if not existing else 2):
            continue
        c = metadata.get(t, {}).get("category_id", "other")
        if counts.get(c, 0) >= 2:
            continue
        new.append(t)
        counts[c] = counts.get(c, 0) + 1
        if len(retained) + len(new) >= MAX_POSITIONS:
            break
    names = sorted(retained | set(new)) if existing else selected
    if not names:
        return {}, {"status": "cash", "available": len(snap)}
    selection = snap.set_index("etf").loc[names]
    vol = selection["vol_21"].clip(lower=.00001)
    strength = (selection["rank_score"]/selection["rank_score"].max()).clip(.5, 1)
    raw = strength / vol
    weights = _capped_weights(raw, metadata, 1.0)
    return weights, {"status": "selected", "available": len(snap),
                     "positions": names, "high_vol_cutoff": float(vol_cutoff)}


def backtest(price_root: Path, start: str, end: str, side_bps: float) -> tuple[pd.DataFrame, dict]:
    if side_bps < 0:
        raise ValueError("Custos negativos")
    metadata = _load_etf_metadata()
    raw: dict[str, pd.DataFrame] = {}
    for ticker in sorted(set(metadata) | {"VWCE.DE", "SPY", "VIX"}):
        path = price_root / f"{ticker}.csv"
        if path.exists():
            try:
                raw[ticker] = read_ohlc(path)
            except ValueError as exc:
                print(f"[WARN] {exc}")
    if not {"VWCE.DE", "SPY"}.issubset(raw):
        raise ValueError("VWCE.DE e SPY obrigatórios")
    bench = raw["VWCE.DE"]
    bench["sma200"] = bench["close"].rolling(200, min_periods=200).mean()
    dates = bench.loc[start:end].index
    dates = dates[dates.isin(bench.index)]
    if len(dates) < 50:
        raise ValueError("Período sem pelo menos 50 sessões VWCE")
    spy = raw["SPY"]["close"]
    metrics = {ticker: compute_metrics(df, spy_close=spy) for ticker, df in raw.items()
               if ticker not in ("SPY", "VIX")}
    nav = INITIAL
    shares: dict[str, float] = {}
    cash = INITIAL
    held: dict[str, float] = {}
    hold_cycles: dict[str, int] = {}
    prior_scores: dict[str, float] = {}
    book = []
    rebalance_count, cost_total = 0, 0.0
    first_decision_day = None
    first_decision_cost = 0.0
    # Fecho de D-1 -> ordem executada na abertura de D.
    for i, day in enumerate(dates):
        if day not in bench.index or not np.isfinite(bench.loc[day, "open"]):
            raise ValueError("Benchmark incompleto")
        price_now = {}
        stale = []
        for ticker in set(shares) | set(metadata):
            if ticker not in raw:
                continue
            past = raw[ticker].loc[:day, "open"].dropna()
            if past.empty or (day - past.index[-1]).days > 7:
                if ticker in shares:
                    stale.append(ticker)
                continue
            price_now[ticker] = float(past.iloc[-1])
        if stale:
            raise ValueError(f"Preços não disponíveis para posições {stale} em {day.date()}")
        nav = cash + sum(qty * price_now[t] for t, qty in shares.items())
        cost = 0.0
        event = "hold"
        if i > 0 and (i - 1) % REBALANCE == 0:
            signal_day = dates[i-1]
            proposed, detail = construct_weights(signal_day, metrics, metadata, prior_scores,
                                                 held, hold_cycles)
            vix_series = raw.get("VIX")
            vix = None
            if vix_series is not None:
                v = vix_series.loc[:signal_day, "close"].dropna()
                if not v.empty and (signal_day - v.index[-1]).days <= 7:
                    vix = float(v.iloc[-1])
            bclose = float(bench.loc[signal_day, "close"])
            sma = float(bench.loc[signal_day, "sma200"])
            regime = classify_regime(bclose, sma, vix)
            # Só iniciar o teste quando a regra SMA200 podia de facto ser calculada.
            # Antes desse ponto, ficar em cash é falta de histórico e não uma decisão.
            if (first_decision_day is None and detail.get("status") == "selected"
                    and np.isfinite(sma) and regime != "UNKNOWN"):
                first_decision_day = day
            exposure = regime_exposure(regime)
            target = {t: w * exposure for t, w in proposed.items()}
            actual = {t: qty*price_now[t]/nav for t, qty in shares.items()}
            change = max([abs(target.get(t, 0)-actual.get(t, 0))
                          for t in set(actual) | set(target)] or [0])
            forced = sum(actual.values()) > exposure + 1e-8
            if not shares or change >= .12 or forced:
                missing_open = [t for t in target if t not in price_now]
                if missing_open:
                    raise ValueError(f"Sem abertura executável: {missing_open}")
                traded = sum(abs(target.get(t, 0)-actual.get(t, 0))
                             for t in set(actual) | set(target))
                cost = nav * traded * (side_bps/10000)
                nav -= cost
                cost_total += cost
                if day == first_decision_day:
                    first_decision_cost = cost
                shares = {t: nav*w/price_now[t] for t, w in target.items() if w > 1e-8}
                cash = nav * (1-sum(target.values()))
                rebalance_count += 1
                event = f"rebalance:{regime}"
            held = {t: w for t, w in target.items() if w > 0}
            hold_cycles = {t: hold_cycles.get(t, 0)+1 for t in held}
        benchmark_equity = INITIAL * float(bench.loc[day, "open"])/float(bench.loc[dates[0], "open"])
        book.append({"date": day, "equity": nav, "vwce_equity": benchmark_equity,
                     "cost": cost, "cash": cash, "event": event,
                     "positions": json.dumps(shares)})
    equity = pd.DataFrame(book).set_index("date")
    if first_decision_day is None:
        raise ValueError("Nenhum sinal V3 elegível; não produzir comparação enganadora com cash de warm-up")
    evaluation = equity.loc[first_decision_day:].copy()
    # O capital de abertura é o valor ANTES da primeira execução: inclui o
    # impacto do custo inicial nas observações seguintes da curva de NAV.
    evaluation.loc[first_decision_day, "equity"] += first_decision_cost
    summary = calculate_metrics(evaluation["equity"], evaluation["vwce_equity"])
    # Anos civis com retornos calculados pela composição das alterações diárias,
    # preservando as passagens de 31/12 para a sessão seguinte.
    day_returns = evaluation[["equity", "vwce_equity"]].pct_change().fillna(0.0)
    annual = {}
    for year, group in day_returns.groupby(day_returns.index.year):
        dates_year = evaluation.loc[group.index]
        annual[str(year)] = {
            "sessions": int(len(group)),
            "first_session": group.index[0].strftime("%Y-%m-%d"),
            "last_session": group.index[-1].strftime("%Y-%m-%d"),
            "strategy_return": float((1 + group["equity"]).prod() - 1),
            "vwce_return": float((1 + group["vwce_equity"]).prod() - 1),
            "strategy_max_drawdown_in_year": float((dates_year["equity"] / dates_year["equity"].cummax() - 1).min()),
            "vwce_max_drawdown_in_year": float((dates_year["vwce_equity"] / dates_year["vwce_equity"].cummax() - 1).min()),
        }
    summary["annual_breakdown"] = annual
    summary.update({"status": "RETROSPECTIVE_V3_ONLY_NOT_OUT_OF_SAMPLE",
                    "model": "score_v3_1_no_xgboost",
                    "rebalance_days": REBALANCE, "rebalance_count": rebalance_count,
                    "warmup_sessions_excluded": int((equity.index < first_decision_day).sum()),
                    "first_executable_decision": first_decision_day.strftime("%Y-%m-%d"),
                    "invested_sessions": int((evaluation["cash"] < evaluation["equity"] - 0.01).sum()),
                    "cost_side_bps": side_bps, "cost_eur": cost_total,
                    "start": evaluation.index.min().strftime("%Y-%m-%d"),
                    "loaded_data_from": equity.index.min().strftime("%Y-%m-%d"),
                    "end": equity.index.max().strftime("%Y-%m-%d"),
                    "limitations": [
                        "Universo actual de ETFs: enviesamento de sobrevivência possível",
                        "Cotações de mercados/moedas diferentes sem conversão cambial: NÃO EXECUTÁVEL",
                        "Política histórica aproximada: não equivale ao ensemble oficial 60/40",
                        "Parâmetros selecionados em 2026: passado NÃO é amostra intocada",
                        "VWCE só comparado onde existe histórico; sem proxy não se cobre toda a queda de 2020",
                        "Execução idealizada na abertura seguinte; custos 15bps por lado, sujeitos a stress"
                    ]})
    return equity, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices-dir", type=Path, default=Path("data/research_prices"))
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default="2026-10-22")
    parser.add_argument("--download-from", default=None,
                        help="Descarrega histórico desde data YYYY-MM-DD, isolado de produção")
    parser.add_argument("--cost-side-bps", type=float, default=COST_SIDE_BPS)
    parser.add_argument("--output", type=Path, default=Path("research_results"))
    args = parser.parse_args()
    if args.download_from:
        report = download_prices(args.prices_dir, args.download_from)
        print(json.dumps(report, ensure_ascii=False))
    equity, report = backtest(args.prices_dir, args.start, args.end, args.cost_side_bps)
    args.output.mkdir(parents=True, exist_ok=True)
    equity.to_csv(args.output/"equity_v3_research.csv")
    (args.output/"audit_v3_research.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
