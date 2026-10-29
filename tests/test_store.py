from __future__ import annotations

from datetime import UTC, datetime, timedelta

from autokudos.models import RunStats
from autokudos.store import Store
from tests.support import make_activity

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_record_sent_is_idempotent(tmp_path) -> None:
    with Store(tmp_path / "test.db") as store:
        activity = make_activity("123")

        assert store.has_sent("123") is False
        store.record_kudos(activity, "sent")
        assert store.has_sent("123") is True
        assert store.count_by_status("sent") == 1

        store.record_kudos(activity, "failed", error="nie powinno nadpisać")
        record = store.get_kudos("123")
        assert record is not None
        assert record["status"] == "sent"
        assert record["error"] is None


def test_count_sent_between_includes_unverified(tmp_path) -> None:
    with Store(tmp_path / "test.db") as store:
        store.record_kudos(make_activity("1"), "sent", when=NOW)
        store.record_kudos(make_activity("2"), "unverified", when=NOW)
        store.record_kudos(make_activity("3"), "failed", when=NOW)

        assert store.count_sent_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1)) == 2
        assert store.count_sent_between(NOW + timedelta(hours=1), NOW + timedelta(hours=2)) == 0


def test_run_history(tmp_path) -> None:
    with Store(tmp_path / "test.db") as store:
        run_id = store.start_run(started_at=NOW, dry_run=False)
        stats = RunStats(
            dry_run=False,
            found=5,
            candidates=2,
            sent=1,
            would_send=0,
            skipped=4,
            errors=0,
        )
        store.finish_run(run_id, stats, finished_at=NOW + timedelta(seconds=10))

        last = store.last_run()
        assert last is not None
        assert last["id"] == run_id
        assert last["dry_run"] == 0
        assert last["found"] == 5
        assert last["candidates"] == 2
        assert last["sent"] == 1
        assert last["skipped"] == 4
        assert last["errors"] == 0
        assert last["aborted"] is None
