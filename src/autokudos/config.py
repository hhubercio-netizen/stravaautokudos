"""Ładowanie i walidacja konfiguracji bota."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(ValueError):
    """Konfiguracja jest niepoprawna albo brakuje wymaganych danych."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_ACTIVE_HOURS_RE = re.compile(
    r"^(?P<start_h>[01]\d|2[0-3]):(?P<start_m>[0-5]\d)"
    r"-(?P<end_h>[01]\d|2[0-3]):(?P<end_m>[0-5]\d)$"
)


class AppConfig(StrictModel):
    timezone: str = "Europe/Warsaw"
    dry_run: bool = True
    log_level: str = "INFO"
    database: str = "data/autokudos.db"

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Nieznana strefa czasowa {value!r}. Na Windows zainstaluj pakiet 'tzdata'."
            ) from exc
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper().strip()
        allowed = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"log_level musi być jednym z: {', '.join(sorted(allowed))}")
        return normalized


class ScheduleConfig(StrictModel):
    every_minutes: int = Field(default=45, ge=5, le=24 * 60)
    active_hours: str = "07:00-23:00"

    @field_validator("active_hours")
    @classmethod
    def _validate_active_hours(cls, value: str) -> str:
        normalized = value.strip()
        if not _ACTIVE_HOURS_RE.fullmatch(normalized):
            raise ValueError("active_hours musi mieć format HH:MM-HH:MM, np. 07:00-23:00")
        return normalized


class Target(StrictModel):
    id: int = Field(gt=0)
    name: str = Field(min_length=1)


class TargetsConfig(StrictModel):
    mode: Literal["whitelist"] = "whitelist"
    include: list[Target] = Field(min_length=1)
    exclude: list[int] = Field(default_factory=list)

    @field_validator("include")
    @classmethod
    def _unique_targets(cls, value: list[Target]) -> list[Target]:
        seen: set[int] = set()
        for target in value:
            if target.id in seen:
                raise ValueError(f"Zduplikowany athlete_id na whiteliście: {target.id}")
            seen.add(target.id)
        return value

    @model_validator(mode="after")
    def _exclude_not_in_include(self) -> TargetsConfig:
        include_ids = {target.id for target in self.include}
        overlap = include_ids.intersection(self.exclude)
        if overlap:
            raise ValueError(
                "Te same athlete_id są jednocześnie w include i exclude: "
                + ", ".join(str(item) for item in sorted(overlap))
            )
        return self


class RulesConfig(StrictModel):
    sports: list[str] = Field(
        default_factory=lambda: [
            "Run",
            "Ride",
            "VirtualRide",
            "VirtualRun",
            "Walk",
            "Hike",
            "Swim",
        ]
    )
    min_distance_km: float = Field(default=0, ge=0)
    max_age_hours: float = Field(default=36, gt=0)
    skip_own: bool = True
    skip_if_kudosed: bool = True

    @field_validator("sports")
    @classmethod
    def _normalize_sports(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for sport in value:
            normalized = sport.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                result.append(normalized)
        if not result:
            raise ValueError("rules.sports nie może być puste")
        return result


class LimitsConfig(StrictModel):
    max_per_run: int = Field(default=10, ge=1)
    max_per_day: int = Field(default=60, ge=1)
    delay_seconds: tuple[float, float] = (25.0, 90.0)
    stop_on_403: bool = True
    max_consecutive_errors: int = Field(default=3, ge=1)

    @field_validator("delay_seconds")
    @classmethod
    def _validate_delay(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = value
        if low < 0 or high < low:
            raise ValueError("delay_seconds musi być parą [min, max], gdzie 0 <= min <= max")
        return float(low), float(high)


class TelegramConfig(StrictModel):
    enabled: bool = False
    chat_id: str = ""
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"


class NotifyConfig(StrictModel):
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class Config(StrictModel):
    app: AppConfig = Field(default_factory=AppConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    targets: TargetsConfig
    rules: RulesConfig = Field(default_factory=RulesConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)


def load_config(path: str | Path = "config.yaml") -> Config:
    """Wczytuje YAML i zwraca zwalidowaną konfigurację."""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(
            f"Nie znaleziono pliku konfiguracji: {config_path}. "
            "Skopiuj config.example.yaml do config.yaml."
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Błąd składni YAML w {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Plik {config_path} musi zawierać mapę YAML (klucz: wartość).")

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "(root)"
            details.append(f"  - {location}: {error['msg']}")
        raise ConfigError(
            f"Nieprawidłowa konfiguracja w {config_path}:\n" + "\n".join(details)
        ) from exc


def read_env_file(path: Path) -> dict[str, str]:
    """Czyta prosty plik .env bez nadpisywania środowiska."""

    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def find_env_file(config_path: str | Path | None = None) -> Path | None:
    """Szuka .env w katalogu roboczym, a potem obok konfiguracji."""

    candidates = [Path.cwd() / ".env"]
    if config_path is not None:
        candidates.append(Path(config_path).resolve().parent / ".env")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Wczytuje .env do os.environ (bez nadpisywania istniejących zmiennych)."""

    values = read_env_file(path) if path is not None else {}
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def get_session_cookie(env_file: Path | None = None) -> str:
    """Zwraca cookie sesji Strava z env lub .env. Nigdy go nie loguje."""

    value = os.environ.get("STRAVA_SESSION_COOKIE")
    if value and value.strip():
        return value.strip().strip('"').strip("'")

    if env_file is not None:
        value = read_env_file(env_file).get("STRAVA_SESSION_COOKIE")
        if value and value.strip():
            return value.strip().strip('"').strip("'")

    raise ConfigError(
        "Brak STRAVA_SESSION_COOKIE. Ustaw zmienną środowiskową albo wpisz cookie do .env."
    )


def resolve_database_path(config: Config, config_path: str | Path | None = None) -> Path:
    """Ścieżka bazy: AUTOKUDOS_DB > app.database, względna do pliku konfiguracji."""

    raw = os.environ.get("AUTOKUDOS_DB") or config.app.database
    path = Path(raw).expanduser()
    if not path.is_absolute():
        base = Path(config_path).resolve().parent if config_path else Path.cwd()
        path = base / path
    return path


def parse_active_hours(value: str) -> tuple[time, time]:
    match = _ACTIVE_HOURS_RE.fullmatch(value.strip())
    if not match:
        raise ConfigError(f"Niepoprawne active_hours: {value!r}")
    return (
        time(int(match.group("start_h")), int(match.group("start_m"))),
        time(int(match.group("end_h")), int(match.group("end_m"))),
    )


def in_active_hours(now: datetime, window: str) -> bool:
    """Czy `now` mieści się w oknie, z obsługą okna przez północ."""

    start, end = parse_active_hours(window)
    current = now.timetz().replace(tzinfo=None) if now.tzinfo else now.time()
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def local_day_bounds(now: datetime, tz_name: str) -> tuple[datetime, datetime]:
    """Granice lokalnego dnia w UTC, do limitu dziennego."""

    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
