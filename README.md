# Strava AutoKudos

Bot automatycznie dający kudos na Stravie — tylko dla wybranej whitelisty
zawodników. Działa jako pojedynczy przebieg uruchamiany przez `systemd` timer
na Raspberry Pi.

> **Uwaga:** oficjalne API Strava nie ma endpointu do dawania kudos. Projekt
> korzysta z sesji web (`_strava4_session`) i wewnętrznych endpointów Stravy.
> Może to naruszać regulamin Strava — używaj na własne ryzyko.
> **Kudosów nie da się cofnąć.**

## Status

- [x] Odczyt feedu i parser `__NEXT_DATA__`
- [x] Wysyłka kudos przez `POST /feed/activity/{id}/kudo` — zweryfikowana na żywej sesji
- [x] Whitelist, reguły, limity i losowe pauzy
- [x] SQLite: idempotencja, limit dzienny, historia przebiegów
- [x] CLI: `run`, `check`, `status`, `show-config`, `version`
- [x] Testy jednostkowe i `ruff`
- [x] Pliki `systemd` i instrukcja dla Raspberry Pi 4B

## Jak to działa

1. Bot pobiera dashboard Stravy i parsuje dane z `__NEXT_DATA__`.
2. Reguły wybierają aktywności: whitelist, sport, dystans, wiek, brak kudos.
3. SQLite blokuje ponowną wysyłkę tego samego kudosu i pilnuje limitu dziennego.
4. Przed wysyłką bot sprawdza `kudosable`; po wysyłce weryfikuje, czy kudos
   faktycznie się pojawił.
5. Między kolejnymi kudosami jest losowa pauza (domyślnie 25–90 s).

## Szybki start

Wymagania: **Python 3.11+**.

```bash
git clone https://github.com/hhubercio-netizen/stravaautokudos.git
cd stravaautokudos

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / Raspberry Pi:
# source .venv/bin/activate

pip install -e ".[dev]"

cp config.example.yaml config.yaml
cp .env.example .env
```

Uzupełnij:

- `config.yaml` — whitelist i reguły,
- `.env` — `STRAVA_SESSION_COOKIE` (ciasteczko `_strava4_session` ze Stravy).

Sprawdź sesję i kandydatów **bez wysyłania**:

```bash
autokudos check
autokudos status
autokudos run --dry-run
```

Pierwszy prawdziwy przebieg:

```bash
# 1. w config.yaml ustaw app.dry_run: false
# 2. uruchom z jawną flagą --live
autokudos run --live
```

`--live` jest wymagane do wysyłki. Dodatkowo `app.dry_run: true` w konfiguracji
blokuje wysyłkę — to celowa podwójna blokada.

## CLI

```bash
autokudos run [--dry-run | --live] [--watch] [--ignore-schedule] [--limit N]
autokudos check
autokudos status
autokudos show-config
autokudos version
```

| Komenda | Działanie |
|---|---|
| `run` | Jeden przebieg. Domyślnie dry-run. |
| `run --live` | Realna wysyłka (wymaga `app.dry_run: false`). |
| `run --watch` | Powtarzanie co `schedule.every_minutes`. |
| `run --ignore-schedule` | Pomija okno `active_hours` (do testów). |
| `run --limit N` | Nadpisuje `limits.max_per_run` w tym przebiegu. |
| `check` | Sprawdza sesję, CSRF i kandydatów; nic nie wysyła. |
| `status` | Konfiguracja, baza, ostatni przebieg; bez sieci. |
| `show-config` | Zwalidowana konfiguracja bez sekretów. |

Kody wyjścia: `0` — OK, `1` — błąd przebiegu, `2` — wygasła sesja.

## Konfiguracja

Pełny przykład: [`config.example.yaml`](config.example.yaml).

```yaml
app:
  timezone: Europe/Warsaw
  dry_run: true
  log_level: INFO
  database: data/autokudos.db

schedule:
  every_minutes: 45
  active_hours: "07:00-23:00"

targets:
  mode: whitelist
  include:
    - id: 141888360
      name: "Oskar Kotzian"
    - id: 171997323
      name: "Damian Huminiak"
  exclude: []

rules:
  sports: [Run, Ride, VirtualRide, VirtualRun, Walk, Hike, Swim]
  min_distance_km: 0
  max_age_hours: 36
  skip_own: true
  skip_if_kudosed: true

limits:
  max_per_run: 10
  max_per_day: 60
  delay_seconds: [25, 90]
  stop_on_403: true
  max_consecutive_errors: 3
```

