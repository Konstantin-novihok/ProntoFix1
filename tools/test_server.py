import os, tempfile
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["OWNER_PASSWORD"] = "ownerpass"
from fastapi.testclient import TestClient
import server
with TestClient(server.app) as c:
    def H(t): return {"Authorization": f"Bearer {t}"}
    def login(u,p): return c.post("/auth/login", json={"username":u,"password":p}).json()["token"]
    own = login("owner","ownerpass")
    base = {"username":"client1","password":"secret1","full_name":"Ivan Petrov","company_name":"ACME","website":"https://acme.ua","address":"Kyiv","lat":50.45,"lon":30.52,"passport_number":"AB123456","passport_issued":"MVS 2020"}
    assert c.post("/auth/register", json=base).status_code==400            # нет согласия
    assert c.post("/auth/register", json={**base,"consent":True,"full_name":"Ivan"}).status_code==400  # нет фамилии
    r = c.post("/auth/register", json={**base,"consent":True}); assert r.status_code==200, r.text
    assert "passport" not in str(r.json()); print("config:", c.get("/config").json())
    cl0 = r.json()["token"]
    assert c.post("/me/documents", files={"file":("x.jpg", b"GIF89a", "image/jpeg")}, headers=H(cl0)).status_code==400   # подделка типа
    d = c.post("/me/documents", files={"file":("scan.jpg", b"\xff\xd8\xff\xe0data", "image/jpeg")}, headers=H(cl0)); assert d.status_code==200, d.text
    d2 = c.post("/me/documents", files={"file":("scan.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=H(cl0)); assert d2.status_code==200
    cl = r.json()["token"]; clid = r.json()["user"]["id"]
    assert c.post("/departments", json={"name":"Washers"}, headers=H(cl)).status_code==403
    pr = c.get("/users/2/private", headers=H(own)).json(); assert pr["passport_number"]=="AB123456" and len(pr["documents"])==2, pr
    assert c.get("/users/2/private", headers=H(cl)).status_code==403
    assert c.get(f"/documents/{d.json()['id']}", headers=H(own)).content.startswith(b"\xff\xd8")
    dep = c.post("/departments", json={"name":"Washers"}, headers=H(own)).json()
    # owner creates head and executor
    head = c.post("/users", json={"username":"head1","password":"secret1","role":4}, headers=H(own)).json()
    r = c.patch(f"/departments/{dep['id']}", json={"head_id":head["id"]}, headers=H(own)); assert r.status_code==200
    ht = login("head1","secret1")
    ex = c.post("/users", json={"username":"ex1","password":"secret1","employee_no":"E-001"}, headers=H(ht)).json()
    assert ex["role"]==3 and ex["department_id"]==dep["id"]
    et = login("ex1","secret1")
    # client creates staff, staff creates order
    st = c.post("/users", json={"username":"w1","password":"secret1"}, headers=H(cl)).json(); assert st["role"]==5
    stt = login("w1","secret1")
    o = c.post("/orders", json={"title":"Washer leaks","lat":50.45,"lon":30.52,"department_id":dep["id"]}, headers=H(stt)).json()
    assert o["client_id"]==clid
    assert len(c.get("/orders", headers=H(cl)).json())==1       # client sees staff order
    assert len(c.get("/orders", headers=H(et)).json())==1       # executor sees free order in dept
    # accept
    assert c.post(f"/orders/{o['id']}/accept", headers=H(et)).json()["status"]=="accepted"
    # internal comment hidden for client
    c.post(f"/orders/{o['id']}/comments", json={"text":"secret","public":False}, headers=H(et))
    c.post(f"/orders/{o['id']}/comments", json={"text":"hello client","public":True}, headers=H(et))
    assert len(c.get(f"/orders/{o['id']}", headers=H(cl)).json()["comments"])==1
    assert len(c.get(f"/orders/{o['id']}", headers=H(et)).json()["comments"])==2
    assert c.post(f"/orders/{o['id']}/estimate", json={"hours":2,"price":50}, headers=H(et)).json()["status"]=="estimate"
    # media
    r = c.post(f"/orders/{o['id']}/media", files={"file":("a.jpg", b"xx", "image/jpeg")}, headers=H(stt)); assert r.status_code==200, r.text
    assert c.get(f"/media/{r.json()['id']}?token={cl}").content==b"xx"
    assert c.post(f"/orders/{o['id']}/media", files={"file":("a.exe", b"xx", "application/x-msdownload")}, headers=H(stt)).status_code==400
    c.post(f"/orders/{o['id']}/status", json={"status":"done"}, headers=H(et))
    assert c.post(f"/orders/{o['id']}/rate", json={"rating":5}, headers=H(cl)).json()["rating"]==5
    # outsider client can't see
    c.post("/auth/register", json={"username":"client2","password":"secret1","full_name":"Petr Ivanov","consent":True})
    c2 = login("client2","secret1")
    assert c.get(f"/orders/{o['id']}", headers=H(c2)).status_code==404
    # role change only owner; last owner protected
    assert c.patch(f"/users/{ex['id']}", json={"role":1}, headers=H(ht)).status_code==403
    assert c.patch("/users/1", json={"role":4}, headers=H(own)).status_code==400
    assert c.patch(f"/users/{ex['id']}", json={"role":6}, headers=H(own)).json()["role"]==6
    a = c.get("/audit", headers=H(own)).json(); print(len(a), "audit rows;", sorted({x['action'] for x in a}))
    assert c.get("/audit", headers=H(cl)).status_code==403
    print("ALL OK")
