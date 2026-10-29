"""Reguły decydujące, czy aktywność kwalifikuje się do kudos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from autokudos.config import Config
from autokudos.models import Activity


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str
    detail: str = ""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate(
    activity: Activity,
    config: Config,
    *,
    now: datetime,
    me_id: str,
) -> Decision:
    """Zwraca decyzję dla jednej aktywności.

    Kolejność jest celowa: najpierw bezpieczeństwo (własne aktywności,
    whitelist), potem filtry jakościowe, na końcu stan kudos.
    """

    now_utc = _as_utc(now)
    rules = config.rules

    if rules.skip_own and (activity.is_own or activity.athlete_id == me_id):
        return Decision(False, "own", "własna aktywność")

    include_ids = {str(target.id) for target in config.targets.include}
    exclude_ids = {str(item) for item in config.targets.exclude}

    if activity.athlete_id in exclude_ids:
        return Decision(False, "excluded", "zawodnik na liście exclude")
    if activity.athlete_id not in include_ids:
        return Decision(
            False,
            "not_whitelisted",
            f"athlete_id {activity.athlete_id or '?'} poza whitelistą",
        )

    allowed_sports = {sport.lower() for sport in rules.sports}
    if activity.sport.lower() not in allowed_sports:
        return Decision(False, "sport", f"nieobsługiwany sport: {activity.sport}")

    if activity.distance_km < rules.min_distance_km:
        return Decision(
            False,
            "min_distance",
            f"{activity.distance_km:.2f} km < {rules.min_distance_km:.2f} km",
        )

    start = _as_utc(activity.start_date)
    age_hours = (now_utc - start).total_seconds() / 3600.0
    if age_hours < -1:
        return Decision(False, "future", "aktywność z przyszłości (błąd zegara?)")
    if age_hours > rules.max_age_hours:
        return Decision(
            False,
            "too_old",
            f"{age_hours:.1f} h > {rules.max_age_hours:.1f} h",
        )

    if rules.skip_if_kudosed and activity.has_kudoed:
        return Decision(False, "already_kudosed", "kudos już wysłany")
    if rules.skip_if_kudosed and not activity.can_kudo:
        return Decision(False, "cannot_kudo", "Strava nie pozwala dać kudos")

    return Decision(True, "ok")
