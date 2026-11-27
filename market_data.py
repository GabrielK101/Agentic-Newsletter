"""market_data.py - closing-session market figures, fetched by code (not
the model) so the ticker is reliable every day. Wraps yfinance so the
data source can be swapped later without touching callers - get_ticker()
is the only entry point anything outside this module should use.

Verified against the installed yfinance==1.8.0: Ticker(symbol).history()
returns a DataFrame indexed by session date; the last row is the most
recent session yfinance has a bar for. This job runs once a day (well
after US market close for the prior session in practice), so the last
row is treated as the most recent COMPLETED session - this module does
not itself detect an in-progress session.
"""
import yfinance as yf

# label, yfinance symbol, and how to format the close. Keyed by a short
# name so config.yaml can enable a subset by name (see digest.py).
INSTRUMENTS = {
    "sp500": {"symbol": "^GSPC", "label": "S&P 500", "kind": "index"},
    "nasdaq": {"symbol": "^IXIC", "label": "Nasdaq Composite", "kind": "index"},
    "dow": {"symbol": "^DJI", "label": "Dow", "kind": "index"},
    "ftse": {"symbol": "^FTSE", "label": "FTSE 100", "kind": "index"},
    "brent": {"symbol": "BZ=F", "label": "Brent crude", "kind": "money"},
    "gbpusd": {"symbol": "GBPUSD=X", "label": "GBP/USD", "kind": "fx"},
}
DEFAULT_INSTRUMENT_KEYS = ["sp500", "nasdaq", "dow", "ftse", "brent", "gbpusd"]


def _format_value(value: float, kind: str) -> str:
    if kind == "money":
        return f"${value:,.2f}"
    if kind == "fx":
        return f"{value:.4f}"
    return f"{value:,.2f}"


def _fetch_one(instrument: dict) -> dict | None:
    """The last completed daily bar's close and % change from the bar
    before it, shaped like parse_digest's own ticker rows, plus an extra
    "session_day" (e.g. "Fri") - not part of parse_digest's own ticker
    shape, so model-sourced ticker rows never have it, but renderers can
    use it for a shared "Markets · Fri close" heading instead of
    repeating the day on every single row. None on any failure - never
    raises: one bad symbol must not sink the ticker."""
    try:
        hist = yf.Ticker(instrument["symbol"]).history(period="5d")
        if len(hist) < 2:
            return None
        close = float(hist.iloc[-1]["Close"])
        prev_close = float(hist.iloc[-2]["Close"])
        if not prev_close:
            return None
        pct = (close - prev_close) / prev_close * 100
        direction = "up" if pct > 0.05 else "down" if pct < -0.05 else "flat"
        return {
            "label": instrument["label"],
            "value": _format_value(close, instrument["kind"]),
            "change": f"{pct:+.2f}%",
            "direction": direction,
            "session_day": hist.index[-1].strftime("%a"),
        }
    except Exception as e:
        print(f"[warning] market_data: could not fetch {instrument['symbol']}: {type(e).__name__}: {e}")
        return None


def get_ticker(instrument_keys: list[str] | None = None) -> list[dict]:
    """Ticker rows ready to REPLACE the model's own ticker outright (see
    digest.py) - {label, value, change, direction}, the same shape
    parse_digest produces. Skips (and logs) any instrument that fails;
    never raises. `instrument_keys` defaults to every key in INSTRUMENTS,
    in DEFAULT_INSTRUMENT_KEYS order; unknown keys are ignored."""
    keys = instrument_keys if instrument_keys is not None else DEFAULT_INSTRUMENT_KEYS
    rows = []
    for key in keys:
        instrument = INSTRUMENTS.get(key)
        if instrument is None:
            continue
        row = _fetch_one(instrument)
        if row is not None:
            rows.append(row)
    return rows
