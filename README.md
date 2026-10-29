# Strava AutoKudos

Bot do automatycznego dawania kudos na Stravie — na start dla wybranej whitelisty znajomych.

> **Uwaga:** oficjalne API Strava nie ma endpointu do dawania kudos. Projekt korzysta z sesji web
> (`_strava4_session`) i wewnętrznego endpointu `POST /feed/kudos/{id}`. Może to naruszać regulamin
> Strava — używaj na własne ryzyko. Kudosów nie da się cofnąć.

## Status

- [x] Inicjalizacja repozytorium
- [x] Odczyt feedu i parser aktywności (spike)
- [ ] Test zapisu kudos (`POST /feed/kudos/{id}`)
- [ ] MVP CLI (`run --once`, `--dry-run`)
- [ ] Whitelist + reguły + SQLite
- [ ] Wdrożenie na Raspberry Pi (systemd timer)

## Wymagania

- Python 3.11+
- konto Strava
- `.env` z `STRAVA_SESSION_COOKIE` (plik jest w `.gitignore`)

## Podgląd feedu

```bash
python scripts/list_feed.py
```

Skrypt jest **tylko do odczytu** — nie wysyła kudos. Pokazuje aktywności z feedu i informuje,
które z nich nie mają jeszcze Twojego kudos.
