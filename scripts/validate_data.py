"""
Validação de integridade dos dados.
Verifica se os dados estão completos e coerentes antes de commitar.
"""

import sys
from pathlib import Path
import pandas as pd

try:
    from logger_config import setup_logger
    logger = setup_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

DATA_DAILY = Path("data/daily")
DATA_HOURLY = Path("data/hourly")


def validate_daily_data(symbol: str) -> tuple[bool, str]:
    """
    Valida se os dados diários de um ETF estão íntegros.
    
    Returns:
        (is_valid, message)
    """
    path = DATA_DAILY / f"{symbol}.csv"
    
    if not path.exists():
        return False, f"Arquivo não existe: {path}"
    
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception as e:
        return False, f"Erro ao ler CSV: {e}"
    
    if df.empty:
        return False, "DataFrame vazio"
    
    # Verificar colunas críticas
    required_cols = ["close", "sma20", "sma50", "sma200", "score"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return False, f"Colunas ausentes: {missing}"
    
    # Verificar NaNs em coluna crítica
    if df["close"].isna().sum() > len(df) * 0.1:  # Mais de 10% NaNs
        return False, f"Demasiados NaNs em 'close': {df['close'].isna().sum()}/{len(df)}"
    
    # Verificar score_pct percentual (deve estar em [0, 1] ou NaN)
    score_pct = df.get("score_pct")
    if score_pct is not None:
        valid_scores = (score_pct >= 0) & (score_pct <= 1) | score_pct.isna()
        if not valid_scores.all():
            invalid_count = (~valid_scores).sum()
            return False, f"score_pct inválido em {invalid_count} linhas"
    
    logger.info(f"✓ {symbol}: dados válidos ({len(df)} registos)")
    return True, "OK"


def validate_hourly_data(symbol: str) -> tuple[bool, str]:
    """
    Valida se os dados intradiários de um ETF estão íntegros.
    
    Returns:
        (is_valid, message)
    """
    path = DATA_HOURLY / f"{symbol}.csv"
    
    if not path.exists():
        return False, f"Arquivo não existe: {path}"
    
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception as e:
        return False, f"Erro ao ler CSV: {e}"
    
    if df.empty:
        return False, "DataFrame vazio"
    
    required_cols = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return False, f"Colunas ausentes: {missing}"
    
    # Verificar OHLC consistency
    invalid_ohlc = (
        (df["high"] < df["low"]) |
        (df["high"] < df["open"]) |
        (df["high"] < df["close"]) |
        (df["low"] > df["open"]) |
        (df["low"] > df["close"])
    ).sum()
    
    if invalid_ohlc > 0:
        return False, f"Dados OHLC inválidos em {invalid_ohlc} linhas"
    
    logger.info(f"✓ {symbol}: dados intradiários válidos ({len(df)} candles)")
    return True, "OK"


def validate_all_data(cfg: dict) -> bool:
    """
    Valida todos os ETFs.
    Retorna True se tudo OK, False se há erros.
    """
    from utils import get_all_symbols
    
    all_valid = True
    symbols = get_all_symbols(cfg)
    
    logger.info(f"Validando {len(symbols)} ativos...")
    
    for symbol in symbols:
        # Validar dados diários
        is_valid, msg = validate_daily_data(symbol)
        if not is_valid:
            logger.warning(f"✗ {symbol} (diário): {msg}")
            all_valid = False
        
        # Validar dados intradiários
        is_valid, msg = validate_hourly_data(symbol)
        if not is_valid:
            logger.warning(f"✗ {symbol} (intradiário): {msg}")
            all_valid = False
    
    return all_valid


if __name__ == "__main__":
    from utils import load_config
    
    cfg = load_config()
    if validate_all_data(cfg):
        logger.info("✓ Todos os dados estão válidos!")
        sys.exit(0)
    else:
        logger.error("✗ Erros encontrados na validação de dados!")
        sys.exit(1)
