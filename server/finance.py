"""
Финансы.

  Предоплата заказчика    баланс = сумма проводок (Transaction): пополнение (+), списание за услугу (−), корректировка (±)
  Себестоимость заказа    расходы (материалы + транспорт + прочее) + оплата исполнителю
  Маржа                   цена услуги − себестоимость
  Оплата исполнителя      hourly   — часы × ставка            (штат, фиксированная ставка)
                          per_order — фиксированная сумма за заказ
                          percent  — % от прибыли заказа (цена − расходы)   (обычно подрядчики)
  Премии и штрафы         отдельные записи (PayAdjustment); итог сотрудника = начислено + премии − штрафы
"""
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, CLIENT, EXECUTOR, HEAD, OBSERVER, Base, Order, User, current_user, get_db, get_order,
                    get_setting, log, need, now, order_out)

router = APIRouter()


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(12))                  # prepayment | charge | adjust
    amount: Mapped[float] = mapped_column(Float)                   # со знаком: + пополнение, − списание
    note: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")


class Expense(Base):
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))                  # material | transport | other
    description: Mapped[str] = mapped_column(String(300), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # материал со склада
    auto: Mapped[bool] = mapped_column(Boolean, default=False)                # создан автоматически (маршрут/склад)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class OrderPay(Base):   # начисление исполнителю по закрытому (рассчитанному) заказу
    __tablename__ = "order_pay"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    basis: Mapped[str] = mapped_column(String(200), default="")
    currency: Mapped[str] = mapped_column(String(3), default="UAH")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class PayAdjustment(Base):   # премия / штраф
    __tablename__ = "pay_adjustments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))                   # bonus | fine
    amount: Mapped[float] = mapped_column(Float)                   # всегда > 0
    reason: Mapped[str] = mapped_column(String(300), default="")
    order_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    currency: Mapped[str] = mapped_column(String(3), default="UAH")


# ───────────── расчёты ─────────────
def r2(x: float) -> float:
    return round(float(x or 0.0), 2)


def balance_of(db: Session, client_id: int, currency: Optional[str] = None) -> float:
    code = currency_code(currency)
    return r2(db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(
        Transaction.client_id == client_id, func.coalesce(Transaction.currency, "UAH") == code)))


def currency_code(value: Optional[str], fallback: str = "UAH") -> str:
    code = (value or fallback or "UAH").strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise HTTPException(400, "Currency must be a three-letter ISO 4217 code")
    return code


def balances_by_currency(db: Session, client_id: int) -> dict:
    rows = db.execute(select(func.coalesce(Transaction.currency, "UAH"), func.sum(Transaction.amount))
                      .where(Transaction.client_id == client_id)
                      .group_by(func.coalesce(Transaction.currency, "UAH")))
    return {code: r2(amount) for code, amount in rows}


def expense_totals(db: Session, order_id: int) -> dict:
    t = {"material": 0.0, "transport": 0.0, "other": 0.0}
    for kind, s in db.execute(select(Expense.kind, func.sum(Expense.amount)).where(Expense.order_id == order_id).group_by(Expense.kind)):
        t[kind if kind in t else "other"] += float(s or 0)
    return t


def calc_pay(rate_type: str, rate_value: float, hours: float, price: float, expenses_total: float):
    """→ (сумма, пояснение). Чистая функция — одна и та же формула для заказа, зарплаты, графиков и Excel."""
    rate_type, rv = rate_type or "hourly", float(rate_value or 0)
    if rate_type == "per_order":
        return r2(rv), f"fixed {rv}/order"
    if rate_type == "percent":
        profit = max(0.0, float(price or 0) - expenses_total)
        return r2(profit * rv / 100.0), f"{rv}% of profit {r2(profit)}"
    return r2(float(hours or 0) * rv), f"{hours or 0} h x {rv}"


def money(o: Order, ex: Optional[User], totals: dict, settled_pay: Optional[float] = None) -> dict:
    """Финансовая сводка заказа из уже загруженных данных."""
    price = float(o.price or 0)
    exp_total = totals["material"] + totals["transport"] + totals["other"]
    if settled_pay is not None:
        pay = settled_pay
    elif ex is not None:
        pay = calc_pay(ex.rate_type, ex.rate_value, o.labor_hours, price, exp_total)[0]
    else:
        pay = 0.0
    cost = exp_total + pay
    margin = price - cost
    return dict(currency=o.currency or "UAH", price=r2(price), materials=r2(totals["material"]), transport=r2(totals["transport"]), other=r2(totals["other"]),
                expenses_total=r2(exp_total), pay=r2(pay), cost_price=r2(cost), margin=r2(margin),
                margin_pct=r2(margin / price * 100) if price else 0.0, labor_hours=o.labor_hours or 0.0,
                km=o.distance_km or 0.0, settled=bool(o.settled_at))


