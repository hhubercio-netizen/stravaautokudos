from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Activity:
    id: str
    athlete_id: str
    athlete_name: str
    title: str
    sport: str
    start_date: datetime
    distance_km: float
    moving_time: str
    kudos_count: int
    has_kudoed: bool
    can_kudo: bool
    is_own: bool
    display_date: str = ""

    @property
    def url(self) -> str:
        return f"https://www.strava.com/activities/{self.id}"


@dataclass(slots=True)
class Session:
    athlete_id: str
    athlete_name: str
    csrf: str


@dataclass(slots=True)
class Dashboard:
    activities: list[Activity]
    session: Session
    csrf: str


@dataclass(slots=True)
class KudosInfo:
    activity_id: str
    is_owner: bool
    kudosable: bool
    athlete_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def count(self) -> int:
        return len(self.athlete_ids)


@dataclass(slots=True)
class SendResult:
    activity_id: str
    response_ok: bool
    verified: bool


@dataclass(slots=True)
class RunStats:
    dry_run: bool = True
    found: int = 0
    candidates: int = 0
    sent: int = 0
    would_send: int = 0
    skipped: int = 0
    errors: int = 0
    aborted: str | None = None
