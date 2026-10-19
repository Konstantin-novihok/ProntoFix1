#!/bin/sh
#
# ЗАПАСНОЙ ВАРИАНТ для TrueNAS CORE: ProntoFix внутри Linux-виртуалки (bhyve) с Docker.
# Запуск ВНУТРИ виртуалки Ubuntu Server 22.04/24.04 (или Debian 12) от обычного пользователя с sudo:
#     sh /home/<вы>/prontofix/truenas/vm_docker/install_docker_ubuntu.sh
#
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$(dirname "$HERE")")            # корень проекта: server/ + web/
[ -f "$ROOT/server/Dockerfile" ] || { echo "Не найден $ROOT/server/Dockerfile"; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
    echo "==> Устанавливаю Docker"
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo systemctl enable --now docker

cd "$ROOT/server"
if [ ! -f .env ]; then
    PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 14)
    KEY=$(head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c 64)
    printf 'OWNER_PASSWORD=%s\nSECRET_KEY=%s\n' "$PW" "$KEY" > .env
    chmod 600 .env
    echo "Создан $ROOT/server/.env (пароль владельца: $PW) — сохраните этот файл!"
fi
sudo docker compose --env-file .env up -d --build
IP=$(hostname -I | awk '{print $1}')
echo
echo "Готово: http://$IP:8000/app/   (логин owner, пароль — в $ROOT/server/.env)"
echo "Данные лежат в $ROOT/server/data — это папка нужно включить в резервные копии."
