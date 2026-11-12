"""Android updates served only from the administrator-managed TrueNAS data folder.

Publish an update by placing HomeMaster.apk and latest.json in DATA_DIR/updates.
Nothing in this module contacts GitHub or deploys/restarts the server.
"""
import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from server import DATA_DIR

router = APIRouter(tags=["updates"])
UPDATE_DIR = Path(DATA_DIR) / "updates"
APK_PATH = UPDATE_DIR / "HomeMaster.apk"
MANIFEST_PATH = UPDATE_DIR / "latest.json"


def _load_update():
    if not MANIFEST_PATH.is_file() or not APK_PATH.is_file():
        raise HTTPException(status_code=404, detail="No Android update has been published on this server")

    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="Android update manifest is invalid")

    version = str(manifest.get("version", "")).strip()
    if not version or len(version) > 64:
        raise HTTPException(status_code=503, detail="Android update version is invalid")

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


@router.get("/updates/latest")
def latest_android_update():
    """Return the update explicitly staged by the server administrator."""
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
    """Download the APK staged locally on TrueNAS."""
    if not APK_PATH.is_file() or not MANIFEST_PATH.is_file():
        raise HTTPException(status_code=404, detail="No Android update is available")
    # Validate the manifest before allowing download.
    _load_update()
    return FileResponse(
        str(APK_PATH),
        media_type="application/vnd.android.package-archive",
        filename="HomeMaster.apk",
        headers={"Cache-Control": "no-store"},
    )
