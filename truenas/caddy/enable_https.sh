#!/bin/sh
#
# Включает HTTPS (бесплатный сертификат Let's Encrypt) через Caddy внутри того же jail.
# Запуск:  sh enable_https.sh service.example.com you@example.com
#
# Перед запуском должно быть готово:
#   1. Доменное имя (или динамический DNS), указывающее на ВНЕШНИЙ IP вашего роутера.
#   2. На роутере проброс портов 80 и 443 на IP этого jail.
#   3. ProntoFix уже установлен и открывается по http://IP:8000/app/
#
set -u
DOMAIN=${1:-}
EMAIL=${2:-}
[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || { echo "Использование: sh enable_https.sh ДОМЕН EMAIL"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "запустите от root"; exit 1; }

pkg install -y caddy || { echo "не удалось установить caddy"; exit 1; }
mkdir -p /usr/local/etc/caddy
cat > /usr/local/etc/caddy/Caddyfile <<CEOF
{
	email $EMAIL
}

$DOMAIN {
	encode gzip
	request_body {
		max_size 250MB
	}
	reverse_proxy 127.0.0.1:8000
}
CEOF
sysrc caddy_enable=YES >/dev/null
# наружу смотрит только Caddy; сам ProntoFix слушает только внутри jail
sysrc prontofix_host=127.0.0.1 >/dev/null
service prontofix restart
service caddy restart || service caddy start
echo
echo "Готово. Через минуту откройте  https://$DOMAIN/app/"
echo "Если сертификат не выдался:  tail -50 /var/log/caddy/caddy.log  (или  service caddy status)"
echo "Адрес сервера для мобильного приложения:  https://$DOMAIN"
