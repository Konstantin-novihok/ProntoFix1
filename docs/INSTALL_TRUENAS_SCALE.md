# ProntoFix на TrueNAS SCALE (Docker)

**Коротко: да, работает.** SCALE построен на Linux, поэтому сервер запускается в Docker из готового `docker-compose.yml`. Это проще и надёжнее, чем jail в TrueNAS CORE.
Я не мог проверить установку на реальном TrueNAS SCALE: ниже — стандартная схема запуска Docker, перед боевым использованием проверьте её на тестовых данных.

## Какая версия SCALE нужна
* **24.10 («Electric Eel») и новее** (включая редакцию Community) — приложения работают на Docker. Подходит.
* **24.04 («Dragonfly») и старше** — приложения на Kubernetes: Docker для своих контейнеров там не предусмотрен. Обновите SCALE или используйте Linux-виртуалку (см. `truenas/INSTALL_TRUENAS_CORE.md`, «Вариант Б»).

## Установка
1. **Датасет:** Storage → Create Dataset → `prontofix` (внутри потом появится папка `data`). Например `/mnt/tank/prontofix`.
2. **Скопируйте проект** (папки `server/` и `web/`) в `/mnt/tank/prontofix/app/` — по SMB или `scp`.
3. **Откройте оболочку:** System → Shell (или SSH) и выполните:
```bash
cd /mnt/tank/prontofix/app/server
mkdir -p /mnt/tank/prontofix/data
cat > .env <<EOT
OWNER_PASSWORD=ВашНадёжныйПароль
SECRET_KEY=$(head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n')
DATA_PATH=/mnt/tank/prontofix/data
MAP_PROVIDER=osm
EOT
chmod 600 .env
docker compose up -d --build
```
4. Откройте `http://IP-NAS:8000/app/` → войдите `owner` + пароль из `.env`.

**Важно:** сохраните `.env` (там `SECRET_KEY` — без него паспортные данные не расшифровать) и включите снимки ZFS для `tank/prontofix`.

## Замечания именно для SCALE
* Контейнеры, запущенные вручную через `docker compose`, **не отображаются в разделе Apps** интерфейса TrueNAS. Они работают и перезапускаются сами (`restart: unless-stopped`), управлять ими — из оболочки: `docker compose ps | logs | restart`.
* Если хотите видеть сервис в Apps (**Install via YAML / Custom App**), ему нужен **готовый образ**: соберите его (`docker build -f server/Dockerfile -t ghcr.io/ВАШ_АККАУНТ/prontofix:1 .` из корня проекта), опубликуйте в реестре и укажите образ в YAML. Мастер Apps не умеет собирать образ из исходников.
* Порт 8000 может конфликтовать с другими приложениями: поменяйте в `docker-compose.yml` левую часть (`"8080:8000"`).
* Служебные команды (пароль, резервная копия):
```bash
docker compose exec repair-server python manage.py reset-password owner
docker compose exec repair-server python manage.py backup /data/backups
```

## HTTPS (нужен для мобильного приложения и камеры)
Самый простой путь на SCALE — готовое приложение **Nginx Proxy Manager** из каталога Apps (или Caddy / Cloudflare Tunnel): домен → `http://IP-NAS:8000`, включить Let's Encrypt и увеличить лимит тела запроса до 250 МБ (загрузка видео). Затем в мобильном приложении укажите `https://ваш-домен`.

## Обновление
Замените файлы в `app/` на новые, затем `docker compose up -d --build`. Данные в `data/` сохраняются.
