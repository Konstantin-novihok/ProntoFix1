"""
СЕРВЕР учёта заказов на ремонт и обслуживание бытовой техники.
Запускается на TrueNAS (Docker). Хранит пользователей, заказы, фото/видео и ПОЛНЫЙ журнал действий.

Стек: FastAPI (REST API) + SQLAlchemy (БД; SQLite по умолчанию, можно PostgreSQL) + JWT-токены.
Документация API открывается сама по адресу  http://<сервер>:8000/docs
"""
import base64
import datetime as dt
import importlib
import json
import hashlib
import hmac
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import (Boolean, inspect as sa_inspect, text as sa_text, DateTime, Float, ForeignKey, Integer, String,
                        Text, and_, create_engine, func, or_, select)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            sessionmaker)
from sqlalchemy.exc import IntegrityError

# ───────────────────────── Настройки ─────────────────────────
DATA_DIR = os.getenv("DATA_DIR", "./data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/service.db")
ALLOW_REGISTRATION = os.getenv("ALLOW_REGISTRATION", "1") == "1"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
TOKEN_DAYS = int(os.getenv("TOKEN_DAYS", "30"))


def _load_secret() -> str:
    """Ключ подписи токенов: из переменной окружения или генерируется один раз и хранится в /data."""
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    return open(path).read().strip()


SECRET = _load_secret()

# Паспортные данные хранятся ЗАШИФРОВАННЫМИ (Fernet/AES). Ключ выводится из SECRET_KEY:
# потеряете ключ — расшифровать данные будет нельзя. Дополнительно включите шифрование датасета в TrueNAS.
_FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET.encode()).digest()))
DOCS_DIR = os.path.join(DATA_DIR, "docs")      # сканы документов — отдельно от медиа заказов
os.makedirs(DOCS_DIR, exist_ok=True)

# Настройки карт, которые сервер раздаёт приложению (экран регистрации открыт без входа)
MAP_PROVIDER = os.getenv("MAP_PROVIDER", "google")          # google | osm | custom | offline
GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_KEY", "")          # ключ Google Map Tiles API
CUSTOM_TILE_URL = os.getenv("CUSTOM_TILE_URL", "")          # напр. https://tiles.my.com/{z}/{x}/{y}.png


def enc(value: str) -> str:
    return _FERNET.encrypt(value.encode()).decode() if value else ""


def dec(value: str) -> str:
    try:
        return _FERNET.decrypt(value.encode()).decode() if value else ""
    except Exception:
        return ""


# ───────────────────────── Роли и статусы ─────────────────────────
# Чтобы добавить роль: допишите константу здесь, затем правила в visible_orders()/эндпоинтах
# и подписи role_* в app/locales/*.json.
OWNER, HEAD, EXECUTOR, CLIENT, STAFF, OBSERVER, ADMIN = 1, 2, 3, 4, 5, 6, 7
ADMINS = (OWNER, ADMIN)                           # могут администрировать сервер (владелец + назначенные администраторы)
STAFF_ROLES = (OWNER, ADMIN, HEAD, EXECUTOR, OBSERVER)   # «внутренние» сотрудники компании
PRICE_ROLES = (OWNER, ADMIN, HEAD, OBSERVER, CLIENT)      # кто видит цену заказа
STATUSES = ["new", "assigned", "accepted", "in_progress", "estimate", "done", "cancelled"]


# ───────────────────────── База данных ─────────────────────────
def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    role: Mapped[int] = mapped_column(Integer, default=CLIENT)
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # для роли 5: id заказчика-работодателя
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    # --- данные компании/заказчика (регистрация) ---
    company_name: Mapped[str] = mapped_column(String(200), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(String(300), default="")
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # --- персональные данные (шифруются; видит только суперпользователь) ---
    passport_number_enc: Mapped[str] = mapped_column(Text, default="")
    passport_issued_enc: Mapped[str] = mapped_column(Text, default="")
    consent_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)  # согласие на обработку данных
    # --- сотрудники и подрядчики ---
    employment: Mapped[str] = mapped_column(String(12), default="internal")      # internal (штат) | external (подрядчик)
    employee_no: Mapped[str] = mapped_column(String(40), default="")             # табельный номер (идентификация штата)
    tax_id: Mapped[str] = mapped_column(String(40), default="")                  # ИНН/рег. номер (идентификация подрядчика)
    verification: Mapped[str] = mapped_column(String(12), default="verified")    # verified | pending | rejected
    rate_type: Mapped[str] = mapped_column(String(12), default="hourly")         # hourly | per_order | percent
    rate_value: Mapped[float] = mapped_column(Float, default=0.0)
    skin_json: Mapped[str] = mapped_column(Text, default="")                     # личный скин пользователя
    last_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)      # последнее известное положение (трекинг)
    last_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)  # timestamp последнего GPS-пакета
    location_received_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)  # время приёма GPS сервером
    last_seen: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


class UserDoc(Base):  # скан/фото документа пользователя (JPEG или PDF)
    __tablename__ = "user_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(100))
    original: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Department(Base):  # «направление» (стиральные машины, холодильники, мелкий ремонт...)
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    head_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    department_id: Mapped[Optional[int]] = mapped_column(ForeignKey("departments.id"), nullable=True)
    executor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    address: Mapped[str] = mapped_column(String(300), default="")
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimate_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimate_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)
    # --- услуга и финансы ---
    service_type: Mapped[str] = mapped_column(String(80), default="")
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)         # цена услуги для заказчика
    currency: Mapped[str] = mapped_column(String(3), default="UAH")               # ISO 4217 currency for all order finance
    labor_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # отработанные часы
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # километры дороги к объекту
    settled_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)   # расчёт проведён
    arrived_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)   # исполнитель прибыл
    geo_verified: Mapped[bool] = mapped_column(Boolean, default=False)           # координаты уточнены по GPS исполнителя


