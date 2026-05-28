"""
Envio de notificações via Telegram.
Credenciais via variáveis de ambiente:
  TELEGRAM_BOT_TOKEN  – token do bot (@BotFather)
  TELEGRAM_CHAT_ID    – ID do chat/grupo para enviar mensagens
"""

import os
import sys
import requests
from typing import Optional


TELEGRAM_API_BASE = "https://api.telegram.org"


def send_telegram_alert(
    message: str,
    parse_mode: str = "HTML",
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 10
) -> bool:
    """
    Envia mensagem via Telegram.
    
    Args:
        message: Conteúdo da mensagem (suporta HTML se parse_mode="HTML")
        parse_mode: "HTML", "Markdown", ou "MarkdownV2"
        bot_token: Token do bot (default: TELEGRAM_BOT_TOKEN env var)
        chat_id: ID do chat (default: TELEGRAM_CHAT_ID env var)
        timeout: Timeout em segundos
    
    Returns:
        True se enviado com sucesso, False caso contrário
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print(
            "[TELEGRAM] Credenciais não definidas. "
            "Define TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.",
            file=sys.stderr
        )
        return False
    
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        print(f"[TELEGRAM] ✓ Mensagem enviada para {chat_id}")
        return True
    except requests.RequestException as e:
        print(f"[TELEGRAM] ✗ Erro ao enviar: {e}", file=sys.stderr)
        return False


def send_telegram_photo(
    photo_url: str,
    caption: Optional[str] = None,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 10
) -> bool:
    """
    Envia foto via Telegram.
    
    Args:
        photo_url: URL da foto
        caption: Legenda (opcional, suporta HTML)
        bot_token: Token do bot
        chat_id: ID do chat
        timeout: Timeout em segundos
    
    Returns:
        True se enviado com sucesso, False caso contrário
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print(
            "[TELEGRAM] Credenciais não definidas.",
            file=sys.stderr
        )
        return False
    
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
    }
    
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
    
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        print(f"[TELEGRAM] ✓ Foto enviada para {chat_id}")
        return True
    except requests.RequestException as e:
        print(f"[TELEGRAM] ✗ Erro ao enviar foto: {e}", file=sys.stderr)
        return False

