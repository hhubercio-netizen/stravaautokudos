from __future__ import annotations

import pytest

from autokudos.strava.client import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    StravaClient,
    StravaError,
)
from tests.support import ME_ID, FakeTransport, activity_entry, dashboard_html

DASHBOARD_URL = "https://www.strava.com/dashboard?num_entries=50"
LOGIN_URL = "https://www.strava.com/login"
KUDO_URL = "https://www.strava.com/feed/activity/123/kudo"
KUDOS_URL = "https://www.strava.com/feed/activity/123/kudos"


def _transport_with_dashboard(csrf: str = "csrf-abc") -> FakeTransport:
    transport = FakeTransport()
    transport.add(
        "GET",
        DASHBOARD_URL,
        text=dashboard_html([activity_entry("123")], csrf=csrf),
    )
    return transport


def test_fetch_dashboard_parses_feed_and_csrf() -> None:
    transport = _transport_with_dashboard()

    with StravaClient("cookie-value", transport=transport) as client:
        dashboard = client.fetch_dashboard()

    assert dashboard.session.athlete_id == ME_ID
    assert dashboard.session.athlete_name == "Jakub Mrzygłód"
    assert dashboard.csrf == "csrf-abc"
    assert len(dashboard.activities) == 1
    assert dashboard.activities[0].id == "123"

    request = transport.requests[-1]
    assert request["headers"]["Cookie"] == "_strava4_session=cookie-value"


def test_login_redirect_raises_auth_error() -> None:
    transport = FakeTransport()
    transport.add(
        "GET",
        DASHBOARD_URL,
        text="login",
        response_url=LOGIN_URL,
    )

    with (
        StravaClient("expired", transport=transport) as client,
        pytest.raises(AuthError, match="wygasła"),
    ):
        client.fetch_dashboard()


def test_kudos_info() -> None:
    transport = FakeTransport()
    transport.add(
        "GET",
        KUDOS_URL,
        json_data={
            "is_owner": False,
            "kudosable": True,
            "athletes": [{"id": 1, "id_str": "1"}, {"id": 2}],
        },
    )

    with StravaClient("cookie", transport=transport) as client:
        info = client.get_kudos_info("123")

    assert info.activity_id == "123"
    assert info.is_owner is False
    assert info.kudosable is True
    assert info.athlete_ids == frozenset({"1", "2"})
    assert info.count == 2


def test_send_kudo_posts_json_null_and_verifies() -> None:
    transport = _transport_with_dashboard(csrf="csrf-abc")
    transport.add("POST", KUDO_URL, json_data={"success": "true"})
    transport.add(
        "GET",
        KUDOS_URL,
        json_data={
            "is_owner": False,
            "kudosable": False,
            "athletes": [{"id": int(ME_ID), "id_str": ME_ID}],
        },
    )

    with StravaClient("cookie", transport=transport) as client:
        result = client.send_kudo("123")

    assert result.response_ok is True
    assert result.verified is True

    post_request = next(request for request in transport.requests if request["method"] == "POST")
    assert post_request["headers"]["X-CSRF-Token"] == "csrf-abc"
    assert post_request["headers"]["Content-Type"] == "application/json"
    assert post_request["body"] == b"null"


def test_send_kudo_rejects_unsuccessful_response() -> None:
    transport = _transport_with_dashboard()
    transport.add("POST", KUDO_URL, json_data={"success": "false"})

    with (
        StravaClient("cookie", transport=transport) as client,
        pytest.raises(StravaError, match="nie potwierdziła"),
    ):
        client.send_kudo("123", verify=False)


def test_403_raises_forbidden_error() -> None:
    transport = _transport_with_dashboard()
    transport.add("POST", KUDO_URL, status=403)

    with (
        StravaClient("cookie", transport=transport) as client,
        pytest.raises(ForbiddenError),
    ):
        client.send_kudo("123", verify=False)


def test_429_raises_rate_limit_error() -> None:
    transport = _transport_with_dashboard()
    transport.add("POST", KUDO_URL, status=429)

    with (
        StravaClient("cookie", transport=transport) as client,
        pytest.raises(RateLimitError),
    ):
        client.send_kudo("123", verify=False)


def test_404_raises_not_found_error() -> None:
    transport = FakeTransport()
    transport.add("GET", "https://www.strava.com/feed/activity/999/kudos", status=404)

    with (
        StravaClient("cookie", transport=transport) as client,
        pytest.raises(NotFoundError),
    ):
        client.get_kudos_info("999")