class OrderSyncKey(Base):
    """Idempotency receipt for orders created by retrying/offline clients."""
    __tablename__ = "order_sync_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    client_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    payload_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class CancellationRecord(Base):
    """Minimal cancellation audit metadata for owner-only analytics."""
    __tablename__ = "order_cancellations"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(300), default="")
    cancelled_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    public: Mapped[bool] = mapped_column(Boolean, default=True)  # False = внутренняя заметка, заказчик не видит
    kind: Mapped[str] = mapped_column(String(20), default="comment")  # comment | estimate
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Media(Base):
    __tablename__ = "media"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(100))   # имя на диске
    original: Mapped[str] = mapped_column(String(200))   # исходное имя
    mime: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class MediaUploadReceipt(Base):
    """Idempotency receipt for attachment uploads. Key is globally unique; owner/order/content are verified."""
    __tablename__ = "media_upload_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    upload_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media.id"), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class AppSetting(Base):   # общие настройки приложения (ключ → JSON-значение)
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Audit(Base):  # журнал: кто, что, когда, над чем (создание, назначение, смена прав...)
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log(db: Session, actor, action: str, ttype: str, tid: Optional[int], details: str = ""):
    """Записать событие в журнал. Вызывается при КАЖДОМ значимом действии."""
    db.add(Audit(actor_id=getattr(actor, "id", None), action=action, target_type=ttype, target_id=tid, details=details))


# ───────────────────────── Пароли и токены ─────────────────────────
def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    salt, h = stored.split("$")
    return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex(), h)


def make_token(user: User) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub": str(user.id), "exp": exp}, SECRET, algorithm="HS256")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Токен берётся из заголовка Authorization: Bearer ... либо из ?token= (нужно для показа картинок)."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        uid = int(jwt.decode(token, SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        raise HTTPException(401, "Invalid token")
    user = db.get(User, uid)
    if not user or not user.is_active:
        raise HTTPException(401, "User disabled")
    return user


def need(user: User, *roles: int):
    if user.role not in roles:
        raise HTTPException(403, "Forbidden")


SETTING_DEFAULTS = {
    "app_name": "ProntoFix", "company_name": "", "currency": "UAH", "cost_per_km": 0.0, "road_factor": 1.3,
    "overdraft_allowed": True, "require_employee_no": True, "id_rules_text": "",
    "service_types": ["Ремонт стиральных машин", "Ремонт холодильников", "Мелкий ремонт", "Диагностика", "Выезд мастера"],
    "default_skin": None,
}


def get_setting(db: Session, key: str):
    row = db.get(AppSetting, key)
    if row is None or row.value == "":
        return SETTING_DEFAULTS.get(key)
    try:
        return json.loads(row.value)
    except Exception:
        return SETTING_DEFAULTS.get(key)


def set_setting(db: Session, key: str, value):
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key)
        db.add(row)
    row.value = json.dumps(value, ensure_ascii=False)


# Безопасная загрузка файлов: только известные типы; исполняемые и «активные» (html/js/svg) запрещены,
# потому что файлы отдаются с того же адреса, что и приложение.
ALLOWED_EXT = {
    "image": ["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp"],
    "video": ["mp4", "mov", "webm", "3gp", "mkv", "avi", "m4v"],
    "audio": ["mp3", "m4a", "ogg", "wav", "aac", "amr"],
    "doc": ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv", "rtf", "odt", "ods"],
    "archive": ["zip", "7z", "rar"],
}
EXT_KIND = {e: k for k, exts in ALLOWED_EXT.items() for e in exts}
INLINE_KINDS = ("image", "video", "audio")


def check_upload(filename: str, content_type: str):
    """→ (расширение, вид файла). Бросает 400, если тип не разрешён."""
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    kind = EXT_KIND.get(ext)
    if not kind:
        raise HTTPException(400, "File type not allowed")
    return ext, kind


# ───────────────────────── Сериализация ─────────────────────────
def user_out(u: Optional[User]):
    if not u:
        return None
    return dict(id=u.id, username=u.username, full_name=u.full_name, phone=u.phone, role=u.role,
                department_id=u.department_id, parent_id=u.parent_id, is_active=u.is_active,
                company_name=u.company_name, website=u.website, address=u.address, lat=u.lat, lon=u.lon,
                employment=u.employment or "internal", employee_no=u.employee_no or "",
                verification=u.verification or "verified")


def order_out(db: Session, o: Order, viewer: Optional["User"] = None):
    def nm(uid):
        u = db.get(User, uid) if uid else None
        return (u.full_name or u.username) if u else None
    dep = db.get(Department, o.department_id) if o.department_id else None
    cl = db.get(User, o.client_id) if o.client_id else None
    ex = db.get(User, o.executor_id) if o.executor_id else None
    return dict(id=o.id, title=o.title, description=o.description, status=o.status,
                client_id=o.client_id, client_name=nm(o.client_id), created_by=o.created_by,
                created_by_name=nm(o.created_by), department_id=o.department_id,
                department_name=dep.name if dep else None, executor_id=o.executor_id,
                executor_name=nm(o.executor_id), address=o.address, lat=o.lat, lon=o.lon,
                estimate_hours=o.estimate_hours, estimate_price=o.estimate_price, rating=o.rating,
                created_at=o.created_at.isoformat(), updated_at=o.updated_at.isoformat(),
                service_type=o.service_type or "", labor_hours=o.labor_hours, distance_km=o.distance_km,
                arrived_at=o.arrived_at.isoformat() if o.arrived_at else None, geo_verified=bool(o.geo_verified),
                settled=bool(o.settled_at), client_company=cl.company_name if cl else None,
                executor_company=ex.company_name if ex else None,
                executor_employment=(ex.employment or "internal") if ex else None,
                price=o.price if (viewer is not None and viewer.role in PRICE_ROLES) else None, currency=(o.currency or "UAH"))


def visible_orders(user: User):
    """ПРАВА ДОСТУПА К ЗАКАЗАМ: единое место, определяющее, кто какие заказы видит."""
    q = select(Order)
    r = user.role
    if r in (OWNER, ADMIN, OBSERVER):
        return q
    if r == HEAD:      # видит заказы своего направления
        return q.where(Order.department_id == user.department_id) if user.department_id else q.where(Order.id < 0)
    if r == EXECUTOR:  # свои + свободные в своём направлении
        cond = Order.executor_id == user.id
        if user.department_id:
            cond = or_(cond, and_(Order.department_id == user.department_id, Order.executor_id.is_(None)))
        return q.where(cond)
    if r == CLIENT:    # все заказы своей организации (и свои, и созданные работниками)
        return q.where(Order.client_id == user.id)
    return q.where(Order.created_by == user.id)  # STAFF: только созданные самим


def get_order(db: Session, user: User, oid: int) -> Order:
    o = db.scalar(visible_orders(user).where(Order.id == oid))
    if not o:
        raise HTTPException(404, "Order not found")
    return o


# ───────────────────────── Приложение ─────────────────────────
@asynccontextmanager
async def lifespan(_app):
    startup()      # создать таблицы, добавить недостающие колонки, создать владельца
    yield


app = FastAPI(title="Repair Service API", lifespan=lifespan)


def ensure_columns():
    """Мини-миграция: если в старой БД нет новых колонок — добавляет их (чтобы не терять данные)."""
    insp = sa_inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    conn.execute(sa_text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))