Najważniejsze zasady:

- **Whitelist** — tylko osoby z `targets.include`. `exclude` ma pierwszeństwo.
- **Własne aktywności** — zawsze pomijane, nawet jeśli dodasz siebie do whitelisty.
- **Sport** — dopasowanie bez rozróżniania wielkości liter.
- **Wiek** — `max_age_hours` liczone od `startDate`; aktywności z przyszłości
  (błąd zegara) są pomijane.
- **Kudos** — `hasKudoed` i `canKudo` są sprawdzane zarówno w feedzie, jak i
  przed wysyłką przez endpoint kudos.
- **Idempotencja** — `activity_id` zapisany jako `sent` nie zostanie wysłany
  ponownie.
- **Limit dzienny** — liczony w strefie `app.timezone`, obejmuje też wysyłki
  niepotwierdzone (`unverified`).

## Baza SQLite

Domyślnie `data/autokudos.db` (względem pliku `config.yaml`). Na Pi:
`/var/lib/autokudos/autokudos.db`.

Tabele:

- `kudos` — statusy `sent`, `unverified`, `failed`; idempotencja,
- `runs` — historia przebiegów, liczniki i kod przerwania.

`status` pokazuje stan bez łączenia się ze Stravą.

## Raspberry Pi 4B

Instrukcja krok po kroku: [`deploy/README.md`](deploy/README.md).

Pliki:

- [`deploy/autokudos.service`](deploy/autokudos.service) — oneshot z hardeningiem,
- [`deploy/autokudos.timer`](deploy/autokudos.timer) — co 45 minut,
- [`deploy/config.production.example.yaml`](deploy/config.production.example.yaml),
- [`deploy/autokudos.env.example`](deploy/autokudos.env.example).

```bash
sudo systemctl enable --now autokudos.timer
systemctl list-timers autokudos.timer
sudo journalctl -u autokudos.service -f
```

## Bezpieczeństwo

- `.env` i `config.yaml` są w `.gitignore` — nigdy ich nie commituj.
- Nie loguj cookie ani tokenu CSRF. Bot pokazuje tylko długość CSRF.
- Używaj osobnego użytkownika systemowego i plików `chmod 600/640`.
- Nie wystawiaj żadnego portu — bot tylko wychodzi na zewnątrz.
- Gdy sesja wygaśnie, zaktualizuj `STRAVA_SESSION_COOKIE` i uruchom service.
- Ustawiaj limity i pauzy; nie zalewaj Stravy requestami.

## Rozwiązywanie problemów

| Objaw | Przyczyna / rozwiązanie |
|---|---|
| `Sesja Strava wygasła` | Nowe `_strava4_session` w `.env` / `autokudos.env`. |
| `HTTP 403` | Strava blokuje requesty; bot zatrzymuje przebieg (`stop_on_403`). |
| `Kandydaci wg reguł: 0` | Wszyscy już mają kudos, aktywności są za stare lub poza whitelistą. |
| Brak wysyłki mimo `--live` | `app.dry_run: true` w konfiguracji. |
| `Brak STRAVA_SESSION_COOKIE` | Uzupełnij `.env` albo zmienną środowiskową. |
| Garbione polskie znaki w Windows | Użyj Windows Terminal / PowerShell 7 albo `chcp 65001`. |

## Struktura projektu

```text
src/autokudos/
  config.py          # Pydantic + YAML + .env
  models.py          # Activity, Session, RunStats...
  rules.py           # whitelist, sport, dystans, wiek, kudos
  runner.py          # jeden przebieg: feed -> reguły -> wysyłka
  store.py           # SQLite
  notify.py          # opcjonalny Telegram
  cli.py             # Typer
  strava/
    client.py        # sesja, CSRF, kudos info/send
    feed.py          # parser __NEXT_DATA__
tests/               # pytest
deploy/              # systemd + instrukcja Pi
scripts/             # spike'y z początku projektu (legacy)
```
