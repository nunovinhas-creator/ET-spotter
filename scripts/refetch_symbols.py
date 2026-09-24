"""
refetch_symbols.py — força o re-download completo do histórico diário de tickers.

Uso: python scripts/refetch_symbols.py AIGA.L PHPT.L [--period 2y]

Descarrega cada ticker individualmente (sem batch), funde com o histórico
existente se o Yahoo ainda devolver uma série curta, e valida o resultado:
sem datas duplicadas, sem fins de semana e sem buracos acima de 5 dias úteis.
Termina com código 1 se algum ticker continuar incompleto.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from fetch_daily import _existing_history, fetch_daily, is_truncated, merge_with_existing
from paths import DATA_DAILY

MAX_GAP_BUSINESS_DAYS = 5
MIN_ROWS = 400  # ~2 anos de negociação menos margem


def validate(df: pd.DataFrame) -> list[str]:
    problems = []
    if df.index.duplicated().any():
        problems.append("datas duplicadas")
    if (df.index.dayofweek >= 5).any():
        problems.append(f"{int((df.index.dayofweek >= 5).sum())} barras ao fim de semana")
    if len(df) < MIN_ROWS:
        problems.append(f"só {len(df)} barras (< {MIN_ROWS})")
    gaps = [
        (a.date(), b.date(), len(pd.bdate_range(a, b)) - 2)
        for a, b in zip(df.index[:-1], df.index[1:])
        if len(pd.bdate_range(a, b)) - 2 > MAX_GAP_BUSINESS_DAYS
    ]
    if gaps:
        problems.append(f"buracos > {MAX_GAP_BUSINESS_DAYS} dias úteis: {gaps}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--period", default="2y")
    args = parser.parse_args()

    failed = []
    for symbol in args.symbols:
        existing = _existing_history(symbol)
        df = fetch_daily(symbol, period=args.period)
        if is_truncated(df, existing):
            df = merge_with_existing(df, existing)
        df.index = pd.to_datetime(df.index).normalize()
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_csv(DATA_DAILY / f"{symbol}.csv")
        problems = validate(df)
        status = "OK" if not problems else "INCOMPLETO: " + "; ".join(problems)
        print(f"[{status}] {symbol}: {len(df)} barras {df.index.min().date()} → {df.index.max().date()}")
        if problems:
            failed.append(symbol)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
