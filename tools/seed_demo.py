"""
Демо-данные для проверки: сотрудники всех ролей, подрядчик, склад, чат, предоплата, ~40 заказов за 6 месяцев с расчётами.
Логины (пароль test1234; владелец — owner / указанный пароль): admin1 head1 exec1 exec2 ctr1 observer1 client1 client2 staff1.
Запуск:  python seed_demo.py http://127.0.0.1:8000 owner123      (можно запускать повторно — существующее пропускается)
Если задана переменная DATA_DIR (локальный запуск), даты заказов раскидываются по последним 6 месяцам.
"""
import os
import random
import sqlite3
import sys
import datetime as dt

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OWNER_PW = sys.argv[2] if len(sys.argv) > 2 else "owner123"
PW = "test1234"
random.seed(7)


def call(method, path, token=None, **kw):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.request(method, BASE + path, headers=h, timeout=30, **kw)


def login(u, p=PW):
    r = call("POST", "/auth/login", json={"username": u, "password": p})
    return r.json()["token"] if r.ok else None


owner = login("owner", OWNER_PW)
if not owner:
    sys.exit("Не удалось войти владельцем (owner)")
if login("client1"):
    print("Демо-данные уже созданы")
    sys.exit(0)

O = lambda m, p, **kw: call(m, p, owner, **kw)
O("PUT", "/settings", json={"values": {"company_name": "ProntoFix Service", "currency": "UAH", "cost_per_km": 8, "road_factor": 1.3}})
deps = {d["name"]: d["id"] for d in O("GET", "/departments").json()}
for name in ("Стиральные машины", "Холодильники", "Мелкий ремонт"):
    deps.setdefault(name, O("POST", "/departments", json={"name": name}).json().get("id"))
D1 = deps["Стиральные машины"]


def mk(**kw):
    r = O("POST", "/users", json={"password": PW, **kw})
    assert r.ok, (kw, r.text)
    return r.json()["id"]


admin_id = mk(username="admin1", role=7, full_name="Светлана Админ", phone="+380501110001")
head_id = mk(username="head1", role=2, full_name="Мария Начальник", phone="+380501110002", employee_no="H-001", department_id=D1)
O("PATCH", f"/departments/{D1}", json={"head_id": head_id})
ex1 = mk(username="exec1", role=3, full_name="Андрей Кузнецов", phone="+380501110003", employee_no="E-001", department_id=D1, company_name="ProntoFix Service", rate_type="hourly", rate_value=150)
ex2 = mk(username="exec2", role=3, full_name="Олег Мельник", phone="+380501110004", employee_no="E-002", department_id=D1, company_name="ProntoFix Service", rate_type="per_order", rate_value=400)
mk(username="observer1", role=6, full_name="Ирина Наблюдатель", phone="+380501110005")

# подрядчик: приглашение → регистрация → документы → проверка администратором
inv = O("POST", "/invites", json={"company_name": "ТОВ Майстер-Сервіс", "department_id": D1, "rate_value": 35}).json()
r = call("POST", "/auth/register", json={"username": "ctr1", "password": PW, "full_name": "Петро Підрядник", "phone": "+380501110006", "company_name": "ТОВ Майстер-Сервіс",
          "tax_id": "3456789012", "consent": True, "invite_code": inv["code"]}).json()
ctr_id, ctr_tok = r["user"]["id"], r["token"]
call("POST", "/me/documents", ctr_tok, files={"file": ("passport.jpg", b"\xff\xd8\xff\xe0demo", "image/jpeg")})
O("PATCH", f"/users/{ctr_id}/verify", json={"status": "verified"})

# заказчики (компании) и работник заказчика
def reg_client(username, full, company, lat, lon):
    r = call("POST", "/auth/register", json={"username": username, "password": PW, "full_name": full, "phone": "+3805011100" + str(random.randint(10, 99)), "company_name": company,
             "website": "https://example.com", "address": "Киев", "lat": lat, "lon": lon, "passport_number": "АВ " + str(random.randint(100000, 999999)), "passport_issued": "демо", "consent": True}).json()
    return r["user"]["id"], r["token"]
c1, c1t = reg_client("client1", "Иван Заказчик", "ООО «Тепло Дом»", 50.4501, 30.5234)
c2, c2t = reg_client("client2", "Наталья Иванова", "ФОП Иванова Н.", 50.4120, 30.6300)
call("POST", "/users", c1t, json={"username": "staff1", "password": PW, "full_name": "Анна Работник", "phone": "+380501110008"})
O("POST", "/finance/prepayment", json={"client_id": c1, "amount": 30000, "note": "договор №1"})
O("POST", "/finance/prepayment", json={"client_id": c2, "amount": 25000, "note": "аванс"})

# склад
items = {}
for name, kind, cost, minq in [("Насос сливной", "material", 450, 3), ("Термостат", "material", 320, 2), ("Ремень привода", "material", 120, 5), ("Мультиметр", "equipment", 900, 0), ("Дрель-шуруповёрт", "equipment", 2400, 0)]:
    i = O("POST", "/warehouse/items", json={"name": name, "kind": kind, "unit": "шт", "unit_cost": cost, "min_qty": minq, "sku": "SKU-" + str(len(items) + 1), "description": "Демо-позиция"}).json()["id"]
    items[name] = i
    O("POST", "/warehouse/moves", json={"item_id": i, "kind": "receipt", "qty": 10 if kind == "material" else 2, "unit_cost": cost, "note": "закупка"})
