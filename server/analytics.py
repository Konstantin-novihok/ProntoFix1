"""
Аналитика: единый набор данных по всем заказам для графиков (строится на стороне приложения — администратор сам выбирает
вид диаграммы, показатели, цвета и накладывает несколько графиков). Сервер отдаёт готовые «плоские» строки с вычисленными
деньгами и справочник заказчиков с остатком предоплаты.
"""
import datetime as dt
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, CLIENT, HEAD, OBSERVER, Base, Department, Order, User, current_user, get_db, need, now, visible_orders)
from finance import OrderPay, Transaction, balance_of, money, r2

router = APIRouter()
NONE_LABEL = "—"


class ChartPreset(Base):
    __tablename__ = "chart_presets"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    config: Mapped[str] = mapped_column(Text)
    created_at = mapped_column(DateTime, default=now)


def parse_day(s: Optional[str], end=False):
    if not s:
        return None
    try:
        d = dt.datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    return d + dt.timedelta(days=1) if end else d


def order_rows(db: Session, user: User, frm: Optional[str] = None, to: Optional[str] = None, extra_where=None):
    """Строки «заказ + все измерения» с пересчитанными деньгами. Данные загружаются пачками (без запроса на каждый заказ)."""
    from finance import Expense
    q = visible_orders(user).order_by(Order.id)
    a, b = parse_day(frm), parse_day(to, True)
    if a:
        q = q.where(Order.created_at >= a)
    if b:
        q = q.where(Order.created_at < b)
    if extra_where is not None:
        q = q.where(extra_where)
    orders = db.scalars(q).all()
    ids = [o.id for o in orders] or [-1]
    users = {u.id: u for u in db.scalars(select(User))}
    deps = {d.id: d.name for d in db.scalars(select(Department))}
    exp = {}
    for oid, kind, s in db.execute(select(Expense.order_id, Expense.kind, func.sum(Expense.amount)).where(Expense.order_id.in_(ids)).group_by(Expense.order_id, Expense.kind)):
        exp.setdefault(oid, {"material": 0.0, "transport": 0.0, "other": 0.0})[kind if kind in ("material", "transport") else "other"] += float(s or 0)
    paid = {oid: amt for oid, amt in db.execute(select(OrderPay.order_id, OrderPay.amount).where(OrderPay.order_id.in_(ids)))}
    rows = []
    for o in orders:
        cl, ex = users.get(o.client_id), users.get(o.executor_id)
        m = money(o, ex, exp.get(o.id, {"material": 0.0, "transport": 0.0, "other": 0.0}), paid.get(o.id))
        c = o.created_at
        iso = c.isocalendar()
        rows.append(dict(
            id=o.id, title=o.title, date=c.strftime("%Y-%m-%d"), month=c.strftime("%Y-%m"), week=f"{iso[0]}-W{iso[1]:02d}",
            weekday=c.weekday(), hour=c.hour, status=o.status, service_type=o.service_type or NONE_LABEL,
            department=deps.get(o.department_id, NONE_LABEL), address=o.address or "",
            client_name=(cl.full_name or cl.username) if cl else NONE_LABEL,
            client_company=(cl.company_name or cl.full_name or cl.username) if cl else NONE_LABEL,
            executor=(ex.full_name or ex.username) if ex else NONE_LABEL,
            executor_company=(ex.company_name or NONE_LABEL) if ex else NONE_LABEL,
            employment=(ex.employment or "internal") if ex else NONE_LABEL,
            hours=m["labor_hours"], km=m["km"], price=m["price"], materials=m["materials"], transport=m["transport"],
            other=m["other"], pay=m["pay"], cost=m["cost_price"], margin=m["margin"], rating=o.rating, settled=1 if o.settled_at else 0))
    return rows


@router.get("/analytics/dataset")
def dataset(frm: Optional[str] = None, to: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER, HEAD)
    out = dict(orders=order_rows(db, user, frm, to), clients=[], ledger=[])
    if user.role in (*ADMINS, OBSERVER):
        for c in db.scalars(select(User).where(User.role == CLIENT)):
            prepaid = float(db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(Transaction.client_id == c.id, Transaction.kind == "prepayment")) or 0)
            charged = float(db.scalar(select(func.coalesce(-func.sum(Transaction.amount), 0.0)).where(Transaction.client_id == c.id, Transaction.kind == "charge")) or 0)
            out["clients"].append(dict(company=c.company_name or c.full_name or c.username, name=c.full_name or c.username,
                                       balance=balance_of(db, c.id), prepaid_total=r2(prepaid), charged_total=r2(charged)))
        a, b = parse_day(frm), parse_day(to, True)
        q = select(Transaction).order_by(Transaction.id)
        if a:
            q = q.where(Transaction.created_at >= a)
        if b:
            q = q.where(Transaction.created_at < b)
        names = {c.id: (c.company_name or c.full_name or c.username) for c in db.scalars(select(User).where(User.role == CLIENT))}
        out["ledger"] = [dict(date=t.created_at.strftime("%Y-%m-%d"), client_company=names.get(t.client_id, NONE_LABEL), kind=t.kind, amount=r2(t.amount))
                         for t in db.scalars(q.limit(20000))]
    return out


# ───────────── сохранённые настройки диаграмм ─────────────
class PresetIn(BaseModel):
    name: str
    config: dict


@router.get("/analytics/presets")
def presets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER, HEAD)
    return [dict(id=p.id, name=p.name, config=json.loads(p.config)) for p in db.scalars(select(ChartPreset).where(ChartPreset.owner_id == user.id).order_by(ChartPreset.name))]


@router.post("/analytics/presets")
def save_preset(b: PresetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER, HEAD)
    name = b.name.strip()[:60]
    if not name or len(json.dumps(b.config)) > 20000:
        raise HTTPException(400, "Bad preset")
    p = db.scalar(select(ChartPreset).where(ChartPreset.owner_id == user.id, ChartPreset.name == name))
    if p is None:
        p = ChartPreset(owner_id=user.id, name=name, config="")
        db.add(p)
    p.config = json.dumps(b.config, ensure_ascii=False)
    db.commit()
    return dict(id=p.id, name=p.name, config=b.config)


@router.delete("/analytics/presets/{pid}")
def delete_preset(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(ChartPreset, pid)
    if not p or p.owner_id != user.id:
        raise HTTPException(404)
    db.delete(p)
    db.commit()
    return {"ok": True}
