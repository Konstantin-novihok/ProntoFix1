"""
Файлы и чат.

  StoredFile        файлы чата и склада (фото, видео, документы). Файлы заказов (Media) и документы пользователей (UserDoc)
                    остаются в своих таблицах — менеджер хранилища показывает ВСЕ три источника единым списком.
  Менеджер файлов   только администратор: просмотр, сортировка (дата / размер / имя / отправитель), поиск, удаление любого файла.
  Общий чат         только сотрудники: текст, файлы, геопозиция, ссылка на складскую позицию. История хранится на сервере.
"""
import datetime as dt
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, EXECUTOR, EXT_KIND, HEAD, MEDIA_DIR, DOCS_DIR, OBSERVER, STAFF_ROLES, Base, Media, User,
                    UserDoc, check_upload, current_user, file_response, get_db, guess_mime, log, need, now, save_stream,
                    DATA_DIR)

router = APIRouter()
FILES_DIR = os.path.join(DATA_DIR, "files")
os.makedirs(FILES_DIR, exist_ok=True)
CHAT_WRITERS = (*ADMINS, HEAD, EXECUTOR)        # наблюдатель в чате только читает


class StoredFile(Base):
    __tablename__ = "stored_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(100))
    original: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(10), default="doc")
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(12), default="chat")        # chat | warehouse
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # id позиции склада / движения
    description: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="text")          # text | location | file | item
    text: Mapped[str] = mapped_column(Text, default="")
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    file_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)


async def store_upload(db: Session, file: UploadFile, user: User, source: str, ref_id: Optional[int] = None, description: str = "") -> StoredFile:
    ext, kind = check_upload(file.filename, file.content_type)
    name, size = await save_stream(file, FILES_DIR, ext)
    f = StoredFile(filename=name, original=(file.filename or name)[:200], mime=guess_mime(name), size=size, kind=kind,
                   uploader_id=user.id, source=source, ref_id=ref_id, description=description[:500])
    db.add(f)
    db.flush()
    return f


def file_out(f: StoredFile, db: Optional[Session] = None):
    u = db.get(User, f.uploader_id) if db else None
    return dict(id=f.id, original=f.original, mime=f.mime, size=f.size, kind=f.kind, description=f.description,
                uploader=(u.full_name or u.username) if u else None, created_at=f.created_at.isoformat())


