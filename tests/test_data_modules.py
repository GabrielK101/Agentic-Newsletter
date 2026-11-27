"""pytest tests for market_data.py and sports_data.py: mocked HTTP/yfinance
calls, a failed instrument is skipped (never raises), and unfinished
events are excluded. Run with: pytest tests/test_data_modules.py -q
"""
import sys
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import market_data
import sports_data


# --- market_data ---

def _fake_history(closes):
    return pd.DataFrame({"Close": closes}, index=pd.date_range("2026-11-20", periods=len(closes)))


def test_get_ticker_formats_and_computes_change():
    fake_ticker = mock.MagicMock()
    fake_ticker.history.return_value = _fake_history([100.0, 110.0])
    with mock.patch.object(market_data.yf, "Ticker", return_value=fake_ticker):
        rows = market_data.get_ticker(["sp500"])
    assert len(rows) == 1
    assert rows[0]["direction"] == "up"
    assert rows[0]["change"] == "+10.00%"
    assert "S&P 500" in rows[0]["label"]


def test_get_ticker_skips_failed_instrument():
    def ticker_side_effect(symbol):
        t = mock.MagicMock()
        if symbol == "^GSPC":
            t.history.side_effect = RuntimeError("network error")
        else:
            t.history.return_value = _fake_history([1.0, 1.0])
        return t

    with mock.patch.object(market_data.yf, "Ticker", side_effect=ticker_side_effect):
        rows = market_data.get_ticker(["sp500", "nasdaq"])
    labels = [r["label"] for r in rows]
    assert not any("S&P 500" in label for label in labels)
    assert any("Nasdaq" in label for label in labels)


def test_get_ticker_unknown_key_ignored():
    rows = market_data.get_ticker(["not-a-real-instrument"])
    assert rows == []


def test_get_ticker_flat_direction_for_tiny_change():
    fake_ticker = mock.MagicMock()
    fake_ticker.history.return_value = _fake_history([100.0, 100.01])
    with mock.patch.object(market_data.yf, "Ticker", return_value=fake_ticker):
        rows = market_data.get_ticker(["sp500"])
    assert rows[0]["direction"] == "flat"


# --- sports_data ---

def test_get_f1_builds_podium_and_standings():
    results_payload = {
        "MRData": {"RaceTable": {"Races": [{
            "raceName": "Las Vegas Grand Prix",
            "Results": [
                {"position": "1", "Driver": {"familyName": "Verstappen"}},
                {"position": "2", "Driver": {"familyName": "Norris"}},
                {"position": "3", "Driver": {"familyName": "Piastri"}},
            ],
        }]}}
    }
    standings_payload = {
        "MRData": {"StandingsTable": {"StandingsLists": [{
            "DriverStandings": [
                {"points": "450", "Driver": {"familyName": "Antonelli"}},
                {"points": "352", "Driver": {"familyName": "Verstappen"}},
            ],
        }]}}
    }

    def fake_get(url, **kwargs):
        resp = mock.MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = results_payload if "results" in url else standings_payload
        return resp

    with mock.patch.object(sports_data.httpx, "get", side_effect=fake_get):
        rows = sports_data.get_f1()
    assert any("Las Vegas Grand Prix" in r["label"] for r in rows)
    assert any("Verstappen · Norris · Piastri" == r["line"] for r in rows)
    assert any("Antonelli leads Verstappen by 98 pts" == r["line"] for r in rows)
    assert all(r["group"] == "Formula 1" for r in rows)


def test_get_f1_returns_empty_on_failure():
    with mock.patch.object(sports_data.httpx, "get", side_effect=RuntimeError("boom")):
        rows = sports_data.get_f1()
    assert rows == []


def test_get_football_excludes_unfinished_and_requires_key(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_API_KEY", raising=False)
    assert sports_data.get_football("premier_league", 7) == []

    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "fake-key")
    payload = {
        "competition": {"name": "Premier League"},
        "matches": [
            {"status": "FINISHED", "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 2, "away": 1}}},
            {"status": "SCHEDULED", "homeTeam": {"name": "Liverpool"}, "awayTeam": {"name": "Everton"},
             "score": {"fullTime": {"home": None, "away": None}}},
        ],
    }
    resp = mock.MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    with mock.patch.object(sports_data.httpx, "get", return_value=resp):
        rows = sports_data.get_football("premier_league", 7)
    assert len(rows) == 1
    assert rows[0]["line"] == "Arsenal 2-1 Chelsea"
    assert rows[0]["group"] == "Premier League"
    assert rows[0]["label"] == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
