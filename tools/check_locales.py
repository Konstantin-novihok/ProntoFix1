"""Проверка переводов: каких ключей не хватает в каждом языке (эталон — en.json). Запуск:  python tools/check_locales.py
Добавить язык: скопируйте web/locales/en.json в web/locales/<код>.json и переведите значения (поле "_name" — название в списке)."""
import glob, json, os
folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "locales")
base = json.load(open(os.path.join(folder, "en.json"), encoding="utf-8"))
bad = 0
for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    miss = [k for k in base if k not in d]
    bad += bool(miss)
    print(os.path.basename(f), f"{len(d)} ключей:", "OK" if not miss else f"не хватает: {miss}")
raise SystemExit(1 if bad else 0)
