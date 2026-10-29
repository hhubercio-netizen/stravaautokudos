"""Opcjonalne powiadomienia Telegram (bez logowania sekretów)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from loguru import logger

from autokudos.config import NotifyConfig
from autokudos.models import RunStats


class Notifier:
    def __init__(
        self,
        config: NotifyConfig,
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._telegram = config.telegram
        self._env = env if env is not None else os.environ
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return self._telegram.enabled and bool(self._telegram.chat_id.strip())

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False

        token = self._env.get(self._telegram.bot_token_env, "").strip()
        if not token:
            logger.warning(
                "Telegram włączony, ale brak zmiennej {}.",
                self._telegram.bot_token_env,
            )
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": self._telegram.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout) as response:
                if response.status != 200:
                    logger.warning("Telegram: HTTP {}.", response.status)
                    return False
                return True
        except HTTPError as exc:
            logger.warning("Telegram: HTTP {}.", exc.code)
            return False
        except (URLError, TimeoutError) as exc:
            # Nie logujemy URL-a — zawiera token bota.
            logger.warning("Telegram: błąd sieci ({}).", exc.__class__.__name__)
            return False

    def send_run_summary(self, stats: RunStats) -> bool:
        mode = "DRY RUN" if stats.dry_run else "LIVE"
        lines = [
            f"Strava AutoKudos — {mode}",
            f"Znalezione: {stats.found}",
            f"Kandydaci: {stats.candidates}",
            f"Wysłane: {stats.sent}",
        ]
        if stats.dry_run:
            lines.append(f"Do wysłania: {stats.would_send}")
        lines.extend(
            [
                f"Pominięte: {stats.skipped}",
                f"Błędy: {stats.errors}",
            ]
        )
        if stats.aborted:
            lines.append(f"Przerwano: {stats.aborted}")
        return self.send("\n".join(lines))

    def send_session_expired(self) -> bool:
        return self.send(
            "Strava AutoKudos: sesja Strava wygasła. "
            "Zaktualizuj STRAVA_SESSION_COOKIE na Raspberry Pi."
        )
