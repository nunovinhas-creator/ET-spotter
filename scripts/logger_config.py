"""
Sistema de logging centralizado com suporte a arquivo e console.
Estrutura logs de forma compatível com GitHub Actions.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(
    name: str,
    level: int = logging.DEBUG,
    log_dir: Path | str = "logs"
) -> logging.Logger:
    """
    Configura um logger com handlers de console e arquivo.
    
    Args:
        name: Nome do logger (e.g., __name__)
        level: Nível de logging (DEBUG, INFO, WARNING, ERROR)
        log_dir: Diretório para guardar logs
    
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Evitar duplicação de handlers
    if logger.handlers:
        return logger
    
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Formatter com timestamp
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler para console (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler para arquivo
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Obtém um logger existente ou cria um novo."""
    return logging.getLogger(name)
