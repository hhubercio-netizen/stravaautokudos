"""Parser feedu Strava z danych Next.js (`__NEXT_DATA__`)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from loguru import logger

from autokudos.models import Activity


class FeedParseError(ValueError):
    """Nie udało się sparsować dashboardu Stravy."""


@dataclass(slots=True)
class FeedSnapshot:
    activities: list[Activity]
    current_athlete_id: str
    current_athlete_name: str
    entry_count: int


_NUMBER_RE = re.compile(r"(\d(?:[\d.,\s\u00a0\u202f]*\d)?)")


def extract_next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if script is None or not script.string:
        raise FeedParseError("Nie znaleziono danych __NEXT_DATA__ na dashboardzie Stravy.")
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError as exc:
        raise FeedParseError(f"Niepoprawny JSON w __NEXT_DATA__: {exc}") from exc
    if not isinstance(data, dict):
        raise FeedParseError("__NEXT_DATA__ nie jest obiektem JSON.")
    return data


def _parse_number(raw: str) -> float:
    value = re.sub(r"[\s\u00a0\u202f]", "", raw.strip())
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    return float(value)


def _distance_from_html(raw: str) -> float:
    if not raw:
        return 0.0

    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = _NUMBER_RE.search(text)
    if not match:
        return 0.0

    number = _parse_number(match.group(1))
    abbr = soup.find("abbr")
    unit_title = (abbr.get("title") or "").strip().lower() if abbr else ""
    unit_text = abbr.get_text(" ", strip=True).strip().lower() if abbr else ""
    unit = unit_title or unit_text

    if unit in {"mile", "miles", "mi"} or unit_text in {"mi", "miles"}:
        number *= 1.609344
    elif unit in {"metr", "metry", "meters", "meter", "m"} or unit_text == "m":
        number /= 1000.0

    return round(number, 3)


def _stat_value(activity: dict, key: str) -> str:
    for stat in activity.get("stats") or []:
        if stat.get("key") == key:
            return str(stat.get("value") or "")
    return ""


def _moving_time(activity: dict) -> str:
    raw = _stat_value(activity, "stat_three")
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(" ", strip=True)


def _parse_start_date(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _current_athlete(dashboard_data: dict, entries: list[dict]) -> tuple[str, str]:
    current = dashboard_data.get("currentAthlete") or {}
    athlete_id = str(current.get("id") or "").strip()
    first_name = str(current.get("firstName") or "").strip()
    last_name = str(current.get("lastName") or "").strip()
    athlete_name = " ".join(part for part in (first_name, last_name) if part)

    if not athlete_id:
        for entry in entries:
            viewing = entry.get("viewingAthlete") or {}
            candidate = str(viewing.get("id") or "").strip()
            if candidate:
                athlete_id = candidate
                athlete_name = str(viewing.get("name") or "").strip()
                break

    if not athlete_id:
        raise FeedParseError("Nie udało się ustalić ID zalogowanego zawodnika.")

    return athlete_id, athlete_name or "?"


def _activity_from_entry(entry: dict, me_id: str) -> Activity | None:
    activity = entry.get("activity")
    if not isinstance(activity, dict):
        return None

    activity_id = str(activity.get("id") or "").strip()
    if not activity_id:
        return None

    start_date = _parse_start_date(activity.get("startDate"))
    if start_date is None:
        logger.warning("Pomijam aktywność {} — brak poprawnego startDate.", activity_id)
        return None

    athlete = activity.get("athlete") or {}
    athlete_id = str(athlete.get("athleteId") or athlete.get("id") or "").strip()
    athlete_name = str(athlete.get("athleteName") or athlete.get("name") or "?").strip()

    kudos = activity.get("kudosAndComments") or {}
    time_and_location = activity.get("timeAndLocation") or {}

    return Activity(
        id=activity_id,
        athlete_id=athlete_id,
        athlete_name=athlete_name or "?",
        title=str(activity.get("activityName") or "(bez nazwy)").strip(),
        sport=str(activity.get("type") or "?").strip(),
        start_date=start_date,
        distance_km=_distance_from_html(_stat_value(activity, "stat_one")),
        moving_time=_moving_time(activity),
        kudos_count=int(kudos.get("kudosCount") or 0),
        has_kudoed=bool(kudos.get("hasKudoed", False)),
        can_kudo=bool(kudos.get("canKudo", False)),
        is_own=bool(activity.get("ownedByCurrentAthlete")) or athlete_id == me_id,
        display_date=str(
            time_and_location.get("displayDateAtTime") or time_and_location.get("displayDate") or ""
        ),
    )


def parse_dashboard(html: str) -> FeedSnapshot:
    data = extract_next_data(html)
    page_props = data.get("props", {}).get("pageProps", {})
    dashboard_data = page_props.get("dashboardData") or {}
    feed = dashboard_data.get("feed") or {}
    entries = feed.get("entries") or []
    if not isinstance(entries, list):
        raise FeedParseError("Nieoczekiwany format feedu w __NEXT_DATA__.")

    me_id, me_name = _current_athlete(dashboard_data, entries)

    activities: list[Activity] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("entity") != "Activity":
            continue
        activity = _activity_from_entry(entry, me_id)
        if activity is not None:
            activities.append(activity)

    return FeedSnapshot(
        activities=activities,
        current_athlete_id=me_id,
        current_athlete_name=me_name,
        entry_count=len(entries),
    )
