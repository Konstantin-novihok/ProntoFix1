#!/bin/sh
#
# Установщик ProntoFix для FreeBSD-jail (TrueNAS CORE). Запускать от root ВНУТРИ jail:
#     sh /root/prontofix/truenas/install_in_jail.sh
# Можно запускать повторно: обновит программу и сохранит ваши настройки и данные.
#
# Необязательные переменные:  OWNER_PASSWORD=...  PORT=8000  sh install_in_jail.sh
#
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(dirname "$HERE")                       # папка, где лежат server/ и web/
APP_DIR=/usr/local/prontofix
DATA_DIR=/var/db/prontofix
CONF=/usr/local/etc/prontofix.conf
SVC_USER=prontofix
PORT=${PORT:-8000}

say()  { printf '\n==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*"; }
die()  { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }
rand() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n' | head -c "$1"; }

[ "$(id -u)" = 0 ]        || die "запустите от root (внутри jail: iocage console <имя>)"
[ "$(uname -s)" = FreeBSD ] || die "скрипт предназначен для FreeBSD (jail TrueNAS CORE). Для Linux-виртуалки см. truenas/vm_docker/"
[ -f "$SRC/server/server.py" ] && [ -d "$SRC/web" ] || die "не найдены server/server.py и web/ рядом с truenas/ (распакуйте архив целиком)"

# ---------- 1. Пакетный менеджер ----------
say "1/8 Проверяю доступ к репозиторию пакетов FreeBSD"
if ! pkg -N >/dev/null 2>&1; then
    env ASSUME_ALWAYS_YES=yes pkg bootstrap -f || die "не удалось установить pkg. Проверьте сеть в jail: ping -c1 pkg.freebsd.org"
fi
pkg update -f || die "репозиторий пакетов недоступен (ping pkg.freebsd.org). Проверьте DNS/шлюз jail, см. раздел «Проблемы» в инструкции"

# ---------- 2. Python и библиотеки ----------
say "2/8 Подбираю версию Python"
PYV=""
for v in 311 312 310 39; do
    if [ -n "$(pkg rquery '%n' "py${v}-fastapi" 2>/dev/null)" ] && [ -n "$(pkg rquery '%n' "py${v}-sqlalchemy20" 2>/dev/null)" ]; then
        PYV=$v; break
    fi
done
[ -n "$PYV" ] || die "в репозитории нет подходящих пакетов Python (py3xx-fastapi, py3xx-sqlalchemy20). Вероятно, репозиторий для этой версии FreeBSD снят — используйте вариант «Linux-виртуалка + Docker» (см. инструкцию)"
PYBIN="/usr/local/bin/python3.${PYV#3}"      # 311 -> python3.11, 39 -> python3.9
echo "Использую Python $PYBIN"

say "3/8 Устанавливаю пакеты (может занять несколько минут)"
pkg install -y "python${PYV}" "py${PYV}-sqlite3" || die "не удалось установить Python"
MISSING=""
for p in fastapi uvicorn sqlalchemy20 pyjwt python-multipart cryptography requests openpyxl pip; do
    pkg install -y "py${PYV}-${p}" || { warn "пакет py${PYV}-${p} не установился"; MISSING="$MISSING $p"; }
done
if [ -n "$MISSING" ]; then
    warn "Пробую поставить недостающее через pip:$MISSING"
    for p in $MISSING; do
        case "$p" in
            sqlalchemy20) pip_name="sqlalchemy>=2.0" ;;
            pyjwt)        pip_name="PyJWT" ;;
            pip)          continue ;;
            *)            pip_name="$p" ;;
        esac
        "$PYBIN" -m pip install "$pip_name" || warn "pip не смог установить $pip_name"
    done
fi

say "4/8 Проверяю библиотеки"
"$PYBIN" - <<'PYEOF' || die "не хватает библиотек Python — см. сообщения выше"
import sqlite3, fastapi, uvicorn, jwt, multipart, cryptography, sqlalchemy, pydantic, openpyxl
assert int(sqlalchemy.__version__.split(".")[0]) >= 2, "нужен SQLAlchemy 2.x, установлен " + sqlalchemy.__version__
assert int(pydantic.VERSION.split(".")[0]) >= 2, "нужен pydantic 2.x, установлен " + pydantic.VERSION
print("fastapi", fastapi.__version__, "| sqlalchemy", sqlalchemy.__version__, "| pydantic", pydantic.VERSION)
PYEOF

# ---------- 3. Пользователь, папки ----------
say "5/8 Создаю пользователя и копирую программу"
id "$SVC_USER" >/dev/null 2>&1 || pw user add "$SVC_USER" -c "ProntoFix service" -d /nonexistent -s /usr/sbin/nologin || die "не удалось создать пользователя"
if [ -d "$APP_DIR" ]; then rm -rf "$APP_DIR/server" "$APP_DIR/web"; fi
mkdir -p "$APP_DIR"
cp -R "$SRC/server" "$APP_DIR/server" && cp -R "$SRC/web" "$APP_DIR/web" || die "не удалось скопировать программу в $APP_DIR"
rm -rf "$APP_DIR/server/__pycache__"
chown -R root:wheel "$APP_DIR"
chmod -R go-w "$APP_DIR"

