# Strava AutoKudos

Bot do automatycznego dawania kudos na Stravie — na start dla wybranej whitelisty znajomych.

> **Uwaga:** oficjalne API Strava nie ma endpointu do dawania kudos. Projekt korzysta z sesji web
> (`_strava4_session`) i wewnętrznych endpointów Strava. Może to naruszać regulamin Strava —
> używaj na własne ryzyko. Kudosów nie da się cofnąć.

## Status

- [x] Inicjalizacja repozytorium
- [x] Odczyt feedu i parser aktywności
- [x] Test zapisu kudos (`POST /feed/activity/{id}/kudo`) — **działa**
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
które z nich nie mają jeszcze Twojego kudos. Własne aktywności są oznaczane jako pomijane.

## Testowy kudos

Najpierw dry-run (nic nie wysyła):

```bash
python scripts/send_kudos.py <ACTIVITY_ID>
```

Wysyłka (nieodwracalna):

```bash
python scripts/send_kudos.py <ACTIVITY_ID> --yes
```

Skrypt sprawdza `is_owner` i `kudosable`, pobiera CSRF z dashboardu i po wysyłce weryfikuje,
czy kudos faktycznie się pojawił.

## Odkryte endpointy (spike)

| Operacja | Endpoint | Uwagi |
|---|---|---|
| Informacje o kudos | `GET /feed/activity/{id}/kudos` | JSON: `is_owner`, `kudosable`, `athletes` |
| Dodanie kudos | `POST /feed/activity/{id}/kudo` | `X-CSRF-Token`, `Content-Type: application/json`, body `null` |
| Token CSRF | `<meta name="csrf" content="...">` | na dashboardzie |
| Stary endpoint | `POST /feed/kudos/{id}` | **404** — nie używać |

## Bezpieczeństwo

- `.env` jest w `.gitignore` — nigdy nie commituj cookie.
- Nie loguj wartości cookie ani tokenu CSRF.
- Ustawiaj limity i losowe opóźnienia między kudos.
