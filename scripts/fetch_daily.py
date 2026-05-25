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


def main():
    cfg = load_config()
    DATA_DAILY.mkdir(parents=True, exist_ok=True)

    for symbol in get_all_symbols(cfg):
        try:
            df = fetch_daily(symbol)
            df.to_csv(DATA_DAILY / f"{symbol}.csv")
            print(f"[OK] {symbol} ({len(df)} registos)")
        except Exception as e:
            print(f"[ERRO] {symbol}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