def startup():
    Base.metadata.create_all(engine)
    ensure_columns()
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(User).where(User.role == OWNER)):
            u = User(username=os.getenv("OWNER_USERNAME", "owner"), role=OWNER, full_name="Owner",
                     password_hash=hash_password(os.getenv("OWNER_PASSWORD", "change-me")))
            db.add(u)
            db.flush()
            log(db, None, "bootstrap_owner", "user", u.id)
            db.commit()


# ---------- Авторизация ----------
class RegisterIn(BaseModel):
    username: str
    password: str
    full_name: str = ""          # имя и фамилия
    phone: str = ""
    company_name: str = ""
    website: str = ""
    address: str = ""
    lat: Optional[float] = None  # положение на карте (GPS или выбрано вручную)
    lon: Optional[float] = None
    passport_number: str = ""
    passport_issued: str = ""    # кем и когда выдан
    consent: bool = False        # согласие на обработку персональных данных (обязательно)
    invite_code: str = ""        # код приглашения подрядчика (внешнего исполнителя)
    tax_id: str = ""             # ИНН/регистрационный номер (для подрядчиков)


@app.get("/config")
def public_config():
    """Публичные настройки карт для экрана регистрации (до входа). Ключ Google ограничьте в консоли Google Cloud
    только на Map Tiles API и добавьте квоты/бюджет."""
    return dict(map_provider=MAP_PROVIDER, google_maps_key=GOOGLE_MAPS_KEY, custom_tile_url=CUSTOM_TILE_URL,
                registration=ALLOW_REGISTRATION)


class Invite(Base):   # приглашение внешнего исполнителя (подрядчика)
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    department_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_value: Mapped[float] = mapped_column(Float, default=0.0)        # процент от прибыли для подрядчика
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    used_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/auth/register")
def register(b: RegisterIn, db: Session = Depends(get_db)):
    """Публичная регистрация создаёт ТОЛЬКО заказчика (роль 4). Остальные роли выдаёт суперпользователь."""
    if not ALLOW_REGISTRATION:
        raise HTTPException(403, "Registration disabled")
    if len(b.password) < 6 or len(b.username) < 3:
        raise HTTPException(400, "Username >= 3 and password >= 6 chars")
    if len(b.full_name.split()) < 2:
        raise HTTPException(400, "Enter first name and last name")
    if not b.consent:
        raise HTTPException(400, "Consent to personal data processing is required")
    if b.lat is not None and not (-90 <= b.lat <= 90 and -180 <= (b.lon or 0) <= 180):
        raise HTTPException(400, "Bad coordinates")
    if db.scalar(select(User).where(User.username == b.username.lower())):
        raise HTTPException(409, "Username taken")
    role, employment, verification, dep, inv = CLIENT, "internal", "verified", None, None
    if b.invite_code.strip():     # регистрация внешнего исполнителя по приглашению администратора
        inv = db.scalar(select(Invite).where(Invite.code == b.invite_code.strip().upper()))
        if not inv or inv.used_by or (inv.expires_at and inv.expires_at < now()):
            raise HTTPException(400, "Invite is invalid or already used")
        if not b.company_name.strip() or not (b.tax_id.strip() or b.passport_number.strip()):
            raise HTTPException(400, "Contractor must provide company and tax id / passport")
        role, employment, verification, dep = EXECUTOR, "external", "pending", inv.department_id
    u = User(username=b.username.lower(), password_hash=hash_password(b.password),
             full_name=b.full_name.strip(), phone=b.phone, role=role, company_name=b.company_name.strip(),
             website=b.website.strip(), address=b.address.strip(), lat=b.lat, lon=b.lon,
             passport_number_enc=enc(b.passport_number.strip()), passport_issued_enc=enc(b.passport_issued.strip()),
             consent_at=now(), employment=employment, verification=verification, department_id=dep,
             tax_id=b.tax_id.strip(), rate_type="percent" if inv else "hourly", rate_value=inv.rate_value if inv else 0.0)
    db.add(u)
    db.flush()
    if inv:
        inv.used_by = u.id
    log(db, u, "register", "user", u.id, f"role={role}; consent=yes" + ("; invite=" + inv.code if inv else ""))
    db.commit()
    return {"token": make_token(u), "user": me_out(u)}


