"""Filtro de regime de mercado: VWCE vs SMA200 + VIX.

Regras (ver data/reports/market_regime_filter.md):

    BULL     VWCE > SMA200 e VIX < 22          → exposição 100% (sizing normal)
    NEUTRAL  VWCE > SMA200 e 22 ≤ VIX < 28     → exposição máxima 60%
    STRESS   VIX ≥ 28                          → 100% cash
    BEAR     VWCE ≤ SMA200                     → 100% cash

Se VWCE < SMA200 e VIX ≥ 28 ao mesmo tempo, o regime é STRESS (ambos → cash).
Sem VIX (download falhado ou série desatualizada) o filtro cai para SMA200 apenas:
BULL acima da média, BEAR abaixo. Sem SMA200 (histórico < 200 sessões) o regime é
UNKNOWN e a carteira fica em cash, como antes.

Fontes do VIX, por ordem: yfinance ^VIX → CSV oficial da CBOE → espelho do CSV da
CBOE no GitHub (datasets/finance-vix). A série é gravada em data/daily/VIX.csv e
nunca é encurtada por um download parcial.

Uso: python scripts/market_regime.py  → atualiza VIX.csv e grava
data/reports/market_regime.json + market_regime_history.csv.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from paths import DATA_DAILY, REPORTS

REGIME_BENCHMARK = "VWCE.DE"
SMA_WINDOW = 200
VIX_TICKER = "^VIX"
VIX_PATH = DATA_DAILY / "VIX.csv"
VIX_NEUTRAL_LEVEL = 22.0
VIX_STRESS_LEVEL = 28.0
# Um VIX mais antigo do que isto (dias úteis) face à data avaliada é ignorado → fallback SMA200.
VIX_MAX_STALENESS_DAYS = 5
REGIME_EXPOSURE = {"BULL": 1.0, "NEUTRAL": 0.6, "STRESS": 0.0, "BEAR": 0.0, "UNKNOWN": 0.0}
REGIME_COLORS = {"BULL": "#00FF9D", "NEUTRAL": "#FFB800", "STRESS": "#FF8800", "BEAR": "#FF4466", "UNKNOWN": "#7183A6"}
VIX_CSV_SOURCES = (
    ("cboe", "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"),
    ("github-mirror", "https://raw.githubusercontent.com/datasets/finance-vix/main/data/vix-daily.csv"),
)
STATUS_PATH = REPORTS / "market_regime.json"
HISTORY_PATH = REPORTS / "market_regime_history.csv"


def classify_regime(close: float | None, sma200: float | None, vix: float | None) -> str:
    """Classifica um dia. `vix` None/NaN = sem VIX → só SMA200."""
    vix_ok = vix is not None and not pd.isna(vix)
    if vix_ok and vix >= VIX_STRESS_LEVEL:
        return "STRESS"
    if close is None or sma200 is None or pd.isna(close) or pd.isna(sma200):
        return "UNKNOWN"
    if close <= sma200:
        return "BEAR"
    if vix_ok and vix >= VIX_NEUTRAL_LEVEL:
        return "NEUTRAL"
    return "BULL"


def regime_exposure(regime: str) -> float:
    return REGIME_EXPOSURE.get(regime, 0.0)


# ── Download ─────────────────────────────────────────────────────────────────

def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)
    frame.index = frame.index.normalize()
    frame.index.name = "Date"
    columns = [column for column in ("open", "high", "low", "close") if column in frame.columns]
    frame = frame[columns].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])
    frame = frame[frame["close"] > 0]
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def _fetch_yfinance(period: str) -> pd.DataFrame:
    import yfinance as yf

    return _normalize(yf.Ticker(VIX_TICKER).history(period=period, interval="1d", auto_adjust=True))


def _fetch_csv(url: str) -> pd.DataFrame:
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = pd.read_csv(io.BytesIO(response.read()))
    date_column = next(column for column in raw.columns if column.strip().lower() == "date")
    return _normalize(raw.set_index(date_column))


def fetch_vix(period: str = "2y") -> tuple[pd.DataFrame, str]:
    """Tenta cada fonte até uma devolver dados. Levanta RuntimeError se todas falharem."""
    errors = []
    attempts = [("yfinance", lambda: _fetch_yfinance(period))]
    attempts += [(name, lambda url=url: _fetch_csv(url)) for name, url in VIX_CSV_SOURCES]
    for name, fetch in attempts:
        try:
            frame = fetch()
            if not frame.empty:
                return frame, name
            errors.append(f"{name}: vazio")
        except Exception as exc:  # noqa: BLE001 — qualquer falha passa à fonte seguinte
            errors.append(f"{name}: {exc}")
    raise RuntimeError("VIX indisponível — " + " | ".join(errors))


def update_vix_file(period: str = "2y") -> bool:
    """Atualiza data/daily/VIX.csv. Devolve False (sem levantar) se o download falhar."""
    try:
        fresh, source = fetch_vix(period)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] {exc} — regime cai para SMA200 apenas", file=sys.stderr)
        return False
    existing = load_vix_frame()
    if not existing.empty:
        fresh = pd.concat([existing, fresh])
        fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()
    # Mantém a mesma janela das restantes séries diárias (mais 1 ano de margem).
    fresh = fresh[fresh.index >= fresh.index.max() - pd.DateOffset(years=3)]
    VIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    fresh.to_csv(VIX_PATH)
    print(f"[OK] VIX ({len(fresh)} registos, fonte {source}, último {fresh.index.max().date()} = {fresh['close'].iloc[-1]:.2f})")
    return True


# ── Leitura e histórico ──────────────────────────────────────────────────────

def load_vix_frame() -> pd.DataFrame:
    if not VIX_PATH.exists():
        return pd.DataFrame()
    try:
        return _normalize(pd.read_csv(VIX_PATH, index_col=0))
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] VIX.csv ilegível: {exc}", file=sys.stderr)
        return pd.DataFrame()


def load_vix() -> pd.Series:
    frame = load_vix_frame()
    return frame["close"].astype(float) if not frame.empty else pd.Series(dtype=float)


def align_vix(vix: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """VIX no calendário, com forward-fill limitado para não usar valores obsoletos."""
    if vix.empty:
        return pd.Series(float("nan"), index=calendar)
    union = vix.index.union(calendar)
    return vix.reindex(union).ffill(limit=VIX_MAX_STALENESS_DAYS).reindex(calendar)


def regime_history(start: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Regime diário (dias úteis) a partir do VWCE e do VIX gravados em data/daily."""
    path = DATA_DAILY / f"{REGIME_BENCHMARK}.csv"
    if not path.exists():
        return pd.DataFrame()
    benchmark = pd.read_csv(path, index_col=0, parse_dates=True)
    benchmark.index = pd.to_datetime(benchmark.index).normalize()
    close = benchmark[~benchmark.index.duplicated(keep="last")].sort_index()["close"].astype(float).dropna()
    sma200 = close.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    calendar = pd.bdate_range(close.index.min(), close.index.max())
    frame = pd.DataFrame(index=calendar)
    frame.index.name = "date"
    frame["vwce_close"] = close.reindex(calendar).ffill()
    frame["sma200"] = sma200.reindex(calendar).ffill()
    frame["vix"] = align_vix(load_vix(), calendar)
    frame["regime"] = [
        classify_regime(row.vwce_close, row.sma200, row.vix) for row in frame.itertuples()
    ]
    frame["exposure"] = frame["regime"].map(regime_exposure)
    frame["vix_available"] = frame["vix"].notna()
    frame = frame[frame["sma200"].notna()]
    if start is not None:
        frame = frame[frame.index >= pd.Timestamp(start)]
    return frame


