"""
Склад: материалы (расходуются) и оборудование (возвращается). Остатки хранятся в двух местах:
главный склад (holder_user_id = NULL) и «на руках» у сотрудника — поэтому всегда видно, у кого какая деталь,
где он находится (последнее положение) и как с ним связаться.

Движения:
  receipt   поступление на склад                       (администратор/начальник)
  take      склад → сотрудник                          (исполнитель себе; администратор/начальник — любому)
  transfer  сотрудник → сотрудник                      (исполнитель от себя; администратор — любые)
  return    сотрудник → склад
  consume   списание материала на заказ → расход «материал» в себестоимости заказа (только для материалов)
  writeoff  списание (брак, потеря)                    (администратор/начальник)
"""
import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, EXECUTOR, HEAD, OBSERVER, STAFF_ROLES, Base, Order, User, current_user, get_db, get_order, log,
                    need, now)
from storage import StoredFile, file_out, store_upload

router = APIRouter()
MANAGERS = (*ADMINS, HEAD)


class Item(Base):
    __tablename__ = "wh_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), default="")
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(10), default="material")      # material | equipment
    unit: Mapped[str] = mapped_column(String(12), default="pcs")
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    min_qty: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class Stock(Base):
    __tablename__ = "wh_stock"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("wh_items.id"), index=True)
    holder_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)   # NULL = главный склад
    qty: Mapped[float] = mapped_column(Float, default=0.0)


class Move(Base):
    __tablename__ = "wh_moves"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("wh_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    qty: Mapped[float] = mapped_column(Float)
    from_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now, index=True)


def _stock(db: Session, item_id: int, holder: Optional[int], create=False) -> Optional[Stock]:
    q = select(Stock).where(Stock.item_id == item_id, Stock.holder_user_id.is_(None) if holder is None else Stock.holder_user_id == holder)
    s = db.scalar(q)
    if s is None and create:
        s = Stock(item_id=item_id, holder_user_id=holder, qty=0.0)
        db.add(s)
        db.flush()
    return s


def qty_of(db: Session, item_id: int, holder: Optional[int]) -> float:
    s = _stock(db, item_id, holder)
    return s.qty if s else 0.0


def holders_of(db: Session, item_id: int):
    """У кого сейчас эта позиция: сотрудник, количество, контакты и последнее известное положение."""
    out = []
    for s in db.scalars(select(Stock).where(Stock.item_id == item_id, Stock.holder_user_id.is_not(None), Stock.qty > 0)):
        u = db.get(User, s.holder_user_id)
        if not u:
            continue
        from people import is_online
        out.append(dict(user_id=u.id, name=u.full_name or u.username, phone=u.phone, company=u.company_name, qty=s.qty,
                        lat=u.last_lat, lon=u.last_lon, last_seen=u.last_seen.isoformat() if u.last_seen else None, online=is_online(u)))
    return out


def item_out(db: Session, it: Item, viewer: User):
    in_wh = qty_of(db, it.id, None)
    with_staff = float(db.scalar(select(func.coalesce(func.sum(Stock.qty), 0.0)).where(Stock.item_id == it.id, Stock.holder_user_id.is_not(None))) or 0)
    thumb = db.scalar(select(StoredFile.id).where(StoredFile.source == "warehouse", StoredFile.ref_id == it.id, StoredFile.kind == "image").order_by(StoredFile.id).limit(1))
    return dict(id=it.id, sku=it.sku, name=it.name, kind=it.kind, unit=it.unit, unit_cost=it.unit_cost, min_qty=it.min_qty,
                description=it.description, active=it.active, in_warehouse=in_wh, with_staff=with_staff,
                total=in_wh + with_staff, mine=qty_of(db, it.id, viewer.id), low=bool(it.min_qty and in_wh < it.min_qty), thumb=thumb)


class ItemIn(BaseModel):
    name: str
    sku: str = ""
    kind: str = "material"
    unit: str = "pcs"
    unit_cost: float = 0.0
    min_qty: float = 0.0
    description: str = ""


@router.get("/warehouse/items")
def items(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    stmt = select(Item).where(Item.active).order_by(Item.name)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Item.name.ilike(like) | Item.sku.ilike(like))
    return [item_out(db, it, user) for it in db.scalars(stmt)]


