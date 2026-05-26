"""
Recolhe 2 anos de dados diários OHLCV para todos os símbolos via yfinance.
Guarda em data/daily/SYMBOL.csv (sobrescreve).

yfinance usa auto_adjust=True por omissão — preços já ajustados para splits e dividendos.
Este módulo valida explicitamente que os dados não contêm anomalias de ajustamento.
"""

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols

DATA_DAILY = Path("data/daily")

# Limiar para detectar movimento suspeito num único dia (possível split não ajustado)
SPLIT_THRESHOLD = 0.40


def validate_splits(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Detecta movimentos diários > 40% em valor absoluto.

    yfinance retorna preços já ajustados (auto_adjust=True), mas podem ocorrer:
      - Splits recentes ainda não reflectidos correctamente
      - Erros de dados pontuais (bad ticks)
      - Eventos reais extremos (circuit breaker, halt)

    Em caso de suspeita, emite aviso mas não descarta o dado — o analista decide.
    Adicionalmente, valida que open/high/low/close são internamente consistentes.
    """
    if df.empty:
        return df

    # 1. Movimentos diários suspeitos
    daily_ret = df["close"].pct_change(1).abs()
    suspicious = daily_ret[daily_ret > SPLIT_THRESHOLD].dropna()
    for date, val in suspicious.items():
        print(
            f"[AVISO] {symbol}: movimento de {val:.1%} em {date.date()}"
            " — possível split não ajustado ou erro de dados"
        )

    # 2. Coerência OHLC: high >= close >= low e high >= open >= low
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        bad_high  = df["high"]  < df[["open", "close"]].max(axis=1)
        bad_low   = df["low"]   > df[["open", "close"]].min(axis=1)
        n_bad = int((bad_high | bad_low).sum())
        if n_bad > 0:
            print(f"[AVISO] {symbol}: {n_bad} barra(s) com OHLC inconsistente (high<close ou low>close)")

    # 3. Preços nulos ou negativos
    zero_prices = (df["close"] <= 0).sum()
    if zero_prices > 0:
        print(f"[AVISO] {symbol}: {zero_prices} registo(s) com preço nulo/negativo — dados corrompidos")
        df = df[df["close"] > 0]

    return df


def fetch_daily(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Descarrega dados diários via yfinance com auto_adjust=True (preços ajustados).
    Valida anomalias de splits antes de retornar.
    """
    ticker = yf.Ticker(symbol)
    # auto_adjust=True (default): preços já corrigidos para dividendos e splits
    df = ticker.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"Sem dados para {symbol}")
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.columns = [c.lower() for c in df.columns]

    # Mantém apenas OHLCV base
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols]

    df = validate_splits(df, symbol)
    return df


def fetch_all_batch(symbols: list[str], period: str = "2y") -> tuple[dict, list[str]]:
    """
    Descarrega todos os símbolos numa única chamada yf.download().
    Mais eficiente e menos sujeito a throttling que chamadas individuais.
    Devolve (resultados_ok, lista_de_falhas).
    """
    raw = yf.download(
        tickers=symbols,
        period=period,
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False,
        threads=True,
    )

    results: dict[str, pd.DataFrame] = {}
    failed:  list[str]               = []

    for symbol in symbols:
        try:
            # MultiIndex: raw[SYMBOL][OHLCV] quando group_by="ticker" e n>1
            if len(symbols) == 1:
                df = raw.copy()
            else:
                if symbol not in raw.columns.get_level_values(0):
                    failed.append(symbol)
                    continue
                df = raw[symbol].copy()

            if df.empty or df.dropna(how="all").empty:
                failed.append(symbol)
                continue

            if df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            df.columns = [c.lower() for c in df.columns]
            cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
            df = df[cols].dropna(subset=["close"])

            if df.empty:
                failed.append(symbol)
                continue

            df = validate_splits(df, symbol)
            results[symbol] = df
        except Exception as e:
            failed.append(symbol)
            print(f"[ERRO batch] {symbol}: {e}", file=sys.stderr)

    return results, failed


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)

    symbols = get_all_symbols(cfg)
    print(f"[INFO] A descarregar {len(symbols)} símbolos via batch download...")

    results, failed = fetch_all_batch(symbols)

    # Fallback individual para falhas do batch
    if failed:
        print(f"[WARN] {len(failed)} símbolo(s) falharam no batch, tentando individualmente: {', '.join(failed)}")
        retry_failed = []
        for symbol in failed:
            try:
                df = fetch_daily(symbol)
                results[symbol] = df
                print(f"[OK fallback] {symbol} ({len(df)} registos)")
            except Exception as e:
                retry_failed.append(symbol)
                print(f"[ERRO] {symbol}: {e}", file=sys.stderr)
        failed = retry_failed

    # Persiste resultados
    ok_count = 0
    for symbol, df in results.items():
        df.to_csv(DATA_DAILY / f"{symbol}.csv")
        print(f"[OK] {symbol} ({len(df)} registos)")
        ok_count += 1

    # Log estruturado de falhas
    if failed:
        print(f"\n[SUMÁRIO] {ok_count}/{len(symbols)} símbolos descarregados com sucesso.")
        print(f"[FALHAS]  {len(failed)} símbolo(s) sem dados: {', '.join(sorted(failed))}", file=sys.stderr)
    else:
        print(f"\n[SUMÁRIO] {ok_count}/{len(symbols)} símbolos descarregados — sem falhas.")


if __name__ == "__main__":
    main()