@app.post("/auth/login")
def login(b: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == b.username.lower()))
    if not u or not u.is_active or not check_password(b.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    return {"token": make_token(u), "user": me_out(u)}


def me_out(u: User):
    d = user_out(u)
    try:
        d["skin"] = json.loads(u.skin_json) if u.skin_json else None
    except Exception:
        d["skin"] = None
    return d


@app.get("/me")
def me(user: User = Depends(current_user)):
    return me_out(user)


# ---------- Документы пользователя (скан паспорта и т.п.) ----------
DOC_TYPES = {"image/jpeg": (b"\xff\xd8\xff", ".jpg"), "application/pdf": (b"%PDF", ".pdf")}
MAX_DOC_MB = 30


@app.post("/me/documents")
async def upload_my_document(file: UploadFile = File(...), user: User = Depends(current_user),
                             db: Session = Depends(get_db)):
    """Только JPEG и PDF. Тип проверяется по СОДЕРЖИМОМУ файла (а не по расширению)."""
    data = await file.read(MAX_DOC_MB * 1024 * 1024 + 1)
    if len(data) > MAX_DOC_MB * 1024 * 1024:
        raise HTTPException(413, "File too large")
    mime = next((m for m, (magic, _e) in DOC_TYPES.items() if data.startswith(magic)), None)
    if not mime:
        raise HTTPException(400, "Only JPEG or PDF")
    name = uuid.uuid4().hex + DOC_TYPES[mime][1]
    with open(os.path.join(DOCS_DIR, name), "wb") as f:
        f.write(data)
    d = UserDoc(user_id=user.id, filename=name, original=(file.filename or name)[:200], mime=mime)
    db.add(d)
    db.flush()
    log(db, user, "upload_document", "user", user.id, f"{mime} {len(data)} bytes")
    db.commit()
    return dict(id=d.id, original=d.original, mime=d.mime)


@app.get("/documents/{did}")
def get_document(did: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.get(UserDoc, did)
    if not d or (user.role not in ADMINS and d.user_id != user.id):
        raise HTTPException(404)
    if user.role in ADMINS and d.user_id != user.id:
        log(db, user, "view_document", "user", d.user_id, f"doc={d.id}")
        db.commit()
    return FileResponse(os.path.join(DOCS_DIR, d.filename), media_type=d.mime, filename=d.original)


@app.get("/users/{uid}/private")
def user_private(uid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Персональные данные (паспорт, документы) — только суперпользователь; каждый просмотр пишется в журнал."""
    need(user, *ADMINS)
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404)
    log(db, user, "view_private", "user", t.id)
    db.commit()
    docs = [dict(id=d.id, original=d.original, mime=d.mime) for d in db.scalars(select(UserDoc).where(UserDoc.user_id == uid))]
    return dict(user=user_out(t), passport_number=dec(t.passport_number_enc), passport_issued=dec(t.passport_issued_enc),
                consent_at=t.consent_at.isoformat() if t.consent_at else None, documents=docs)


# ---------- Пользователи и права ----------
class UserIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    phone: str = ""
    role: int = EXECUTOR
    department_id: Optional[int] = None
    employment: str = "internal"      # internal (штат компании) | external (подрядчик)
    company_name: str = ""
    employee_no: str = ""
    tax_id: str = ""
    rate_type: str = "hourly"         # hourly | per_order | percent
    rate_value: float = 0.0


class UserPatch(BaseModel):
    role: Optional[int] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


@app.get("/users")
def list_users(role: Optional[int] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(User)
    if user.role in (OWNER, ADMIN, OBSERVER):
        pass
    elif user.role == HEAD:   # свои сотрудники + исполнители без направления (кандидаты)
        q = q.where(or_(User.department_id == user.department_id,
                        and_(User.role == EXECUTOR, User.department_id.is_(None))))
    elif user.role == CLIENT:  # свои работники
        q = q.where(User.parent_id == user.id)
    else:
        raise HTTPException(403, "Forbidden")
    if role:
        q = q.where(User.role == role)
    return [user_out(u) for u in db.scalars(q.order_by(User.id))]


@app.post("/users")
def create_user(b: UserIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, OWNER, ADMIN, HEAD, CLIENT)
    role, dep, parent = b.role, b.department_id, None
    if user.role == HEAD:        # начальник создаёт только исполнителей в своё направление
        role, dep = EXECUTOR, user.department_id
    elif user.role == CLIENT:    # заказчик создаёт только своих работников
        role, dep, parent = STAFF, None, user.id
    if role not in range(1, 8):
        raise HTTPException(400, "Bad role")
    if role in ADMINS and user.role != OWNER:
        raise HTTPException(403, "Only the owner can create owners and administrators")
    if db.scalar(select(User).where(User.username == b.username.lower())):
        raise HTTPException(409, "Username taken")
    employment = b.employment if b.employment in ("internal", "external") else "internal"
    can_pay = user.role in ADMINS
    company = b.company_name.strip()
    verification = "verified"
    if role in (HEAD, EXECUTOR, OBSERVER, ADMIN) and employment == "internal":
        if role in (HEAD, EXECUTOR) and get_setting(db, "require_employee_no") and not b.employee_no.strip():
            raise HTTPException(400, "Employee number is required for staff (company identification rule)")
        company = company or (get_setting(db, "company_name") or "")
    if employment == "external" and role == EXECUTOR:
        if not company or not b.tax_id.strip():
            raise HTTPException(400, "Contractor requires company name and tax id")
        verification = "pending"      # подрядчик допускается к заказам только после проверки администратором
    u = User(username=b.username.lower(), password_hash=hash_password(b.password), full_name=b.full_name,
             phone=b.phone, role=role, department_id=dep, parent_id=parent, employment=employment,
             company_name=company, employee_no=b.employee_no.strip(), tax_id=b.tax_id.strip(), verification=verification,
             rate_type=b.rate_type if (can_pay and b.rate_type in ("hourly", "per_order", "percent")) else "hourly",
             rate_value=max(0.0, b.rate_value) if can_pay else 0.0)
    db.add(u)
    db.flush()
    log(db, user, "create_user", "user", u.id, f"role={role} {employment}")
    db.commit()
    return user_out(u)


@app.patch("/users/{uid}")
def patch_user(uid: int, b: UserPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Суперпользователь меняет роль/направление/активность. Начальник — только переводит исполнителей в своё направление."""
    t = db.get(User, uid)
    if not t:
        raise HTTPException(404)
    sent = b.model_fields_set
    if user.role in ADMINS:
        if user.role != OWNER and (t.role in ADMINS or (b.role in ADMINS)):
            raise HTTPException(403, "Only the owner can change owners and administrators")
        owners = db.scalar(select(func.count()).select_from(User).where(User.role == OWNER, User.is_active))
        losing = t.role == OWNER and (("role" in sent and b.role != OWNER) or b.is_active is False)
        if losing and owners <= 1:
            raise HTTPException(400, "Cannot remove the last owner")
        if "role" in sent and b.role is not None:
            if b.role not in range(1, 8):
                raise HTTPException(400, "Bad role")
            log(db, user, "change_role", "user", t.id, f"{t.role}->{b.role}")
            t.role = b.role
        if "department_id" in sent:
            log(db, user, "change_department", "user", t.id, f"{t.department_id}->{b.department_id}")
            t.department_id = b.department_id
        if b.is_active is not None:
            log(db, user, "set_active", "user", t.id, str(b.is_active))
            t.is_active = b.is_active
    elif user.role == HEAD and user.department_id:
        ok = t.role == EXECUTOR and t.department_id in (None, user.department_id) \
            and b.department_id in (None, user.department_id) and sent <= {"department_id"}
        if not ok:
            raise HTTPException(403, "Forbidden")
        log(db, user, "change_department", "user", t.id, f"{t.department_id}->{b.department_id}")
        t.department_id = b.department_id
    else:
        raise HTTPException(403, "Forbidden")
    db.commit()
    return user_out(t)


# ---------- Направления ----------
class DepIn(BaseModel):
    name: str


class DepPatch(BaseModel):
    name: Optional[str] = None
    head_id: Optional[int] = None


@app.get("/departments")
def list_deps(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for d in db.scalars(select(Department).order_by(Department.name)):
        h = db.get(User, d.head_id) if d.head_id else None
        out.append(dict(id=d.id, name=d.name, head_id=d.head_id, head_name=(h.full_name or h.username) if h else None))
    return out


@app.post("/departments")
def create_dep(b: DepIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    d = Department(name=b.name.strip())
    db.add(d)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, "Department exists")
    log(db, user, "create_department", "department", d.id, d.name)
    db.commit()
    return dict(id=d.id, name=d.name, head_id=None, head_name=None)


@app.patch("/departments/{did}")
def patch_dep(did: int, b: DepPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Владелец назначает начальника направления: пользователь получает роль 2 и это направление."""
    need(user, *ADMINS)
    d = db.get(Department, did)
    if not d:
        raise HTTPException(404)
    if b.name:
        d.name = b.name
    if b.head_id:
        h = db.get(User, b.head_id)
        if not h:
            raise HTTPException(404, "User not found")
        log(db, user, "assign_head", "department", d.id, f"user={h.id} (role {h.role}->2)")
        h.role, h.department_id, d.head_id = HEAD, d.id, h.id
    db.commit()
    return {"ok": True}


# ---------- Заказы ----------
class OrderIn(BaseModel):
    title: str
    description: str = ""
    address: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    department_id: Optional[int] = None
    client_id: Optional[int] = None   # только если заказ создаёт владелец/начальник от имени заказчика
    service_type: str = ""            # вид услуги (список настраивает администратор)
    currency: Optional[str] = None      # ISO 4217; defaults to company currency\n    currency: Optional[str] = None  # ISO 4217; omitted = company base currency


@app.get("/orders")
def list_orders(status: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = visible_orders(user)
    if status:
        q = q.where(Order.status == status)
    return [order_out(db, o, user) for o in db.scalars(q.order_by(Order.id.desc()).limit(500))]


@app.post("/orders")
def create_order(b: OrderIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create order. X-Client-Request-ID makes offline retries idempotent."""
    need(user, OWNER, ADMIN, HEAD, CLIENT, STAFF)
    client_key = (request.headers.get("x-client-request-id") or "").strip()
    # Fingerprint validated canonical payload so an idempotency key cannot silently
    # turn a changed offline intent into a replay of an unrelated order.
    payload_sha256 = hashlib.sha256(json.dumps(b.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if client_key:
        if len(client_key) > 80:
            raise HTTPException(400, "X-Client-Request-ID must be at most 80 characters")
        receipt = db.scalar(select(OrderSyncKey).where(OrderSyncKey.client_key == client_key))
        if receipt:
            if receipt.user_id != user.id:
                raise HTTPException(409, "Request ID already belongs to another account")
            if receipt.payload_sha256 and not hmac.compare_digest(receipt.payload_sha256, payload_sha256):
                raise HTTPException(409, "Request ID was already used with a different payload")
            existing = db.get(Order, receipt.order_id)
            if not existing:
                raise HTTPException(409, "Idempotency receipt points to a missing order")
            return order_out(db, existing, user)
    if user.role == CLIENT:
        client_id = user.id
    elif user.role == STAFF:
        client_id = user.parent_id
    else:
        client_id = b.client_id
    order_currency = (b.currency or get_setting(db, "currency") or "UAH").strip().upper()
    if len(order_currency) != 3 or not order_currency.isascii() or not order_currency.isalpha():
        raise HTTPException(400, "Currency must be a three-letter ISO 4217 code")
    o = Order(title=b.title.strip() or "-", description=b.description, address=b.address, lat=b.lat, lon=b.lon,
              department_id=b.department_id, client_id=client_id, created_by=user.id,
              service_type=b.service_type.strip()[:80], currency=order_currency)
    if user.role == HEAD:
        o.department_id = user.department_id
    db.add(o)
    db.flush()
    if client_key:
        db.add(OrderSyncKey(user_id=user.id, client_key=client_key, order_id=o.id, payload_sha256=payload_sha256))
    log(db, user, "create_order", "order", o.id, o.title)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent retries can both miss the initial receipt lookup.
        # The unique key is the final arbiter; rollback the losing transaction,
        # then return the already-committed order only to its owning account.
        db.rollback()
        if client_key:
            receipt = db.scalar(select(OrderSyncKey).where(OrderSyncKey.client_key == client_key))
            if receipt and receipt.user_id == user.id:
                if receipt.payload_sha256 and not hmac.compare_digest(receipt.payload_sha256, payload_sha256):
                    raise HTTPException(409, "Request ID was already used with a different payload")
                existing = db.get(Order, receipt.order_id)
                if existing:
                    return order_out(db, existing, user)
        raise HTTPException(409, "Idempotency key conflict; retry with the original request ID")
    return order_out(db, o, user)


def comment_out(db: Session, c: Comment):
    u = db.get(User, c.user_id)
    return dict(id=c.id, user_id=c.user_id, author=(u.full_name or u.username) if u else "?", role=u.role if u else None,
                text=c.text, public=c.public, kind=c.kind, created_at=c.created_at.isoformat())


@app.get("/orders/{oid}")
def order_detail(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = get_order(db, user, oid)
    cq = select(Comment).where(Comment.order_id == oid)
    if user.role in (CLIENT, STAFF):      # заказчик не видит внутренние заметки
        cq = cq.where(Comment.public)
    comments = [comment_out(db, c) for c in db.scalars(cq.order_by(Comment.id))]
    media = [dict(id=m.id, original=m.original, mime=m.mime, user_id=m.user_id, size=m.size,
                  uploader=(db.get(User, m.user_id).full_name if db.get(User, m.user_id) else "?"))
             for m in db.scalars(select(Media).where(Media.order_id == oid).order_by(Media.id))]
    return dict(order=order_out(db, o, user), comments=comments, media=media)


@app.get("/orders/{oid}/history")
def order_history(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    get_order(db, user, oid)
    rows = db.scalars(select(Audit).where(Audit.target_type == "order", Audit.target_id == oid).order_by(Audit.id))
    return [audit_out(db, a) for a in rows]


class AssignIn(BaseModel):
    department_id: Optional[int] = None
    executor_id: Optional[int] = None


@app.post("/orders/{oid}/assign")
def assign(oid: int, b: AssignIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Владелец: направление и/или исполнитель. Начальник: исполнитель из СВОЕГО направления."""
    need(user, OWNER, ADMIN, HEAD)
    o = get_order(db, user, oid)
    if b.department_id:
        need(user, *ADMINS)
        if not db.get(Department, b.department_id):
            raise HTTPException(404, "Department not found")
        log(db, user, "assign_department", "order", o.id, f"{o.department_id}->{b.department_id}")
        o.department_id = b.department_id
    if b.executor_id:
        ex = db.get(User, b.executor_id)
        if not ex or ex.role != EXECUTOR:
            raise HTTPException(400, "Not an executor")
        if (ex.verification or "verified") != "verified":
            raise HTTPException(403, "Executor is not verified yet")
        if user.role == HEAD and ex.department_id != user.department_id:
            raise HTTPException(403, "Executor is not in your department")
        log(db, user, "assign_executor", "order", o.id, f"{o.executor_id}->{ex.id}")
        o.executor_id = ex.id
        if o.department_id is None:
            o.department_id = ex.department_id
        if o.status == "new":
            o.status = "assigned"
    db.commit()
    return order_out(db, o, user)


@app.post("/orders/{oid}/accept")
def accept(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, EXECUTOR)
    if (user.verification or "verified") != "verified":
        raise HTTPException(403, "Your account is not verified yet")
    o = get_order(db, user, oid)
    if o.executor_id not in (None, user.id):
        raise HTTPException(409, "Already taken")
    o.executor_id, o.status = user.id, "accepted"
    log(db, user, "accept_order", "order", o.id)
    db.commit()
    return order_out(db, o, user)


class StatusIn(BaseModel):
    status: str
    reason: str = ""


@app.post("/orders/{oid}/status")
def set_status(oid: int, b: StatusIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if b.status not in STATUSES:
        raise HTTPException(400, "Bad status")
    o = get_order(db, user, oid)
    allowed = (user.role in (OWNER, ADMIN, HEAD)
               or (user.role == EXECUTOR and o.executor_id == user.id)
               or (user.role == CLIENT and b.status == "cancelled"))
    if not allowed:
        raise HTTPException(403, "Forbidden")
    if b.status == "cancelled" and o.status != "cancelled":
        db.add(CancellationRecord(order_id=o.id, actor_id=user.id, reason=b.reason.strip()[:300]))
    log(db, user, "set_status", "order", o.id, f"{o.status}->{b.status}")
    o.status = b.status
    db.commit()
    return order_out(db, o, user)


@app.get("/analytics/cancellations")
def cancellation_analytics(limit: int = 500, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Owner/admin cancellation records, separated from active work queue."""
    need(user, OWNER, ADMIN)
    rows = db.execute(select(CancellationRecord, Order).join(Order, Order.id == CancellationRecord.order_id)
                      .order_by(CancellationRecord.cancelled_at.desc()).limit(min(max(limit, 1), 1000))).all()
    result = []
    for record, order in rows:
        actor = db.get(User, record.actor_id)
        result.append(dict(order_id=order.id, title=order.title, status=order.status,
                           actor=(actor.full_name or actor.username) if actor else "?",
                           reason=record.reason, cancelled_at=record.cancelled_at.isoformat(),
                           created_at=order.created_at.isoformat(), service_type=order.service_type))
    return result


class EstimateIn(BaseModel):
    hours: float
    price: float
    text: str = ""


@app.post("/orders/{oid}/estimate")
def estimate(oid: int, b: EstimateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Оценка объёма работ — виден заказчику как публичное сообщение."""
    need(user, OWNER, ADMIN, HEAD, EXECUTOR)
    o = get_order(db, user, oid)
    o.estimate_hours, o.estimate_price = b.hours, b.price
    if o.status in ("new", "assigned", "accepted", "in_progress"):
        o.status = "estimate"
    db.add(Comment(order_id=o.id, user_id=user.id, kind="estimate", public=True,
                   text=f"{b.hours} h / {b.price}. {b.text}".strip()))
    log(db, user, "estimate", "order", o.id, f"{b.hours}h {b.price}")
    db.commit()
    return order_out(db, o, user)


class RateIn(BaseModel):
    rating: int


@app.post("/orders/{oid}/rate")
def rate(oid: int, b: RateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, CLIENT)
    o = get_order(db, user, oid)
    if o.status != "done" or not 1 <= b.rating <= 5:
        raise HTTPException(400, "Order must be done, rating 1..5")
    o.rating = b.rating
    log(db, user, "rate", "order", o.id, str(b.rating))
    db.commit()
    return order_out(db, o, user)


class CommentIn(BaseModel):
    text: str
    public: bool = True


@app.post("/orders/{oid}/comments")
def add_comment(oid: int, b: CommentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, OWNER, ADMIN, HEAD, EXECUTOR, CLIENT, STAFF)   # наблюдатель (6) только читает
    o = get_order(db, user, oid)
    public = True if user.role in (CLIENT, STAFF) else b.public
    c = Comment(order_id=o.id, user_id=user.id, text=b.text, public=public)
    db.add(c)
    log(db, user, "comment", "order", o.id, "public" if public else "internal")
    db.commit()
    return comment_out(db, c)


async def save_stream(file: UploadFile, folder: str, ext: str):
    """Потоково сохраняет загрузку на диск с ограничением размера. → (имя_на_диске, размер)"""
    name = uuid.uuid4().hex + ("." + ext if ext else "")
    path = os.path.join(folder, name)
    size, limit = 0, MAX_UPLOAD_MB * 1024 * 1024
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                os.remove(path)
                raise HTTPException(413, "File too large")
            f.write(chunk)
    return name, size


def file_response(path: str, original: str, kind: str, mime: str):
    """Фото/видео/аудио показываются в браузере, остальное — скачивается (защита от исполнения чужого кода)."""
    r = FileResponse(path, media_type=mime, filename=original,
                     content_disposition_type="inline" if kind in INLINE_KINDS or mime == "application/pdf" else "attachment")
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


def guess_mime(filename: str) -> str:
    import mimetypes
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


@app.post("/orders/{oid}/media")
async def upload(oid: int, request: Request, file: UploadFile = File(...),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Upload media. X-Client-Upload-ID provides retry-safe idempotency with SHA-256 verification."""
    need(user, OWNER, ADMIN, HEAD, EXECUTOR, CLIENT, STAFF)
    o = get_order(db, user, oid)
    upload_key = (request.headers.get("x-client-upload-id") or "").strip()
    if upload_key and (len(upload_key) > 80 or not all(ch.isalnum() or ch in "-_." for ch in upload_key)):
        raise HTTPException(400, "Invalid X-Client-Upload-ID")
    if upload_key:
        receipt = db.scalar(select(MediaUploadReceipt).where(MediaUploadReceipt.upload_key == upload_key))
        if receipt:
            if receipt.user_id != user.id or receipt.order_id != o.id:
                raise HTTPException(409, "Upload ID belongs to another account or order")
            expected_hash = (request.headers.get("x-content-sha256") or "").strip().lower()
            expected_size = request.headers.get("x-content-size")
            if expected_hash != receipt.sha256 or expected_size != str(receipt.size):
                raise HTTPException(409, "Upload ID reused with different content metadata")
            # Verify replay bytes too; do not trust client-supplied digest/size alone.
            replay_digest = hashlib.sha256()
            replay_size = 0
            while chunk := await file.read(1024 * 1024):
                replay_size += len(chunk)
                if replay_size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, "File too large")
                replay_digest.update(chunk)
            if replay_size != receipt.size or replay_digest.hexdigest() != receipt.sha256:
                raise HTTPException(409, "Upload ID reused with different content")
            media = db.get(Media, receipt.media_id)
            if not media:
                raise HTTPException(409, "Upload receipt points to missing media")
            return dict(id=media.id, original=media.original, mime=media.mime, size=media.size,
                        kind=EXT_KIND.get(os.path.splitext(media.filename)[1].lstrip("."), "doc"))
    expected_hash = (request.headers.get("x-content-sha256") or "").strip().lower()
    expected_size = request.headers.get("x-content-size")
    if upload_key and (len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash)
                       or expected_size is None or not expected_size.isdigit()):
        raise HTTPException(400, "Idempotent uploads require X-Content-SHA256 and X-Content-Size")
    ext, kind = check_upload(file.filename, file.content_type)
    name, size = await save_stream(file, MEDIA_DIR, ext)
    path = os.path.join(MEDIA_DIR, name)
    digest = hashlib.sha256()
    with open(path, "rb") as saved:
        for chunk in iter(lambda: saved.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if upload_key and (actual_hash != expected_hash or size != int(expected_size)):
        os.remove(path)
        raise HTTPException(400, "Uploaded content hash or size mismatch")
    m = Media(order_id=o.id, user_id=user.id, filename=name, original=(file.filename or name)[:200],
              mime=guess_mime(name), size=size)
    db.add(m)
    db.flush()
    if upload_key:
        db.add(MediaUploadReceipt(upload_key=upload_key, user_id=user.id, order_id=o.id,
                                  media_id=m.id, sha256=actual_hash, size=size))
    log(db, user, "upload_media", "order", o.id, m.original)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if os.path.exists(path):
            os.remove(path)
        raise HTTPException(409, "Upload receipt conflict; retry with the same upload ID")
    return dict(id=m.id, original=m.original, mime=m.mime, size=size, kind=kind)

@app.get("/media/{mid}")
def get_media(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Media, mid)
    if not m:
        raise HTTPException(404)
    get_order(db, user, m.order_id)   # проверка права видеть заказ
    return file_response(os.path.join(MEDIA_DIR, m.filename), m.original, EXT_KIND.get(os.path.splitext(m.filename)[1].lstrip("."), "doc"), m.mime)


# ---------- Журнал ----------
def audit_out(db: Session, a: Audit):
    u = db.get(User, a.actor_id) if a.actor_id else None
    return dict(id=a.id, actor=(u.full_name or u.username) if u else "system", action=a.action,
                target_type=a.target_type, target_id=a.target_id, details=a.details,
                created_at=a.created_at.isoformat())


@app.get("/audit")
def audit(limit: int = 200, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    return [audit_out(db, a) for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(min(limit, 1000)))]


# ---------- Модули расширений ----------
# Каждый модуль определяет router (APIRouter) и свои таблицы; ВАЖНО: импортировать надо именно server,
# а не модуль напрямую (модули берут общие функции из server).
EXT_MODULES = ["people", "appearance", "finance", "tracking", "warehouse", "storage", "analytics", "reports", "notifications"]
for _name in EXT_MODULES:
    app.include_router(importlib.import_module(_name).router)


# ---------- Веб-версия (браузер) ----------
# Папка web/ (рядом с server/) раздаётся по адресу /app/ — тот же интерфейс, что в Android-приложении, но в браузере.
WEB_DIR = os.getenv("WEB_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")


@app.get("/locales")
def list_locales():
    """Список доступных языков (по файлам web/locales/*.json) — новый язык появляется автоматически."""
    import json
    out = []
    folder = os.path.join(WEB_DIR, "locales")
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.endswith(".json"):
                with open(os.path.join(folder, fn), encoding="utf-8") as f:
                    out.append({"code": fn[:-5], "name": json.load(f).get("_name", fn[:-5])})
    return out


if os.path.isdir(WEB_DIR):
    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/app/")

    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")
