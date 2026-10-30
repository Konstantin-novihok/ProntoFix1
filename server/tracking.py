"""
Карта заказов, маршруты, километры и трекинг исполнителей.

  Оценка пути        по прямой × коэффициент дорожной сети (настройка road_factor). Если для пары точек уже есть
                     РЕАЛЬНЫЙ замер (из трекинга прошлых поездок) — берётся он (DistanceCache). Так оценки со временем уточняются.
  Маршрут            порядок заездов подбирается автоматически (ближайший сосед + 2-opt), считаются километры и стоимость транспорта.
  Трекинг            исполнитель включает запись положения; точки сохраняются, по ним считается фактический путь.
  «Прибыл»           фиксирует фактическое положение объекта (GeoFix → координаты заказа уточняются), реальный километраж
                     этапа (в кэш для будущих расчётов) и добавляет расход «транспорт» в себестоимость заказа.
"""
import datetime as dt
import json
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from server import (ADMINS, EXECUTOR, HEAD, STAFF_ROLES, Base, Order, User, current_user, get_db, get_setting, log, need,
                    now, visible_orders)

router = APIRouter()


class TrackingPreference(Base):
    __tablename__ = "tracking_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TrackingPreferenceIn(BaseModel):
    enabled: bool


@router.get("/tracking/preferences")
def list_tracking_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    members = db.scalars(select(User).where(User.role.in_(STAFF_ROLES), User.is_active == True).order_by(User.full_name, User.username)).all()  # noqa: E712
    prefs = {p.user_id: p.enabled for p in db.scalars(select(TrackingPreference)).all()}
    return [dict(user_id=m.id, full_name=m.full_name or m.username, username=m.username,
                 role=m.role, enabled=prefs.get(m.id, True), last_seen=m.last_seen.isoformat() if m.last_seen else None,
                 last_lat=m.last_lat, last_lon=m.last_lon,
                 last_location_at=m.last_location_at.isoformat() if m.last_location_at else None) for m in members]


@router.put("/tracking/preferences/{uid}")
def set_tracking_preference(uid: int, b: TrackingPreferenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *ADMINS)
    target = db.get(User, uid)
    if not target or target.role not in STAFF_ROLES or not target.is_active:
        raise HTTPException(404, "Active staff member not found")
    pref = db.get(TrackingPreference, uid)
    if pref is None:
        pref = TrackingPreference(user_id=uid, enabled=b.enabled)
        db.add(pref)
    else:
        pref.enabled = b.enabled
    pref.updated_at, pref.updated_by = now(), user.id
    log(db, user, "tracking_preference", "user", uid, "enabled" if b.enabled else "disabled")
    db.commit()
    return dict(user_id=uid, enabled=pref.enabled, updated_at=pref.updated_at.isoformat())


class TrackPoint(Base):
    __tablename__ = "track_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    route_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime, index=True)


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="active")     # active | done
    start_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    start_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stops_json: Mapped[str] = mapped_column(Text, default="[]")
    planned_km: Mapped[float] = mapped_column(Float, default=0.0)
    actual_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


class DistanceCache(Base):   # реальные замеры расстояний между точками (для будущих расчётов)
    __tablename__ = "distance_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    km: Mapped[float] = mapped_column(Float)
    samples: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class GeoFix(Base):   # уточнение положения объекта по GPS исполнителя
    __tablename__ = "geo_fixes"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


# ───────────── география ─────────────
def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def cache_key(a, b) -> str:
    return f"{a['lat']:.4f},{a['lon']:.4f}>{b['lat']:.4f},{b['lon']:.4f}"


def leg_km(db: Session, a: dict, b: dict):
    """→ (км, источник 'measured' | 'estimate'). Реальный замер важнее оценки; путь считается одинаковым в обе стороны."""
    row = db.scalar(select(DistanceCache).where(DistanceCache.key.in_([cache_key(a, b), cache_key(b, a)])))
    if row:
        return round(row.km, 3), "measured"
    factor = float(get_setting(db, "road_factor") or 1.3)
    return round(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * factor, 3), "estimate"


