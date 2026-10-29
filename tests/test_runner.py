from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autokudos.models import RunStats
from autokudos.runner import run_once
from autokudos.store import Store
from autokudos.strava.client import AuthError, ForbiddenError, StravaError
from tests.support import FakeClient, make_activity, make_config

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class AuthFailClient(FakeClient):
    def fetch_dashboard(self):
        raise AuthError("Sesja wygasła")


class FakeNotifier:
    def __init__(self) -> None:
        self.summaries: list[RunStats] = []
        self.session_expired = 0

    def send_session_expired(self) -> bool:
        self.session_expired += 1
        return True

    def send_run_summary(self, stats: RunStats) -> bool:
        self.summaries.append(stats)
        return True


def test_dry_run_does_not_send_or_record(tmp_path) -> None:
    client = FakeClient([make_activity("1")])
    with Store(tmp_path / "test.db") as store:
        stats = run_once(
            make_config(),
            client,
            store,
            dry_run=True,
            now=NOW,
        )

        assert stats.found == 1
        assert stats.candidates == 1
        assert stats.would_send == 1
        assert stats.sent == 0
        assert stats.errors == 0
        assert client.sent == []
        assert store.has_sent("1") is False


def test_live_run_sends_and_second_run_is_idempotent(tmp_path) -> None:
    client = FakeClient([make_activity("1")])
    with Store(tmp_path / "test.db") as store:
        first = run_once(make_config(), client, store, dry_run=False, now=NOW)
        second = run_once(make_config(), client, store, dry_run=False, now=NOW)

        assert first.sent == 1
        assert first.errors == 0
        assert client.sent == ["1"]
        assert store.has_sent("1") is True

        assert second.sent == 0
        assert second.skipped == 1
        assert client.sent == ["1"]


def test_max_per_run_limit(tmp_path) -> None:
    activities = [make_activity(str(index)) for index in range(1, 4)]
    client = FakeClient(activities)
    config = make_config(limits={"max_per_run": 2})

    with Store(tmp_path / "test.db") as store:
        stats = run_once(config, client, store, dry_run=False, now=NOW)

        assert stats.candidates == 3
        assert stats.sent == 2
        assert client.sent == ["1", "2"]


def test_daily_limit_blocks_sending(tmp_path) -> None:
    client = FakeClient([make_activity("new")])
    config = make_config(limits={"max_per_day": 1})

    with Store(tmp_path / "test.db") as store:
        store.record_kudos(make_activity("old"), "sent", when=NOW)
        stats = run_once(config, client, store, dry_run=False, now=NOW)

        assert stats.sent == 0
        assert stats.skipped == 1
        assert client.sent == []


def test_outside_active_hours_skips(tmp_path) -> None:
    client = FakeClient([make_activity("1")])
    config = make_config(schedule={"active_hours": "07:00-08:00"})

    with Store(tmp_path / "test.db") as store:
        stats = run_once(config, client, store, dry_run=False, now=NOW)

        assert stats.sent == 0
        assert stats.skipped == 1
        assert client.sent == []

        forced = run_once(
            config,
            client,
            store,
            dry_run=False,
            now=NOW,
            ignore_schedule=True,
        )
        assert forced.sent == 1


def test_auth_error_aborts_and_notifies(tmp_path) -> None:
    client = AuthFailClient([])
    notifier = FakeNotifier()

    with Store(tmp_path / "test.db") as store:
        with pytest.raises(AuthError):
            run_once(
                make_config(),
                client,
                store,
                dry_run=False,
                now=NOW,
                notifier=notifier,  # type: ignore[arg-type]
            )

        last = store.last_run()
        assert last is not None
        assert last["aborted"] == "session_expired"
        assert last["errors"] == 1
        assert notifier.session_expired == 1
        assert notifier.summaries == []


def test_consecutive_errors_abort_run(tmp_path) -> None:
    client = FakeClient([make_activity("1"), make_activity("2")])
    client.failures["1"] = StravaError("boom")
    config = make_config(limits={"max_consecutive_errors": 1})

    with Store(tmp_path / "test.db") as store:
        stats = run_once(config, client, store, dry_run=False, now=NOW)

        assert stats.errors == 1
        assert stats.aborted == "too_many_errors"
        assert client.sent == []
        assert store.get_kudos("1")["status"] == "failed"


def test_403_stops_run_when_configured(tmp_path) -> None:
    client = FakeClient([make_activity("1"), make_activity("2")])
    client.failures["1"] = ForbiddenError(403, "blocked")
    config = make_config(limits={"stop_on_403": True})

    with Store(tmp_path / "test.db") as store:
        stats = run_once(config, client, store, dry_run=False, now=NOW)

        assert stats.errors == 1
        assert stats.aborted == "http_403"
        assert client.sent == []
