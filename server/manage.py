"""
Служебные команды сервера (запускаются на самом NAS, в jail:  prontofix-manage <команда>).

  list-users                      список пользователей
  reset-password ЛОГИН [ПАРОЛЬ]   задать новый пароль (если пароль не указан — спросит; минимум 6 символов)
  set-role ЛОГИН НОМЕР_РОЛИ       выдать роль (1..6). Нужна, если потеряли доступ владельца
  activate ЛОГИН                  снова включить отключённого пользователя
  backup [ПАПКА]                  резервная копия: база + фото/видео + документы + ключи/настройки (tar.gz)
  check                           краткая сводка: пользователи, заказы, размер данных

Команды работают напрямую с базой и пишутся в журнал (audit) как действие «cli».
"""
import getpass
import os
import sqlite3
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Если задан PRONTOFIX_CONF (его ставит команда prontofix-manage) — берём настройки из prontofix.conf (строки ИМЯ=значение)
_conf = os.getenv("PRONTOFIX_CONF")
if _conf and os.path.exists(_conf):
    with open(_conf, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and _line[0].isupper() and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import server as S                      # те же настройки (DATA_DIR, DATABASE_URL...), что у работающего сервера
from sqlalchemy import func, select

S.Base.metadata.create_all(S.engine)     # если сервер ещё ни разу не запускался — создаём таблицы
S.ensure_columns()


def find_user(db, username):
    u = db.scalar(select(S.User).where(S.User.username == username.lower()))
    if not u:
        sys.exit(f"Пользователь '{username}' не найден")
    return u


def cmd_list_users():
    with S.SessionLocal() as db:
        for u in db.scalars(select(S.User).order_by(S.User.id)):
            print(f"{u.id:4}  {u.username:20}  роль {u.role}  {'активен' if u.is_active else 'ОТКЛЮЧЁН'}  {u.full_name}")


def cmd_reset_password(username, password=None):
    if password is None:
        password = getpass.getpass("Новый пароль: ")
        if password != getpass.getpass("Повторите пароль: "):
            sys.exit("Пароли не совпали")
    if len(password) < 6:
        sys.exit("Пароль должен быть не короче 6 символов")
    with S.SessionLocal() as db:
        u = find_user(db, username)
        u.password_hash = S.hash_password(password)
        S.log(db, None, "cli_reset_password", "user", u.id, username)
        db.commit()
    print("Пароль изменён для", username)


def cmd_set_role(username, role):
    role = int(role)
    if role not in range(1, 7):
        sys.exit("Роль: число от 1 до 6")
    with S.SessionLocal() as db:
        u = find_user(db, username)
        S.log(db, None, "cli_change_role", "user", u.id, f"{u.role}->{role}")
        u.role, u.is_active = role, True
        db.commit()
    print(f"{username}: роль {role}, учётная запись включена")


def cmd_activate(username):
    with S.SessionLocal() as db:
        u = find_user(db, username)
        u.is_active = True
        S.log(db, None, "cli_activate", "user", u.id)
        db.commit()
    print(username, "включён")


def cmd_backup(dest=None):
    dest = dest or os.path.join(S.DATA_DIR, "backups")
    os.makedirs(dest, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(dest, f"prontofix_{stamp}.tar.gz")
    db_path = os.path.join(S.DATA_DIR, "service.db")
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        if S.DB_URL.startswith("sqlite") and os.path.exists(db_path):
            copy = os.path.join(tmp, "service.db")          # согласованная копия, даже если сервер работает
            src, dst = sqlite3.connect(db_path), sqlite3.connect(copy)
            src.backup(dst)
            src.close(); dst.close()
            tar.add(copy, arcname="service.db")
        else:
            print("ВНИМАНИЕ: база не SQLite — сделайте её дамп средствами вашей СУБД")
        for name in ("media", "docs", "secret.key"):
            p = os.path.join(S.DATA_DIR, name)
            if os.path.exists(p):
                tar.add(p, arcname=name)
        conf = os.getenv("PRONTOFIX_CONF")
        if conf and os.path.exists(conf):
            tar.add(conf, arcname="prontofix.conf")     # в нём SECRET_KEY: без него паспорта не расшифровать
        elif os.getenv("SECRET_KEY"):
            print("ВНИМАНИЕ: ключ задан переменной окружения SECRET_KEY — сохраните его отдельно!")
    print("Резервная копия:", out, f"({os.path.getsize(out) / 1024 / 1024:.1f} МБ)")


def cmd_check():
    with S.SessionLocal() as db:
        users = db.scalar(select(func.count()).select_from(S.User))
        orders = db.scalar(select(func.count()).select_from(S.Order))
        docs = db.scalar(select(func.count()).select_from(S.UserDoc))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(S.DATA_DIR) for f in fs)
    print(f"Данные: {S.DATA_DIR}  ({size / 1024 / 1024:.1f} МБ)\nПользователей: {users}, заказов: {orders}, документов: {docs}")


COMMANDS = {"list-users": cmd_list_users, "reset-password": cmd_reset_password, "set-role": cmd_set_role,
            "activate": cmd_activate, "backup": cmd_backup, "check": cmd_check}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    try:
        COMMANDS[sys.argv[1]](*sys.argv[2:])
    except TypeError:
        print("Неверные аргументы.\n" + __doc__)
        sys.exit(1)
