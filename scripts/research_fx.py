"""Conversão temporal estrita de cotações de ETFs e SPY para EUR.

O preço Yahoo é na moeda/unidade de negociação (incluindo GBP em pence/GBp).
A taxa EURXXX=X expressa quantas unidades de XXX custam 1 EUR. Para
obter preço EUR: preço_local * factor / EURXXX. Não inferir moeda de .L.
A série FX é alinhada para trás, nunca à frente; preços não disponíveis
ou FX demasiado antigo fazem a conversão falhar, não criam rentabilidade.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

QUOTE_MULTIPLIER = {
    "EUR": ("EUR", 1.0),
    "USD": ("USD", 1.0),
    "GBP": ("GBP", 1.0),
    "GBPENCE": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
    "GBPENNY": ("GBP", 0.01),
    "GBPENNIES": ("GBP", 0.01),
    "GBPenny": ("GBP", 0.01),
    "GBp": ("GBP", 0.01),
    "CHF": ("CHF", 1.0),
    "JPY": ("JPY", 1.0),
    "CAD": ("CAD", 1.0),
    "AUD": ("AUD", 1.0),
}


def normalize_currency(raw: str) -> tuple[str, float]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Moeda não identificada pelo fornecedor — conversão recusada")
    name = raw.strip()
    if name == "GBp":
        return "GBP", 0.01
    key = name.upper()
    # Yahoo GBX indica pence (1/100 GBP), não GBP!
    if key in ("GBX", "GBPENCE", "GBPENNY", "GBPENNIES"):
        return "GBP", 0.01
    if key not in ("EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD"):
        raise ValueError(f"Moeda sem conversor auditado: {raw!r}")
    return key, 1.0


def pair_symbol(currency: str) -> str | None:
    c, _ = normalize_currency(currency)
    return None if c == "EUR" else f"EUR{c}=X"


def load_manifest(root: Path) -> dict[str, dict]:
    path = root / "currencies.json"
    if not path.exists():
        raise FileNotFoundError(f"Falta {path}: não é permitido inferir moedas pelo sufixo do ticker")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("provider") != "yfinance_quote_metadata":
        raise ValueError("Origem de cotações não verificável")
    return doc["quotes"]


def load_daily(root: Path, ticker: str) -> pd.DataFrame:
    df = pd.read_csv(root / f"{ticker}.csv", index_col=0, parse_dates=True).sort_index()
    df.index = pd.to_datetime(df.index).normalize()
    if not {"open", "close"}.issubset(df.columns):
        raise ValueError(f"{ticker}: faltam open/close")
    if df.index.has_duplicates or (df[["open", "close"]].dropna() <= 0).any().any():
        raise ValueError(f"{ticker}: barras duplicadas ou preços não positivos")
    return df


def _asof_quote_fx(fx: pd.DataFrame, dates: pd.DatetimeIndex, field: str) -> pd.Series:
    series = fx[field].astype(float).dropna()
    if series.empty or (series <= 0).any():
        raise ValueError("Cotação cambial ausente ou inválida")
    positions = series.index.get_indexer(dates, method="ffill")
    if (positions < 0).any():
        raise ValueError("FX ainda não existia na data do ETF")
    observed = series.index.take(positions)
    age = (dates - observed).days
    if (age > 6).any():
        raise ValueError("FX desatualizado (> 6 dias): recusa de forward-fill longo")
    return pd.Series(series.iloc[positions].to_numpy(), index=dates)


def to_eur(raw: pd.DataFrame, currency: str, fx: pd.DataFrame | None = None) -> pd.DataFrame:
    native, scale = normalize_currency(currency)
    data = raw.copy()
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("Ordenação ou unicidade do calendário inválida")
    if native != "EUR":
        if fx is None or fx.empty:
            raise ValueError(f"Falta série EUR{native}=X")
    # Valor de abertura FX na abertura da sessão; fecho FX no fecho.
    # Para high/low construir limites conservadores de FX open/close para
    # preservar high >= open/close >= low, sem usar FX de dias futuros.
    q_open = 1.0 if native == "EUR" else _asof_quote_fx(fx, data.index, "open")
    q_close = 1.0 if native == "EUR" else _asof_quote_fx(fx, data.index, "close")
    q_min = np.minimum(q_open, q_close)
    q_max = np.maximum(q_open, q_close)
    data["open"] = data["open"].astype(float) * scale / q_open
    data["close"] = data["close"].astype(float) * scale / q_close
    if "high" in data:
        data["high"] = np.maximum.reduce([data["high"].astype(float) * scale / q_min,
                                           data["open"], data["close"]])
    if "low" in data:
        data["low"] = np.minimum.reduce([data["low"].astype(float) * scale / q_max,
                                         data["open"], data["close"]])
    if data[["open", "close"]].isna().any().any() or (data[["open", "close"]] <= 0).any().any():
        raise ValueError("Preço EUR não finito ou inválido")
    return data


def convert_folder(root: Path, tickers: list[str], *, fail_on_unknown: bool = True):
    """Devolve OHLC convertidos e auditoria. Não altera os CSV originais."""
    manifest = load_manifest(root)
    fx_cache: dict[str, pd.DataFrame] = {}
    converted = {}
    excluded: dict[str, str] = {}
    quotes = {}
    for ticker in sorted(set(tickers)):
        csv = root / f"{ticker}.csv"
        if not csv.exists():
            excluded[ticker] = "missing_price_file"
            continue
        raw_curr = manifest.get(ticker, {}).get("currency")
        if not raw_curr:
            excluded[ticker] = "unknown_quote_currency"
            continue
        try:
            native, scale = normalize_currency(raw_curr)
            pair = pair_symbol(raw_curr)
            if pair and pair not in fx_cache:
                fx_cache[pair] = load_daily(root, pair)
            euro = to_eur(load_daily(root, ticker), raw_curr, fx_cache.get(pair))
            # Guarda dura: saltos >50% num só dia em ETFs ajustados são muito
            # suspeitos (alternância GBP/GBp, splits mal ajustados, erros de feed).
            # Excluir toda a série; nunca deixar que um 100x dispare o CAGR.
            extreme = euro["close"].pct_change(fill_method=None).dropna()
            bad = extreme[extreme.abs() > .50]
            if not bad.empty:
                d = bad.index[0].strftime("%Y-%m-%d")
                raise ValueError(f"possible_currency_unit_or_split_error:{d}:return={bad.iloc[0]:+.1%}")
            converted[ticker] = euro
            quotes[ticker] = {"original_currency": raw_curr, "base_currency": native,
                              "unit_scale": scale, "fx_pair": pair}
        except (ValueError, KeyError, FileNotFoundError) as exc:
            excluded[ticker] = str(exc)
    if fail_on_unknown and excluded:
        raise ValueError(f"FX/cobertura rejeitada ({len(excluded)}): {excluded}")
    return converted, {"currency_basis": "EUR", "source": "yfinance_quote_metadata",
                       "converted_count": len(converted),
                       "excluded": excluded, "quotes": quotes}