def current_regime(history: pd.DataFrame | None = None) -> dict:
    history = regime_history() if history is None else history
    if history.empty:
        return {"regime": "UNKNOWN", "exposure": 0.0, "vix_available": False}
    last = history.iloc[-1]
    since = history.index[-1]
    changed = history["regime"].ne(history["regime"].shift())
    if changed.any():
        since = history.index[changed][-1]
    return {
        "date": history.index[-1].strftime("%Y-%m-%d"),
        "regime": last["regime"],
        "exposure": float(last["exposure"]),
        "vwce_close": round(float(last["vwce_close"]), 4) if pd.notna(last["vwce_close"]) else None,
        "sma200": round(float(last["sma200"]), 4) if pd.notna(last["sma200"]) else None,
        "vix": round(float(last["vix"]), 2) if pd.notna(last["vix"]) else None,
        "vix_available": bool(last["vix_available"]),
        "mode": "VIX + SMA200" if last["vix_available"] else "SMA200 (fallback sem VIX)",
        "regime_since": since.strftime("%Y-%m-%d"),
        "vix_neutral_level": VIX_NEUTRAL_LEVEL,
        "vix_stress_level": VIX_STRESS_LEVEL,
        "exposure_rules": REGIME_EXPOSURE,
    }


def write_reports() -> tuple[dict, pd.DataFrame]:
    """Grava market_regime.json + market_regime_history.csv a partir dos ficheiros locais."""
    history = regime_history()
    status = current_regime(history)
    if history.empty:
        print("[WARN] Sem dados do VWCE — regime não calculado", file=sys.stderr)
        return status, history
    REPORTS.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    history.round(4).to_csv(HISTORY_PATH)
    print(f"[OK] Regime {status['regime']} ({status['mode']}) desde {status['regime_since']} · exposição {status['exposure']:.0%}")
    return status, history


def main() -> None:
    update_vix_file()
    write_reports()


if __name__ == "__main__":
    main()
