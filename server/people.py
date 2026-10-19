"""
Люди: приглашения и проверка подрядчиков (внешних исполнителей), справочник сотрудников с положением,
изменение рабочего профиля сотрудника (занятость, компания, ставка).

Правила идентификации:
  * штатный сотрудник (internal) — табельный номер (если включено в настройках) и компания;
  * подрядчик (external) — название компании + ИНН/номер + хотя бы один документ; пока администратор не нажмёт
    «Проверен», подрядчик не может брать заказы и ему нельзя назначать заказы.
"""
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server import (ADMINS, EXECUTOR, HEAD, OBSERVER, STAFF_ROLES, Department, Invite, User, UserDoc, current_user,
                    get_db, log, need, now, user_out)

router = APIRouter()
ONLINE_MINUTES = 10


def is_online(u: User) -> bool:
    return bool(u.last_seen and (now() - u.last_seen) < timedelta(minutes=ONLINE_MINUTES))


def staff_out(db: Session, u: User, admin_view: bool):
    dep = db.get(Department, u.department_id) if u.department_id else None
    d = dict(id=u.id, username=u.username, full_name=u.full_name, phone=u.phone, role=u.role, company_name=u.company_name,
             employment=u.employment or "internal", verification=u.verification or "verified", is_active=u.is_active,
             department_id=u.department_id, department_name=dep.name if dep else None,
             last_lat=u.last_lat, last_lon=u.last_lon, last_seen=u.last_seen.isoformat() if u.last_seen else None,
             online=is_online(u))
    if admin_view:       # финансовые и идентификационные данные — только администраторам
        d.update(employee_no=u.employee_no or "", tax_id=u.tax_id or "", rate_type=u.rate_type or "hourly",
                 rate_value=u.rate_value or 0.0)
    return d


# ---------- Справочник сотрудников и их положение ----------
@router.get("/staff")
def staff_directory(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Все сотрудники (штат и подрядчики) с контактами и последним положением. Видят только сотрудники компании."""
    need(user, *STAFF_ROLES)
    users = db.scalars(select(User).where(User.role.in_(STAFF_ROLES), User.is_active).order_by(User.full_name))
    return [staff_out(db, u, user.role in ADMINS) for u in users]


# ---------- Приглашения подрядчиков ----------
class InviteIn(BaseModel):
    company_name: str = ""
    department_id: Optional[int] = None
    rate_value: float = 0.0       # процент от прибыли
    note: str = ""
    days: int = 14


def invite_out(db: Session, i: Invite):
    used = db.get(User, i.used_by) if i.used_by else None
    return dict(id=i.id, code=i.code, company_name=i.company_name, department_id=i.department_id, rate_value=i.rate_value,
                note=i.note, created_at=i.created_at.isoformat(), expires_at=i.expires_at.isoformat() if i.expires_at else None,
                used_by=i.used_by, used_by_name=(used.full_name or used.username) if used else None)


@router.post("/invites")
def create_invite(b: InviteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, HEAD)
    dep = user.department_id if user.role == HEAD else b.department_id
    inv = Invite(code=secrets.token_hex(4).upper(), company_name=b.company_name.strip(), department_id=dep,
                 rate_value=max(0.0, min(100.0, b.rate_value)), note=b.note[:300], created_by=user.id,
                 expires_at=now() + timedelta(days=max(1, min(b.days, 90))))
    db.add(inv)
    db.flush()
    log(db, user, "create_invite", "invite", inv.id, inv.company_name)
    db.commit()
    return invite_out(db, inv)


@router.get("/invites")
def list_invites(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, HEAD)
    q = select(Invite).order_by(Invite.id.desc()).limit(200)
    if user.role == HEAD:
        q = q.where(Invite.created_by == user.id)
    return [invite_out(db, i) for i in db.scalars(q)]


@router.delete("/invites/{iid}")
def delete_invite(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    i = db.get(Invite, iid)
    if not i or i.used_by:
        raise HTTPException(400, "Invite not found or already used")
    db.delete(i)
    log(db, user, "delete_invite", "invite", iid)
    db.commit()
    return {"ok": True}


# ---------- Подрядчики: список, проверка ----------
@router.get("/contractors")
def contractors(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, HEAD)
    q = select(User).where(User.role == EXECUTOR, User.employment == "external").order_by(User.id.desc())
    if user.role == HEAD:
        q = q.where(User.department_id == user.department_id)
    out = []
    for u in db.scalars(q):
        docs = db.scalars(select(UserDoc).where(UserDoc.user_id == u.id)).all()
        d = staff_out(db, u, True)
        d["documents"] = [dict(id=x.id, original=x.original, mime=x.mime) for x in docs]
        out.append(d)
    return out


class VerifyIn(BaseModel):
    status: str      # verified | rejected | pending
    note: str = ""


@router.patch("/users/{uid}/verify")
def verify(uid: int, b: VerifyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Администратор подтверждает личность подрядчика (по документам) — только после этого ему можно давать заказы."""
    need(user, *ADMINS)
    t = db.get(User, uid)
    if not t or t.employment != "external":
        raise HTTPException(404, "Contractor not found")
    if b.status not in ("verified", "rejected", "pending"):
        raise HTTPException(400, "Bad status")
    if b.status == "verified":
        docs = db.scalar(select(func.count()).select_from(UserDoc).where(UserDoc.user_id == uid))
        if not docs:
            raise HTTPException(400, "Upload at least one identity document first")
        if not (t.company_name and (t.tax_id or t.passport_number_enc)):
            raise HTTPException(400, "Company and tax id / passport are required")
    t.verification = b.status
    log(db, user, "verify_contractor", "user", t.id, f"{b.status} {b.note}".strip())
    db.commit()
    return staff_out(db, t, True)


# ---------- Рабочий профиль сотрудника (администратор) ----------
class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    employment: Optional[str] = None
    company_name: Optional[str] = None
    employee_no: Optional[str] = None
    tax_id: Optional[str] = None
    rate_type: Optional[str] = None
    rate_value: Optional[float] = None


@router.patch("/users/{uid}/profile")
def edit_profile(uid: int, b: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404)
    if user.role != ADMINS[0] and t.role in ADMINS:
        raise HTTPException(403, "Only the owner can edit owners and administrators")
    data = b.model_dump(exclude_none=True)
    if "employment" in data and data["employment"] not in ("internal", "external"):
        raise HTTPException(400, "Bad employment")
    if "rate_type" in data and data["rate_type"] not in ("hourly", "per_order", "percent"):
        raise HTTPException(400, "Bad rate type")
    if "rate_value" in data and data["rate_value"] < 0:
        raise HTTPException(400, "Rate must be >= 0")
    if data.get("employment") == "external" and t.employment != "external":
        t.verification = "pending"
    for k, v in data.items():
        setattr(t, k, v.strip() if isinstance(v, str) else v)
    log(db, user, "edit_profile", "user", t.id, ", ".join(data.keys()))
    db.commit()
    return staff_out(db, t, True)
