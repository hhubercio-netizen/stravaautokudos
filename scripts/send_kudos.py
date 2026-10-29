#!/usr/bin/env python3
"""Spike: wysyła jeden kudos przez wewnętrzny endpoint Strava.

Domyślnie działa w trybie dry-run. Wysyłka wymaga flagi --yes.
Kudosów nie da się cofnąć — używaj świadomie.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from list_feed import USER_AGENT, current_athlete_id, load_cookie

DASHBOARD_URL = "https://www.strava.com/dashboard"
ACTIVITY_URL = "https://www.strava.com/activities/{activity_id}"
KUDOS_INFO_URL = "https://www.strava.com/feed/activity/{activity_id}/kudos"
KUDOS_CREATE_URL = "https://www.strava.com/feed/activity/{activity_id}/kudo"


def fetch(url: str, cookie: str, *, accept: str = "text/html") -> tuple[int, str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": f"_strava4_session={cookie}",
            "Referer": "https://www.strava.com/dashboard",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, response.geturl(), body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.geturl(), body
    except URLError as exc:
        raise SystemExit(f"Błąd sieci: {exc.reason}") from exc


def kudos_info(activity_id: str, cookie: str) -> dict:
    status, url, body = fetch(
        KUDOS_INFO_URL.format(activity_id=activity_id),
        cookie,
        accept="application/json, text/javascript, */*; q=0.01",
    )
    if status != 200:
        raise SystemExit(f"Nie można pobrać informacji o kudos: HTTP {status} ({url})")
    return json.loads(body)


def csrf_token(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[name="csrf"]')
    if meta and meta.get("content"):
        return meta["content"]

    match = re.search(r'"key"\s*:\s*"_csrf_token"\s*,\s*"value"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1)

    raise SystemExit("Nie znaleziono tokenu CSRF")


def main() -> int:
    parser = argparse.ArgumentParser(description="Wyślij testowy kudos na Strava")
    parser.add_argument("activity_id", help="ID aktywności, np. 20769715359")
    parser.add_argument("--yes", action="store_true", help="faktycznie wyślij kudos")
    args = parser.parse_args()

    cookie = load_cookie()
    before = kudos_info(args.activity_id, cookie)
    print("Przed:", json.dumps(before, ensure_ascii=False))

    if before.get("is_owner"):
        print("To Twoja własna aktywność — Strava nie pozwala dać kudos. Przerywam.")
        return 1
    if before.get("kudosable") is False:
        print("kudosable=False — już dałeś kudos albo nie możesz. Przerywam.")
        return 1

    status, url, dashboard_html = fetch(DASHBOARD_URL, cookie)
    if status != 200 or "/login" in url:
        print(f"Dashboard niedostępny: HTTP {status}, URL {url}")
        return 1

    csrf = csrf_token(dashboard_html)
    me = current_athlete_id(dashboard_html)
    print(f"CSRF: znaleziony ({len(csrf)} znaków), moje athlete_id: {me}")

    if not args.yes:
        print("DRY RUN — dodaj --yes, żeby wysłać kudos.")
        return 0

    request = Request(
        KUDOS_CREATE_URL.format(activity_id=args.activity_id),
        data=b"null",
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": f"_strava4_session={cookie}",
            "X-CSRF-Token": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": ACTIVITY_URL.format(activity_id=args.activity_id),
            "Origin": "https://www.strava.com",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"POST: HTTP {response.status}, URL {response.geturl()}")
            print("Odpowiedź:", body[:500].replace("\n", " "))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"POST: HTTP {exc.code}, URL {exc.geturl()}")
        print("Odpowiedź:", body[:500].replace("\n", " "))
        return 1
    except URLError as exc:
        print(f"POST błąd sieci: {exc.reason}")
        return 1

    after = kudos_info(args.activity_id, cookie)
    print("Po:", json.dumps(after, ensure_ascii=False))

    athlete_ids = {
        str(athlete.get("id_str") or athlete.get("id")) for athlete in after.get("athletes", [])
    }
    if after.get("kudosable") is False or (me and me in athlete_ids):
        print("SUKCES: kudos dodany.")
        return 0

    print("Nie udało się potwierdzić kudos.")
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