@router.post("/warehouse/items")
def create_item(b: ItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *MANAGERS)
    if not b.name.strip() or b.kind not in ("material", "equipment") or b.unit_cost < 0 or b.min_qty < 0:
        raise HTTPException(400, "Bad item")
    it = Item(name=b.name.strip()[:160], sku=b.sku.strip()[:40], kind=b.kind, unit=b.unit.strip()[:12] or "pcs",
              unit_cost=b.unit_cost, min_qty=b.min_qty, description=b.description[:5000], created_by=user.id)
    db.add(it)
    db.flush()
    log(db, user, "wh_item_create", "item", it.id, it.name)
    db.commit()
    return item_out(db, it, user)


@router.patch("/warehouse/items/{iid}")
def edit_item(iid: int, b: ItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *MANAGERS)
    it = db.get(Item, iid)
    if not it or b.kind not in ("material", "equipment"):
        raise HTTPException(404)
    it.name, it.sku, it.kind, it.unit = b.name.strip()[:160], b.sku.strip()[:40], b.kind, b.unit.strip()[:12] or "pcs"
    it.unit_cost, it.min_qty, it.description = max(0.0, b.unit_cost), max(0.0, b.min_qty), b.description[:5000]
    log(db, user, "wh_item_edit", "item", it.id, it.name)
    db.commit()
    return item_out(db, it, user)


