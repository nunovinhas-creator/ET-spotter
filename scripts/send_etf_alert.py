"""
Envia alerta Telegram para ETFs em condição de entrada potencial.

Condição de disparo:
  - Regime SPY == BULL
  - Score em A OBSERVAR  [CONVICTION_POTENTIAL_SCORE, CONVICTION_BUY_SCORE)
  - Momentum 12-1 positivo  ((1+ret_252d)/(1+ret_21d) - 1) > 0

Credenciais via env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from constants import CONVICTION_POTENTIAL_SCORE, CONVICTION_BUY_SCORE
from utils import get_spy_regime
from send_telegram import send_telegram_alert

SCORES_CSV = Path(__file__).parent.parent / "data/reports/scores_latest.csv"


def _build_message(candidates: list[dict]) -> str:
    lines = [
        "📊 <b>ET-Spotter — entrada potencial</b>",
        "🟡 A OBSERVAR em regime BULL",
        "",
    ]
    for c in candidates:
        lines.append(f"<b>{c['etf']}</b>: score={c['score']:.2f} | mom={c['mom']:.1%}")
    lines += ["", "💡 Momento para contribuição mensal"]
    return "\n".join(lines)


def main() -> None:
    regime = get_spy_regime()
    if regime != "BULL":
        print(f"Regime {regime} — sem alerta")
        return

    if not SCORES_CSV.exists():
        print(f"ERRO: {SCORES_CSV} não encontrado", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(SCORES_CSV)

    mask = (df["score"] >= CONVICTION_POTENTIAL_SCORE) & (df["score"] < CONVICTION_BUY_SCORE)
    subset = df[mask].copy()

    subset["mom_12_1"] = (1 + subset["ret_252d"]) / (1 + subset["ret_21d"]) - 1
    subset = subset[subset["mom_12_1"] > 0].sort_values("score", ascending=False)

    if subset.empty:
        print("Nenhum ETF em condição de entrada — sem alerta")
        return

    candidates = [
        {"etf": r["etf"], "score": r["score"], "mom": r["mom_12_1"]}
        for _, r in subset.iterrows()
    ]

    message = _build_message(candidates)
    print(message)
    send_telegram_alert(message)
    print(f"Alerta enviado — {len(candidates)} ETF(s)")


if __name__ == "__main__":
    main()
