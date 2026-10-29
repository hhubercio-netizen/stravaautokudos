"""CLI bota Strava AutoKudos."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import typer
import yaml
from loguru import logger

from autokudos import __version__
from autokudos.config import (
    Config,
    ConfigError,
    find_env_file,
    get_session_cookie,
    load_config,
    load_env_file,
    local_day_bounds,
    resolve_database_path,
)
from autokudos.notify import Notifier
from autokudos.rules import evaluate
from autokudos.runner import run_once
from autokudos.store import Store
from autokudos.strava.client import AuthError, StravaClient, StravaError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Automatyczne kudos na Stravie dla wybranej whitelisty.",
)


@dataclass(slots=True)
class CliContext:
    config: Config
    config_path: Path
    env_file: Path | None
    cookie: str | None
    db_path: Path


def _setup_logging(level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )


def _load_context(config_path: Path, *, require_cookie: bool) -> CliContext:
    config = load_config(config_path)
    env_file = find_env_file(config_path)
    load_env_file(env_file)
    cookie = get_session_cookie(env_file) if require_cookie else None
    db_path = resolve_database_path(config, config_path)
    return CliContext(
        config=config,
        config_path=config_path,
        env_file=env_file,
        cookie=cookie,
        db_path=db_path,
    )


def _fail(message: str, *, code: int = 1) -> None:
    typer.echo(f"Błąd: {message}", err=True)
    raise typer.Exit(code)


def _effective_dry_run(config: Config, *, live: bool, dry_run: bool) -> bool:
    if live and dry_run:
        raise typer.BadParameter("Nie można użyć jednocześnie --live i --dry-run.")
    if dry_run or not live:
        return True
    if config.app.dry_run:
        logger.warning(
            "app.dry_run=true w konfiguracji — pozostaję w dry-run. "
            "Ustaw app.dry_run: false, aby wysyłać kudos."
        )
        return True
    return False


def _print_summary(stats) -> None:
    logger.info(
        "Podsumowanie: znalezione={} kandydaci={} wysłane={} do_wysłania={} pominięte={} błędy={}",
        stats.found,
        stats.candidates,
        stats.sent,
        stats.would_send,
        stats.skipped,
        stats.errors,
    )


@app.command()
def run(
    config: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Ścieżka do pliku konfiguracji YAML.",
    ),
    live: bool = typer.Option(
        False,
        "--live",
        help="Faktycznie wysyłaj kudos. Wymaga app.dry_run: false w konfiguracji.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Wymuś tryb testowy (domyślne zachowanie).",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Powtarzaj przebiegi co schedule.every_minutes zamiast jednego razu.",
    ),
    ignore_schedule: bool = typer.Option(
        False,
        "--ignore-schedule",
        help="Nie respektuj schedule.active_hours (np. do testów ręcznych).",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Nadpisz maksymalną liczbę kudos w tym przebiegu.",
    ),
) -> None:
    """Uruchom bota (domyślnie jeden przebieg w trybie dry-run)."""

    try:
        context = _load_context(config, require_cookie=True)
    except ConfigError as exc:
        _fail(str(exc))

    _setup_logging(context.config.app.log_level)
    effective_dry_run = _effective_dry_run(context.config, live=live, dry_run=dry_run)
    assert context.cookie is not None

    notifier = Notifier(context.config.notify)
    if effective_dry_run:
        logger.info("Tryb DRY RUN — nic nie zostanie wysłane.")
    else:
        logger.warning("Tryb LIVE — kudos będą wysyłane nieodwracalnie.")

    try:
        with StravaClient(context.cookie) as client, Store(context.db_path) as store:
            while True:
                try:
                    stats = run_once(
                        context.config,
                        client,
                        store,
                        dry_run=effective_dry_run,
                        ignore_schedule=ignore_schedule,
                        max_per_run=limit,
                        notifier=notifier,
                    )
                except AuthError as exc:
                    logger.error("{}", exc)
                    raise typer.Exit(2) from exc
                except StravaError as exc:
                    logger.error("{}", exc)
                    raise typer.Exit(1) from exc

                _print_summary(stats)

                if not watch:
                    if stats.errors or stats.aborted:
                        raise typer.Exit(1)
                    return
                if stats.errors or stats.aborted:
                    raise typer.Exit(1)

                interval = context.config.schedule.every_minutes * 60
                logger.info(
                    "Następny przebieg za {} min. Ctrl+C kończy.",
                    context.config.schedule.every_minutes,
                )
                time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Przerwano przez użytkownika.")


@app.command()
def check(
    config: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Ścieżka do pliku konfiguracji YAML.",
    ),
) -> None:
    """Sprawdź sesję Strava, CSRF i kandydatów bez wysyłania kudos."""

    try:
        context = _load_context(config, require_cookie=True)
    except ConfigError as exc:
        _fail(str(exc))

    _setup_logging(context.config.app.log_level)
    assert context.cookie is not None

    try:
        with StravaClient(context.cookie) as client:
            dashboard = client.fetch_dashboard()
    except AuthError as exc:
        _fail(str(exc), code=2)
    except StravaError as exc:
        _fail(str(exc))

    typer.echo(f"Sesja OK: {dashboard.session.athlete_name} ({dashboard.session.athlete_id})")
    typer.echo(f"CSRF: OK ({len(dashboard.csrf)} znaków, wartość nie jest pokazywana)")
    typer.echo(f"Feed: {len(dashboard.activities)} aktywności")

    now = datetime.now(UTC)
    candidates = [
        activity
        for activity in dashboard.activities
        if evaluate(
            activity,
            context.config,
            now=now,
            me_id=dashboard.session.athlete_id,
        ).allowed
    ]
    typer.echo(f"Kandydaci wg reguł: {len(candidates)}")
    for activity in candidates:
        typer.echo(
            f"  - {activity.athlete_name} | {activity.sport} | "
            f"{activity.distance_km:.2f} km | {activity.url}"
        )


@app.command()
def status(
    config: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Ścieżka do pliku konfiguracji YAML.",
    ),
) -> None:
    """Pokaż konfigurację, stan bazy i ostatni przebieg (bez sieci)."""

    try:
        context = _load_context(config, require_cookie=False)
    except ConfigError as exc:
        _fail(str(exc))

    _setup_logging(context.config.app.log_level)
    config_data = context.config

    typer.echo(f"Konfiguracja: {context.config_path}")
    typer.echo(f"Baza: {context.db_path}")
    typer.echo(
        "Whitelist: "
        + ", ".join(f"{target.name} ({target.id})" for target in config_data.targets.include)
    )
    typer.echo(
        f"Limity: {config_data.limits.max_per_run}/przebieg, {config_data.limits.max_per_day}/dzień"
    )
    typer.echo(f"Okno: {config_data.schedule.active_hours} ({config_data.app.timezone})")
    typer.echo(
        "Tryb: "
        + (
            "dry-run (app.dry_run=true)"
            if config_data.app.dry_run
            else "live (app.dry_run=false; do wysyłki wymagane --live)"
        )
    )

    with Store(context.db_path) as store:
        total_sent = store.count_by_status("sent")
        total_unverified = store.count_by_status("unverified")
        total_failed = store.count_by_status("failed")
        day_start, day_end = local_day_bounds(datetime.now(UTC), config_data.app.timezone)
        today_sent = store.count_sent_between(day_start, day_end)
        last_run = store.last_run()

    typer.echo(
        f"Kudos w bazie: sent={total_sent}, unverified={total_unverified}, failed={total_failed}"
    )
    typer.echo(f"Wysłane dziś: {today_sent}/{config_data.limits.max_per_day}")

    if last_run is None:
        typer.echo("Ostatni przebieg: brak")
    else:
        typer.echo(
            f"Ostatni przebieg: {last_run['started_at']} | "
            f"dry_run={bool(last_run['dry_run'])} | "
            f"wysłane={last_run['sent']} | błędy={last_run['errors']} | "
            f"aborted={last_run['aborted'] or '-'}"
        )


@app.command("show-config")
def show_config(
    config: Path = typer.Option(
        Path("config.yaml"),
        "--config",
        "-c",
        help="Ścieżka do pliku konfiguracji YAML.",
    ),
) -> None:
    """Wypisz zwalidowaną konfigurację (bez sekretów)."""

    try:
        config_data = load_config(config)
    except ConfigError as exc:
        _fail(str(exc))

    typer.echo(
        yaml.safe_dump(
            config_data.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )
    )


@app.command()
def version() -> None:
    """Pokaż wersję."""

    typer.echo(f"autokudos {__version__}")


if __name__ == "__main__":
    app()
