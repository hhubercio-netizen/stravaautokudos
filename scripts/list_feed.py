#!/usr/bin/env python3
"""Read-only podgląd feedu Strava: lista aktywności i stan kudos.

Nie wysyła kudos. Służy do sprawdzenia parsera przed spike'em.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DASHBOARD_URL = "https://www.strava.com/dashboard?num_entries=50"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

SPORT_MAP = {
    "virtualride": "VirtualRide",
    "virtualrun": "VirtualRun",
    "ride": "Ride",
    "run": "Run",
    "walk": "Walk",
    "hike": "Hike",
    "swim": "Swim",
    "ebikeride": "EBikeRide",
    "gravelride": "GravelRide",
    "mountainbikeride": "MountainBikeRide",
    "workout": "Workout",
    "weighttraining": "WeightTraining",
    "highintensityintervaltraining": "HIIT",
    "yoga": "Yoga",
    "rowing": "Rowing",
    "virtualrow": "VirtualRow",
    "kayaking": "Kayaking",
    "canoeing": "Canoeing",
    "standuppaddling": "StandUpPaddling",
    "nordicski": "NordicSki",
    "alpineski": "AlpineSki",
    "backcountryski": "BackcountrySki",
    "snowshoe": "Snowshoe",
    "iceskate": "IceSkate",
    "inlineskate": "InlineSkate",
    "skateboard": "Skateboard",
    "surfing": "Surfing",
    "windsurf": "Windsurf",
    "kitesurf": "Kitesurf",
    "sail": "Sail",
    "soccer": "Soccer",
    "tennis": "Tennis",
    "badminton": "Badminton",
    "golf": "Golf",
    "rockclimbing": "RockClimbing",
}


@dataclass(slots=True)
class FeedActivity:
    activity_id: str
    athlete_name: str
    athlete_id: str | None
    title: str
    sport: str
    distance: str
    moving_time: str
    when: str
    kudosed: bool
    kudos_count: str
    is_own: bool = False

    @property
    def url(self) -> str:
        return f"https://www.strava.com/activities/{self.activity_id}"


def load_cookie() -> str:
    if not ENV_PATH.exists():
        raise SystemExit(f"Brak pliku {ENV_PATH}")

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "STRAVA_SESSION_COOKIE":
            cookie = value.strip().strip('"').strip("'")
            if cookie:
                return cookie

    raise SystemExit("Brak STRAVA_SESSION_COOKIE w .env")


def fetch_dashboard(cookie: str) -> str:
    request = Request(
        DASHBOARD_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": f"_strava4_session={cookie}",
            "Referer": "https://www.strava.com/dashboard",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise SystemExit(f"HTTP {response.status}")
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise SystemExit(f"Błąd sieci: {exc.reason}") from exc


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _sport(entry) -> str:
    icon = entry.select_one('[data-testid="activity-icon"]')
    title = icon.find("title") if icon else None
    raw = _text(title)
    if "." in raw:
        raw = raw.rsplit(".", 1)[-1]
    return SPORT_MAP.get(raw.lower(), raw or "?")


def _stats(entry) -> tuple[str, str]:
    container = entry.select_one('[data-testid="activity_entry_container"]')
    stats = container.select_one('ul[class*="Stats_listStats"]') if container else None
    distance = ""
    moving_time = ""

    if stats:
        for item in stats.find_all("li"):
            value = item.select_one('[class*="Stat_statValue"]')
            text = _text(value)
            units = {abbr.get("title", "").lower() for abbr in item.find_all("abbr")}
            if units & {"kilometers", "miles", "kilometry", "mile"}:
                distance = text
            elif units & {
                "minute",
                "hour",
                "second",
                "minuta",
                "godzina",
                "sekunda",
            }:
                moving_time = text

    return distance, moving_time


def current_athlete_id(html: str) -> str | None:
    match = re.search(
        r'"currentAthlete"\s*:\s*\{\s*"id"\s*:\s*"(\d+)"',
        html,
    )
    return match.group(1) if match else None


def parse_entries(html: str) -> list[FeedActivity]:
    soup = BeautifulSoup(html, "html.parser")
    me = current_athlete_id(html)
    activities: list[FeedActivity] = []

    for entry in soup.select('[data-testid="web-feed-entry"]'):
        link = entry.select_one('a[data-testid="activity_name"]')
        if not link:
            continue

        match = re.search(r"/activities/(\d+)", link.get("href", ""))
        if not match:
            continue

        athlete = entry.select_one('[data-testid="owners-name"]')
        athlete_id = None
        if athlete and athlete.get("href"):
            athlete_match = re.search(r"/athletes/(\d+)", athlete["href"])
            athlete_id = athlete_match.group(1) if athlete_match else None

        distance, moving_time = _stats(entry)
        activities.append(
            FeedActivity(
                activity_id=match.group(1),
                athlete_name=_text(athlete) or "?",
                athlete_id=athlete_id,
                title=_text(link) or "(bez nazwy)",
                sport=_sport(entry),
                distance=distance,
                moving_time=moving_time,
                when=_text(entry.select_one('[data-testid="date_at_time"]')),
                kudosed=entry.select_one('[data-testid="filled_kudos"]') is not None,
                kudos_count=_text(entry.select_one('[data-testid="kudos_count"]')) or "0 kudos",
                is_own=bool(athlete_id and me and athlete_id == me),
            )
        )

    return activities


def print_report(activities: list[FeedActivity]) -> None:
    missing = [activity for activity in activities if not activity.kudosed and not activity.is_own]
    own = [activity for activity in activities if activity.is_own]
    done = [activity for activity in activities if activity.kudosed and not activity.is_own]
    print(
        f"Strava feed: {len(activities)} aktywności — "
        f"{len(missing)} bez Twojego kudos, {len(done)} już okudoszonych, "
        f"{len(own)} własnych (pomijane).\n"
    )

    ordered = missing + done + own
    for index, activity in enumerate(ordered, start=1):
        if activity.is_own:
            status = "WŁASNA — pomiń"
        elif activity.kudosed:
            status = "OK"
        else:
            status = "BRAK KUDOS"
        print(f"[{index}] {status} — {activity.athlete_name}")
        print(f"    {activity.title}")
        print(
            f"    {activity.sport} | {activity.distance} | "
            f"{activity.moving_time} | {activity.when}"
        )
        print(f"    {activity.kudos_count} | {activity.url}")
        print()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print_report(parse_entries(fetch_dashboard(load_cookie())))