def remember_leg(db: Session, a: dict, b: dict, km: float):
    """Запоминает фактический километраж между двумя точками (среднее по всем замерам)."""
    if km <= 0.01:
        return
    for k in (cache_key(a, b),):
        row = db.scalar(select(DistanceCache).where(DistanceCache.key == k))
        rev = db.scalar(select(DistanceCache).where(DistanceCache.key == cache_key(b, a)))
        row = row or rev
        if row:
            row.km = (row.km * row.samples + km) / (row.samples + 1)
            row.samples += 1
            row.updated_at = now()
        else:
            db.add(DistanceCache(key=k, km=km, samples=1))


def tracked_distance_km(points) -> float:
    """Фактический путь по трекингу. Шум GPS отфильтровывается: плохая точность, прыжки и дрожание на месте игнорируются."""
    total, prev = 0.0, None
    for p in points:
        if p.accuracy is not None and p.accuracy > 100:
            continue
        if prev is not None:
            d = haversine_km(prev.lat, prev.lon, p.lat, p.lon) * 1000
            dt_s = max(1.0, (p.ts - prev.ts).total_seconds())
            if d >= 5 and d / dt_s <= 60:           # >=5 м и не быстрее 216 км/ч
                total += d
        prev = p
    return round(total / 1000, 3)


