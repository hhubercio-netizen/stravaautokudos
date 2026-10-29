"""Klient wewnętrznych endpointów web Stravy.

Oficjalne API Strava nie udostępnia dodawania kudos, dlatego bot korzysta
z sesji web (`_strava4_session`) i endpointów używanych przez stronę.

Transport oparty jest o `urllib` (stdlib). To celowe: Strava potrafi
przekierować na `/login` requesty z niektórych bibliotek HTTP, a `urllib`
został zweryfikowany na żywej sesji.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from autokudos.models import Activity, Dashboard, KudosInfo, SendResult, Session
from autokudos.strava.feed import FeedParseError, parse_dashboard

BASE_URL = "https://www.strava.com"
DASHBOARD_PATH = "/dashboard"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class StravaError(Exception):
    """Bazowy błąd klienta Stravy."""


class StravaNetworkError(StravaError):
    """Błąd sieci lub timeout."""


class StravaParseError(StravaError):
    """Nieoczekiwana odpowiedź Stravy."""


class StravaHTTPError(StravaError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthError(StravaError):
    """Sesja wygasła albo Strava przekierowała na logowanie."""


class NotFoundError(StravaHTTPError):
    """Zasób nie istnieje (np. usunięta aktywność)."""


class ForbiddenError(StravaHTTPError):
    """HTTP 403 — brak uprawnień, rate limit albo blokada."""


class RateLimitError(ForbiddenError):
    """HTTP 429 — zbyt wiele requestów."""


@dataclass(slots=True)
class HttpResponse:
    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8", errors="replace"))


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    url=response.geturl(),
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                url=exc.geturl(),
                headers={key.lower(): value for key, value in exc.headers.items()},
                body=exc.read(),
            )
        except (URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise StravaNetworkError(f"Błąd sieci: {reason}") from exc


def extract_csrf(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": "csrf"})
    if meta is not None and meta.get("content"):
        return str(meta["content"])

    match = re.search(
        r'"key"\s*:\s*"_csrf_token"\s*,\s*"value"\s*:\s*"([^"]+)"',
        html,
    )
    if match:
        return match.group(1)

    raise StravaParseError("Nie znaleziono tokenu CSRF na dashboardzie Stravy.")


class StravaClient:
    def __init__(
        self,
        session_cookie: str,
        *,
        timeout: float = 30.0,
        transport: Transport | None = None,
    ) -> None:
        cookie = session_cookie.strip()
        if not cookie:
            raise ValueError("Puste cookie sesji Strava.")

        self._cookie = cookie
        self._csrf: str | None = None
        self._session: Session | None = None
        self._timeout = timeout
        self._transport = transport or UrllibTransport()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        """Transport stdlib nie wymaga zamykania."""

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        url = f"{BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        request_headers: dict[str, str] = {
            "Cookie": f"_strava4_session={self._cookie}",
        }
        if headers:
            request_headers.update(headers)

        response = self._transport.request(
            method,
            url,
            request_headers,
            body,
            self._timeout,
        )

        if self._is_login_response(response):
            raise AuthError("Sesja Strava wygasła. Zaktualizuj STRAVA_SESSION_COOKIE w .env.")
        if response.status_code == 401:
            raise AuthError("Strava odrzuciła sesję (HTTP 401). Zaktualizuj STRAVA_SESSION_COOKIE.")
        if response.status_code == 404:
            raise NotFoundError(404, f"Strava zwróciła HTTP 404 dla {path}.")
        if response.status_code == 429:
            raise RateLimitError(429, "Strava zwróciła HTTP 429 — zbyt wiele requestów.")
        if response.status_code == 403:
            raise ForbiddenError(403, f"Strava zwróciła HTTP 403 dla {path}.")
        if response.status_code >= 400:
            raise StravaHTTPError(
                response.status_code,
                f"Strava zwróciła HTTP {response.status_code} dla {path}.",
            )
        return response

    @staticmethod
    def _is_login_response(response: HttpResponse) -> bool:
        return "/login" in urlparse(response.url).path

    def get_dashboard_html(self, *, num_entries: int = 50) -> str:
        response = self._request(
            "GET",
            DASHBOARD_PATH,
            params={"num_entries": num_entries},
            headers={
                "Accept": HTML_ACCEPT,
                "Referer": f"{BASE_URL}{DASHBOARD_PATH}",
                "User-Agent": USER_AGENT,
            },
        )
        return response.text

    def fetch_dashboard(self, *, num_entries: int = 50) -> Dashboard:
        html = self.get_dashboard_html(num_entries=num_entries)
        try:
            snapshot = parse_dashboard(html)
        except FeedParseError as exc:
            raise StravaParseError(str(exc)) from exc

        csrf = extract_csrf(html)
        session = Session(
            athlete_id=snapshot.current_athlete_id,
            athlete_name=snapshot.current_athlete_name,
            csrf=csrf,
        )
        self._session = session
        self._csrf = csrf
        return Dashboard(
            activities=snapshot.activities,
            session=session,
            csrf=csrf,
        )

    def get_session(self) -> Session:
        if self._session is None:
            self.fetch_dashboard()
        assert self._session is not None
        return self._session

    def get_feed(self, *, num_entries: int = 50) -> list[Activity]:
        return self.fetch_dashboard(num_entries=num_entries).activities

    def get_kudos_info(self, activity_id: str) -> KudosInfo:
        activity_id = str(activity_id)
        response = self._request(
            "GET",
            f"/feed/activity/{activity_id}/kudos",
            headers={
                "Accept": JSON_ACCEPT,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/activities/{activity_id}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise StravaParseError(
                f"Nieoczekiwana odpowiedź kudos dla aktywności {activity_id}."
            ) from exc
        if not isinstance(data, dict):
            raise StravaParseError(
                f"Nieoczekiwany format odpowiedzi kudos dla aktywności {activity_id}."
            )

        athlete_ids: set[str] = set()
        for athlete in data.get("athletes") or []:
            if not isinstance(athlete, dict):
                continue
            athlete_id = athlete.get("id_str") or athlete.get("id")
            if athlete_id is not None:
                athlete_ids.add(str(athlete_id))

        return KudosInfo(
            activity_id=activity_id,
            is_owner=bool(data.get("is_owner", False)),
            kudosable=bool(data.get("kudosable", False)),
            athlete_ids=frozenset(athlete_ids),
        )

    def send_kudo(self, activity_id: str, *, verify: bool = True) -> SendResult:
        activity_id = str(activity_id)
        if self._csrf is None:
            self.fetch_dashboard()

        response = self._request(
            "POST",
            f"/feed/activity/{activity_id}/kudo",
            headers={
                "Accept": JSON_ACCEPT,
                "X-CSRF-Token": self._csrf or "",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/activities/{activity_id}",
                "Origin": BASE_URL,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            body=b"null",
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise StravaParseError(
                f"Nieoczekiwana odpowiedź po wysłaniu kudos dla {activity_id}."
            ) from exc

        success = isinstance(data, dict) and data.get("success") in (
            True,
            "true",
            "True",
            1,
        )
        if not success:
            raise StravaError(f"Strava nie potwierdziła wysłania kudos dla {activity_id}: {data!r}")

        verified = False
        if verify:
            info = self.get_kudos_info(activity_id)
            session = self.get_session()
            verified = (not info.kudosable) or session.athlete_id in info.athlete_ids

        return SendResult(activity_id=activity_id, response_ok=True, verified=verified)

    def refresh_session(self) -> Dashboard:
        self._session = None
        self._csrf = None
        return self.fetch_dashboard()
