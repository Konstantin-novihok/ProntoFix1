"""Ждёт, пока локальный сервер начнёт отвечать (до 60 секунд)."""
import sys, time, urllib.request
url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/config"
for _ in range(60):
    try:
        urllib.request.urlopen(url, timeout=2)
        sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit(1)
