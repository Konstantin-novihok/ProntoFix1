"""Persisted in-app notifications with per-recipient acknowledgement."""
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import ADMINS, STAFF_ROLES, Base, User, current_user, get_db, log, need, now

router = APIRouter()


class Notice(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), default="general")
    priority: Mapped[str] = mapped_column(String(12), default="normal")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    sound: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)
    acknowledged_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


class NoticeBatch(Base):
    __tablename__ = "notification_batches"
    __table_args__ = (UniqueConstraint("sender_id", "request_key", name="uq_notice_batch_sender_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class NoticePreference(Base):
    __tablename__ = "notification_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    categories_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


NOTICE_CATEGORIES = ("general", "orders", "safety", "finance", "system")


class NoticePreferenceIn(BaseModel):
    categories: dict[str, bool] = Field(default_factory=dict)


@router.get("/notifications/preferences")
def get_notice_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    import json
    row = db.get(NoticePreference, user.id)
    saved = json.loads(row.categories_json or "{}") if row else {}
    return {"categories": {c: bool(saved.get(c, True)) for c in NOTICE_CATEGORIES},
            "critical_bypass": True}


@router.put("/notifications/preferences")
def set_notice_preferences(b: NoticePreferenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    import json
    if any(k not in NOTICE_CATEGORIES for k in b.categories):
        raise HTTPException(400, "Unsupported notification category")
    row = db.get(NoticePreference, user.id)
    if row is None:
        row = NoticePreference(user_id=user.id)
        db.add(row)
    row.categories_json = json.dumps({c: bool(v) for c, v in b.categories.items()}, ensure_ascii=False)
    row.updated_at = now()
    db.commit()
    return {"ok": True}


class NoticeSend(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)
    category: str = "general"
    priority: str = "normal"
    sound: bool = False
    recipient_ids: list[int] = Field(default_factory=list, max_length=500)
    roles: list[int] = Field(default_factory=list, max_length=10)
    group_ids: list[int] = Field(default_factory=list, max_length=200)
    request_key: Optional[str] = Field(default=None, min_length=8, max_length=100)


def notice_out(n: Notice):
    return dict(id=n.id, sender_id=n.sender_id, recipient_id=n.recipient_id, category=n.category,
                priority=n.priority, title=n.title, body=n.body, sound=n.sound,
                created_at=n.created_at.isoformat() + "Z",
                acknowledged_at=n.acknowledged_at.isoformat() + "Z" if n.acknowledged_at else None)


@router.post("/notifications")
def send_notice(b: NoticeSend, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    if b.category not in ("general", "orders", "safety", "finance", "system"):
        raise HTTPException(400, "Unsupported notification category")
    if b.priority not in ("normal", "important", "critical"):
        raise HTTPException(400, "Unsupported priority")
    if b.priority == "critical" and not b.sound:
        raise HTTPException(400, "Critical notification requires sound enabled")
    import json, hashlib
    digest = None
    if b.request_key:
        payload = b.model_dump(exclude={"request_key"})
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        previous = db.scalar(select(NoticeBatch).where(NoticeBatch.sender_id == user.id, NoticeBatch.request_key == b.request_key))
        if previous:
            if previous.payload_hash != digest:
                raise HTTPException(409, "Request key already used with a different payload")
            return json.loads(previous.result_json)
    group_member_ids = set()
    for gid in set(b.group_ids):
        group = db.get(NoticeGroup, gid)
        if group is None:
            raise HTTPException(400, f"Unknown notification group: {gid}")
        group_member_ids.update(json.loads(group.member_ids or "[]"))
    target_ids = set(b.recipient_ids) | group_member_ids
    if not target_ids and not b.roles:
        raise HTTPException(400, "Choose recipients, groups or roles")
    if any(r not in STAFF_ROLES for r in b.roles):
        raise HTTPException(400, "Unsupported recipient role")
    q = select(User).where(User.is_active.is_(True))
    if target_ids and b.roles:
        q = q.where((User.id.in_(target_ids)) | (User.role.in_(b.roles)))
    elif target_ids:
        q = q.where(User.id.in_(target_ids))
    else:
        q = q.where(User.role.in_(b.roles))
    recipients = db.scalars(q).all()
    if not recipients:
        raise HTTPException(400, "No active recipients match selection")
    import json
    created = []
    skipped = 0
    for target in recipients:
        pref = db.get(NoticePreference, target.id)
        settings = json.loads(pref.categories_json or "{}") if pref else {}
        # Critical notices bypass category opt-outs; routine and important notices do not.
        if b.priority != "critical" and settings.get(b.category, True) is False:
            skipped += 1
            continue
        n = Notice(sender_id=user.id, recipient_id=target.id, category=b.category, priority=b.priority,
                   title=b.title.strip(), body=b.body.strip(), sound=b.sound)
        db.add(n)
        created.append(n)
    db.flush()
    log(db, user, "notification_broadcast", "notification", None,
        f"sent={len(created)} skipped_preferences={skipped} category={b.category} priority={b.priority} groups={sorted(set(b.group_ids))}")
    result = {"sent": len(created), "skipped_preferences": skipped, "ids": [n.id for n in created]}
    if b.request_key:
        db.add(NoticeBatch(sender_id=user.id, request_key=b.request_key, payload_hash=digest, result_json=json.dumps(result)))
    try:
        db.commit()
    except IntegrityError:
        # Two requests with the same idempotency key can pass the initial
        # lookup concurrently. The unique constraint is the final arbiter;
        # rollback this transaction (including its Notice rows), then return
        # the result committed by the winning request.
        db.rollback()
        if not b.request_key:
            raise
        previous = db.scalar(select(NoticeBatch).where(
            NoticeBatch.sender_id == user.id,
            NoticeBatch.request_key == b.request_key,
        ))
        if previous is None:
            raise
        if previous.payload_hash != digest:
            raise HTTPException(409, "Request key already used with a different payload")
        return json.loads(previous.result_json)
    return result


@router.get("/notifications")
def list_notices(after: int = 0, unread_only: bool = False, limit: int = 100,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    q = select(Notice).where(Notice.recipient_id == user.id, Notice.id > after).order_by(Notice.id.desc()).limit(limit)
    if unread_only:
        q = q.where(Notice.acknowledged_at.is_(None))
    return [notice_out(n) for n in reversed(db.scalars(q).all())]


@router.post("/notifications/{nid}/ack")
def acknowledge(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notice, nid)
    if not n or n.recipient_id != user.id:
        raise HTTPException(404, "Notification not found")
    if n.acknowledged_at is None:
        n.acknowledged_at = now()
        log(db, user, "notification_ack", "notification", n.id, n.priority)
        db.commit()
    return {"ok": True, "acknowledged_at": n.acknowledged_at.isoformat() + "Z"}


class NoticeTemplate(Base):
    __tablename__ = "notification_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(32), default="general")
    priority: Mapped[str] = mapped_column(String(12), default="normal")
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class NoticeTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = "general"
    priority: str = "normal"
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)


@router.get("/notifications/templates")
def list_templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    return [dict(id=x.id, name=x.name, category=x.category, priority=x.priority,
                 title=x.title, body=x.body, updated_at=x.updated_at.isoformat() + "Z")
            for x in db.scalars(select(NoticeTemplate).order_by(NoticeTemplate.name)).all()]


@router.put("/notifications/templates")
def save_template(b: NoticeTemplateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    if b.category not in ("general", "orders", "safety", "finance", "system"):
        raise HTTPException(400, "Unsupported notification category")
    if b.priority not in ("normal", "important", "critical"):
        raise HTTPException(400, "Unsupported priority")
    name = b.name.strip()
    item = db.scalar(select(NoticeTemplate).where(NoticeTemplate.name == name))
    if item is None:
        item = NoticeTemplate(name=name, updated_by=user.id)
        db.add(item)
    item.category, item.priority = b.category, b.priority
    item.title, item.body, item.updated_by = b.title.strip(), b.body.strip(), user.id
    db.commit()
    db.refresh(item)
    return {"ok": True, "id": item.id}


@router.delete("/notifications/templates/{template_id}")
def delete_template(template_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    item = db.get(NoticeTemplate, template_id)
    if item is None:
        raise HTTPException(404, "Template not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


class NoticeGroup(Base):
    __tablename__ = "notification_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    member_ids: Mapped[str] = mapped_column(Text, default="[]")
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)


class NoticeGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    member_ids: list[int] = Field(default_factory=list, max_length=500)


@router.get("/notifications/groups")
def list_notice_groups(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    import json
    result = []
    for g in db.scalars(select(NoticeGroup).order_by(NoticeGroup.name)).all():
        ids = json.loads(g.member_ids or "[]")
        active = db.scalars(select(User).where(User.id.in_(ids), User.is_active.is_(True))).all() if ids else []
        result.append({"id":g.id,"name":g.name,"member_ids":[u.id for u in active],
                       "members":[{"id":u.id,"name":getattr(u,"full_name",None) or u.username,"role":u.role} for u in active]})
    return result


@router.put("/notifications/groups")
def save_notice_group(b: NoticeGroupIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    import json
    name = b.name.strip()
    if not name:
        raise HTTPException(400, "Group name is required")
    if len(set(b.member_ids)) != len(b.member_ids):
        raise HTTPException(400, "Duplicate member IDs")
    people = db.scalars(select(User).where(User.id.in_(b.member_ids), User.is_active.is_(True))).all() if b.member_ids else []
    if {u.id for u in people} != set(b.member_ids):
        raise HTTPException(400, "Some members do not exist or are inactive")
    group = db.scalar(select(NoticeGroup).where(NoticeGroup.name == name))
    if group is None:
        group = NoticeGroup(name=name, updated_by=user.id)
        db.add(group)
    group.member_ids = json.dumps(sorted(set(b.member_ids)))
    group.updated_by = user.id
    # Flush first so creation audit events always carry the durable group ID.
    db.flush()
    log(db,user,"notification_group_save","notification_group",group.id,f"name={name} members={len(b.member_ids)}")
    db.commit()
    return {"ok":True,"id":group.id,"member_count":len(b.member_ids)}


@router.delete("/notifications/groups/{group_id}")
def delete_notice_group(group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    group = db.get(NoticeGroup,group_id)
    if group is None:
        raise HTTPException(404,"Group not found")
    log(db,user,"notification_group_delete","notification_group",group.id,group.name)
    db.delete(group)
    db.commit()
    return {"ok":True}
