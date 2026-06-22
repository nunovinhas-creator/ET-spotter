"""
Regenera as secções dinâmicas do README.md com dados reais.

Secções geridas (delimitadas por marcadores HTML):
  <!-- ET-SPOTTER:TOP-ETFS:START --> ... <!-- ET-SPOTTER:TOP-ETFS:END -->
  <!-- ET-SPOTTER:REGIME:START -->   ... <!-- ET-SPOTTER:REGIME:END -->
  <!-- ET-SPOTTER:UPDATED:START -->  ... <!-- ET-SPOTTER:UPDATED:END -->

Corre via .github/workflows/update_readme.yml em push de scores_latest.csv
ou backtest_status.json. Nunca toca no resto do README.
"""

import json
import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCORES_CSV     = ROOT / "data/reports/scores_latest.csv"
BACKTEST_JSON  = ROOT / "data/reports/backtest_status.json"
README         = ROOT / "README.md"

SIGNAL_LABELS = {
    "RADAR_MAXIMO": "RADAR MÁXIMO",
    "EM_DESTAQUE":  "EM DESTAQUE",
    "A_OBSERVAR":   "A OBSERVAR",
}

def score_to_signal(score: float) -> str:
    if score >= 0.62:
        return "🟢 RADAR MÁXIMO"
    if score >= 0.50:
        return "🔵 EM DESTAQUE"
    if score >= 0.40:
        return "🟡 A OBSERVAR"
    return "—"


def load_scores() -> list[dict]:
    if not SCORES_CSV.exists():
        return []
    rows = []
    with open(SCORES_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "etf":       row["etf"],
                    "score":     float(row["score"]),
                    "score_pct": float(row.get("score_pct", 0)),
                    "ml_prob":   float(row.get("ml_prob", 0)) if row.get("ml_prob") else None,
                    "ret_63d":   float(row.get("ret_63d", 0)),
                    "above_sma200": int(float(row.get("above_sma200", -1))),
                })
            except (ValueError, KeyError):
                continue
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def spy_regime(rows: list[dict]) -> str:
    spy = next((r for r in rows if r["etf"] == "SPY"), None)
    if spy is None:
        # fallback: use above_sma200 from any row (all share the same market regime)
        if rows:
            v = rows[0].get("above_sma200", -1)
            return "BULL" if v == 1 else ("BEAR" if v == 0 else "DESCONHECIDO")
        return "DESCONHECIDO"
    v = spy.get("above_sma200", -1)
    return "BULL" if v == 1 else ("BEAR" if v == 0 else "DESCONHECIDO")


def build_top_etfs_section(rows: list[dict]) -> str:
    if not rows:
        return "_Dados não disponíveis._"

    regime = spy_regime(rows)
    regime_emoji = "🟢" if regime == "BULL" else ("🔴" if regime == "BEAR" else "⚪")
    top10 = [r for r in rows if r["etf"] != "SPY"][:10]

    now_pt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"> Actualizado automaticamente · {now_pt}",
        "",
        f"**Regime SPY:** {regime_emoji} {regime}",
        "",
        "| # | ETF | Score | Sinal | Ret 63d |",
        "|:-:|-----|:-----:|-------|--------:|",
    ]
    for i, r in enumerate(top10, 1):
        signal = score_to_signal(r["score"])
        ret63  = f"{r['ret_63d']:+.1%}" if r["ret_63d"] is not None else "—"
        lines.append(
            f"| {i} | `{r['etf']}` | **{r['score']:.3f}** | {signal} | {ret63} |"
        )

    n_radar    = sum(1 for r in rows if r["score"] >= 0.62)
    n_destaque = sum(1 for r in rows if 0.50 <= r["score"] < 0.62)
    n_observar = sum(1 for r in rows if 0.40 <= r["score"] < 0.50)
    lines += [
        "",
        f"**Sinais activos:** {n_radar} RADAR MÁXIMO · {n_destaque} EM DESTAQUE · {n_observar} A OBSERVAR",
    ]
    return "\n".join(lines)


def build_regime_section(rows: list[dict]) -> str:
    if not rows:
        return "_Regime indeterminado._"
    regime = spy_regime(rows)
    if regime == "BULL":
        return "🟢 **BULL** — SPY acima da SMA200 · sinais activos"
    if regime == "BEAR":
        return "🔴 **BEAR** — SPY abaixo da SMA200 · sinais suprimidos"
    return "⚪ **DESCONHECIDO**"


def build_updated_section() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"_Última actualização automática: **{now}**_"


def replace_section(content: str, tag: str, new_body: str) -> str:
    start_marker = f"<!-- ET-SPOTTER:{tag}:START -->"
    end_marker   = f"<!-- ET-SPOTTER:{tag}:END -->"
    start_idx = content.find(start_marker)
    end_idx   = content.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return content
    return (
        content[:start_idx + len(start_marker)]
        + "\n"
        + new_body
        + "\n"
        + content[end_idx:]
    )


def main() -> None:
    if not README.exists():
        print(f"README não encontrado: {README}")
        return

    rows = load_scores()
    content = README.read_text(encoding="utf-8")

    content = replace_section(content, "TOP-ETFS", build_top_etfs_section(rows))
    content = replace_section(content, "REGIME",   build_regime_section(rows))
    content = replace_section(content, "UPDATED",  build_updated_section())

    README.write_text(content, encoding="utf-8")
    print(f"README actualizado — {len(rows)} ETFs processados")


if __name__ == "__main__":
    main()