ex1t, ex2t, headt, adm = login("exec1"), login("exec2"), login("head1"), login("admin1")
call("POST", "/warehouse/moves", ex1t, json={"item_id": items["Насос сливной"], "kind": "take", "qty": 3})
call("POST", "/warehouse/moves", ex1t, json={"item_id": items["Мультиметр"], "kind": "take", "qty": 1})
call("POST", "/warehouse/moves", ex2t, json={"item_id": items["Термостат"], "kind": "take", "qty": 2})
call("POST", f"/warehouse/items/{items['Насос сливной']}/files", ex1t, files={"file": ("pump.jpg", b"\xff\xd8\xff\xe0demo", "image/jpeg")}, data={"description": "Сливной насос Askoll — вид сверху"})

# заказы с историей
SERV = ["Ремонт стиральных машин", "Ремонт холодильников", "Мелкий ремонт", "Диагностика", "Выезд мастера"]
EXEC = [(ex1, 1.0), (ex2, 1.0), (ctr_id, 0.7)]
orders = []
for n in range(40):
    cl, tok = random.choice([(c1, c1t), (c2, c2t)])
    lat, lon = 50.40 + random.random() * 0.12, 30.40 + random.random() * 0.25
    o = call("POST", "/orders", tok, json={"title": random.choice(["Не сливает воду", "Не включается", "Течёт кран", "Шумит при отжиме", "Не морозит", "Замена розетки", "Диагностика"]) + f" #{n + 1}",
             "description": "Демо-заказ", "address": f"Киев, ул. Демо {n + 1}", "lat": lat, "lon": lon, "service_type": random.choice(SERV), "department_id": D1}).json()
    orders.append(o["id"])
    ex, _ = random.choice(EXEC)
    O("POST", f"/orders/{o['id']}/assign", json={"executor_id": ex})
    if n < 30:      # выполнены и рассчитаны
        O("POST", f"/orders/{o['id']}/status", json={"status": "done"})
        O("POST", f"/orders/{o['id']}/finance", json={"price": random.choice([600, 850, 1200, 1500, 2100, 2800]), "labor_hours": random.choice([1, 1.5, 2, 3])})
        for _ in range(random.randint(0, 2)):
            O("POST", f"/orders/{o['id']}/expenses", json={"kind": random.choice(["material", "transport", "other"]), "description": "расход", "qty": 1, "unit_cost": random.choice([60, 120, 250, 450])})
        O("POST", f"/orders/{o['id']}/settle")
        if random.random() < 0.6:
            call("POST", f"/orders/{o['id']}/rate", tok, json={"rating": random.choice([3, 4, 5, 5])})
    elif n < 36:
        O("POST", f"/orders/{o['id']}/status", json={"status": "in_progress"})
O("POST", "/payroll/adjustments", json={"user_id": ex1, "kind": "bonus", "amount": 500, "reason": "за скорость"})
O("POST", "/payroll/adjustments", json={"user_id": ex2, "kind": "fine", "amount": 200, "reason": "опоздание"})

# файлы: фото и документ к заказу, файл в чате
call("POST", f"/orders/{orders[0]}/media", c1t, files={"file": ("photo_problem.jpg", b"\xff\xd8\xff\xe0" + b"0" * 4000, "image/jpeg")})
call("POST", f"/orders/{orders[0]}/media", ex1t, files={"file": ("act.pdf", b"%PDF-1.4 demo" + b"0" * 2500, "application/pdf")})
call("POST", f"/orders/{orders[1]}/media", c2t, files={"file": ("video_problem.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 9000, "video/mp4")})
call("POST", "/chat/files", ex2t, files={"file": ("schema.pdf", b"%PDF-1.4 demo" + b"0" * 1500, "application/pdf")}, data={"text": "Схема подключения"})

# маршрут исполнителя + положение сотрудников + чат
free = [o for o in orders[36:]]
r = call("POST", "/routes", ex1t, json={"order_ids": free, "start": {"lat": 50.4501, "lon": 30.5234}}).json()
if "stops" in r and r["stops"]:
    s = r["stops"][0]
    call("POST", f"/routes/{r['id']}/arrive", ex1t, json={"order_id": s["order_id"], "lat": s["lat"], "lon": s["lon"], "accuracy": 12})
for tok, la, lo in [(ex1t, 50.447, 30.52), (ex2t, 50.43, 30.60), (headt, 50.45, 30.50), (adm, 50.46, 30.53)]:
    call("POST", "/tracking/points", tok, json={"points": [{"lat": la, "lon": lo, "accuracy": 10}]})
call("POST", "/chat", headt, json={"kind": "text", "text": "Коллеги, у кого есть сливной насос Askoll?"})
call("POST", "/chat", ex1t, json={"kind": "item", "item_id": items["Насос сливной"]})
call("POST", "/chat", ex1t, json={"kind": "location", "lat": 50.447, "lon": 30.52})
call("POST", "/chat", adm, json={"kind": "text", "text": "Отлично. Андрей, завезёшь Олегу один насос после обеда."})

# история: раскидать даты заказов по последним 6 месяцам (только при локальном запуске)
data_dir = os.getenv("DATA_DIR")
db = os.path.join(data_dir, "service.db") if data_dir else None
if db and os.path.exists(db):
    con = sqlite3.connect(db)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for i, oid in enumerate(orders):
        d = now - dt.timedelta(days=int(180 * (1 - i / len(orders))) + random.randint(0, 3), hours=random.randint(0, 9), minutes=random.randint(0, 59))
        con.execute("UPDATE orders SET created_at=?, updated_at=? WHERE id=?", (d.isoformat(sep=" "), d.isoformat(sep=" "), oid))
        con.execute("UPDATE order_pay SET created_at=? WHERE order_id=?", (d.isoformat(sep=" "), oid))
        con.execute("UPDATE transactions SET created_at=? WHERE order_id=?", (d.isoformat(sep=" "), oid))
    con.commit(); con.close()
print("Готово: демо-данные созданы")
