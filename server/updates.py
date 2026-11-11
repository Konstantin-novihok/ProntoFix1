"""Public Android update metadata backed by GitHub Releases.

Only published releases with a .apk asset are advertised. Drafts and prereleases
are excluded by GitHub's /releases/latest endpoint.
"""
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(tags=["updates"])
_REPO = "Konstantin-novihok/ProntoFix1"
_CACHE_SECONDS = 300
_cache = {"at": 0.0, "data": None}


def _latest_release():
    now = time.time()
    if _cache["data"] is not None and now - _cache["at"] < _CACHE_SECONDS:
        return _cache["data"]

    url = "https://api.github.com/repos/" + _REPO + "/releases/latest"
    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "HomeMaster-UpdateService",
    })
    try:
        with urlopen(req, timeout=5) as response:
            release = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="No stable Android release published")
        raise HTTPException(status_code=502, detail="GitHub release service unavailable")
    except (URLError, TimeoutError, ValueError):
        raise HTTPException(status_code=502, detail="GitHub release service unavailable")

    apk = next((a for a in release.get("assets", [])
                if str(a.get("name", "")).lower().endswith(".apk")
                and a.get("browser_download_url", "").startswith("https://github.com/")), None)
    if not apk:
        raise HTTPException(status_code=404, detail="Latest release has no APK asset")

    tag = str(release.get("tag_name", "")).strip()
    version = tag[1:] if tag.lower().startswith("v") else tag
    if not version or len(version) > 64:
        raise HTTPException(status_code=502, detail="Invalid release version")

    data = {
        "version": version,
        "tag": tag,
        "name": str(release.get("name") or tag)[:160],
        "notes": str(release.get("body") or "")[:12000],
        "published_at": release.get("published_at"),
        "apk_url": apk["browser_download_url"],
        "apk_name": apk.get("name", "HomeMaster.apk"),
        "apk_size": apk.get("size"),
        "sha256": apk.get("digest"),
        "release_url": release.get("html_url"),
    }
    _cache.update(at=now, data=data)
    return data


@router.get("/updates/latest")
def latest_android_update():
    """Latest stable Home Master APK release; no user data or device identifiers."""
    try:
        data = _latest_release()
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                            headers={"Cache-Control": "no-store"})
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=300"})
