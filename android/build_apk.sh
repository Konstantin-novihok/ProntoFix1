#!/usr/bin/env bash
#
# Сборка HomeMaster.apk БЕЗ Android Studio и без скачивания Android SDK:
# нужны только пакеты Ubuntu/Debian (Windows — через WSL2):
#     sudo apt install openjdk-17-jdk-headless aapt apksigner zipalign dalvik-exchange android-sdk-platform-23
# Запуск:   ./build_apk.sh          → HomeMaster.apk
#
# Подпись: при первой сборке создаётся ключ keystore/release.keystore. СОХРАНИТЕ эту папку: приложение с другим ключом
# нельзя установить «поверх» предыдущего (придётся удалять). Свой ключ: KEYSTORE=путь KS_PASS=пароль KEY_ALIAS=имя ./build_apk.sh
set -euo pipefail
cd "$(dirname "$0")"

ANDROID_JAR=${ANDROID_JAR:-$(ls /usr/lib/android-sdk/platforms/android-*/android.jar 2>/dev/null | sort -V | tail -1)}
[ -f "$ANDROID_JAR" ] || { echo "Не найден android.jar — установите: sudo apt install android-sdk-platform-23"; exit 1; }
for t in javac aapt zipalign apksigner dalvik-exchange keytool; do command -v "$t" >/dev/null || { echo "Не найдена программа: $t (см. список пакетов в начале скрипта)"; exit 1; }; done

OUT=build; rm -rf "$OUT"; mkdir -p "$OUT/classes"
echo "[1/5] Ресурсы и манифест"
aapt package -f -M AndroidManifest.xml -S res -I "$ANDROID_JAR" -F "$OUT/base.apk"
echo "[2/5] Компиляция Java (Java 8, API 21+)"
javac --release 8 -encoding UTF-8 -Xlint:-options -cp "$ANDROID_JAR" -d "$OUT/classes" $(find src -name '*.java')
echo "[3/5] Преобразование в DEX"
dalvik-exchange --dex --min-sdk-version=21 --output="$OUT/classes.dex" "$OUT/classes"
echo "[4/5] Упаковка и выравнивание"
( cd "$OUT" && zip -q -j base.apk classes.dex && zipalign -f 4 base.apk aligned.apk )

KEYSTORE=${KEYSTORE:-keystore/release.keystore}
KS_PASS=${KS_PASS:-prontofix-release}
KEY_ALIAS=${KEY_ALIAS:-prontofix}
if [ ! -f "$KEYSTORE" ]; then
    echo "      создаю ключ подписи $KEYSTORE (сохраните его!)"
    mkdir -p "$(dirname "$KEYSTORE")"
    keytool -genkeypair -keystore "$KEYSTORE" -storepass "$KS_PASS" -keypass "$KS_PASS" -alias "$KEY_ALIAS" \
        -keyalg RSA -keysize 2048 -validity 36500 -dname "CN=Home Master, O=ProntoFix" >/dev/null 2>&1
fi
echo "[5/5] Подпись"
apksigner sign --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" --ks-key-alias "$KEY_ALIAS" --out HomeMaster.apk "$OUT/aligned.apk"
apksigner verify HomeMaster.apk
echo; echo "Готово: $(pwd)/HomeMaster.apk ($(du -h HomeMaster.apk | cut -f1))"
aapt dump badging HomeMaster.apk | grep -E "^(package|sdkVersion|targetSdkVersion|application-label:)" 