mkdir -p "$DATA_DIR" || die "нет папки данных $DATA_DIR — подключён ли датасет (шаг 3 инструкции)?"
chown -R "$SVC_USER":"$SVC_USER" "$DATA_DIR" || die "не удалось выдать права на $DATA_DIR"
chmod 750 "$DATA_DIR"
touch "$DATA_DIR/.write_test" 2>/dev/null && rm -f "$DATA_DIR/.write_test" || warn "папка данных $DATA_DIR недоступна для записи"

# ---------- 4. Настройки ----------
say "6/8 Настройки"
NEW_CONF=0
if [ ! -f "$CONF" ]; then
    NEW_CONF=1
    OWNER_PW=${OWNER_PASSWORD:-$(rand 14)}
    case "$OWNER_PW" in
        *[!A-Za-z0-9._@%+=-]*) die "в OWNER_PASSWORD допустимы только латинские буквы, цифры и . _ @ % + = -" ;;
    esac
    [ ${#OWNER_PW} -ge 6 ] || die "пароль владельца не короче 6 символов"
    SECRET=$(rand 64)
    sed -e "s|@@OWNER_PASSWORD@@|$OWNER_PW|" -e "s|@@SECRET_KEY@@|$SECRET|" "$HERE/prontofix.conf.sample" > "$CONF"
    chown root:wheel "$CONF"; chmod 600 "$CONF"
    echo "Создан $CONF"
else
    echo "Файл настроек уже есть — оставляю без изменений: $CONF"
fi

# ---------- 5. Служба ----------
say "7/8 Устанавливаю службу автозапуска"
install -m 555 "$HERE/rc.d/prontofix" /usr/local/etc/rc.d/prontofix || die "не удалось установить службу автозапуска (/usr/local/etc/rc.d)"
sysrc prontofix_enable=YES prontofix_python="$PYBIN" prontofix_port="$PORT" >/dev/null || die "sysrc не смог записать настройки службы"
grep -q '^prontofix_host=' /etc/rc.conf 2>/dev/null || sysrc prontofix_host=0.0.0.0 >/dev/null

cat > /usr/local/bin/prontofix-manage <<WEOF
#!/bin/sh
# Служебные команды ProntoFix:  prontofix-manage list-users | reset-password ЛОГИН | set-role ЛОГИН N | backup | check
[ "\$(id -u)" = 0 ] || { echo "запустите от root"; exit 1; }
cd $APP_DIR/server || exit 1
PRONTOFIX_CONF=$CONF $PYBIN manage.py "\$@"
rc=\$?
chown -R $SVC_USER:$SVC_USER $DATA_DIR      # файлы, созданные командой, должны принадлежать службе
exit \$rc
WEOF
chmod 755 /usr/local/bin/prontofix-manage

mkdir -p /usr/local/etc/newsyslog.conf.d
echo "/var/log/prontofix.log  $SVC_USER:$SVC_USER  640  7  5000  *  JC" > /usr/local/etc/newsyslog.conf.d/prontofix.conf

# ---------- 6. Запуск ----------
say "8/8 Запускаю сервер"
service prontofix stop >/dev/null 2>&1
service prontofix start || die "служба не запустилась. Смотрите: tail -50 /var/log/prontofix.log"
OK=0
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if fetch -q -o - "http://127.0.0.1:${PORT}/config" >/dev/null 2>&1; then OK=1; break; fi
    sleep 2
done
IPS=$(ifconfig | awk '/inet /{ if ($2 != "127.0.0.1") print $2 }' | tr '\n' ' ')

echo
echo "=============================================================="
if [ "$OK" = 1 ]; then
    echo " ProntoFix УСТАНОВЛЕН И РАБОТАЕТ"
else
    echo " Служба запущена, но не отвечает. Смотрите:  tail -50 /var/log/prontofix.log"
fi
echo "--------------------------------------------------------------"
for ip in $IPS; do echo " Откройте в браузере:   http://${ip}:${PORT}/app/"; done
echo " Документация API:      http://<IP>:${PORT}/docs"
if [ "$NEW_CONF" = 1 ]; then
    echo " Логин владельца:       owner"
    echo " Пароль владельца:      $OWNER_PW"
    echo " (сохраните его сейчас; он также записан в $CONF)"
fi
echo " Данные:                $DATA_DIR"
echo " Журнал службы:         /var/log/prontofix.log"
echo " Управление:            service prontofix start|stop|restart|status"
echo " Служебные команды:     prontofix-manage  (смена пароля, резервная копия)"
echo "=============================================================="
[ "$OK" = 1 ]
