# Wdrożenie na Raspberry Pi 4B (4 GB)

Bot jest zaprojektowany jako **oneshot** uruchamiany przez `systemd` timer.
Nie otwiera żadnego portu — potrzebuje tylko wychodzącego HTTPS do `strava.com`.

## 1. System

Zalecany: **Raspberry Pi OS Lite 64-bit**.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git sqlite3
```

Utwórz osobnego użytkownika bez uprawnień do sudo:

```bash
sudo useradd --system --create-home --home-dir /home/autokudos \
  --shell /usr/sbin/nologin autokudos
```

## 2. Kod i środowisko Python

```bash
sudo git clone https://github.com/hhubercio-netizen/stravaautokudos.git /opt/autokudos
sudo chown -R autokudos:autokudos /opt/autokudos

sudo -u autokudos python3 -m venv /opt/autokudos/.venv
sudo -u autokudos /opt/autokudos/.venv/bin/pip install --upgrade pip
sudo -u autokudos /opt/autokudos/.venv/bin/pip install -e /opt/autokudos
```

Test importu:

```bash
sudo -u autokudos /opt/autokudos/.venv/bin/autokudos version
```

## 3. Konfiguracja i sekret

```bash
sudo install -d -m 750 -o root -g autokudos /etc/autokudos

sudo cp /opt/autokudos/deploy/config.production.example.yaml /etc/autokudos/config.yaml
sudo cp /opt/autokudos/deploy/autokudos.env.example /etc/autokudos/autokudos.env

sudo chown root:autokudos /etc/autokudos/config.yaml
sudo chmod 640 /etc/autokudos/config.yaml

sudo chown root:root /etc/autokudos/autokudos.env
sudo chmod 600 /etc/autokudos/autokudos.env
```

Uzupełnij:

```bash
sudo nano /etc/autokudos/config.yaml
sudo nano /etc/autokudos/autokudos.env
```

- `config.yaml`: whitelist, reguły, limity. Na start zostaw `app.dry_run: true`.
- `autokudos.env`: `STRAVA_SESSION_COOKIE` (wartość ciasteczka `_strava4_session`).
- Opcjonalnie `TELEGRAM_BOT_TOKEN` i `notify.telegram.enabled: true`.

> **Nigdy** nie commituj `config.yaml` ani `autokudos.env`. Oba zawierają sekrety.

## 4. Test dry-run

```bash
sudo systemctl start autokudos.service
sudo journalctl -u autokudos.service -n 50 --no-pager
```

Service ma `--live`, ale `app.dry_run: true` wymusza dry-run. Sprawdź, czy feed
się pobiera i czy kandydaci są poprawni.

## 5. Pierwszy prawdziwy przebieg

Po akceptacji dry-runu:

```bash
sudo nano /etc/autokudos/config.yaml
# zmień: app.dry_run: false
```

Wykonaj ręcznie:

```bash
sudo systemctl start autokudos.service
sudo journalctl -u autokudos.service -n 50 --no-pager
```

Kudosów **nie da się cofnąć**. Sprawdź log, zanim uruchomisz timer.

## 6. Timer

```bash
sudo cp /opt/autokudos/deploy/autokudos.service /etc/systemd/system/
sudo cp /opt/autokudos/deploy/autokudos.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autokudos.timer

systemctl list-timers autokudos.timer
```

Timer domyślnie uruchamia przebieg co **45 minut**. Jeśli zmienisz
`schedule.every_minutes` w konfiguracji, zmień też `OnUnitActiveSec` w
`/etc/systemd/system/autokudos.timer` i wykonaj `systemctl daemon-reload`.

## 7. Podgląd i diagnostyka

```bash
# Ostatnie logi
sudo journalctl -u autokudos.service -n 100 --no-pager

# Logi na żywo
sudo journalctl -u autokudos.service -f

# Stan bazy i konfiguracji (bez sieci)
sudo -u autokudos /opt/autokudos/.venv/bin/autokudos status \
  --config /etc/autokudos/config.yaml

# Test sesji i kandydatów (bez wysyłki)
sudo -u autokudos sh -c 'set -a; . /etc/autokudos/autokudos.env; set +a; \
  cd /opt/autokudos && .venv/bin/autokudos check \
  --config /etc/autokudos/config.yaml'
```

## 8. Aktualizacja

```bash
cd /opt/autokudos
sudo -u autokudos git pull
sudo -u autokudos .venv/bin/pip install -e .
sudo systemctl restart autokudos.timer
```

## 9. Kopia zapasowa

Baza jest w `/var/lib/autokudos/autokudos.db`.

```bash
sudo -u autokudos sqlite3 /var/lib/autokudos/autokudos.db \
  ".backup '/var/lib/autokudos/autokudos-backup.db'"
```

Kopię można przenieść poza Pi. **Nie kopiuj i nie commituj cookie.**

## 10. Bezpieczeństwo

- SSH tylko po kluczach, hasło wyłączone.
- `ufw`: zezwól na SSH tylko z LAN, resztę ruchu przychodzącego odrzuć.
- `unattended-upgrades` włączone.
- Osobny użytkownik `autokudos`, bez sudo.
- Sekrety w `/etc/autokudos`, poza repozytorium.
- Service ma `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`
  i zapis tylko do `/var/lib/autokudos`.
- Gdy sesja wygaśnie, bot zakończy się błędem i (opcjonalnie) wyśle Telegram.
  Wtedy zaktualizuj cookie i uruchom service ponownie.
