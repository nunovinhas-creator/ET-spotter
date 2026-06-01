"""
Constantes globais e configurações centralizadas.
Evita magic numbers espalhados pelo código.
"""

# Horas de mercado US em UTC
US_MARKET_OPEN_UTC = 13    # 13:00 UTC = 08:00 EST / 09:00 EDT
US_MARKET_CLOSE_UTC = 22   # 22:00 UTC = 17:00 EST / 18:00 EDT
US_MARKET_HOURS = (US_MARKET_OPEN_UTC, US_MARKET_CLOSE_UTC)

# Limiares de alertas estruturais
SCORE_DANGER = 0.40           # Score crítico para deterioração
SCORE_DROP_FAST = 0.07        # Queda rápida de score numa sessão
SCORE_RECOVERY_THRESHOLD = 0.48  # Score para considerar recuperação

# Limiares técnicos
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_ENTRY_ZONE_MIN = 40
RSI_ENTRY_ZONE_MAX = 65
ADX_TREND_THRESHOLD = 20      # ADX > 20 indica tendência forte

# Defaults para thresholds de drops
DEFAULT_HOURLY_DROP_THRESHOLD = -0.02  # -2%
DEFAULT_DRAWDOWN_THRESHOLD = -0.08     # -8%

# Configurações de retry
MAX_API_RETRIES = 3
RETRY_BASE_WAIT_TIME = 1      # segundos (aplicar exponencial backoff)

# Períodos de dados
INTRADAY_FETCH_PERIOD = "60d"
INTRADAY_INTERVAL = "1h"
SCORE_HISTORY_WINDOW = 252    # ~1 ano de dias úteis

# Configurações de email/notificações
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Limiares de convicção para sinais de compra (compute_conviction)
CONVICTION_STRONG_BUY_SCORE   = 0.62
CONVICTION_STRONG_BUY_SIGNALS = 6
CONVICTION_BUY_SCORE          = 0.54
CONVICTION_BUY_SIGNALS        = 4
CONVICTION_POTENTIAL_SCORE    = 0.48
CONVICTION_POTENTIAL_SIGNALS  = 3
