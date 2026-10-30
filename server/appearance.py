"""
Оформление и общие настройки.
  * Скин = только цвета и шрифт. Масштаб, расположение кнопок, иконки, функции и логика скином НЕ меняются.
  * Любой пользователь выбирает/создаёт свои скины; администратор задаёт скин по умолчанию для всех и общие скины.
  * Все значения проходят проверку (sanitize_skin): принимаются только цвета #rrggbb и шрифты из фиксированного списка.
"""
import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, SETTING_DEFAULTS, Base, User, current_user, get_db, get_setting, log, need, now, set_setting)

router = APIRouter()

# Шрифты: безопасные системные стеки (внешние шрифты не загружаются — работает офлайн и быстро)
FONTS = {
    "system": 'system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif',
    "humanist": 'Candara,"Segoe UI","Trebuchet MS",Optima,Verdana,sans-serif',
    "verdana": 'Verdana,Geneva,Tahoma,sans-serif',
    "tahoma": 'Tahoma,"Segoe UI",Geneva,sans-serif',
    "trebuchet": '"Trebuchet MS","Lucida Grande","Lucida Sans Unicode",sans-serif',
    "georgia": 'Georgia,"Times New Roman",Times,serif',
    "serif": '"Palatino Linotype","Book Antiqua",Palatino,"Times New Roman",serif',
    "mono": 'ui-monospace,"Cascadia Code","SF Mono",Consolas,"Liberation Mono",monospace',
    "rounded": '"Arial Rounded MT Bold","Segoe UI",system-ui,sans-serif',
    "condensed": '"Arial Narrow","Roboto Condensed","Helvetica Neue",Arial,sans-serif',
}
COLOR_KEYS = ["bg", "card", "text", "muted", "line", "accent", "accentText", "ok", "warn", "bad"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class Skin(Base):
    __tablename__ = "skins"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    data: Mapped[str] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)      # общий скин (создаёт только администратор)
    created_at = mapped_column(DateTime, default=now)


def sanitize_skin(d: Any) -> dict:
    """Оставляет только допустимое: название, светлый/тёмный режим, 10 цветов #rrggbb, шрифт из списка."""
    if not isinstance(d, dict):
        raise HTTPException(400, "Bad skin")
    colors = d.get("colors") or {}
    out_colors = {}
    for k in COLOR_KEYS:
        v = colors.get(k)
        if not isinstance(v, str) or not HEX.match(v):
            raise HTTPException(400, f"Bad color '{k}' (need #rrggbb)")
        out_colors[k] = v.lower()
    font = d.get("font", "system")
    if font not in FONTS:
        raise HTTPException(400, "Unknown font")
    return {"name": str(d.get("name", ""))[:40], "mode": "dark" if d.get("mode") == "dark" else "light",
            "colors": out_colors, "font": font}


# ---------- Настройки приложения ----------
# Currency codes offered by the app. Existing stored values remain valid only when in this list.
SUPPORTED_CURRENCIES = {
    "UAH", "USD", "EUR", "GBP", "PLN", "CZK", "HUF", "RON", "MDL", "BGN",
    "CHF", "CAD", "AUD", "JPY", "CNY", "TRY", "AED", "SAR", "SEK", "NOK",
    "DKK", "ISK", "HRK", "RSD", "GEL", "KZT", "INR", "ILS", "MXN", "BRL",
}
PUBLIC_KEYS = ["app_name", "company_name", "currency", "service_types", "default_skin", "id_rules_text"]


@router.get("/settings/public")
def public_settings(db: Session = Depends(get_db)):
    """Открыто без входа: название, валюта и скин по умолчанию (чтобы экран входа уже был в нужных цветах)."""
    d = {k: get_setting(db, k) for k in PUBLIC_KEYS}
    d["fonts"] = list(FONTS.keys())
    return d


@router.get("/settings")
def all_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    return {k: get_setting(db, k) for k in SETTING_DEFAULTS}


class SettingsIn(BaseModel):
    values: dict


@router.put("/settings")
def save_settings(b: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    changed = []
    for k, v in b.values.items():
        if k not in SETTING_DEFAULTS:
            raise HTTPException(400, f"Unknown setting '{k}'")
        default = SETTING_DEFAULTS[k]
        if k == "default_skin":
            v = None if v is None else sanitize_skin(v)
        elif k == "currency":
            v = str(v).strip().upper()
            if v not in SUPPORTED_CURRENCIES:
                raise HTTPException(400, "Unsupported currency code")
        elif k == "service_types":
            if not isinstance(v, list) or len(v) > 60:
                raise HTTPException(400, "service_types must be a list (max 60)")
            v = [str(x).strip()[:80] for x in v if str(x).strip()]
        elif isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, float):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"'{k}' must be a number")
            if k == "road_factor":
                v = min(3.0, max(1.0, v))
            if v < 0:
                raise HTTPException(400, f"'{k}' must be >= 0")
        else:
            v = str(v).strip()[:2000 if k == "id_rules_text" else 80]
        set_setting(db, k, v)
        changed.append(k)
    log(db, user, "change_settings", "settings", None, ",".join(changed))
    db.commit()
    return {k: get_setting(db, k) for k in SETTING_DEFAULTS}


