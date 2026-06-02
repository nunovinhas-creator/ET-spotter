"""
Lê posições actuais do portfolio via Alpaca Markets API (paper ou live).
Guarda em data/portfolio.csv com snapshot diário.

Credenciais via variáveis de ambiente:
  ALPACA_API_KEY    – API Key ID
  ALPACA_API_SECRET – API Secret Key
  ALPACA_BASE_URL   – base URL (default: https://paper-api.alpaca.markets)
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from paths import PORTFOLIO

_DEFAULT_BASE_URL = "https://paper-api.alpaca.markets"
_POSITIONS_ENDPOINT = "/v2/positions"
_ACCOUNT_ENDPOINT   = "/v2/account"

_CSV_COLUMNS = [
    "date", "symbol", "qty", "side",
    "avg_entry_price", "current_price",
    "market_value", "unrealized_pl", "unrealized_plpc",
]


def fetch_positions(api_key: str, api_secret: str, base_url: str = _DEFAULT_BASE_URL) -> list[dict]:
    """Busca posições abertas via Alpaca REST API. Devolve [] em caso de erro."""
    url = base_url.rstrip("/") + _POSITIONS_ENDPOINT
    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[PORTFOLIO] Erro a obter posições: {e}", file=sys.stderr)
        return []


def fetch_account(api_key: str, api_secret: str, base_url: str = _DEFAULT_BASE_URL) -> dict:
    """Busca informação da conta (equity, cash, etc.). Devolve {} em caso de erro."""
    url = base_url.rstrip("/") + _ACCOUNT_ENDPOINT
    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[PORTFOLIO] Erro a obter conta: {e}", file=sys.stderr)
        return {}


def _parse_position(raw: dict, date_str: str) -> dict:
    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(raw.get(key) or default)
        except (TypeError, ValueError):
            return default

    return {
        "date":             date_str,
        "symbol":           str(raw.get("symbol", "")),
        "qty":              _f("qty"),
        "side":             str(raw.get("side", "long")),
        "avg_entry_price":  _f("avg_entry_price"),
        "current_price":    _f("current_price"),
        "market_value":     _f("market_value"),
        "unrealized_pl":    _f("unrealized_pl"),
        "unrealized_plpc":  _f("unrealized_plpc"),
    }


def save_portfolio(positions: list[dict], out_path: Path) -> None:
    """Grava posições em CSV, substituindo qualquer snapshot do mesmo dia."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if out_path.exists():
        with open(out_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            today = positions[0]["date"] if positions else ""
            existing = [row for row in reader if row.get("date") != today]

    rows = existing + positions
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    api_key    = os.getenv("ALPACA_API_KEY", "")
    api_secret = os.getenv("ALPACA_API_SECRET", "")
    base_url   = os.getenv("ALPACA_BASE_URL", _DEFAULT_BASE_URL)

    if not api_key or not api_secret:
        print("[PORTFOLIO] ALPACA_API_KEY / ALPACA_API_SECRET não definidos — a ignorar.", file=sys.stderr)
        sys.exit(0)

    date_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_positions = fetch_positions(api_key, api_secret, base_url)

    if not raw_positions:
        print("[PORTFOLIO] Sem posições abertas ou erro na API.")
        return

    positions = [_parse_position(p, date_str) for p in raw_positions]
    save_portfolio(positions, PORTFOLIO)

    total_pl = sum(p["unrealized_pl"] for p in positions)
    print(f"[OK] Portfolio: {len(positions)} posições · P&L não realizado: {total_pl:+.2f}")
    for p in positions:
        print(f"  {p['symbol']:12s}  qty={p['qty']:.2f}  price={p['current_price']:.2f}  pl={p['unrealized_pl']:+.2f} ({p['unrealized_plpc']:+.2%})")


if __name__ == "__main__":
    main()