def order_finance(db: Session, o: Order) -> dict:
    ex = db.get(User, o.executor_id) if o.executor_id else None
    paid = db.scalar(select(OrderPay.amount).where(OrderPay.order_id == o.id))
    return money(o, ex, expense_totals(db, o.id), paid)


def can_manage(user: User, o: Order) -> bool:
    return user.role in ADMINS or user.role == HEAD


# ───────────── эндпоинты по заказу ─────────────
class FinIn(BaseModel):
    price: Optional[float] = None
    labor_hours: Optional[float] = None
    service_type: Optional[str] = None


@router.get("/orders/{oid}/finance")
def get_order_finance(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = get_order(db, user, oid)
    exps = [dict(id=e.id, kind=e.kind, description=e.description, qty=e.qty, unit_cost=e.unit_cost, amount=r2(e.amount), currency=e.currency or o.currency or "UAH", auto=e.auto)
            for e in db.scalars(select(Expense).where(Expense.order_id == oid).order_by(Expense.id))]
    full = order_finance(db, o)
    if user.role in ADMINS or user.role in (HEAD, OBSERVER):
        out = dict(full, expenses=exps)
        if o.client_id:
            out["client_balance"] = balance_of(db, o.client_id)
        return out
    if user.role == EXECUTOR:     # исполнитель видит свои расходы и свою оплату, но не цену и маржу
        return dict(expenses=exps, pay=full["pay"], labor_hours=full["labor_hours"], km=full["km"], settled=full["settled"])
    if user.role == CLIENT:       # заказчик видит только цену и факт расчёта
        return dict(price=full["price"], settled=full["settled"])
    raise HTTPException(403, "Forbidden")


@router.post("/orders/{oid}/finance")
def set_order_finance(oid: int, b: FinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = get_order(db, user, oid)
    if o.settled_at:
        raise HTTPException(400, "Order is already settled")
    manage = can_manage(user, o)
    if not manage and not (user.role == EXECUTOR and o.executor_id == user.id):
        raise HTTPException(403, "Forbidden")
    if b.price is not None:
        if not manage:
            raise HTTPException(403, "Only managers set the price")
        if b.price < 0:
            raise HTTPException(400, "Price must be >= 0")
        o.price = r2(b.price)
    if b.labor_hours is not None:
        if b.labor_hours < 0 or b.labor_hours > 1000:
            raise HTTPException(400, "Bad hours")
        o.labor_hours = b.labor_hours
    if b.service_type is not None:
        o.service_type = b.service_type.strip()[:80]
    log(db, user, "order_finance", "order", o.id, f"price={o.price} hours={o.labor_hours}")
    db.commit()
    return order_out(db, o, user)


class ExpenseIn(BaseModel):
    kind: str = "material"
    description: str = ""
    qty: float = 1.0
    unit_cost: float = 0.0


@router.post("/orders/{oid}/expenses")
def add_expense(oid: int, b: ExpenseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = get_order(db, user, oid)
    if o.settled_at:
        raise HTTPException(400, "Order is already settled")
    if not (can_manage(user, o) or (user.role == EXECUTOR and o.executor_id == user.id)):
        raise HTTPException(403, "Forbidden")
    if b.kind not in ("material", "transport", "other") or b.qty <= 0 or b.unit_cost < 0:
        raise HTTPException(400, "Bad expense")
    e = Expense(order_id=o.id, kind=b.kind, description=b.description[:300], qty=b.qty, unit_cost=b.unit_cost,
                amount=r2(b.qty * b.unit_cost), currency=cur, created_by=user.id)
    db.add(e)
    log(db, user, "add_expense", "order", o.id, f"{b.kind} {e.amount}")
    db.commit()
    return dict(id=e.id, amount=e.amount)


@router.delete("/orders/{oid}/expenses/{eid}")
def delete_expense(oid: int, eid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o = get_order(db, user, oid)
    e = db.get(Expense, eid)
    if not e or e.order_id != oid or o.settled_at or not can_manage(user, o):
        raise HTTPException(400, "Cannot delete this expense")
    db.delete(e)
    log(db, user, "delete_expense", "order", oid, str(eid))
    db.commit()
    return {"ok": True}


@router.post("/orders/{oid}/settle")
def settle(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Закрывающий расчёт: списывает цену услуги с предоплаты заказчика и начисляет оплату исполнителю."""
    o = get_order(db, user, oid)
    if not can_manage(user, o):
        raise HTTPException(403, "Forbidden")
    if o.settled_at:
        raise HTTPException(400, "Already settled")
    if o.status != "done":
        raise HTTPException(400, "Order must be done first")
    if o.price is None:
        raise HTTPException(400, "Set the price first")
    totals = expense_totals(db, o.id)
    ex = db.get(User, o.executor_id) if o.executor_id else None
    new_balance = None
    if o.client_id and o.price > 0:
        order_cur = currency_code(o.currency)
        bal = balance_of(db, o.client_id, order_cur)
        if not get_setting(db, "overdraft_allowed") and bal - o.price < 0:
            raise HTTPException(400, f"Insufficient prepayment: balance {bal}, price {o.price}")
        db.add(Transaction(client_id=o.client_id, order_id=o.id, kind="charge", amount=-r2(o.price), currency=order_cur,
                           note=f"Order #{o.id}", created_by=user.id))
        new_balance = r2(bal - o.price)
    pay = None
    if ex is not None:
        amount, basis = calc_pay(ex.rate_type, ex.rate_value, o.labor_hours, o.price, sum(totals.values()))
        db.add(OrderPay(order_id=o.id, user_id=ex.id, amount=amount, basis=basis, currency=currency_code(o.currency)))
        pay = amount
    o.settled_at = now()
    log(db, user, "settle", "order", o.id, f"price={o.price} pay={pay} balance={new_balance}")
    db.commit()
    return dict(order_finance(db, o), client_balance=new_balance)


# ───────────── предоплата ─────────────
class PrepayIn(BaseModel):
    client_id: int
    amount: float
    note: str = ""
    currency: Optional[str] = None


@router.post("/finance/prepayment")
def prepayment(b: PrepayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    c = db.get(User, b.client_id)
    if not c or c.role != CLIENT or b.amount <= 0:
        raise HTTPException(400, "Bad client or amount")
    cur = currency_code(b.currency, get_setting(db, "currency"))
    db.add(Transaction(client_id=c.id, kind="prepayment", amount=r2(b.amount), currency=cur, note=b.note[:300], created_by=user.id))
    log(db, user, "prepayment", "user", c.id, str(b.amount))
    db.commit()
    return {"currency": cur, "balance": balance_of(db, c.id, cur), "balances": balances_by_currency(db, c.id)}


class AdjustIn(BaseModel):
    client_id: int
    amount: float            # со знаком
    note: str = ""
    currency: Optional[str] = None


@router.post("/finance/adjust")
def adjust(b: AdjustIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    c = db.get(User, b.client_id)
    if not c or c.role != CLIENT or b.amount == 0 or not b.note.strip():
        raise HTTPException(400, "Client, non-zero amount and a note are required")
    cur = currency_code(b.currency, get_setting(db, "currency"))
    db.add(Transaction(client_id=c.id, kind="adjust", amount=r2(b.amount), currency=cur, note=b.note[:300], created_by=user.id))
    log(db, user, "finance_adjust", "user", c.id, f"{b.amount} {b.note}")
    db.commit()
    return {"currency": cur, "balance": balance_of(db, c.id, cur), "balances": balances_by_currency(db, c.id)}


def tx_out(t: Transaction):
    return dict(id=t.id, kind=t.kind, amount=r2(t.amount), currency=t.currency or "UAH", note=t.note, order_id=t.order_id, created_at=t.created_at.isoformat())


@router.get("/finance/clients")
def clients(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER)
    out = []
    for c in db.scalars(select(User).where(User.role == CLIENT).order_by(User.company_name, User.full_name)):
        prepaid = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0.0)).where(Transaction.client_id == c.id, Transaction.kind == "prepayment"))
        charged = db.scalar(select(func.coalesce(-func.sum(Transaction.amount), 0.0)).where(Transaction.client_id == c.id, Transaction.kind == "charge"))
        out.append(dict(id=c.id, name=c.full_name or c.username, company=c.company_name or "", balance=balance_of(db, c.id), balances=balances_by_currency(db, c.id),
                        prepaid_total=r2(prepaid), charged_total=r2(charged)))
    return out


@router.get("/finance/ledger")
def ledger(client_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER)
    rows = db.scalars(select(Transaction).where(Transaction.client_id == client_id).order_by(Transaction.id.desc()).limit(500))
    return dict(balance=balance_of(db, client_id), balances=balances_by_currency(db, client_id), items=[tx_out(t) for t in rows])


@router.get("/me/finance")
def my_finance(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Заказчик видит остаток своей предоплаты и историю списаний."""
    need(user, CLIENT)
    rows = db.scalars(select(Transaction).where(Transaction.client_id == user.id).order_by(Transaction.id.desc()).limit(200))
    return dict(balance=balance_of(db, user.id), balances=balances_by_currency(db, user.id), items=[tx_out(t) for t in rows])


# ───────────── зарплата, премии, штрафы ─────────────
def parse_range(frm: Optional[str], to: Optional[str]):
    def p(s, end=False):
        if not s:
            return None
        try:
            d = dt.datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Dates must be YYYY-MM-DD")
        return d + dt.timedelta(days=1) if end else d
    return p(frm), p(to, True)


def payroll_rows(db: Session, frm: Optional[str], to: Optional[str], only_user: Optional[int] = None):
    a, b = parse_range(frm, to)

    def in_range(col):
        conds = []
        if a:
            conds.append(col >= a)
        if b:
            conds.append(col < b)
        return conds
    rows = []
    q = select(User).where(User.role.in_([EXECUTOR, HEAD, 3, 7, 6, 1]))
    if only_user:
        q = q.where(User.id == only_user)
    for u in db.scalars(q.order_by(User.full_name)):
        pays = db.execute(select(func.count(), func.coalesce(func.sum(OrderPay.amount), 0.0)).where(OrderPay.user_id == u.id, *in_range(OrderPay.created_at))).one()
        def adj(kind):
            return float(db.scalar(select(func.coalesce(func.sum(PayAdjustment.amount), 0.0)).where(
                PayAdjustment.user_id == u.id, PayAdjustment.kind == kind, *in_range(PayAdjustment.created_at))) or 0)
        bonus, fine = adj("bonus"), adj("fine")
        if not (pays[0] or bonus or fine) and u.role != EXECUTOR:
            continue
        rows.append(dict(user_id=u.id, name=u.full_name or u.username, company=u.company_name or "", employment=u.employment or "internal",
                         role=u.role, rate_type=u.rate_type or "hourly", rate_value=u.rate_value or 0.0, orders=pays[0],
                         earned=r2(pays[1]), bonus=r2(bonus), fine=r2(fine), total=r2(pays[1] + bonus - fine)))
    return rows


@router.get("/payroll")
def payroll(frm: Optional[str] = None, to: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER)
    return payroll_rows(db, frm, to)


@router.get("/me/payroll")
def my_payroll(frm: Optional[str] = None, to: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Сотрудник видит собственные начисления, премии и штрафы."""
    need(user, EXECUTOR, HEAD, OBSERVER, *ADMINS)
    rows = payroll_rows(db, frm, to, only_user=user.id)
    adj = db.scalars(select(PayAdjustment).where(PayAdjustment.user_id == user.id).order_by(PayAdjustment.id.desc()).limit(100))
    return dict(summary=rows[0] if rows else None, adjustments=[adj_out(db, a) for a in adj])


class AdjIn(BaseModel):
    user_id: int
    kind: str
    amount: float
    reason: str = ""
    order_id: Optional[int] = None


def adj_out(db: Session, a: PayAdjustment):
    u = db.get(User, a.user_id)
    return dict(id=a.id, user_id=a.user_id, user_name=(u.full_name or u.username) if u else "?", kind=a.kind, amount=r2(a.amount),
                reason=a.reason, order_id=a.order_id, created_at=a.created_at.isoformat())


@router.post("/payroll/adjustments")
def add_adjustment(b: AdjIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, HEAD)
    t = db.get(User, b.user_id)
    if not t or b.kind not in ("bonus", "fine") or b.amount <= 0:
        raise HTTPException(400, "Bad user, kind or amount")
    if user.role == HEAD and t.department_id != user.department_id:
        raise HTTPException(403, "Not your department")
    a = PayAdjustment(user_id=t.id, kind=b.kind, amount=r2(b.amount), reason=b.reason[:300], order_id=b.order_id, created_by=user.id)
    db.add(a)
    db.flush()
    log(db, user, "pay_" + b.kind, "user", t.id, f"{b.amount} {b.reason}")
    db.commit()
    return adj_out(db, a)


@router.get("/payroll/adjustments")
def list_adjustments(user_id: Optional[int] = None, frm: Optional[str] = None, to: Optional[str] = None,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS, OBSERVER, HEAD)
    a, b = parse_range(frm, to)
    q = select(PayAdjustment).order_by(PayAdjustment.id.desc()).limit(500)
    if user_id:
        q = q.where(PayAdjustment.user_id == user_id)
    if a:
        q = q.where(PayAdjustment.created_at >= a)
    if b:
        q = q.where(PayAdjustment.created_at < b)
    return [adj_out(db, x) for x in db.scalars(q)]


@router.delete("/payroll/adjustments/{aid}")
def delete_adjustment(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    a = db.get(PayAdjustment, aid)
    if not a:
        raise HTTPException(404)
    db.delete(a)
    log(db, user, "pay_adjustment_delete", "user", a.user_id, str(aid))
    db.commit()
    return {"ok": True}
