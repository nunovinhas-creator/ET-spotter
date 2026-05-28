"""
Integração com Telegram para envio de alertas.
"""

import os
import requests

try:
    from logger_config import setup_logger
    logger = setup_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def send_telegram_alert(message: str, parse_mode: str = "HTML") -> bool:
    """
    Envia mensagem de texto via Telegram.
    Returns True se enviado com sucesso.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("[TELEGRAM] Credenciais não definidas — a ignorar envio.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"[TELEGRAM] Mensagem enviada com sucesso.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"[TELEGRAM] Erro ao enviar mensagem: {e}")
        return False


def send_telegram_photo(photo_url: str, caption: str = "") -> bool:
    """
    Envia imagem via Telegram com legenda opcional.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        logger.warning("[TELEGRAM] Credenciais não definidas — a ignorar envio.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"[TELEGRAM] Foto enviada com sucesso.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"[TELEGRAM] Erro ao enviar foto: {e}")
        return False
