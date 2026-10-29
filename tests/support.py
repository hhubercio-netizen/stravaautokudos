from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from autokudos.config import Config
from autokudos.models import Activity, Dashboard, SendResult, Session
from autokudos.strava.client import HttpResponse

ME_ID = "1783870285"
ME_NAME = "Jakub Mrzygłód"


def activity_entry(
    activity_id: str = "123",
    *,
    athlete_id: str = "141888360",
    athlete_name: str = "Oskar Kotzian",
    sport: str = "VirtualRide",
    start_date: str = "2026-10-29T10:00:00Z",
    distance_html: str = "25,28<abbr class='unit' title='kilometry'> km</abbr>",
    has_kudoed: bool = False,
    can_kudo: bool = True,
    kudos_count: int = 3,
    is_own: bool = False,
) -> dict[str, Any]:
    return {
        "viewingAthlete": {"id": ME_ID, "name": ME_NAME},
        "entity": "Activity",
        "activity": {
            "id": activity_id,
            "activityName": f"Trening {activity_id}",
            "type": sport,
            "athlete": {
                "athleteId": athlete_id,
                "athleteName": athlete_name,
            },
            "ownedByCurrentAthlete": is_own,
            "startDate": start_date,
            "stats": [
                {"key": "stat_one", "value": distance_html},
                {
                    "key": "stat_three",
                    "value": "45<abbr class='unit' title='minuta'>min</abbr> "
                    "9<abbr class='unit' title='sekunda'>s</abbr>",
                },
            ],
            "timeAndLocation": {"displayDateAtTime": "Dzisiaj o 12:00"},
            "kudosAndComments": {
                "hasKudoed": has_kudoed,
                "canKudo": can_kudo,
                "kudosCount": kudos_count,
            },
        },
    }


def dashboard_payload(
    entries: list[dict[str, Any]],
    *,
    current_athlete: dict[str, Any] | None = None,
) -> dict[str, Any]:
    athlete = current_athlete or {
        "id": ME_ID,
        "firstName": "Jakub",
        "lastName": "Mrzygłód",
    }
    return {
        "props": {
            "pageProps": {
                "dashboardData": {
                    "currentAthlete": athlete,
                    "feed": {"entries": entries},
                }
            }
        },
        "page": "/dashboard",
    }


def dashboard_html(
    entries: list[dict[str, Any]] | None = None,
    *,
    csrf: str = "test-csrf-token",
    payload: dict[str, Any] | None = None,
) -> str:
    data = payload if payload is not None else dashboard_payload(entries or [])
    return (
        "<!doctype html><html><head>"
        f'<meta name="csrf" content="{csrf}">'
        "</head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
        "</body></html>"
    )


def make_activity(
    activity_id: str = "123",
    *,
    athlete_id: str = "141888360",
    athlete_name: str = "Oskar Kotzian",
    sport: str = "VirtualRide",
    start_date: datetime | None = None,
    distance_km: float = 25.0,
    has_kudoed: bool = False,
    can_kudo: bool = True,
    is_own: bool = False,
) -> Activity:
    return Activity(
        id=activity_id,
        athlete_id=athlete_id,
        athlete_name=athlete_name,
        title=f"Trening {activity_id}",
        sport=sport,
        start_date=start_date or datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
        distance_km=distance_km,
        moving_time="45 min",
        kudos_count=3,
        has_kudoed=has_kudoed,
        can_kudo=can_kudo,
        is_own=is_own,
        display_date="Dzisiaj o 12:00",
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def make_config(**overrides: Any) -> Config:
    data: dict[str, Any] = {
        "app": {
            "timezone": "Europe/Warsaw",
            "dry_run": False,
            "log_level": "INFO",
            "database": "data/test.db",
        },
        "schedule": {"every_minutes": 45, "active_hours": "00:00-23:59"},
        "targets": {
            "include": [
                {"id": 141888360, "name": "Oskar Kotzian"},
                {"id": 171997323, "name": "Damian Huminiak"},
            ]
        },
        "rules": {
            "sports": ["Run", "Ride", "VirtualRide", "Walk", "Hike", "Swim"],
            "min_distance_km": 0,
            "max_age_hours": 36,
        },
        "limits": {
            "max_per_run": 10,
            "max_per_day": 60,
            "delay_seconds": [0, 0],
            "stop_on_403": True,
            "max_consecutive_errors": 3,
        },
    }
    _deep_merge(data, overrides)
    return Config.model_validate(data)


class FakeTransport:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], HttpResponse | Exception] = {}
        self.requests: list[dict[str, Any]] = []

    def add(
        self,
        method: str,
        url: str,
        *,
        status: int = 200,
        json_data: Any | None = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        response_url: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        if exc is not None:
            self.routes[(method.upper(), url)] = exc
            return

        response_headers = dict(headers or {})
        if json_data is not None:
            body = json.dumps(json_data).encode("utf-8")
            response_headers.setdefault("content-type", "application/json")
        else:
            body = (text or "").encode("utf-8")
            response_headers.setdefault("content-type", "text/html; charset=utf-8")

        self.routes[(method.upper(), url)] = HttpResponse(
            status_code=status,
            url=response_url or url,
            headers={key.lower(): value for key, value in response_headers.items()},
            body=body,
        )

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
                "timeout": timeout,
            }
        )
        try:
            response = self.routes[(method.upper(), url)]
        except KeyError:
            raise AssertionError(f"Brak zamockowanej trasy: {method} {url}") from None
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(
        self,
        activities: list[Activity],
        *,
        me_id: str = ME_ID,
        me_name: str = ME_NAME,
    ) -> None:
        self.activities = activities
        self.session = Session(me_id, me_name, "test-csrf-token")
        self.sent: list[str] = []
        self.failures: dict[str, Exception] = {}

    def fetch_dashboard(self) -> Dashboard:
        return Dashboard(
            activities=list(self.activities),
            session=self.session,
            csrf=self.session.csrf,
        )

    def send_kudo(self, activity_id: str, *, verify: bool = True) -> SendResult:
        if activity_id in self.failures:
            raise self.failures[activity_id]
        self.sent.append(activity_id)
        return SendResult(activity_id=activity_id, response_ok=True, verified=True)
