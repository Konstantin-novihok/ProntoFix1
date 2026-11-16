"""Внутренний мост Home Master -> ProntoF. Пользователи работают только в Home Master."""
import os
import re
import datetime as dt
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, Integer, String, DateTime, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMIN, CLIENT, EXECUTOR, HEAD, OWNER, STAFF, Base, User, current_user,
                    get_db, get_order, log, need, now)

router = APIRouter()
PRONTOF_API_URL = os.getenv("PRONTOF_API_URL", "").rstrip("/")
PRONTOF_INTERNAL_KEY = os.getenv("PRONTOF_INTERNAL_KEY", "")
CHUNK_LIMIT = 32 * 1024 * 1024


class OrderVideoJob(Base):
    __tablename__ = "order_video_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    upload_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    remote_job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    target_language: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class VideoUploadComplete(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    total_chunks: int = Field(ge=1, le=100001)
    source_language: Optional[str] = None
    target_language: str = Field(min_length=2, max_length=8)


def _ensure_config():
    if not PRONTOF_API_URL or not PRONTOF_INTERNAL_KEY:
        raise HTTPException(503, "Видеообработка не подключена: проверьте PRONTOF_API_URL и PRONTOF_INTERNAL_KEY на сервере Home Master")


def _headers():
    return {"X-ProntoF-Internal-Key": PRONTOF_INTERNAL_KEY}


async def _remote(method: str, path: str, **kwargs):
    _ensure_config()
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.request(method, PRONTOF_API_URL + path, headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Сервис обработки видео недоступен: {exc.__class__.__name__}")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text[:500])
        except Exception:
            detail = response.text[:500]
        raise HTTPException(response.status_code, detail)
    return response


def _check_order(oid: int, user: User, db: Session):
    need(user, OWNER, ADMIN, HEAD, EXECUTOR, CLIENT, STAFF)
    return get_order(db, user, oid)


@router.put("/orders/{oid}/video-processing/uploads/{upload_id}/chunks/{index}")
async def video_upload_chunk(oid: int, upload_id: str, index: int, request: Request,
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_order(oid, user, db)
    if not re.fullmatch(r"hm-[A-Za-z0-9-]{8,60}", upload_id) or index < 0 or index > 100000:
        raise HTTPException(400, "Некорректный ID загрузки или номер части")
    body = await request.body()
    if not body or len(body) > CHUNK_LIMIT:
        raise HTTPException(413, "Размер части должен быть от 1 байта до 32 MiB")
    response = await _remote("PUT", f"/internal/orders/{oid}/uploads/{upload_id}/chunks/{index}", content=body)
    return response.json()


@router.post("/orders/{oid}/video-processing/uploads/{upload_id}/complete")
async def video_upload_complete(oid: int, upload_id: str, data: VideoUploadComplete,
                                user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_order(oid, user, db)
    if not re.fullmatch(r"hm-[A-Za-z0-9-]{8,60}", upload_id):
        raise HTTPException(400, "Некорректный ID загрузки")
    existing = db.scalar(select(OrderVideoJob).where(OrderVideoJob.upload_id == upload_id))
    if existing:
        if existing.order_id != oid or existing.user_id != user.id:
            raise HTTPException(409, "ID загрузки уже использован")
        return {"job_id": existing.remote_job_id, "order_id": oid, "status": "queued", "filename": existing.filename}
    response = await _remote("POST", f"/internal/orders/{oid}/uploads/{upload_id}/complete",
                             json=data.model_dump())
    result = response.json()
    row = OrderVideoJob(order_id=oid, user_id=user.id, upload_id=upload_id,
                        remote_job_id=result["job_id"], filename=data.filename[:255],
                        target_language=data.target_language)
    db.add(row)
    log(db, user, "video_processing_start", "order", oid, data.filename[:200])
    try:
        db.commit()
    except Exception:
        db.rollback()
        existing = db.scalar(select(OrderVideoJob).where(OrderVideoJob.upload_id == upload_id))
        if existing and existing.order_id == oid and existing.user_id == user.id:
            return {"job_id": existing.remote_job_id, "order_id": oid, "status": "queued", "filename": existing.filename}
        raise HTTPException(409, "Не удалось сохранить связь видео с заказом; повторите отправку с тем же ID")
    return {"job_id": result["job_id"], "order_id": oid, "status": result.get("status", "queued"),
            "filename": data.filename, "size_bytes": result.get("size_bytes")}


@router.get("/orders/{oid}/video-processing")
async def order_video_processing(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_order(oid, user, db)
    rows = db.scalars(select(OrderVideoJob).where(OrderVideoJob.order_id == oid).order_by(OrderVideoJob.id.desc())).all()
    out = []
    for row in rows:
        try:
            response = await _remote("GET", f"/internal/jobs/{row.remote_job_id}")
            item = response.json()
            if item.get("order_id") != oid:
                raise HTTPException(409, "Задача не связана с этим заказом")
            out.append({"job_id": row.remote_job_id, "filename": row.filename,
                        "target_language": row.target_language, **item})
        except HTTPException as exc:
            out.append({"job_id": row.remote_job_id, "filename": row.filename,
                        "target_language": row.target_language, "status": "unavailable",
                        "message": "Не удалось получить состояние сервиса обработки", "error": str(exc.detail)})
    return out
