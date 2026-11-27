"""sports_data.py - finished-event sport results, fetched by code (not
the model) so the scoreboard is reliable and never shows an unfinished
event. F1 via the Jolpica API (the maintained Ergast successor); football
via football-data.org, optional, behind FOOTBALL_DATA_API_KEY.

Jolpica (verified against the live repo docs, 2026): base
http://api.jolpi.ca/ergast/f1/, no API key, but a descriptive User-Agent
is required. Unauthenticated limits: 4 req/s burst, 500 req/hour.

football-data.org v4 (verified against docs.football-data.org): base
https://api.football-data.org/v4/, auth via the X-Auth-Token header.
"""
import os

import httpx

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"  # the http:// form 301-redirects here
_USER_AGENT = "AgenticNewsletterBot/1.0 (digest@localhost)"
_TIMEOUT = 10.0

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
# name -> football-data.org competition code (docs/lookup_tables.html).
FOOTBALL_COMPETITIONS = {"premier_league": "PL"}


def _jolpica_get(path: str) -> dict | None:
    try:
        response = httpx.get(
            f"{JOLPICA_BASE}/{path}",
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"[warning] sports_data: Jolpica request failed for {path}: {type(e).__name__}: {e}")
        return None


def get_f1() -> list[dict]:
    """Scoreboard rows for the latest finished race's podium and the
    current championship gap, grouped under "Formula 1" (parse_digest's
    scoreboard shape: {group, label, line}). Only ever reports what the
    API already shows as finished results - never a preview. Empty list
    (never raises) on any failure."""
    rows = []

    results = _jolpica_get("current/last/results/")
    races = (results or {}).get("MRData", {}).get("RaceTable", {}).get("Races", [])
    if races:
        race = races[0]
        podium = sorted(
            (r for r in race.get("Results", []) if r.get("position") in ("1", "2", "3")),
            key=lambda r: int(r["position"]),
        )
        if podium:
            names = " · ".join(r["Driver"]["familyName"] for r in podium)
            rows.append({"group": "Formula 1", "label": race.get("raceName", "Latest race"), "line": names})

    standings = _jolpica_get("current/driverstandings/")
    lists = (standings or {}).get("MRData", {}).get("StandingsTable", {}).get("StandingsLists", [])
    if lists:
        drivers = lists[0].get("DriverStandings", [])
        if len(drivers) >= 2:
            try:
                leader, second = drivers[0], drivers[1]
                gap = int(leader["points"]) - int(second["points"])
                rows.append({
                    "group": "Formula 1", "label": "Drivers",
                    "line": f"{leader['Driver']['familyName']} leads {second['Driver']['familyName']} by {gap} pts",
                })
            except (KeyError, ValueError, TypeError):
                pass

    return rows


def get_football(competition_key: str, lookback_days: int) -> list[dict]:
    """Finished matches for `competition_key` (a FOOTBALL_COMPETITIONS
    name, e.g. "premier_league") in the last `lookback_days` days, as
    scoreboard rows grouped under the competition's name, up to 4 (the
    per-group cap). Requires FOOTBALL_DATA_API_KEY; returns [] (never
    raises) if it's unset, the competition name is unknown, or the
    request fails."""
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY")
    code = FOOTBALL_COMPETITIONS.get(competition_key)
    if not api_key or not code:
        return []

    from datetime import date, timedelta
    date_from = (date.today() - timedelta(days=lookback_days)).isoformat()
    date_to = date.today().isoformat()

    try:
        response = httpx.get(
            f"{FOOTBALL_DATA_BASE}/competitions/{code}/matches",
            headers={"X-Auth-Token": api_key},
            params={"status": "FINISHED", "dateFrom": date_from, "dateTo": date_to},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[warning] sports_data: football-data.org request failed for {competition_key}: {type(e).__name__}: {e}")
        return []

    competition_name = data.get("competition", {}).get("name", competition_key)
    rows = []
    for match in data.get("matches", []):
        if len(rows) >= 4:
            break
        if match.get("status") != "FINISHED":
            continue
        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")
        score = match.get("score", {}).get("fullTime", {})
        home_score, away_score = score.get("home"), score.get("away")
        if home_score is None or away_score is None:
            continue
        rows.append({"group": competition_name, "label": "", "line": f"{home} {home_score}-{away_score} {away}"})
    return rows