@router.get("/files/{fid}")
def download_file(fid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Файлы чата и склада — доступны сотрудникам компании."""
    need(user, *STAFF_ROLES)
    f = db.get(StoredFile, fid)
    if not f:
        raise HTTPException(404)
    return file_response(os.path.join(FILES_DIR, f.filename), f.original, f.kind, f.mime)


# ───────────── чат ─────────────
def msg_out(db: Session, m: ChatMessage):
    u = db.get(User, m.sender_id)
    d = dict(id=m.id, sender_id=m.sender_id, sender=(u.full_name or u.username) if u else "?", sender_company=u.company_name if u else "",
             sender_role=u.role if u else None, kind=m.kind, text="" if m.deleted else m.text, lat=m.lat, lon=m.lon,
             deleted=m.deleted, created_at=m.created_at.isoformat(), file=None, item=None)
    if m.file_id and not m.deleted:
        f = db.get(StoredFile, m.file_id)
        d["file"] = file_out(f, db) if f else None
    if m.item_id and not m.deleted:
        from warehouse import Item, holders_of     # локальный импорт (модуль склада загружается сервером)
        it = db.get(Item, m.item_id)
        if it:
            d["item"] = dict(id=it.id, name=it.name, unit=it.unit, holders=holders_of(db, it.id))
    return d


@router.get("/chat")
def chat_list(after: int = 0, before: int = 0, limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """after=ID — только новые сообщения (опрос раз в несколько секунд); before=ID — подгрузка старой истории."""
    need(user, *STAFF_ROLES)
    limit = max(1, min(limit, 200))
    q = select(ChatMessage)
    if after:
        rows = db.scalars(q.where(ChatMessage.id > after).order_by(ChatMessage.id).limit(limit)).all()
    else:
        if before:
            q = q.where(ChatMessage.id < before)
        rows = list(reversed(db.scalars(q.order_by(ChatMessage.id.desc()).limit(limit)).all()))
    return [msg_out(db, m) for m in rows]


class ChatIn(BaseModel):
    kind: str = "text"
    text: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    item_id: Optional[int] = None


@router.post("/chat")
def chat_send(b: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *CHAT_WRITERS)
    if b.kind not in ("text", "location", "item"):
        raise HTTPException(400, "Bad kind")
    if b.kind == "text" and not b.text.strip():
        raise HTTPException(400, "Empty message")
    if b.kind == "location":
        if b.lat is None or b.lon is None or not (-90 <= b.lat <= 90 and -180 <= b.lon <= 180):
            raise HTTPException(400, "Bad location")
    if b.kind == "item":
        from warehouse import Item
        if not b.item_id or not db.get(Item, b.item_id):
            raise HTTPException(404, "Item not found")
    m = ChatMessage(sender_id=user.id, kind=b.kind, text=b.text.strip()[:4000], lat=b.lat, lon=b.lon, item_id=b.item_id)
    db.add(m)
    db.flush()
    if b.kind == "location":                          # поделившись местом, сотрудник обновляет и своё положение на карте
        user.last_lat, user.last_lon, user.last_seen = b.lat, b.lon, now()
    db.commit()
    return msg_out(db, m)


@router.post("/chat/files")
async def chat_send_file(file: UploadFile = File(...), text: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *CHAT_WRITERS)
    f = await store_upload(db, file, user, "chat")
    m = ChatMessage(sender_id=user.id, kind="file", text=text.strip()[:1000], file_id=f.id)
    db.add(m)
    db.flush()
    log(db, user, "chat_file", "file", f.id, f.original)
    db.commit()
    return msg_out(db, m)


@router.delete("/chat/{mid}")
def chat_delete(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    m = db.get(ChatMessage, mid)
    if not m:
        raise HTTPException(404)
    m.deleted, m.text = True, ""
    log(db, user, "chat_delete", "chat", mid)
    db.commit()
    return {"ok": True}


# ───────────── менеджер хранилища (администратор) ─────────────
def _size(path: str, known: Optional[int]) -> int:
    if known is not None:
        return known
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def all_files(db: Session):
    """Единый список всех файлов сервера. Ключ: m:<id> — файл заказа, d:<id> — документ пользователя, f:<id> — чат/склад."""
    users = {u.id: (u.full_name or u.username) for u in db.scalars(select(User))}
    rows = []
    for m in db.scalars(select(Media)):
        rows.append(dict(key=f"m:{m.id}", name=m.original, size=_size(os.path.join(MEDIA_DIR, m.filename), m.size), mime=m.mime,
                         sender=users.get(m.user_id, "?"), sender_id=m.user_id, date=m.created_at.isoformat(), source="order", ref=m.order_id,
                         kind=EXT_KIND.get(os.path.splitext(m.filename)[1].lstrip("."), "doc")))
    for d in db.scalars(select(UserDoc)):
        rows.append(dict(key=f"d:{d.id}", name=d.original, size=_size(os.path.join(DOCS_DIR, d.filename), None), mime=d.mime,
                         sender=users.get(d.user_id, "?"), sender_id=d.user_id, date=d.created_at.isoformat(), source="document", ref=d.user_id,
                         kind="image" if d.mime == "image/jpeg" else "doc"))
    for f in db.scalars(select(StoredFile)):
        rows.append(dict(key=f"f:{f.id}", name=f.original, size=f.size, mime=f.mime, sender=users.get(f.uploader_id, "?"),
                         sender_id=f.uploader_id, date=f.created_at.isoformat(), source=f.source, ref=f.ref_id, kind=f.kind))
    return rows


@router.get("/storage/files")
def storage_files(sort: str = "date", dir: str = "desc", q: str = "", source: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Сортировка: date | size | name | sender (по возрастанию asc / убыванию desc)."""
    need(user, *ADMINS)
    rows = all_files(db)
    if source:
        rows = [r for r in rows if r["source"] == source]
    if q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in (r["sender"] or "").lower()]
    keyf = {"date": lambda r: r["date"], "size": lambda r: r["size"], "name": lambda r: r["name"].lower(),
            "sender": lambda r: (r["sender"] or "").lower()}.get(sort, lambda r: r["date"])
    rows.sort(key=keyf, reverse=(dir != "asc"))
    total = sum(r["size"] for r in rows)
    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + r["size"]
    return dict(count=len(rows), total_bytes=total, by_source=by_source, items=rows[:2000])


def _locate(db: Session, key: str):
    kind, _, sid = key.partition(":")
    if not sid.isdigit():
        raise HTTPException(400, "Bad key")
    sid = int(sid)
    if kind == "m":
        o = db.get(Media, sid)
        return (o, os.path.join(MEDIA_DIR, o.filename)) if o else (None, None)
    if kind == "d":
        o = db.get(UserDoc, sid)
        return (o, os.path.join(DOCS_DIR, o.filename)) if o else (None, None)
    if kind == "f":
        o = db.get(StoredFile, sid)
        return (o, os.path.join(FILES_DIR, o.filename)) if o else (None, None)
    raise HTTPException(400, "Bad key")


@router.get("/storage/files/{key}/download")
def storage_download(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    obj, path = _locate(db, key)
    if not obj or not os.path.exists(path):
        raise HTTPException(404)
    log(db, user, "storage_view", "file", None, key)
    db.commit()
    mime = obj.mime
    return file_response(path, getattr(obj, "original"), "doc" if mime == "application/pdf" else EXT_KIND.get(os.path.splitext(path)[1].lstrip("."), "doc"), mime)


@router.delete("/storage/files/{key}")
def storage_delete(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Администратор удаляет любой файл: с диска и из базы. Сообщение чата остаётся с пометкой «файл удалён»."""
    need(user, *ADMINS)
    obj, path = _locate(db, key)
    if not obj:
        raise HTTPException(404)
    name = getattr(obj, "original", "")
    if isinstance(obj, StoredFile):
        for m in db.scalars(select(ChatMessage).where(ChatMessage.file_id == obj.id)):
            m.file_id, m.text = None, (m.text + " " if m.text else "") + "[file deleted]"
    db.delete(obj)
    try:
        os.remove(path)
    except OSError:
        pass
    log(db, user, "storage_delete", "file", None, f"{key} {name}")
    db.commit()
    return {"ok": True}