# ---------- Личный скин ----------
class SkinSel(BaseModel):
    skin: Optional[dict] = None


@router.put("/me/skin")
def set_my_skin(b: SkinSel, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.skin_json = "" if b.skin is None else json.dumps(sanitize_skin(b.skin), ensure_ascii=False)
    db.commit()
    return {"skin": json.loads(user.skin_json) if user.skin_json else None}


# ---------- Библиотека скинов ----------
class SkinIn(BaseModel):
    name: str
    data: dict
    shared: bool = False


def skin_out(s: Skin, viewer: User):
    d = json.loads(s.data)
    d["name"] = s.name
    return dict(id=s.id, name=s.name, shared=s.shared, mine=(s.owner_id == viewer.id), data=d)


@router.get("/skins")
def list_skins(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Skin).where(or_(Skin.owner_id == user.id, Skin.shared)).order_by(Skin.id)
    return [skin_out(s, user) for s in db.scalars(q)]


@router.post("/skins")
def create_skin(b: SkinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    name = b.name.strip()[:40]
    if not name:
        raise HTTPException(400, "Name is required")
    data = sanitize_skin({**b.data, "name": name})
    if b.shared and user.role not in ADMINS:
        raise HTTPException(403, "Only administrators can publish shared skins")
    if len(db.scalars(select(Skin).where(Skin.owner_id == user.id)).all()) >= 50:
        raise HTTPException(400, "Too many skins (max 50)")
    s = Skin(owner_id=user.id, name=name, data=json.dumps(data, ensure_ascii=False), shared=b.shared)
    db.add(s)
    db.commit()
    return skin_out(s, user)


@router.delete("/skins/{sid}")
def delete_skin(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.get(Skin, sid)
    if not s or (s.owner_id != user.id and user.role not in ADMINS):
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---------- Управление версиями приложения ----------
# Публикация обновления не отключает старые клиенты. Совместимость задаётся диапазоном API,
# а минимальная версия клиента остаётся 1, пока владелец явно не изменит политику.
from sqlalchemy import desc

class AppRelease(Base):
    __tablename__ = "app_releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), default="android", index=True)
    version_code: Mapped[int] = mapped_column(Integer, index=True)
    version_name: Mapped[str] = mapped_column(String(32))
    download_url: Mapped[str] = mapped_column(String(1000))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    min_client_version: Mapped[int] = mapped_column(Integer, default=1)
    api_min: Mapped[int] = mapped_column(Integer, default=1)
    api_max: Mapped[int] = mapped_column(Integer, default=1)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at = mapped_column(DateTime, default=now)


class ReleaseIn(BaseModel):
    platform: str = "android"
    version_code: int
    version_name: str
    download_url: str
    sha256: str = ""
    notes: str = ""
    min_client_version: int = 1
    api_min: int = 1
    api_max: int = 1
    mandatory: bool = False


@router.get("/app/update")
def check_app_update(platform: str = "android", version_code: int = 1, api_version: int = 1,
                     db: Session = Depends(get_db)):
    """Public update manifest. Old clients remain supported unless an owner explicitly changes min_client_version."""
    latest = db.scalar(select(AppRelease).where(AppRelease.platform == platform, AppRelease.active.is_(True))
                        .order_by(desc(AppRelease.version_code)))
    if not latest:
        return {"app": "ProntoFix", "update_available": False, "compatible": True,
                "latest_version_code": version_code, "minimum_client_version": 1}
    compatible = version_code >= latest.min_client_version and latest.api_min <= api_version <= latest.api_max
    return {"app": "ProntoFix", "update_available": latest.version_code > version_code,
            "compatible": compatible, "mandatory": bool(latest.mandatory and version_code < latest.min_client_version),
            "latest_version_code": latest.version_code, "latest_version": latest.version_name,
            "download_url": latest.download_url, "sha256": latest.sha256, "notes": latest.notes,
            "minimum_client_version": latest.min_client_version, "api_min": latest.api_min, "api_max": latest.api_max}


@router.post("/app/releases")
def publish_app_release(b: ReleaseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    platform = b.platform.strip().lower()
    if platform not in ("android", "web") or b.version_code < 1 or b.min_client_version < 1:
        raise HTTPException(400, "Invalid platform or version")
    if b.api_min < 1 or b.api_max < b.api_min:
        raise HTTPException(400, "Invalid API compatibility range")
    if not b.download_url.startswith("https://") or len(b.download_url) > 1000:
        raise HTTPException(400, "A trusted HTTPS download URL is required")
    digest = b.sha256.strip().lower()
    if digest and (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)):
        raise HTTPException(400, "SHA-256 must contain 64 hexadecimal characters")
    release = AppRelease(platform=platform, version_code=b.version_code, version_name=b.version_name[:32],
        download_url=b.download_url, sha256=digest, notes=b.notes[:2000], min_client_version=b.min_client_version,
        api_min=b.api_min, api_max=b.api_max, mandatory=b.mandatory, created_by=user.id)
    db.add(release)
    log(db, user, "publish_app_release", "app_release", None, f"{platform} {b.version_name} ({b.version_code})")
    db.commit()
    return {"id": release.id, "version_code": release.version_code, "version_name": release.version_name}
