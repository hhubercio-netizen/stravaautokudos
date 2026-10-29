from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import yaml

from autokudos.config import (
    ConfigError,
    get_session_cookie,
    in_active_hours,
    load_config,
    load_env_file,
    local_day_bounds,
    resolve_database_path,
)
from tests.support import make_config


def _write_config(tmp_path, data: dict):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_config_from_yaml(tmp_path) -> None:
    data = make_config().model_dump(mode="json")
    path = _write_config(tmp_path, data)

    config = load_config(path)

    assert config.app.timezone == "Europe/Warsaw"
    assert [target.id for target in config.targets.include] == [141888360, 171997323]
    assert config.limits.delay_seconds == (0.0, 0.0)


def test_rejects_invalid_active_hours(tmp_path) -> None:
    data = make_config().model_dump(mode="json")
    data["schedule"]["active_hours"] = "7-23"

    with pytest.raises(ConfigError, match="active_hours"):
        load_config(_write_config(tmp_path, data))


def test_rejects_duplicate_whitelist_entries(tmp_path) -> None:
    data = make_config().model_dump(mode="json")
    data["targets"]["include"].append({"id": 141888360, "name": "Duplikat"})

    with pytest.raises(ConfigError, match="Zduplikowany"):
        load_config(_write_config(tmp_path, data))


def test_rejects_exclude_overlapping_include(tmp_path) -> None:
    data = make_config().model_dump(mode="json")
    data["targets"]["exclude"] = [141888360]

    with pytest.raises(ConfigError, match="include i exclude"):
        load_config(_write_config(tmp_path, data))


def test_rejects_unknown_config_key(tmp_path) -> None:
    data = make_config().model_dump(mode="json")
    data["app"]["nieznany_klucz"] = True

    with pytest.raises(ConfigError, match="nieznany_klucz"):
        load_config(_write_config(tmp_path, data))


def test_in_active_hours_normal_window() -> None:
    assert in_active_hours(datetime(2026, 10, 29, 8, 0, tzinfo=UTC), "07:00-23:00")
    assert not in_active_hours(datetime(2026, 10, 29, 23, 0, tzinfo=UTC), "07:00-23:00")
    assert not in_active_hours(datetime(2026, 10, 29, 6, 59, tzinfo=UTC), "07:00-23:00")


def test_in_active_hours_overnight_window() -> None:
    assert in_active_hours(datetime(2026, 10, 29, 23, 30, tzinfo=UTC), "23:00-07:00")
    assert in_active_hours(datetime(2026, 10, 29, 6, 30, tzinfo=UTC), "23:00-07:00")
    assert not in_active_hours(datetime(2026, 10, 29, 12, 0, tzinfo=UTC), "23:00-07:00")


def test_local_day_bounds_warsaw() -> None:
    start, end = local_day_bounds(datetime(2026, 10, 29, 12, 0, tzinfo=UTC), "Europe/Warsaw")

    assert start.isoformat() == "2026-10-28T23:00:00+00:00"
    assert end.isoformat() == "2026-10-29T23:00:00+00:00"


def test_session_cookie_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("STRAVA_SESSION_COOKIE", "abc123")

    assert get_session_cookie() == "abc123"


def test_session_cookie_from_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STRAVA_SESSION_COOKIE", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text('STRAVA_SESSION_COOKIE="xyz789"\n', encoding="utf-8")

    assert get_session_cookie(env_file) == "xyz789"


def test_session_cookie_missing_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STRAVA_SESSION_COOKIE", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("# brak cookie\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="STRAVA_SESSION_COOKIE"):
        get_session_cookie(env_file)


def test_load_env_file_does_not_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "z_env")
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=z_pliku\n", encoding="utf-8")

    load_env_file(env_file)

    assert os.environ["TELEGRAM_BOT_TOKEN"] == "z_env"


def test_resolve_database_path_relative_to_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AUTOKUDOS_DB", raising=False)
    config = make_config()
    config_path = tmp_path / "config.yaml"

    path = resolve_database_path(config, config_path)

    assert path == tmp_path / "data" / "test.db"


def test_resolve_database_path_env_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOKUDOS_DB", str(tmp_path / "custom.db"))

    path = resolve_database_path(make_config(), tmp_path / "config.yaml")

    assert path == tmp_path / "custom.db"
