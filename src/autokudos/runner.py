"""Pętla pojedynczego uruchomienia bota."""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from autokudos.config import Config, in_active_hours, local_day_bounds
from autokudos.models import RunStats
from autokudos.notify import Notifier
from autokudos.rules import evaluate
from autokudos.store import Store
from autokudos.strava.client import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    StravaClient,
    StravaError,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def run_once(
    config: Config,
    client: StravaClient,
    store: Store,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    ignore_schedule: bool = False,
    max_per_run: int | None = None,
    notifier: Notifier | None = None,
) -> RunStats:
    """Wykonuje jeden przebieg: feed → reguły → limity → kudos → SQLite."""

    started_at = _as_utc(now or datetime.now(UTC))
    stats = RunStats(dry_run=dry_run)
    run_id = store.start_run(started_at=started_at, dry_run=dry_run)
    error_text: str | None = None

    try:
        dashboard = client.fetch_dashboard()
        stats.found = len(dashboard.activities)
        me_id = dashboard.session.athlete_id

        local_now = started_at.astimezone(ZoneInfo(config.app.timezone))
        if not ignore_schedule and not in_active_hours(local_now, config.schedule.active_hours):
            logger.info(
                "Poza aktywnymi godzinami ({}) — kończę bez wysyłki.",
                config.schedule.active_hours,
            )
            stats.skipped = stats.found
            return stats

        day_start, day_end = local_day_bounds(started_at, config.app.timezone)
        sent_today = store.count_sent_between(day_start, day_end)
        remaining_today = max(0, config.limits.max_per_day - sent_today)
        if remaining_today <= 0:
            logger.warning(
                "Dzienny limit {} kudos osiągnięty (wysłane dziś: {}).",
                config.limits.max_per_day,
                sent_today,
            )
            stats.skipped = stats.found
            return stats

        run_limit = min(config.limits.max_per_run, remaining_today)
        if max_per_run is not None:
            run_limit = min(run_limit, max(0, max_per_run))

        if run_limit <= 0:
            stats.skipped = stats.found
            return stats

        logger.info(
            "Feed: {} aktywności | limit run: {} | wysłane dziś: {}/{} | tryb: {}",
            stats.found,
            run_limit,
            sent_today,
            config.limits.max_per_day,
            "DRY RUN" if dry_run else "LIVE",
        )

        sends = 0
        consecutive_errors = 0

        for activity in dashboard.activities:
            decision = evaluate(activity, config, now=started_at, me_id=me_id)
            if not decision.allowed:
                logger.debug(
                    "Pomijam {} ({}) — {}: {}",
                    activity.id,
                    activity.athlete_name,
                    decision.reason,
                    decision.detail,
                )
                stats.skipped += 1
                continue

            stats.candidates += 1

            if store.has_sent(activity.id):
                logger.info("Pomijam {} — kudos już wysłany wcześniej.", activity.id)
                stats.skipped += 1
                continue

            if sends >= run_limit:
                logger.info("Limit na ten przebieg ({}) osiągnięty.", run_limit)
                stats.skipped += 1
                continue

            if dry_run:
                logger.info(
                    "[DRY RUN] Kudos dla {} — {} ({})",
                    activity.athlete_name,
                    activity.title,
                    activity.url,
                )
                stats.would_send += 1
                sends += 1
                continue

            if sends > 0:
                low, high = config.limits.delay_seconds
                delay = random.uniform(low, high)
                logger.info("Pauza {:.1f}s przed kolejnym kudos...", delay)
                time.sleep(delay)

            try:
                result = client.send_kudo(activity.id)
            except NotFoundError:
                logger.warning("Aktywność {} nie istnieje — pomijam.", activity.id)
                stats.skipped += 1
                continue
            except AuthError:
                raise
            except ForbiddenError as exc:
                stats.errors += 1
                consecutive_errors += 1
                store.record_kudos(activity, "failed", error=str(exc))
                logger.error("HTTP 403 przy {}: {}", activity.id, exc)
                if config.limits.stop_on_403:
                    stats.aborted = "http_403"
                    logger.error("stop_on_403=true — przerywam przebieg.")
                    break
                if consecutive_errors >= config.limits.max_consecutive_errors:
                    stats.aborted = "too_many_errors"
                    logger.error("Zbyt wiele błędów pod rząd — przerywam.")
                    break
            except StravaError as exc:
                stats.errors += 1
                consecutive_errors += 1
                store.record_kudos(activity, "failed", error=str(exc))
                logger.error("Błąd przy {}: {}", activity.id, exc)
                if consecutive_errors >= config.limits.max_consecutive_errors:
                    stats.aborted = "too_many_errors"
                    logger.error("Zbyt wiele błędów pod rząd — przerywam.")
                    break
            else:
                consecutive_errors = 0
                sends += 1
                if result.verified:
                    stats.sent += 1
                    store.record_kudos(activity, "sent")
                    logger.success(
                        "Kudos dla {} — {}",
                        activity.athlete_name,
                        activity.url,
                    )
                else:
                    stats.errors += 1
                    store.record_kudos(
                        activity,
                        "unverified",
                        error="Nie potwierdzono kudos po wysłaniu",
                    )
                    logger.warning(
                        "Wysłano, ale nie potwierdzono kudos: {}",
                        activity.url,
                    )

        return stats
    except AuthError as exc:
        stats.errors += 1
        stats.aborted = "session_expired"
        error_text = "Sesja Strava wygasła."
        logger.error("{}", exc)
        if notifier is not None:
            notifier.send_session_expired()
        raise
    except Exception as exc:
        stats.errors += 1
        stats.aborted = "error"
        error_text = exc.__class__.__name__
        logger.exception("Nieoczekiwany błąd przebiegu: {}", exc.__class__.__name__)
        raise
    finally:
        store.finish_run(
            run_id,
            stats,
            finished_at=datetime.now(UTC),
            error=error_text,
        )
        if (
            notifier is not None
            and not dry_run
            and stats.aborted != "session_expired"
            and (stats.sent or stats.errors)
        ):
            notifier.send_run_summary(stats)
