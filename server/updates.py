"""Home Master Android updates.

The server first serves an administrator-staged APK from DATA_DIR/updates.
If no local APK is staged, it proxies the latest published GitHub Release.
The Android app always downloads from this server's /updates/download route.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from server import DATA_DIR

router = APIRouter(tags=["updates"])
UPDATE_DIR = Path(DATA_DIR) / "updates"
APK_PATH = UPDATE_DIR / "HomeMaster.apk"
MANIFEST_PATH = UPDATE_DIR / "latest.json"

RELEASE_API = "https://api.github.com/repos/Konstantin-novihok/ProntoFix1/releases/latest"
_CACHE_SECONDS = 60
_release_cache = {"expires": 0.0, "value": None}


def _request(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HomeMaster-TrueNAS-Update-Server",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=30)


def _remote_release():
    now = time.monotonic()
    cached = _release_cache.get("value")
    if cached and now < _release_cache.get("expires", 0):
        return cached

    try:
        with _request(RELEASE_API) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="No Home Master release has been published yet")
        raise HTTPException(status_code=503, detail=f"GitHub release lookup failed: HTTP {exc.code}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach GitHub releases: {exc}")

    assets = {item.get("name"): item for item in release.get("assets", [])}
    apk = assets.get("HomeMaster.apk")
    manifest_asset = assets.get("latest.json")
    checksum_asset = assets.get("HomeMaster.apk.sha256")
    if not apk or not manifest_asset or not checksum_asset:
        raise HTTPException(status_code=503, detail="Latest GitHub release is missing APK, latest.json or SHA-256 file")

    try:
        with _request(manifest_asset["browser_download_url"]) as response:
            manifest = json.loads(response.read().decode("utf-8"))
        with _request(checksum_asset["browser_download_url"]) as response:
            checksum_text = response.read(4096).decode("utf-8", errors="replace")
        sha256 = checksum_text.strip().split()[0].lower()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot read Home Master release metadata: {exc}")

    version = str(manifest.get("version", "")).strip()
    if not version or len(version) > 64 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise HTTPException(status_code=503, detail="GitHub release metadata or SHA-256 is invalid")

    value = {
        "version": version,
        "name": str(manifest.get("name") or ("Home Master " + version))[:160],
        "notes": str(manifest.get("notes") or release.get("body") or "")[:12000],
        "apk_name": "HomeMaster.apk",
        "apk_url": "/updates/download",
        "apk_size": int(apk.get("size") or 0),
        "sha256": sha256,
        "_remote_apk_url": apk["browser_download_url"],
    }
    _release_cache["value"] = value
    _release_cache["expires"] = now + _CACHE_SECONDS
    return value


def _load_local_update():
    if not MANIFEST_PATH.is_file() or not APK_PATH.is_file():
        return None
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Local Android update manifest is invalid")

    version = str(manifest.get("version", "")).strip()
    if not version or len(version) > 64:
        raise HTTPException(status_code=503, detail="Local Android update version is invalid")

    digest = hashlib.sha256()
    with APK_PATH.open("rb") as apk:
        for chunk in iter(lambda: apk.read(1024 * 1024), b""):
            digest.update(chunk)

    return {
        "version": version,
        "name": str(manifest.get("name") or ("Home Master " + version))[:160],
        "notes": str(manifest.get("notes") or "")[:12000],
        "apk_name": "HomeMaster.apk",
        "apk_url": "/updates/download",
        "apk_size": APK_PATH.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _load_update():
    # Prefer the latest CI-published release. Local staging remains a fallback
    # for offline testing or when no GitHub release exists yet.
    try:
        return _remote_release()
    except HTTPException:
        local = _load_local_update()
        if local:
            return local
        raise


@router.get("/updates/latest")
def latest_android_update():
    """Return the staged update or the latest published GitHub Release."""
    try:
        data = _load_update()
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(content=data, headers={"Cache-Control": "no-store"})


@router.get("/updates/download")
def download_android_update():
    """Download the APK from local staging or proxy the latest GitHub Release."""
    try:
        update = _remote_release()
    except HTTPException:
        update = None

    if update is None:
        if APK_PATH.is_file() and MANIFEST_PATH.is_file():
            _load_local_update()
            return FileResponse(
                str(APK_PATH),
                media_type="application/vnd.android.package-archive",
                filename="HomeMaster.apk",
                headers={"Cache-Control": "no-store"},
            )
        raise HTTPException(status_code=404, detail="No Home Master APK is available")

    remote_url = update["_remote_apk_url"]

    def stream_apk():
        with _request(remote_url) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="HomeMaster.apk"',
    }
    if update["apk_size"] > 0:
        headers["Content-Length"] = str(update["apk_size"])
    return StreamingResponse(
        stream_apk(),
        media_type="application/vnd.android.package-archive",
        headers=headers,
    )
