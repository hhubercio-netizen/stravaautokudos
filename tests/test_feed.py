from __future__ import annotations

import pytest

from autokudos.strava.feed import FeedParseError, parse_dashboard
from tests.support import (
    ME_ID,
    activity_entry,
    dashboard_html,
    dashboard_payload,
)


def test_parses_activity_fields() -> None:
    snapshot = parse_dashboard(dashboard_html([activity_entry("20770288613")]))

    assert snapshot.current_athlete_id == ME_ID
    assert snapshot.current_athlete_name == "Jakub Mrzygłód"
    assert len(snapshot.activities) == 1

    activity = snapshot.activities[0]
    assert activity.id == "20770288613"
    assert activity.athlete_id == "141888360"
    assert activity.athlete_name == "Oskar Kotzian"
    assert activity.sport == "VirtualRide"
    assert activity.distance_km == pytest.approx(25.28)
    assert activity.moving_time == "45 min 9 s"
    assert activity.kudos_count == 3
    assert activity.has_kudoed is False
    assert activity.can_kudo is True
    assert activity.is_own is False
    assert activity.display_date == "Dzisiaj o 12:00"
    assert activity.start_date.isoformat() == "2026-10-29T10:00:00+00:00"


def test_marks_own_activity() -> None:
    snapshot = parse_dashboard(
        dashboard_html(
            [activity_entry("1", athlete_id=ME_ID, athlete_name="Jakub Mrzygłód", is_own=True)]
        )
    )

    assert snapshot.activities[0].is_own is True


def test_converts_miles_to_km() -> None:
    snapshot = parse_dashboard(
        dashboard_html(
            [
                activity_entry(
                    "1",
                    distance_html="10<abbr class='unit' title='miles'> mi</abbr>",
                )
            ]
        )
    )

    assert snapshot.activities[0].distance_km == pytest.approx(16.093, abs=0.001)


def test_converts_meters_to_km() -> None:
    snapshot = parse_dashboard(
        dashboard_html(
            [
                activity_entry(
                    "1",
                    distance_html="500<abbr class='unit' title='metry'> m</abbr>",
                )
            ]
        )
    )

    assert snapshot.activities[0].distance_km == pytest.approx(0.5)


def test_parses_thousands_separator() -> None:
    snapshot = parse_dashboard(
        dashboard_html(
            [
                activity_entry(
                    "1",
                    distance_html="1 234,56<abbr class='unit' title='kilometry'> km</abbr>",
                )
            ]
        )
    )

    assert snapshot.activities[0].distance_km == pytest.approx(1234.56)


def test_skips_non_activity_entries() -> None:
    entries = [
        {"entity": "Post", "post": {"id": "1"}},
        activity_entry("2"),
    ]
    snapshot = parse_dashboard(dashboard_html(entries))

    assert [activity.id for activity in snapshot.activities] == ["2"]
    assert snapshot.entry_count == 2


def test_skips_activity_without_valid_start_date() -> None:
    snapshot = parse_dashboard(dashboard_html([activity_entry("1", start_date="")]))

    assert snapshot.activities == []


def test_current_athlete_falls_back_to_viewing_athlete() -> None:
    payload = dashboard_payload([activity_entry("1")])
    del payload["props"]["pageProps"]["dashboardData"]["currentAthlete"]

    snapshot = parse_dashboard(dashboard_html(payload=payload))

    assert snapshot.current_athlete_id == ME_ID
    assert snapshot.current_athlete_name == "Jakub Mrzygłód"


def test_missing_next_data_raises() -> None:
    with pytest.raises(FeedParseError):
        parse_dashboard("<html><body>brak</body></html>")
