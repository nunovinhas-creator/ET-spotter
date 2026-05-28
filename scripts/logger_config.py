"""
Sistema de logging centralizado para o ET-Spotter.
"""

import logging
import sys
from pathlib import Path


def setup_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Cria e configura um logger com output para console.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File handler (opcional - cria pasta logs/ se não existir)
    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(log_dir / f"{name}.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        pass  # Se não conseguir criar ficheiro, continua só com console

    return logger