@router.get("/warehouse/items/{iid}")
def item_detail(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    it = db.get(Item, iid)
    if not it:
        raise HTTPException(404)
    files = [file_out(f, db) for f in db.scalars(select(StoredFile).where(StoredFile.source == "warehouse", StoredFile.ref_id == iid).order_by(StoredFile.id))]
    moves = db.scalars(select(Move).where(Move.item_id == iid).order_by(Move.id.desc()).limit(30)).all()
    return dict(item=item_out(db, it, user), holders=holders_of(db, iid), files=files, moves=[move_out(db, m) for m in moves])


@router.post("/warehouse/items/{iid}/files")
async def item_file(iid: int, file: UploadFile = File(...), description: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Фото/видео/документ к позиции склада (с описанием)."""
    need(user, *MANAGERS, EXECUTOR)
    if not db.get(Item, iid):
        raise HTTPException(404)
    f = await store_upload(db, file, user, "warehouse", iid, description)
    log(db, user, "wh_item_file", "item", iid, f.original)
    db.commit()
    return file_out(f, db)


@router.get("/warehouse/mine")
def my_items(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    out = []
    for s in db.scalars(select(Stock).where(Stock.holder_user_id == user.id, Stock.qty > 0)):
        it = db.get(Item, s.item_id)
        if it:
            out.append(dict(item_id=it.id, name=it.name, kind=it.kind, unit=it.unit, qty=s.qty))
    return out


# ───────────── движения ─────────────
class MoveIn(BaseModel):
    item_id: int
    kind: str
    qty: float
    from_user_id: Optional[int] = None
    to_user_id: Optional[int] = None
    order_id: Optional[int] = None
    unit_cost: Optional[float] = None     # для receipt: закупочная цена (пересчитывается средняя)
    note: str = ""


def move_out(db: Session, m: Move):
    def nm(uid):
        u = db.get(User, uid) if uid else None
        return (u.full_name or u.username) if u else None
    it = db.get(Item, m.item_id)
    return dict(id=m.id, item_id=m.item_id, item=it.name if it else "?", unit=it.unit if it else "", kind=m.kind, qty=m.qty,
                from_user_id=m.from_user_id, from_name=nm(m.from_user_id) or ("Warehouse" if m.kind in ("take", "writeoff") else None),
                to_user_id=m.to_user_id, to_name=nm(m.to_user_id) or ("Warehouse" if m.kind in ("receipt", "return") else None),
                order_id=m.order_id, unit_cost=m.unit_cost, note=m.note, by=nm(m.created_by), created_at=m.created_at.isoformat())


def _staff_user(db: Session, uid: Optional[int]) -> User:
    u = db.get(User, uid) if uid else None
    if not u or u.role not in STAFF_ROLES or not u.is_active:
        raise HTTPException(400, "Employee not found")
    return u


@router.post("/warehouse/moves")
def make_move(b: MoveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from finance import Expense, r2
    need(user, *MANAGERS, EXECUTOR)
    it = db.get(Item, b.item_id)
    if not it or not it.active or b.qty <= 0:
        raise HTTPException(400, "Bad item or quantity")
    mgr = user.role in MANAGERS
    src: Optional[int] = "wh"       # "wh" — склад; число — id сотрудника; None — вне склада (приход)
    dst: Optional[int] = "wh"
    k = b.kind
    if k == "receipt":
        if not mgr:
            raise HTTPException(403, "Forbidden")
        src, dst = None, "wh"
    elif k == "take":
        to = b.to_user_id if (mgr and b.to_user_id) else user.id
        dst = _staff_user(db, to).id
        if not mgr and to != user.id:
            raise HTTPException(403, "Forbidden")
    elif k == "transfer":
        frm = b.from_user_id if (mgr and b.from_user_id) else user.id
        if not mgr and frm != user.id:
            raise HTTPException(403, "Forbidden")
        src, dst = _staff_user(db, frm).id, _staff_user(db, b.to_user_id).id
        if src == dst:
            raise HTTPException(400, "Choose another employee")
    elif k == "return":
        frm = b.from_user_id if (mgr and b.from_user_id) else user.id
        if not mgr and frm != user.id:
            raise HTTPException(403, "Forbidden")
        src, dst = _staff_user(db, frm).id, "wh"
    elif k == "consume":
        if it.kind != "material":
            raise HTTPException(400, "Equipment cannot be consumed — return it to the warehouse")
        frm = b.from_user_id if (mgr and b.from_user_id) else user.id
        if not mgr and frm != user.id:
            raise HTTPException(403, "Forbidden")
        if not b.order_id:
            raise HTTPException(400, "Order is required")
        src, dst = _staff_user(db, frm).id, None
    elif k == "writeoff":
        if not mgr:
            raise HTTPException(403, "Forbidden")
        src, dst = (_staff_user(db, b.from_user_id).id if b.from_user_id else "wh"), None
    else:
        raise HTTPException(400, "Bad kind")
    # проверка остатка и перенос
    if src is not None:
        holder = None if src == "wh" else src
        s = _stock(db, it.id, holder)
        if not s or s.qty + 1e-9 < b.qty:
            raise HTTPException(400, f"Not enough stock (available {s.qty if s else 0})")
        s.qty = round(s.qty - b.qty, 6)
    if dst is not None:
        d = _stock(db, it.id, None if dst == "wh" else dst, create=True)
        d.qty = round(d.qty + b.qty, 6)
    if k == "receipt" and b.unit_cost is not None and b.unit_cost >= 0:   # средневзвешенная цена
        total_before = float(db.scalar(select(func.coalesce(func.sum(Stock.qty), 0.0)).where(Stock.item_id == it.id)) or 0) - b.qty
        it.unit_cost = round(((it.unit_cost * max(0.0, total_before)) + b.unit_cost * b.qty) / (max(0.0, total_before) + b.qty), 4)
    if k == "consume":
        o = get_order(db, user, b.order_id)
        if o.settled_at:
            raise HTTPException(400, "Order is already settled")
        db.add(Expense(order_id=o.id, kind="material", description=it.name, qty=b.qty, unit_cost=it.unit_cost,
                       amount=r2(b.qty * it.unit_cost), item_id=it.id, auto=True, created_by=user.id))
    m = Move(item_id=it.id, kind=k, qty=b.qty, from_user_id=src if isinstance(src, int) else None,
             to_user_id=dst if isinstance(dst, int) else None, order_id=b.order_id, unit_cost=it.unit_cost, note=b.note[:500], created_by=user.id)
    db.add(m)
    db.flush()
    log(db, user, "wh_" + k, "item", it.id, f"{b.qty} {it.unit}" + (f" order={b.order_id}" if b.order_id else ""))
    db.commit()
    return move_out(db, m)


@router.get("/warehouse/moves")
def moves(item_id: Optional[int] = None, user_id: Optional[int] = None, kind: str = "", frm: str = "", to: str = "", limit: int = 300,
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Складской отчёт — движение материалов и оборудования. Исполнитель видит только движения, где участвовал сам."""
    need(user, *STAFF_ROLES)
    q = select(Move).order_by(Move.id.desc()).limit(max(1, min(limit, 2000)))
    if item_id:
        q = q.where(Move.item_id == item_id)
    if kind:
        q = q.where(Move.kind == kind)
    if user.role == EXECUTOR:
        q = q.where((Move.from_user_id == user.id) | (Move.to_user_id == user.id) | (Move.created_by == user.id))
    elif user_id:
        q = q.where((Move.from_user_id == user_id) | (Move.to_user_id == user_id))
    try:
        if frm:
            q = q.where(Move.created_at >= dt.datetime.strptime(frm[:10], "%Y-%m-%d"))
        if to:
            q = q.where(Move.created_at < dt.datetime.strptime(to[:10], "%Y-%m-%d") + dt.timedelta(days=1))
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    return [move_out(db, m) for m in db.scalars(q)]
