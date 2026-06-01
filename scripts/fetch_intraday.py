"""
Recolhe dados intradiários (60min) de todos os ETFs via yfinance.
Sem API key, sem limites práticos.
Guarda um CSV fixo por ETF em data/hourly/SYMBOL.csv (sobrescreve).

Inclui retry logic com exponencial backoff.
"""

import sys
import time
import random
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_config, get_all_symbols
from constants import INTRADAY_FETCH_PERIOD, INTRADAY_INTERVAL, MAX_API_RETRIES, RETRY_BASE_WAIT_TIME
from paths import DATA_INTRA as DATA_HOURLY


def fetch_intraday(symbol: str, period: str = INTRADAY_FETCH_PERIOD, interval: str = INTRADAY_INTERVAL) -> pd.DataFrame:
    """Recolhe dados intradiários via yfinance."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise RuntimeError(f"Sem dados para {symbol}")
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[cols]


def fetch_with_retry(symbol: str, max_retries: int = MAX_API_RETRIES) -> pd.DataFrame:
    """Recolhe dados com retry automático em caso de falha."""
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return fetch_intraday(symbol)
        except Exception as e:
            last_error = e
            if attempt == max_retries - 1:
                raise RuntimeError(f"Falhou após {max_retries} tentativas: {e}")
            
            wait_time = (2 ** attempt) * RETRY_BASE_WAIT_TIME + random.uniform(0, 1)
            print(
                f"[RETRY] {symbol}: tentativa {attempt + 1}/{max_retries} falhou, "
                f"aguardando {wait_time:.1f}s... ({e})",
                file=sys.stderr
            )
            time.sleep(wait_time)
    
    raise last_error


def main():
    cfg = load_config()
    DATA_HOURLY.mkdir(parents=True, exist_ok=True)
    
    symbols = get_all_symbols(cfg)
    success_count = 0
    error_count = 0
    
    print(f"[INFO] Recolhendo dados intradiários para {len(symbols)} ativos...")
    
    for symbol in symbols:
        try:
            df = fetch_with_retry(symbol)
            df.to_csv(DATA_HOURLY / f"{symbol}.csv")
            print(f"[OK] {symbol}: {len(df)} candles")
            success_count += 1
        except Exception as e:
            print(f"[ERRO] {symbol}: {e}", file=sys.stderr)
            error_count += 1
    
    print(f"[RESUMO] Recolha concluída: {success_count} OK, {error_count} erros")
    
    if error_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
