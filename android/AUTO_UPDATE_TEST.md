# Автообновление Home Master — тестирование

## Что уже реализовано

1. `.github/workflows/release-home-master.yml` собирает APK в GitHub Actions, подписывает его постоянным keystore и публикует GitHub Release.
2. `server/updates.py` предоставляет серверные адреса:
   - `GET /updates/latest` — версия, размер и SHA-256;
   - `GET /updates/download` — APK из последнего GitHub Release (или локального тестового каталога `/data/updates`, если Release недоступен).
3. `web/updates.js` показывает уведомление о новой версии и вызывает нативный установщик Android.
4. `android/src/org/prontofix/app/MainActivity.java` загружает APK, сверяет SHA-256 и передаёт установку системному PackageInstaller. Android всё равно показывает пользователю системное подтверждение установки.

## Однократная настройка GitHub

В репозитории `Konstantin-novihok/ProntoFix1`, раздел **Settings → Secrets and variables → Actions**, создать секреты:

- `KEYSTORE_B64` — Base64 содержимое файла PKCS#12 keystore.
- `KS_PASS` — пароль keystore.

Имя alias по умолчанию: `prontofix`. Если в keystore другое имя, добавить секрет `KEY_ALIAS` с точным alias.

Секреты вводятся непосредственно в GitHub. Не добавлять keystore, пароль или Base64 в файлы репозитория.

## Выпуск тестового обновления

1. Открыть **Actions → Build and publish Home Master Android APK**.
2. Нажать **Run workflow** на ветке `main`.
3. Дождаться успешного завершения сборки и публикации Release с тремя файлами:
   - `HomeMaster.apk`
   - `latest.json`
   - `HomeMaster.apk.sha256`

Каждый запуск повышает версию сборки. Не менять keystore между выпусками: Android не установит APK с другой подписью поверх установленного приложения.

## Проверка на TrueNAS

После обновления контейнера с текущей веткой `main` проверить:

```sh
curl -i http://127.0.0.1:8000/updates/latest
```

Ответ должен быть HTTP 200 и содержать `version`, `apk_url` со значением `/updates/download` и 64-символьный `sha256`.

Проверить доступность APK:

```sh
curl -I http://127.0.0.1:8000/updates/download
```

Ожидается HTTP 200 и тип `application/vnd.android.package-archive`. Для реальной загрузки APK использовать GET, а не HEAD, если прокси не поддерживает HEAD.

## Проверка на телефоне

1. Установить первый APK вручную.
2. Открыть Home Master и дождаться проверки обновлений.
3. Нажать **Скачать и установить**.
4. При первом запуске разрешить установку неизвестных приложений для Home Master, если Android запросит это разрешение.
5. Подтвердить установку в системном окне Android.

Обновление поверх установленной версии сохраняет данные приложения, если совпадают package ID (`org.prontofix.app`) и сертификат подписи.

## Важно для текущей отладки

- Сборка и публикация Release выполняются GitHub Actions; сервер получает APK напрямую из GitHub Release и не требует ручного копирования APK в каталог TrueNAS.
- Если GitHub Release ещё не опубликован, сервер может отдавать локальный тестовый APK из `/data/updates/HomeMaster.apk` вместе с `/data/updates/latest.json`.
- Проверка SHA-256 защищает от повреждённой загрузки, но не заменяет проверку Android-подписи.
- APK не устанавливается скрытно: финальное подтверждение контролирует Android.