def order_route(db: Session, start: Optional[dict], stops: List[dict], optimize: bool):
    """Порядок заездов: ближайший сосед + улучшение 2-opt. Расстояния — leg_km (кэш замеров или оценка)."""
    n = len(stops)
    order = list(range(n))
    if optimize and n > 1:
        def d(a, b):
            return leg_km(db, a, b)[0]
        cur, left, order = start or stops[0], set(range(n)), []
        while left:
            nxt = min(left, key=lambda i: d(cur, stops[i]))
            order.append(nxt)
            left.remove(nxt)
            cur = stops[nxt]
        def length(o):
            pts = ([start] if start else []) + [stops[i] for i in o]
            return sum(d(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        improved = n > 2
        while improved:
            improved = False
            for i in range(0, n - 1):
                for j in range(i + 1, n):
                    cand = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                    if length(cand) + 1e-9 < length(order):
                        order, improved = cand, True
    seq = ([start] if start else []) + [stops[i] for i in order]
    legs = []
    for i in range(len(seq) - 1):
        km, src = leg_km(db, seq[i], seq[i + 1])
        legs.append(dict(km=km, source=src))
    total = round(sum(l["km"] for l in legs), 3)
    return order, legs, total


class Pt(BaseModel):
    lat: float
    lon: float
    order_id: Optional[int] = None


class EstimateIn(BaseModel):
    start: Optional[Pt] = None
    stops: List[Pt]
    optimize: bool = True


def _check_coords(*pts):
    for p in pts:
        if p is not None and not (-90 <= p.lat <= 90 and -180 <= p.lon <= 180):
            raise HTTPException(400, "Bad coordinates")


@router.post("/routes/estimate")
def estimate(b: EstimateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, EXECUTOR, HEAD, *ADMINS)
    if not b.stops or len(b.stops) > 40:
        raise HTTPException(400, "1..40 stops")
    _check_coords(b.start, *b.stops)
    stops = [p.model_dump() for p in b.stops]
    start = b.start.model_dump() if b.start else None
    order, legs, total = order_route(db, start, stops, b.optimize)
    cpk = float(get_setting(db, "cost_per_km") or 0)
    return dict(order=order, legs=legs, total_km=total, cost_per_km=cpk, transport_cost=round(total * cpk, 2))


# ───────────── маршруты ─────────────
class RouteIn(BaseModel):
    order_ids: List[int]
    start: Optional[Pt] = None
    optimize: bool = True
    accept: bool = True        # сразу взять заказы в работу


def route_out(r: Route):
    return dict(id=r.id, user_id=r.user_id, status=r.status, planned_km=r.planned_km, actual_km=r.actual_km,
                start=({"lat": r.start_lat, "lon": r.start_lon} if r.start_lat is not None else None),
                stops=json.loads(r.stops_json), created_at=r.created_at.isoformat(),
                finished_at=r.finished_at.isoformat() if r.finished_at else None)


@router.post("/routes")
def create_route(b: RouteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Исполнитель выбирает заказы на карте → «взять в работу» → маршрут с километрами."""
    need(user, EXECUTOR, *ADMINS)
    if not b.order_ids or len(b.order_ids) > 40:
        raise HTTPException(400, "1..40 orders")
    _check_coords(b.start)
    if user.role == EXECUTOR and (user.verification or "verified") != "verified":
        raise HTTPException(403, "Your account is not verified yet")
    orders, skipped = [], []
    for oid in dict.fromkeys(b.order_ids):
        o = db.scalar(visible_orders(user).where(Order.id == oid))
        if not o or o.lat is None:
            skipped.append(oid)
            continue
        if user.role == EXECUTOR and o.executor_id not in (None, user.id):
            skipped.append(oid)
            continue
        orders.append(o)
    if not orders:
        raise HTTPException(400, "No suitable orders")
    start = b.start.model_dump() if b.start else None
    pts = [dict(lat=o.lat, lon=o.lon) for o in orders]
    order, legs, total = order_route(db, start, pts, b.optimize)
    stops = []
    for pos, i in enumerate(order):
        o = orders[i]
        if b.accept and user.role == EXECUTOR and o.status in ("new", "assigned"):
            o.executor_id, o.status = user.id, "accepted"
            log(db, user, "accept_order", "order", o.id, "via route")
        leg = legs[pos] if start is not None else (legs[pos - 1] if pos > 0 else dict(km=0.0, source="estimate"))
        stops.append(dict(order_id=o.id, title=o.title, address=o.address, lat=o.lat, lon=o.lon,
                          planned_leg_km=leg["km"], leg_source=leg["source"], actual_leg_km=None, arrived_at=None))
    r = Route(user_id=user.id, start_lat=start["lat"] if start else None, start_lon=start["lon"] if start else None,
              stops_json=json.dumps(stops, ensure_ascii=False), planned_km=total)
    db.add(r)
    db.flush()
    log(db, user, "create_route", "route", r.id, f"{len(stops)} stops, {total} km")
    db.commit()
    return dict(route_out(r), skipped=skipped)


@router.get("/routes")
def list_routes(user_id: Optional[int] = None, status: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, EXECUTOR, HEAD, *ADMINS)
    q = select(Route).order_by(Route.id.desc()).limit(300)
    if user.role in ADMINS:
        if user_id:
            q = q.where(Route.user_id == user_id)
    else:
        q = q.where(Route.user_id == user.id)
    if status:
        q = q.where(Route.status == status)
    out = []
    for r in db.scalars(q):
        d = route_out(r)
        u = db.get(User, r.user_id)
        d["user_name"] = (u.full_name or u.username) if u else "?"
        out.append(d)
    return out


def _my_route(db: Session, user: User, rid: int) -> Route:
    r = db.get(Route, rid)
    if not r or (r.user_id != user.id and user.role not in ADMINS):
        raise HTTPException(404, "Route not found")
    return r


@router.get("/routes/{rid}")
def get_route(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, EXECUTOR, HEAD, *ADMINS)
    return route_out(_my_route(db, user, rid))


class ArriveIn(BaseModel):
    order_id: int
    # GPS is optional: an employee may report arrival even when tracking is disabled
    # or Android location permission/network is unavailable.
    lat: Optional[float] = None
    lon: Optional[float] = None
    accuracy: Optional[float] = None

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be provided together")
        if self.lat is not None and not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError("Bad coordinates")
        return self


@router.post("/routes/{rid}/arrive")
def arrive(rid: int, b: ArriveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """«Прибыл на объект»: фиксируем фактические координаты, километраж этапа и расход на транспорт."""
    from finance import Expense, r2        # локальный импорт: finance загружается тем же сервером
    need(user, EXECUTOR, *ADMINS)
    r = _my_route(db, user, rid)
    if r.status != "active":
        raise HTTPException(400, "Route is finished")
    has_fix = b.lat is not None and b.lon is not None
    stops = json.loads(r.stops_json)
    idx = next((i for i, s in enumerate(stops) if s["order_id"] == b.order_id), None)
    if idx is None:
        raise HTTPException(404, "Order is not in this route")
    if stops[idx]["arrived_at"]:
        raise HTTPException(400, "Already arrived")
    t_now = now()
    # когда закончился предыдущий этап → точки трекинга между этим моментом и «сейчас»
    prev_times = [dt.datetime.fromisoformat(s["arrived_at"]) for s in stops if s["arrived_at"]]
    since = max(prev_times) if prev_times else r.created_at
    # Do not use historical GPS traces for mileage once organization tracking is disabled.
    pref = db.get(TrackingPreference, r.user_id)
    tracking_allowed = pref is None or pref.enabled
    pts = (db.scalars(select(TrackPoint).where(TrackPoint.user_id == r.user_id, TrackPoint.ts >= since, TrackPoint.ts <= t_now)
                      .order_by(TrackPoint.ts)).all() if tracking_allowed else [])
    tracked = tracked_distance_km(pts) if len(pts) >= 2 else 0.0
    planned = stops[idx]["planned_leg_km"]
    leg, source = (tracked, "tracked") if tracked > 0.05 else (planned, stops[idx]["leg_source"])
    stop_update = dict(actual_leg_km=round(leg, 3), actual_source=source, arrived_at=t_now.isoformat())
    if has_fix:
        stop_update["fix"] = dict(lat=b.lat, lon=b.lon, accuracy=b.accuracy)
    stops[idx].update(stop_update)
    # запомнить реальный замер между предыдущей и этой точкой
    prev_pt = ({"lat": stops[idx - 1]["lat"], "lon": stops[idx - 1]["lon"]} if idx > 0
               else ({"lat": r.start_lat, "lon": r.start_lon} if r.start_lat is not None else None))
    if source == "tracked" and prev_pt:
        remember_leg(db, prev_pt, {"lat": stops[idx]["lat"], "lon": stops[idx]["lon"]}, leg)
    # заказ: прибытие, уточнение координат, километры, расход на транспорт
    o = db.get(Order, b.order_id)
    if o:
        o.arrived_at = t_now
        # Save GPS-derived data only when the client explicitly supplied a fix.
        if has_fix:
            db.add(GeoFix(order_id=o.id, user_id=user.id, lat=b.lat, lon=b.lon, accuracy=b.accuracy))
            if b.accuracy is None or b.accuracy <= 50:
                o.lat, o.lon, o.geo_verified = b.lat, b.lon, True
        o.distance_km = r2((o.distance_km or 0) + leg)
        cpk = float(get_setting(db, "cost_per_km") or 0)
        if not o.settled_at:
            e = db.scalar(select(Expense).where(Expense.order_id == o.id, Expense.kind == "transport", Expense.auto == True))  # noqa: E712
            if e is None:
                e = Expense(order_id=o.id, kind="transport", auto=True, created_by=user.id)
                db.add(e)
            e.qty, e.unit_cost = o.distance_km, cpk
            e.amount = r2(o.distance_km * cpk)
            e.description = f"Transport {o.distance_km} km"
    r.stops_json = json.dumps(stops, ensure_ascii=False)
    log(db, user, "arrive", "route", r.id, f"order={b.order_id} leg={round(leg, 2)}km ({source})")
    db.commit()
    return route_out(r)


@router.post("/routes/{rid}/finish")
def finish_route(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, EXECUTOR, *ADMINS)
    r = _my_route(db, user, rid)
    if r.status == "done":
        return route_out(r)
    stops = json.loads(r.stops_json)
    r.actual_km = round(sum(s["actual_leg_km"] or 0 for s in stops), 3)
    r.status, r.finished_at = "done", now()
    log(db, user, "finish_route", "route", r.id, f"{r.actual_km} km")
    db.commit()
    return route_out(r)


# ───────────── трекинг ─────────────
class PointIn(BaseModel):
    lat: float
    lon: float
    accuracy: Optional[float] = None
    speed: Optional[float] = None
    ts: Optional[str] = None       # ISO UTC; если нет — время сервера


class PointsIn(BaseModel):
    points: List[PointIn]
    route_id: Optional[int] = None


@router.post("/tracking/points")
def add_points(b: PointsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    pref = db.get(TrackingPreference, user.id)
    if pref is not None and not pref.enabled:
        raise HTTPException(403, "Location tracking is disabled by organization policy")
    if not b.points or len(b.points) > 500:
        raise HTTPException(400, "1..500 points")
    last = None
    for p in b.points:
        _check_coords(Pt(lat=p.lat, lon=p.lon))
        try:
            ts = dt.datetime.fromisoformat(p.ts.replace("Z", "+00:00")).astimezone(dt.timezone.utc).replace(tzinfo=None) if p.ts else now()
        except ValueError:
            ts = now()
        if ts > now() + dt.timedelta(minutes=5):
            ts = now()
        db.add(TrackPoint(user_id=user.id, route_id=b.route_id, lat=p.lat, lon=p.lon, accuracy=p.accuracy, speed=p.speed, ts=ts))
        if last is None or ts >= last[2]:
            last = (p.lat, p.lon, ts)
    # Location telemetry must not overwrite general account activity (last_seen).
    user.last_lat, user.last_lon = last[0], last[1]
    user.last_location_at = last[2]
    db.commit()
    return {"saved": len(b.points)}


@router.get("/tracking/points")
def get_points(user_id: Optional[int] = None, frm: Optional[str] = None, to: Optional[str] = None, limit: int = 2000,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    need(user, *STAFF_ROLES)
    uid = user_id if (user_id and user.role in ADMINS) else user.id
    q = select(TrackPoint).where(TrackPoint.user_id == uid).order_by(TrackPoint.ts)
    try:
        if frm:
            q = q.where(TrackPoint.ts >= dt.datetime.strptime(frm[:10], "%Y-%m-%d"))
        if to:
            q = q.where(TrackPoint.ts < dt.datetime.strptime(to[:10], "%Y-%m-%d") + dt.timedelta(days=1))
    except ValueError:
        raise HTTPException(400, "Dates must be YYYY-MM-DD")
    pts = db.scalars(q.limit(min(limit, 5000))).all()
    return dict(distance_km=tracked_distance_km(pts), points=[dict(lat=p.lat, lon=p.lon, ts=p.ts.isoformat(), accuracy=p.accuracy) for p in pts])


@router.get("/map/orders")
def map_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Заказы с координатами для карты исполнителя (только то, что ему разрешено видеть) — без финансовых данных."""
    need(user, EXECUTOR, HEAD, *ADMINS, 6)
    q = visible_orders(user).where(Order.lat.is_not(None), Order.status.notin_(["done", "cancelled"])).order_by(Order.id.desc()).limit(500)
    return [dict(id=o.id, title=o.title, address=o.address, status=o.status, lat=o.lat, lon=o.lon, executor_id=o.executor_id,
                 service_type=o.service_type, geo_verified=bool(o.geo_verified)) for o in db.scalars(q)]
