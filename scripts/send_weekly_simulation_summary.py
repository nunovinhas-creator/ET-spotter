"""Envia um resumo semanal da carteira simulada para o Telegram."""

import argparse
import html
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from send_telegram import send_telegram_alert


RESULTS_CSV = Path(__file__).parent.parent / "data" / "reports" / "simulation_results.csv"


def _pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def build_message(results: pd.DataFrame) -> str:
    latest = results.iloc[-1]
    allocations = []
    if pd.notna(latest.get("allocation_details")):
        details = json.loads(latest["allocation_details"])
        allocations = [
            f"{html.escape(item['ticker'])} ({float(item['weight']) * 100:.0f}%)"
            for item in details
            if item.get("active", True) and float(item.get("weight", 0)) > 0
        ]

    holdings = ", ".join(allocations) if allocations else "Liquidez / sem exposição a risco"
    lines = [
        "📈 <b>ET-Spotter · Resumo semanal da simulação</b>",
        f"Período: <b>{html.escape(str(latest['analysis_start']))}</b> → <b>{html.escape(str(latest['analysis_end']))}</b>",
        "",
        f"💼 Valor final: <b>€{float(latest['final_portfolio_value']):,.2f}</b>",
        f"📊 Rentabilidade acumulada: <b>{_pct(float(latest['cumulative_return']))}</b>",
        f"📉 Max Drawdown: <b>{_pct(float(latest['max_drawdown']))}</b>",
        f"⚖️ Sharpe / Sortino: <b>{float(latest['sharpe_ratio']):.2f} / {float(latest['sortino_ratio']):.2f}</b>",
        "",
        f"🛡️ Último ciclo: <b>{html.escape(str(latest['market_regime']))}</b> · exposição <b>{float(latest['exposure']) * 100:.0f}%</b>",
        f"🔁 Turnover: <b>{float(latest['turnover']) * 100:.1f}%</b> · custo: <b>€{float(latest['friction_cost_eur']):,.2f}</b>",
        f"🎯 Carteira: {holdings}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Imprime a mensagem sem enviar para o Telegram")
    args = parser.parse_args()

    if not RESULTS_CSV.exists():
        raise FileNotFoundError(f"Resultados da simulação não encontrados: {RESULTS_CSV}")

    results = pd.read_csv(RESULTS_CSV)
    required = {
        "analysis_start", "analysis_end", "final_portfolio_value", "cumulative_return",
        "max_drawdown", "sharpe_ratio", "sortino_ratio", "market_regime", "exposure",
        "turnover", "friction_cost_eur", "allocation_details",
    }
    missing = required.difference(results.columns)
    if missing:
        raise ValueError(f"Colunas em falta no CSV de simulação: {sorted(missing)}")

    message = build_message(results)
    print(message)
    if not args.dry_run and not send_telegram_alert(message):
        raise RuntimeError("Não foi possível enviar o resumo semanal para o Telegram")


if __name__ == "__main__":
    main()