from __future__ import annotations

from datetime import UTC, datetime, timedelta

from autokudos.rules import evaluate
from tests.support import ME_ID, make_activity, make_config

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_allows_whitelisted_recent_activity() -> None:
    decision = evaluate(
        make_activity(start_date=NOW - timedelta(hours=2)),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is True
    assert decision.reason == "ok"


def test_skips_own_activity() -> None:
    decision = evaluate(
        make_activity(athlete_id=ME_ID, athlete_name="Jakub Mrzygłód", is_own=True),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "own"


def test_skips_athlete_outside_whitelist() -> None:
    decision = evaluate(
        make_activity(athlete_id="999", athlete_name="Ktoś Inny"),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "not_whitelisted"


def test_skips_excluded_athlete() -> None:
    config = make_config(
        targets={
            "include": [{"id": 141888360, "name": "Oskar Kotzian"}],
            "exclude": [171997323],
        }
    )
    decision = evaluate(
        make_activity(athlete_id="171997323", athlete_name="Damian Huminiak"),
        config,
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "excluded"


def test_skips_unsupported_sport() -> None:
    decision = evaluate(
        make_activity(sport="Yoga"),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "sport"


def test_skips_too_short_activity() -> None:
    config = make_config(
        rules={
            "sports": ["VirtualRide"],
            "min_distance_km": 10,
            "max_age_hours": 36,
        }
    )
    decision = evaluate(
        make_activity(distance_km=5),
        config,
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "min_distance"


def test_skips_too_old_activity() -> None:
    decision = evaluate(
        make_activity(start_date=NOW - timedelta(hours=48)),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "too_old"


def test_skips_future_activity() -> None:
    decision = evaluate(
        make_activity(start_date=NOW + timedelta(hours=2)),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "future"


def test_skips_already_kudosed_activity() -> None:
    decision = evaluate(
        make_activity(has_kudoed=True, can_kudo=False),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "already_kudosed"


def test_skips_when_strava_disallows_kudos() -> None:
    decision = evaluate(
        make_activity(can_kudo=False),
        make_config(),
        now=NOW,
        me_id=ME_ID,
    )

    assert decision.allowed is False
    assert decision.reason == "cannot_kudo"
