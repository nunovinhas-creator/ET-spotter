"""
repair_scores_history.py — corrige as datas de data/scores_history.csv.

Problema: compute_score.py gravava cada snapshot com a data do relógio. As
corridas de fim de semana (daily.yml corre todos os dias) e as horárias antes
do fetch diário repetiam a barra anterior com uma data nova. Por isso o ret_1d
de sexta aparecia também em sábado e domingo.

Reparação (idempotente):
  1. Para cada linha, identifica a barra diária real, procurando o ret_1d nas
     últimas barras do ETF até à data gravada.
  2. A data de mercado do snapshot é a barra mais frequente entre os seus ETFs.
     Sem correspondência (snapshots de barras parciais), usa o último dia útil
     até à data gravada.
  3. Por (data de mercado, ETF) mantém o snapshot gravado mais tarde, como o
     de-dup original (keep="last").
  4. close e ret_1d passam a vir dos preços finais diários no calendário de dias
     úteis: preço com forward-fill e retorno 0% em feriados. Scores e features
     ficam como foram calculados na altura.
"""
import numpy as np
import pandas as pd

from paths import DATA_DAILY, SCORES_HIST

MATCH_WINDOW_BARS = 6


def _load_closes(etfs: list[str]) -> dict[str, pd.DataFrame]:
    daily = {}
    for etf in etfs:
        path = DATA_DAILY / f"{etf}.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index).normalize()
            daily[etf] = df[~df.index.duplicated(keep="last")].sort_index()
    return daily


def _matched_bar_date(row: pd.Series, daily: dict[str, pd.DataFrame]) -> pd.Timestamp:
    df = daily.get(row["etf"])
    if df is None or pd.isna(row["ret_1d"]) or "ret_1d" not in df.columns:
        return pd.NaT
    candidates = df.loc[: row["stamp"], "ret_1d"].tail(MATCH_WINDOW_BARS)
    matches = candidates[np.isclose(candidates, row["ret_1d"], rtol=1e-6, atol=1e-9)]
    return matches.index[-1] if len(matches) else pd.NaT


def repair(hist: pd.DataFrame, daily: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    hist = hist.copy()
    hist["stamp"] = pd.to_datetime(hist["date"])
    hist["bar_date"] = hist.apply(_matched_bar_date, axis=1, daily=daily)

    market_dates = {}
    fallback_snapshots = 0
    for stamp, group in hist.groupby("stamp"):
        matched = group["bar_date"].dropna()
        if len(matched):
            market_dates[stamp] = matched.mode().max()
        else:
            market_dates[stamp] = stamp if stamp.dayofweek < 5 else stamp - pd.offsets.BDay(1)
            fallback_snapshots += 1
    hist["market_date"] = hist["stamp"].map(market_dates)

    repaired = (
        hist.sort_values("stamp")
        .drop_duplicates(subset=["market_date", "etf"], keep="last")
        .copy()
    )

    bdays = pd.bdate_range(repaired["market_date"].min() - pd.Timedelta(days=10), repaired["market_date"].max())
    for etf, idx in repaired.groupby("etf").groups.items():
        df = daily.get(etf)
        if df is None or "close" not in df.columns:
            continue
        close = df["close"].reindex(df.index.union(bdays)).ffill().reindex(bdays)
        ret = close.pct_change(fill_method=None)
        dates = repaired.loc[idx, "market_date"]
        priced = close.reindex(dates).notna().to_numpy()
        # 0% em dias sem negociação. Sem preço diário (ex.: ficheiro recriado com
        # menos histórico) mantém-se o close/ret_1d do snapshot, já com data corrigida.
        priced_idx = pd.Index(idx)[priced]
        repaired.loc[priced_idx, "close"] = close.reindex(dates[priced]).to_numpy()
        repaired.loc[priced_idx, "ret_1d"] = ret.fillna(0.0).reindex(dates[priced]).to_numpy()

    repaired["date"] = repaired["market_date"].dt.strftime("%Y-%m-%d")
    stats = {
        "rows_before": len(hist),
        "rows_after": len(repaired),
        "weekend_rows_before": int((hist["stamp"].dt.dayofweek >= 5).sum()),
        "weekend_rows_after": int((repaired["market_date"].dt.dayofweek >= 5).sum()),
        "redated_snapshots": int(sum(stamp != date for stamp, date in market_dates.items())),
        "snapshots_before": len(market_dates),
        "snapshots_after": repaired["market_date"].nunique(),
        "fallback_snapshots": fallback_snapshots,
        "missing_business_days": [
            d.strftime("%Y-%m-%d")
            for d in pd.bdate_range(repaired["market_date"].min(), repaired["market_date"].max())
            if d not in set(repaired["market_date"])
        ],
    }
    repaired = repaired.drop(columns=["stamp", "bar_date", "market_date"]).sort_values(["date", "etf"])
    return repaired.reset_index(drop=True), stats


def main() -> None:
    hist = pd.read_csv(SCORES_HIST)
    daily = _load_closes(sorted(hist["etf"].unique()))
    repaired, stats = repair(hist, daily)
    tmp = SCORES_HIST.with_suffix(".tmp")
    repaired.to_csv(tmp, index=False)
    tmp.replace(SCORES_HIST)
    for key, value in stats.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
