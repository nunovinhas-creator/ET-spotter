"""Caminhos de dados centralizados, ancorados ao repositório."""

from pathlib import Path

ROOT            = Path(__file__).parent.parent
DATA_DAILY      = ROOT / "data" / "daily"
DATA_INTRA      = ROOT / "data" / "intraday"
REPORTS         = ROOT / "data" / "reports"
SCORES_HIST     = ROOT / "data" / "scores_history.csv"
CONFIG_PATH     = ROOT / "config" / "etfs.json"
PORTFOLIO       = ROOT / "data" / "portfolio.csv"
PUSH_SUBS       = ROOT / "data" / "push_subscriptions.json"
